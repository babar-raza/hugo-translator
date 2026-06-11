"""
Regression tests for signature preservation (Concern #4 fix).

These tests ensure that method/type signatures are never corrupted during translation.
The _is_signature_like() function was added to detect and protect signatures.

MUST pass cases (should be preserved exactly):
- BarCodeReader(string)
- Foo(int, bool)
- Aspose.BarCode.BarCodeReader(string)
- MyType<T>(IEnumerable<T>)
- DoThing(params string[])

MUST translate cases (should NOT be protected):
- "Inheritance" (single word, not a signature)
- "Derived" (single word, not a signature)
- "Notes (Important)" (sentence with parentheses, not API signature)
"""

import sys
from pathlib import Path

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.translation_engine.extractor.text_unit_extractor import TextUnitExtractor


class TestSignaturePreservation:
    """Tests for _is_signature_like() method."""

    @pytest.fixture
    def extractor(self):
        """Create a TextUnitExtractor instance."""
        # Minimal config for testing
        return TextUnitExtractor(
            segmentation_strategy="sentence_only",
            preserve_patterns=[],
        )

    # ============================================
    # MUST PRESERVE cases (signatures)
    # ============================================

    @pytest.mark.parametrize(
        "signature",
        [
            "BarCodeReader(string)",
            "BarCodeReader\\(string\\)",  # Escaped markdown
            "Foo(int, bool)",
            "Aspose.BarCode.BarCodeReader(string)",
            "MyType()",
            "DoThing(params string[])",
            "GetValue(int index)",
            "System.Exception(string message)",
            "IDisposable.Dispose()",
            "List.Add(T item)",
        ],
    )
    def test_must_preserve_simple_signatures(self, extractor, signature):
        """Simple method signatures must be detected and protected."""
        assert extractor._is_signature_like(signature), (
            f"Signature should be protected: {signature}"
        )

    @pytest.mark.parametrize(
        "signature",
        [
            '<a id="__ctor_System_String_"></a> BarCodeReader(string)',
            '<a id="__method"></a> GetValue(int)',
        ],
    )
    def test_must_preserve_anchor_with_signature(self, extractor, signature):
        """HTML anchors with signatures must be detected and protected."""
        assert extractor._is_signature_like(signature), (
            f"Anchor+signature should be protected: {signature}"
        )

    @pytest.mark.parametrize(
        "signature",
        [
            "Namespace.Class.Method(Type param)",
            "Aspose.BarCode.Recognition.BarCodeReader(string)",
            "System.Collections.Generic.List(T)",
        ],
    )
    def test_must_preserve_dotted_signatures(self, extractor, signature):
        """Fully-qualified dotted signatures must be protected."""
        assert extractor._is_signature_like(signature), (
            f"Dotted signature should be protected: {signature}"
        )

    # ============================================
    # MUST TRANSLATE cases (not signatures)
    # ============================================

    @pytest.mark.parametrize(
        "text",
        [
            "Inheritance",
            "Derived",
            "Exception",
            "Constructor",
            "Method",
            "Property",
        ],
    )
    def test_must_translate_single_words(self, extractor, text):
        """Single words without parentheses must NOT be protected."""
        assert not extractor._is_signature_like(text), (
            f"Single word should NOT be protected: {text}"
        )

    @pytest.mark.parametrize(
        "text",
        [
            "Notes (Important)",
            "This method returns a value (see documentation)",
            "Use the constructor (recommended)",
            "The class inherits from base (abstract)",
        ],
    )
    def test_must_translate_sentences_with_parentheses(self, extractor, text):
        """Sentences with parenthetical comments are NOT signatures."""
        assert not extractor._is_signature_like(text), (
            f"Sentence with parentheses should NOT be protected: {text}"
        )

    @pytest.mark.parametrize(
        "text",
        [
            "Click here to learn more",
            "This is a description of the API",
            "Returns the barcode value",
            "Throws an exception if invalid",
        ],
    )
    def test_must_translate_prose(self, extractor, text):
        """Normal prose/sentences must NOT be protected."""
        assert not extractor._is_signature_like(text), f"Prose should NOT be protected: {text}"

    # ============================================
    # Edge cases
    # ============================================

    def test_empty_string(self, extractor):
        """Empty string should not be a signature."""
        assert not extractor._is_signature_like("")

    def test_none_handling(self, extractor):
        """None should not crash."""
        assert not extractor._is_signature_like(None)

    def test_whitespace_only(self, extractor):
        """Whitespace-only should not be a signature."""
        assert not extractor._is_signature_like("   ")

    def test_unicode_in_signature(self, extractor):
        """Unicode characters should not break detection."""
        # Note: Current regex uses \w which may not match all unicode
        # This tests that the function doesn't crash on unicode input
        # Whether it detects "GetNäme()" as signature is implementation detail
        result = extractor._is_signature_like("GetNäme()")
        assert isinstance(result, bool), "Should return bool, not crash"
        # ASCII signatures still work
        assert extractor._is_signature_like("GetName()")
        # Prose sentences are not signatures (pattern 3 checks ratio)
        assert not extractor._is_signature_like(
            "This is a sentence that happens to contain GetName()."
        )


class TestSignaturePreservationIntegration:
    """Integration tests verifying signatures are preserved in full extraction."""

    @pytest.fixture
    def extractor(self):
        """Create a TextUnitExtractor instance."""
        return TextUnitExtractor(
            segmentation_strategy="sentence_only",
            preserve_patterns=[],
        )

    def test_signature_not_in_translatable_units(self, extractor):
        """Signatures should not appear in units marked for translation."""
        # This test verifies the integration with _is_non_translatable()
        text = "BarCodeReader(string)"
        # The signature should be detected as non-translatable
        is_non_translatable = extractor._is_non_translatable(text)
        assert is_non_translatable, f"Signature '{text}' should be marked as non-translatable"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
