#!/usr/bin/env python3
"""
Terminology Coverage Checker

Scans translated output files and reports what fraction of required terminology
terms (from config/terminology.yaml) are correctly preserved per language.

This helps identify which languages are systematically dropping product names,
file format terms, or other protected terminology.

Usage:
    python scripts/check_terminology_coverage.py \\
        --content-root D:\\onedrive\\Documents\\GitHub\\aspose.net \\
        --langs fr de es ar zh \\
        --n-sample 20

    python scripts/check_terminology_coverage.py --help
"""

import argparse
import logging
import random
import sys
from collections import defaultdict
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

_ALL_LANGUAGE_CODES = frozenset(
    [
        "af",
        "ar",
        "az",
        "bg",
        "ca",
        "cs",
        "da",
        "de",
        "el",
        "es",
        "et",
        "fa",
        "fi",
        "fr",
        "ga",
        "he",
        "hi",
        "hr",
        "hu",
        "id",
        "it",
        "ja",
        "ko",
        "lt",
        "lv",
        "ms",
        "nb",
        "nl",
        "no",
        "pl",
        "pt",
        "ro",
        "ru",
        "sk",
        "sl",
        "sr",
        "sv",
        "th",
        "tr",
        "uk",
        "vi",
        "zh",
    ]
)


def _find_translated_path(source_path: Path, content_root: Path, lang: str) -> Path | None:
    # Folder-based: content_root/lang/rel_path.md
    try:
        rel = source_path.relative_to(content_root)
        candidate = content_root / lang / rel
        if candidate.exists():
            return candidate
    except ValueError:
        pass
    # File-based: source.lang.md
    candidate = source_path.parent / f"{source_path.stem}.{lang}{source_path.suffix}"
    return candidate if candidate.exists() else None


def load_exact_matches(terminology_config: dict) -> list[str]:
    """Extract all exact-match term strings from terminology.yaml."""
    global_section = terminology_config.get("global", {})
    raw = global_section.get("exact_matches", [])
    terms = []
    for entry in raw:
        if isinstance(entry, str):
            terms.append(entry)
        elif isinstance(entry, dict):
            term = entry.get("term") or entry.get("text") or entry.get("match")
            if term:
                terms.append(str(term))
    return terms


def check_file_coverage(
    source_text: str,
    translated_text: str,
    terms: list[str],
) -> dict[str, bool]:
    """
    For each term that appears in the source, check if it appears in translation.

    Returns {term: preserved} dict for terms present in source.
    """
    results = {}
    for term in terms:
        if term in source_text:
            results[term] = term in translated_text
    return results


def run_coverage_check(
    content_root: Path,
    langs: list[str],
    terms: list[str],
    n_sample: int,
    seed: int,
) -> dict[str, dict[str, list[bool]]]:
    """
    For each language, sample n_sample source+translation pairs and check coverage.

    Returns {lang: {term: [True/False, ...]}} where each bool is one file's result.
    """
    rng = random.Random(seed)

    # Collect source files
    source_files = []
    for f in content_root.rglob("*.md"):
        stem = f.stem
        parts = stem.rsplit(".", 1)
        if len(parts) == 2 and parts[1] in _ALL_LANGUAGE_CODES:
            continue
        source_files.append(f)

    logger.info("Found %d source files", len(source_files))

    results: dict[str, dict[str, list[bool]]] = {}

    for lang in langs:
        logger.info("Checking language: %s", lang)
        # Find pairs for this language
        pairs = []
        for src in source_files:
            tgt = _find_translated_path(src, content_root, lang)
            if tgt is not None:
                pairs.append((src, tgt))

        if not pairs:
            logger.warning("No translated files found for language: %s", lang)
            continue

        sample = rng.sample(pairs, min(n_sample, len(pairs)))
        lang_results: dict[str, list[bool]] = defaultdict(list)

        for src_path, tgt_path in sample:
            try:
                src_text = src_path.read_text(encoding="utf-8", errors="replace")
                tgt_text = tgt_path.read_text(encoding="utf-8", errors="replace")
                file_coverage = check_file_coverage(src_text, tgt_text, terms)
                for term, preserved in file_coverage.items():
                    lang_results[term].append(preserved)
            except Exception as e:
                logger.debug("Error reading %s: %s", tgt_path, e)

        results[lang] = dict(lang_results)

    return results


def print_report(results: dict[str, dict[str, list[bool]]], threshold: float = 0.80) -> None:
    print(f"\n{'=' * 65}")
    print("TERMINOLOGY COVERAGE REPORT")
    print(f"Threshold: {threshold:.0%}  |  Terms with low coverage flagged with [!]")
    print(f"{'=' * 65}\n")

    all_terms = set()
    for lang_data in results.values():
        all_terms.update(lang_data.keys())

    if not all_terms:
        print("No terminology data collected.")
        return

    # Per-language summary
    for lang, lang_data in sorted(results.items()):
        if not lang_data:
            print(f"  {lang}: no data")
            continue

        term_rates: list[tuple[str, float, int]] = []
        for term, checks in lang_data.items():
            if checks:
                rate = sum(checks) / len(checks)
                term_rates.append((term, rate, len(checks)))

        overall = sum(r for _, r, _ in term_rates) / len(term_rates) if term_rates else 0.0
        low = [(t, r, n) for t, r, n in term_rates if r < threshold]

        flag = "[!]" if low else "   "
        print(
            f"  {flag} {lang:<6}  overall={overall:.1%}  ({len(low)} terms below {threshold:.0%})"
        )
        for term, rate, n in sorted(low, key=lambda x: x[1]):
            print(f"         - '{term}': {rate:.1%} preserved ({n} files checked)")

    # Cross-language worst terms
    print(f"\n  WORST TERMS ACROSS ALL LANGUAGES (below {threshold:.0%}):")
    term_global: dict[str, list[float]] = defaultdict(list)
    for lang_data in results.values():
        for term, checks in lang_data.items():
            if checks:
                term_global[term].append(sum(checks) / len(checks))

    worst = [
        (term, sum(rates) / len(rates))
        for term, rates in term_global.items()
        if sum(rates) / len(rates) < threshold
    ]
    worst.sort(key=lambda x: x[1])
    for term, avg_rate in worst[:20]:
        print(f"    '{term}': avg {avg_rate:.1%}")

    print(f"\n{'=' * 65}\n")


def main() -> int:
    p = argparse.ArgumentParser(description="Check terminology preservation coverage")
    p.add_argument(
        "--content-root",
        type=Path,
        required=True,
        help="Root directory containing translated content",
    )
    p.add_argument(
        "--langs",
        nargs="+",
        default=["fr", "de", "es", "ar", "zh"],
        help="Target language codes to check",
    )
    p.add_argument(
        "--n-sample", type=int, default=20, help="Files to sample per language (default: 20)"
    )
    p.add_argument("--seed", type=int, default=42)
    p.add_argument(
        "--threshold",
        type=float,
        default=0.80,
        help="Coverage rate below which terms are flagged (default: 0.80)",
    )
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if not args.content_root.exists():
        logger.error("Content root not found: %s", args.content_root)
        return 1

    # Load terminology config
    terminology_path = _PROJECT_ROOT / "config" / "terminology.yaml"
    if not terminology_path.exists():
        logger.error("Terminology config not found at %s", terminology_path)
        return 1

    try:
        import yaml

        with open(terminology_path, encoding="utf-8") as f:
            terminology_config = yaml.safe_load(f) or {}
    except Exception as e:
        logger.error("Failed to load terminology config: %s", e)
        return 1

    terms = load_exact_matches(terminology_config)
    logger.info("Loaded %d exact-match terms", len(terms))
    if not terms:
        logger.warning("No exact_matches found in terminology config — nothing to check")
        return 0

    results = run_coverage_check(
        content_root=args.content_root,
        langs=args.langs,
        terms=terms,
        n_sample=args.n_sample,
        seed=args.seed,
    )

    print_report(results, threshold=args.threshold)
    return 0


if __name__ == "__main__":
    sys.exit(main())
