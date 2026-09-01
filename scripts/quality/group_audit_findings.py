#!/usr/bin/env python
"""
TC-P7-02: Group audit findings by subdomain (site_id) x family x locale x
issue_type, for the 10 corruption categories tracked by the
quality-remediation-audit-phase7-20260723 mission (see
C:\\Users\\prora\\.claude\\plans\\link-path-corrupted-1-638-memoized-hinton.md).

Source: data/audit/audit_18site_dryrun.jsonl (rebaselined -- see plan's
"Live-System Reassessment (2026-07-24)" section D.2). This file already
covers all 18 sites including blog.aspose.org natively (via
src/utils/content_discovery.py's per_language_folders-aware discovery), so
no separate blogscheme-merge adapter is needed.

Usage:
    python scripts/quality/group_audit_findings.py
    python scripts/quality/group_audit_findings.py --source data/audit/audit_18site_dryrun.jsonl
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

CONTENT_ROOT = "D:\\onedrive\\Documents\\GitHub\\aspose.org\\"

# The 10 categories this mission is scoped to fix or backlog. Everything
# else in the source JSONL (content_hash_stale_gate32, dropped_trailing_link_gate35,
# heading_deficit_gate34, english_headings_nonlatin, etc.) belongs to a
# different, much larger initiative and is deliberately excluded here --
# see the plan's rebaseline note for volumes.
TARGET_ISSUE_TYPES = {
    "link_path_corrupted",
    "title_mismatch",
    "double_period",
    "newline_explosion",
    "table_desc_not_translated",
    "code_fence_dropped",
    "empty_body",
    "partial_script_contamination_gate31",
    "linktitle_mismatch",
    "shortcode_leak",
}


def derive_family(rel_parts: list[str], locale: str) -> str | None:
    """Family = the path segment immediately after the locale directory
    (dirscheme sites), or the first segment after site_id (blogscheme
    sites, where locale lives in the filename, not a directory). None for
    site-root-level pages (websites.aspose.org, www.aspose.org) that have
    no family segment at all -- out of this mission's fix-scope, kept for
    reporting completeness only.
    """
    if locale in rel_parts:
        idx = rel_parts.index(locale)
        remainder = rel_parts[idx + 1 :]
    else:
        remainder = rel_parts
    # remainder's last element is always the filename itself; a real
    # family segment requires at least one directory beyond that.
    if len(remainder) >= 2:
        return remainder[0]
    return None


def to_rel_parts(file_path: str, site_id: str) -> list[str]:
    p = file_path
    if p.startswith(CONTENT_ROOT):
        p = p[len(CONTENT_ROOT) :]
    p = p.replace("\\", "/")
    parts = p.split("/")
    # parts[0] == "content", parts[1] == site_id -- drop both, keep the rest
    if len(parts) >= 2 and parts[0] == "content" and parts[1] == site_id:
        return parts[2:]
    return parts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--source",
        default="data/audit/audit_18site_dryrun.jsonl",
        help="Source audit JSONL (default: rebaselined 18-site scan)",
    )
    ap.add_argument(
        "--out-dir",
        default="reports/audit",
        help="Output directory for the two CSV reports",
    )
    args = ap.parse_args()

    source = Path(args.source)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    group_counts: dict[tuple[str, str, str, str], int] = defaultdict(int)
    detail_rows: list[dict] = []
    total_rows = 0
    matched_rows = 0

    with source.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            total_rows += 1
            site_id = rec["site_id"]
            locale = rec["locale"]
            file_path = rec["file_path"]
            en_path = rec.get("en_path", "")
            rel_parts = to_rel_parts(file_path, site_id)
            family = derive_family(rel_parts, locale) or "(root)"

            row_matched = False
            for iss in rec.get("issues", []):
                itype = iss.get("type")
                if itype not in TARGET_ISSUE_TYPES:
                    continue
                row_matched = True
                group_counts[(site_id, family, locale, itype)] += 1
                detail_rows.append(
                    {
                        "site_id": site_id,
                        "family": family,
                        "locale": locale,
                        "file_path": file_path,
                        "en_path": en_path,
                        "issue_type": itype,
                        "detail": iss.get("detail", ""),
                        "priority": iss.get("priority", ""),
                    }
                )
            if row_matched:
                matched_rows += 1

    group_path = out_dir / "findings_by_group.csv"
    with group_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["site_id", "family", "locale", "issue_type", "count"])
        for (site_id, family, locale, itype), count in sorted(
            group_counts.items(), key=lambda kv: (-kv[1], kv[0])
        ):
            w.writerow([site_id, family, locale, itype, count])

    detail_path = out_dir / "findings_detail.csv"
    with detail_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "site_id",
                "family",
                "locale",
                "file_path",
                "en_path",
                "issue_type",
                "detail",
                "priority",
            ],
        )
        w.writeheader()
        w.writerows(detail_rows)

    type_totals: dict[str, int] = defaultdict(int)
    for (_, _, _, itype), count in group_counts.items():
        type_totals[itype] += count

    print(f"Source: {source} ({total_rows:,} rows scanned, {matched_rows:,} matched a target category)")
    print(f"Wrote {group_path} ({len(group_counts):,} group rows)")
    print(f"Wrote {detail_path} ({len(detail_rows):,} detail rows)")
    print()
    print("Totals by issue_type:")
    for itype, count in sorted(type_totals.items(), key=lambda kv: -kv[1]):
        print(f"  {count:>6,}  {itype}")
    print()
    print("Totals by site_id:")
    site_totals: dict[str, int] = defaultdict(int)
    for row in detail_rows:
        site_totals[row["site_id"]] += 1
    for site_id, count in sorted(site_totals.items(), key=lambda kv: -kv[1]):
        print(f"  {count:>6,}  {site_id}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
