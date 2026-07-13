"""
Merge Tier-1/2/3/4 audit JSONL files into a single master_heal_queue.jsonl.

Deduplicates entries by (file_path, locale), merges issues lists, assigns
max_priority, and sorts by (max_priority ASC, site_id, file_path).

TC-AUD-005 implementation.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJ_ROOT = _SCRIPT_DIR.parent.parent

PRIORITY: dict[str, int] = {
    "encoding_corruption": 1,
    "body_identical_to_en": 1,
    "empty_body": 1,
    "table_desc_hallucinated": 1,
    "content_drift": 2,
    "english_headings_nonlatin": 2,
    "english_heading": 2,
    "purity_issue": 2,
    "inline_code_translated": 2,
    "shortcode_leak": 2,
    "code_fence_dropped": 2,
    "link_path_corrupted": 3,
    "table_desc_not_translated": 3,
    "description_hallucination": 3,
    "description_yaml_reverted": 3,
    "duplicate_content": 4,
    "double_period": 4,
    "newline_explosion": 4,
}


def _load_jsonl(path: Path) -> list[dict]:
    entries = []
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError as exc:
                print(f"  [warn] {path.name}:{lineno}: skipping malformed line: {exc}")
    return entries


def merge(
    tier_paths: list[Path],
    output_path: Path,
) -> None:
    # Key: (file_path, locale) → merged record
    merged: dict[tuple[str, str], dict] = {}

    total_loaded = 0
    for tier_path in tier_paths:
        if not tier_path.exists():
            print(f"  [skip] {tier_path} not found")
            continue
        entries = _load_jsonl(tier_path)
        print(f"  Loaded {len(entries):,} entries from {tier_path.name}")
        total_loaded += len(entries)
        for entry in entries:
            fp = entry.get("file_path", "")
            locale = entry.get("locale", "")
            key = (fp, locale)
            if key not in merged:
                merged[key] = {
                    "file_path": fp,
                    "en_path": entry.get("en_path", ""),
                    "locale": locale,
                    "site_id": entry.get("site_id", ""),
                    "issues": [],
                    "max_priority": 9,
                }
            existing_types = {iss["type"] for iss in merged[key]["issues"]}
            for issue in entry.get("issues", []):
                if issue["type"] not in existing_types:
                    # Re-apply canonical priority in case tier files used stale values
                    prio = PRIORITY.get(issue["type"], issue.get("priority", 4))
                    merged[key]["issues"].append(
                        {
                            "type": issue["type"],
                            "unit_indices": issue.get("unit_indices", [0]),
                            "priority": prio,
                        }
                    )
                    existing_types.add(issue["type"])

    # Recompute max_priority and sort issues within each record
    for record in merged.values():
        if record["issues"]:
            record["max_priority"] = min(iss["priority"] for iss in record["issues"])
        else:
            record["max_priority"] = 9
        record["issues"].sort(key=lambda i: i["priority"])

    # Sort output by (max_priority, site_id, file_path)
    sorted_records = sorted(
        merged.values(),
        key=lambda r: (r["max_priority"], r["site_id"], r["file_path"]),
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fh:
        for record in sorted_records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    # Summary
    issue_counts: dict[str, int] = defaultdict(int)
    for record in sorted_records:
        for iss in record["issues"]:
            issue_counts[iss["type"]] += 1

    print(f"\n=== Merge complete ===")
    print(f"Total entries loaded: {total_loaded:,}")
    print(f"Unique files in output: {len(sorted_records):,}")
    print("Issue type counts:")
    for issue_type, cnt in sorted(issue_counts.items(), key=lambda x: -x[1]):
        prio = PRIORITY.get(issue_type, 4)
        print(f"  P{prio} {issue_type}: {cnt:,}")
    print(f"\nOutput: {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Merge T1/T2/T3/T4 audit JSONL files into master_heal_queue.jsonl."
    )
    parser.add_argument("--t1", help="Tier-1 structural audit JSONL")
    parser.add_argument("--t2", help="Tier-2 linguistic audit JSONL")
    parser.add_argument("--t3", help="Tier-3 completeness audit JSONL")
    parser.add_argument("--t4", help="Tier-4 semantic audit JSONL (optional)")
    parser.add_argument(
        "--output",
        default="data/audit/master_heal_queue.jsonl",
        help="Output JSONL path",
    )
    args = parser.parse_args()

    tier_paths = []
    for attr in ("t1", "t2", "t3", "t4"):
        val = getattr(args, attr, None)
        if val:
            p = Path(val)
            if not p.is_absolute():
                p = _PROJ_ROOT / p
            tier_paths.append(p)

    if not tier_paths:
        # Auto-discover from data/audit/
        audit_dir = _PROJ_ROOT / "data" / "audit"
        for name in ("audit_structural.jsonl", "audit_linguistic.jsonl", "audit_completeness.jsonl", "audit_semantic.jsonl"):
            p = audit_dir / name
            if p.exists():
                print(f"  Auto-discovered: {p.name}")
                tier_paths.append(p)

    if not tier_paths:
        parser.error("No tier files specified and none found in data/audit/")

    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = _PROJ_ROOT / output_path

    merge(tier_paths, output_path)


if __name__ == "__main__":
    main()
