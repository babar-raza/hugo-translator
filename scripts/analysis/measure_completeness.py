"""
WS-COMP-1: Translation Completeness Measurement

Walks all site content repos using site profiles and reports per-site per-language
coverage percentages. Run this before any changes to establish a baseline, then
periodically to track reduction in incomplete translations.

Usage:
    python scripts/measure_completeness.py
    python scripts/measure_completeness.py --site blog.aspose.net
    python scripts/measure_completeness.py --site docs.aspose.net --lang de
    python scripts/measure_completeness.py --json > reports/coverage_baseline.json
    python scripts/measure_completeness.py --summary   # totals only

Output columns:
    site_id | lang | source_files | translated | missing | coverage_pct

Completeness definition:
    A source file is "translated" for lang X if the corresponding output file exists
    (regardless of content quality — use scan_wrong_language_outputs.py for that).
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import yaml

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Language codes that appear in filenames (file-based localization filter)
_ALL_LANG_CODES = frozenset(
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
        "en",
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


def expand_env(value: str) -> str:
    """Expand ${VAR} and $VAR style environment variables."""
    return os.path.expandvars(value.replace("${", "$").replace("}", ""))


def load_site_profiles(profiles_dir: Path, site_filter: str | None = None) -> list[dict]:
    """Load all production site profiles (*.aspose.net.yaml)."""
    profiles = []
    for p in sorted(profiles_dir.glob("*.yaml")):
        # Only load production aspose.net profiles; skip test/disabled profiles
        name = p.stem
        if not (name.endswith(".aspose.net") or name.endswith(".aspose.org")):
            continue
        if site_filter and name != site_filter:
            continue
        try:
            with open(p, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if data and "site_id" in data and "content_roots" in data:
                profiles.append(data)
        except Exception as e:
            logger.warning(f"Failed to load {p}: {e}")
    return profiles


def is_source_file_file_based(path: Path) -> bool:
    """
    For file-based localization: return True if this file is a source (English) file.
    Source files have no language code in the stem, e.g. index.md, post.md.
    Translated files have a lang code: index.de.md, post.es.md — excluded.
    """
    stem = path.stem  # e.g. "index" or "index.de"
    # Check if stem ends with a known language code
    parts = stem.rsplit(".", 1)
    if len(parts) == 2 and parts[1].lower() in _ALL_LANG_CODES:
        return False  # Already translated file
    return True


def get_output_path_file_based(source_path: Path, target_lang: str, pattern: str) -> Path:
    """Compute output path for file-based localization."""
    stem = source_path.stem
    ext = source_path.suffix
    output_filename = pattern.format(
        filename=stem, lang=target_lang, ext=ext, path=source_path.name
    )
    return source_path.parent / output_filename


def get_output_path_folder_based(
    source_path: Path, target_lang: str, source_lang: str
) -> Path | None:
    """Compute output path for folder-based localization (replace /en/ with /lang/)."""
    source_str = str(source_path)
    for sep in ["/", "\\"]:
        source_folder = f"{sep}{source_lang}{sep}"
        target_folder = f"{sep}{target_lang}{sep}"
        if source_folder in source_str:
            return Path(source_str.replace(source_folder, target_folder, 1))
    return None


def measure_site(
    profile: dict,
    lang_filter: str | None = None,
) -> list[dict]:
    """
    Measure completeness for one site profile.

    Returns list of dicts: {site_id, lang, source_files, translated, missing, coverage_pct}
    """
    site_id = profile.get("site_id", "unknown")
    source_lang = profile.get("default_source_lang", "en")
    target_langs = profile.get("target_langs", [])
    content_roots_raw = profile.get("content_roots", [])
    output_layout = profile.get("output_layout", {})
    per_language_folders = output_layout.get("per_language_folders", False)
    pattern = output_layout.get("pattern", "{filename}.{lang}{ext}")

    if lang_filter:
        target_langs = [l for l in target_langs if l == lang_filter]
        if not target_langs:
            return []

    results = []

    for root_raw in content_roots_raw:
        root_path = Path(expand_env(str(root_raw)))
        if not root_path.exists():
            logger.warning(f"[{site_id}] Content root not found: {root_path}")
            continue

        # Collect source files
        source_files = []
        if per_language_folders:
            # Folder-based: look for files under /<source_lang>/ subfolder
            en_root = root_path / source_lang
            if not en_root.exists():
                # Try finding /en/ anywhere in the tree
                en_dirs = list(root_path.rglob(source_lang))
                if en_dirs:
                    for en_dir in en_dirs:
                        if en_dir.is_dir():
                            source_files.extend(en_dir.rglob("*.md"))
                else:
                    logger.warning(f"[{site_id}] No /{source_lang}/ folder found in {root_path}")
                    continue
            else:
                source_files = list(en_root.rglob("*.md"))
        else:
            # File-based: walk entire root, filter to source files only
            all_md = list(root_path.rglob("*.md"))
            source_files = [f for f in all_md if is_source_file_file_based(f)]

        if not source_files:
            logger.debug(f"[{site_id}] No source files found in {root_path}")
            continue

        total = len(source_files)

        # For each target language, count how many outputs exist
        lang_stats: dict[str, dict] = {}
        for lang in target_langs:
            lang_stats[lang] = {"translated": 0, "missing": 0, "missing_files": []}

        for src_file in source_files:
            for lang in target_langs:
                if per_language_folders:
                    output_path = get_output_path_folder_based(src_file, lang, source_lang)
                else:
                    output_path = get_output_path_file_based(src_file, lang, pattern)

                if output_path and output_path.exists():
                    lang_stats[lang]["translated"] += 1
                else:
                    lang_stats[lang]["missing"] += 1
                    lang_stats[lang]["missing_files"].append(str(src_file))

        for lang in target_langs:
            stats = lang_stats[lang]
            translated = stats["translated"]
            missing = stats["missing"]
            coverage = round(translated / total * 100, 1) if total > 0 else 0.0
            results.append(
                {
                    "site_id": site_id,
                    "content_root": str(root_path),
                    "lang": lang,
                    "source_files": total,
                    "translated": translated,
                    "missing": missing,
                    "coverage_pct": coverage,
                    "missing_files": stats["missing_files"],
                }
            )

    return results


def print_table(rows: list[dict], show_missing_files: bool = False) -> None:
    """Print results as a human-readable table."""
    if not rows:
        print(
            "No results (check that ASPOSE_NET_CONTENT or ASPOSE_ORG_CONTENT is set and content repos are accessible)."
        )
        return

    # Group by site
    by_site: dict[str, list[dict]] = {}
    for row in rows:
        by_site.setdefault(row["site_id"], []).append(row)

    header = (
        f"{'Site':<30} {'Lang':<6} {'Source':>8} {'Translated':>12} {'Missing':>9} {'Coverage':>9}"
    )
    sep = "-" * len(header)

    for site_id, site_rows in sorted(by_site.items()):
        print(f"\n{site_id}")
        print(header)
        print(sep)
        for row in sorted(site_rows, key=lambda r: r["lang"]):
            pct = row["coverage_pct"]
            flag = "  ✓" if pct >= 90 else ("  !" if pct >= 70 else "  ✗")
            print(
                f"{'':30} {row['lang']:<6} {row['source_files']:>8} {row['translated']:>12} "
                f"{row['missing']:>9} {pct:>8.1f}%{flag}"
            )
            if show_missing_files and row["missing_files"]:
                for mf in row["missing_files"][:5]:
                    print(f"    {'':28} {mf}")
                if len(row["missing_files"]) > 5:
                    print(f"    {'':28} ... and {len(row['missing_files']) - 5} more")

        # Site-level summary
        total_source = max((r["source_files"] for r in site_rows), default=0)
        total_translated = sum(r["translated"] for r in site_rows)
        total_missing = sum(r["missing"] for r in site_rows)
        total_possible = total_source * len(site_rows)
        site_coverage = (
            round(total_translated / total_possible * 100, 1) if total_possible > 0 else 0.0
        )
        print(sep)
        print(
            f"{'  TOTAL':<30} {'all':<6} {total_source:>8} {total_translated:>12} {total_missing:>9} {site_coverage:>8.1f}%"
        )


def print_summary(rows: list[dict]) -> None:
    """Print overall summary across all sites."""
    if not rows:
        return
    total_source_x_lang = sum(r["source_files"] for r in rows)
    total_translated = sum(r["translated"] for r in rows)
    total_missing = sum(r["missing"] for r in rows)
    overall_pct = (
        round(total_translated / total_source_x_lang * 100, 1) if total_source_x_lang > 0 else 0.0
    )

    print(f"\n{'=' * 55}")
    print("OVERALL COMPLETENESS SUMMARY")
    print(f"{'=' * 55}")
    print(f"Total source×lang slots:  {total_source_x_lang:>10}")
    print(f"Translated:               {total_translated:>10}")
    print(f"Missing:                  {total_missing:>10}")
    print(f"Overall coverage:         {overall_pct:>9.1f}%")

    # Worst languages
    lang_totals: dict[str, dict] = {}
    for row in rows:
        lang = row["lang"]
        if lang not in lang_totals:
            lang_totals[lang] = {"translated": 0, "source": 0}
        lang_totals[lang]["translated"] += row["translated"]
        lang_totals[lang]["source"] += row["source_files"]

    worst = sorted(
        [
            (l, round(v["translated"] / v["source"] * 100, 1) if v["source"] else 0)
            for l, v in lang_totals.items()
        ],
        key=lambda x: x[1],
    )[:10]
    print("\nWorst 10 languages by coverage:")
    for lang, pct in worst:
        print(f"  {lang:<6}  {pct:.1f}%")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure translation completeness across aspose.net sites"
    )
    parser.add_argument("--site", help="Filter to a specific site_id (e.g. blog.aspose.net)")
    parser.add_argument("--lang", help="Filter to a specific target language (e.g. de)")
    parser.add_argument(
        "--json", action="store_true", help="Output raw JSON (no missing_files list)"
    )
    parser.add_argument(
        "--json-full", action="store_true", help="Output full JSON including missing file lists"
    )
    parser.add_argument(
        "--summary", action="store_true", help="Print only the overall summary totals"
    )
    parser.add_argument(
        "--missing", action="store_true", help="Show first 5 missing files per lang (table mode)"
    )
    parser.add_argument(
        "--profiles-dir",
        default="config/site_profiles",
        help="Path to site profiles directory (default: config/site_profiles)",
    )
    args = parser.parse_args()

    profiles_dir = Path(args.profiles_dir)
    if not profiles_dir.exists():
        print(f"ERROR: Profiles directory not found: {profiles_dir}", file=sys.stderr)
        sys.exit(1)

    profiles = load_site_profiles(profiles_dir, site_filter=args.site)
    if not profiles:
        print(
            f"No site profiles found in {profiles_dir}"
            + (f" matching '{args.site}'" if args.site else ""),
            file=sys.stderr,
        )
        sys.exit(1)

    all_rows: list[dict] = []
    for profile in profiles:
        site_id = profile.get("site_id", "unknown")
        rows = measure_site(profile, lang_filter=args.lang)
        if not rows:
            logger.debug(f"No results for {site_id}")
        all_rows.extend(rows)

    if args.json or args.json_full:
        output_rows = all_rows
        if not args.json_full:
            # Strip missing_files list from JSON output (can be huge)
            output_rows = [{k: v for k, v in r.items() if k != "missing_files"} for r in all_rows]
        print(json.dumps(output_rows, indent=2))
        return

    if args.summary:
        print_summary(all_rows)
        return

    print_table(all_rows, show_missing_files=args.missing)
    print_summary(all_rows)


if __name__ == "__main__":
    main()
