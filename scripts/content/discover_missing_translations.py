#!/usr/bin/env python3
"""
Discovery script for missing translations - Phase 1 of orchestration run.
Enumerates all source files and computes missing translations per site/language.
"""

import csv
import json
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import yaml


def load_site_profile(profile_path: str) -> dict:
    """Load a site profile YAML file."""
    with open(profile_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def discover_source_files(content_root: str, source_lang: str = "en") -> list[Path]:
    """
    Discover all source files in the content root.
    For Hugo sites with per-language folders, source files are in the source language folder.
    """
    content_path = Path(content_root)
    source_lang_path = content_path / source_lang

    if not source_lang_path.exists():
        # Fallback: scan entire content root
        source_lang_path = content_path

    source_files = []
    for md_file in source_lang_path.rglob("*.md"):
        # Skip _index.md unless specifically needed
        if md_file.name == "_index.md":
            continue
        source_files.append(md_file)

    return sorted(source_files)


def compute_expected_translation_path(
    source_file: Path, source_lang: str, target_lang: str, content_root: str
) -> Path:
    """
    Compute the expected path for a translated file.
    Pattern: {content_root}/{target_lang}/{relative_path_from_source_lang_folder}
    """
    content_path = Path(content_root)
    source_lang_path = content_path / source_lang

    # Get relative path from source lang folder
    try:
        rel_path = source_file.relative_to(source_lang_path)
    except ValueError:
        # If source file is not under source_lang_path, use relative to content_root
        rel_path = source_file.relative_to(content_path)

    # Construct target path
    target_path = content_path / target_lang / rel_path
    return target_path


def check_translation_status(target_path: Path) -> str:
    """
    Check the status of a translation file.
    Returns: EXISTS, MISSING, INVALID
    """
    if not target_path.exists():
        return "MISSING"

    # Basic validity check - can we read it?
    try:
        with open(target_path, encoding="utf-8") as f:
            content = f.read()
            # Check if file is empty or just frontmatter
            if len(content.strip()) < 10:
                return "INVALID"
        return "EXISTS"
    except Exception:
        return "INVALID"


def discover_site(site_profile_path: str, run_dir: Path) -> dict:
    """
    Discover all missing translations for a single site.
    Returns summary statistics and writes detailed manifest.
    """
    profile = load_site_profile(site_profile_path)
    site_id = profile["site_id"]
    source_lang = profile.get("default_source_lang", "en")
    target_langs = profile.get("target_langs", [])
    content_roots = profile.get("content_roots", [])

    print(f"\n{'=' * 80}")
    print(f"Site: {site_id}")
    print(f"Source language: {source_lang}")
    print(
        f"Target languages: {len(target_langs)} ({', '.join(target_langs[:5])}{'...' if len(target_langs) > 5 else ''})"
    )
    print(f"Content roots: {len(content_roots)}")
    print(f"{'=' * 80}\n")

    all_source_files = []
    for content_root in content_roots:
        if not os.path.exists(content_root):
            print(f"WARNING: Content root does not exist: {content_root}")
            continue
        source_files = discover_source_files(content_root, source_lang)
        print(f"  Found {len(source_files)} source files in {content_root}")
        all_source_files.extend([(sf, content_root) for sf in source_files])

    print(f"\nTotal source files: {len(all_source_files)}")

    # Compute missing translations
    missing_by_lang = defaultdict(list)
    exists_by_lang = defaultdict(int)
    invalid_by_lang = defaultdict(int)

    manifest_rows = []

    for source_file, content_root in all_source_files:
        for target_lang in target_langs:
            target_path = compute_expected_translation_path(
                source_file, source_lang, target_lang, content_root
            )
            status = check_translation_status(target_path)

            if status == "MISSING":
                missing_by_lang[target_lang].append(
                    {
                        "source": str(source_file),
                        "target": str(target_path),
                        "content_root": content_root,
                    }
                )
            elif status == "EXISTS":
                exists_by_lang[target_lang] += 1
            elif status == "INVALID":
                invalid_by_lang[target_lang] += 1

            manifest_rows.append(
                {
                    "site_id": site_id,
                    "source_file": str(source_file),
                    "target_lang": target_lang,
                    "target_path": str(target_path),
                    "status": status,
                    "content_root": content_root,
                }
            )

    # Write detailed manifest
    manifest_csv = run_dir / f"manifest_{site_id}.csv"
    with open(manifest_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "site_id",
                "source_file",
                "target_lang",
                "target_path",
                "status",
                "content_root",
            ],
        )
        writer.writeheader()
        writer.writerows(manifest_rows)

    print(f"\n[OK] Wrote detailed manifest: {manifest_csv}")

    # Summary statistics
    summary = {
        "site_id": site_id,
        "source_lang": source_lang,
        "target_langs": target_langs,
        "num_source_files": len(all_source_files),
        "missing_by_lang": {lang: len(files) for lang, files in missing_by_lang.items()},
        "exists_by_lang": dict(exists_by_lang),
        "invalid_by_lang": dict(invalid_by_lang),
        "total_missing": sum(len(files) for files in missing_by_lang.values()),
        "total_exists": sum(exists_by_lang.values()),
        "total_invalid": sum(invalid_by_lang.values()),
    }

    # Print summary
    print(f"\nSummary for {site_id}:")
    print(f"  Source files: {summary['num_source_files']}")
    print(f"  Total missing: {summary['total_missing']}")
    print(f"  Total exists: {summary['total_exists']}")
    print(f"  Total invalid: {summary['total_invalid']}")

    # Print top 10 languages by missing count
    missing_sorted = sorted(missing_by_lang.items(), key=lambda x: len(x[1]), reverse=True)
    print("\n  Top 10 languages by missing translations:")
    for lang, files in missing_sorted[:10]:
        print(f"    {lang}: {len(files)} missing")

    return summary


def main():
    # Setup
    repo_root = Path(__file__).parent.parent
    run_dir = repo_root / "reports" / "translation_runs" / "20260212_131519_missing_full"
    run_dir.mkdir(parents=True, exist_ok=True)

    # Find all site profiles
    site_profiles_dir = repo_root / "config" / "site_profiles"
    site_profiles = []

    # Only process main aspose.net sites
    main_sites = [
        "reference.aspose.net.yaml",
        "products.aspose.net.yaml",
        "docs.aspose.net.yaml",
        "www.aspose.net.yaml",
        "about.aspose.net.yaml",
        "blog.aspose.net.yaml",
        "kb.aspose.net.yaml",
        "websites.aspose.net.yaml",
    ]

    for site_file in main_sites:
        site_profile = site_profiles_dir / site_file
        if site_profile.exists():
            site_profiles.append(str(site_profile))

    print(f"Found {len(site_profiles)} site profiles to process")

    # Discover each site
    all_summaries = []
    for site_profile in site_profiles:
        summary = discover_site(site_profile, run_dir)
        all_summaries.append(summary)

    # Write combined summary
    summary_json = run_dir / "discovery_summary.json"
    with open(summary_json, "w", encoding="utf-8") as f:
        json.dump(
            {
                "timestamp": datetime.now().isoformat(),
                "sites": all_summaries,
                "total_missing": sum(s["total_missing"] for s in all_summaries),
                "total_exists": sum(s["total_exists"] for s in all_summaries),
                "total_invalid": sum(s["total_invalid"] for s in all_summaries),
            },
            f,
            indent=2,
        )

    print(f"\n{'=' * 80}")
    print("[OK] Discovery complete!")
    print(f"[OK] Summary written to: {summary_json}")
    print("\nOverall totals across all sites:")
    print(f"  Total missing: {sum(s['total_missing'] for s in all_summaries):,}")
    print(f"  Total exists: {sum(s['total_exists'] for s in all_summaries):,}")
    print(f"  Total invalid: {sum(s['total_invalid'] for s in all_summaries):,}")
    print(f"{'=' * 80}\n")


if __name__ == "__main__":
    main()
