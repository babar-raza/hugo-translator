"""TC-C1: Purity false-positive strip tests.

Validates _should_skip_purity_segment() helper in engine.py.

Six cases:
  1. test_barcode_spec_skipped
  2. test_aspose_name_skipped
  3. test_normal_prose_not_skipped
  4. test_legitimate_wrong_language_detected
  5. test_punctuation_heavy_skipped
  6. test_purity_threshold_reduction_bg (integration: BG 0.15 threshold + strip)
"""

from __future__ import annotations

import pytest


def _skip(line: str) -> bool:
    from src.translation_engine.engine import TranslationEngine

    return TranslationEngine._should_skip_purity_segment(line)


class TestShouldSkipPuritySegment:
    def test_barcode_spec_skipped(self):
        """Barcode symbology spec lines must be excluded from FastText."""
        assert _skip("Codabar: 0-9,A-D") is True
        assert _skip("Code 11: 0-9,-") is True
        assert _skip("Code 128: 0-9,A-Z,a-z") is True

    def test_aspose_name_skipped(self):
        """Lines containing Aspose product tokens must be excluded."""
        assert _skip("Aspose.BarCode for .NET") is True
        assert _skip("Aspose.PDF Cloud") is True

    def test_normal_prose_not_skipped(self):
        """Natural-language sentences must NOT be excluded."""
        assert _skip("Тази функция поддържа следните формати на баркод") is False
        assert _skip("The document was saved successfully") is False
        assert _skip("Dokumentas sėkmingai išsaugotas") is False

    def test_punctuation_heavy_skipped(self):
        """Lines that are mostly punctuation/digits must be excluded."""
        assert _skip("---") is True
        assert _skip("===") is True
        assert _skip("0-9,A-Z,...") is True
        assert _skip("1234567890") is True  # all digits

    def test_reference_table_row_skipped(self):
        """Generated API reference table rows are identifier-heavy, not language evidence."""
        assert _skip("| `MAXREGSECT` | `uint` | Read | Defines the maximum regular sectors |") is True

    def test_reference_api_signature_line_skipped(self):
        """API signature-heavy lines are excluded from FastText purity scoring."""
        assert _skip("`A3DObject(name: String)` creates an A3D object") is True

    def test_hugo_shortcode_line_skipped(self):
        """Hugo shortcode-only lines are structure, not language evidence."""
        assert _skip('{{< sections cols="4" >}}') is True
        assert _skip('{{% alert color="primary" %}}') is True

    def test_format_acronym_selector_line_skipped(self):
        """Format selector lines are immutable technical inventories, not prose."""
        assert _skip("MSG (read/write), CFB (read/write), EML (via conversion)") is True
        assert _skip("DOCX, DOC, RTF, TXT, PDF, Markdown") is True

    def test_legitimate_wrong_language_not_skipped(self):
        """Russian text in a BG file is legitimate wrong-language — must NOT be skipped."""
        russian_text = "Привет мир, как дела сегодня вечером"
        assert _skip(russian_text) is False

    def test_empty_line_not_skipped(self):
        """Empty string returns False without errors."""
        assert _skip("") is False

    # TC-C1B: Verify the token-dominance replacement for Pattern 3 (2026-06-11)

    def test_prose_with_product_name_not_skipped(self):
        """TC-C1B: Natural-language prose that mentions an Aspose product must NOT be skipped.
        These lines have one product token among many prose words (dominance < 50%)."""
        assert _skip("Aspose.BarCode provides comprehensive barcode generation functionality for enterprise document workflows") is False
        assert _skip("For more information about Aspose.PDF see the official documentation page") is False
        assert _skip("Aspose.Words supports all major document formats including DOCX PDF and RTF") is False

    def test_product_name_only_line_still_skipped(self):
        """TC-C1B: Lines that are predominantly product-name tokens are still skipped.
        These lines have product tokens as majority of words (dominance > 50%)."""
        assert _skip("Aspose.BarCode for .NET") is True
        assert _skip("Aspose.PDF Cloud") is True
        assert _skip("Aspose.Words") is True


class TestPurityThresholdReductionBG:
    """Integration test: BG file with barcode ASCII passes at 0.15 threshold after strip."""

    def test_bg_barcode_file_passes_with_strip(self):
        """A BG-translated file containing barcode spec lines passes at 0.15 threshold
        when the strip removes them from FastText input."""
        from unittest.mock import MagicMock

        # Detector that flags "Codabar: 0-9,A-D" as Spanish (the real FP observed in logs)
        # and correctly identifies Bulgarian prose as Bulgarian
        def mock_detect(text):
            if text.startswith("Codabar") or text.startswith("Code"):
                return ("es", 0.90)  # FastText FP for barcode ASCII
            return ("bg", 0.95)

        detector = MagicMock()
        detector.detect.side_effect = mock_detect

        # Build a minimal engine with only the config attribute needed
        from src.translation_engine.engine import TranslationEngine

        engine = TranslationEngine.__new__(TranslationEngine)

        class FakeConfig:
            def get_config(self):
                return {
                    "translation_engine": {
                        "language_detection_confidence_threshold": 0.80,
                        "purity_threshold_overrides": {"bg": 0.15},
                    }
                }

        engine.config = FakeConfig()
        engine.similarity_tracker = None

        from src.translation_engine.write_gate import WriteGateEvaluator

        engine._write_gate = WriteGateEvaluator(
            detector=None,
            similarity_tracker=None,
            config=engine.config,
            force_accept=False,
        )

        # Content: mostly Bulgarian prose, with 3 barcode spec lines scattered in
        content = (
            "---\ntitle: Баркод\n---\n"
            "Тази страница описва поддържаните формати на баркод за Aspose.BarCode.\n"
            "Codabar: 0-9,A-D\n"
            "Поддържаните типове включват следните стандарти.\n"
            "Code 11: 0-9,-\n"
            "Форматите се използват широко в логистиката и управлението.\n"
            "Code 128: 0-9,A-Z,a-z\n"
            "Всички формати са напълно поддържани от нашата библиотека.\n"
        )

        result = engine._verify_final_file_purity(content, "bg", detector)

        # After strip, no barcode lines reach FastText → 0% wrong-language
        assert result["passed"] is True, (
            f"Expected BG file to pass at 0.15 threshold after strip, got: {result}"
        )

    def test_legitimate_russian_in_bg_still_detected(self):
        """Russian paragraphs in a BG file must still be detected even after strip."""
        from unittest.mock import MagicMock

        def mock_detect(text):
            if "Привет" in text or "Россия" in text:
                return ("ru", 0.92)
            return ("bg", 0.95)

        detector = MagicMock()
        detector.detect.side_effect = mock_detect

        from src.translation_engine.engine import TranslationEngine

        engine = TranslationEngine.__new__(TranslationEngine)

        class FakeConfig:
            def get_config(self):
                return {
                    "translation_engine": {
                        "language_detection_confidence_threshold": 0.80,
                        "purity_threshold_overrides": {"bg": 0.15},
                    }
                }

        engine.config = FakeConfig()
        engine.similarity_tracker = None

        from src.translation_engine.write_gate import WriteGateEvaluator

        engine._write_gate = WriteGateEvaluator(
            detector=None,
            similarity_tracker=None,
            config=engine.config,
            force_accept=False,
        )

        # Content: 2 good BG paragraphs + 3 Russian paragraphs (>15% threshold)
        content = (
            "---\ntitle: Test\n---\n"
            "Тази страница е написана на български език за тестване.\n"
            "Форматите се използват широко в логистиката и управлението.\n"
            "Привет, это тестовый параграф на русском языке здесь.\n"
            "Россия является крупнейшей страной в мире по территории.\n"
            "Это третий параграф на русском языке для теста провала.\n"
        )

        result = engine._verify_final_file_purity(content, "bg", detector)
        assert result["passed"] is False, (
            f"Russian contamination must be detected even after TC-C1 strip, got: {result}"
        )
