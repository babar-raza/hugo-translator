#!/usr/bin/env python3
"""
Test if sequential translations to different languages cause contamination.
Simplified version that avoids printing non-ASCII characters.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

def has_contamination(text, expected_lang):
    """
    Check if text contains markers from wrong languages.
    Returns (is_contaminated, list of detected wrong languages)
    """
    contamination = []

    # Czech markers
    if 'Zkouska' in text or 'zkouskou' in text or 'Ceviri' in text:
        if expected_lang != 'cs':
            contamination.append('Czech')

    # German markers
    if 'Ubersetzer' in text or 'funktioniert' in text or 'Ubersetzung' in text:
        if expected_lang != 'de':
            contamination.append('German')

    # Turkish markers
    if 'Ceviri' in text or 'Yaratimi' in text or 'yariyor' in text:
        if expected_lang != 'tr':
            contamination.append('Turkish')

    return len(contamination) > 0, contamination


def test_sequential_translations():
    """Test if translating sequentially to different languages causes contamination."""
    print("="*80)
    print("SEQUENTIAL TRANSLATION CONTAMINATION TEST")
    print("="*80)

    from model_runtime.loader import ModelLoader
    from utils.config_loader import ConfigService

    config_root = Path("config").absolute()
    config = ConfigService(config_root)
    loader = ModelLoader(config)
    model = loader.load_model('m2m100_418m')

    print(f"\nModel: {model.model_info.model_id}")
    print("\nTest: Translate to Greek, then Turkish, then German with SAME model instance")
    print("If tokenizer state bleeds, we'll see contamination in later translations.\n")

    test_texts = [
        "Translation Job Creation",
        "Worker processing",
        "TM storage and retrieval"
    ]

    # Sequence of target languages
    lang_sequence = [('el', 'Greek'), ('tr', 'Turkish'), ('de', 'German')]

    contamination_detected = False

    for lang_code, lang_name in lang_sequence:
        print(f"[{lang_name}] Translating {len(test_texts)} texts to {lang_code}...")

        # Translate batch
        translations = model.translate(test_texts, 'en', lang_code)

        # Check each translation for contamination
        for i, (src, tgt) in enumerate(zip(test_texts, translations)):
            is_contaminated, contaminants = has_contamination(tgt, lang_code)

            if is_contaminated:
                print(f"  Text {i+1}: CONTAMINATED ({', '.join(contaminants)})")
                print(f"    Source: {src}")
                print(f"    Target has markers from: {contaminants}")
                contamination_detected = True
            else:
                print(f"  Text {i+1}: CLEAN")

        print()

    print("="*80)
    if contamination_detected:
        print("RESULT: CONTAMINATION DETECTED")
        print("\nSequential translations to different languages ARE producing contamination.")
        print("This confirms tokenizer state is bleeding between calls.")
    else:
        print("RESULT: NO CONTAMINATION")
        print("\nSequential translations appear clean.")
        print("Issue may be intermittent or triggered by other conditions.")
    print("="*80)

    return contamination_detected


def test_batch_after_language_switch():
    """Test if batch translation after switching languages causes contamination."""
    print("\n\n" + "="*80)
    print("BATCH AFTER LANGUAGE SWITCH TEST")
    print("="*80)

    from model_runtime.loader import ModelLoader
    from utils.config_loader import ConfigService

    config_root = Path("config").absolute()
    config = ConfigService(config_root)
    loader = ModelLoader(config)
    model = loader.load_model('m2m100_418m')

    print("\nTest: Translate to Greek first, then translate BATCH to Turkish")
    print("This simulates the production scenario.\n")

    test_texts = [
        "Test Translation Article",
        "This is a test article to verify the translation system works correctly",
        "Features for testing"
    ]

    # First: Translate to Greek (prime the tokenizer)
    print("[1] Priming tokenizer with Greek translation...")
    greek_batch = model.translate(test_texts, 'en', 'el')
    print(f"    Translated {len(greek_batch)} texts to Greek")

    # Second: Translate to Turkish (this is where contamination might occur)
    print("\n[2] Now translating BATCH to Turkish with same model instance...")
    print("    (After Greek - high contamination risk)")
    turkish_batch = model.translate(test_texts, 'en', 'tr')

    # Check for contamination
    contamination_detected = False
    for i, (src, tgt) in enumerate(zip(test_texts, turkish_batch)):
        is_contaminated, contaminants = has_contamination(tgt, 'tr')

        if is_contaminated:
            print(f"  Text {i+1}: CONTAMINATED ({', '.join(contaminants)})")
            print(f"    Source: {src}")
            contamination_detected = True
        else:
            print(f"  Text {i+1}: CLEAN")

    print("\n" + "="*80)
    if contamination_detected:
        print("RESULT: CONTAMINATION DETECTED")
        print("\nBatch translation after language switch IS contaminated.")
        print("ROOT CAUSE CONFIRMED: Tokenizer state bleeding between language switches.")
    else:
        print("RESULT: NO CONTAMINATION")
        print("\nBatch translation appears clean after language switch.")
    print("="*80)

    return contamination_detected


def main():
    """Run all tests."""
    print("\nTOKENIZER STATE CONTAMINATION DIAGNOSTICS\n")

    try:
        # Test 1: Sequential translations to different languages
        test1_failed = test_sequential_translations()

        # Test 2: Batch after language switch
        test2_failed = test_batch_after_language_switch()

        # Summary
        print("\n\n" + "="*80)
        print("FINAL DIAGNOSIS")
        print("="*80)

        if test1_failed or test2_failed:
            print("\nCONTAMINATION REPRODUCED")
            print("\nThe tokenizer state is NOT properly isolated between translations")
            print("to different target languages.")
            print("\nThis explains the intermittent corruption in production:")
            print("  - When translating to multiple languages sequentially,")
            print("  - Previous language state bleeds into next translation")
            print("  - Batch translations are more susceptible than individual")
            return 1
        else:
            print("\nNO CONTAMINATION DETECTED")
            print("\nThe issue may be:")
            print("  - Intermittent (run test multiple times)")
            print("  - Triggered by specific text patterns")
            print("  - In a different part of the pipeline")
            return 0

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
