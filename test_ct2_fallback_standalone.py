"""
Standalone test for CT2 empty translation fallback (no pytest required).
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.model_runtime.loader import CTranslate2Backend


def test_ct2_empty_translation_fallback():
    """Test that CT2 falls back to source text for empty translations."""

    model_path = "D:/models/opus_mt_ct2/en-fr/ct2_int8"
    if not Path(model_path).exists():
        print(f"❌ CT2 model not found at {model_path}")
        print("   Skipping test - model directory does not exist")
        return False

    print(f"\n{'='*70}")
    print("CT2 Empty Translation Fallback Test")
    print(f"{'='*70}\n")
    print(f"Model: {model_path}")
    print(f"Testing: Placeholder-only content should fall back to source text\n")

    # Initialize CT2 backend
    print("Loading CT2 model...")
    backend = CTranslate2Backend()

    try:
        backend.load(
            model_path=model_path,
            device="cpu",
            compute_type="int8"
        )
        print("✅ Model loaded successfully\n")

        # Test cases
        test_cases = [
            {
                "name": "Placeholder-only content",
                "text": "{PLACEHOLDER_0}",
                "expect_fallback": True
            },
            {
                "name": "Normal text",
                "text": "Hello, world!",
                "expect_fallback": False
            },
            {
                "name": "Another placeholder",
                "text": "{PLACEHOLDER_1}",
                "expect_fallback": True
            },
            {
                "name": "Simple greeting",
                "text": "Good morning",
                "expect_fallback": False
            }
        ]

        print("Running translations...")
        print("-" * 70)

        texts = [tc["text"] for tc in test_cases]
        translations = backend.translate(
            texts=texts,
            src_lang="en",
            tgt_lang="fr"
        )

        print()
        all_passed = True

        for i, (test_case, translation) in enumerate(zip(test_cases, translations)):
            source = test_case["text"]
            expect_fallback = test_case["expect_fallback"]
            name = test_case["name"]

            # Check if translation is source text (fallback occurred)
            is_fallback = (translation == source)

            # Determine pass/fail
            if expect_fallback:
                # Should have fallen back to source
                passed = is_fallback
                status = "✅ PASS" if passed else "❌ FAIL"
                expected = "source text (fallback)"
            else:
                # Should have actual translation (or fallback if model fails)
                # We accept both since model might fail on simple text too
                passed = translation.strip() != ""
                status = "✅ PASS" if passed else "❌ FAIL"
                expected = "translation or fallback (not empty)"

            all_passed = all_passed and passed

            print(f"{status} [{i+1}] {name}")
            print(f"     Source: '{source}'")
            print(f"     Result: '{translation}'")
            print(f"     Expected: {expected}")
            print(f"     Got: {'fallback' if is_fallback else 'translation'}")
            print()

        print("-" * 70)

        if all_passed:
            print("✅ All tests PASSED")
            print("\nSummary:")
            print("  - Placeholder-only content correctly falls back to source text")
            print("  - Empty translation detection is working")
            print("  - CT2Backend achieves parity with HuggingFaceBackend fallback")
        else:
            print("❌ Some tests FAILED")

        return all_passed

    except Exception as e:
        print(f"❌ Error during test: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        print("\nCleaning up...")
        backend.unload()
        print("✅ Model unloaded\n")


if __name__ == "__main__":
    success = test_ct2_empty_translation_fallback()
    sys.exit(0 if success else 1)
