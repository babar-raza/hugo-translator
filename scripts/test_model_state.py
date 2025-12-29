#!/usr/bin/env python3
"""
Test model/tokenizer state bleeding between sequential translations.
Direct test without the full extraction pipeline.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

def test_sequential_model_state():
    """Test if model state bleeds when translating to different languages sequentially."""
    print("="*80)
    print("MODEL STATE BLEEDING TEST")
    print("="*80)
    print("\nDirect model test: Sequential translations to different target languages\n")

    from model_runtime.registry import ModelRegistry
    from model_runtime.loader import ModelLoader

    # Set up model using existing registry
    registry_path = Path("config/model_registry.yaml").absolute()
    registry = ModelRegistry(registry_path)

    loader = ModelLoader(registry, device='cpu')
    model = loader.load_model('m2m100_418m')

    print(f"Model loaded: {model.model_info.model_id}")
    print(f"Device: cpu\n")

    # Test texts
    test_texts = [
        "Test Translation Article",
        "This is a test article to verify the translation system works correctly",
        "Features for testing",
        "Translation Job Creation",
        "Worker processing"
    ]

    print(f"Testing {len(test_texts)} texts")
    print(f"Translating to 4 languages sequentially with SAME model instance\n")

    # Sequential translation to different languages (this is the key!)
    lang_sequence = [('el', 'Greek'), ('tr', 'Turkish'), ('de', 'German'), ('uk', 'Ukrainian')]

    contamination_found = False

    for lang_code, lang_name in lang_sequence:
        print(f"[{lang_name}] Translating to {lang_code}...")

        # Translate batch
        translations = model.translate(test_texts, 'en', lang_code)

        # Check for contamination
        for i, (src, tgt) in enumerate(zip(test_texts, translations), 1):
            # Check for wrong language markers
            wrong_markers = []

            # Czech markers
            if 'Zkouska' in tgt or 'zkouskou' in tgt:
                wrong_markers.append('Czech')

            # German markers (but not in German output)
            if lang_code != 'de':
                if 'Ubersetzer' in tgt or 'funktioniert' in tgt or 'Ubersetzung' in tgt:
                    wrong_markers.append('German')

            # Greek markers (but not in Greek output)
            if lang_code != 'el':
                if any(ord(c) >= 0x0370 and ord(c) <= 0x03FF for c in tgt):
                    wrong_markers.append('Greek')

            # Turkish markers (but not in Turkish output)
            if lang_code != 'tr':
                if 'Ceviri' in tgt or 'Yaratimi' in tgt or 'yariyor' in tgt:
                    wrong_markers.append('Turkish')

            # Catalan markers
            if 'Arxius' in tgt:
                wrong_markers.append('Catalan')

            if wrong_markers:
                print(f"  Text {i}: CONTAMINATED ({', '.join(wrong_markers)})")
                print(f"    Source: {src[:50]}...")
                contamination_found = True

                # Save to file
                with open('model_state_contamination.txt', 'a', encoding='utf-8') as f:
                    f.write(f"{lang_name} [Text {i}]:\n")
                    f.write(f"  Source: {src}\n")
                    f.write(f"  Translation: {tgt}\n")
                    f.write(f"  Contamination: {', '.join(wrong_markers)}\n\n")
            else:
                print(f"  Text {i}: CLEAN")

        print()

    print("="*80)
    if contamination_found:
        print("CONTAMINATION DETECTED")
        print("\nSequential translations with SAME model instance ARE contaminated.")
        print("Details saved to: model_state_contamination.txt")
        print("\nROOT CAUSE CONFIRMED:")
        print("  Model/tokenizer state bleeding between target language switches")
    else:
        print("NO CONTAMINATION")
        print("\nAll translations clean across all sequential language switches.")
        print("Contamination may be intermittent - try running multiple times.")
    print("="*80)

    return 0 if not contamination_found else 1


if __name__ == "__main__":
    try:
        # Clear previous log
        log_file = Path('model_state_contamination.txt')
        if log_file.exists():
            log_file.unlink()

        sys.exit(test_sequential_model_state())

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
