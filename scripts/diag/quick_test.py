#!/usr/bin/env python3
"""Quick test to reproduce the corruption issue directly."""


def test():
    print("=" * 80)
    print("QUICK CORRUPTION TEST")
    print("=" * 80)

    try:
        import torch
        from transformers import M2M100ForConditionalGeneration, M2M100Tokenizer

        print("\n[1/4] Loading model...")
        model = M2M100ForConditionalGeneration.from_pretrained("facebook/m2m100_418M")
        tokenizer = M2M100Tokenizer.from_pretrained("facebook/m2m100_418M")
        print("OK - Model loaded")

        # Test texts from test-translation.md
        test_texts = [
            "Test Translation Article",
            "This is a test article to verify the translation system works correctly",
            "File detection by orchestrator",
        ]

        # Languages that showed corruption
        test_langs = ["el", "de", "tr", "uk"]
        lang_names = {"el": "Greek", "de": "German", "tr": "Turkish", "uk": "Ukrainian"}

        print("\n[2/4] Testing BATCH translation (reproducing production scenario)...")

        all_clean = True

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
                generated = model.generate(**encoded, forced_bos_token_id=bos_id, max_new_tokens=50)

            # Decode
            translations = tokenizer.batch_decode(generated, skip_special_tokens=True)

            # Check each translation
            for i, (src, tgt) in enumerate(zip(test_texts, translations, strict=False), 1):
                # Check for contamination markers
                markers = {
                    "Czech": ["Zkouska", "zkouskou"],
                    "German": ["Ubersetzer", "funktioniert"],
                    "Greek": ["ΠΡΟΣΟΧΗ", "ΔΗΜΙΟΥΡΓΙΑ"],
                    "Catalan": ["Arxius", "l'Orqu"],
                    "Arabic": ["تخزين", "واسترداد"],
                }

                found = []
                for lang, words in markers.items():
                    for word in words:
                        if word in tgt:
                            found.append(lang)
                            break

                status = "CLEAN" if not found else f"CONTAMINATED ({', '.join(set(found))})"
                if found:
                    all_clean = False

                print(f"  [{i}] {status}")
                # Skip printing Unicode to avoid encoding issues
                # print(f"      {tgt[:70]}")

        print("\n[3/4] Testing INDIVIDUAL translation (fallback mode)...")

        individual_clean = True
        lang_code = "el"  # Test Greek

        print(f"\n--- {lang_names[lang_code]} (individual) ---")

        for i, text in enumerate(test_texts, 1):
            tokenizer.src_lang = "en"
            encoded = tokenizer([text], return_tensors="pt")
            bos_id = tokenizer.get_lang_id(lang_code)

            with torch.no_grad():
                generated = model.generate(**encoded, forced_bos_token_id=bos_id, max_new_tokens=50)

            translation = tokenizer.batch_decode(generated, skip_special_tokens=True)[0]

            # Check contamination
            if any(
                m in translation for m in ["Zkouska", "Ubersetzer", "ΠΡΟΣΟΧΗ", "Arxius", "تخزين"]
            ):
                print(f"  [{i}] CONTAMINATED")
                individual_clean = False
            else:
                print(f"  [{i}] CLEAN")

        print("\n[4/4] DIAGNOSIS")
        print("=" * 80)

        if not all_clean and not individual_clean:
            print("\nX CORRUPTION REPRODUCED IN BOTH MODES")
            print("  -> MODEL OR TOKENIZER ISSUE")
            print("\n  Root cause:")
            print("    - forced_bos_token_id may not be working")
            print("    - Model checkpoint may be corrupted")
            print("    - Tokenizer state contamination")
        elif not all_clean:
            print("\nX CORRUPTION IN BATCH MODE ONLY")
            print("  -> BATCH PROCESSING BUG")
        elif not individual_clean:
            print("\nX CORRUPTION IN INDIVIDUAL MODE ONLY")
            print("  -> UNEXPECTED (shouldn't happen)")
        else:
            print("\nOK ALL TRANSLATIONS ARE CLEAN")
            print("  -> Cannot reproduce corruption")
            print("  -> Issue may have been temporary or TM-related")
            print("\n  Since no TM database files were found, the corruption")
            print("  was likely a one-time event that's now resolved.")

        return 0

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    import sys

    sys.exit(test())
