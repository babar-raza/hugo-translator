"""
words_inventory.py — Read-only stale detection ledger for Aspose.Words translation sprint.

Scans all configured Aspose.Words content surfaces under ASPOSE_NET_CONTENT and produces
a JSONL ledger with 28 fields per (source_file, locale) pair, reporting staleness,
translation status, and recommended action.

This script is READ-ONLY. It never modifies source content, translated files, TM, or metadata.

Usage:
    python scripts/words_inventory.py [--output PATH] [--site SITE_ID] [--verbose]

Environment:
    ASPOSE_NET_CONTENT   Root of aspose.net content repository (required)

Output:
    JSONL ledger at data/sprints/words-inventory-YYYYMMDD.jsonl (or --output path)
    Summary table printed to stdout

Stale reason categories:
    missing_localized_page          Localized file does not exist
    localized_page_older_than_source Source mtime newer than localized mtime
    no_change_detected              Both files exist, source not newer (may still need quality review)
    unknown_needs_manual_review     Edge case; inspect manually

Exit codes:
    0   Inventory complete (stale items may exist — check ledger)
    1   ASPOSE_NET_CONTENT not set or invalid
    2   No words profiles found or readable
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Tuple: (profile_filename, words_subdir_override)
# profile_filename: the .yaml filename; the stem (without .yaml) is the --site key for the worker CLI.
# The site_id field inside the profile may differ from the filename (e.g. docs.aspose.net.words.yaml
# has site_id: docs.aspose.net). The worker CLI resolves profiles by filename stem, not site_id.
# words_subdir_override: if set, only scan this subdir within each content_root.
# Required for profiles whose content_root covers the full site (e.g. blog).
WORDS_SURFACE_PROFILES = [
    ("docs.aspose.net.words.yaml",      None),        # worker --site docs.aspose.net.words
    ("kb.aspose.net.words.yaml",        None),        # worker --site kb.aspose.net.words
    ("products.aspose.net.words.yaml",  None),        # worker --site products.aspose.net.words
    ("blog.aspose.net.yaml",            "words"),     # worker --site blog.aspose.net (scoped to /words)
    # reference.aspose.net excluded from sprint scope (163 files × 36 locales = 5,868 pairs;
    # scheduled for a separate dedicated reference sprint)
    # ("reference.aspose.net.words.yaml", None),      # worker --site reference.aspose.net.words
]

# Surface name extracted from profile site_id for display purposes
SECTION_MAP = {
    "docs": "Docs",
    "kb": "KB",
    "blog": "Blog",
    "products": "Product Pages",
    "reference": "API Reference",
}

STALE_REASONS = {
    "missing_localized_page": 1,       # Priority 1 — highest
    "localized_page_older_than_source": 2,
    "no_change_detected": 5,
    "unknown_needs_manual_review": 5,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def expand_content_roots(content_roots: list, content_base: str) -> list[Path]:
    """Expand ${ASPOSE_NET_CONTENT} and other env vars in content_roots."""
    expanded = []
    for root in content_roots:
        expanded_str = root.replace("${ASPOSE_NET_CONTENT}", content_base)
        expanded_str = os.path.expandvars(expanded_str)
        p = Path(expanded_str)
        if p.exists():
            expanded.append(p)
        else:
            print(f"  [WARN] content_root does not exist: {expanded_str}", file=sys.stderr)
    return expanded


def detect_locale_convention(profile: dict) -> str:
    """Return 'subdirectory' or 'filename' based on output_layout."""
    layout = profile.get("output_layout", {})
    if layout.get("per_language_folders", True):
        return "subdirectory"
    pattern = layout.get("pattern", "")
    if "{filename}" in pattern or "{stem}" in pattern or "{lang}" in pattern and "{ext}" in pattern:
        return "filename"
    return "subdirectory"


def find_english_files(content_root: Path, convention: str) -> list[Path]:
    """Return list of English source .md files."""
    if convention == "subdirectory":
        en_dir = content_root / "en"
        if not en_dir.exists():
            return []
        return sorted(en_dir.rglob("*.md"))
    else:
        # Filename convention: source files are those WITHOUT a lang suffix
        # Pattern: index.md is source; index.es.md is already translated
        # Use a simple heuristic: filename has no second extension that is a locale code
        all_md = sorted(content_root.rglob("*.md"))
        # Build locale set from a reasonable set of lang codes
        lang_suffixes = {
            "ar", "bg", "ca", "cs", "da", "de", "el", "es", "fa", "fi", "fr",
            "he", "hi", "hr", "hu", "id", "it", "ja", "ko", "lt", "lv", "ms",
            "nl", "no", "pl", "pt", "ro", "ru", "sk", "sr", "sv", "th", "tr",
            "uk", "vi", "zh",
        }
        source_files = []
        for f in all_md:
            # e.g. "index.es.md" → stem = "index.es", second_ext = "es"
            name = f.name  # "index.es.md"
            parts = name.split(".")
            # source: index.md → ["index", "md"]
            # translated: index.es.md → ["index", "es", "md"]
            if len(parts) >= 3 and parts[-2].lower() in lang_suffixes:
                continue  # skip translated files
            source_files.append(f)
        return source_files


def get_expected_localized_path(
    source_path: Path,
    content_root: Path,
    locale: str,
    convention: str,
    output_pattern: str,
) -> Path:
    """Compute expected path for a localized file."""
    if convention == "subdirectory":
        # source: {content_root}/en/some/path.md
        # output: {content_root}/{locale}/some/path.md
        rel = source_path.relative_to(content_root / "en")
        return content_root / locale / rel
    else:
        # source: {content_root}/some/dir/index.md
        # output: {content_root}/some/dir/index.{locale}.md
        stem = source_path.stem  # "index"
        suffix = source_path.suffix  # ".md"
        return source_path.parent / f"{stem}.{locale}{suffix}"


def get_surface_from_site_id(site_id: str) -> str:
    """Extract surface label (docs, kb, blog, products, reference) from site_id."""
    site_lower = site_id.lower()
    for key in SECTION_MAP:
        if key in site_lower:
            return key
    return "unknown"


def estimate_segments(source_path: Path) -> int:
    """Rough estimate of segment count from file size."""
    try:
        size = source_path.stat().st_size
        # ~100 bytes per segment on average for markdown
        return max(1, size // 100)
    except OSError:
        return 0


def estimate_tokens(segment_count: int) -> int:
    """Rough token estimate: ~30 tokens per segment (English technical content)."""
    return segment_count * 30


def determine_stale_reason(
    source_path: Path,
    localized_path: Path,
) -> str:
    """Determine stale reason by comparing file existence and mtimes."""
    if not localized_path.exists():
        return "missing_localized_page"

    try:
        src_mtime = source_path.stat().st_mtime
        loc_mtime = localized_path.stat().st_mtime
        if src_mtime > loc_mtime + 1.0:  # 1-second tolerance for filesystem precision
            return "localized_page_older_than_source"
        return "no_change_detected"
    except OSError:
        return "unknown_needs_manual_review"


def determine_change_type(stale_reason: str, localized_path: Path) -> str:
    if stale_reason == "missing_localized_page":
        return "new_file"
    if stale_reason == "localized_page_older_than_source":
        return "source_updated"
    return "no_change"


def determine_priority(stale_reason: str) -> int:
    return STALE_REASONS.get(stale_reason, 5)


def check_frontmatter(source_path: Path) -> str:
    """Quick frontmatter validity check on the source file."""
    try:
        content = source_path.read_text(encoding="utf-8", errors="replace")
        if not content.startswith("---"):
            return "no_frontmatter"
        end = content.find("\n---", 3)
        if end == -1:
            return "unclosed_frontmatter"
        yaml.safe_load(content[3:end])
        return "ok"
    except Exception:
        return "parse_error"


def build_record(
    source_path: Path,
    content_root: Path,
    site_id: str,
    profile_key: str,
    surface: str,
    convention: str,
    output_pattern: str,
    locale: str,
    frontmatter_status: str,
) -> dict:
    """Build one inventory ledger record."""
    localized_path = get_expected_localized_path(
        source_path, content_root, locale, convention, output_pattern
    )
    stale_reason = determine_stale_reason(source_path, localized_path)
    change_type = determine_change_type(stale_reason, localized_path)
    priority = determine_priority(stale_reason)
    localized_exists = localized_path.exists()
    translation_required = stale_reason in (
        "missing_localized_page",
        "localized_page_older_than_source",
    )
    improvement_required = stale_reason == "no_change_detected" and localized_exists
    seg_count = estimate_segments(source_path)

    return {
        "source_english_path": str(source_path),
        "website_surface": site_id,
        "profile_key": profile_key,    # filename stem (without .yaml) — use as --site arg for worker CLI
        "product": "Aspose.Words",
        "content_type": surface,
        "locale": locale,
        "localized_path": str(localized_path),
        "source_exists": source_path.exists(),
        "localized_exists": localized_exists,
        "source_hash_current": None,   # Hash comparison requires MetadataTracker; not available pre-sprint
        "localized_source_hash_recorded": None,
        "stale_reason": stale_reason,
        "change_type": change_type,
        "frontmatter_status": frontmatter_status,
        "markdown_structure_status": "unchecked",
        "shortcode_status": "unchecked",
        "protected_terms_status": "unchecked",
        "tm_status": "unknown",
        "translation_required": translation_required,
        "improvement_required": improvement_required,
        "priority": priority,
        "estimated_segments": seg_count,
        "estimated_tokens": estimate_tokens(seg_count),
        "recommended_worker_queue": "content_translation" if translation_required else "quality_review",
        "recommended_translation_strategy": "tm_l2_then_model" if translation_required else "quality_only",
        "validation_commands": [
            f"python -m src.workers.autonomous_verification_worker "
            f"--site {site_id} --log-level INFO"
        ],
        "expected_output_artifacts": [str(localized_path)],
        "risk_level": "low" if surface in ("docs", "kb") else "medium" if surface in ("blog", "products") else "high",
        "notes": "",
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", help="Output JSONL path (default: data/sprints/words-inventory-YYYYMMDD.jsonl)")
    parser.add_argument("--site", help="Only scan this site_id (default: all words surfaces)")
    parser.add_argument("--verbose", action="store_true", help="Print each record to stdout")
    args = parser.parse_args()

    # Resolve ASPOSE_NET_CONTENT
    content_base = os.environ.get("ASPOSE_NET_CONTENT", "")
    if not content_base:
        print("ERROR: ASPOSE_NET_CONTENT environment variable is not set.", file=sys.stderr)
        print("  Set it to the root of the aspose.net content repository.", file=sys.stderr)
        print("  Example: export ASPOSE_NET_CONTENT=/d/onedrive/Documents/GitHub/aspose.net/content", file=sys.stderr)
        sys.exit(1)

    content_base_path = Path(content_base)
    if not content_base_path.exists():
        print(f"ERROR: ASPOSE_NET_CONTENT path does not exist: {content_base}", file=sys.stderr)
        sys.exit(1)

    # Locate config/site_profiles directory
    script_dir = Path(__file__).parent
    repo_root = script_dir.parent
    profiles_dir = repo_root / "config" / "site_profiles"
    if not profiles_dir.exists():
        print(f"ERROR: site_profiles directory not found: {profiles_dir}", file=sys.stderr)
        sys.exit(2)

    # Determine output path
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    if args.output:
        output_path = Path(args.output)
    else:
        sprints_dir = repo_root / "data" / "sprints"
        sprints_dir.mkdir(parents=True, exist_ok=True)
        output_path = sprints_dir / f"words-inventory-{today}.jsonl"

    print(f"\n{'='*70}")
    print(f"  ASPOSE.WORDS TRANSLATION SPRINT — INVENTORY SCAN")
    print(f"  Date: {today}")
    print(f"  Content root: {content_base}")
    print(f"  Output: {output_path}")
    print(f"{'='*70}\n")

    records = []
    summary: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for profile_name, words_subdir_override in WORDS_SURFACE_PROFILES:
        profile_path = profiles_dir / profile_name
        if not profile_path.exists():
            print(f"  [SKIP] Profile not found: {profile_name}")
            continue

        profile = load_yaml(profile_path)
        site_id = profile.get("site_id", "")
        # profile_key is the filename stem (without .yaml); this is the --site arg for the worker CLI.
        # The worker CLI resolves profiles by filename, not by the site_id field inside the profile.
        profile_key = Path(profile_name).stem   # e.g. "docs.aspose.net.words"
        display_name = profile.get("display_name", site_id)
        surface = get_surface_from_site_id(site_id)

        # Apply --site filter: match on either site_id or profile_key
        if args.site and args.site not in (site_id, profile_key):
            continue

        raw_roots = expand_content_roots(
            profile.get("content_roots", []), content_base
        )
        if not raw_roots:
            print(f"  [SKIP] No resolvable content roots for: {site_id}")
            continue

        # Apply words_subdir_override: narrow content_root to the /words subdir
        if words_subdir_override:
            content_roots = []
            for r in raw_roots:
                narrowed = r / words_subdir_override
                if narrowed.exists():
                    content_roots.append(narrowed)
                else:
                    print(f"  [WARN] words subdir not found: {narrowed}", file=sys.stderr)
        else:
            content_roots = raw_roots

        if not content_roots:
            print(f"  [SKIP] No valid content roots after subdir filter for: {site_id}")
            continue

        target_langs = profile.get("target_langs", [])
        output_layout = profile.get("output_layout", {})
        output_pattern = output_layout.get("pattern", "{lang}/{path}")
        convention = detect_locale_convention(profile)

        print(f"  [{site_id}] surface={surface} convention={convention} locales={len(target_langs)}")

        for content_root in content_roots:
            english_files = find_english_files(content_root, convention)
            print(f"    content_root: {content_root}")
            print(f"    english_files_found: {len(english_files)}")

            if not english_files:
                print(f"    [WARN] No English source files found under {content_root}")
                continue

            # Frontmatter check is per-source-file (not per locale)
            frontmatter_cache: dict[Path, str] = {}

            for source_path in english_files:
                if source_path not in frontmatter_cache:
                    frontmatter_cache[source_path] = check_frontmatter(source_path)
                fm_status = frontmatter_cache[source_path]

                for locale in target_langs:
                    record = build_record(
                        source_path=source_path,
                        content_root=content_root,
                        site_id=site_id,
                        profile_key=profile_key,
                        surface=surface,
                        convention=convention,
                        output_pattern=output_pattern,
                        locale=locale,
                        frontmatter_status=fm_status,
                    )
                    records.append(record)

                    # Accumulate summary
                    summary[site_id][record["stale_reason"]] += 1

                    if args.verbose:
                        print(f"      {record['stale_reason']:40s} {source_path.name}@{locale}")

    if not records:
        print("\n[WARN] No records generated. Check profiles and ASPOSE_NET_CONTENT.")
        sys.exit(2)

    # Write JSONL output
    with open(output_path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # Print summary table
    total_translation_required = sum(1 for r in records if r["translation_required"])
    total_improvement_required = sum(1 for r in records if r["improvement_required"])
    total_no_action = len(records) - total_translation_required - total_improvement_required

    print(f"\n{'='*70}")
    print(f"  SUMMARY")
    print(f"{'='*70}")
    print(f"  Total (source, locale) pairs scanned: {len(records)}")
    print(f"  Translation required:                 {total_translation_required}")
    print(f"  Improvement/quality review:           {total_improvement_required}")
    print(f"  No action needed:                     {total_no_action}")
    print()
    print(f"  {'Surface':<35} {'missing':>8} {'stale':>8} {'ok':>8}")
    print(f"  {'-'*35} {'-'*8} {'-'*8} {'-'*8}")
    for site_id, counts in sorted(summary.items()):
        missing = counts.get("missing_localized_page", 0)
        stale = counts.get("localized_page_older_than_source", 0)
        ok = counts.get("no_change_detected", 0)
        print(f"  {site_id:<35} {missing:>8} {stale:>8} {ok:>8}")
    print(f"{'='*70}")
    print(f"\n  Ledger written to: {output_path}")
    print(f"  Records: {len(records)}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
