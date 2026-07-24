#!/usr/bin/env python
"""
TC-P7-06: Newline-explosion classifier + fixer.

Sampling (see plan Deliverable 3 / Reassessment) found ~78% of
newline_explosion findings are root cause 2 (stale/orphaned translation
describing an EN revision that's since been restructured -- confirmed via
frontmatter evidence.apis list divergence, e.g. Material.md's Python
translation still documenting a removed LambertMaterial/PhongMaterial/
PbrMaterial API surface that current EN no longer has), NOT blank-line
bloat (max consecutive blank-line run in the sampled stale case was only
2). Only a small minority is genuine whitespace bloat that a mechanical
`\\n{3,}` -> `\\n\\n` collapse actually fixes.

This script classifies every flagged file into "mechanical" (fixed) or
"stale" (backlog, untouched) using three signals, in priority order:
  1. evidence.apis / apis: frontmatter list overlap with EN, where present.
  2. Fallback: ## heading-set overlap with EN.
  3. Fallback: non-blank-line-count ratio to EN (if TR's real content lines
     are within ~1.3x of EN's, the extra lines are genuinely blank-line
     bloat, not extra real content).

Usage:
    python scripts/quality/triage_newline_explosion.py --dry-run
    python scripts/quality/triage_newline_explosion.py --write --verify
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
_QUALITY_DIR = Path(__file__).resolve().parent
if str(_QUALITY_DIR) not in sys.path:
    sys.path.insert(0, str(_QUALITY_DIR))

FM_RE = re.compile(r"^---\n(.*?)\n---", re.S)
APIS_BLOCK_RE = re.compile(r"apis:\n((?:\s*-\s*.+\n)+)")
HEADING_RE = re.compile(r"^##\s+(.+)$", re.M)


def get_frontmatter_and_body(text: str) -> tuple[str, str]:
    m = FM_RE.match(text)
    if not m:
        return "", text
    return text[: m.end()], text[m.end() :]


def get_apis(text: str) -> set[str]:
    fm, _ = get_frontmatter_and_body(text)
    apis = set()
    for am in APIS_BLOCK_RE.finditer(fm):
        for line in am.group(1).splitlines():
            line = line.strip()
            if line.startswith("-"):
                apis.add(line[1:].strip())
    return apis


def get_headings(body: str) -> set[str]:
    return set(HEADING_RE.findall(body))


@dataclass
class Classification:
    verdict: str  # "mechanical" or "stale"
    signal_used: str
    detail: str


def classify(en_text: str, tr_text: str) -> Classification:
    en_apis = get_apis(en_text)
    tr_apis = get_apis(tr_text)
    if en_apis and tr_apis:
        overlap = len(en_apis & tr_apis) / max(1, len(en_apis | tr_apis))
        verdict = "mechanical" if overlap >= 0.5 else "stale"
        return Classification(verdict, "apis_overlap", f"overlap={overlap:.2f}")

    _, en_body = get_frontmatter_and_body(en_text)
    _, tr_body = get_frontmatter_and_body(tr_text)
    en_headings = get_headings(en_body)
    tr_headings = get_headings(tr_body)
    if en_headings:
        ratio = len(tr_headings) / len(en_headings)
        # translated headings should roughly match EN's heading count;
        # a big mismatch (extra or missing sections) signals stale content
        if 0.7 <= ratio <= 1.3:
            verdict = "mechanical"
        else:
            verdict = "stale"
        return Classification(verdict, "heading_overlap", f"en={len(en_headings)} tr={len(tr_headings)} ratio={ratio:.2f}")

    en_nonblank = sum(1 for ln in en_body.splitlines() if ln.strip())
    tr_nonblank = sum(1 for ln in tr_body.splitlines() if ln.strip())
    line_ratio = tr_nonblank / max(1, en_nonblank)
    verdict = "mechanical" if line_ratio <= 1.3 else "stale"
    return Classification(verdict, "line_ratio", f"en_nonblank={en_nonblank} tr_nonblank={tr_nonblank} ratio={line_ratio:.2f}")


def collapse_blank_lines(text: str) -> tuple[str, bool]:
    fm, body = get_frontmatter_and_body(text)
    new_body = re.sub(r"\n{3,}", "\n\n", body)
    changed = new_body != body
    return fm + new_body, changed


@dataclass
class FixOutcome:
    file_path: str
    verdict: str
    changed: bool
    detail: str = ""


def process_file(tr_path: Path, en_path: Path, write: bool) -> FixOutcome:
    if not tr_path.exists() or not en_path.exists():
        return FixOutcome(str(tr_path), "error", False, "tr_path or en_path missing")

    tr_text = tr_path.read_text(encoding="utf-8", errors="replace")
    en_text = en_path.read_text(encoding="utf-8", errors="replace")

    classification = classify(en_text, tr_text)
    if classification.verdict == "stale":
        return FixOutcome(str(tr_path), "stale", False, f"{classification.signal_used}: {classification.detail}")

    new_text, changed = collapse_blank_lines(tr_text)
    if not changed:
        return FixOutcome(str(tr_path), "mechanical", False, "already clean (idempotent no-op)")

    if write:
        tr_path.write_text(new_text, encoding="utf-8")
    return FixOutcome(str(tr_path), "mechanical", True, classification.detail)


def load_targets(detail_csv: Path, site: str | None, family: str | None) -> list[dict]:
    rows = []
    with detail_csv.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["issue_type"] != "newline_explosion":
                continue
            if site and r["site_id"] != site:
                continue
            if family and r["family"] != family:
                continue
            rows.append(r)
    return rows


def verify_with_retries(verify_fn, tr_path, en_path, before_text, locale, site_id, attempts=3, base_delay=0.5):
    result = None
    for attempt in range(attempts):
        after_text = tr_path.read_text(encoding="utf-8", errors="replace")
        result = verify_fn("newline_explosion", tr_path, en_path, before_text, after_text, locale, site_id)
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
    ap.add_argument("--backlog-out", default="reports/audit/backlog_newline_explosion.csv")
    args = ap.parse_args()

    targets = load_targets(Path(args.detail_csv), args.site, args.family)
    print(f"Loaded {len(targets)} candidate files (site={args.site}, family={args.family})")

    verify_fn = None
    if args.verify:
        from verify_fix import verify_fix

        verify_fn = verify_fix

    n_mechanical_fixed = 0
    n_stale = 0
    n_noop = 0
    backlog_rows = []
    pending_recheck = []

    for i, t in enumerate(targets):
        if i >= args.batch_size:
            print(f"Batch size {args.batch_size} reached, stopping")
            break
        tr_path = Path(t["file_path"])
        en_path = Path(t["en_path"])
        before_text = tr_path.read_text(encoding="utf-8", errors="replace") if tr_path.exists() else ""

        outcome = process_file(tr_path, en_path, write=args.write)

        if outcome.verdict == "stale":
            n_stale += 1
            backlog_rows.append(
                {
                    "site_id": t["site_id"], "family": t.get("family", ""), "locale": t["locale"],
                    "file_path": t["file_path"], "en_path": t["en_path"], "issue_type": "newline_explosion",
                    "backlog_reason": f"root cause 2 (stale content): {outcome.detail}",
                }
            )
            continue
        if not outcome.changed:
            n_noop += 1
            continue
        n_mechanical_fixed += 1
        print(f"  [{'WRITE' if args.write else 'DRY-RUN'}] {tr_path} -- {outcome.detail}")

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
                print(f"CONFIRMED verify failure: {tr_path} -- {result.detector_detail}")

    if backlog_rows:
        backlog_path = Path(args.backlog_out)
        backlog_path.parent.mkdir(parents=True, exist_ok=True)
        file_exists = backlog_path.exists()
        with backlog_path.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["site_id", "family", "locale", "file_path", "en_path", "issue_type", "backlog_reason"])
            if not file_exists:
                w.writeheader()
            w.writerows(backlog_rows)
        print(f"Wrote/appended {len(backlog_rows)} rows to {backlog_path}")

    print(f"\nMechanical (fixed): {n_mechanical_fixed}, no-op: {n_noop}, stale (backlog): {n_stale}, confirmed verify failures: {errors}")
    real_split_pct = (n_mechanical_fixed + n_noop) / max(1, len(targets)) * 100
    print(f"Real mechanical/stale split observed: {real_split_pct:.0f}% mechanical, {100 - real_split_pct:.0f}% stale")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
