#!/usr/bin/env python3
"""
Wait for bg worker to finish, then launch ca,cs worker.
Run this now alongside the already-running bg/da,de workers.
"""
from __future__ import annotations
import subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYTHON = str(ROOT / ".venv" / "Scripts" / "python.exe")
WORKER = str(ROOT / "scripts" / "quality" / "reference_inprocess_worker.py")
LOG_DIR = ROOT / "data" / "logs"
BG_LOG  = LOG_DIR / "reference_inprocess_bg.log"

def log_is_done(log_path: Path) -> bool:
    """Return True if the worker log shows 'Run complete' or hasn't been written in 120s."""
    if not log_path.exists():
        return False
    # Check content
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
        if "Run complete" in text or "Nothing to do" in text:
            return True
    except Exception:
        pass
    # Check staleness
    import os
    age = time.time() - os.path.getmtime(log_path)
    return age > 120  # 2 min idle = done

print(f"[{time.strftime('%H:%M:%S')}] Waiting for bg worker to finish (monitoring {BG_LOG.name})")
while not log_is_done(BG_LOG):
    time.sleep(30)
    import os
    age = time.time() - os.path.getmtime(BG_LOG) if BG_LOG.exists() else 999
    print(f"[{time.strftime('%H:%M:%S')}] bg log age={age:.0f}s, still running...", flush=True)

print(f"[{time.strftime('%H:%M:%S')}] bg done. Launching ca,cs worker...")

log_path = LOG_DIR / "reference_inprocess_ca_cs.log"
with open(log_path, "a", encoding="utf-8") as lf:
    proc = subprocess.Popen(
        [PYTHON, WORKER, "--locales", "ca,cs", "--shard-id", "inproc-ca-cs", "--retry-failed", "--resume"],
        stdout=lf, stderr=lf, cwd=ROOT,
    )
print(f"[{time.strftime('%H:%M:%S')}] ca,cs worker PID={proc.pid}, waiting...")
proc.wait()
print(f"[{time.strftime('%H:%M:%S')}] ca,cs done (exit={proc.returncode})")
