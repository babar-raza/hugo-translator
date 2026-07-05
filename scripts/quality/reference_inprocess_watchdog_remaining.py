#!/usr/bin/env python3
"""
Sequential watchdog for remaining reference.aspose.org locales.

Runs ONE in-process NLLB worker at a time to stay within GPU memory.
Each locale gets its own shard checkpoint.

Usage:
    python scripts/quality/reference_inprocess_watchdog_remaining.py
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

# 32 remaining locales (ca, cs, da, de are done)
LOCALES = [
    "ar", "bg", "el", "es", "fa", "fi", "fr", "he",
    "hi", "hr", "hu", "id", "it", "ja", "ko", "lt",
    "lv", "ms", "nl", "no", "pl", "pt", "ro", "ru",
    "sk", "sr", "sv", "th", "tr", "uk", "vi", "zh",
]


def launch(locale: str) -> subprocess.Popen:
    shard_id = f"inproc-{locale}"
    log_name = f"reference_inprocess_{locale}.log"
    log_path = LOG_DIR / log_name
    log_file = open(log_path, "a", encoding="utf-8")
    proc = subprocess.Popen(
        [
            PYTHON, WORKER,
            "--locales", locale,
            "--shard-id", shard_id,
            "--retry-failed",
            "--resume",
        ],
        stdout=log_file,
        stderr=log_file,
        cwd=ROOT,
    )
    print(
        f"[{time.strftime('%H:%M:%S')}] Launched {locale} "
        f"(shard={shard_id}) PID={proc.pid} -> {log_name}",
        flush=True,
    )
    return proc


def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[{time.strftime('%H:%M:%S')}] Starting sequential campaign for {len(LOCALES)} locales", flush=True)
    print(f"[{time.strftime('%H:%M:%S')}] Order: {', '.join(LOCALES)}", flush=True)

    for i, locale in enumerate(LOCALES, 1):
        print(f"\n[{time.strftime('%H:%M:%S')}] === [{i}/{len(LOCALES)}] Starting {locale} ===", flush=True)
        proc = launch(locale)
        proc.wait()
        exit_code = proc.returncode
        status = "OK" if exit_code == 0 else f"EXIT={exit_code}"
        print(f"[{time.strftime('%H:%M:%S')}] {locale} finished ({status})", flush=True)

    print(f"\n[{time.strftime('%H:%M:%S')}] All {len(LOCALES)} locales done.", flush=True)


if __name__ == "__main__":
    main()
