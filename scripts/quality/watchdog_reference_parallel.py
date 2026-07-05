"""
Parallel locale watchdog for reference.aspose.org retranslation.

Runs one governed-retranslate subprocess per locale concurrently.
Each shard gets its own checkpoint file (checkpoint.latin-<locale>.json).
Uses the same RUN_ID as the main latin-a campaign so evidences land on D:\
via the existing junction.

Usage:
    python scripts/quality/watchdog_reference_parallel.py

Locales handled here: bg, ca, cs, da, de
(ar is handled by watchdog_reference.py / latin-a shard already running)
"""
import subprocess
import sys
import time
import json
import threading
from pathlib import Path

HUGO_DIR     = Path("C:/Users/prora/OneDrive/Documents/GitHub/hugo-translator")
ASPOSE_DIR   = Path("C:/Users/prora/OneDrive/Documents/GitHub/aspose.org")
PYTHON       = str(HUGO_DIR / ".venv/Scripts/python.exe")
SCRIPT       = str(HUGO_DIR / "scripts/quality/aspose_org_governed_retranslate.py")
CONTENT_ROOT = str(ASPOSE_DIR / "content/reference.aspose.org")
RUN_ID       = "aspose_org_multisite_20260704_012331"  # same as latin-a

# Locales with remaining MISSING_TARGET items (ar handled by latin-a already)
LOCALE_SHARDS = ["bg", "ca", "cs", "da", "de"]

LOG_DIR = HUGO_DIR / "data/logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

_print_lock = threading.Lock()


def log(shard: str, msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}][{shard}] {msg}"
    with _print_lock:
        print(line, flush=True)
    log_path = LOG_DIR / f"ref_parallel_{shard}.log"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run_shard(locale: str) -> None:
    shard_id = f"latin-{locale}"
    log(locale, f"Starting shard {shard_id} for locale {locale}")

    run_num = 0
    while True:
        run_num += 1
        log(locale, f"=== Run #{run_num} ===")

        cmd = [
            PYTHON, SCRIPT,
            "--site", "reference.aspose.org",
            "--run-id", RUN_ID,
            "--resume", "--retry-failed",
            "--shard-id", shard_id,
            "--only-locales", locale,
            "--model", "nllb_200_1.3b",
            "--content-root", CONTENT_ROOT,
        ]

        log_path = LOG_DIR / f"ref_parallel_{locale}_run{run_num}.log"
        try:
            with open(log_path, "w", encoding="utf-8") as lf:
                result = subprocess.run(
                    cmd,
                    cwd=HUGO_DIR,
                    stdout=lf,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=7200,  # 2-hour hard timeout per run
                )
            log(locale, f"Run #{run_num} exited code={result.returncode}")
        except subprocess.TimeoutExpired:
            log(locale, f"Run #{run_num} timed out after 2h — restarting")
            continue
        except Exception as e:
            log(locale, f"Run #{run_num} error: {e} — retrying in 10s")
            time.sleep(10)
            continue

        # Check checkpoint for remaining work
        cp_path = (
            HUGO_DIR / ".local/evidences/reference.aspose.org"
            / RUN_ID / "checkpoints" / f"checkpoint.{shard_id}.json"
        )
        try:
            with open(cp_path, encoding="utf-8") as f:
                cp = json.load(f)
            n_accepted = len(cp.get("accepted", {}))
            n_failed = len(cp.get("failed", {}))
            n_missing = sum(
                1 for v in cp.get("failed", {}).values()
                if v.get("failure_type") == "MISSING_TARGET"
            )
            log(locale, f"Checkpoint: {n_accepted} accepted, {n_failed} failed ({n_missing} MISSING_TARGET)")
            if n_missing == 0 and n_failed <= 10:
                log(locale, "All items processed — shard complete.")
                break
        except Exception as e:
            log(locale, f"Could not read checkpoint: {e}")

        # Brief pause between runs to avoid hammering disk/GPU
        time.sleep(5)

    log(locale, f"Shard {locale} finished.")


def main() -> None:
    print(f"[{time.strftime('%H:%M:%S')}] Parallel reference watchdog starting")
    print(f"  Locales: {', '.join(LOCALE_SHARDS)}")
    print(f"  Each shard runs independently with its own checkpoint")
    print(f"  Logs: data/logs/ref_parallel_<locale>.log")
    print()

    threads = []
    for locale in LOCALE_SHARDS:
        t = threading.Thread(target=run_shard, args=(locale,), daemon=True, name=f"shard-{locale}")
        t.start()
        threads.append(t)
        # Stagger starts by 30s to avoid simultaneous VRAM spikes
        time.sleep(30)

    for t in threads:
        t.join()

    print(f"[{time.strftime('%H:%M:%S')}] All shards complete.")


if __name__ == "__main__":
    main()
