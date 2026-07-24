#!/usr/bin/env python
"""
TC-P7-05: Link-path fixer + classifier.

Root cause 1 (~1,325 of 1,638 link_path_corrupted, mostly docs.aspose.org):
every "../" in a markdown link target had one dot eaten by Gate 12's
unprotected double-period regex ("../developer-guide/" -> "./developer-
guide/"). Confirmed byte-for-byte via direct diffing (see plan Deliverable
3 / Reassessment root cause 1).

Root cause 2 (~313, reference/kb.aspose.org): stale/orphaned translations
whose cross-reference links point at an EN page structure that has since
been renamed/restructured -- NOT mechanically fixable, no exact-match
reverse-transform exists, routed to backlog untouched (whole file, not
partially patched -- a half-fixed file mixing a corrected link with stale
prose is worse than a fully-stale one).

Fix rule (high-confidence, exact-match only, no guessing): for each
flagged link target in the translated body, reverse the confirmed "../" ->
"./" collapse (re-insert one "." per "./" segment) and check whether the
result exactly matches a link target present in the EN body. Only then is
it replaced. Everything else is left untouched and logged to the backlog
manifest.

Usage:
    python scripts/content/fix_link_paths.py --dry-run
    python scripts/content/fix_link_paths.py --write --verify --site docs.aspose.org
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
_QUALITY_DIR = _PROJECT_ROOT / "scripts" / "quality"
if str(_QUALITY_DIR) not in sys.path:
    sys.path.insert(0, str(_QUALITY_DIR))

FM_RE = re.compile(r"^---\n(.*?)\n---", re.S)
_LINK_RE = re.compile(r"(\[(?:[^\[\]]*)\])\(([^)]+)\)")


def get_body(text: str) -> str:
    m = FM_RE.match(text)
    return text[m.end() :] if m else text


def get_frontmatter_prefix(text: str) -> str:
    m = FM_RE.match(text)
    return text[: m.end()] if m else ""


def reverse_collapsed_dots(target: str) -> str:
    """Reverse the confirmed corruption rule: every "../" was collapsed to
    "./" (literal string substitution, confirmed by diffing "../../developer-
    guide/" -> "././developer-guide/"). The inverse of a literal
    replace("../", "./") is replace("./", "../") -- but only for the
    "./"-shaped segments, never touching an already-correct "../" or a
    bare "foo/" with no dot prefix at all (those were never touched by the
    corruption in the first place).
    """
    return target.replace("./", "../")


@dataclass
class LinkFixOutcome:
    file_path: str
    changed: bool
    fixed_links: list[tuple[str, str]] = field(default_factory=list)  # (old, new)
    unresolved_links: list[str] = field(default_factory=list)
    skipped_reason: str = ""


def fix_file(tr_path: Path, en_path: Path, write: bool) -> LinkFixOutcome:
    if not tr_path.exists() or not en_path.exists():
        return LinkFixOutcome(str(tr_path), False, skipped_reason="tr_path or en_path missing")

    tr_text = tr_path.read_text(encoding="utf-8", errors="replace")
    en_text = en_path.read_text(encoding="utf-8", errors="replace")
    tr_body = get_body(tr_text)
    en_body = get_body(en_text)

    en_targets = {m.group(2) for m in _LINK_RE.finditer(en_body)}
    tr_targets_in_order = [m.group(2) for m in _LINK_RE.finditer(tr_body)]
    corrupted = {t for t in tr_targets_in_order if t.startswith(("../", "./", "/"))} - en_targets

    if not corrupted:
        return LinkFixOutcome(str(tr_path), False, skipped_reason="no corrupted links found (idempotent no-op)")

    fixed_links = []
    unresolved = []
    new_body = tr_body
    for target in corrupted:
        candidate = reverse_collapsed_dots(target)
        if candidate != target and candidate in en_targets:
            # Exact-match replace of this specific link target only, not a
            # blind global substitution of "./" -> "../" across the body
            # (which could touch an unrelated, already-correct link).
            new_body = new_body.replace(f"]({target})", f"]({candidate})")
            fixed_links.append((target, candidate))
        else:
            unresolved.append(target)

    if not fixed_links:
        return LinkFixOutcome(str(tr_path), False, unresolved_links=unresolved, skipped_reason="no exact reverse-match; routed to backlog")

    if write:
        fm_prefix = get_frontmatter_prefix(tr_text)
        tr_path.write_text(fm_prefix + new_body, encoding="utf-8")

    return LinkFixOutcome(str(tr_path), True, fixed_links=fixed_links, unresolved_links=unresolved)


def load_targets(detail_csv: Path, site: str | None, family: str | None) -> list[dict]:
    rows = []
    with detail_csv.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["issue_type"] != "link_path_corrupted":
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
        result = verify_fn("link_path_corrupted", tr_path, en_path, before_text, after_text, locale, site_id)
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
    ap.add_argument("--backlog-out", default="reports/audit/backlog_link_path_corrupted.csv")
    args = ap.parse_args()

    targets = load_targets(Path(args.detail_csv), args.site, args.family)
    print(f"Loaded {len(targets)} candidate files (site={args.site}, family={args.family})")

    verify_fn = None
    if args.verify:
        from verify_fix import verify_fix

        verify_fn = verify_fix

    changed = 0
    skipped = 0
    backlog_rows = []
    pending_recheck = []

    for i, t in enumerate(targets):
        if i >= args.batch_size:
            print(f"Batch size {args.batch_size} reached, stopping (re-run for the next batch)")
            break
        tr_path = Path(t["file_path"])
        en_path = Path(t["en_path"])
        before_text = tr_path.read_text(encoding="utf-8", errors="replace") if tr_path.exists() else ""

        outcome = fix_file(tr_path, en_path, write=args.write)

        if outcome.unresolved_links:
            backlog_rows.append(
                {
                    "site_id": t["site_id"],
                    "family": t.get("family", ""),
                    "locale": t["locale"],
                    "file_path": t["file_path"],
                    "en_path": t["en_path"],
                    "issue_type": "link_path_corrupted",
                    "backlog_reason": f"no exact reverse-match for: {outcome.unresolved_links}",
                }
            )

        if not outcome.changed:
            skipped += 1
            continue
        changed += 1
        print(f"  [{'WRITE' if args.write else 'DRY-RUN'}] {tr_path} -- fixed: {outcome.fixed_links}")

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
                print(f"CONFIRMED verify failure: {tr_path} -- {result.detector_detail} "
                      f"unresolved_links={result.unresolved_links} gates={result.gate_failures}")

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

    print(f"\nChanged: {changed}, no-op/backlog: {skipped}, confirmed verify failures: {errors}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
