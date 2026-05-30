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

try:
    from dotenv import load_dotenv as _load_dotenv
    _HAVE_DOTENV = True
except ImportError:
    _HAVE_DOTENV = False

from src.utils.config_loader import load_worker_registry
from src.workers.queue_probes import (
    config_changed_since,
    content_repo_has_changes,
    file_exists,
    queue_has_entries,
    worker_pid_alive,
)

logger = logging.getLogger(__name__)

# Tracks unresolved env var paths already warned about to avoid log spam.
_warned_unresolved_paths: set[str] = set()

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
            if "${" in p:
                if p not in _warned_unresolved_paths:
                    _warned_unresolved_paths.add(p)
                    logger.warning(
                        "file_change trigger path contains unresolved env var: %r — "
                        "set the environment variable or remove this path from workers.yaml",
                        p,
                    )
                continue
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
        completed_workers = state.get("recently_launched_workers", [])
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

    # PID alive check — auto-clean stale files
    pid_name = cfg.get("pid_file_name", name)
    pid_file = Path("data/logs") / f"{pid_name}.pid"
    if pid_file.exists():
        if worker_pid_alive(pid_file):
            return False, f"worker already running (PID file: {pid_file})"
        else:
            # Stale PID file — process is dead, clean up so we don't block forever
            try:
                stale_pid = pid_file.read_text(encoding="utf-8").strip()
                pid_file.unlink(missing_ok=True)
                logger.info("Worker %s: removed stale PID file %s (dead PID %s)", name, pid_file, stale_pid)
            except OSError as exc:
                logger.warning("Worker %s: could not remove stale PID file %s: %s", name, pid_file, exc)
            # Update state file so it no longer shows "starting" after a crash
            try:
                from src.workers.worker_state import load_worker_state, record_worker_state
                ws = load_worker_state(name)
                if ws.get("state") not in ("stopped", ""):
                    record_worker_state(name, "stopped",
                                       error="process found dead on orchestrator startup check")
                    logger.info("Worker %s: state file updated to stopped (dead process cleanup)", name)
            except Exception as _exc:
                logger.debug("Worker %s: could not update state file: %s", name, _exc)

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
    # On Windows, Popen with shell=False does not resolve relative executable
    # paths against CWD.  Resolve to absolute so CreateProcess can find it.
    if parts:
        exe = Path(parts[0])
        if not exe.is_absolute() and exe.exists():
            parts[0] = str(exe.resolve())
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
            logger.info("Worker %s: skipped (%s)", name, reason)

    if not launched:
        logger.info("No workers launched this cycle")
        _append_event({
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": "no_work_available",
        })

    # Mark completed workers for next cycle's worker_completed triggers
    state["recently_launched_workers"] = launched
    state["last_check_time"] = time.time()

    return launched


def print_status(
    registry: dict[str, Any],
    state: dict[str, Any],
    *,
    as_json: bool = False,
) -> dict[str, Any]:
    """Print a human-readable (or JSON) status report of all workers.

    Returns the status payload dict.
    """
    from src.workers.worker_state import _is_process_alive, load_worker_state

    workers = registry.get("workers", {})
    now = time.time()
    report: dict[str, Any] = {"timestamp": datetime.now(timezone.utc).isoformat(), "workers": {}}

    for name, cfg in workers.items():
        w: dict[str, Any] = {"enabled": cfg.get("enabled", True)}

        # PID alive check — respect pid_file_name override from workers.yaml
        pid_name = cfg.get("pid_file_name", name)
        pid_file_candidate = Path("data/logs") / f"{pid_name}.pid"
        pid_file = pid_file_candidate if pid_file_candidate.exists() else None
        if pid_file and pid_file.exists():
            try:
                pid = int(pid_file.read_text(encoding="utf-8").strip())
                w["pid"] = pid
                w["pid_alive"] = _is_process_alive(pid)
            except (ValueError, OSError):
                w["pid_alive"] = False
        else:
            w["pid_alive"] = False

        # Last launch + cooldown
        last_launch = state.get("last_launch", {}).get(name, 0.0)
        cooldown = cfg.get("cooldown_seconds", 0)
        if last_launch > 0:
            w["last_launch"] = datetime.fromtimestamp(last_launch, tz=timezone.utc).isoformat()
            remaining = max(0, int(cooldown - (now - last_launch)))
            w["cooldown_remaining_s"] = remaining
        else:
            w["last_launch"] = None
            w["cooldown_remaining_s"] = 0

        # Campaign sentinel
        sentinel = cfg.get("campaign_sentinel")
        if sentinel and Path(sentinel).exists():
            w["campaign_sentinel"] = True
        else:
            w["campaign_sentinel"] = False

        # Trigger evaluation (safe)
        try:
            w["trigger_active"] = evaluate_trigger(cfg.get("trigger", {}), state)
        except Exception:
            w["trigger_active"] = False

        # Worker state file
        ws = load_worker_state(name)
        if ws:
            w["state"] = ws.get("state")
            w["last_success"] = ws.get("last_success_ts")
            w["last_error"] = ws.get("last_error_ts")

        report["workers"][name] = w

    # Queue depths
    queues: dict[str, int] = {}
    for qpath in ["data/retranslate_queue.jsonl", "data/quarantine.jsonl", "data/tm/improvement_queue.jsonl"]:
        p = Path(qpath)
        if p.exists():
            try:
                queues[qpath] = sum(1 for _ in p.open(encoding="utf-8"))
            except OSError:
                queues[qpath] = -1
    report["queues"] = queues

    # Circuit breaker
    launches = state.get("launch_history", [])
    hour_ago = now - 3600
    recent = [ts for ts in launches if ts > hour_ago]
    report["circuit_breaker"] = {
        "launches_last_hour": len(recent),
        "max_per_hour": _MAX_LAUNCHES_PER_HOUR,
        "open": len(recent) >= _MAX_LAUNCHES_PER_HOUR,
    }

    if as_json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"=== Orchestrator Status ({report['timestamp']}) ===\n")
        for name, w in report["workers"].items():
            alive = "ALIVE" if w.get("pid_alive") else "DEAD"
            pid_str = f"PID {w['pid']}" if "pid" in w else "no PID file"
            enabled = "enabled" if w.get("enabled") else "DISABLED"
            trigger = "ACTIVE" if w.get("trigger_active") else "inactive"
            campaign = " [CAMPAIGN]" if w.get("campaign_sentinel") else ""
            cooldown = f" cooldown={w['cooldown_remaining_s']}s" if w.get("cooldown_remaining_s", 0) > 0 else ""
            state_str = w.get("state", "unknown")
            print(f"  {name}: {alive} ({pid_str}) {enabled} trigger={trigger}{campaign}{cooldown} state={state_str}")
        print()
        for qpath, depth in report.get("queues", {}).items():
            print(f"  Queue {qpath}: {depth} entries")
        cb = report["circuit_breaker"]
        print(f"\n  Circuit breaker: {cb['launches_last_hour']}/{cb['max_per_hour']} launches/hour"
              f" ({'OPEN' if cb['open'] else 'closed'})")

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Worker orchestrator")
    parser.add_argument("--config", default="config/workers.yaml",
                        help="Path to worker registry YAML")
    parser.add_argument("--check-interval", type=int, default=900,
                        help="Seconds between check cycles (default: 900)")
    parser.add_argument("--once", action="store_true",
                        help="Run one check cycle and exit")
    parser.add_argument("--status", action="store_true",
                        help="Print worker status and exit")
    parser.add_argument("--json", action="store_true",
                        help="Output status as JSON (use with --status)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Evaluate triggers but do not launch workers")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--log-file", default=None,
                        help="Append log output to this file in addition to stderr")
    args = parser.parse_args()

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if args.log_file:
        Path(args.log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(args.log_file, encoding="utf-8"))
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(name)s [%(levelname)s] %(message)s",
        handlers=handlers,
    )

    # Load .env so ASPOSE_NET_CONTENT / ASPOSE_ORG_CONTENT enter os.environ
    # and are inherited by all subprocess workers launched by this orchestrator.
    if _HAVE_DOTENV:
        _env_file = Path(__file__).resolve().parent.parent.parent / ".env"
        if _env_file.exists():
            _load_dotenv(_env_file, override=False)
            logger.info("Loaded environment from %s", _env_file)
    else:
        logger.warning("python-dotenv not installed — .env file not loaded")

    for _var in ("ASPOSE_NET_CONTENT", "ASPOSE_ORG_CONTENT"):
        if not os.environ.get(_var):
            logger.warning(
                "Required env var %s is not set — content_worker will skip all sites. "
                "Add it to .env",
                _var,
            )

    # Anchor CWD to project root regardless of how the orchestrator was launched.
    # All worker file paths (queues, state, PID files) are relative to the project root.
    _project_root = Path(__file__).resolve().parent.parent.parent
    os.chdir(_project_root)
    logger.info("Working directory anchored to: %s", _project_root)

    registry = load_worker_registry(args.config)
    state = _load_state()

    if args.status:
        print_status(registry, state, as_json=args.json)
        sys.exit(0)

    if args.once:
        launched = run_check_cycle(registry, state, dry_run=args.dry_run)
        _save_state(state)
        if launched:
            logger.info("Launched workers: %s", ", ".join(launched))
        sys.exit(0)

    # Daemon loop
    logger.info("Orchestrator starting (check-interval=%ds, dry-run=%s)",
                args.check_interval, args.dry_run)
    while True:
        try:
            launched = run_check_cycle(registry, state, dry_run=args.dry_run)
            _save_state(state)
            if launched:
                logger.info("Launched workers: %s", ", ".join(launched))
        except KeyboardInterrupt:
            logger.info("Orchestrator stopped by user")
            _save_state(state)
            sys.exit(0)
        except Exception as exc:
            logger.error(
                "Unhandled error in check cycle — retrying in 60s: %s", exc, exc_info=True
            )
            _append_event({
                "ts": datetime.now(timezone.utc).isoformat(),
                "event": "cycle_error",
                "error": str(exc),
            })
            time.sleep(60)
        time.sleep(args.check_interval)


if __name__ == "__main__":
    main()
