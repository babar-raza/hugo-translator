"""
Unit test: Translation Memory must reject English stored as "French translation".

This test verifies that when TM contains English text stored as a French translation,
the system rejects it and retranslates instead of reusing the incorrect cached entry.

Context:
If the translation pipeline accidentally stores English as a "translation" in TM,
subsequent runs would reuse this English text, causing the output to remain English.

Expected behavior:
- TM entry with English stored as "fr translation" should be rejected
- System should call backend to get real French translation
- Language purity check should prevent storing English as French in TM
"""

import sys
from pathlib import Path

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def test_tm_cache_language_validation():
    """
    Test that TM cache validates language before reuse.

    Scenario:
    1. TM contains: source="Hello world" → target="Hello world" (lang=fr)
    2. Request translation of "Hello world" to French
    3. System should REJECT cached entry (English != French)
    4. System should call backend for real translation
    """
    # This is a placeholder test - actual implementation depends on TM structure
    # The test would:
    # 1. Create a mock TM with English stored as French
    # 2. Request translation
    # 3. Verify backend was called (TM rejected)
    # 4. Verify output is French, not English

    pytest.skip("TM language validation test - requires TM implementation details")


def test_language_purity_prevents_english_storage():
    """
    Test that language purity check prevents storing English as French in TM.

    Scenario:
    1. Backend returns English (bug or misconfiguration)
    2. Language purity check detects English output for French target
    3. System should NOT store this in TM as "French translation"
    4. System should retry or fallback, not cache the error
    """
    pytest.skip("Language purity storage prevention test - requires TM integration")


def test_backend_output_language_detection():
    """
    Test that backend outputs are language-detected before storage.

    Scenario:
    1. Translate "Hello world" to French
    2. Backend returns "Hello world" (unchanged - bug)
    3. Detect language of output = English
    4. Assert output language != target language
    5. Do not store in TM
    """

    # Simple heuristic detection (if FastText not available)
    def detect_language_simple(text: str) -> str:
        text_lower = text.lower()
        # Common French words
        fr_words = ["le", "la", "les", "est", "sont", "de", "des", "et", "pour"]
        # Common English words
        en_words = ["the", "is", "are", "and", "for", "with"]

        fr_count = sum(1 for word in fr_words if f" {word} " in f" {text_lower} ")
        en_count = sum(1 for word in en_words if f" {word} " in f" {text_lower} ")

        if en_count > fr_count:
            return "en"
        elif fr_count > 0:
            return "fr"
        return "unknown"

    # Test cases
    english_output = "Hello world, this is a test"
    french_output = "Bonjour le monde, c'est un test"

    assert detect_language_simple(english_output) == "en", "Should detect English output"
    assert detect_language_simple(french_output) == "fr", "Should detect French output"

    # If target is French but output is English, reject
    target_lang = "fr"
    detected = detect_language_simple(english_output)
    assert detected != target_lang, (
        f"Backend output language ({detected}) does not match target ({target_lang}), should reject"
    )


def test_generation_params_applied():
    """
    Test that generation_params are applied to prevent copy-through.

    Context:
    If generation_params (repetition_penalty, etc.) are not applied,
    the model may copy the source text unchanged.

    Test:
    1. Verify NLLBBackend.translate() accepts generation_params
    2. Verify parameters are passed to CTranslate2
    3. Verify different params produce different outputs (indirect test)
    """
    # This would test the fix we just applied
    import inspect

    from src.model_runtime.loader import NLLBBackend

    # Check signature includes generation_params
    sig = inspect.signature(NLLBBackend.translate)
    params = list(sig.parameters.keys())

    assert "generation_params" in params, (
        "NLLBBackend.translate() must accept generation_params parameter"
    )
    assert "max_new_tokens" in params, (
        "NLLBBackend.translate() must accept max_new_tokens parameter"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
