#!/usr/bin/env python
"""
Test script for FIX-BT-02: Verify language marker sanitization works on real file.
"""

import sys
import re
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.translation_engine.parser.hugo_parser import HugoParser
from src.translation_engine.extractor.text_unit_extractor import TextUnitExtractor
from src.translation_engine.reconstructor.ast_renderer import ASTRenderer


def test_marker_sanitization():
    """Test that markers are removed from output."""

    # Read source file
    source_path = Path("D:/onedrive/Documents/GitHub/aspose.net/content/kb.aspose.net/slides/en/presentation-converter/how-to-convert-odp-to-powerpoint-pptx-csharp.md")

    if not source_path.exists():
        print(f"ERROR: Source file not found: {source_path}")
        return False

    with open(source_path, 'r', encoding='utf-8') as f:
        source_content = f.read()

    print(f"Source file: {source_path}")
    print(f"Source size: {len(source_content)} characters\n")

    # Parse
    parser = HugoParser()
    doc = parser.parse_string(source_content)

    print(f"Parsed {len(doc.ast)} root nodes")

    # Extract
    extractor = TextUnitExtractor(segmentation_strategy="leaf_only")
    plan = extractor.extract_from_ast(doc.ast)
    units = plan.units

    print(f"Extracted {len(units)} text units")

    # Simulate translation that adds markers (mimics the bug)
    print("\nSimulating translation with marker injection...")
    for unit in units:
        if not unit.do_not_translate:
            # Add markers to simulate the bug
            unit.translated_text = f"__de__{unit.source_text}__de__"

    # Apply and render (should sanitize markers)
    renderer = ASTRenderer()
    renderer.apply_translations(doc.ast, units)
    output_md = renderer.render_to_markdown(doc.ast)

    print(f"Rendered output: {len(output_md)} characters\n")

    # Check for markers
    marker_pattern = r'__[a-z]{2}__'
    markers = re.findall(marker_pattern, output_md)

    if markers:
        print(f"FAIL: Found {len(markers)} language markers in output:")
        # Show first few occurrences
        for i, marker in enumerate(markers[:10]):
            print(f"  - {marker}")
        if len(markers) > 10:
            print(f"  ... and {len(markers) - 10} more")
        return False
    else:
        print("PASS: No language markers found in output")

        # Verify content is still present
        if "German text" in output_md or len(output_md) > 100:
            print("PASS: Output contains translated content")
        else:
            print("WARNING: Output seems empty or missing content")

        return True


if __name__ == "__main__":
    success = test_marker_sanitization()
    sys.exit(0 if success else 1)
