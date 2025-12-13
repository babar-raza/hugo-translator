#!/usr/bin/env python3
"""
Test script for SE-01 fix: Nested Array Field Extraction.

This script verifies that the segment extractor correctly handles
nested array paths like body.block.title_left and faq.list.question.

Run: python scripts/test_nested_array_fix.py
"""

import sys
import os
from pathlib import Path
from datetime import datetime

# Add src to path
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.chdir(str(REPO_ROOT))

# Set up logging
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_segment_extraction():
    """Test segment extraction with nested arrays."""
    print("=" * 70)
    print("SE-01 FIX VERIFICATION: Nested Array Field Extraction")
    print(f"Started: {datetime.now().isoformat()}")
    print("=" * 70)

    # Import components
    print("\n[1/4] Importing components...")
    try:
        from src.translation_engine.extractor.segment_extractor import SegmentExtractor
        from src.utils.config_loader import ConfigService
        print("   OK: Components imported")
    except ImportError as e:
        print(f"   ERROR: Import failed: {e}")
        return False

    # Load site profile
    print("\n[2/4] Loading site profile...")
    try:
        config_path = REPO_ROOT / "config"
        config_service = ConfigService(config_path)
        profile = config_service.get_site_profile("products.aspose.net")
        extractor = SegmentExtractor(profile)
        print(f"   OK: Loaded profile for {profile.site_id}")
    except Exception as e:
        print(f"   ERROR: Failed to load profile: {e}")
        return False

    # Test data matching real products.aspose.net structure
    print("\n[3/4] Testing segment extraction with nested arrays...")

    test_frontmatter = {
        "title": "Programmatic Presentation Merging",
        "description": "Test description",
        "body": {
            "enable": True,
            "block": [
                {
                    "title_left": "Merging Presentations in .NET",
                    "content_left": "Add the Aspose.Slides plugin to your .NET project from NuGet.",
                    "title_right": "Acquire Aspose.Slides for .NET",
                    "content_right": "Get Aspose.Slides for .NET from the releases page or NuGet."
                },
                {
                    "title_left": "Best Practices for Presentation Merging",
                    "content_left": "Ensure that all input presentations are in supported formats.",
                    "title_right": "Troubleshooting Merging Operations",
                    "content_right": "If issues arise, verify that Aspose.Slides is correctly referenced."
                }
            ]
        },
        "faq": {
            "enable": True,
            "list": [
                {"question": "Do I need to install this plugin separately?", "answer": "No."},
                {"question": "Which presentation formats are supported?", "answer": "PPT, PPTX, POTX."},
                {"question": "Can I merge presentations from streams?", "answer": "Yes."},
            ]
        }
    }

    # Test extraction
    segments = extractor.extract_from_frontmatter(test_frontmatter, "en")

    print(f"   Total segments extracted: {len(segments)}")

    # Group by key pattern
    segment_keys = {}
    for seg in segments:
        key = seg.context.frontmatter_key
        segment_keys[key] = seg.source_text[:50] + "..." if len(seg.source_text) > 50 else seg.source_text

    # Check expected fields
    expected_patterns = [
        "title",
        "description",
        "body.block[0].title_left",
        "body.block[0].content_left",
        "body.block[0].title_right",
        "body.block[0].content_right",
        "body.block[1].title_left",
        "body.block[1].content_left",
        "body.block[1].title_right",
        "body.block[1].content_right",
        "faq.list[0].question",
        "faq.list[0].answer",
        "faq.list[1].question",
        "faq.list[1].answer",
        "faq.list[2].question",
        "faq.list[2].answer",
    ]

    found = []
    missing = []

    for pattern in expected_patterns:
        if pattern in segment_keys:
            found.append(pattern)
            print(f"   FOUND: {pattern}")
        else:
            missing.append(pattern)
            print(f"   MISSING: {pattern}")

    # Summary
    print("\n[4/4] Results")
    print("=" * 70)

    success = len(missing) == 0

    if success:
        print(f"PASS: All {len(expected_patterns)} expected segments found!")
    else:
        print(f"FAIL: {len(missing)} segments missing:")
        for m in missing:
            print(f"   - {m}")

    print(f"\nSegments extracted: {len(found)}/{len(expected_patterns)}")
    print("=" * 70)

    return success


def test_real_file():
    """Test extraction on a real products.aspose.net file."""
    print("\n" + "=" * 70)
    print("REAL FILE TEST")
    print("=" * 70)

    source_file = Path(r"D:\onedrive\Documents\GitHub\aspose.net\content\products.aspose.net\slides\en\presentation-merger\_index.md")

    if not source_file.exists():
        print(f"   SKIP: Source file not found: {source_file}")
        return None

    print(f"\n[1/3] Loading source file...")
    print(f"   Path: {source_file}")

    try:
        from src.translation_engine.parser import HugoParser
        from src.translation_engine.extractor.segment_extractor import SegmentExtractor
        from src.utils.config_loader import ConfigService

        config_path = Path(__file__).parent.parent / "config"
        config_service = ConfigService(config_path)
        profile = config_service.get_site_profile("products.aspose.net")

        parser = HugoParser()
        doc = parser.parse_file(source_file)

        extractor = SegmentExtractor(profile)
        segments = extractor.extract_all(doc, "en")

        print(f"   OK: Parsed file successfully")
        print(f"\n[2/3] Extracted segments: {len(segments)}")

        # Group by context type
        frontmatter_segs = [s for s in segments if s.context.context_type.value == "frontmatter"]
        body_segs = [s for s in segments if s.context.context_type.value != "frontmatter"]

        print(f"   Frontmatter segments: {len(frontmatter_segs)}")
        print(f"   Body segments: {len(body_segs)}")

        # Show frontmatter keys
        print("\n[3/3] Frontmatter segment keys:")
        for seg in frontmatter_segs:
            key = seg.context.frontmatter_key
            text_preview = seg.source_text[:40] + "..." if len(seg.source_text) > 40 else seg.source_text
            print(f"   {key}: {text_preview}")

        # Check for nested array segments
        nested_array_keys = [s.context.frontmatter_key for s in frontmatter_segs
                           if "[" in s.context.frontmatter_key]

        print(f"\n   Nested array segments found: {len(nested_array_keys)}")

        if len(nested_array_keys) > 0:
            print("   PASS: Nested array extraction working!")
            return True
        else:
            print("   WARN: No nested array segments found - check site profile")
            return False

    except Exception as e:
        print(f"   ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    # Run unit test
    result1 = test_segment_extraction()

    # Run real file test
    result2 = test_real_file()

    # Final status
    print("\n" + "=" * 70)
    print("FINAL STATUS")
    print("=" * 70)
    print(f"Unit test: {'PASS' if result1 else 'FAIL'}")
    print(f"Real file test: {'PASS' if result2 else 'SKIP' if result2 is None else 'FAIL'}")

    sys.exit(0 if result1 else 1)
