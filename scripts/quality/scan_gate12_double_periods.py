"""TC-APT-009 step 3: measure the Gate-12 double-period population in the live content repo.

For every ledger cell whose target exists, compare source vs target for `..` occurrences that
are NOT ellipses, NOT inside fenced code / inline code spans, NOT inside links/URLs/shortcodes.
Classifies each hit so the producing stage can be identified (prose join, list item, table cell,
heading, frontmatter scalar).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from src.workers.work_ledger import WorkLedger

REPO = Path("D:/onedrive/Documents/GitHub/aspose.org")
FENCE = re.compile(r"^```[\s\S]*?^```", re.M)
INLINE = re.compile(r"`[^`\n]*`")
LINKS = re.compile(r"\]\([^)]*\)|https?://\S+|\{\{[<%][\s\S]*?[>%]\}\}|<[^>\n]+>")
DOTS = re.compile(r"(?<!\.)\.\.(?!\.)")


def strip_protected(text: str) -> str:
    text = FENCE.sub(lambda m: " " * len(m.group(0)), text)
    text = INLINE.sub(lambda m: " " * len(m.group(0)), text)
    return LINKS.sub(lambda m: " " * len(m.group(0)), text)


def classify_line(line: str) -> str:
    s = line.lstrip()
    if s.startswith("|"):
        return "table_row"
    if s.startswith("#"):
        return "heading"
    if s.startswith(("-", "*", "+")) or re.match(r"^\d+\.", s):
        return "list_item"
    return "prose"


def main() -> int:
    counts: Counter[str] = Counter()
    kinds: Counter[str] = Counter()
    langs: Counter[str] = Counter()
    samples: list[dict] = []
    with WorkLedger() as ledger:
        rows = [r for r in ledger.query() if r["target_exists"] and r["eligibility_state"] != "EXCLUDED_BY_PROFILE"]
    counts["cells_with_target"] = len(rows)
    src_cache: dict[str, str] = {}
    for row in rows:
        tgt_path = REPO / row["expected_output_path"]
        try:
            tgt = tgt_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            counts["target_unreadable"] += 1
            continue
        body = strip_protected(tgt)
        hits = list(DOTS.finditer(body))
        if not hits:
            continue
        src_rel = row["source_path"]
        if src_rel not in src_cache:
            try:
                src_cache[src_rel] = strip_protected((REPO / src_rel).read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                src_cache[src_rel] = ""
        if DOTS.search(src_cache[src_rel]):
            counts["source_also_has_dots"] += 1
            continue
        counts["defective_targets"] += 1
        langs[row["target_lang"]] += 1
        for m in hits[:3]:
            line_start = body.rfind("\n", 0, m.start()) + 1
            line_end = body.find("\n", m.end())
            line = tgt[line_start : line_end if line_end != -1 else len(tgt)]
            kind = classify_line(line)
            kinds[kind] += 1
            if len(samples) < 25:
                samples.append({"path": row["expected_output_path"], "lang": row["target_lang"], "kind": kind, "excerpt": line.strip()[:160]})
    report = {
        "counts": dict(counts),
        "hit_kinds": dict(kinds),
        "by_lang_top": langs.most_common(10),
        "samples": samples,
    }
    Path("data/quality/gate12_double_period_scan.json").parent.mkdir(parents=True, exist_ok=True)
    Path("data/quality/gate12_double_period_scan.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "samples"}, indent=2, ensure_ascii=False))
    for s in samples[:8]:
        print(s["kind"], "|", s["lang"], "|", s["excerpt"][:120])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
