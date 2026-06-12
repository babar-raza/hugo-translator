#!/usr/bin/env python3
"""
Backend Translation Probe

Tests whether the translation backend is actually returning translations
or if translations are being reverted somewhere in the pipeline.

Exit code:
- 0: Backend works correctly (outputs French/German)
- 1: Backend failure (outputs remain English)
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))


from src.translation_engine.backends.mt_backend import MTBackend


def detect_language_simple(text: str) -> str:
    """
    Simple heuristic language detection based on common words.

    Returns: 'en', 'fr', 'de', or 'unknown'
    """
    text_lower = text.lower()

    # Common English words
    en_words = ["the", "is", "are", "this", "that", "and", "or", "for", "with", "from", "to"]
    # Common French words
    fr_words = [
        "le",
        "la",
        "les",
        "est",
        "sont",
        "ce",
        "cette",
        "et",
        "ou",
        "pour",
        "avec",
        "de",
        "du",
        "des",
    ]
    # Common German words
    de_words = ["der", "die", "das", "ist", "sind", "und", "oder", "für", "mit", "von", "zu", "den"]

    en_count = sum(1 for word in en_words if f" {word} " in f" {text_lower} ")
    fr_count = sum(1 for word in fr_words if f" {word} " in f" {text_lower} ")
    de_count = sum(1 for word in de_words if f" {word} " in f" {text_lower} ")

    max_count = max(en_count, fr_count, de_count)
    if max_count == 0:
        return "unknown"
    elif en_count == max_count:
        return "en"
    elif fr_count == max_count:
        return "fr"
    elif de_count == max_count:
        return "de"

    return "unknown"


def probe_backend(backend: MTBackend, test_cases: list, src_lang: str, tgt_lang: str) -> dict:
    """
    Probe backend with test sentences.

    Returns:
        dict with results for each test case
    """
    results = []

    print(f"\nProbing: {src_lang} -> {tgt_lang}")
    print("=" * 70)

    for i, source_text in enumerate(test_cases, 1):
        print(f"\n[Test {i}] Source: {source_text}")

        try:
            # Translate
            translation = backend.translate(source_text, src_lang=src_lang, tgt_lang=tgt_lang)

            # Detect language
            detected_lang = detect_language_simple(translation)

            # Check if translation is different from source
            is_different = translation.lower().strip() != source_text.lower().strip()

            # Check if detected language matches target
            lang_match = detected_lang == tgt_lang

            print(f"  Translation: {translation}")
            print(f"  Detected lang: {detected_lang} (expected: {tgt_lang})")
            print(f"  Different from source: {is_different}")
            print(f"  Language match: {'PASS' if lang_match else 'FAIL'}")

            results.append(
                {
                    "source": source_text,
                    "translation": translation,
                    "detected_lang": detected_lang,
                    "expected_lang": tgt_lang,
                    "is_different": is_different,
                    "lang_match": lang_match,
                }
            )

        except Exception as e:
            print(f"  ERROR: {e}")
            results.append(
                {
                    "source": source_text,
                    "error": str(e),
                    "lang_match": False,
                }
            )

    print("\n" + "=" * 70)

    # Summary
    passed = sum(1 for r in results if r.get("lang_match", False))
    total = len(results)

    print(f"\nSummary: {passed}/{total} translations in correct language")

    return {
        "src_lang": src_lang,
        "tgt_lang": tgt_lang,
        "results": results,
        "passed": passed,
        "total": total,
        "success_rate": passed / total if total > 0 else 0,
    }


def main():
    """Main probe entry point."""
    print("Backend Translation Probe")
    print("=" * 70)

    # Test sentences
    test_cases = [
        "This is a test sentence.",
        "Merge textual content.",
        "Supported platforms.",
        "The quick brown fox jumps over the lazy dog.",
    ]

    # Use default model configuration
    model_id = "m2m100_418m"  # Default model
    device = "cuda"  # Default device

    print(f"\nUsing model: {model_id}")
    print(f"Using device: {device}")

    # Create backends (one for French, one for German)
    # Note: Both backends can share the same model (M2M100 supports multiple languages)
    print("\n  Creating French backend...")
    fr_backend = MTBackend(model_id=model_id, device=device)

    print("  Creating German backend...")
    de_backend = MTBackend(model_id=model_id, device=device)

    # Probe French
    fr_results = probe_backend(fr_backend, test_cases, "en", "fr")

    # Probe German
    de_results = probe_backend(de_backend, test_cases, "en", "de")

    # Overall assessment
    print("\n" + "=" * 70)
    print("OVERALL ASSESSMENT")
    print("=" * 70)

    fr_success = fr_results["success_rate"]
    de_success = de_results["success_rate"]

    print(f"French (en->fr): {fr_success:.0%} success rate")
    print(f"German (en->de): {de_success:.0%} success rate")

    # Threshold: require at least 75% success rate
    threshold = 0.75
    fr_pass = fr_success >= threshold
    de_pass = de_success >= threshold

    print(f"\nFrench: {'PASS' if fr_pass else 'FAIL'} (threshold: {threshold:.0%})")
    print(f"German: {'PASS' if de_pass else 'FAIL'} (threshold: {threshold:.0%})")

    if not fr_pass or not de_pass:
        print("\n[WARNING] BACKEND FAILURE DETECTED")
        print("The backend is outputting English when it should output translations.")
        print("Check:")
        print("  1. Language code mapping (fr vs fra_Latn, de vs deu_Latn)")
        print("  2. Model selection (correct model for target language)")
        print("  3. Generation parameters (forced_bos_token_id, etc.)")
        print("  4. Backend signature (generation_params applied correctly)")
        return 1
    else:
        print("\n[OK] Backend appears to be working correctly.")
        print("If translations still appear as English in output, the issue is in the pipeline:")
        print("  - Check SegmentExtractor translation phase")
        print("  - Check language purity validator")
        print("  - Check TM cache (might contain English as 'translations')")
        return 0


if __name__ == "__main__":
    sys.exit(main())
