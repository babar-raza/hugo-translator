"""TC-APT-088: commit to a repo (typically the content repo) as a real
OS-detached subprocess, so a hook suite that can exceed the harness's ~120s
tool timeout never gets interrupted mid-commit.

Found 2026-09-06: the content repo's 40-step hook suite exceeds the 120s
harness tool timeout once a commit carries ~7+ files (a 1-file commit fit
inside it). Interrupting a commit mid-hook risks a partial index and a stale
`index.lock`, so the runbook forbids it (plan §1 hard limit: never span a
wake boundary with a harness-level background task; anything that must
outlive an iteration runs as a real OS-detached subprocess). This formalizes
the ad hoc `Popen(DETACHED)` pattern campaigns already use for the same
reason (`scripts/campaign/launch_parallel_campaign_shards.py`) instead of
re-deriving it by hand at commit time.

Usage:
    launch(repo, message_path) -> {"pid": ..., "started_at": ..., "log_path": ...,
                                    "head_before": ...}
    check_status(repo, pid, head_before) -> {"process_alive": bool,
                                              "head_moved": bool, "new_head": str | None}

Never calls `git add` or any governance CLI (skill_run_manager.py,
session_ledger.py, path_guard.py, override_manager.py) -- those must already
have run and staged exactly the receipt-listed paths before this launches.
This only detaches the `git commit` step itself, which is the one that can
outlive the harness timeout.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_CREATE_NO_WINDOW = 0x08000000
_DETACHED_PROCESS = 0x00000008
_CREATE_NEW_PROCESS_GROUP = 0x00000200


def _is_process_alive(pid: int) -> bool:
    """Cross-platform liveness check. Same approach as
    `FileLock._is_process_alive` (tasklist grep on Windows, signal-0 on Unix)
    reimplemented as a plain function here -- that method isn't a
    staticmethod, and instantiating a bare FileLock just to reach it left a
    dangling object with no `_locked` attribute, which raised in `__del__`
    on garbage collection."""
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True, text=True, timeout=5,
            )
            return str(pid) in result.stdout
        except Exception:
            return False
    else:
        import os
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def _git_head(repo: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def launch(
    repo: Path,
    message_path: Path,
    *,
    log_path: Path | None = None,
    extra_args: list[str] | None = None,
) -> dict[str, Any]:
    """Launch `git commit -F <message_path>` detached; returns immediately.

    The caller must have already staged exactly the intended files. Records
    `head_before` so a later check_status() call can tell whether the commit
    actually landed.
    """
    repo = Path(repo).resolve()
    log_path = Path(log_path) if log_path else repo / ".git" / "detached-commit.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    head_before = _git_head(repo)

    command = ["git", "commit", "-F", str(Path(message_path).resolve())]
    command.extend(extra_args or [])

    flags = 0
    if sys.platform == "win32":
        flags = _DETACHED_PROCESS | _CREATE_NEW_PROCESS_GROUP | _CREATE_NO_WINDOW
    popen_kwargs: dict[str, Any] = {"cwd": str(repo), "creationflags": flags}
    if sys.platform != "win32":
        popen_kwargs["start_new_session"] = True

    with log_path.open("w", encoding="utf-8") as handle:
        process = subprocess.Popen(command, stdout=handle, stderr=subprocess.STDOUT, **popen_kwargs)

    return {
        "pid": process.pid,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "log_path": str(log_path),
        "head_before": head_before,
        "repo": str(repo),
    }


def check_status(repo: Path, pid: int, head_before: str) -> dict[str, Any]:
    """Check a launched commit without blocking. Never kills the process --
    the runbook forbids interrupting a commit mid-hook (risks a partial index
    and a stale index.lock)."""
    repo = Path(repo).resolve()
    process_alive = _is_process_alive(pid)
    new_head = _git_head(repo)
    head_moved = new_head != head_before
    lock_file = repo / ".git" / "index.lock"
    return {
        "process_alive": process_alive,
        "head_moved": head_moved,
        "new_head": new_head if head_moved else None,
        "index_lock_present": lock_file.exists(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)

    launch_p = sub.add_parser("launch")
    launch_p.add_argument("--repo", required=True, type=Path)
    launch_p.add_argument("--message-file", required=True, type=Path)
    launch_p.add_argument("--log-path", type=Path, default=None)
    launch_p.add_argument("--extra-arg", action="append", default=[])
    launch_p.add_argument("--state-out", type=Path, required=True, help="Where to write the launch state JSON")

    check_p = sub.add_parser("check")
    check_p.add_argument("--repo", required=True, type=Path)
    check_p.add_argument("--pid", required=True, type=int)
    check_p.add_argument("--head-before", required=True)

    args = parser.parse_args(argv)

    if args.action == "launch":
        state = launch(args.repo, args.message_file, log_path=args.log_path, extra_args=args.extra_arg)
        args.state_out.parent.mkdir(parents=True, exist_ok=True)
        args.state_out.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(state, indent=2))
    else:
        status = check_status(args.repo, args.pid, args.head_before)
        print(json.dumps(status, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
