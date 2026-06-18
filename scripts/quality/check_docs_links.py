#!/usr/bin/env python3
"""
Validate internal links in documentation files.

Usage:
    python scripts/quality/check_docs_links.py docs/features/segment-sorting.md
    python scripts/quality/check_docs_links.py --dir docs/
"""

import argparse
import re
import sys
from pathlib import Path


def _heading_to_anchor(heading_line: str) -> str:
    """Convert a markdown heading line to a GitHub/GitLab-compatible anchor.

    Algorithm (matches GitHub Flavored Markdown):
    1. Strip leading # characters and surrounding whitespace
    2. Lowercase
    3. Remove characters that are not letters, digits, spaces, or hyphens
    4. Replace spaces with hyphens
    """
    text = re.sub(r"^#+\s*", "", heading_line).strip()
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)  # remove punctuation (keeps _ \w includes _)
    text = re.sub(r"[\s_]+", "-", text)  # spaces and underscores → hyphens
    text = text.strip("-")
    return text


def _any_heading_matches_anchor(heading_lines: list[str], anchor: str) -> bool:
    """Check if any heading generates an anchor matching the given anchor string."""
    anchor_lower = anchor.lower()
    for line in heading_lines:
        if _heading_to_anchor(line) == anchor_lower:
            return True
    return False


def check_links(doc_path: Path) -> list[str]:
    """Check all markdown links in doc_path."""
    broken_links = []
    content = doc_path.read_text(encoding="utf-8")

    # Find all markdown links: [text](path) or [text](path#anchor)
    link_pattern = r"\[([^\]]+)\]\(([^)]+)\)"

    for match in re.finditer(link_pattern, content):
        link_text, link_path = match.groups()

        # Skip external links
        if link_path.startswith(("http://", "https://", "mailto:")):
            continue

        # Parse path and anchor
        path_part = link_path.split("#")[0] if "#" in link_path else link_path
        anchor = link_path.split("#")[1] if "#" in link_path else None

        # Skip empty paths (anchor-only links like #heading)
        if not path_part:
            continue

        # Resolve relative path
        target = (doc_path.parent / path_part).resolve()

        # Check file exists
        if not target.exists():
            broken_links.append(f"Missing file: {link_path} (in {doc_path})")
            continue

        # Check anchor exists using GitHub/GitLab anchor generation rules
        if anchor and target.exists() and target.suffix == ".md":
            target_content = target.read_text(encoding="utf-8")
            headings = [line for line in target_content.split("\n") if line.startswith("#")]
            if not _any_heading_matches_anchor(headings, anchor):
                broken_links.append(f"Missing anchor: {link_path} (in {doc_path})")

    return broken_links


def check_dir(dir_path: Path) -> tuple[int, list[str]]:
    """Check all .md files in dir_path recursively. Returns (files_checked, all_broken_links)."""
    all_broken: list[str] = []
    files_checked = 0

    md_files = sorted(dir_path.rglob("*.md"))
    for md_file in md_files:
        broken = check_links(md_file)
        all_broken.extend(broken)
        files_checked += 1

    return files_checked, all_broken


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate internal links in markdown documentation files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/quality/check_docs_links.py docs/README.md\n"
            "  python scripts/quality/check_docs_links.py --dir docs/"
        ),
    )
    parser.add_argument(
        "file",
        nargs="?",
        help="Single markdown file to check",
    )
    parser.add_argument(
        "--dir",
        metavar="PATH",
        help="Directory to scan recursively for .md files",
    )

    args = parser.parse_args()

    if args.dir and args.file:
        parser.error("Provide either a file or --dir, not both.")

    if args.dir:
        dir_path = Path(args.dir)
        if not dir_path.is_dir():
            print(f"[ERROR] Directory not found: {dir_path}")
            return 1

        files_checked, broken = check_dir(dir_path)

        if broken:
            print(f"[FAIL] Found {len(broken)} broken link(s) across {files_checked} file(s):")
            for link in broken:
                print(f"  - {link}")
            return 1
        else:
            print(f"[PASS] All links valid across {files_checked} file(s) in {dir_path}")
            return 0

    elif args.file:
        doc = Path(args.file)
        if not doc.exists():
            print(f"[ERROR] File not found: {doc}")
            return 1

        broken = check_links(doc)

        if broken:
            print(f"[FAIL] Found {len(broken)} broken link(s):")
            for link in broken:
                print(f"  - {link}")
            return 1
        else:
            print(f"[PASS] All links valid in {doc.name}")
            return 0

    else:
        parser.print_help()
        return 2


if __name__ == "__main__":
    sys.exit(main())
