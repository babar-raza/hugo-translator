#!/usr/bin/env python
"""
TC-MLD-05 Remediation Monitor -- run periodically to track queue drain,
catch regressions, and verify fixes are working.

Usage:
    python scripts/monitor_mld_remediation.py
    python scripts/monitor_mld_remediation.py --watch 300   # re-run every 5 min
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

# -- Paths ------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
QUEUE = ROOT / "data" / "retranslate_queue.jsonl"
HEARTBEAT_CW = ROOT / "data" / "logs" / "content_worker.heartbeat"
HEARTBEAT_TM = ROOT / "data" / "logs" / "tm_worker.heartbeat"
LOG_DIR = ROOT / "data" / "logs"
BASELINE_INVENTORY = ROOT / "reports" / "agents" / "contamination_audit" / "inventory_20260421.json"


def _read_queue() -> tuple[int, dict]:
    """Return (total entries, breakdown by retry_count bucket)."""
    if not QUEUE.exists():
        return 0, {}
    buckets: dict[str, int] = {"retry_0": 0, "retry_1": 0, "retry_2": 0, "retry_3+": 0}
    total = 0
    for line in QUEUE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        total += 1
        try:
            entry = json.loads(line)
            rc = entry.get("retry_count", 0)
            if rc >= 3:
                buckets["retry_3+"] += 1
            else:
                buckets[f"retry_{rc}"] += 1
        except json.JSONDecodeError:
            pass
    return total, buckets


def _read_heartbeat(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _scan_recent_logs(hours: float = 6) -> dict:
    """Scan worker logs for key patterns from the last N hours."""
    results = {
        "llm_escalation_fired": 0,
        "semantic_similarity_warn": 0,
        "semantic_similarity_block": 0,
        "accept_after_max_retries": 0,  # should be 0 after RC-1 fix
        "contamination_scan_ran": False,
        "contamination_scan_fast": False,  # should be False after RC-2 fix
        "case4_retranslate_queued": 0,
        "validation_reject": 0,
        "validation_accept": 0,
        "purity_fail": 0,
        "errors": [],
    }

    cutoff = time.time() - hours * 3600
    log_files = sorted(LOG_DIR.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)

    for log_file in log_files[:10]:  # check up to 10 most recent log files
        if log_file.stat().st_mtime < cutoff:
            continue
        try:
            text = log_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        for line in text.splitlines():
            if "LLM escalation" in line and ("firing" in line.lower() or "escalat" in line.lower()):
                results["llm_escalation_fired"] += 1
            if "SemanticSimilarity" in line and "WARN" in line:
                results["semantic_similarity_warn"] += 1
            if "SemanticSimilarity" in line and (
                "ERROR" in line or "BLOCK" in line or "REJECT" in line
            ):
                results["semantic_similarity_block"] += 1
            if "accept_after_max_retries" in line:
                results["accept_after_max_retries"] += 1
            if "contamination_scan" in line or "scan_language_contamination" in line:
                results["contamination_scan_ran"] = True
                if "--fast" in line:
                    results["contamination_scan_fast"] = True
            if "CASE 4" in line and "retranslate" in line.lower():
                results["case4_retranslate_queued"] += 1
            if "ValidationDecision.REJECT" in line or "decision=REJECT" in line:
                results["validation_reject"] += 1
            if "ValidationDecision.ACCEPT" in line or "decision=ACCEPT" in line:
                results["validation_accept"] += 1
            if "purity" in line.lower() and ("fail" in line.lower() or "below" in line.lower()):
                results["purity_fail"] += 1
            if "ERROR" in line and (
                "Traceback" in line or "Exception" in line or "crash" in line.lower()
            ):
                results["errors"].append(line[:200])

    # Keep only last 5 unique errors
    results["errors"] = list(dict.fromkeys(results["errors"]))[:5]
    return results


def _worker_status(hb: dict | None, name: str) -> str:
    if hb is None:
        return f"  {name}: NO HEARTBEAT (not running or stale)"
    ts = hb.get("timestamp", "")
    state = hb.get("status", hb.get("state", "unknown"))
    pid = hb.get("pid", "?")
    try:
        dt = datetime.fromisoformat(ts)
        age_min = (datetime.now(timezone.utc) - dt).total_seconds() / 60
        freshness = f"{age_min:.0f} min ago"
        if age_min > 60:
            freshness += " !! STALE"
    except (ValueError, TypeError):
        freshness = "unknown"
    return f"  {name}: state={state}, pid={pid}, heartbeat={freshness}"


def run_check():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'=' * 70}")
    print(f"  TC-MLD-05 Remediation Monitor -- {now}")
    print(f"{'=' * 70}")

    # 1. Queue status
    total, buckets = _read_queue()
    print(f"\n> Retranslate Queue: {total:,} entries")
    if buckets:
        for k, v in sorted(buckets.items()):
            print(f"    {k}: {v:,}")
    if total == 0:
        print("    [OK] Queue fully drained!")

    # 2. Worker heartbeats
    print("\n> Worker Status:")
    cw_hb = _read_heartbeat(HEARTBEAT_CW)
    tm_hb = _read_heartbeat(HEARTBEAT_TM)
    print(_worker_status(cw_hb, "ContentWorker"))
    print(_worker_status(tm_hb, "TMWorker"))

    # 3. Log analysis
    print("\n> Log Analysis (last 6h):")
    logs = _scan_recent_logs(6)

    # Fix verification
    print(
        "  RC-1 (accept_after_max_retries references):",
        logs["accept_after_max_retries"],
        "[OK] clean" if logs["accept_after_max_retries"] == 0 else "!! REGRESSION -- should be 0!",
    )
    print(
        "  RC-2 (--fast in scan):",
        "!! REGRESSION -- --fast still used!" if logs["contamination_scan_fast"] else "[OK] clean",
    )
    print(
        "  RC-3 (LLM escalation fired):",
        logs["llm_escalation_fired"],
        "-- expected >0 once queue has retry>=2 files"
        if logs["llm_escalation_fired"] == 0
        else "[OK] firing",
    )
    print(
        "  SemanticSimilarity warns:",
        logs["semantic_similarity_warn"],
        "blocks:",
        logs["semantic_similarity_block"],
    )
    print("  Validation: accept:", logs["validation_accept"], "reject:", logs["validation_reject"])
    print("  Purity failures:", logs["purity_fail"])
    print("  CASE 4 -> queue:", logs["case4_retranslate_queued"])

    if logs["errors"]:
        print("\n  !! Recent errors:")
        for err in logs["errors"]:
            print(f"    {err}")

    # 4. Baseline comparison hint
    if BASELINE_INVENTORY.exists():
        size_mb = BASELINE_INVENTORY.stat().st_size / (1024 * 1024)
        print(f"\n> Baseline inventory: {size_mb:.1f} MB ({BASELINE_INVENTORY.name})")
        print("  Before-count: 19,882 contaminated files")
        print("  Run TC-VFY-01 scan after queue drains to get after-count.")

    # 5. Overall health
    print("\n> Overall:")
    issues = []
    if total > 0:
        issues.append(f"queue has {total:,} entries remaining")
    if cw_hb is None:
        issues.append("content worker heartbeat missing")
    if logs["accept_after_max_retries"] > 0:
        issues.append("RC-1 REGRESSION detected")
    if logs["contamination_scan_fast"]:
        issues.append("RC-2 REGRESSION detected")
    if logs["errors"]:
        issues.append(f"{len(logs['errors'])} error(s) in logs")

    if not issues:
        print("  [OK] All clear -- fixes verified, queue drained.")
    else:
        print("  Attention needed:")
        for i in issues:
            print(f"    - {i}")

    print()
    return total


def main():
    parser = argparse.ArgumentParser(description="TC-MLD-05 remediation monitor")
    parser.add_argument(
        "--watch", type=int, default=0, help="Re-run every N seconds (0 = single run)"
    )
    args = parser.parse_args()

    if args.watch > 0:
        print(f"Watching every {args.watch}s. Press Ctrl+C to stop.")
        try:
            while True:
                run_check()
                time.sleep(args.watch)
        except KeyboardInterrupt:
            print("\nStopped.")
    else:
        run_check()


if __name__ == "__main__":
    main()
