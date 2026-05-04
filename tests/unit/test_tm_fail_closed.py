"""TC-C3: TM fail-closed on detector errors.

Four cases:
  (a) detector raises → returns False + warning logged
  (b) valid hit (correct language) → returns True
  (c) invalid-language hit → returns False
  (d) short-text (<10 chars) → returns True (short-text exemption preserved)
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest


def _make_tm_with_detector(detector):
    """Build a minimal TranslationMemory instance with the given detector."""
    from src.tm.translation_memory import TranslationMemory

    tm = TranslationMemory.__new__(TranslationMemory)
    tm._language_detector = detector
    tm._similarity_tracker = None
    tm._poisoned_hits_rejected = 0
    return tm


class TestTMFailClosed:
    def test_detector_raises_returns_false_with_warning(self, caplog):
        """(a) Detector exception → returns False; warning is logged."""
        bad_detector = MagicMock()
        bad_detector.detect.side_effect = RuntimeError("CUDA OOM")
        tm = _make_tm_with_detector(bad_detector)

        with caplog.at_level(logging.WARNING, logger="src.tm.translation_memory"):
            result = tm._validate_hit_language("Привет, как дела сегодня!", "bg")

        assert result is False, "Must reject (fail-closed) when detector raises"
        assert any(
            "fail-closed" in record.message.lower()
            or "exception" in record.message.lower()
            or "detector" in record.message.lower()
            for record in caplog.records
        ), "Warning must be logged when detector raises"

    def test_valid_hit_returns_true(self):
        """(b) Valid hit in the correct language → returns True."""
        good_detector = MagicMock()
        good_detector.detect.return_value = ("bg", 0.95)
        tm = _make_tm_with_detector(good_detector)

        result = tm._validate_hit_language("Здравейте, как сте?", "bg")

        assert result is True

    def test_wrong_language_hit_returns_false(self):
        """(c) Hit detected as wrong language → returns False."""
        bad_lang_detector = MagicMock()
        bad_lang_detector.detect.return_value = ("es", 0.92)
        tm = _make_tm_with_detector(bad_lang_detector)

        result = tm._validate_hit_language("Hello world in wrong language here", "bg")

        assert result is False

    def test_short_text_exemption_preserved(self):
        """(d) Short text (<10 chars) → returns True; detector never called."""
        detector = MagicMock()
        detector.detect.side_effect = RuntimeError("should not be called")
        tm = _make_tm_with_detector(detector)

        result = tm._validate_hit_language("Hi", "bg")

        assert result is True
        detector.detect.assert_not_called()
