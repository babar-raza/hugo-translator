#!/usr/bin/env python3
"""
Reverify structural element counts with precise pattern matching.
"""

import re
from collections import defaultdict
from pathlib import Path

BASE_PATH = Path("D:/onedrive/Documents/GitHub/aspose.net/content/kb.aspose.net/slides")

def count_structures(file_path):
    """Count structural elements in a markdown file."""
    try:
        content = file_path.read_text(encoding='utf-8')
    except:
        return None

    # Remove frontmatter
    if content.startswith('---'):
        parts = content.split('---', 2)
        if len(parts) >= 3:
            content = parts[2]

    # Remove code blocks to avoid false positives
    content_no_code = re.sub(r'```[\s\S]*?```', '', content)

    counts = {
        # Ordered list: line starting with number followed by period and space
        'ordered_list_items': len(re.findall(r'^\s*\d+\.\s+\S', content_no_code, re.MULTILINE)),

        # Bullet list: line starting with - or * followed by space
        'bullet_list_items': len(re.findall(r'^\s*[-*]\s+\S', content_no_code, re.MULTILINE)),

        # Links: [text](url) pattern
        'links': len(re.findall(r'\[([^\]]+)\]\(([^)]+)\)', content_no_code)),

        # Bold: **text** pattern (not inside code)
        'bold': len(re.findall(r'\*\*[^*]+\*\*', content_no_code)),

        # Code blocks (count in original content)
        'code_blocks': len(re.findall(r'```', content)) // 2,

        # Inline code: `text` pattern
        'inline_code': len(re.findall(r'`[^`\n]+`', content_no_code)),

        # Shortcodes: {{< >}} or {{% %}} pattern
        'shortcodes': len(re.findall(r'\{\{[<%].*?[%>]\}\}', content)),

        # Headings: # at start of line
        'headings': len(re.findall(r'^#{1,6}\s+', content, re.MULTILINE)),
    }

    return counts


def analyze_folder(folder_path):
    """Analyze all markdown files in a folder."""
    totals = defaultdict(int)
    file_count = 0

    for md_file in folder_path.rglob("*.md"):
        counts = count_structures(md_file)
        if counts:
            file_count += 1
            for key, val in counts.items():
                totals[key] += val

    return dict(totals), file_count


def main():
    print("=" * 80)
    print("REVERIFICATION: Structural Element Analysis")
    print("=" * 80)

    # Analyze each language
    results = {}
    for lang in ['en', 'de', 'fr']:
        folder = BASE_PATH / lang
        if folder.exists():
            totals, count = analyze_folder(folder)
            results[lang] = {'totals': totals, 'file_count': count}
            print(f"\n{lang.upper()}: {count} files analyzed")
        else:
            print(f"\n{lang.upper()}: Folder not found!")

    # Print comparison table
    print("\n" + "=" * 80)
    print("STRUCTURAL ELEMENT COMPARISON")
    print("=" * 80)

    elements = ['ordered_list_items', 'bullet_list_items', 'links', 'bold',
                'code_blocks', 'inline_code', 'shortcodes', 'headings']

    print(f"\n{'Element':<25} {'EN':<10} {'DE':<10} {'FR':<10} {'DE vs EN':<12} {'FR vs EN':<12}")
    print("-" * 80)

    for elem in elements:
        en_val = results.get('en', {}).get('totals', {}).get(elem, 0)
        de_val = results.get('de', {}).get('totals', {}).get(elem, 0)
        fr_val = results.get('fr', {}).get('totals', {}).get(elem, 0)

        de_diff = de_val - en_val
        fr_diff = fr_val - en_val

        de_pct = f"({de_diff:+d})" if de_diff != 0 else "(OK)"
        fr_pct = f"({fr_diff:+d})" if fr_diff != 0 else "(OK)"

        # Mark critical issues
        status = ""
        if elem in ['ordered_list_items', 'links', 'bold'] and (de_val == 0 or fr_val == 0) and en_val > 0:
            status = " CRITICAL!"

        print(f"{elem:<25} {en_val:<10} {de_val:<10} {fr_val:<10} {de_pct:<12} {fr_pct:<12}{status}")

    # Summary
    print("\n" + "=" * 80)
    print("VERIFICATION SUMMARY")
    print("=" * 80)

    critical_issues = []
    if results.get('en', {}).get('totals', {}).get('ordered_list_items', 0) > 0:
        if results.get('de', {}).get('totals', {}).get('ordered_list_items', 0) == 0:
            critical_issues.append("DE: All ordered lists LOST")
        if results.get('fr', {}).get('totals', {}).get('ordered_list_items', 0) == 0:
            critical_issues.append("FR: All ordered lists LOST")

    if results.get('en', {}).get('totals', {}).get('links', 0) > 0:
        if results.get('de', {}).get('totals', {}).get('links', 0) == 0:
            critical_issues.append("DE: All links LOST")
        if results.get('fr', {}).get('totals', {}).get('links', 0) == 0:
            critical_issues.append("FR: All links LOST")

    if results.get('en', {}).get('totals', {}).get('bold', 0) > 0:
        if results.get('de', {}).get('totals', {}).get('bold', 0) == 0:
            critical_issues.append("DE: All bold markers LOST")
        if results.get('fr', {}).get('totals', {}).get('bold', 0) == 0:
            critical_issues.append("FR: All bold markers LOST")

    if critical_issues:
        print("\nCRITICAL ISSUES CONFIRMED:")
        for issue in critical_issues:
            print(f"  - {issue}")
    else:
        print("\nNo critical issues found - translations preserve structure.")

    # Sample file check
    print("\n" + "=" * 80)
    print("SAMPLE FILE VERIFICATION")
    print("=" * 80)

    sample_file = "presentation-converter/how-to-convert-odp-to-powerpoint-pptx-csharp.md"

    for lang in ['en', 'de', 'fr']:
        file_path = BASE_PATH / lang / sample_file
        if file_path.exists():
            counts = count_structures(file_path)
            if counts:
                print(f"\n{lang.upper()}: {sample_file}")
                for key, val in sorted(counts.items()):
                    print(f"  {key}: {val}")


if __name__ == "__main__":
    main()
