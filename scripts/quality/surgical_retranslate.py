"""
surgical_retranslate.py — Full-disk scan repair for reference.aspose.org translations.

Scans ALL translated files on disk (not JSONL-dependent) and applies surgical repairs:

No-GPU repairs (applied immediately with --apply):
  - inline_code_translation : Restore EN backtick spans (pure string replace)
  - duplicate_content       : Remove repeated paragraphs
  - double_period           : Replace ".." with "." outside code blocks

Model-required repairs (detected but require --apply-model + GPU):
  - description_hallucination : Description >3x source length or <0.3x
  - table_row_corruption      : Table row count mismatch >50%
  - mixed_language            : English paragraphs in non-Latin target
  - heading_count_mismatch    : Extra or missing headings vs source
  - eu_hallucination          : GDPR/cookie text not in source
  - newline_explosion         : >2.5x newline count vs source

Usage:
  python scripts/quality/surgical_retranslate.py --dry-run          # default
  python scripts/quality/surgical_retranslate.py --apply            # no-GPU repairs
  python scripts/quality/surgical_retranslate.py --dry-run --locales ar,bg,ru
  python scripts/quality/surgical_retranslate.py --apply --issue-type inline_code_translation
  python scripts/quality/surgical_retranslate.py --dry-run --max-files 500
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# Content root resolution
# ---------------------------------------------------------------------------

SITE = "reference.aspose.org"
EN_LOCALE = "en"

LATIN_SCRIPT_LANGS = frozenset({
    "af", "az", "ca", "cs", "da", "de", "en", "es", "et", "fi",
    "fr", "ga", "hr", "hu", "id", "it", "lt", "lv", "ms", "nl",
    "no", "pl", "pt", "ro", "sk", "sl", "sr", "sv", "tr", "vi",
})

_API_HEADING_TERMS = frozenset({
    "Name", "Type", "Description", "Returns", "Parameters",
    "Properties", "Methods", "Fields", "Constructors", "Events",
    "Exceptions", "Remarks", "Examples", "See Also", "Inheritance",
    "Implements", "Namespace", "Assembly", "Syntax", "Value",
})

_EU_HALLUCINATION_PATTERNS = [
    re.compile(r"(?:cookie|GDPR|General Data Protection|privacy policy|data protection)", re.IGNORECASE),
    re.compile(r"(?:European Union|EU regulation|DSGVO|Datenschutz)", re.IGNORECASE),
]


def _resolve_content_root() -> Path:
    env = os.environ.get("ASPOSE_ORG_CONTENT")
    if env:
        p = Path(env)
        if p.exists():
            return p
    defaults = [
        Path(r"C:\Users\prora\OneDrive\Documents\GitHub\aspose.org\content"),
        Path(r"D:\onedrive\Documents\GitHub\aspose.org\content"),
    ]
    for p in defaults:
        if p.exists():
            return p
    raise FileNotFoundError(
        "Cannot locate aspose.org content root. Set ASPOSE_ORG_CONTENT env var."
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_body(content: str) -> str:
    """Strip frontmatter (--- ... ---) and return the body."""
    if not content.startswith("---"):
        return content
    end = content.find("\n---", 4)
    if end == -1:
        return content
    return content[end + 4:]


def _strip_code_blocks(text: str) -> str:
    """Remove fenced code blocks from text (for line-level analysis)."""
    return re.sub(r"```[\s\S]*?```", "", text)


def _get_table_row_count(text: str) -> int:
    """Count table rows (lines starting with |) in text, excluding code blocks."""
    clean = _strip_code_blocks(text)
    return sum(1 for line in clean.splitlines() if line.strip().startswith("|"))


# ---------------------------------------------------------------------------
# Corruption detectors
# ---------------------------------------------------------------------------


def _detect_inline_code_translation(
    en_content: str, tr_content: str
) -> list[tuple[int, str, str, str]]:
    """
    Detect lines where inline code spans were translated.

    Returns list of (line_index, en_line, tr_line, issue_type).
    Only flags lines where an EN ASCII span became non-ASCII in translation.
    """
    en_body = _get_body(en_content)
    tr_body = _get_body(tr_content)

    en_lines = en_body.splitlines()
    tr_lines = tr_body.splitlines()

    issues = []
    in_code = False

    for i, (en_line, tr_line) in enumerate(zip(en_lines, tr_lines)):
        # Track fenced code block boundaries
        if en_line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue

        en_spans = re.findall(r"`([^`]+)`", en_line)
        tr_spans = re.findall(r"`([^`]+)`", tr_line)
        if not en_spans or not tr_spans:
            continue

        for en_sp, tr_sp in zip(en_spans, tr_spans):
            if en_sp.isascii() and not tr_sp.isascii():
                issues.append((i, en_line, tr_line, "inline_code_translation"))
                break

    return issues


def _repair_inline_code_line(en_line: str, tr_line: str) -> str:
    """
    Replace non-ASCII inline code spans in tr_line with corresponding EN spans.
    Surrounding translated text is preserved exactly.
    """
    en_spans = re.findall(r"`([^`]+)`", en_line)
    tr_spans = re.findall(r"`([^`]+)`", tr_line)

    repaired = tr_line

    if len(en_spans) == len(tr_spans):
        for en_sp, tr_sp in zip(en_spans, tr_spans):
            if en_sp.isascii() and not tr_sp.isascii():
                repaired = repaired.replace(f"`{tr_sp}`", f"`{en_sp}`", 1)
    else:
        # Span count mismatch: replace non-ASCII translated spans by position
        for i, tr_sp in enumerate(tr_spans):
            if not tr_sp.isascii() and i < len(en_spans):
                repaired = repaired.replace(f"`{tr_sp}`", f"`{en_spans[i]}`", 1)

    return repaired


def _detect_duplicate_content(tr_content: str) -> list[tuple[int, str, str, str]]:
    """Detect paragraphs appearing 3+ times in body."""
    body = _get_body(tr_content)
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", body) if len(p.strip()) > 30]

    counts: dict[str, int] = {}
    for p in paragraphs:
        counts[p] = counts.get(p, 0) + 1

    duplicates = [p for p, c in counts.items() if c >= 3]
    if duplicates:
        return [(0, "", tr_content, "duplicate_content")]
    return []


def _fix_duplicate_content(tr_content: str) -> str:
    """Remove duplicate paragraphs (keep first occurrence)."""
    # Split into frontmatter and body
    if tr_content.startswith("---"):
        end = tr_content.find("\n---", 4)
        if end != -1:
            fm = tr_content[:end + 4]
            body = tr_content[end + 4:]
        else:
            fm = ""
            body = tr_content
    else:
        fm = ""
        body = tr_content

    paragraphs = re.split(r"(\n{2,})", body)
    seen: set[str] = set()
    result = []
    for segment in paragraphs:
        stripped = segment.strip()
        if len(stripped) > 30:
            if stripped in seen:
                continue  # skip duplicate
            seen.add(stripped)
        result.append(segment)

    return fm + "".join(result)


def _detect_double_periods(
    en_content: str, tr_content: str
) -> list[tuple[int, str, str, str]]:
    """Detect '..' (not '...') in body outside code blocks."""
    body = _get_body(tr_content)
    clean = _strip_code_blocks(body)
    if re.search(r"(?<!\.)\.\.(?!\.)", clean):
        return [(0, "", tr_content, "double_period")]
    return []


def _fix_double_periods(tr_content: str) -> str:
    """Replace '..' with '.' (but not '...') outside code blocks."""
    if tr_content.startswith("---"):
        end = tr_content.find("\n---", 4)
        if end != -1:
            fm = tr_content[:end + 4]
            body = tr_content[end + 4:]
        else:
            fm = ""
            body = tr_content
    else:
        fm = ""
        body = tr_content

    # Only replace in non-code-block sections
    def _fix_segment(seg: str) -> str:
        return re.sub(r"(?<!\.)\.\.(?!\.)", ".", seg)

    parts = re.split(r"(```[\s\S]*?```)", body)
    fixed_parts = [
        part if re.match(r"```", part.strip()) else _fix_segment(part)
        for part in parts
    ]
    return fm + "".join(fixed_parts)


def _detect_description_hallucination(
    en_content: str, tr_content: str
) -> list[tuple[int, str, str, str]]:
    """Detect description field with >3x or <0.3x the source length."""
    en_fm_match = re.search(r"^description:\s*(.+?)$", en_content[:2000], re.MULTILINE)
    tr_fm_match = re.search(r"^description:\s*(.+?)$", tr_content[:2000], re.MULTILINE)
    if not en_fm_match or not tr_fm_match:
        return []

    en_desc = en_fm_match.group(1).strip().strip('"').strip("'")
    tr_desc = tr_fm_match.group(1).strip().strip('"').strip("'")
    if not en_desc or not tr_desc:
        return []

    ratio = len(tr_desc) / max(len(en_desc), 1)
    if ratio > 3.0 or ratio < 0.3:
        return [(0, en_desc, tr_desc, "description_hallucination")]
    return []


def _detect_table_corruption(
    en_content: str, tr_content: str
) -> list[tuple[int, str, str, str]]:
    """Detect table row count mismatch >50%."""
    en_body = _get_body(en_content)
    tr_body = _get_body(tr_content)

    en_rows = _get_table_row_count(en_body)
    tr_rows = _get_table_row_count(tr_body)

    if en_rows < 4:
        return []  # Too small to reliably detect

    if tr_rows < en_rows * 0.5 or tr_rows > en_rows * 2.0:
        return [(0, str(en_rows), str(tr_rows), "table_row_corruption")]
    return []


def _detect_mixed_language(
    tr_content: str, target_lang: str
) -> list[tuple[int, str, str, str]]:
    """Detect fully-English paragraphs in non-Latin target translations."""
    if target_lang in LATIN_SCRIPT_LANGS:
        return []  # Latin-script target — can't distinguish

    body = _get_body(tr_content)
    clean = _strip_code_blocks(body)

    issues = []
    for line in clean.splitlines():
        stripped = line.strip()
        if len(stripped) < 20 or "|" in stripped or stripped.startswith(">"):
            continue
        words = stripped.split()
        if len(words) < 5:
            continue
        if re.fullmatch(r"[A-Za-z0-9\s.,;:!?\-\'\"()\[\]{}#@_/\\`*]+", stripped):
            issues.append((0, "", stripped, "mixed_language"))

    if len(issues) > 3:
        return [(0, "", tr_content, "mixed_language")]
    return []


def _detect_heading_mismatch(
    en_content: str, tr_content: str
) -> list[tuple[int, str, str, str]]:
    """Detect heading count mismatch vs source."""
    en_body = _get_body(en_content)
    tr_body = _get_body(tr_content)

    en_headings = re.findall(r"^#{1,6}\s+.+$", en_body, re.MULTILINE)
    tr_headings = re.findall(r"^#{1,6}\s+.+$", tr_body, re.MULTILINE)

    if len(en_headings) == 0:
        return []

    if len(tr_headings) != len(en_headings):
        return [(0, str(len(en_headings)), str(len(tr_headings)), "heading_count_mismatch")]
    return []


def _detect_eu_hallucination(
    en_content: str, tr_content: str
) -> list[tuple[int, str, str, str]]:
    """Detect EU/GDPR text in translation not present in source."""
    tr_body = _get_body(tr_content)
    en_body = _get_body(en_content)

    for pattern in _EU_HALLUCINATION_PATTERNS:
        if pattern.search(tr_body) and not pattern.search(en_body):
            return [(0, "", "", "eu_hallucination")]
    return []


def _detect_newline_explosion(
    en_content: str, tr_content: str
) -> list[tuple[int, str, str, str]]:
    """Detect >2.5x newlines vs source body."""
    en_body = _get_body(en_content)
    tr_body = _get_body(tr_content)

    en_lines = en_body.count("\n")
    tr_lines = tr_body.count("\n")

    if en_lines < 5:
        return []
    if tr_lines > en_lines * 2.5:
        return [(0, str(en_lines), str(tr_lines), "newline_explosion")]
    return []


def detect_all_corruption(
    en_content: str, tr_content: str, target_lang: str
) -> list[tuple[int, str, str, str]]:
    """Run all detectors. Returns list of (line_idx, en_text, tr_text, issue_type)."""
    issues = []
    issues += _detect_inline_code_translation(en_content, tr_content)
    issues += _detect_duplicate_content(tr_content)
    issues += _detect_double_periods(en_content, tr_content)
    issues += _detect_description_hallucination(en_content, tr_content)
    issues += _detect_table_corruption(en_content, tr_content)
    issues += _detect_mixed_language(tr_content, target_lang)
    issues += _detect_heading_mismatch(en_content, tr_content)
    issues += _detect_eu_hallucination(en_content, tr_content)
    issues += _detect_newline_explosion(en_content, tr_content)
    return issues


# ---------------------------------------------------------------------------
# Per-file repair (no-GPU only)
# ---------------------------------------------------------------------------


def _apply_no_gpu_repairs(en_content: str, tr_content: str) -> tuple[str, list[str]]:
    """
    Apply all no-GPU repairs to tr_content.
    Returns (repaired_content, list_of_applied_fixes).
    """
    working = tr_content
    applied = []

    # 1. Inline code translation repair
    inline_issues = _detect_inline_code_translation(en_content, working)
    if inline_issues:
        en_body = _get_body(en_content)
        tr_body = _get_body(working)
        en_lines = en_body.splitlines()
        tr_lines = tr_body.splitlines()
        repaired_lines = list(tr_lines)

        in_code = False
        for i, (en_line, tr_line) in enumerate(zip(en_lines, tr_lines)):
            if en_line.strip().startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                continue
            repaired_line = _repair_inline_code_line(en_line, tr_line)
            if repaired_line != tr_line:
                repaired_lines[i] = repaired_line

        # Reconstruct with repaired body
        if working.startswith("---"):
            end = working.find("\n---", 4)
            if end != -1:
                fm = working[:end + 4]
                new_body = "\n".join(repaired_lines)
                working = fm + "\n" + new_body if not new_body.startswith("\n") else fm + new_body
            # edge case: no proper body separator — skip
        applied.append(f"inline_code_translation:{len(inline_issues)}_lines")

    # 2. Duplicate content
    if _detect_duplicate_content(working):
        working = _fix_duplicate_content(working)
        applied.append("duplicate_content")

    # 3. Double periods
    if _detect_double_periods(en_content, working):
        working = _fix_double_periods(working)
        applied.append("double_period")

    return working, applied


# ---------------------------------------------------------------------------
# File walker
# ---------------------------------------------------------------------------


def process_file(
    tr_path: Path,
    en_path: Path,
    locale: str,
    apply: bool,
    only_issues: set[str] | None,
    stats: dict,
    verbose: bool,
) -> None:
    if not en_path.exists():
        stats["en_missing"] += 1
        return

    try:
        tr_content = tr_path.read_text(encoding="utf-8", errors="replace")
        en_content = en_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        stats["read_errors"] += 1
        return

    issues = detect_all_corruption(en_content, tr_content, locale)

    if only_issues:
        issues = [iss for iss in issues if iss[3] in only_issues]

    if not issues:
        stats["files_clean"] += 1
        return

    stats["files_with_issues"] += 1
    issue_types = {iss[3] for iss in issues}
    for it in issue_types:
        stats[f"issue_{it}"] += 1

    if verbose:
        rel = str(tr_path).replace(str(tr_path.parent.parent.parent.parent), "...")
        print(f"  [{', '.join(sorted(issue_types))}] {rel}")

    # Determine which issues are no-GPU fixable
    no_gpu_issue_types = {"inline_code_translation", "duplicate_content", "double_period"}
    has_no_gpu = bool(issue_types & no_gpu_issue_types)
    has_model_needed = bool(issue_types - no_gpu_issue_types)

    if has_model_needed:
        for it in issue_types - no_gpu_issue_types:
            stats[f"model_needed_{it}"] += 1

    if apply and has_no_gpu:
        repaired, applied = _apply_no_gpu_repairs(en_content, tr_content)
        if repaired != tr_content:
            try:
                tr_path.write_text(repaired, encoding="utf-8")
                stats["files_repaired"] += 1
                for a in applied:
                    stats[f"repaired_{a.split(':')[0]}"] += 1
            except OSError as e:
                print(f"  ERROR writing {tr_path}: {e}", file=sys.stderr)
                stats["write_errors"] += 1


def run(
    content_root: Path,
    only_locales: list[str] | None,
    apply: bool,
    only_issues: set[str] | None,
    max_files: int | None,
    verbose: bool,
) -> dict:
    site_root = content_root / SITE
    if not site_root.exists():
        raise FileNotFoundError(f"Site root not found: {site_root}")

    en_root = site_root / EN_LOCALE
    stats: dict = defaultdict(int)

    locales = sorted(
        d.name
        for d in site_root.iterdir()
        if d.is_dir() and d.name != EN_LOCALE
        and (not only_locales or d.name in only_locales)
    )

    print(f"Content root: {site_root}")
    print(f"Locales: {locales}")
    print(f"Mode: {'APPLY (no-GPU repairs)' if apply else 'DRY-RUN'}")
    if only_issues:
        print(f"Issue filter: {', '.join(sorted(only_issues))}")
    print()

    files_processed = 0
    for locale in locales:
        locale_root = site_root / locale
        locale_files = list(locale_root.rglob("*.md"))

        print(f"  {locale}: {len(locale_files)} files", end="", flush=True)

        for tr_path in locale_files:
            if max_files and files_processed >= max_files:
                break
            stats["files_scanned"] += 1
            files_processed += 1

            rel = tr_path.relative_to(locale_root)
            en_path = en_root / rel
            process_file(tr_path, en_path, locale, apply, only_issues, stats, verbose)

        locale_issues = sum(
            v for k, v in stats.items()
            if k.startswith("issue_") and not k.startswith("issue_type")
        )
        print(f"  (scanned={stats['files_scanned']}, with_issues={stats['files_with_issues']})")

        if max_files and files_processed >= max_files:
            print(f"  Reached --max-files={max_files} limit.")
            break

    return dict(stats)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Surgical per-file repair for reference.aspose.org translations"
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=True,
        help="Report issues only (default)",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Apply no-GPU repairs in place",
    )
    parser.add_argument(
        "--content-root", type=Path,
        help="Path to aspose.org/content directory",
    )
    parser.add_argument(
        "--locales", type=str,
        help="Comma-separated locales to restrict (default: all)",
    )
    parser.add_argument(
        "--issue-type", type=str,
        help="Comma-separated issue types to filter (default: all)",
    )
    parser.add_argument(
        "--max-files", type=int,
        help="Maximum files to process (for testing)",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Print each file with issues",
    )
    args = parser.parse_args()

    apply = args.apply
    content_root = args.content_root or _resolve_content_root()
    only_locales = [l.strip() for l in args.locales.split(",")] if args.locales else None
    only_issues = (
        {i.strip() for i in args.issue_type.split(",")}
        if args.issue_type else None
    )

    stats = run(
        content_root=content_root,
        only_locales=only_locales,
        apply=apply,
        only_issues=only_issues,
        max_files=args.max_files,
        verbose=args.verbose,
    )

    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Files scanned:              {stats.get('files_scanned', 0):>8,}")
    print(f"Files clean:                {stats.get('files_clean', 0):>8,}")
    print(f"Files with issues:          {stats.get('files_with_issues', 0):>8,}")
    print()

    issue_keys = [k for k in sorted(stats) if k.startswith("issue_")]
    if issue_keys:
        print("Issue counts (files affected):")
        for k in issue_keys:
            label = k.replace("issue_", "")
            print(f"  {label:35s} {stats[k]:>6,}")
        print()

    model_keys = [k for k in sorted(stats) if k.startswith("model_needed_")]
    if model_keys:
        print("Requires model retranslation (not repaired by this script):")
        for k in model_keys:
            label = k.replace("model_needed_", "")
            print(f"  {label:35s} {stats[k]:>6,}")
        print()

    if apply:
        print(f"Files repaired (no-GPU):    {stats.get('files_repaired', 0):>8,}")
        repair_keys = [k for k in sorted(stats) if k.startswith("repaired_")]
        for k in repair_keys:
            print(f"  {k.replace('repaired_', ''):35s} {stats[k]:>6,}")
        print(f"Write errors:               {stats.get('write_errors', 0):>8,}")

    print(f"EN source missing:          {stats.get('en_missing', 0):>8,}")
    print(f"Read errors:                {stats.get('read_errors', 0):>8,}")
    print()

    if not apply:
        print("DRY-RUN complete. Run with --apply to apply no-GPU repairs.")
        if model_keys:
            model_needed_count = sum(stats.get(k, 0) for k in model_keys)
            print(f"  {model_needed_count} files need model retranslation (future work).")
    else:
        print("APPLY complete (no-GPU repairs applied).")


if __name__ == "__main__":
    main()
