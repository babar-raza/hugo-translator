#!/usr/bin/env python3
"""Read-only audit of all posted Agent Metrics sidecar evidence.

Loads every sidecar file that has a .posted marker, classifies each row,
and produces a structured JSON report + human-readable stdout summary.

Usage:
    python scripts/ops/audit_sheet_reconciliation.py [--evidence-dir DIR] [--output FILE]

Defaults:
    --evidence-dir  data/metrics/agent_evidence
    --output        data/metrics/sheet_reconciliation_audit.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


def classify_row(sidecar: dict) -> str:
    """Classify a posted sidecar into one of the audit categories."""
    payload = sidecar.get("posted_payload", {})
    scope = sidecar.get("scope", {})
    posting = sidecar.get("posting", {})

    response_code = posting.get("response_code")
    if response_code is not None and response_code != 200:
        return "RESPONSE_CODE_ANOMALY"

    website = payload.get("website", "")
    product = payload.get("product", "")
    if website == "tm_improvement" or "Tm_improvement" in product:
        return "BROKEN_TM_SCOPE"

    items_discovered = payload.get("items_discovered", 0)
    if items_discovered == 0:
        return "ZERO_ITEM"

    confidence = scope.get("reporting_confidence", "high")
    fallback = scope.get("fallback_used", False)
    if confidence == "low":
        return "LOW_CONFIDENCE"

    return "CLEAN"


def load_posted_sidecars(evidence_dir: Path) -> list[dict]:
    """Load all sidecar JSON files that have a .posted marker."""
    markers_dir = evidence_dir / "markers"
    if not markers_dir.exists():
        print(f"ERROR: Markers directory not found: {markers_dir}", file=sys.stderr)
        return []

    posted_ids = set()
    for marker in markers_dir.glob("*.posted"):
        posted_ids.add(marker.stem)

    sidecars = []
    missing = []
    for seg_id in sorted(posted_ids):
        found = False
        for date_dir in sorted(evidence_dir.iterdir()):
            if not date_dir.is_dir() or date_dir.name in ("markers",):
                continue
            sidecar_path = date_dir / f"{seg_id}.json"
            if sidecar_path.exists():
                try:
                    data = json.loads(sidecar_path.read_text(encoding="utf-8"))
                    data["_sidecar_path"] = str(sidecar_path)
                    data["_segment_run_id"] = seg_id
                    sidecars.append(data)
                    found = True
                    break
                except (json.JSONDecodeError, OSError) as e:
                    missing.append({"segment_run_id": seg_id, "error": str(e)})
                    found = True
                    break
        if not found:
            missing.append({"segment_run_id": seg_id, "error": "sidecar file not found"})

    return sidecars, missing


def load_failed_posts(evidence_dir: Path) -> list[dict]:
    """Load failed post events from the ledger."""
    ledger_path = evidence_dir / "metrics_ledger.jsonl"
    if not ledger_path.exists():
        return []

    failed = []
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            if entry.get("event") == "post_failed":
                failed.append(entry)
        except json.JSONDecodeError:
            continue
    return failed


def build_report(sidecars: list[dict], missing: list[dict], failed_posts: list[dict]) -> dict:
    """Build the structured audit report."""
    categories = Counter()
    by_job_type = Counter()
    by_product = Counter()
    by_website = Counter()
    by_website_section = Counter()
    by_date = Counter()

    total_items_discovered = 0
    total_items_succeeded = 0
    total_items_failed = 0
    total_token_usage = 0

    rows_detail = []
    anomalies = []

    for sc in sidecars:
        payload = sc.get("posted_payload", {})
        scope = sc.get("scope", {})
        posting = sc.get("posting", {})
        call_acc = sc.get("call_accounting", {})

        category = classify_row(sc)
        categories[category] += 1

        job_type = payload.get("job_type", "unknown")
        product = payload.get("product", "unknown")
        website = payload.get("website", "unknown")
        section = payload.get("website_section", "unknown")
        timestamp = payload.get("timestamp", "")
        date = timestamp[:10] if len(timestamp) >= 10 else "unknown"

        by_job_type[job_type] += 1
        by_product[product] += 1
        by_website[website] += 1
        by_website_section[section] += 1
        by_date[date] += 1

        disc = payload.get("items_discovered", 0)
        succ = payload.get("items_succeeded", 0)
        fail = payload.get("items_failed", 0)
        tokens = payload.get("token_usage", 0)

        total_items_discovered += disc
        total_items_succeeded += succ
        total_items_failed += fail
        total_token_usage += tokens

        row = {
            "segment_run_id": sc.get("_segment_run_id", ""),
            "category": category,
            "timestamp": timestamp,
            "job_type": job_type,
            "product": product,
            "platform": payload.get("platform", ""),
            "website": website,
            "website_section": section,
            "item_name": payload.get("item_name", ""),
            "status": payload.get("status", ""),
            "items_discovered": disc,
            "items_succeeded": succ,
            "items_failed": fail,
            "token_usage": tokens,
            "api_calls_count": payload.get("api_calls_count", 0),
            "run_duration_ms": payload.get("run_duration_ms", 0),
            "run_id": payload.get("run_id", ""),
            "reporting_confidence": scope.get("reporting_confidence", ""),
            "fallback_used": scope.get("fallback_used", False),
            "detection_method": scope.get("detection_method", ""),
            "scope_warnings": scope.get("warnings", []),
            "error_detail": sc.get("error_detail"),
            "response_code": posting.get("response_code"),
            "posting_status": posting.get("status", ""),
            "sidecar_path": sc.get("_sidecar_path", ""),
        }
        rows_detail.append(row)

        if category != "CLEAN":
            anomalies.append(row)

    timestamps = [r["timestamp"] for r in rows_detail if r["timestamp"]]
    first_post = min(timestamps) if timestamps else None
    last_post = max(timestamps) if timestamps else None

    report = {
        "audit_metadata": {
            "audit_date": "2026-06-15",
            "total_posted_markers": len(sidecars) + len(missing),
            "total_sidecars_loaded": len(sidecars),
            "orphan_markers": len(missing),
            "failed_posts_in_ledger": len(failed_posts),
            "first_post_timestamp": first_post,
            "last_post_timestamp": last_post,
        },
        "category_summary": dict(sorted(categories.items())),
        "by_job_type": dict(sorted(by_job_type.items())),
        "by_product": dict(sorted(by_product.items())),
        "by_website": dict(sorted(by_website.items())),
        "by_website_section": dict(sorted(by_website_section.items())),
        "by_date": dict(sorted(by_date.items())),
        "aggregate_totals": {
            "items_discovered": total_items_discovered,
            "items_succeeded": total_items_succeeded,
            "items_failed": total_items_failed,
            "token_usage": total_token_usage,
        },
        "anomalies": anomalies,
        "orphan_markers": missing,
        "failed_posts": [
            {
                "timestamp": fp.get("timestamp"),
                "segment_run_id": fp.get("segment_run_id"),
                "error": fp.get("detail", {}).get("error"),
                "response_code": fp.get("detail", {}).get("response_code"),
            }
            for fp in failed_posts
        ],
        "all_rows": rows_detail,
    }
    return report


def print_summary(report: dict) -> None:
    """Print a human-readable summary to stdout."""
    meta = report["audit_metadata"]
    cats = report["category_summary"]
    totals = report["aggregate_totals"]

    print("=" * 72)
    print("AGENT METRICS — POSTED ROW RECONCILIATION AUDIT")
    print("=" * 72)
    print()
    print(f"  Audit date:             {meta['audit_date']}")
    print(f"  Posted markers found:   {meta['total_posted_markers']}")
    print(f"  Sidecars loaded:        {meta['total_sidecars_loaded']}")
    print(f"  Orphan markers:         {meta['orphan_markers']}")
    print(f"  Failed posts (ledger):  {meta['failed_posts_in_ledger']}")
    print(f"  First post:             {meta['first_post_timestamp']}")
    print(f"  Last post:              {meta['last_post_timestamp']}")
    print()

    print("--- CATEGORY BREAKDOWN ---")
    total = sum(cats.values())
    for cat, count in sorted(cats.items(), key=lambda x: -x[1]):
        pct = (count / total * 100) if total else 0
        print(f"  {cat:30s}  {count:4d}  ({pct:5.1f}%)")
    print(f"  {'TOTAL':30s}  {total:4d}")
    print()

    print("--- BY JOB TYPE ---")
    for jt, count in sorted(report["by_job_type"].items(), key=lambda x: -x[1]):
        print(f"  {jt:30s}  {count:4d}")
    print()

    print("--- BY PRODUCT ---")
    for prod, count in sorted(report["by_product"].items(), key=lambda x: -x[1]):
        print(f"  {prod:30s}  {count:4d}")
    print()

    print("--- BY WEBSITE ---")
    for ws, count in sorted(report["by_website"].items(), key=lambda x: -x[1]):
        print(f"  {ws:30s}  {count:4d}")
    print()

    print("--- BY DATE ---")
    for date, count in sorted(report["by_date"].items()):
        print(f"  {date}  {count:4d}")
    print()

    print("--- AGGREGATE TOTALS ---")
    print(f"  Items discovered:       {totals['items_discovered']:,}")
    print(f"  Items succeeded:        {totals['items_succeeded']:,}")
    print(f"  Items failed:           {totals['items_failed']:,}")
    print(f"  Token usage:            {totals['token_usage']:,}")
    print()

    anomalies = report["anomalies"]
    if anomalies:
        print(f"--- ANOMALOUS ROWS ({len(anomalies)}) ---")
        for a in anomalies:
            print(
                f"  [{a['category']}] {a['timestamp'][:19]}  "
                f"{a['job_type']:25s}  {a['product']:25s}  "
                f"{a['website']:15s}  {a['website_section']:15s}  "
                f"disc={a['items_discovered']}  succ={a['items_succeeded']}  "
                f"tok={a['token_usage']}  status={a['status']}  "
                f"confidence={a['reporting_confidence']}  "
                f"resp={a['response_code']}"
            )
        print()

    orphans = report["orphan_markers"]
    if orphans:
        print(f"--- ORPHAN MARKERS ({len(orphans)}) ---")
        for o in orphans:
            print(f"  {o['segment_run_id']}  error={o['error']}")
        print()

    failed = report["failed_posts"]
    if failed:
        print(f"--- FAILED POSTS ({len(failed)}) ---")
        for fp in failed:
            print(
                f"  {fp['timestamp'][:19]}  {fp['segment_run_id']}  "
                f"error={fp['error']}  resp={fp['response_code']}"
            )
        print()

    print("--- CLEAN ROW SAMPLE (first 5) ---")
    clean = [r for r in report["all_rows"] if r["category"] == "CLEAN"]
    for r in clean[:5]:
        print(
            f"  {r['timestamp'][:19]}  {r['job_type']:25s}  {r['product']:25s}  "
            f"{r['website']:15s}  {r['website_section']:15s}  "
            f"disc={r['items_discovered']}  succ={r['items_succeeded']}  "
            f"tok={r['token_usage']}  status={r['status']}"
        )
    if len(clean) > 5:
        print(f"  ... and {len(clean) - 5} more clean rows")
    print()
    print("=" * 72)


def main():
    parser = argparse.ArgumentParser(description="Audit posted Agent Metrics sidecars")
    parser.add_argument(
        "--evidence-dir",
        default="data/metrics/agent_evidence",
        help="Path to evidence directory",
    )
    parser.add_argument(
        "--output",
        default="data/metrics/sheet_reconciliation_audit.json",
        help="Output JSON report path",
    )
    args = parser.parse_args()

    evidence_dir = Path(args.evidence_dir)
    if not evidence_dir.exists():
        print(f"ERROR: Evidence directory not found: {evidence_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading sidecars from: {evidence_dir}")
    sidecars, missing = load_posted_sidecars(evidence_dir)
    print(f"Loaded {len(sidecars)} posted sidecars, {len(missing)} orphan markers")

    failed_posts = load_failed_posts(evidence_dir)
    print(f"Found {len(failed_posts)} failed post events in ledger")
    print()

    report = build_report(sidecars, missing, failed_posts)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"Report written to: {output_path}")
    print()

    print_summary(report)


if __name__ == "__main__":
    main()
