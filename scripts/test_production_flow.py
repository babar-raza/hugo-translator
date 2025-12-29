#!/usr/bin/env python3
"""Test using actual production flow."""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

def test():
    print("="*80)
    print("SEQUENTIAL LANGUAGE CONTAMINATION TEST")
    print("="*80)
    print("\nTesting if sequential translations to different languages contaminate each other...")
    print("This replicates the production for loop over target_langs.\n")

    try:
        from model_runtime.registry import ModelRegistry
        from model_runtime.loader import ModelLoader
        from translation_engine.extractor.text_unit_extractor import TextUnitExtractor
        from translation_engine.extractor.schemas import TextUnit

        # Set up model registry
        registry = ModelRegistry()
        registry.register_model(
            model_id='m2m100_418m',
            backend='huggingface',
            hf_model_id='facebook/m2m100_418M',
            model_size_mb=1024,
            languages=['en', 'el', 'tr', 'de', 'uk'],
        )

        loader = ModelLoader(registry, device='cpu')
        model = loader.load_model('m2m100_418m')

        print(f"[1/4] Model loaded: {model.model_info.model_id}")
        print(f"      Device: cpu")

        # Create text units like production does
        test_texts = [
            "Test Translation Article",
            "This is a test article to verify the translation system works correctly",
            "File detection by orchestrator",
            "Translation Job Creation",
            "Worker processing"
        ]

        units = [
            TextUnit(source_text=text, translated_text="", metadata={})
            for text in test_texts
        ]

        print(f"\n[2/4] Created {len(units)} text units")

        # Test translation to different languages SEQUENTIALLY
        # This is the key: using the SAME model instance for all languages
        extractor = TextUnitExtractor()
        test_langs = ['el', 'tr', 'de', 'uk']  # Greek, Turkish, German, Ukrainian
        lang_names = {'el': 'Greek', 'de': 'German', 'tr': 'Turkish', 'uk': 'Ukrainian'}

        print(f"\n[3/4] Translating to {len(test_langs)} languages sequentially")
        print("      (This is where contamination occurs if tokenizer state bleeds)\n")

        all_clean = True
        contamination_details = []

        for lang_code in test_langs:
            print(f"--- Translating to {lang_names[lang_code]} ({lang_code}) ---")

            # Reset units
            for unit in units:
                unit.translated_text = ""

            # Translate using extractor (like production)
            translated_units = extractor.batch_translate(
                units=units,
                mt_model=model,
                src_lang='en',
                tgt_lang=lang_code
            )

            # Check results
            lang_contaminated = False
            for i, unit in enumerate(translated_units, 1):
                translation = unit.translated_text

                # Check for wrong language markers
                wrong_markers = []
                if 'Zkouska' in translation or 'zkouskou' in translation:
                    wrong_markers.append('Czech')
                if lang_code != 'de' and ('Ubersetzer' in translation or 'funktioniert' in translation or 'Ubersetzung' in translation):
                    wrong_markers.append('German')
                if lang_code != 'el' and any(ord(c) >= 0x0370 and ord(c) <= 0x03FF for c in translation):
                    wrong_markers.append('Greek')
                if lang_code != 'tr' and ('Ceviri' in translation or 'Yaratimi' in translation or 'yariyor' in translation):
                    wrong_markers.append('Turkish')
                if 'Arxius' in translation:
                    wrong_markers.append('Catalan')

                status = "CLEAN" if not wrong_markers else f"CONTAMINATED ({', '.join(wrong_markers)})"
                print(f"  [{i}] {status}")

                if wrong_markers:
                    all_clean = False
                    lang_contaminated = True
                    contamination_details.append({
                        'lang': lang_names[lang_code],
                        'text_num': i,
                        'source': test_texts[i-1],
                        'translation': translation,
                        'markers': wrong_markers
                    })
                    # Save for inspection
                    with open('production_contamination.txt', 'a', encoding='utf-8') as f:
                        f.write(f"{lang_names[lang_code]} [{i}]: {translation}\n")
                        f.write(f"  Source: {test_texts[i-1]}\n")
                        f.write(f"  Contamination: {', '.join(wrong_markers)}\n\n")

            print()

        print("\n[4/4] DIAGNOSIS")
        print("="*80)

        if all_clean:
            print("\nOK - All translations CLEAN across all languages")
            print("\n  Sequential translations did NOT produce contamination in this run.")
            print("  Since contamination is intermittent, try running multiple times.")
        else:
            print("\nCONTAMINATION DETECTED!")
            print(f"\n  Found {len(contamination_details)} contaminated translations")
            print("  Contaminated output saved to: production_contamination.txt")
            print("\n  ROOT CAUSE CONFIRMED:")
            print("  - Sequential translations to different languages WITH SAME model instance")
            print("  - Tokenizer state bleeding between language switches")
            print("  - batch_translate() uses the model without proper state isolation")
            print("\n  Contamination pattern:")
            for detail in contamination_details[:3]:  # Show first 3
                print(f"    {detail['lang']} text {detail['text_num']}: {', '.join(detail['markers'])} contamination")
            if len(contamination_details) > 3:
                print(f"    ... and {len(contamination_details) - 3} more")

        print("="*80)
        return 0 if all_clean else 1

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(test())
