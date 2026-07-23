"""
Integration tests for write gate 42 (HT-QUALITY-GATES-001 Phase 8, Tier A
#1): whole-page wrong-target-language contamination -- catches "this Czech
page is actually Chinese" wholesale-swap corruption that Gate 4/5's
per-paragraph purity sampling can miss, and that audit_all_content.py's
purity_issue check structurally cannot catch (pure ASCII-ratio proxy, only
ever flags excess ENGLISH). Reuses the production FastTextDetector, not a
4th independent language-ID implementation.

Ships "warn" per this registry's established rollout convention.
"""
from pathlib import Path
from unittest.mock import MagicMock

from src.translation_engine.write_gate import WriteGateEvaluator, WriteGateResult


def _make_gate(detector=None, similarity_tracker=None) -> WriteGateEvaluator:
    config = MagicMock()
    config.get_config.return_value = {"translation_engine": {}}
    return WriteGateEvaluator(
        detector=detector, similarity_tracker=similarity_tracker, config=config,
        force_accept=True,
    )


_LONG_BODY = (
    "---\ntitle: Test\n---\n"
    "This body is long enough to be classified reliably by a whole-page "
    "language detector, well above the minimum length threshold.\n"
)


class TestGateWholePageLanguageMismatch:
    def test_wrong_language_wholesale_swap_is_flagged(self):
        detector = MagicMock()
        detector.detect.return_value = ("zh", 0.97)
        tracker = MagicMock()
        tracker.are_similar.return_value = False
        gate = _make_gate(detector=detector, similarity_tracker=tracker)

        result = WriteGateResult(passed=True)
        gate._gate_whole_page_language_mismatch(_LONG_BODY, "cs", Path("test.md"), result)

        assert result.passed is False
        assert "zh" in result.error
        assert "cs" in result.error

    def test_matching_language_is_silent(self):
        detector = MagicMock()
        detector.detect.return_value = ("cs", 0.97)
        gate = _make_gate(detector=detector)

        result = WriteGateResult(passed=True)
        gate._gate_whole_page_language_mismatch(_LONG_BODY, "cs", Path("test.md"), result)

        assert result.passed is True

    def test_low_confidence_detection_is_not_flagged(self):
        detector = MagicMock()
        detector.detect.return_value = ("zh", 0.60)  # below 0.85 threshold
        gate = _make_gate(detector=detector)

        result = WriteGateResult(passed=True)
        gate._gate_whole_page_language_mismatch(_LONG_BODY, "cs", Path("test.md"), result)

        assert result.passed is True

    def test_similarity_tracker_suppresses_known_similar_pair(self):
        detector = MagicMock()
        detector.detect.return_value = ("hr", 0.95)
        tracker = MagicMock()
        tracker.are_similar.return_value = True  # hr/sr known-similar pair
        gate = _make_gate(detector=detector, similarity_tracker=tracker)

        result = WriteGateResult(passed=True)
        gate._gate_whole_page_language_mismatch(_LONG_BODY, "sr", Path("test.md"), result)

        assert result.passed is True

    def test_no_detector_available_is_a_graceful_no_op(self):
        """Matches Gates 2-5's own degrade behavior when no detector is
        injected (e.g. a dependency-free offline audit context) -- must
        not crash or falsely flag."""
        gate = _make_gate(detector=None)

        result = WriteGateResult(passed=True)
        gate._gate_whole_page_language_mismatch(_LONG_BODY, "cs", Path("test.md"), result)

        assert result.passed is True

    def test_short_body_is_not_classified(self):
        detector = MagicMock()
        detector.detect.return_value = ("zh", 0.99)
        gate = _make_gate(detector=detector)
        short_body = "---\ntitle: Test\n---\nHi.\n"

        result = WriteGateResult(passed=True)
        gate._gate_whole_page_language_mismatch(short_body, "cs", Path("test.md"), result)

        assert result.passed is True
        detector.detect.assert_not_called()

    def test_detector_exception_fails_open(self):
        detector = MagicMock()
        detector.detect.side_effect = ValueError("boom")
        gate = _make_gate(detector=detector)

        result = WriteGateResult(passed=True)
        gate._gate_whole_page_language_mismatch(_LONG_BODY, "cs", Path("test.md"), result)

        assert result.passed is True
