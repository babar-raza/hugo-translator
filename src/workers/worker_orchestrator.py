"""Worker Orchestrator — trigger-based launcher for oneshot workers.

Replaces blind periodic scheduling with intelligent trigger evaluation.
Workers are launched as separate subprocesses; no worker code is imported.

Usage::

    python -m src.workers.worker_orchestrator --once
    python -m src.workers.worker_orchestrator --check-interval 900
    python -m src.workers.worker_orchestrator --dry-run
    python -m src.workers.worker_orchestrator --config config/workers.yaml
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.utils.config_loader import load_worker_registry
from src.workers.queue_probes import (
    config_changed_since,
    content_repo_has_changes,
    file_exists,
    queue_has_entries,
    worker_pid_alive,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_MAX_LAUNCHES_PER_HOUR = 5
_STATE_FILE = Path("data/logs/orchestrator.state.json")
_EVENT_LOG = Path("data/logs/worker_events.jsonl")


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

def _load_state() -> dict[str, Any]:
    if _STATE_FILE.exists():
        try:
            return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_state(state: dict[str, Any]) -> None:
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True, default=str), encoding="utf-8")
    tmp.replace(_STATE_FILE)


def _append_event(event: dict[str, Any]) -> None:
    _EVENT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(_EVENT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, default=str) + "\n")


# ---------------------------------------------------------------------------
# Trigger evaluation
# ---------------------------------------------------------------------------

def evaluate_trigger(trigger: dict[str, Any], state: dict[str, Any]) -> bool:
    """Return True if the trigger condition is met.  Never raises."""
    try:
        return _eval(trigger, state)
    except Exception as exc:
        logger.warning("Trigger evaluation error: %s", exc)
        return False


def _eval(trigger: dict[str, Any], state: dict[str, Any]) -> bool:
    ttype = trigger.get("type")

    if ttype == "queue_non_empty":
        path = _expand_env(trigger.get("queue_path", ""))
        return queue_has_entries(path)

    if ttype == "file_change":
        since = state.get("last_check_time", 0.0)
        paths = trigger.get("paths", [])
        pattern = trigger.get("pattern", "*")
        for p in paths:
            p = _expand_env(p)
            if not Path(p).exists():
                continue
            if pattern == "*.yaml":
                if config_changed_since(p, since):
                    return True
            else:
                if content_repo_has_changes(p, since):
                    return True
        return False

    if ttype == "worker_completed":
        target = trigger.get("worker", "")
        completed_workers = state.get("recently_completed_workers", [])
        return target in completed_workers

    if ttype == "multi":
        conditions = trigger.get("conditions", [])
        return any(_eval(c, state) for c in conditions)

    logger.warning("Unknown trigger type: %s", ttype)
    return False


def _expand_env(s: str) -> str:
    """Expand ``${VAR}`` placeholders from environment."""
    if "${" not in s:
        return s
    import re
    return re.sub(r"\$\{(\w+)\}", lambda m: os.environ.get(m.group(1), m.group(0)), s)


# ---------------------------------------------------------------------------
# Launch logic
# ---------------------------------------------------------------------------

def should_launch(
    name: str,
    cfg: dict[str, Any],
    state: dict[str, Any],
    now: float | None = None,
) -> tuple[bool, str]:
    """Decide whether to launch *name*.  Returns (ok, reason)."""
    now = now or time.time()

    if not cfg.get("enabled", True):
        return False, "disabled"

    # Campaign sentinel
    sentinel = cfg.get("campaign_sentinel")
    if sentinel and file_exists(sentinel):
        return False, f"campaign sentinel active: {sentinel}"

    # PID alive check
    pid_file = Path("data/logs") / f"{name.replace('_worker', '_worker')}.pid"
    # Try common patterns
    for candidate in [
        Path("data/logs") / f"{name}.pid",
        Path("data/logs") / f"{name.replace('_worker', '')}_worker.pid",
    ]:
        if candidate.exists():
            pid_file = candidate
            break
    if worker_pid_alive(pid_file):
        return False, f"worker already running (PID file: {pid_file})"

    # Cooldown
    last_launch = state.get("last_launch", {}).get(name, 0.0)
    cooldown = cfg.get("cooldown_seconds", 0)
    if now - last_launch < cooldown:
        remaining = int(cooldown - (now - last_launch))
        return False, f"cooldown ({remaining}s remaining)"

    # Circuit breaker
    launches = state.get("launch_history", [])
    hour_ago = now - 3600
    recent = [ts for ts in launches if ts > hour_ago]
    if len(recent) >= _MAX_LAUNCHES_PER_HOUR:
        return False, f"circuit breaker: {len(recent)} launches in last hour"

    # Max concurrent
    max_conc = cfg.get("max_concurrent", 1)
    running = state.get("running_count", {}).get(name, 0)
    if running >= max_conc:
        return False, f"max_concurrent ({max_conc}) reached"

    # Evaluate trigger
    if not evaluate_trigger(cfg.get("trigger", {}), state):
        return False, "no trigger fired"

    return True, "trigger fired"


def launch_worker(
    name: str,
    cfg: dict[str, Any],
    state: dict[str, Any],
    dry_run: bool = False,
) -> bool:
    """Launch *name* as a subprocess.  Returns True on success."""
    cmd = cfg.get("safe_command", "")
    if not cmd:
        logger.error("Worker %s has no safe_command", name)
        return False

    parts = cmd.split()
    now = time.time()

    if dry_run:
        logger.info("[DRY-RUN] Would launch %s: %s", name, cmd)
        _append_event({
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": "dry_run_launch",
            "worker": name,
            "command": cmd,
        })
        return True

    logger.info("Launching %s: %s", name, cmd)
    try:
        proc = subprocess.Popen(
            parts,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        logger.info("Launched %s as PID %d", name, proc.pid)

        # Update state
        state.setdefault("last_launch", {})[name] = now
        state.setdefault("launch_history", []).append(now)
        # Prune old history
        hour_ago = now - 3600
        state["launch_history"] = [t for t in state["launch_history"] if t > hour_ago]

        _append_event({
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": "worker_launched",
            "worker": name,
            "pid": proc.pid,
            "command": cmd,
        })
        return True
    except Exception as exc:
        logger.error("Failed to launch %s: %s", name, exc)
        _append_event({
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": "launch_failed",
            "worker": name,
            "error": str(exc),
        })
        return False


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run_check_cycle(
    registry: dict[str, Any],
    state: dict[str, Any],
    dry_run: bool = False,
) -> list[str]:
    """Evaluate all workers and launch those with active triggers.

    Returns list of worker names that were launched (or would be in dry-run).
    """
    workers = registry.get("workers", {})
    launched: list[str] = []

    for name, cfg in workers.items():
        ok, reason = should_launch(name, cfg, state, time.time())
        if ok:
            success = launch_worker(name, cfg, state, dry_run=dry_run)
            if success:
                launched.append(name)
                logger.info("Worker %s: launched (%s)", name, reason)
        else:
            logger.debug("Worker %s: skipped (%s)", name, reason)

    if not launched:
        logger.info("No work available — all triggers inactive")
        _append_event({
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": "no_work_available",
        })

    # Mark completed workers for next cycle's worker_completed triggers
    state["recently_completed_workers"] = launched
    state["last_check_time"] = time.time()

    return launched


def main() -> None:
    parser = argparse.ArgumentParser(description="Worker orchestrator")
    parser.add_argument("--config", default="config/workers.yaml",
                        help="Path to worker registry YAML")
    parser.add_argument("--check-interval", type=int, default=900,
                        help="Seconds between check cycles (default: 900)")
    parser.add_argument("--once", action="store_true",
                        help="Run one check cycle and exit")
    parser.add_argument("--dry-run", action="store_true",
                        help="Evaluate triggers but do not launch workers")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(name)s [%(levelname)s] %(message)s",
    )

    registry = load_worker_registry(args.config)
    state = _load_state()

    if args.once:
        launched = run_check_cycle(registry, state, dry_run=args.dry_run)
        _save_state(state)
        if launched:
            logger.info("Launched workers: %s", ", ".join(launched))
        sys.exit(0)

    # Daemon loop
    logger.info("Orchestrator starting (check-interval=%ds, dry-run=%s)",
                args.check_interval, args.dry_run)
    try:
        while True:
            launched = run_check_cycle(registry, state, dry_run=args.dry_run)
            _save_state(state)
            if launched:
                logger.info("Launched workers: %s", ", ".join(launched))
            time.sleep(args.check_interval)
    except KeyboardInterrupt:
        logger.info("Orchestrator stopped by user")
        _save_state(state)


if __name__ == "__main__":
    main()
