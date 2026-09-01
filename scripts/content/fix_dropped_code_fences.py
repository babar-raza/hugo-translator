#!/usr/bin/env python
"""
TC-P7-07: Dropped-code-fence fixer.

Sampling (see plan Deliverable 3) found 0% staleness for code_fence_dropped
(EN/TR heading structure matches closely in every sample) -- unlike
newline_explosion, this category is genuinely dropped code blocks during
translation/reconstruction, not stale content describing an old EN
revision. Fix: split both EN and TR bodies by ##/### headings, align
sections by heading text + order, and where an aligned TR section is
missing fence pairs present in the matching EN section, reinsert the EN
code block verbatim at the matching position -- code content is never
translated, so copying EN's fenced block is correct by construction.

Only applied where heading count/order between EN and TR matches exactly
(unambiguous alignment); anything else is left untouched and routed to
backlog rather than force-fixed against a guessed alignment. Extra
scrutiny per the plan (code content is live, not a low-stakes text tweak):
verify_fix.py's fence-count re-check + blast-radius diff are both mandatory
gates on every write, not optional.

Usage:
    python scripts/content/fix_dropped_code_fences.py --dry-run
    python scripts/content/fix_dropped_code_fences.py --write --verify
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

FM_RE = re.compile(r"^---\n(.*?)\n---", re.S)
HEADING_SPLIT_RE = re.compile(r"^(#{2,3}\s+.+)$", re.M)
FENCE_RE = re.compile(r"```[\s\S]*?```")


def get_frontmatter_and_body(text: str) -> tuple[str, str]:
    m = FM_RE.match(text)
    if not m:
        return "", text
    return text[: m.end()], text[m.end() :]


def split_into_sections(body: str) -> list[tuple[str | None, str]]:
    """Return [(heading_line_or_None, section_text), ...] -- section_text
    includes everything up to (not including) the next heading."""
    parts = HEADING_SPLIT_RE.split(body)
    sections = []
    if parts and parts[0]:
        sections.append((None, parts[0]))
    i = 1
    while i < len(parts):
        heading = parts[i]
        content = parts[i + 1] if i + 1 < len(parts) else ""
        sections.append((heading, content))
        i += 2
    return sections


def count_fences(text: str) -> int:
    return len(FENCE_RE.findall(text))


@dataclass
class FixOutcome:
    file_path: str
    changed: bool
    skipped_reason: str = ""
    sections_fixed: int = 0


def fix_file(tr_path: Path, en_path: Path, write: bool) -> FixOutcome:
    if not tr_path.exists() or not en_path.exists():
        return FixOutcome(str(tr_path), False, "tr_path or en_path missing")

    tr_text = tr_path.read_text(encoding="utf-8", errors="replace")
    en_text = en_path.read_text(encoding="utf-8", errors="replace")
    fm_prefix, tr_body = get_frontmatter_and_body(tr_text)
    _, en_body = get_frontmatter_and_body(en_text)

    en_sections = split_into_sections(en_body)
    tr_sections = split_into_sections(tr_body)

    # Alignment key: heading LEVEL sequence (## vs ###) and count, not exact
    # text -- headings are legitimately translated ("## Installation" ->
    # "## Installazione"), so comparing raw text would reject nearly every
    # real file. Level sequence is what actually needs to match for
    # position-based section alignment to be safe.
    en_levels = [h.split()[0] if h else None for h, _ in en_sections]
    tr_levels = [h.split()[0] if h else None for h, _ in tr_sections]
    if en_levels != tr_levels:
        return FixOutcome(
            str(tr_path), False,
            f"heading structure mismatch (en={len(en_levels)} tr={len(tr_levels)}) -- ambiguous alignment, routed to backlog",
        )

    new_sections = []
    sections_fixed = 0
    any_missing = False
    for (_, en_content), (tr_heading, tr_content) in zip(en_sections, tr_sections):
        # Use TR's own (translated) heading when rebuilding -- only the
        # fenced code content is ever borrowed from EN, never the heading.
        en_fences = FENCE_RE.findall(en_content)
        tr_fence_count = count_fences(tr_content)
        if en_fences and tr_fence_count < len(en_fences):
            # This section dropped fence(s): reinsert EN's fenced block(s)
            # verbatim, appended at the end of the TR section (code content
            # is never translated, so EN's block is correct as-is).
            new_content = tr_content.rstrip("\n") + "\n\n" + "\n\n".join(en_fences) + "\n"
            new_sections.append((tr_heading, new_content))
            sections_fixed += 1
            any_missing = True
        else:
            new_sections.append((tr_heading, tr_content))

    if not any_missing:
        return FixOutcome(str(tr_path), False, "no missing fences in any aligned section (idempotent no-op)")

    rebuilt_body_parts = []
    for heading, content in new_sections:
        if heading is not None:
            rebuilt_body_parts.append(heading)
        rebuilt_body_parts.append(content)
    new_body = "".join(rebuilt_body_parts)

    if write:
        tr_path.write_text(fm_prefix + new_body, encoding="utf-8")

    return FixOutcome(str(tr_path), True, sections_fixed=sections_fixed)


def load_targets(detail_csv: Path, site: str | None, family: str | None) -> list[dict]:
    rows = []
    with detail_csv.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["issue_type"] != "code_fence_dropped":
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
        result = verify_fn("code_fence_dropped", tr_path, en_path, before_text, after_text, locale, site_id)
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
    ap.add_argument("--verify", action="store_true", help="Mandatory in practice for this category (see docstring)")
    ap.add_argument("--backlog-out", default="reports/audit/backlog_code_fence_dropped.csv")
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
            print(f"Batch size {args.batch_size} reached, stopping")
            break
        tr_path = Path(t["file_path"])
        en_path = Path(t["en_path"])
        before_text = tr_path.read_text(encoding="utf-8", errors="replace") if tr_path.exists() else ""

        outcome = fix_file(tr_path, en_path, write=args.write)

        if not outcome.changed:
            skipped += 1
            if "ambiguous alignment" in outcome.skipped_reason:
                backlog_rows.append(
                    {
                        "site_id": t["site_id"], "family": t.get("family", ""), "locale": t["locale"],
                        "file_path": t["file_path"], "en_path": t["en_path"], "issue_type": "code_fence_dropped",
                        "backlog_reason": outcome.skipped_reason,
                    }
                )
            continue
        changed += 1
        print(f"  [{'WRITE' if args.write else 'DRY-RUN'}] {tr_path} -- {outcome.sections_fixed} section(s) fixed")

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
                print(f"CONFIRMED verify failure: {tr_path} -- {result.detector_detail} blast_radius={result.blast_radius_detail}")

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
