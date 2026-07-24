#!/usr/bin/env python
r"""
TC-P7-04: Double-period fixer.

Lifts Gate 12's core regex (write_gate.py _gate_double_periods:
re.sub(r"(?<!\.)\.\.(?!\.)", ".", seg) on segments split by code fence) for
already-written files, PLUS protects markdown link targets before applying
it -- Gate 12's own unprotected regex is the confirmed root cause of most
link_path_corrupted findings (every "../" had one dot eaten by this exact
pattern when it ran unprotected over a link target). A fixer that repeats
the same unprotected regex would re-introduce the very corruption this
mission exists to clean up.

Idempotent: if there's nothing to change (no stray ".." outside fences/
links), the file is a no-op.

Usage:
    python scripts/content/fix_double_periods.py --dry-run
    python scripts/content/fix_double_periods.py --write --verify --site docs.aspose.org
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
_QUALITY_DIR = _PROJECT_ROOT / "scripts" / "quality"
if str(_QUALITY_DIR) not in sys.path:
    sys.path.insert(0, str(_QUALITY_DIR))

DOUBLE_PERIOD = re.compile(r"(?<!\.)\.\.(?!\.)")
FM_RE = re.compile(r"^---\n(.*?)\n---", re.S)
# Split out: fenced code blocks, THEN markdown link targets (the part
# inside the parens) within whatever remains -- both are protected from
# the double-period collapse.
FENCE_SPLIT_RE = re.compile(r"(```[\s\S]*?```)")
LINK_TARGET_SPLIT_RE = re.compile(r"(\[[^\]]*\]\([^)]+\))")


def get_frontmatter_and_body(text: str) -> tuple[str, str]:
    m = FM_RE.match(text)
    if not m:
        return "", text
    fm_block = text[: m.end()]
    body = text[m.end() :]
    return fm_block, body


def fix_double_periods_in_body(body: str) -> tuple[str, bool]:
    changed = False
    fence_segments = FENCE_SPLIT_RE.split(body)
    out_segments = []
    for seg in fence_segments:
        if seg.startswith("```"):
            out_segments.append(seg)
            continue
        link_segments = LINK_TARGET_SPLIT_RE.split(seg)
        fixed_link_segments = []
        for lseg in link_segments:
            if lseg.startswith("[") and "](" in lseg:
                fixed_link_segments.append(lseg)  # link (label+target) untouched
                continue
            fixed = DOUBLE_PERIOD.sub(".", lseg)
            if fixed != lseg:
                changed = True
            fixed_link_segments.append(fixed)
        out_segments.append("".join(fixed_link_segments))
    return "".join(out_segments), changed


@dataclass
class FixOutcome:
    file_path: str
    changed: bool
    skipped_reason: str = ""


def fix_file(tr_path: Path, write: bool) -> FixOutcome:
    if not tr_path.exists():
        return FixOutcome(str(tr_path), False, "tr_path missing")
    text = tr_path.read_text(encoding="utf-8", errors="replace")
    fm_block, body = get_frontmatter_and_body(text)
    new_body, changed = fix_double_periods_in_body(body)
    if not changed:
        return FixOutcome(str(tr_path), False, "already clean (idempotent no-op)")
    new_text = fm_block + new_body
    if write:
        tr_path.write_text(new_text, encoding="utf-8")
    return FixOutcome(str(tr_path), True)


def load_targets(detail_csv: Path, site: str | None, family: str | None) -> list[dict]:
    rows = []
    with detail_csv.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["issue_type"] != "double_period":
                continue
            if site and r["site_id"] != site:
                continue
            if family and r["family"] != family:
                continue
            rows.append(r)
    seen = {}
    for r in rows:
        seen.setdefault(r["file_path"], r)
    return list(seen.values())


def verify_with_retries(verify_fn, tr_path, en_path, before_text, locale, site_id, attempts=3, base_delay=0.5):
    result = None
    for attempt in range(attempts):
        after_text = tr_path.read_text(encoding="utf-8", errors="replace")
        result = verify_fn("double_period", tr_path, en_path, before_text, after_text, locale, site_id)
        if result.passed:
            return result
        if attempt < attempts - 1:
            time.sleep(base_delay * (attempt + 1))
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--detail-csv", default="reports/audit/findings_detail.csv")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--site", default=None)
    ap.add_argument("--family", default=None)
    ap.add_argument("--batch-size", type=int, default=1000)
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()

    targets = load_targets(Path(args.detail_csv), args.site, args.family)
    print(f"Loaded {len(targets)} candidate files (site={args.site}, family={args.family})")

    verify_fn = None
    if args.verify:
        from verify_fix import verify_fix

        verify_fn = verify_fix

    changed = 0
    skipped = 0
    pending_recheck = []

    for i, t in enumerate(targets):
        if i >= args.batch_size:
            print(f"Batch size {args.batch_size} reached, stopping (re-run for the next batch)")
            break
        tr_path = Path(t["file_path"])
        en_path = Path(t["en_path"])
        before_text = tr_path.read_text(encoding="utf-8", errors="replace") if tr_path.exists() else ""

        outcome = fix_file(tr_path, write=args.write)
        if not outcome.changed:
            skipped += 1
            continue
        changed += 1
        print(f"  [{'WRITE' if args.write else 'DRY-RUN'}] {tr_path}")

        if args.write and verify_fn is not None:
            result = verify_with_retries(verify_fn, tr_path, en_path, before_text, t["locale"], t["site_id"])
            if not result.passed:
                pending_recheck.append((tr_path, en_path, t["locale"], t["site_id"], before_text))

    errors = 0
    if pending_recheck:
        print(f"\nFinal recheck on {len(pending_recheck)} pending results...")
        time.sleep(2.0)
        for tr_path, en_path, locale, site_id, before_text in pending_recheck:
            result = verify_with_retries(verify_fn, tr_path, en_path, before_text, locale, site_id, attempts=3, base_delay=1.0)
            if not result.passed:
                errors += 1
                print(f"CONFIRMED verify failure: {tr_path} -- {result.detector_detail} gates={result.gate_failures} "
                      f"blast_radius={result.blast_radius_detail}")

    print(f"\nChanged: {changed}, idempotent no-op: {skipped}, confirmed verify failures: {errors}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
