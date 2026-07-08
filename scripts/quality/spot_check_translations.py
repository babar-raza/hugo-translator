#!/usr/bin/env python3
"""
Post-hoc translation quality spot-checker.

Compares translated files against their English source and flags structural/semantic anomalies
that the real-time validation system cannot catch:

  - Heading count mismatch
  - Link count mismatch (markdown + shortcode links)
  - Table row/column count mismatch
  - Code block count mismatch
  - Untranslated prose (>N consecutive English words in a non-English file)
  - Frontmatter fields that were not translated (same value as English source)
  - Product name mutations (Aspose.3D → Задача.3D / أسبو 3D)
  - Table header corruption (single repeated term across all cells)

Usage:
    python scripts/quality/spot_check_translations.py [OPTIONS]

Options:
    --site SITE_ID          Filter to one site (e.g. reference.aspose.org)
    --locale LOCALE         Filter to one locale (e.g. bg)
    --sample N              Random-sample N files per locale (default: all)
    --output PATH           Write JSON report to PATH (default: stdout)
    --min-english-words N   Threshold for "untranslated prose" detection (default: 20)
    --fail-threshold N      Exit 1 if critical issues >= N (default: 0 = never fail)
    --files PATH [PATH...]  Check specific files (must pass --locale too)
"""

import argparse
import json
import random
import re
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]
CONTENT = Path("C:/Users/prora/OneDrive/Documents/GitHub/aspose.org/content")

SITES_DIRECTORY = {
    "kb.aspose.org": CONTENT / "kb.aspose.org",
    "docs.aspose.org": CONTENT / "docs.aspose.org",
    "products.aspose.org": CONTENT / "products.aspose.org",
    "reference.aspose.org": CONTENT / "reference.aspose.org",
}

SITES_SUFFIX = {
    "blog.aspose.org": CONTENT / "blog.aspose.org",
}

LOCALES = [
    "ar", "bg", "ca", "cs", "da", "de", "el", "es", "fa", "fi", "fr", "he",
    "hi", "hr", "hu", "id", "it", "ja", "ko", "lt", "lv", "ms", "nl", "no",
    "pl", "pt", "ro", "ru", "sk", "sr", "sv", "th", "tr", "uk", "vi", "zh",
]

# English words regex — used for untranslated prose detection
_EN_WORD_RE = re.compile(r"\b[a-zA-Z]{3,}\b")
# Aspose product name mutations
_ASPOSE_PRODUCT_RE = re.compile(r"\bAspose\.\S+", re.IGNORECASE)
_VALID_ASPOSE_RE = re.compile(r"\bAspose\.[A-Z3]", re.IGNORECASE)
# Markdown heading
_HEADING_RE = re.compile(r"^#{1,6}\s", re.MULTILINE)
# Markdown link
_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]*)\)")
# Table row (pipe-delimited)
_TABLE_ROW_RE = re.compile(r"^\|.*\|", re.MULTILINE)
# Fenced code block
_CODE_FENCE_RE = re.compile(r"^```", re.MULTILINE)
# Frontmatter block
_FM_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)
# Translatable frontmatter fields (same as site profile)
_TRANSLATABLE_FM_FIELDS = {"title", "description", "summary", "linktitle"}


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def parse_frontmatter(text: str) -> dict:
    """Return dict of frontmatter key→value (strings only)."""
    m = _FM_RE.match(text)
    if not m:
        return {}
    result = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            result[key.strip()] = val.strip().strip('"').strip("'")
    return result


def body_text(text: str) -> str:
    """Return body (after frontmatter) or full text."""
    m = _FM_RE.match(text)
    if m:
        return text[m.end():].strip()
    return text


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_heading_count(src_body: str, tgt_body: str) -> Optional[dict]:
    src_n = len(_HEADING_RE.findall(src_body))
    tgt_n = len(_HEADING_RE.findall(tgt_body))
    if src_n != tgt_n:
        return {"check": "heading_count", "src": src_n, "tgt": tgt_n,
                "severity": "critical" if abs(src_n - tgt_n) > 1 else "warning"}
    return None


def check_link_count(src_body: str, tgt_body: str) -> Optional[dict]:
    src_n = len(_LINK_RE.findall(src_body))
    tgt_n = len(_LINK_RE.findall(tgt_body))
    if src_n != tgt_n:
        diff = abs(src_n - tgt_n)
        return {"check": "link_count", "src": src_n, "tgt": tgt_n,
                "severity": "critical" if diff > 2 else "warning"}
    return None


def check_table_structure(src_body: str, tgt_body: str) -> Optional[dict]:
    src_rows = _TABLE_ROW_RE.findall(src_body)
    tgt_rows = _TABLE_ROW_RE.findall(tgt_body)
    if len(src_rows) != len(tgt_rows):
        return {"check": "table_row_count", "src": len(src_rows), "tgt": len(tgt_rows),
                "severity": "critical"}
    # Check column count for each row
    col_mismatches = 0
    for s, t in zip(src_rows, tgt_rows):
        sc = len([c for c in s.split("|") if c.strip()])
        tc = len([c for c in t.split("|") if c.strip()])
        if sc != tc:
            col_mismatches += 1
    if col_mismatches:
        return {"check": "table_col_count", "mismatched_rows": col_mismatches,
                "severity": "warning"}
    return None


def check_table_header_corruption(src_body: str, tgt_body: str) -> Optional[dict]:
    """Detect NLLB pattern: all table cells replaced with one repeated term."""
    tgt_rows = _TABLE_ROW_RE.findall(tgt_body)
    if not tgt_rows:
        return None
    # Collect non-separator, non-empty cells
    all_cells = []
    for row in tgt_rows:
        cells = [c.strip() for c in row.split("|") if c.strip() and not re.match(r"^[-:]+$", c.strip())]
        all_cells.extend(cells)
    if len(all_cells) < 4:
        return None
    # If >70% of cells are the same value (case-insensitive), flag as corrupted
    from collections import Counter
    counts = Counter(c.lower() for c in all_cells)
    top_val, top_count = counts.most_common(1)[0]
    ratio = top_count / len(all_cells)
    if ratio > 0.70 and top_count >= 4:
        return {"check": "table_header_corruption", "dominant_value": top_val,
                "ratio": round(ratio, 2), "cell_count": len(all_cells),
                "severity": "critical"}
    return None


def check_code_block_count(src_body: str, tgt_body: str) -> Optional[dict]:
    src_n = len(_CODE_FENCE_RE.findall(src_body))
    tgt_n = len(_CODE_FENCE_RE.findall(tgt_body))
    if src_n != tgt_n:
        return {"check": "code_block_count", "src": src_n, "tgt": tgt_n,
                "severity": "critical" if abs(src_n - tgt_n) > 1 else "warning"}
    return None


def check_untranslated_prose(tgt_body: str, locale: str, min_words: int = 20) -> Optional[dict]:
    """Flag if >min_words consecutive English words appear in a non-Latin-script locale."""
    # Only check for non-Latin-script languages where English stands out clearly
    non_latin = {"ar", "bg", "el", "fa", "he", "hi", "ja", "ko", "ru", "sr", "th", "uk", "zh"}
    if locale not in non_latin:
        return None
    # Split into sentences/runs and look for long English runs
    sentences = re.split(r"[.!?\n]", tgt_body)
    max_run = 0
    worst = ""
    for sent in sentences:
        words = _EN_WORD_RE.findall(sent)
        # Filter out short technical tokens (API names, URLs, code)
        prose_words = [w for w in words if len(w) > 3 and w.lower() not in (
            "aspose", "http", "https", "null", "void", "true", "false", "none", "class",
            "method", "object", "value", "list", "type", "name", "path", "file", "data",
        )]
        if len(prose_words) > max_run:
            max_run = len(prose_words)
            worst = sent[:120]
    if max_run >= min_words:
        return {"check": "untranslated_prose", "max_english_word_run": max_run,
                "example": worst.strip(), "severity": "critical"}
    return None


def check_frontmatter_not_translated(src_fm: dict, tgt_fm: dict) -> list:
    """Check if translatable frontmatter fields are identical to source (untranslated)."""
    issues = []
    for field in _TRANSLATABLE_FM_FIELDS:
        src_val = src_fm.get(field, "").strip()
        tgt_val = tgt_fm.get(field, "").strip()
        if not src_val or not tgt_val:
            continue
        # Skip very short values (single words, API names) — they may legitimately stay same
        if len(src_val.split()) < 3:
            continue
        if src_val == tgt_val:
            issues.append({"check": "frontmatter_not_translated", "field": field,
                           "value": src_val[:80], "severity": "warning"})
    return issues


def check_product_name_mutations(src_body: str, tgt_body: str, src_fm: dict, tgt_fm: dict) -> list:
    """Detect Aspose product names mutated in translation."""
    issues = []
    # Find all Aspose.X references in source
    src_products = set(_ASPOSE_PRODUCT_RE.findall(src_body))
    for title_field in ("title", "linktitle", "description"):
        val = src_fm.get(title_field, "")
        src_products.update(_ASPOSE_PRODUCT_RE.findall(val))

    # Check each product name is preserved in target
    tgt_text = tgt_body + " " + " ".join(tgt_fm.values())
    for prod in src_products:
        if not re.search(re.escape(prod), tgt_text, re.IGNORECASE):
            issues.append({"check": "product_name_mutation", "product": prod,
                           "severity": "critical"})
    return issues


# ---------------------------------------------------------------------------
# File checker
# ---------------------------------------------------------------------------

def check_file_pair(src_path: Path, tgt_path: Path, locale: str,
                    min_english_words: int = 20) -> dict:
    """Run all checks on a source→target pair. Returns a result dict."""
    result = {"src": str(src_path), "tgt": str(tgt_path), "locale": locale,
              "issues": [], "status": "ok"}
    try:
        src_text = src_path.read_text(encoding="utf-8")
        tgt_text = tgt_path.read_text(encoding="utf-8")
    except Exception as e:
        result["status"] = "read_error"
        result["error"] = str(e)
        return result

    src_fm = parse_frontmatter(src_text)
    tgt_fm = parse_frontmatter(tgt_text)
    src_body = body_text(src_text)
    tgt_body = body_text(tgt_text)

    checks = [
        check_heading_count(src_body, tgt_body),
        check_link_count(src_body, tgt_body),
        check_table_structure(src_body, tgt_body),
        check_table_header_corruption(src_body, tgt_body),
        check_code_block_count(src_body, tgt_body),
        check_untranslated_prose(tgt_body, locale, min_english_words),
    ]
    issues = [c for c in checks if c]
    issues.extend(check_frontmatter_not_translated(src_fm, tgt_fm))
    issues.extend(check_product_name_mutations(src_body, tgt_body, src_fm, tgt_fm))

    result["issues"] = issues
    criticals = [i for i in issues if i.get("severity") == "critical"]
    if criticals:
        result["status"] = "critical"
    elif issues:
        result["status"] = "warning"

    return result


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

def scan_site(site_id: str, root: Path, locale_filter: Optional[str],
              sample_n: Optional[int], min_english_words: int,
              newer_than: Optional[float] = None) -> list:
    results = []
    is_suffix = site_id in SITES_SUFFIX
    locales = [locale_filter] if locale_filter else LOCALES

    if is_suffix:
        src_files = sorted(root.rglob("index.md"))
        for locale in locales:
            pairs = []
            for idx in src_files:
                tgt = idx.parent / f"index.{locale}.md"
                if tgt.exists():
                    if newer_than is None or tgt.stat().st_mtime > newer_than:
                        pairs.append((idx, tgt))
            if sample_n and len(pairs) > sample_n:
                pairs = random.sample(pairs, sample_n)
            for src, tgt in pairs:
                results.append(check_file_pair(src, tgt, locale, min_english_words))
    else:
        en_root = root / "en"
        if not en_root.exists():
            return []
        src_files = sorted(en_root.rglob("*.md"))
        for locale in locales:
            pairs = []
            for src in src_files:
                rel = src.relative_to(en_root)
                tgt = root / locale / rel
                if tgt.exists():
                    if newer_than is None or tgt.stat().st_mtime > newer_than:
                        pairs.append((src, tgt, rel))
            if sample_n and len(pairs) > sample_n:
                pairs = random.sample(pairs, sample_n)
            for src, tgt, _ in pairs:
                results.append(check_file_pair(src, tgt, locale, min_english_words))

    return results


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def print_report(results: list, output_path: Optional[str]) -> int:
    total = len(results)
    criticals = [r for r in results if r["status"] == "critical"]
    warnings = [r for r in results if r["status"] == "warning"]
    errors = [r for r in results if r["status"] == "read_error"]
    ok = [r for r in results if r["status"] == "ok"]

    summary = {
        "total_files": total,
        "ok": len(ok),
        "critical": len(criticals),
        "warning": len(warnings),
        "read_error": len(errors),
        "results": results,
    }

    if output_path:
        Path(output_path).write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Report written to {output_path}")
    else:
        print(f"\n=== Spot-Check Report ===")
        print(f"Files checked: {total} | OK: {len(ok)} | Critical: {len(criticals)} | "
              f"Warning: {len(warnings)} | Read errors: {len(errors)}")

        if criticals:
            print(f"\n--- CRITICAL Issues ({len(criticals)} files) ---")
            for r in criticals[:50]:
                rel = Path(r["tgt"]).name
                for issue in r["issues"]:
                    if issue.get("severity") == "critical":
                        print(f"  [{r['locale']}] {Path(r['tgt']).parts[-3]}/{rel}: "
                              f"{issue['check']}", end="")
                        # Print relevant extra info
                        for k in ("src", "tgt", "dominant_value", "product", "max_english_word_run"):
                            if k in issue:
                                print(f" ({k}={issue[k]})", end="")
                        print()

        if warnings:
            print(f"\n--- WARNING Issues ({len(warnings)} files) ---")
            for r in warnings[:20]:
                rel = Path(r["tgt"]).name
                for issue in r["issues"]:
                    if issue.get("severity") == "warning":
                        print(f"  [{r['locale']}] {Path(r['tgt']).parts[-3]}/{rel}: {issue['check']}")

    return len(criticals)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Spot-check translation quality")
    parser.add_argument("--site", help="Site ID to check (e.g. reference.aspose.org)")
    parser.add_argument("--locale", help="Locale to check (e.g. bg)")
    parser.add_argument("--sample", type=int, help="Random sample N files per locale")
    parser.add_argument("--output", help="Write JSON report to this path")
    parser.add_argument("--min-english-words", type=int, default=20,
                        help="English word run threshold for untranslated prose (default: 20)")
    parser.add_argument("--fail-threshold", type=int, default=0,
                        help="Exit 1 if critical issues >= N (default: 0 = never)")
    parser.add_argument("--files", nargs="+", help="Specific target files to check (requires --locale)")
    parser.add_argument("--newer-than", type=float, default=None,
                        help="Only check target files with mtime > this Unix timestamp (e.g. from S4 start)")
    args = parser.parse_args()

    if args.files:
        if not args.locale:
            print("ERROR: --files requires --locale", file=sys.stderr)
            sys.exit(2)
        results = []
        for fpath in args.files:
            tgt = Path(fpath)
            # Find source: look for en/ sibling directory or index.md
            # Try directory-based: tgt is {root}/{locale}/path.md → src is {root}/en/path.md
            parts = tgt.parts
            try:
                loc_idx = next(i for i, p in enumerate(parts) if p == args.locale)
                src = Path(*parts[:loc_idx]) / "en" / Path(*parts[loc_idx + 1:])
                if not src.exists():
                    # Try suffix-based
                    src = tgt.parent / "index.md"
            except StopIteration:
                src = tgt.parent / "index.md"
            results.append(check_file_pair(src, tgt, args.locale, args.min_english_words))
        n_crit = print_report(results, args.output)
        if args.fail_threshold > 0 and n_crit >= args.fail_threshold:
            sys.exit(1)
        return

    all_results = []
    sites = {}
    if args.site:
        if args.site in SITES_DIRECTORY:
            sites = {args.site: SITES_DIRECTORY[args.site]}
        elif args.site in SITES_SUFFIX:
            sites = {args.site: SITES_SUFFIX[args.site]}
        else:
            print(f"ERROR: Unknown site '{args.site}'", file=sys.stderr)
            sys.exit(2)
    else:
        sites = {**SITES_DIRECTORY, **SITES_SUFFIX}

    for site_id, root in sites.items():
        print(f"Scanning {site_id}...", flush=True)
        results = scan_site(site_id, root, args.locale, args.sample, args.min_english_words,
                            newer_than=args.newer_than)
        print(f"  {len(results)} pairs checked", flush=True)
        for r in results:
            r["site_id"] = site_id
        all_results.extend(results)

    n_crit = print_report(all_results, args.output)
    if args.fail_threshold > 0 and n_crit >= args.fail_threshold:
        sys.exit(1)


if __name__ == "__main__":
    main()
