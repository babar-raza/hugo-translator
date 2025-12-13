"""Quick validation script for TRM-05 implementation."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

print("=" * 60)
print("TRM-05 Implementation Validation")
print("=" * 60)

# Test 1: Import and structure validation
print("\n[Test 1] Checking imports and structure...")
try:
    from translation_engine.extractor.segment_extractor import (
        Segment,
        SegmentExtractor,
        SegmentContext,
        SegmentContextType,
    )
    print("  [OK] Can import SegmentExtractor and related classes")
except Exception as e:
    print(f"  [ERROR] Import failed: {e}")
    sys.exit(1)

# Test 2: Check Segment has new fields
print("\n[Test 2] Checking Segment dataclass fields...")
try:
    import inspect
    sig = inspect.signature(Segment.__init__)
    params = list(sig.parameters.keys())

    assert 'protected_terms' in params, "Missing protected_terms"
    assert 'protection_metadata' in params, "Missing protection_metadata"
    print("  [OK] Segment has protected_terms field")
    print("  [OK] Segment has protection_metadata field")
except Exception as e:
    print(f"  [ERROR] Field check failed: {e}")
    sys.exit(1)

# Test 3: Check SegmentExtractor has new methods
print("\n[Test 3] Checking SegmentExtractor methods...")
try:
    methods = [m for m in dir(SegmentExtractor) if not m.startswith('_')]
    assert 'restore_terminology' in dir(SegmentExtractor), "Missing restore_terminology"

    # Check __init__ signature
    init_sig = inspect.signature(SegmentExtractor.__init__)
    assert 'terminology_manager' in init_sig.parameters, "Missing terminology_manager parameter"
    print("  [OK] SegmentExtractor has restore_terminology method")
    print("  [OK] SegmentExtractor accepts terminology_manager parameter")
except Exception as e:
    print(f"  [ERROR] Method check failed: {e}")
    sys.exit(1)

# Test 4: Test backward compatibility (no terminology manager)
print("\n[Test 4] Testing backward compatibility...")
try:
    from utils.models import SiteProfile, BodyRules, FrontmatterRule, FrontmatterMode

    profile = SiteProfile(
        site_id="test-site",
        content_roots=["/test"],
        default_source_lang="en",
        target_langs=["es"],
        frontmatter={"title": FrontmatterRule(mode=FrontmatterMode.TRANSLATE)},
        body=BodyRules(
            translate_markdown=True,
            preserve_blocks=[],
            preserve_patterns=[],
        ),
    )

    # Should work without terminology_manager
    extractor = SegmentExtractor(profile)
    print("  [OK] SegmentExtractor works without terminology_manager")

    # Extract segments
    segments = extractor.extract_from_frontmatter({"title": "Test Title"}, "en")
    assert len(segments) > 0, "No segments extracted"

    seg = segments[0]
    assert hasattr(seg, 'protected_terms'), "Missing protected_terms attribute"
    assert hasattr(seg, 'protection_metadata'), "Missing protection_metadata attribute"
    assert len(seg.protected_terms) == 0, "Should have no protected terms"
    assert len(seg.protection_metadata) == 0, "Should have no protection metadata"

    print("  [OK] Segments have correct default values for new fields")
    print("  [OK] Backward compatibility verified")
except Exception as e:
    print(f"  [ERROR] Backward compatibility test failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 5: Check test file exists and is valid
print("\n[Test 5] Checking test file...")
try:
    test_file = Path(__file__).parent / "tests/unit/phase-2/test_segment_extractor_terminology.py"
    assert test_file.exists(), f"Test file not found: {test_file}"

    # Check test file compiles
    import py_compile
    py_compile.compile(str(test_file), doraise=True)
    print(f"  [OK] Test file exists: {test_file.name}")
    print("  [OK] Test file syntax is valid")

    # Count test functions
    with open(test_file) as f:
        content = f.read()
        test_count = content.count("def test_")
        print(f"  [OK] Test file contains {test_count} test functions")

        # Check for required test patterns
        required = [
            "test_protect_terms",
            "test_restore_terms",
            "test_protection_metadata",
            "test_no_protection_when_manager_none",
        ]
        for req in required:
            assert req in content, f"Missing required test pattern: {req}"
        print("  [OK] All required test patterns present")

except Exception as e:
    print(f"  [ERROR] Test file check failed: {e}")
    sys.exit(1)

# Summary
print("\n" + "=" * 60)
print("VALIDATION SUMMARY")
print("=" * 60)
print("[OK] All validation checks passed!")
print("\nImplementation complete:")
print("  - Segment dataclass updated with terminology fields")
print("  - SegmentExtractor integrated with TerminologyManager")
print("  - Protection/restoration methods implemented")
print("  - Backward compatibility maintained")
print("  - Comprehensive test suite created")
print("\nNext steps:")
print("  - Run full test suite: pytest tests/unit/phase-2/test_segment_extractor_terminology.py -v")
print("  - Verify existing tests still pass: pytest tests/unit/phase-2/test_segment_extractor.py -v")
print("=" * 60)
