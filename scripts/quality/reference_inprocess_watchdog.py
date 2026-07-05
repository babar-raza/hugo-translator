#!/usr/bin/env python3
"""
Watchdog that sequentially launches in-process workers for reference.aspose.org.

Starts bg, waits for it, then starts ca,cs (to avoid simultaneous RAM OOM
from 3 NLLB instances). da,de runs in parallel throughout.

Usage:
    python scripts/quality/reference_inprocess_watchdog.py
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYTHON = str(ROOT / ".venv" / "Scripts" / "python.exe")
WORKER = str(ROOT / "scripts" / "quality" / "reference_inprocess_worker.py")
LOG_DIR = ROOT / "data" / "logs"

def launch(locales: str, shard_id: str, log_name: str) -> subprocess.Popen:
    log_path = LOG_DIR / log_name
    log_file = open(log_path, "a", encoding="utf-8")
    proc = subprocess.Popen(
        [PYTHON, WORKER, "--locales", locales, "--shard-id", shard_id, "--retry-failed", "--resume"],
        stdout=log_file,
        stderr=log_file,
        cwd=ROOT,
    )
    print(f"[{time.strftime('%H:%M:%S')}] Launched {locales} (shard={shard_id}) PID={proc.pid} -> {log_path.name}", flush=True)
    return proc


def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # da,de runs throughout (already started or starts now)
    da_de = launch("da,de", "inproc-da-de", "reference_inprocess_da_de.log")

    # bg first pass
    bg = launch("bg", "inproc-bg", "reference_inprocess_bg.log")
    print(f"[{time.strftime('%H:%M:%S')}] Waiting for bg worker (PID={bg.pid}) to finish...", flush=True)
    bg.wait()
    print(f"[{time.strftime('%H:%M:%S')}] bg finished (exit={bg.returncode}). Launching ca,cs ...", flush=True)

    # Now bg is done; start ca,cs with freed RAM
    ca_cs = launch("ca,cs", "inproc-ca-cs", "reference_inprocess_ca_cs.log")
    ca_cs.wait()
    print(f"[{time.strftime('%H:%M:%S')}] ca,cs finished (exit={ca_cs.returncode})", flush=True)

    da_de.wait()
    print(f"[{time.strftime('%H:%M:%S')}] da,de finished (exit={da_de.returncode})", flush=True)
    print(f"[{time.strftime('%H:%M:%S')}] All workers done.", flush=True)


if __name__ == "__main__":
    main()
