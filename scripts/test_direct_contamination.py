#!/usr/bin/env python3
"""
Test contamination using production code path (TextUnitExtractor).
This replicates exactly what production does.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

def test_production_contamination():
    """Test using the exact production flow."""
    print("="*80)
    print("PRODUCTION CODE PATH CONTAMINATION TEST")
    print("="*80)

    from model_runtime.registry import ModelRegistry
    from model_runtime.loader import ModelLoader
    from translation_engine.extractor.text_unit_extractor import TextUnitExtractor
    from translation_engine.extractor.schemas import TextUnit

    # Set up model like production does
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

    print(f"\nModel loaded: {model.model_info.model_id}")
    print(f"Device: cpu")

    # Create text units like production
    test_texts = [
        "Test Translation Article",
        "This is a test article to verify the translation system works correctly",
        "Features for testing",
        "Translation Job Creation",
        "Worker processing"
    ]

    units = [
        TextUnit(source_text=text, translated_text="", metadata={})
        for text in test_texts
    ]

    # Create extractor (production uses this)
    extractor = TextUnitExtractor()

    # Test sequence: Translate to Greek, then Turkish, then German
    # This simulates the production for loop over target languages
    lang_sequence = [('el', 'Greek'), ('tr', 'Turkish'), ('de', 'German'), ('uk', 'Ukrainian')]

    print(f"\nTranslating {len(units)} text units to {len(lang_sequence)} languages sequentially...")
    print("This replicates the production for loop over target_langs.\n")

    contamination_found = False

    for lang_code, lang_name in lang_sequence:
        print(f"[{lang_name}] Translating to {lang_code}...")

        # Reset units
        for unit in units:
            unit.translated_text = ""

        # Translate using extractor (EXACT production code path)
        translated_units = extractor.batch_translate(
            units=units,
            mt_model=model,
            src_lang='en',
            tgt_lang=lang_code
        )

        # Check for wrong language markers
        contaminated_count = 0
        for i, unit in enumerate(translated_units, 1):
            translation = unit.translated_text

            # Check for contamination markers
            wrong_markers = []

            # Czech markers
            if 'Zkouska' in translation or 'zkouskou' in translation:
                wrong_markers.append('Czech')

            # German markers (but not in German output)
            if lang_code != 'de' and ('Ubersetzer' in translation or 'funktioniert' in translation or 'Ubersetzung' in translation):
                wrong_markers.append('German')

            # Greek markers (but not in Greek output)
            if lang_code != 'el' and any(ord(c) >= 0x0370 and ord(c) <= 0x03FF for c in translation):
                wrong_markers.append('Greek')

            # Turkish markers (but not in Turkish output)
            if lang_code != 'tr' and ('Ceviri' in translation or 'Yaratimi' in translation):
                wrong_markers.append('Turkish')

            # Catalan markers
            if 'Arxius' in translation:
                wrong_markers.append('Catalan')

            if wrong_markers:
                contaminated_count += 1
                contamination_found = True
                print(f"  Text {i}: CONTAMINATED ({', '.join(wrong_markers)})")
                print(f"    Source: {test_texts[i-1]}")
                # Save to file for inspection
                with open('contamination_detected.txt', 'a', encoding='utf-8') as f:
                    f.write(f"{lang_name} [Text {i}]: {translation}\n")
                    f.write(f"  Source: {test_texts[i-1]}\n")
                    f.write(f"  Markers: {', '.join(wrong_markers)}\n\n")

        if contaminated_count == 0:
            print(f"  All {len(units)} texts: CLEAN")
        else:
            print(f"  {contaminated_count}/{len(units)} texts contaminated")

        print()

    print("="*80)
    if contamination_found:
        print("CONTAMINATION DETECTED")
        print("\nProduction code path IS producing mixed-language output.")
        print("Contaminated translations saved to: contamination_detected.txt")
        print("\nROOT CAUSE CONFIRMED:")
        print("  Sequential translations to different languages contaminate each other")
        print("  when using the SAME model instance.")
    else:
        print("NO CONTAMINATION")
        print("\nAll translations clean across all languages.")
        print("Issue may be intermittent - run test multiple times.")
    print("="*80)

    return 0 if not contamination_found else 1


if __name__ == "__main__":
    try:
        # Clear previous contamination log
        contamination_file = Path('contamination_detected.txt')
        if contamination_file.exists():
            contamination_file.unlink()

        sys.exit(test_production_contamination())

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
