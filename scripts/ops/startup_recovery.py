"""System-startup recovery: relaunches all long-running infrastructure that
should survive a reboot but doesn't auto-resume on its own.

Found 2026-07-19: the existing "HugoTranslatorGitlab-Orchestrator" scheduled
task (logon trigger, meant to keep worker_orchestrator.py alive) pointed at
a 2-week-stale sibling clone (hugo-translator-gitlab, last touched 2026-07-04)
instead of this repo -- silently failing (ERROR_FILE_NOT_FOUND) on every
logon since. Combined with .local/scheduler.py and thermal_watchdog.py having
no recovery mechanism at all, three separate multi-hour-to-13-hour outages
happened this session alone (2026-07-17, 2026-07-18 x2) with nothing
resuming until manually noticed and relaunched.

This script is idempotent -- safe to run repeatedly (e.g. from a scheduled
task's logon trigger, or manually). It only launches a component if no live,
correctly-identified process for it already exists.

Update the scheduled task to point here instead of directly at
worker_orchestrator, so both the production worker system AND the ad-hoc
GPU heal campaign infrastructure recover together on every reboot.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parent.parent.parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"
LOCAL = ROOT / ".local"


def _is_alive(script_hint: str) -> bool:
    """True if a live python.exe process's cmdline contains script_hint.
    Restricted to python.exe processes specifically -- a plain substring
    match against every process (including this session's own bash wrapper
    shells, which can carry long inline scripts) produces false positives."""
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            name = (p.info["name"] or "").lower()
            if "python" not in name:
                continue
            cmdline = " ".join(p.info["cmdline"] or [])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if script_hint in cmdline:
            return True
    return False


def _launch(args: list[str], cwd: Path, log_stem: str) -> int:
    out = (LOCAL / f"{log_stem}.out").open("a", encoding="utf-8")
    err = (LOCAL / f"{log_stem}.err").open("a", encoding="utf-8")
    proc = subprocess.Popen(
        args, cwd=str(cwd), stdout=out, stderr=err,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    return proc.pid


def main() -> None:
    print(f"[startup_recovery] anchored to {ROOT}")

    # 1. worker_orchestrator.py -- production worker registry (content_worker,
    #    tm_improvement_worker, verification_worker). Persistent daemon loop
    #    (--check-interval), not oneshot -- one live instance is sufficient.
    if _is_alive("worker_orchestrator"):
        print("[startup_recovery] worker_orchestrator already running, skipping")
    else:
        (ROOT / "data" / "logs").mkdir(parents=True, exist_ok=True)
        pid = _launch(
            [str(PY), "-m", "src.workers.worker_orchestrator",
             "--check-interval", "900", "--log-level", "INFO",
             "--log-file", "data/logs/orchestrator_daemon.log"],
            ROOT, "orchestrator_daemon",
        )
        print(f"[startup_recovery] launched worker_orchestrator, PID {pid}")

    # 2. .local/scheduler.py -- ad-hoc GPU heal campaign dispatcher (D56).
    if _is_alive("scheduler.py"):
        print("[startup_recovery] scheduler.py already running, skipping")
    else:
        pid = _launch([str(PY), str(LOCAL / "scheduler.py")], ROOT, "scheduler")
        print(f"[startup_recovery] launched scheduler.py, PID {pid}")

    # 3. thermal_watchdog.py -- GPU thermal safety net for the heal campaign.
    if _is_alive("thermal_watchdog.py"):
        print("[startup_recovery] thermal_watchdog.py already running, skipping")
    else:
        pid = _launch(
            [str(PY), str(ROOT / "scripts" / "quality" / "thermal_watchdog.py")],
            ROOT, "thermal_watchdog",
        )
        print(f"[startup_recovery] launched thermal_watchdog.py, PID {pid}")


if __name__ == "__main__":
    main()
