"""Quick test script for FilePlacementValidator."""

import sys
import importlib.util
from pathlib import Path

# Add repo root to path for 'src.*' imports
REPO_ROOT = Path(__file__).parent.parent.parent
SRC_ROOT = REPO_ROOT / "src"
sys.path.insert(0, str(REPO_ROOT))

# Load modules directly to avoid package __init__.py issues
def load_module_from_path(module_name: str, file_path: Path):
    """Load a Python module from file path and register in sys.modules."""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module

# Load base module first and register as the relative import target
base_module = load_module_from_path(
    "src.translation_engine.validation.base",
    SRC_ROOT / "translation_engine" / "validation" / "base.py"
)

# Load models module
models_module = load_module_from_path(
    "src.utils.models",
    SRC_ROOT / "utils" / "models.py"
)

# Load config_loader (needed by file_placement_validator)
config_loader_module = load_module_from_path(
    "src.utils.config_loader",
    SRC_ROOT / "utils" / "config_loader.py"
)

# Now load the validator (it will find dependencies in sys.modules)
validator_module = load_module_from_path(
    "src.translation_engine.validation.file_placement_validator",
    SRC_ROOT / "translation_engine" / "validation" / "file_placement_validator.py"
)

# Extract the classes we need
FilePlacementValidator = validator_module.FilePlacementValidator
SiteProfile = models_module.SiteProfile
OutputLayout = models_module.OutputLayout
BodyRules = models_module.BodyRules

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
        body=BodyRules(
            translate_markdown=True
        ),
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
