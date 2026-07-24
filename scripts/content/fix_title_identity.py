#!/usr/bin/env python
"""
TC-P7-03: Title/linkTitle identity fixer.

Gate 28's rule (write_gate.py's _gate_title_identity, is_family_platform_index
in text_unit_extractor.py): family/platform & family-root index pages on
docs/kb/products.aspose.org, plus every reference.aspose.org page, must have
`title` (and, per the audit's mirrored check, `linkTitle`) byte-identical to
current EN -- this holds regardless of staleness elsewhere on the page, so
it is always correct to enforce, independent of the root-cause-2 stale-
content question that applies to other categories in this mission.

Idempotent: skips a file if its title/linkTitle already match EN (safe to
re-run or resume). Copies the EN frontmatter line's value verbatim
(including its own YAML quoting), rather than re-serializing, since the
title being copied is EN's own already-valid YAML string.

Usage:
    python scripts/content/fix_title_identity.py --dry-run
    python scripts/content/fix_title_identity.py --write --batch-size 500 --site docs.aspose.org --family cells
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
_QUALITY_DIR = _PROJECT_ROOT / "scripts" / "quality"
if str(_QUALITY_DIR) not in sys.path:
    sys.path.insert(0, str(_QUALITY_DIR))

FIELD_LINE_RE_TMPL = r"^{field}:\s*.+$"


@dataclass
class FixOutcome:
    file_path: str
    changed: bool
    skipped_reason: str = ""
    fields_changed: list[str] | None = None


def get_field_line(text: str, field: str) -> str | None:
    m = re.search(FIELD_LINE_RE_TMPL.format(field=re.escape(field)), text, re.MULTILINE)
    return m.group(0) if m else None


def get_field_value(text: str, field: str) -> str | None:
    line = get_field_line(text, field)
    if line is None:
        return None
    value = line.split(":", 1)[1].strip()
    return value.strip("\"'")


def replace_field_line(text: str, field: str, new_line: str) -> str:
    pattern = re.compile(FIELD_LINE_RE_TMPL.format(field=re.escape(field)), re.MULTILINE)
    return pattern.sub(lambda _m: new_line, text, count=1)


def fix_file(tr_path: Path, en_path: Path, fields: list[str], write: bool) -> FixOutcome:
    if not tr_path.exists():
        return FixOutcome(str(tr_path), False, "tr_path missing")
    if not en_path.exists():
        return FixOutcome(str(tr_path), False, "en_path missing")

    tr_text = tr_path.read_text(encoding="utf-8", errors="replace")
    en_text = en_path.read_text(encoding="utf-8", errors="replace")

    fields_changed = []
    new_text = tr_text
    for field in fields:
        en_line = get_field_line(en_text, field)
        if en_line is None:
            continue  # EN doesn't have this field either (e.g. no linkTitle) -- nothing to enforce
        tr_line = get_field_line(new_text, field)
        if tr_line is None:
            continue  # TR frontmatter has no such field to replace -- don't invent one
        en_value = get_field_value(en_text, field)
        tr_value = get_field_value(new_text, field)
        if en_value == tr_value:
            continue  # idempotent: already matches, no-op
        new_text = replace_field_line(new_text, field, en_line)
        fields_changed.append(field)

    if not fields_changed:
        return FixOutcome(str(tr_path), False, "already matches EN (idempotent no-op)")

    if write:
        tr_path.write_text(new_text, encoding="utf-8")

    return FixOutcome(str(tr_path), True, fields_changed=fields_changed)


def _verify_with_retries(verify_fn, issue_type, tr_path, en_path, before_text, locale, site_id, attempts=2, base_delay=0.5):
    """Re-read + retry before declaring a real failure: this mission runs
    concurrently with the content repo's own live pipeline (operator-
    confirmed, see plan "Live-System Reassessment"), and rapid successive
    writes have shown a reproducible transient Windows I/O visibility gap
    (write_text() on one file followed immediately by read_text() on
    another can occasionally observe a stale cached view under load, not a
    real second-writer collision -- confirmed by re-checking failed files
    post-hoc, which always showed byte-identical, correctly-fixed content).
    A failure that survives multiple re-reads with growing delay is real.
    """
    import time

    result = None
    for attempt in range(attempts):
        after_text = tr_path.read_text(encoding="utf-8", errors="replace")
        result = verify_fn(issue_type, tr_path, en_path, before_text, after_text, locale, site_id)
        if result.passed:
            return result
        if attempt < attempts - 1:
            time.sleep(base_delay * (attempt + 1))
    return result


def load_targets(detail_csv: Path, site: str | None, family: str | None) -> list[dict]:
    rows = []
    with detail_csv.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["issue_type"] not in ("title_mismatch", "linktitle_mismatch"):
                continue
            if site and r["site_id"] != site:
                continue
            if family and r["family"] != family:
                continue
            rows.append(r)
    # Group by file_path so both fields are fixed together in one pass per file.
    by_file: dict[str, dict] = {}
    for r in rows:
        key = r["file_path"]
        entry = by_file.setdefault(
            key, {"file_path": r["file_path"], "en_path": r["en_path"], "site_id": r["site_id"], "locale": r["locale"], "fields": set()}
        )
        entry["fields"].add("title" if r["issue_type"] == "title_mismatch" else "linkTitle")
    return list(by_file.values())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--detail-csv", default="reports/audit/findings_detail.csv")
    ap.add_argument("--write", action="store_true", help="Apply fixes. Default is dry-run.")
    ap.add_argument("--site", default=None)
    ap.add_argument("--family", default=None)
    ap.add_argument("--batch-size", type=int, default=500)
    ap.add_argument("--verify", action="store_true", help="Run verify_fix.py after each write")
    args = ap.parse_args()

    targets = load_targets(Path(args.detail_csv), args.site, args.family)
    print(f"Loaded {len(targets)} candidate files (site={args.site}, family={args.family})")

    verify_fn = None
    if args.verify:
        from verify_fix import verify_fix  # noqa: E402

        verify_fn = verify_fix

    changed = 0
    skipped_idempotent = 0
    errors = 0
    verify_failures = []

    for i, t in enumerate(targets):
        if i >= args.batch_size:
            print(f"Batch size {args.batch_size} reached, stopping (re-run for the next batch)")
            break
        tr_path = Path(t["file_path"])
        en_path = Path(t["en_path"])
        fields = sorted(t["fields"])

        before_text = tr_path.read_text(encoding="utf-8", errors="replace") if tr_path.exists() else ""
        outcome = fix_file(tr_path, en_path, fields, write=args.write)

        if not outcome.changed:
            skipped_idempotent += 1
            continue
        changed += 1
        print(f"  [{'WRITE' if args.write else 'DRY-RUN'}] {tr_path} -- fields: {outcome.fields_changed}")

        if args.write and verify_fn is not None:
            for field in outcome.fields_changed:
                issue_type = "title_mismatch" if field == "title" else "linktitle_mismatch"
                result = _verify_with_retries(verify_fn, issue_type, tr_path, en_path, before_text, t["locale"], t["site_id"])
                if not result.passed:
                    errors += 1
                    verify_failures.append((tr_path, en_path, issue_type, t["locale"], t["site_id"], before_text))
                    print(f"    VERIFY pending recheck: {issue_type} -- {result.detector_detail} gates={result.gate_failures}")

    if verify_failures:
        print()
        print(f"Final recheck pass on {len(verify_failures)} pending verify results (settling window for rapid-write I/O visibility)...")
        import time

        time.sleep(2.0)
        still_failing = []
        for tr_path, en_path, issue_type, locale, site_id, before_text in verify_failures:
            result = _verify_with_retries(verify_fn, issue_type, tr_path, en_path, before_text, locale, site_id, attempts=3, base_delay=1.0)
            if not result.passed:
                still_failing.append((tr_path, issue_type, result))
        errors = len(still_failing)
        if still_failing:
            print(f"CONFIRMED verify failures after final recheck ({len(still_failing)}):")
            for tr_path, issue_type, result in still_failing:
                print(f"    {tr_path} -- {issue_type} -- {result.detector_detail} gates={result.gate_failures}")
        else:
            print("All pending verify results cleared on final recheck (confirmed transient I/O visibility, not real defects).")

    print()
    print(f"Changed: {changed}, idempotent no-op: {skipped_idempotent}, verify failures: {errors}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
