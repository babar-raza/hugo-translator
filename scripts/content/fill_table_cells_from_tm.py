#!/usr/bin/env python
"""
TC-P7-08: Table-cell classifier + TM fill.

table_desc_not_translated has no mechanical text fix -- a missing
translation is missing translation, not corruption. The only lever
available without an LLM/MT call is reusing an EXISTING exact TM cache hit
(a plain cache lookup, not a new inference call).

Classification first ("does it fit i18n or not," per the mission's design):
a flagged description cell might be genuine untranslated prose, or it might
be legitimate technical passthrough (type names, identifiers -- the same
shape as the Gate 31 "LE entry"/"DER bytes" case). This script flags cells
whose content looks like a bare identifier/type token (short, no spaces,
matches a common type-name shape) as passthrough candidates rather than
translation gaps, and only attempts TM fill on the remainder.

Usage:
    python scripts/content/fill_table_cells_from_tm.py --dry-run
    python scripts/content/fill_table_cells_from_tm.py --write --verify
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

from src.tm.l2_persistent import L2PersistentTM  # noqa: E402
from src.tm import lmdb_registry  # noqa: E402

FM_RE = re.compile(r"^---\n(.*?)\n---", re.S)
TYPE_TOKEN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.<>\[\]]{0,40}$")  # e.g. "str", "List<int>", "PropertyCollection"


def get_body(text: str) -> str:
    m = FM_RE.match(text)
    return text[m.end() :] if m else text


def looks_like_passthrough_identifier(cell_text: str) -> bool:
    """A single bare token with no spaces (a type name / identifier) is
    legitimate technical passthrough, not an untranslated sentence."""
    stripped = cell_text.strip().strip("`")
    if " " in stripped or not stripped:
        return False
    return bool(TYPE_TOKEN_RE.match(stripped))


@dataclass
class CellFillResult:
    file_path: str
    total_flagged_cells: int
    passthrough_cells: int
    tm_filled_cells: int
    still_missing_cells: int
    changed: bool


def find_table_rows(body: str) -> list[dict]:
    """Return data rows (line_index, line_text, cells), excluding both
    separator rows ("|---|---|") AND header rows.

    Header exclusion matters: a header row's last cell (e.g. "Description")
    would otherwise be treated as a real description value. Detected as any
    non-separator row immediately followed by a separator row (the
    standard GFM table shape), not by raw position -- robust to any number
    of prose lines before the table.
    """
    in_code = False
    candidates = []
    for i, line in enumerate(body.splitlines()):
        s = line.strip()
        if s.startswith("```"):
            in_code = not in_code
            continue
        if in_code or not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 2:
            continue
        is_separator = all(re.fullmatch(r":?-+:?", c) for c in cells if c)
        candidates.append({"index": i, "line": line, "cells": cells, "is_separator": is_separator})

    rows = []
    for j, r in enumerate(candidates):
        if r["is_separator"]:
            continue
        is_header = j + 1 < len(candidates) and candidates[j + 1]["is_separator"]
        if is_header:
            continue
        rows.append(r)
    return rows


def process_file(tr_path: Path, en_path: Path, tm: L2PersistentTM, site_id: str, locale: str, write: bool) -> CellFillResult:
    tr_text = tr_path.read_text(encoding="utf-8", errors="replace")
    en_text = en_path.read_text(encoding="utf-8", errors="replace")
    tr_body = get_body(tr_text)
    en_body = get_body(en_text)

    tr_rows = find_table_rows(tr_body)
    en_rows = find_table_rows(en_body)
    # Align by first-cell KEY (the row's identifier -- a class member/enum
    # value name, never translated), not by line position. Positional
    # (line-index or even ordinal-row-count) alignment breaks whenever EN
    # and TR prose *before* the table has a different line count (routine,
    # since translated text is rarely the same length) -- confirmed root
    # cause of a real data-corruption incident mid-mission: rows silently
    # matched to the wrong EN row and got the wrong "translation" (in one
    # case, literally the table header word "Description") written in.
    # A duplicated first-cell key (confirmed real, e.g. some large reference
    # _index.md tables legitimately list the same identifier -- "Axis" --
    # twice) makes key-based lookup ambiguous: silently keeping "whichever
    # row wins the dict" can match a row to the WRONG sibling's
    # description. Ambiguous keys are marked AMBIGUOUS and never filled --
    # same "don't guess, route to backlog" principle as the link-path fixer.
    en_desc_by_key: dict[str, str | None] = {}
    for r in en_rows:
        if not r["cells"]:
            continue
        key = r["cells"][0]
        if key in en_desc_by_key:
            en_desc_by_key[key] = None  # ambiguous
        else:
            en_desc_by_key[key] = r["cells"][-1]

    body_start = len(tr_text) - len(tr_body)

    total_flagged = 0
    passthrough = 0
    filled = 0
    still_missing = 0
    changed = False

    body_lines = tr_body.splitlines(keepends=True)
    for row in tr_rows:
        idx = row["index"]
        line = row["line"]
        cells = row["cells"]
        if len(cells) < 2:
            continue
        desc_clean = re.sub(r"`[^`]+`", "", cells[-1]).strip()
        if len(desc_clean) < 20:
            continue
        words = desc_clean.split()
        lower_en_words = sum(1 for w in words if re.fullmatch(r"[a-z]{3,}", w))
        is_english_like = len(words) >= 4 and lower_en_words / len(words) >= 0.4
        if not is_english_like:
            continue

        total_flagged += 1
        en_desc = en_desc_by_key.get(cells[0], "")
        if looks_like_passthrough_identifier(cells[-1]):
            passthrough += 1
            continue

        tm_entry = tm.exact_lookup(site_id=site_id, src_lang="en", tgt_lang=locale, text=en_desc) if en_desc else None
        if tm_entry is None:
            still_missing += 1
            continue

        new_line = line.rstrip("\n")
        # Rebuild the row with the last cell replaced by the TM translation.
        parts = new_line.split("|")
        # parts[0] is empty (leading "|"), parts[-1] is empty (trailing "|") typically
        if len(parts) >= 3:
            parts[-2] = f" {tm_entry.translation.strip()} "
            body_lines[idx] = "|".join(parts) + "\n"
            changed = True
            filled += 1
        else:
            still_missing += 1

    if changed and write:
        new_body = "".join(body_lines)
        fm_prefix = tr_text[:body_start]
        tr_path.write_text(fm_prefix + new_body, encoding="utf-8")

    return CellFillResult(str(tr_path), total_flagged, passthrough, filled, still_missing, changed)


def load_targets(detail_csv: Path, site: str | None, family: str | None) -> list[dict]:
    rows = []
    with detail_csv.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["issue_type"] != "table_desc_not_translated":
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--detail-csv", default="reports/audit/findings_detail.csv")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--site", default=None)
    ap.add_argument("--family", default=None)
    ap.add_argument("--batch-size", type=int, default=1000)
    ap.add_argument("--l2-path", default="data/tm/l2.lmdb")
    ap.add_argument("--backlog-out", default="reports/audit/backlog_table_desc_not_translated.csv")
    args = ap.parse_args()

    targets = load_targets(Path(args.detail_csv), args.site, args.family)
    print(f"Loaded {len(targets)} candidate files (site={args.site}, family={args.family})")

    lmdb_registry.set_project_root(_PROJECT_ROOT)
    tm = L2PersistentTM(_PROJECT_ROOT / args.l2_path)

    n_files_changed = 0
    total_passthrough = 0
    total_filled = 0
    total_still_missing = 0
    backlog_rows = []

    for i, t in enumerate(targets):
        if i >= args.batch_size:
            print(f"Batch size {args.batch_size} reached, stopping")
            break
        tr_path = Path(t["file_path"])
        en_path = Path(t["en_path"])
        if not tr_path.exists() or not en_path.exists():
            continue

        result = process_file(tr_path, en_path, tm, t["site_id"], t["locale"], write=args.write)
        total_passthrough += result.passthrough_cells
        total_filled += result.tm_filled_cells
        total_still_missing += result.still_missing_cells

        if result.changed:
            n_files_changed += 1
            print(f"  [{'WRITE' if args.write else 'DRY-RUN'}] {tr_path} -- filled {result.tm_filled_cells}, "
                  f"passthrough {result.passthrough_cells}, still missing {result.still_missing_cells}")
        if result.still_missing_cells:
            backlog_rows.append(
                {
                    "site_id": t["site_id"], "family": t.get("family", ""), "locale": t["locale"],
                    "file_path": t["file_path"], "en_path": t["en_path"], "issue_type": "table_desc_not_translated",
                    "backlog_reason": f"{result.still_missing_cells} cell(s) with no TM cache hit -- needs real translation",
                }
            )

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

    print(f"\nFiles changed: {n_files_changed}")
    print(f"Cells: passthrough (no action) {total_passthrough}, TM-filled {total_filled}, still missing (backlog) {total_still_missing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
