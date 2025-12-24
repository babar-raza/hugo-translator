#!/usr/bin/env python3
"""
Validate internal links in documentation files.

Usage: python scripts/check_docs_links.py docs/features/segment-sorting.md
"""
import re
import sys
from pathlib import Path


def check_links(doc_path: Path) -> list[str]:
    """Check all markdown links in doc_path."""
    broken_links = []
    content = doc_path.read_text(encoding="utf-8")

    # Find all markdown links: [text](path) or [text](path#anchor)
    link_pattern = r'\[([^\]]+)\]\(([^)]+)\)'

    for match in re.finditer(link_pattern, content):
        link_text, link_path = match.groups()

        # Skip external links
        if link_path.startswith(('http://', 'https://', 'mailto:')):
            continue

        # Parse path and anchor
        path_part = link_path.split('#')[0] if '#' in link_path else link_path
        anchor = link_path.split('#')[1] if '#' in link_path else None

        # Skip empty paths (anchor-only links like #heading)
        if not path_part:
            continue

        # Resolve relative path
        target = (doc_path.parent / path_part).resolve()

        # Check file exists
        if not target.exists():
            broken_links.append(f"Missing file: {link_path} (in {doc_path.name})")
            continue

        # Check anchor exists (simplified - just check heading exists)
        if anchor and target.exists() and target.suffix == '.md':
            target_content = target.read_text(encoding='utf-8')
            # Convert anchor to heading format (remove dashes, case-insensitive)
            heading_text = anchor.replace('-', ' ')
            # Check if heading exists (case-insensitive)
            if not any(heading_text.lower() in line.lower() for line in target_content.split('\n') if line.startswith('#')):
                broken_links.append(f"Missing anchor: {link_path} (in {doc_path.name})")

    return broken_links


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python scripts/check_docs_links.py <doc_file>")
        sys.exit(1)

    doc = Path(sys.argv[1])
    if not doc.exists():
        print(f"[ERROR] File not found: {doc}")
        sys.exit(1)

    broken = check_links(doc)

    if broken:
        print(f"[FAIL] Found {len(broken)} broken links:")
        for link in broken:
            print(f"  - {link}")
        sys.exit(1)
    else:
        print(f"[PASS] All links valid in {doc.name}")
        sys.exit(0)
