#!/usr/bin/env python
"""
E2E Random Family Selection Script.

Selects 5 random non-slides families and 2 files from each.
"""

import random
import re
from pathlib import Path

CONTENT_ROOT = Path(r"D:\onedrive\Documents\GitHub\aspose.net\content")
REPORTS_DIR = Path(r"c:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\reports")

# Reuse scoring logic from e2e_select_files.py
NESTED_LIST_PATTERN = re.compile(r"^\s{2,}[-*+]\s", re.MULTILINE)
SHORTCODE_PATTERN = re.compile(r"\{\{[<\%]")
TABLE_PATTERN = re.compile(r"^\|.*\|", re.MULTILINE)
CODE_FENCE_PATTERN = re.compile(r"^```", re.MULTILINE)


def score_file(file_path: Path) -> tuple[int, dict[str, int]]:
    """Score a file based on complexity markers."""
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception:
        return (0, {})

    breakdown = {
        "nested_lists": len(NESTED_LIST_PATTERN.findall(content)),
        "shortcodes": len(SHORTCODE_PATTERN.findall(content)),
        "tables": len(TABLE_PATTERN.findall(content)),
        "code_fences": len(CODE_FENCE_PATTERN.findall(content)),
    }

    total = (
        breakdown["nested_lists"] * 3
        + breakdown["shortcodes"] * 2
        + breakdown["tables"] * 2
        + breakdown["code_fences"] * 1
    )

    return (total, breakdown)


def discover_families() -> set[str]:
    """
    Discover all product families in the content repo.

    Returns:
        Set of family names (excluding slides and system directories)
    """
    families = set()

    # Check common subdomain roots
    subdomain_roots = [
        CONTENT_ROOT / "docs.aspose.net",
        CONTENT_ROOT / "kb.aspose.net",
        CONTENT_ROOT / "reference.aspose.net",
    ]

    for root in subdomain_roots:
        if not root.exists():
            continue

        # List all directories in this root (each is a family)
        for item in root.iterdir():
            if item.is_dir() and not item.name.startswith(".") and not item.name.startswith("_"):
                # Extract family name
                family = item.name
                if family not in ["slides", "en", "common"]:  # Exclude slides and special dirs
                    families.add(family)

    return families


def find_files_for_family(family: str, count: int = 2) -> list[tuple[Path, int, dict]]:
    """
    Find interesting files for a specific family.

    Looks in docs/kb/reference subdomains.

    Args:
        family: Family name (e.g., 'words', 'cells')
        count: Number of files to select

    Returns:
        List of (file_path, score, breakdown) tuples
    """
    search_paths = [
        CONTENT_ROOT / "docs.aspose.net" / family / "en",
        CONTENT_ROOT / "kb.aspose.net" / family / "en",
        CONTENT_ROOT / "reference.aspose.net" / family / "en",
    ]

    all_files = []
    for path in search_paths:
        if path.exists():
            # Find markdown files
            files = list(path.rglob("*.md"))
            all_files.extend(files)

    if not all_files:
        return []

    # Score files
    scored = []
    for file_path in all_files:
        score, breakdown = score_file(file_path)
        scored.append((file_path, score, breakdown))

    # Sort by score
    scored.sort(reverse=True, key=lambda x: x[1])

    # Select top N
    return scored[:count]


def main():
    """Main random family selection logic."""
    print("=" * 60)
    print("E2E RANDOM FAMILY SELECTION")
    print("=" * 60)

    # Use deterministic seed based on current date
    seed = 20260128
    random.seed(seed)

    # Discover all families
    print("\nDiscovering product families...")
    families = discover_families()
    families_list = sorted(list(families))

    print(f"Found {len(families_list)} families (excluding slides)")

    # Save families list
    families_report = REPORTS_DIR / "E2E_BULK_random_families.txt"
    with open(families_report, "w", encoding="utf-8") as f:
        f.write(f"ALL FAMILIES (excluding slides): {len(families_list)}\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"Random seed: {seed}\n\n")
        for family in families_list:
            f.write(f"  {family}\n")

    # Select 5 random families
    if len(families_list) < 5:
        print(f"WARNING: Only {len(families_list)} families available, selecting all")
        selected_families = families_list
    else:
        selected_families = random.sample(families_list, 5)
        selected_families.sort()

    print("\nRandomly selected 5 families:")
    with open(families_report, "a", encoding="utf-8") as f:
        f.write("\n\nSELECTED 5 FAMILIES:\n")
        f.write("-" * 60 + "\n")
        for family in selected_families:
            print(f"  - {family}")
            f.write(f"  {family}\n")

    # Select 2 files from each family
    all_selected = []
    random10_report = REPORTS_DIR / "E2E_BULK_random10.txt"

    with open(random10_report, "w", encoding="utf-8") as f:
        f.write("RANDOM FAMILIES - SELECTED FILES (10 total)\n")
        f.write("=" * 60 + "\n\n")

        for family in selected_families:
            print(f"\nSelecting files from {family}...")
            files = find_files_for_family(family, count=2)

            f.write(f"\n{family.upper()} (2 files):\n")
            f.write("-" * 60 + "\n")

            if not files:
                print(f"  WARNING: No files found for {family}")
                f.write("  No files found\n")
            else:
                for file_path, score, breakdown in files:
                    print(f"  {file_path.name} (score: {score})")
                    f.write(f"{file_path}\n")
                    f.write(f"  Score: {score} | ")
                    f.write(f"Nested lists: {breakdown['nested_lists']}, ")
                    f.write(f"Shortcodes: {breakdown['shortcodes']}, ")
                    f.write(f"Tables: {breakdown['tables']}, ")
                    f.write(f"Code fences: {breakdown['code_fences']}\n\n")
                    all_selected.append(file_path)

    # Append to master file list
    master_list_path = REPORTS_DIR / "E2E_BULK_filelist.txt"
    with open(master_list_path, "a", encoding="utf-8") as f:
        f.write("\n\nRANDOM FAMILIES (10 files from 5 families):\n")
        f.write("=" * 60 + "\n")
        for file_path in all_selected:
            f.write(f"{file_path}\n")

        f.write(f"\n\nTOTAL FILES: {40 + len(all_selected)}\n")

    print(f"\n{'=' * 60}")
    print(f"RANDOM FAMILIES: Selected {len(all_selected)} files total")
    print(f"Random families saved to: {families_report}")
    print(f"Selected files saved to: {random10_report}")
    print(f"Master list updated: {master_list_path}")
    print(f"{'=' * 60}")

    return all_selected


if __name__ == "__main__":
    main()
