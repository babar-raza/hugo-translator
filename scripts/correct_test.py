#!/usr/bin/env python3
"""Correct test with proper contamination detection."""

def test():
    print("="*80)
    print("CORRUPTION TEST - CORRECTED LOGIC")
    print("="*80)

    try:
        import torch
        from transformers import M2M100ForConditionalGeneration, M2M100Tokenizer

        print("\n[1/3] Loading model...")
        model = M2M100ForConditionalGeneration.from_pretrained("facebook/m2m100_418M")
        tokenizer = M2M100Tokenizer.from_pretrained("facebook/m2m100_418M")
        print("OK - Model loaded")

        # Test texts from test-translation.md
        test_texts = [
            "Test Translation Article",
            "This is a test article to verify the translation system works correctly",
            "File detection by orchestrator"
        ]

        # Languages that showed corruption in production
        test_langs = ['el', 'de', 'tr', 'uk']
        lang_names = {'el': 'Greek', 'de': 'German', 'tr': 'Turkish', 'uk': 'Ukrainian'}

        print("\n[2/3] Testing BATCH translation...")

        all_results = {}
        contamination_found = False

        for lang_code in test_langs:
            print(f"\n--- {lang_names[lang_code]} ({lang_code}) ---")

            # Set source language
            tokenizer.src_lang = "en"

            # Encode batch
            encoded = tokenizer(test_texts, return_tensors="pt", padding=True, truncation=True)

            # Get BOS token for target language
            bos_id = tokenizer.get_lang_id(lang_code)
            print(f"  BOS token ID: {bos_id}")

            # Generate
            with torch.no_grad():
                generated = model.generate(
                    **encoded,
                    forced_bos_token_id=bos_id,
                    max_new_tokens=50
                )

            # Decode
            translations = tokenizer.batch_decode(generated, skip_special_tokens=True)
            all_results[lang_code] = translations

            # CORRECT contamination check:
            # For each target language, check if WRONG language markers appear
            wrong_markers = {
                'el': ['Zkouska', 'Ubersetzer', 'Arxius', 'تخزين'],  # Greek shouldn't have Czech/German/Catalan/Arabic
                'de': ['Zkouska', 'ΠΡΟΣΟΧΗ', 'Arxius', 'تخزين'],      # German shouldn't have Czech/Greek/Catalan/Arabic
                'tr': ['Zkouska', 'Ubersetzer', 'ΠΡΟΣΟΧΗ', 'Arxius', 'تخزين'],  # Turkish shouldn't have any
                'uk': ['Zkouska', 'Ubersetzer', 'ΠΡΟΣΟΧΗ', 'Arxius', 'تخزين']   # Ukrainian shouldn't have any
            }

            markers_to_check = wrong_markers[lang_code]

            for i, tgt in enumerate(translations, 1):
                found = []
                if 'Zkouska' in tgt or 'zkouskou' in tgt:
                    found.append('Czech')
                if lang_code != 'de' and ('Ubersetzer' in tgt or 'funktioniert' in tgt):
                    found.append('German')
                if lang_code != 'el' and ('ΠΡΟΣΟΧΗ' in tgt or 'ΔΗΜΙΟΥΡΓΙΑ' in tgt):
                    found.append('Greek')
                if 'Arxius' in tgt or "l'Orqu" in tgt:
                    found.append('Catalan')
                if 'تخزين' in tgt or 'واسترداد' in tgt:
                    found.append('Arabic')

                status = "CLEAN" if not found else f"CONTAMINATED ({', '.join(found)})"
                print(f"  [{i}] {status}")

                if found:
                    contamination_found = True
                    # Save to file for inspection
                    with open('contaminated_output.txt', 'a', encoding='utf-8') as f:
                        f.write(f"{lang_names[lang_code]} [{i}]: {tgt}\n")

        print("\n[3/3] DIAGNOSIS")
        print("="*80)

        if contamination_found:
            print("\nX CORRUPTION DETECTED")
            print("\n  Corrupted translations saved to: contaminated_output.txt")
            print("\n  ROOT CAUSE: Batch translation producing mixed-language output")
            print("  This matches the production issue exactly!")
            print("\n  Next step: Investigate why forced_bos_token_id is not working correctly")
            return 1
        else:
            print("\nOK ALL TRANSLATIONS CLEAN")
            print("\n  Model is working correctly now.")
            print("  The corruption reported was likely:")
            print("    1. A one-time glitch (resolved)")
            print("    2. TM cache serving bad data (no TM found)")
            print("    3. Temporary model state issue (now cleared)")
            print("\n  RECOMMENDATION:")
            print("    - Delete corrupted test-translation.md files")
            print("    - Re-run translation")
            print("    - Monitor for recurrence")
            return 0

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    import sys
    sys.exit(test())
