"""Read-only probe functions for the worker orchestrator.

Every probe is side-effect-free and fault-tolerant: missing files return
``False`` / ``0``, malformed lines are skipped.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Queue probes
# ---------------------------------------------------------------------------

def queue_has_entries(path: str | Path) -> bool:
    """Return True if the JSONL queue file has at least one parseable entry."""
    return queue_entry_count(path) > 0


def queue_entry_count(path: str | Path) -> int:
    """Count parseable JSONL entries in *path*.  Malformed lines are skipped."""
    p = Path(path)
    if not p.exists():
        return 0
    count = 0
    try:
        with p.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    json.loads(line)
                    count += 1
                except json.JSONDecodeError:
                    logger.warning("Malformed JSONL line in %s: %s", p, line[:120])
    except Exception as exc:
        logger.warning("Failed to read queue %s: %s", p, exc)
    return count


# ---------------------------------------------------------------------------
# File-change probes
# ---------------------------------------------------------------------------

def content_repo_has_changes(repo_path: str | Path, since_mtime: float) -> bool:
    """Return True if any ``.md`` file under *repo_path* was modified after *since_mtime*."""
    return _any_file_newer(repo_path, since_mtime, "*.md")


def config_changed_since(config_dir: str | Path, since_mtime: float) -> bool:
    """Return True if any ``.yaml`` file under *config_dir* was modified after *since_mtime*."""
    return _any_file_newer(config_dir, since_mtime, "*.yaml")


def _any_file_newer(root: str | Path, since_mtime: float, pattern: str) -> bool:
    root = Path(root)
    if not root.exists():
        return False
    try:
        for p in root.rglob(pattern):
            if p.is_file() and p.stat().st_mtime > since_mtime:
                return True
    except Exception as exc:
        logger.warning("Error scanning %s: %s", root, exc)
    return False


# ---------------------------------------------------------------------------
# Utility probes
# ---------------------------------------------------------------------------

def file_exists(path: str | Path) -> bool:
    """Return True if *path* exists on disk."""
    return Path(path).exists()


def state_file_recent(path: str | Path, max_age_seconds: int) -> bool:
    """Return True if *path* exists and was modified within *max_age_seconds*."""
    p = Path(path)
    if not p.exists():
        return False
    try:
        import time
        age = time.time() - p.stat().st_mtime
        return age <= max_age_seconds
    except Exception:
        return False


def worker_pid_alive(pid_file: str | Path) -> bool:
    """Return True if the PID recorded in *pid_file* corresponds to a running process."""
    p = Path(pid_file)
    if not p.exists():
        return False
    try:
        pid = int(p.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return False
    return _is_pid_alive(pid)


def _is_pid_alive(pid: int) -> bool:
    """Platform-safe check for process liveness."""
    if platform.system() == "Windows":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True, timeout=5,
            )
            return str(pid) in result.stdout
        except Exception:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False
