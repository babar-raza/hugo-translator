#!/usr/bin/env python3
"""
Test script to check if forced_bos_token_id is being set correctly.

This will help pinpoint if the issue is in BOS token retrieval.
"""

def test_bos_tokens():
    """Test BOS token retrieval for M2M100."""
    print("="*80)
    print("BOS TOKEN DIAGNOSTIC TEST")
    print("="*80)

    try:
        from transformers import M2M100Tokenizer

        print("\n[1/3] Loading M2M100 tokenizer...")
        tokenizer = M2M100Tokenizer.from_pretrained("facebook/m2m100_418M")
        print("✓ Tokenizer loaded")

        # Test languages that are showing contamination
        test_langs = {
            'el': 'Greek',
            'de': 'German',
            'fr': 'French',
            'es': 'Spanish',
            'tr': 'Turkish',
            'uk': 'Ukrainian',
            # Contaminating languages
            'cs': 'Czech (contaminant)',
            'ca': 'Catalan (contaminant)',
            'ar': 'Arabic (contaminant)',
        }

        print("\n[2/3] Testing BOS token retrieval...")
        print(f"{'Language':<25} {'Code':<6} {'BOS Token ID':<15} {'Status'}")
        print("-" * 70)

        bos_tokens = {}
        failures = []

        for code, name in test_langs.items():
            try:
                bos_id = tokenizer.get_lang_id(code)
                bos_tokens[code] = bos_id
                status = "✓ OK"
                print(f"{name:<25} {code:<6} {bos_id:<15} {status}")
            except KeyError as e:
                failures.append((code, name, str(e)))
                status = "✗ FAILED"
                print(f"{name:<25} {code:<6} {'N/A':<15} {status} - KeyError")

        print("\n[3/3] Checking for collisions...")

        # Check if any BOS tokens are the same (collision)
        reverse_map = {}
        collisions = []

        for lang_code, bos_id in bos_tokens.items():
            if bos_id in reverse_map:
                collisions.append((
                    lang_code,
                    reverse_map[bos_id],
                    bos_id
                ))
                print(f"  ✗ COLLISION: {lang_code} and {reverse_map[bos_id]} both map to BOS ID {bos_id}")
            else:
                reverse_map[bos_id] = lang_code

        if not collisions:
            print("  ✓ No BOS token collisions detected")

        # Summary
        print("\n" + "="*80)
        print("SUMMARY")
        print("="*80)
        print(f"  Languages tested: {len(test_langs)}")
        print(f"  Successful: {len(bos_tokens)}")
        print(f"  Failed: {len(failures)}")
        print(f"  Collisions: {len(collisions)}")

        if failures:
            print("\n  ✗ Some languages failed to get BOS token:")
            for code, name, error in failures:
                print(f"    - {name} ({code}): {error}")

        if collisions:
            print("\n  ✗ BOS TOKEN COLLISIONS DETECTED!")
            print("    This will cause language mixing!")

        # Check if tokenizer has all required attributes
        print("\n" + "="*80)
        print("TOKENIZER ATTRIBUTES")
        print("="*80)
        print(f"  has get_lang_id(): {hasattr(tokenizer, 'get_lang_id')}")
        print(f"  has src_lang: {hasattr(tokenizer, 'src_lang')}")
        print(f"  has tgt_lang: {hasattr(tokenizer, 'tgt_lang')}")
        print(f"  has lang_code_to_id: {hasattr(tokenizer, 'lang_code_to_id')}")

        if hasattr(tokenizer, 'lang_code_to_id'):
            num_langs = len(tokenizer.lang_code_to_id)
            print(f"\n  Supported languages: {num_langs}")
            print(f"  Sample codes: {list(tokenizer.lang_code_to_id.keys())[:10]}")

        return len(failures) == 0 and len(collisions) == 0

    except ImportError as e:
        print(f"\n✗ Error: Missing dependency - {e}")
        print("  Install with: pip install transformers")
        return None
    except Exception as e:
        print(f"\n✗ Error during test: {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    import sys
    result = test_bos_tokens()
    if result is None:
        sys.exit(2)
    elif not result:
        sys.exit(1)
    else:
        sys.exit(0)
