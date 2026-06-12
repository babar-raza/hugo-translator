#!/usr/bin/env python3
"""
Minimal reproduction script for the translation corruption issue.

This script simulates what the translation system does and helps pinpoint
where the corruption is happening.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def test_direct_translation():
    """Test translation using the actual model loader."""
    print("=" * 80)
    print("REPRODUCTION TEST: Using ModelLoader (same as production)")
    print("=" * 80)

    try:
        from model_runtime.loader import ModelLoader
        from utils.config_loader import ConfigService

        print("\n[1/4] Loading model...")
        config = ConfigService()
        loader = ModelLoader(config)
        model = loader.load_model("m2m100_418m")
        print("✓ Model loaded")

        test_text = "Test Translation Article"
        print(f"\n[2/4] Test input: '{test_text}'")

        # Test multiple languages
        test_langs = ["el", "de", "fr", "es", "tr", "uk"]
        lang_names = {
            "el": "Greek",
            "de": "German",
            "fr": "French",
            "es": "Spanish",
            "tr": "Turkish",
            "uk": "Ukrainian",
        }

        print("\n[3/4] Translating to multiple languages...")
        results = {}
        corrupted = []

        for lang_code in test_langs:
            result = model.translate([test_text], "en", lang_code)
            translation = result[0] if result else "FAILED"
            results[lang_code] = translation

            # Check for contamination markers
            contaminants = []
            if "Zkouška" in translation:
                contaminants.append("Czech")
            if "Übersetzer" in translation:
                contaminants.append("German")
            if "ΠΡΟΣΟΧΗ" in translation:
                contaminants.append("Greek")
            if "Arxius" in translation or "l'Orqu" in translation:
                contaminants.append("Catalan")
            if "تخزين" in translation or "واسترداد" in translation:
                contaminants.append("Arabic")

            status = (
                "✓ CLEAN" if not contaminants else f"✗ CONTAMINATED ({', '.join(contaminants)})"
            )

            # Try to display with proper encoding
            try:
                print(f"  {lang_names[lang_code]:10s} ({lang_code}): {translation:50s} {status}")
            except UnicodeEncodeError:
                print(f"  {lang_names[lang_code]:10s} ({lang_code}): [Unicode Error] {status}")

            if contaminants:
                corrupted.append(lang_names[lang_code])

        print("\n[4/4] Diagnosis")
        if corrupted:
            print(f"  ✗ CORRUPTION CONFIRMED in: {', '.join(corrupted)}")
            print("\n  This confirms the issue is in the translation system.")
            print("  Possible causes:")
            print("    1. Model checkpoint is corrupted")
            print("    2. forced_bos_token_id is not being set correctly")
            print("    3. Model/tokenizer state contamination")
            print("\n  Next step: Enable DEBUG logging to see forced_bos_token_id values")
            return False
        else:
            print("  ✓ All translations CLEAN")
            print("\n  Model is working correctly.")
            print("  Issue may be in a different part of the system.")
            return True

    except Exception as e:
        print(f"\n✗ Error during test: {e}")
        import traceback

        traceback.print_exc()
        return None


def test_with_debug_logging():
    """Test with DEBUG logging enabled to see BOS token values."""
    print("\n\n" + "=" * 80)
    print("DEBUG TEST: Enable logging to see forced_bos_token_id")
    print("=" * 80)

    import logging

    # Enable DEBUG logging for model_runtime
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger("src.model_runtime.loader")
    logger.setLevel(logging.DEBUG)

    try:
        from model_runtime.loader import ModelLoader
        from utils.config_loader import ConfigService

        print("\n[1/3] Loading model with DEBUG logging...")
        config = ConfigService()
        loader = ModelLoader(config)
        model = loader.load_model("m2m100_418m")

        test_text = "Test"
        test_lang = "el"  # Greek

        print(
            f"\n[2/3] Translating '{test_text}' to {test_lang} (watch for forced_bos_token_id in logs)..."
        )
        print("-" * 80)

        result = model.translate([test_text], "en", test_lang)

        print("-" * 80)
        print(f"\n[3/3] Result: {result[0] if result else 'FAILED'}")

        # Check if Zkouška appears
        if result and "Zkouška" in result[0]:
            print("\n  ✗ CONTAMINATED with Czech!")
            print("  Check the forced_bos_token_id value in the logs above.")
            print("  If it's not showing, that's the problem!")
        elif result:
            print("\n  ✓ Translation looks clean")

    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback

        traceback.print_exc()


def main():
    """Run reproduction tests."""
    print("\nMINIMAL REPRODUCTION TEST FOR TRANSLATION CORRUPTION")
    print("This will test if the corruption can be reproduced with ModelLoader\n")

    # Test 1: Basic reproduction
    result = test_direct_translation()

    if result is False:
        # Test 2: With debug logging
        test_with_debug_logging()

        print("\n\n" + "=" * 80)
        print("NEXT STEPS")
        print("=" * 80)
        print("\n1. Check the DEBUG logs above for 'forced_bos_token_id='")
        print("2. If it's None or wrong, that's the root cause")
        print("3. If it's correct, the model checkpoint may be corrupted")
        print("\n4. To fix:")
        print("   Option A: Re-download model")
        print("     rm -rf ~/.cache/huggingface/hub/models--facebook--m2m100_418M")
        print("     python scripts/reproduce_corruption.py")
        print("\n   Option B: Try NLLB-200 model instead")
        print("     Edit config/global.yaml: fallback_model: 'nllb200_600m'")


if __name__ == "__main__":
    main()
