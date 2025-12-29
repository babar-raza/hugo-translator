#!/usr/bin/env python3
"""
Test tokenizer state management to identify contamination source.

This tests if the tokenizer state is bleeding between translations.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def test_tokenizer_attributes():
    """Check what attributes M2M100Tokenizer actually has."""
    print("="*80)
    print("TEST 1: M2M100Tokenizer Attributes")
    print("="*80)

    try:
        from transformers import M2M100Tokenizer

        print("\n[1/2] Loading M2M100 tokenizer...")
        tokenizer = M2M100Tokenizer.from_pretrained("facebook/m2m100_418M")
        print("OK - Tokenizer loaded")

        print("\n[2/2] Checking attributes...")
        attrs_to_check = [
            'src_lang',
            'tgt_lang',
            'get_lang_id',
            'set_src_lang_special_tokens',
            'set_tgt_lang_special_tokens',
            'lang_code_to_id',
            'convert_tokens_to_ids'
        ]

        for attr in attrs_to_check:
            has_it = hasattr(tokenizer, attr)
            value = getattr(tokenizer, attr, None) if has_it else None

            if has_it and not callable(value):
                print(f"  {attr:35s}: {has_it:5s} (value: {value})")
            else:
                print(f"  {attr:35s}: {has_it:5s}")

        print("\n" + "="*80)
        print("FINDINGS")
        print("="*80)

        if hasattr(tokenizer, 'src_lang'):
            print(f"  OK Has src_lang: {tokenizer.src_lang}")
            print("    WARNING: If this persists across calls, it could cause contamination!")
        else:
            print("  ERROR No src_lang attribute")
            print("    This is expected for M2M100")

        if hasattr(tokenizer, 'tgt_lang'):
            print(f"  OK Has tgt_lang: {tokenizer.tgt_lang}")
            print("    WARNING: This should NOT be set for M2M100!")
        else:
            print("  ERROR No tgt_lang attribute")
            print("    This is correct for M2M100")

    except ImportError as e:
        print(f"\nERROR Error: {e}")
        print("  Install with: pip install transformers")
        return None
    except Exception as e:
        print(f"\nERROR Error: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_tokenizer_state_contamination():
    """Test if tokenizer state bleeds between translations."""
    print("\n\n" + "="*80)
    print("TEST 2: Tokenizer State Contamination")
    print("="*80)

    try:
        from transformers import M2M100ForConditionalGeneration, M2M100Tokenizer
        import torch

        print("\n[1/5] Loading model and tokenizer...")
        model = M2M100ForConditionalGeneration.from_pretrained("facebook/m2m100_418M")
        tokenizer = M2M100Tokenizer.from_pretrained("facebook/m2m100_418M")
        print("OK Loaded")

        test_text = "Test"

        # Test sequence: Greek -> German -> Greek
        # If state is contaminated, second Greek translation might be wrong
        langs = [('el', 'Greek'), ('de', 'German'), ('el', 'Greek again')]

        print(f"\n[2/5] Testing sequential translations: {test_text}")
        print("\nSequence: Greek -> German -> Greek")
        print("If state bleeds, the second Greek translation will be different!\n")

        results = []

        for lang_code, lang_name in langs:
            # Set src_lang (simulating our code)
            if hasattr(tokenizer, 'src_lang'):
                tokenizer.src_lang = "en"

            # Encode
            encoded = tokenizer(test_text, return_tensors="pt")

            # Get BOS token
            try:
                bos_id = tokenizer.get_lang_id(lang_code)
                print(f"[{lang_name:15s}] BOS token ID: {bos_id}")
            except KeyError:
                print(f"[{lang_name:15s}] ERROR KeyError getting BOS token!")
                continue

            # Generate
            with torch.no_grad():
                generated = model.generate(
                    **encoded,
                    forced_bos_token_id=bos_id,
                    max_length=50
                )

            # Decode
            translation = tokenizer.batch_decode(generated, skip_special_tokens=True)[0]
            results.append((lang_name, translation))

            print(f"[{lang_name:15s}] Translation: {translation}")

            # Check current tokenizer state after translation
            if hasattr(tokenizer, 'src_lang'):
                print(f"[{lang_name:15s}] State after: tokenizer.src_lang = {tokenizer.src_lang}")
            if hasattr(tokenizer, 'tgt_lang'):
                print(f"[{lang_name:15s}] State after: tokenizer.tgt_lang = {tokenizer.tgt_lang}")
            print()

        print("[3/5] Comparing Greek translations...")
        if len(results) >= 3:
            greek_1 = results[0][1]
            greek_2 = results[2][1]

            print(f"  First Greek:  {greek_1}")
            print(f"  Second Greek: {greek_2}")

            if greek_1 == greek_2:
                print("\n  OK Both Greek translations are IDENTICAL")
                print("    No state contamination detected")
            else:
                print("\n  ERROR Greek translations are DIFFERENT!")
                print("    STATE CONTAMINATION DETECTED!")
                print("    The German translation affected subsequent Greek translation")

        print("\n[4/5] Testing batch translation with mixed languages...")
        # This simulates what happens in batch translation
        batch_texts = ["Test", "Translation", "Article"]
        batch_langs = ['el', 'de', 'fr']  # Greek, German, French

        print("Translating batch with DIFFERENT target languages:")
        for text, lang in zip(batch_texts, batch_langs):
            bos_id = tokenizer.get_lang_id(lang)
            encoded = tokenizer(text, return_tensors="pt")

            with torch.no_grad():
                generated = model.generate(**encoded, forced_bos_token_id=bos_id, max_length=50)

            translation = tokenizer.batch_decode(generated, skip_special_tokens=True)[0]
            print(f"  {text:15s} -> {lang}: {translation}")

        print("\n[5/5] Testing if src_lang persists...")
        # Set src_lang to something weird
        if hasattr(tokenizer, 'src_lang'):
            tokenizer.src_lang = "cs"  # Czech
            print(f"  Set tokenizer.src_lang = 'cs' (Czech)")

            # Now try to translate to Greek
            encoded = tokenizer(test_text, return_tensors="pt")
            bos_id = tokenizer.get_lang_id('el')

            with torch.no_grad():
                generated = model.generate(**encoded, forced_bos_token_id=bos_id, max_length=50)

            translation = tokenizer.batch_decode(generated, skip_special_tokens=True)[0]
            print(f"  Translation to Greek: {translation}")
            print(f"  Current tokenizer.src_lang: {tokenizer.src_lang}")

            if 'Zkouška' in translation or tokenizer.src_lang == 'cs':
                print("\n  ERROR CONTAMINATION: src_lang is persisting!")
                print("    This could be causing the mixed-language output!")

    except ImportError as e:
        print(f"\nERROR Error: {e}")
        print("  Install with: pip install transformers torch")
        return None
    except Exception as e:
        print(f"\nERROR Error: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_batch_contamination():
    """Test if batch translation causes contamination."""
    print("\n\n" + "="*80)
    print("TEST 3: Batch Translation Contamination")
    print("="*80)

    try:
        from transformers import M2M100ForConditionalGeneration, M2M100Tokenizer
        import torch

        print("\n[1/3] Loading model...")
        model = M2M100ForConditionalGeneration.from_pretrained("facebook/m2m100_418M")
        tokenizer = M2M100Tokenizer.from_pretrained("facebook/m2m100_418M")

        # Test: Translate multiple texts in a single batch to Greek
        batch_texts = [
            "Test Translation Article",
            "This is a test article",
            "File detection by orchestrator"
        ]

        print(f"\n[2/3] Translating {len(batch_texts)} texts to Greek in a batch...")
        print("Source texts:")
        for i, text in enumerate(batch_texts, 1):
            print(f"  {i}. {text}")

        # Set source language
        tokenizer.src_lang = "en"

        # Encode batch
        encoded = tokenizer(batch_texts, return_tensors="pt", padding=True, truncation=True)

        # Get Greek BOS token
        bos_id = tokenizer.get_lang_id('el')
        print(f"\nGreek BOS token ID: {bos_id}")

        # Generate
        with torch.no_grad():
            generated = model.generate(
                **encoded,
                forced_bos_token_id=bos_id,
                max_new_tokens=50
            )

        # Decode
        translations = tokenizer.batch_decode(generated, skip_special_tokens=True)

        print(f"\n[3/3] Results:")
        contaminated = []
        for i, (src, tgt) in enumerate(zip(batch_texts, translations), 1):
            # Check for contamination
            has_czech = 'Zkouška' in tgt or 'zkouškou' in tgt
            has_german = 'Übersetzer' in tgt or 'funktioniert' in tgt
            has_catalan = 'Arxius' in tgt
            has_arabic = 'تخزين' in tgt or 'واسترداد' in tgt

            status = "OK CLEAN"
            if has_czech or has_german or has_catalan or has_arabic:
                status = "ERROR CONTAMINATED"
                contaminants = []
                if has_czech: contaminants.append('Czech')
                if has_german: contaminants.append('German')
                if has_catalan: contaminants.append('Catalan')
                if has_arabic: contaminants.append('Arabic')
                status += f" ({', '.join(contaminants)})"
                contaminated.append(i)

            print(f"\n  {i}. Source: {src}")
            print(f"     Target: {tgt}")
            print(f"     Status: {status}")

        if contaminated:
            print(f"\nERROR BATCH CONTAMINATION DETECTED in items: {contaminated}")
            print("\nThis reproduces the production issue!")
            print("The batch translation is producing mixed-language output.")
        else:
            print("\nOK No contamination in batch translation")
            print("Issue may be elsewhere in the system")

    except ImportError as e:
        print(f"\nERROR Error: {e}")
        print("  Install with: pip install transformers torch")
    except Exception as e:
        print(f"\nERROR Error: {e}")
        import traceback
        traceback.print_exc()


def main():
    """Run all tokenizer state tests."""
    print("\nTOKENIZER STATE CONTAMINATION DIAGNOSTIC\n")

    test_tokenizer_attributes()
    test_tokenizer_state_contamination()
    test_batch_contamination()

    print("\n\n" + "="*80)
    print("SUMMARY & RECOMMENDATIONS")
    print("="*80)
    print("\nIf you see:")
    print("  - 'STATE CONTAMINATION DETECTED' → tokenizer.src_lang is bleeding")
    print("  - 'BATCH CONTAMINATION DETECTED' → batch translation itself is broken")
    print("  - Both clean → issue is in the integration layer")
    print("\nNext steps will depend on which test fails.")


if __name__ == "__main__":
    main()
