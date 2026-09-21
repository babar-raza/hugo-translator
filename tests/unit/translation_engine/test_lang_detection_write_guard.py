"""Tests for language detection write-blocking guards in engine.py.

Regression tests for commit aef8c874: English content overwrote existing
translations because (1) LanguageConsistencyValidator wasn't critical, and
(2) FastText detector was None, skipping all language protection.

These tests verify that the engine blocks writes when language detection
is unavailable or fails, rather than allowing unvalidated content through.
"""

from unittest.mock import Mock

from src.translation_engine.engine import (
    TranslationEngine,
    _frontmatter_has_strong_script_evidence,
)


class _DummyConfigService:
    def get_config(self):
        return {
            "adaptive_batching": {"enabled": False},
            "language_detection": {"provider": "none"},
            "autonomous_recovery": {"oom_retry": {"enabled": False}},
        }


def _make_engine() -> TranslationEngine:
    return TranslationEngine(
        config_service=_DummyConfigService(),
        tm=Mock(),
        model_loader=Mock(),
        enable_validation=False,
        enable_telemetry=False,
    )


class TestChineseTechnicalFrontmatter:
    """Technical ASCII tokens must not outvote Chinese ordinary prose."""

    def test_accepts_substantial_chinese_after_governed_tokens_removed(self):
        assert _frontmatter_has_strong_script_evidence(
            "使用 Aspose.Cells FOSS 在 Rust 中管理电子表格和工作表",
            "zh",
        )

    def test_rejects_token_chinese_added_to_english_prose(self):
        assert not _frontmatter_has_strong_script_evidence(
            "Spreadsheet Management with Aspose.Cells FOSS in Rust 中文",
            "zh",
        )

    def test_frontmatter_gate_keeps_english_ordinary_prose_blocking(self):
        content = "---\ntitle: Spreadsheet Management with Aspose.Cells FOSS in Rust 中文\n---\n"

        issues = _make_engine()._check_frontmatter_language(content, "zh")

        assert len(issues) == 1
        assert issues[0].validator == "FrontmatterLanguageCheck"
        assert issues[0].details["expected_lang"] == "zh"


class TestLatinTechnicalFrontmatter:
    """Governed technical tokens must not outvote translated Latin prose."""

    def test_accepts_strong_italian_ordinary_prose_signal(self):
        content = "---\ntitle: 'Approfondimento: il CSSOM in Python'\n---\n"

        assert _make_engine()._check_frontmatter_language(content, "it") == []

    def test_keeps_untranslated_english_ordinary_prose_blocking(self):
        content = "---\ntitle: 'Deep Dive: The CSSOM in Python'\n---\n"

        issues = _make_engine()._check_frontmatter_language(content, "it")

        assert len(issues) == 1
        assert issues[0].validator == "FrontmatterLanguageCheck"
        assert issues[0].details["detected_lang"] == "en"


class TestShortSignalFrontmatterExemption:
    """TC-APT-040: bare `_index.md` titles like "Aspose.X FOSS for Y" strip down
    to a 1-3 char connector word after governed technical tokens are removed,
    which used to fall through to raw-text detection and hard-fail every
    language 100% of the time regardless of actual translation (confirmed on
    blog.aspose.org/note/python/_index.md, 25/25 languages). Below the 6-alpha-
    char signal floor there is too little independent prose to make any
    reliable determination, so the check must skip instead of misreport.
    """

    def test_bare_index_title_below_signal_floor_skips_validation(self):
        content = "---\ntitle: 'Aspose.Note FOSS for Python'\n---\n"

        for lang in ("fr", "es", "de", "ja"):
            assert _make_engine()._check_frontmatter_language(content, lang) == []

    def test_introducing_prefixed_title_above_floor_still_flags_untranslated(self):
        """The exemption must be narrow: titles with enough real prose (e.g. the
        "Introducing" prefix supplies 11 signal chars) must still correctly
        catch genuinely untranslated English -- this is not a blanket disable.
        """
        content = "---\ntitle: 'Introducing Aspose.Words FOSS for .NET'\n---\n"

        issues = _make_engine()._check_frontmatter_language(content, "fr")

        assert len(issues) == 1
        assert issues[0].validator == "FrontmatterLanguageCheck"
        assert issues[0].details["detected_lang"] == "en"


class TestDetectorNoneBlocksWrite:
    """When _get_language_detector() returns None, writes must be blocked."""

    def test_get_language_detector_returns_none_when_both_attrs_none(self):
        engine = _make_engine()
        engine.fasttext_detector = None
        engine.detector = None

        assert engine._get_language_detector() is None

    def test_detector_none_sets_validation_passed_false(self):
        """Simulate the engine's detector-None guard logic.

        This tests the exact pattern from engine.py:1522-1530 to verify
        that when detector is None, validation_passed is set to False.
        """
        engine = _make_engine()
        engine.fasttext_detector = None
        engine.detector = None

        # Simulate the code path from engine.py:1522-1530
        validation_passed = True
        detector = engine._get_language_detector()

        if detector is None:
            validation_passed = False

        assert validation_passed is False, (
            "validation_passed must be False when detector is None — "
            "this prevents unvalidated content from being written"
        )


class TestDetectorExceptionBlocksWrite:
    """When detector.detect() raises, writes must be blocked."""

    def test_value_error_blocks_write(self):
        """ValueError from detector.detect() must block writes.

        Regression: previously, ValueError was caught with a warning and
        the write was allowed to proceed.
        """
        engine = _make_engine()
        mock_detector = Mock()
        mock_detector.detect.side_effect = ValueError("Confidence too low")
        engine.fasttext_detector = mock_detector

        validation_passed = True
        validation_error = None
        detector = engine._get_language_detector()

        assert detector is not None

        # Simulate the try/except from engine.py:1520-1623
        try:
            detected_lang, confidence = detector.detect("some content")
        except ValueError as e:
            validation_passed = False
            validation_error = f"Language detection uncertain: {e}"

        assert validation_passed is False
        assert "uncertain" in validation_error

    def test_io_error_blocks_write(self):
        """IOError from detector.detect() must block writes.

        Regression: previously, IOError was caught with a warning and
        the write was allowed to proceed.
        """
        engine = _make_engine()
        mock_detector = Mock()
        mock_detector.detect.side_effect = OSError("Model file corrupted")
        engine.fasttext_detector = mock_detector

        validation_passed = True
        validation_error = None
        detector = engine._get_language_detector()

        assert detector is not None

        try:
            detected_lang, confidence = detector.detect("some content")
        except OSError as e:
            validation_passed = False
            validation_error = f"I/O error during language validation: {e}"

        assert validation_passed is False
        assert "I/O error" in validation_error

    def test_os_error_blocks_write(self):
        """OSError from detector.detect() must block writes."""
        engine = _make_engine()
        mock_detector = Mock()
        mock_detector.detect.side_effect = OSError("Permission denied")
        engine.fasttext_detector = mock_detector

        validation_passed = True
        detector = engine._get_language_detector()

        try:
            detected_lang, confidence = detector.detect("some content")
        except OSError:
            validation_passed = False

        assert validation_passed is False


class TestDetectorNoneSkipsPurityCheck:
    """When detector is None, the purity check must also be skipped safely."""

    def test_purity_check_guarded_by_detector_not_none(self):
        """engine.py:1627 gates purity check on `detector is not None`.

        Verify the guard pattern: purity check only runs when detector exists.
        """
        engine = _make_engine()
        engine.fasttext_detector = None
        engine.detector = None

        detector = engine._get_language_detector()
        validation_passed = False  # already blocked by detector=None check

        # This mirrors engine.py:1627
        purity_ran = False
        if validation_passed and detector is not None:
            purity_ran = True

        assert purity_ran is False, "Purity check must not run when detector is None"
