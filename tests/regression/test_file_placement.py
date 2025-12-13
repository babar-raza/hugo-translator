"""Quick test script for FilePlacementValidator."""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

# Import modules directly
import importlib.util
from pathlib import Path

# Load the validator module directly
spec = importlib.util.spec_from_file_location(
    "file_placement_validator",
    os.path.join(os.path.dirname(__file__), "src", "translation_engine", "validation", "file_placement_validator.py")
)
validator_module = importlib.util.module_from_spec(spec)

# Load base module
base_spec = importlib.util.spec_from_file_location(
    "base",
    os.path.join(os.path.dirname(__file__), "src", "translation_engine", "validation", "base.py")
)
base_module = importlib.util.module_from_spec(base_spec)
base_spec.loader.exec_module(base_module)

# Load models module
models_spec = importlib.util.spec_from_file_location(
    "models",
    os.path.join(os.path.dirname(__file__), "src", "utils", "models.py")
)
models_module = importlib.util.module_from_spec(models_spec)

# Inject base module into validator module's globals
sys.modules['src.translation_engine.validation.base'] = base_module
sys.modules['src.utils.models'] = models_module

# Now load validator
spec.loader.exec_module(validator_module)

FilePlacementValidator = validator_module.FilePlacementValidator

# We need to load models for testing
try:
    models_spec.loader.exec_module(models_module)
    SiteProfile = models_module.SiteProfile
    OutputLayout = models_module.OutputLayout
except Exception as e:
    print(f"Warning: Could not load models module: {e}")
    print("Tests requiring SiteProfile will be skipped.")
    SiteProfile = None
    OutputLayout = None

def test_basic():
    """Test basic functionality."""
    validator = FilePlacementValidator()

    # Test 1: Correct language substitution
    print("\nTest 1: Correct language substitution (en -> de)")
    source = "/content/products/en/family/aspose-words.md"
    translation = "/content/products/de/family/aspose-words.md"
    context = {"source_lang": "en", "target_lang": "de"}

    result = validator.validate(source, translation, context)
    print(f"  Success: {result.success}")
    print(f"  Errors: {result.error_count}")
    print(f"  Warnings: {result.warning_count}")
    assert result.success is True, "Test 1 failed"
    assert result.error_count == 0, "Test 1 has errors"
    print("  ✓ PASSED")

    # Test 2: Incorrect language substitution (en -> en)
    print("\nTest 2: Incorrect language substitution (en -> en)")
    source = "/content/products/en/family/aspose-words.md"
    translation = "/content/products/en/family/aspose-words.md"
    context = {"source_lang": "en", "target_lang": "de"}

    result = validator.validate(source, translation, context)
    print(f"  Success: {result.success}")
    print(f"  Errors: {result.error_count}")
    print(f"  Warnings: {result.warning_count}")
    if result.issues:
        print("  Issues:")
        for issue in result.issues:
            print(f"    - [{issue.severity.value}] {issue.message}")
    assert result.success is False, "Test 2 should fail"
    assert result.error_count > 0, "Test 2 should have errors"
    print("  ✓ PASSED")

    # Test 3: Missing target language
    print("\nTest 3: Missing target language in context")
    source = "/content/products/en/family/aspose-words.md"
    translation = "/content/products/de/family/aspose-words.md"
    context = {"source_lang": "en"}

    result = validator.validate(source, translation, context)
    print(f"  Success: {result.success}")
    print(f"  Errors: {result.error_count}")
    assert result.success is False, "Test 3 should fail"
    print("  ✓ PASSED")

    # Test 4: With site profile
    print("\nTest 4: Validation with site profile (products)")
    profile = SiteProfile(
        site_id="products.aspose.net",
        content_roots=["/content/products"],
        default_source_lang="en",
        target_langs=["de", "es", "fr"],
        output_layout=OutputLayout(
            per_language_folders=True,
            pattern="{lang}/{path}"
        )
    )

    source = "/content/products/en/words/index.md"
    translation = "/content/products/de/words/index.md"
    context = {
        "source_lang": "en",
        "target_lang": "de",
        "site_id": "products.aspose.net",
        "site_profile": profile
    }

    result = validator.validate(source, translation, context)
    print(f"  Success: {result.success}")
    print(f"  Errors: {result.error_count}")
    print(f"  Warnings: {result.warning_count}")
    assert result.success is True, "Test 4 failed"
    assert result.error_count == 0, "Test 4 has errors"
    print("  ✓ PASSED")

    # Test 5: Wrong content root
    print("\nTest 5: Wrong content root")
    source = "/content/products/en/words/index.md"
    translation = "/wrong/path/de/words/index.md"
    context = {
        "source_lang": "en",
        "target_lang": "de",
        "site_id": "products.aspose.net",
        "site_profile": profile
    }

    result = validator.validate(source, translation, context)
    print(f"  Success: {result.success}")
    print(f"  Errors: {result.error_count}")
    if result.issues:
        print("  Issues:")
        for issue in result.issues:
            print(f"    - [{issue.severity.value}] {issue.message}")
    assert result.success is False, "Test 5 should fail"
    print("  ✓ PASSED")

    print("\n" + "="*60)
    print("All basic tests PASSED!")
    print("="*60)

if __name__ == "__main__":
    try:
        test_basic()
        print("\n✓ FilePlacementValidator implementation verified successfully!")
        sys.exit(0)
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
