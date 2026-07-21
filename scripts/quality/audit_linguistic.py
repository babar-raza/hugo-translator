"""
Tier-2 Linguistic Audit — per-unit language detection across all aspose.org content.

Detectors:
  english_heading             — heading is pure ASCII in non-Latin locale
  purity_issue                — paragraph detected as English in non-Latin locale
  table_desc_not_translated   — description column cell is ASCII prose in non-Latin locale
  description_yaml_reverted   — frontmatter description field is English in non-Latin locale
  body_identical_to_en        — translated body byte-identical (or near-identical) to EN body

Output: data/audit/audit_linguistic.jsonl  (one JSON line per affected file)

TC-AUD-002 implementation.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Project-root setup so we can import src.*
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJ_ROOT = _SCRIPT_DIR.parent.parent
if str(_PROJ_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJ_ROOT))
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CONTENT_ROOT = Path(r"D:\onedrive\Documents\GitHub\aspose.org\content")
# TC-AUD-007: expanded default from 3 to 5 real content sites (excludes
# "templates" and websites.aspose.org/www.aspose.org, kept out of this pass).
SITES = [
    "reference.aspose.org",
    "docs.aspose.org",
    "kb.aspose.org",
    "blog.aspose.org",
    "products.aspose.org",
]

# Locales that use a non-Latin script — headings/descriptions in pure ASCII
# are almost certainly untranslated English.
NON_LATIN = frozenset(
    {"ar", "bg", "el", "fa", "he", "hi", "ja", "ko", "ru", "th", "uk", "vi", "zh"}
)

# Priority table (used in output to signal urgency for unit_heal.py)
PRIORITY: dict[str, int] = {
    "body_identical_to_en": 1,
    "purity_issue": 2,
    "english_heading": 2,
    "table_desc_not_translated": 3,
    "description_yaml_reverted": 3,
}

# ---------------------------------------------------------------------------
# Regex helpers
# ---------------------------------------------------------------------------
_FM_RE = re.compile(r"^---\n(.*?)\n---", re.S)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.M)
_PURE_ASCII_RE = re.compile(r"^[\x00-\x7F]*$")
_EN_PROSE_MIN_WORDS = 5

# Matches lines that are almost certainly code/shortcode/table and should be
# skipped when checking paragraph purity.
_SKIP_LINE_RE = re.compile(r"^```|^\{\{[<%%]|^\|")


def _get_body(content: str) -> str:
    m = _FM_RE.match(content)
    return content[m.end():] if m else content


def _get_paragraphs(body: str) -> list[str]:
    """Return non-blank, non-code-block paragraphs."""
    in_code = False
    paragraphs: list[str] = []
    current: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
        if in_code:
            current = []
            continue
        if not stripped:
            if current:
                text = " ".join(current).strip()
                if len(text) >= 20:
                    paragraphs.append(text)
                current = []
        else:
            current.append(stripped)
    if current:
        text = " ".join(current).strip()
        if len(text) >= 20:
            paragraphs.append(text)
    return paragraphs


def _get_table_desc_cells(body: str) -> list[str]:
    """Return description-column cells from markdown tables."""
    in_code = False
    cells: list[str] = []
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("```"):
            in_code = not in_code
        if in_code or not s.startswith("|"):
            continue
        parts = [c.strip() for c in s.strip("|").split("|")]
        if not parts:
            continue
        if all(re.fullmatch(r":?-+:?", c) for c in parts if c):
            continue  # separator row
        desc = parts[-1]
        desc_clean = re.sub(r"`[^`]+`", "", desc).strip()
        if len(desc_clean) >= 20:
            cells.append(desc_clean)
    return cells


# ---------------------------------------------------------------------------
# FastText-backed language detector (lazy-loaded singleton)
# ---------------------------------------------------------------------------
_detector = None
_FASTTEXT_CACHE_DIR = _PROJ_ROOT / "data" / "models" / "fasttext"


def _get_detector():
    global _detector
    if _detector is None:
        try:
            from src.translation_engine.language_detection.fasttext_detector import (
                FastTextDetector,
            )
            _detector = FastTextDetector(
                cache_dir=_FASTTEXT_CACHE_DIR,
                min_confidence=0.70,
                auto_download=True,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] FastText unavailable, using ASCII heuristic only: {exc}")
            _detector = None
    return _detector


def _is_english_text(text: str, locale: str) -> bool:
    """
    Return True if `text` looks like English in a non-Latin locale.

    Uses FastText when available; falls back to pure-ASCII heuristic.
    Only meaningful for NON_LATIN locales — Latin-script locales return False.
    """
    if locale not in NON_LATIN:
        return False
    if len(text.strip()) < 10:
        return False
    detector = _get_detector()
    if detector is not None:
        try:
            lang, conf = detector.detect(text)
            return lang == "en" and conf >= 0.70
        except Exception:  # noqa: BLE001
            pass
    # ASCII fallback: if 80%+ of word characters are ASCII letters, flag it
    words = text.split()
    if len(words) < _EN_PROSE_MIN_WORDS:
        return False
    ascii_words = sum(1 for w in words if re.match(r"^[A-Za-z0-9\-'.,;]+$", w))
    return ascii_words / len(words) >= 0.80


# ---------------------------------------------------------------------------
# Per-file detection
# ---------------------------------------------------------------------------

def check_file(
    en_content: str,
    tr_content: str,
    locale: str,
) -> dict[str, list[int]]:
    """
    Return a dict of {issue_type: [unit_indices]} for the given file pair.
    unit_index is the 0-based position within the detected unit list
    (paragraph index for purity_issue, heading index for english_heading, etc.).
    """
    issues: dict[str, list[int]] = defaultdict(list)

    en_body = _get_body(en_content)
    tr_body = _get_body(tr_content)

    # ---- body_identical_to_en ----
    en_body_stripped = en_body.strip()
    tr_body_stripped = tr_body.strip()
    if (
        en_body_stripped
        and tr_body_stripped
        and len(en_body_stripped) >= 50
        and en_body_stripped == tr_body_stripped
    ):
        issues["body_identical_to_en"].append(0)

    if locale not in NON_LATIN:
        # For Latin-script locales we only check body_identical; the other
        # checks rely on non-ASCII script detection which doesn't apply.
        return dict(issues)

    # ---- english_heading ----
    for idx, m in enumerate(_HEADING_RE.finditer(tr_body)):
        heading_text = m.group(2).strip()
        # Strip inline backticks so `ClassName` doesn't trigger false positive
        heading_clean = re.sub(r"`[^`]+`", "", heading_text).strip()
        if not heading_clean:
            continue
        if _PURE_ASCII_RE.match(heading_clean) and len(heading_clean) >= 3:
            issues["english_heading"].append(idx)

    # ---- purity_issue (per-paragraph fasttext detection) ----
    tr_paragraphs = _get_paragraphs(tr_body)
    for idx, para in enumerate(tr_paragraphs):
        # Skip lines that look like code, tables, or shortcodes
        if _SKIP_LINE_RE.match(para):
            continue
        if _is_english_text(para, locale):
            issues["purity_issue"].append(idx)

    # ---- table_desc_not_translated ----
    tr_cells = _get_table_desc_cells(tr_body)
    for idx, cell in enumerate(tr_cells):
        if _PURE_ASCII_RE.match(cell) and len(cell.split()) >= _EN_PROSE_MIN_WORDS:
            issues["table_desc_not_translated"].append(idx)

    # ---- description_yaml_reverted ----
    # Parses frontmatter via HugoParser rather than a first-line regex
    # (TC-HT-001), so multi-line folded/literal scalars compare by their
    # full value instead of being truncated to the first physical line.
    from frontmatter_utils import get_frontmatter_field

    desc_val = get_frontmatter_field(tr_content, "description")
    if desc_val:
        desc_val = desc_val.strip()
        if _is_english_text(desc_val, locale) or (
            _PURE_ASCII_RE.match(desc_val) and len(desc_val.split()) >= 3
        ):
            issues["description_yaml_reverted"].append(0)

    return dict(issues)


# ---------------------------------------------------------------------------
# Main scan loop
# ---------------------------------------------------------------------------

def scan(
    sites: list[str],
    locales_filter: list[str] | None,
    output_path: Path,
    resume: bool,
) -> None:
    # Load already-processed paths for --resume
    resumed_paths: set[str] = set()
    if resume and output_path.exists():
        with output_path.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    entry = json.loads(line)
                    resumed_paths.add(entry.get("file_path", ""))
                except Exception:  # noqa: BLE001
                    pass
        print(f"[resume] Skipping {len(resumed_paths):,} already-processed files")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    out_mode = "a" if resume else "w"
    total_files = 0
    total_issues = 0
    issue_counts: dict[str, int] = defaultdict(int)

    with output_path.open(out_mode, encoding="utf-8") as out_fh:
        for site in sites:
            site_root = CONTENT_ROOT / site
            en_root = site_root / "en"
            if not en_root.exists():
                print(f"  Skipping {site} (no en/ dir)")
                continue

            en_files = sorted(en_root.rglob("*.md"))
            all_locales = sorted(
                d.name
                for d in site_root.iterdir()
                if d.is_dir()
                and d.name != "en"
                and 2 <= len(d.name) <= 5
                and d.name.replace("-", "").isalpha()
            )
            if locales_filter:
                all_locales = [lc for lc in all_locales if lc in locales_filter]

            print(
                f"\n{site}: {len(en_files):,} EN files x {len(all_locales)} locales",
                flush=True,
            )

            done = 0
            for en_path in en_files:
                done += 1
                if done % 1000 == 0:
                    print(f"  ... {done}/{len(en_files)} source files", flush=True)

                rel = en_path.relative_to(en_root)
                try:
                    en_content = en_path.read_text(encoding="utf-8", errors="replace")
                except Exception:  # noqa: BLE001
                    continue

                for locale in all_locales:
                    tr_path = site_root / locale / rel
                    total_files += 1
                    if not tr_path.exists():
                        continue
                    if str(tr_path) in resumed_paths:
                        continue

                    try:
                        tr_content = tr_path.read_text(encoding="utf-8", errors="replace")
                    except Exception:  # noqa: BLE001
                        continue

                    detected = check_file(en_content, tr_content, locale)
                    if not detected:
                        continue

                    file_issues = []
                    max_priority = 9
                    for issue_type, unit_indices in detected.items():
                        if not unit_indices:
                            continue
                        prio = PRIORITY.get(issue_type, 4)
                        file_issues.append(
                            {
                                "type": issue_type,
                                "unit_indices": unit_indices,
                                "priority": prio,
                            }
                        )
                        max_priority = min(max_priority, prio)
                        issue_counts[issue_type] += 1

                    if file_issues:
                        record = {
                            "file_path": str(tr_path),
                            "en_path": str(en_path),
                            "locale": locale,
                            "site_id": site,
                            "issues": file_issues,
                            "max_priority": max_priority,
                        }
                        out_fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                        total_issues += 1

    print(f"\n=== Linguistic audit complete ({datetime.now().strftime('%H:%M:%S')}) ===")
    print(f"Files scanned: {total_files:,}")
    print(f"Files with issues: {total_issues:,}")
    print("Issue counts:")
    for issue_type, cnt in sorted(issue_counts.items(), key=lambda x: -x[1]):
        prio = PRIORITY.get(issue_type, 4)
        print(f"  P{prio} {issue_type}: {cnt:,}")
    print(f"\nOutput: {output_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Tier-2 linguistic audit: per-unit language detection."
    )
    parser.add_argument(
        "--sites",
        nargs="+",
        default=SITES,
        help="Sites to scan (default: all 3)",
    )
    parser.add_argument(
        "--locales",
        nargs="+",
        default=None,
        help="Locales to scan (default: all non-EN locales found on disk)",
    )
    parser.add_argument(
        "--output",
        default="data/audit/audit_linguistic.jsonl",
        help="Output JSONL path (default: data/audit/audit_linguistic.jsonl)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip files already written to the output file",
    )
    args = parser.parse_args()

    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = _PROJ_ROOT / output_path

    scan(
        sites=args.sites,
        locales_filter=args.locales,
        output_path=output_path,
        resume=args.resume,
    )


if __name__ == "__main__":
    main()
