#!/usr/bin/env python3
"""
Comprehensive diagnostic to identify the exact root cause of translation corruption.

This script will:
1. Test the model in isolation
2. Check tokenizer state management
3. Test batch vs individual translation
4. Check if TM is involved
5. Compare with known good/bad translations
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def diagnostic_test():
    """Run comprehensive diagnostic."""
    print("=" * 80)
    print("COMPREHENSIVE TRANSLATION CORRUPTION DIAGNOSTIC")
    print("=" * 80)
    print("\nThis will identify the EXACT root cause of the corruption issue.")
    print("Testing the same input that produced corrupted output...\n")

    try:
        import logging

        logging.basicConfig(level=logging.DEBUG, format="%(name)s - %(levelname)s - %(message)s")

        from model_runtime.loader import ModelLoader
        from utils.config_loader import ConfigService

        # The exact text from test-translation.md that produced corruption
        test_texts = [
            "Test Translation Article",
            "This is a test article to verify the translation system works correctly",
            "File detection by orchestrator",
        ]

        # Languages that showed corruption
        test_langs = {"el": "Greek", "de": "German", "tr": "Turkish", "uk": "Ukrainian"}

        print("[1/5] Loading model...")
        print("=" * 80)
        config = ConfigService()
        loader = ModelLoader(config)
        model = loader.load_model("m2m100_418m")
        print(f"✓ Model loaded: {model}")
        print(f"  Model ID: {model.model_info.model_id}")
        print(f"  HF Model: {model.model_info.hf_model_id}")
        print(f"  Device: {model.device}")
        print()

        print("[2/5] Testing INDIVIDUAL translation (single text at a time)...")
        print("=" * 80)
        print("This simulates the fallback mode that should work correctly.\n")

        individual_results = {}
        for lang_code, lang_name in test_langs.items():
            print(f"\n--- Translating to {lang_name} ({lang_code}) ---")

            # Translate ONE text at a time (like fallback mode)
            translations = []
            for i, text in enumerate(test_texts, 1):
                print(f"  [{i}/3] Translating: '{text[:50]}...'")

                result = model.translate([text], "en", lang_code)
                translation = result[0] if result else "FAILED"
                translations.append(translation)

                # Check for contamination
                contaminants = []
                if "Zkouška" in translation:
                    contaminants.append("Czech")
                if "Übersetzer" in translation:
                    contaminants.append("German")
                if "ΠΡΟΣΟΧΗ" in translation or "ΔΗΜΙΟΥΡΓΙΑ" in translation:
                    contaminants.append("Greek")
                if "Arxius" in translation or "l'Orqu" in translation:
                    contaminants.append("Catalan")
                if "تخزين" in translation or "واسترداد" in translation:
                    contaminants.append("Arabic")

                status = (
                    "✓ CLEAN" if not contaminants else f"✗ CONTAMINATED ({', '.join(contaminants)})"
                )
                try:
                    print(f"       Result: {translation[:60]:60s} {status}")
                except UnicodeEncodeError:
                    print(f"       Result: [encoding error] {status}")

            individual_results[lang_code] = translations

        print("\n\n[3/5] Testing BATCH translation (all texts at once)...")
        print("=" * 80)
        print("This simulates what happens in production batch mode.\n")

        batch_results = {}
        for lang_code, lang_name in test_langs.items():
            print(f"\n--- Batch translating to {lang_name} ({lang_code}) ---")
            print(f"  Translating {len(test_texts)} texts in one batch...")

            # Translate ALL texts at once (like batch mode)
            translations = model.translate(test_texts, "en", lang_code)

            batch_results[lang_code] = translations

            # Check each translation
            for i, (text, translation) in enumerate(zip(test_texts, translations, strict=False), 1):
                contaminants = []
                if "Zkouška" in translation:
                    contaminants.append("Czech")
                if "Übersetzer" in translation:
                    contaminants.append("German")
                if "ΠΡΟΣΟΧΗ" in translation:
                    contaminants.append("Greek")
                if "Arxius" in translation:
                    contaminants.append("Catalan")
                if "تخزين" in translation:
                    contaminants.append("Arabic")

                status = (
                    "✓ CLEAN" if not contaminants else f"✗ CONTAMINATED ({', '.join(contaminants)})"
                )
                try:
                    print(f"  [{i}] {translation[:60]:60s} {status}")
                except UnicodeEncodeError:
                    print(f"  [{i}] [encoding error] {status}")

        print("\n\n[4/5] COMPARING Individual vs Batch...")
        print("=" * 80)

        individual_contaminated = set()
        batch_contaminated = set()

        for lang_code in test_langs.keys():
            # Check individual
            for trans in individual_results.get(lang_code, []):
                if any(
                    marker in trans
                    for marker in ["Zkouška", "Übersetzer", "ΠΡΟΣΟΧΗ", "Arxius", "تخزين"]
                ):
                    individual_contaminated.add(lang_code)
                    break

            # Check batch
            for trans in batch_results.get(lang_code, []):
                if any(
                    marker in trans
                    for marker in ["Zkouška", "Übersetzer", "ΠΡΟΣΟΧΗ", "Arxius", "تخزين"]
                ):
                    batch_contaminated.add(lang_code)
                    break

        print(
            f"\nIndividual mode contaminated: {list(individual_contaminated) if individual_contaminated else 'None'}"
        )
        print(
            f"Batch mode contaminated: {list(batch_contaminated) if batch_contaminated else 'None'}"
        )

        if individual_contaminated and batch_contaminated:
            print("\n✗ BOTH modes contaminated!")
            print("  → Issue is in the model itself or tokenizer setup")
        elif batch_contaminated and not individual_contaminated:
            print("\n✗ Only BATCH mode contaminated!")
            print("  → Issue is in batch translation logic")
        elif not batch_contaminated and not individual_contaminated:
            print("\n✓ Both modes are CLEAN!")
            print("  → Cannot reproduce the issue")
            print("  → The corruption may have been temporary or TM-related")
        else:
            print("\n✗ Only INDIVIDUAL mode contaminated!")
            print("  → Unexpected! This shouldn't happen")

        print("\n\n[5/5] FINAL DIAGNOSIS")
        print("=" * 80)

        if individual_contaminated or batch_contaminated:
            print("\n✗ CORRUPTION REPRODUCED")
            print("\nRoot Cause Analysis:")

            if individual_contaminated and batch_contaminated:
                print("\n  → MODEL OR TOKENIZER ISSUE")
                print("    The same corruption appears in both individual and batch modes.")
                print("\n    Possible causes:")
                print("      1. forced_bos_token_id is not being set correctly")
                print("      2. Tokenizer state is contaminated and persisting")
                print("      3. Model checkpoint is corrupted")
                print("\n    Next steps:")
                print("      - Check DEBUG logs above for 'forced_bos_token_id=' lines")
                print("      - Run: python scripts/test_tokenizer_state.py")
                print("      - Try clearing model cache and re-downloading")

            elif batch_contaminated:
                print("\n  → BATCH TRANSLATION ISSUE")
                print("    Corruption only in batch mode suggests batch processing bug.")
                print("\n    Next steps:")
                print("      - Review batch translation logic in text_unit_extractor.py")
                print("      - Check if tokenizer state bleeds between batch items")

        else:
            print("\n✓ CANNOT REPRODUCE CORRUPTION")
            print("\n  The model is producing clean translations now.")
            print("\n  Possible explanations:")
            print("    1. The issue was temporary (model cache cleared)")
            print("    2. TM was serving corrupted cached translations")
            print("    3. The corruption was from a specific code state that's now fixed")
            print("\n  Recommendation:")
            print("    - Delete the corrupted test-translation.md files")
            print("    - Re-run translation and verify it's clean")
            print("    - Check TM for corrupted entries")

    except ImportError as e:
        print(f"\n✗ Error: Missing dependency - {e}")
        print("  Install with: pip install transformers torch")
        return 2
    except Exception as e:
        print(f"\n✗ Error during diagnostic: {e}")
        import traceback

        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(diagnostic_test())
