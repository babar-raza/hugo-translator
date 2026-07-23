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
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
from src.utils.config_loader import ConfigService  # noqa: E402
from src.utils.content_discovery import discover_source_files  # noqa: E402
from src.utils.content_discovery import resolve_translated_path  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

_CONFIG = ConfigService(_PROJECT_ROOT / "config")

# Durable-fix consolidation: this script already correctly read
# output_layout.per_language_folders (one of only 2 scripts found to do so
# independently, alongside scan_wrong_language_outputs.py) -- it wasn't
# broken, but it was a second, parallel implementation of logic that now
# lives canonically in src/utils/content_discovery.py. Consolidated onto
# that shared module so there is exactly one correct implementation.


def load_site_profiles(profiles_dir: Path, site_filter: str | None = None):
    """Load all production site profiles (*.aspose.net.yaml / *.aspose.org.yaml).

    Preserves this script's original scope: only "top-level" production
    profiles, not the `.words`-suffixed sub-profiles or test/disabled ones
    -- a deliberate choice, unlike the coverage-gap bugs found elsewhere in
    the durable-fix investigation.

    Builds its own ConfigService from profiles_dir's parent rather than
    reusing the module-level _CONFIG singleton, so a custom --profiles-dir
    override is respected rather than silently falling back to the default
    config/ directory.
    """
    config_service = (
        _CONFIG if profiles_dir.resolve() == _CONFIG.site_profiles_dir.resolve()
        else ConfigService(profiles_dir.parent)
    )
    profiles = []
    for p in sorted(profiles_dir.glob("*.yaml")):
        name = p.stem
        if not (name.endswith(".aspose.net") or name.endswith(".aspose.org")):
            continue
        if site_filter and name != site_filter:
            continue
        try:
            profiles.append(config_service.get_site_profile(name))
        except Exception as e:
            logger.warning(f"Failed to load {p}: {e}")
    return profiles


def measure_site(
    profile,
    lang_filter: str | None = None,
) -> list[dict]:
    """
    Measure completeness for one site profile.

    Returns list of dicts: {site_id, lang, source_files, translated, missing, coverage_pct}
    """
    site_id = profile.site_id
    target_langs = list(profile.target_langs)

    if lang_filter:
        target_langs = [l for l in target_langs if l == lang_filter]
        if not target_langs:
            return []

    results = []

    for root_raw in profile.content_roots:
        root_path = _CONFIG.resolve_content_root(root_raw)
        if not root_path.exists():
            logger.warning(f"[{site_id}] Content root not found: {root_path}")
            continue

        # Registry-driven discovery: works identically for
        # per_language_folders=True and file-suffix (=False) sites.
        source_files = discover_source_files(profile, root_path)

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
                output_path = resolve_translated_path(profile, src_file, lang)

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
        site_id = profile.site_id
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
