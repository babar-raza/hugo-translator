#!/usr/bin/env python3
"""Live quality monitor for reference.aspose.org translation campaigns."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_ROOT = ROOT / ".local" / "evidences"
SITE = "reference.aspose.org"

SHARDS = ["latin-a", "latin-b", "latin-c", "latin-d", "latin-e", "latin-f"]
FAILURE_SEVERITY = {
    "REJECT_LANGUAGE_PURITY": "🔴",
    "REJECT_MIXED_LANGUAGE": "🔴",
    "REJECT_WRONG_LANGUAGE": "🔴",
    "REJECT_PARTIAL_TRANSLATION": "🟡",
    "REJECT_STRUCTURAL_MISMATCH": "🟡",
    "REJECT_PROTECTED_FIELD_CHANGED": "🔴",
    "REJECT_SOURCE_MUTATION": "🔴",
    "REJECT_COMPLETENESS": "🟡",
}


def latest_run_id() -> str | None:
    multisite_dir = EVIDENCE_ROOT / "aspose-org-multisite"
    if not multisite_dir.exists():
        return None
    dirs = sorted(
        (d for d in multisite_dir.iterdir() if d.is_dir() and "reference" not in d.name),
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    for d in dirs:
        report = d / "final" / "campaign-report.json"
        if report.exists():
            data = json.loads(report.read_text(encoding="utf-8"))
            if data.get("final_verdict") == "RUNNING" and SITE in data.get("sites", {}):
                return data["run_id"]
    # fallback: latest dir
    return dirs[0].name if dirs else None


def vram() -> str:
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        parts = [p.strip() for p in r.stdout.strip().split(",")]
        used, total, util = int(parts[0]), int(parts[1]), int(parts[2])
        bar_len = 20
        filled = round((used / total) * bar_len)
        bar = "█" * filled + "░" * (bar_len - filled)
        return f"VRAM [{bar}] {used}/{total} MB ({util}% GPU)"
    except Exception:
        return "VRAM: unavailable"


def read_shard_summary(run_id: str, shard_id: str) -> dict:
    p = EVIDENCE_ROOT / SITE / run_id / "final" / f"summary.{shard_id}.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def read_campaign_report(run_id: str) -> dict:
    p = EVIDENCE_ROOT / "aspose-org-multisite" / run_id / "final" / "campaign-report.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def read_live_speed(run_id: str) -> dict:
    p = EVIDENCE_ROOT / "aspose-org-multisite" / run_id / "final" / f"live-speed-report.{SITE}.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def latest_cycle_log(run_id: str) -> Path | None:
    log_dir = EVIDENCE_ROOT / "aspose-org-multisite" / run_id / "logs" / SITE
    if not log_dir.exists():
        return None
    logs = sorted(log_dir.glob("cycle-*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    return logs[0] if logs else None


def tail_log(path: Path, n: int = 8) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return lines[-n:]
    except Exception:
        return []


def render(run_id: str) -> None:
    report = read_campaign_report(run_id)
    speed = read_live_speed(run_id)
    verdict = report.get("final_verdict", "RUNNING")
    stoplight = speed.get("stoplight", "—")
    cycle = speed.get("cycle", "—")

    print(f"\033[H\033[J", end="")  # clear screen
    print(f"{'='*70}")
    print(f"  reference.aspose.org  |  run: {run_id}")
    print(f"  Verdict: {verdict}  |  Stoplight: {stoplight}  |  Cycle: {cycle}")
    print(f"  {vram()}")
    print(f"{'='*70}")

    # Aggregated totals
    total_required = total_accepted = total_failed = 0
    for shard_id in SHARDS:
        s = read_shard_summary(run_id, shard_id)
        if not s:
            continue
        req = int(s.get("required_pairs", 0) or 0)
        acc = int(s.get("accepted_pairs", 0) or 0)
        fail = int(s.get("failed_pairs", 0) or 0)
        total_required += req
        total_accepted += acc
        total_failed += fail
        pct = f"{(acc/req*100):.1f}%" if req else "—"
        print(f"  {shard_id:<12}  req={req:>6}  acc={acc:>6} ({pct:>6})  fail={fail:>5}")

    if total_required:
        pct = f"{(total_accepted/total_required*100):.1f}%"
        print(f"  {'TOTAL':<12}  req={total_required:>6}  acc={total_accepted:>6} ({pct:>6})  fail={total_failed:>5}")

    # Failure breakdown
    all_ftypes: dict[str, int] = {}
    for shard_id in SHARDS:
        s = read_shard_summary(run_id, shard_id)
        for ft, cnt in (s.get("failure_type_counts") or {}).items():
            all_ftypes[ft] = all_ftypes.get(ft, 0) + int(cnt)
    if all_ftypes:
        print(f"\n  Failure breakdown:")
        for ft, cnt in sorted(all_ftypes.items(), key=lambda x: -x[1]):
            icon = FAILURE_SEVERITY.get(ft, "⚪")
            print(f"    {icon} {ft}: {cnt}")

    # Throughput
    tp = speed.get("throughput", {})
    if tp:
        print(f"\n  Throughput (last cycle):")
        print(f"    accepted/hr: {tp.get('cycle_accepted_per_hour', '—')}")
        print(f"    attempted/hr: {tp.get('cycle_attempted_per_hour', '—')}")
        print(f"    elapsed_s: {tp.get('cycle_elapsed_seconds', '—')}")

    # Language mixing
    lm = int(speed.get("language_mixing_failure_count", 0) or 0)
    if lm:
        print(f"\n  ⚠️  Language mixing failures: {lm}")

    # Latest log tail
    log = latest_cycle_log(run_id)
    if log:
        print(f"\n  Latest log: {log.name}")
        for line in tail_log(log, 6):
            print(f"    {line}")

    print(f"\n  Updated: {__import__('datetime').datetime.now().strftime('%H:%M:%S')}  (Ctrl+C to exit)")


def main() -> None:
    run_id = sys.argv[1] if len(sys.argv) > 1 else latest_run_id()
    if not run_id:
        print("No running campaign found. Pass run_id as argument.")
        sys.exit(1)
    print(f"Monitoring: {run_id}")
    interval = int(sys.argv[2]) if len(sys.argv) > 2 else 15
    try:
        while True:
            render(run_id)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nMonitor stopped.")


if __name__ == "__main__":
    main()
