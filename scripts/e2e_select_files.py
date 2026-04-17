#!/usr/bin/env python
"""
E2E File Selection Script.

Selects interesting files for bulk E2E testing based on complexity markers:
- Nested lists
- Tables
- Shortcodes
- Code fences
"""
import re
import random
from pathlib import Path
from typing import List, Dict, Tuple

CONTENT_ROOT = Path(r"D:\onedrive\Documents\GitHub\aspose.net\content")
REPORTS_DIR = Path(r"c:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\reports")

# Patterns for "interesting" content
NESTED_LIST_PATTERN = re.compile(r'^\s{2,}[-*+]\s', re.MULTILINE)
SHORTCODE_PATTERN = re.compile(r'\{\{[<\%]')
TABLE_PATTERN = re.compile(r'^\|.*\|', re.MULTILINE)
CODE_FENCE_PATTERN = re.compile(r'^```', re.MULTILINE)


def score_file(file_path: Path) -> Tuple[int, Dict[str, int]]:
    """
    Score a file based on complexity markers.

    Returns:
        (total_score, breakdown_dict)
    """
    try:
        content = file_path.read_text(encoding='utf-8')
    except Exception:
        return (0, {})

    breakdown = {
        'nested_lists': len(NESTED_LIST_PATTERN.findall(content)),
        'shortcodes': len(SHORTCODE_PATTERN.findall(content)),
        'tables': len(TABLE_PATTERN.findall(content)),
        'code_fences': len(CODE_FENCE_PATTERN.findall(content)),
    }

    # Weight different features
    total = (
        breakdown['nested_lists'] * 3 +  # High priority
        breakdown['shortcodes'] * 2 +
        breakdown['tables'] * 2 +
        breakdown['code_fences'] * 1
    )

    return (total, breakdown)


def select_files(root_path: Path, count: int, file_pattern: str = "*.md") -> List[Path]:
    """
    Select the most interesting files from a directory.

    Args:
        root_path: Root directory to search
        count: Number of files to select
        file_pattern: Glob pattern for files

    Returns:
        List of selected file paths
    """
    if not root_path.exists():
        print(f"WARNING: Path does not exist: {root_path}")
        return []

    # Find all markdown files
    all_files = list(root_path.rglob(file_pattern))

    if len(all_files) == 0:
        print(f"WARNING: No files found in {root_path}")
        return []

    print(f"Found {len(all_files)} files in {root_path}")

    # Score all files
    scored_files = []
    for file_path in all_files:
        score, breakdown = score_file(file_path)
        scored_files.append((score, file_path, breakdown))

    # Sort by score (descending)
    scored_files.sort(reverse=True, key=lambda x: x[0])

    # Select top N
    selected_count = min(count, len(scored_files))
    selected = scored_files[:selected_count]

    # If we need more files and there are low-scoring files, add them
    if selected_count < count:
        # Add remaining files randomly
        remaining = scored_files[selected_count:]
        random.shuffle(remaining)
        additional_needed = count - selected_count
        selected.extend(remaining[:additional_needed])

    return [(file_path, score, breakdown) for score, file_path, breakdown in selected]


def main():
    """Main file selection logic."""
    print("=" * 60)
    print("E2E FILE SELECTION")
    print("=" * 60)

    # Define paths for slides family
    slides_paths = {
        'docs': CONTENT_ROOT / "docs.aspose.net" / "slides" / "en",
        'kb': CONTENT_ROOT / "kb.aspose.net" / "slides" / "en",
        'reference': CONTENT_ROOT / "reference.aspose.net" / "slides" / "en",
        'blog': CONTENT_ROOT / "blog.aspose.net" / "slides"
    }

    # Initialize master file list
    master_list_path = REPORTS_DIR / "E2E_BULK_filelist.txt"
    with open(master_list_path, 'w', encoding='utf-8') as f:
        f.write("E2E BULK FILE LIST (50 files)\n")
        f.write("=" * 60 + "\n\n")

    all_selected = []

    # Select files for each subdomain
    for subdomain, path in slides_paths.items():
        print(f"\n{subdomain.upper()}: Selecting files from {path}")

        # For blog, look for index.md files
        file_pattern = "index.md" if subdomain == "blog" else "*.md"

        selected = select_files(path, 10, file_pattern)

        # Write subdomain-specific report
        subdomain_report = REPORTS_DIR / f"E2E_BULK_{subdomain}10.txt"
        with open(subdomain_report, 'w', encoding='utf-8') as f:
            f.write(f"{subdomain.upper()} - SELECTED FILES (10)\n")
            f.write("=" * 60 + "\n\n")

            for file_path, score, breakdown in selected:
                f.write(f"{file_path}\n")
                f.write(f"  Score: {score}\n")
                f.write(f"  Nested lists: {breakdown['nested_lists']}, ")
                f.write(f"Shortcodes: {breakdown['shortcodes']}, ")
                f.write(f"Tables: {breakdown['tables']}, ")
                f.write(f"Code fences: {breakdown['code_fences']}\n\n")

        # Append to master list
        with open(master_list_path, 'a', encoding='utf-8') as f:
            f.write(f"\n{subdomain.upper()} (10 files):\n")
            f.write("-" * 60 + "\n")
            for file_path, score, breakdown in selected:
                f.write(f"{file_path}\n")

        all_selected.extend([file_path for file_path, _, _ in selected])

        print(f"  Selected {len(selected)} files (saved to {subdomain_report})")

    print(f"\n{'=' * 60}")
    print(f"SLIDES FAMILY: Selected {len(all_selected)} files total")
    print(f"Master list saved to: {master_list_path}")
    print(f"{'=' * 60}")

    return all_selected


if __name__ == "__main__":
    # Set random seed for deterministic selection
    random.seed(20260128)
    main()
