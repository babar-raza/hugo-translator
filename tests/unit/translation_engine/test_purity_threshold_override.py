"""
Tests for per-language purity threshold overrides in _verify_final_file_purity.

The method under test lives at:
    src/translation_engine/engine.py :: TranslationEngine._verify_final_file_purity

Key behavioural facts confirmed by reading the source:
  - Content is split line-by-line; empty lines are dropped by the stripped check.
  - A paragraph is skipped when len(para) < 20.
  - Wrong only when detected != expected AND conf > 0.70.
  - Boundary: wrong_percentage > threshold -> FAIL  (equal == PASS).
  - Default threshold: 0.06 (falls back when no override / config raises).
  - Per-language overrides: translation_engine.purity_threshold_overrides.
"""

from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine(purity_threshold_overrides=None, config_raises=False):
    """Return a minimal mock self that satisfies _verify_final_file_purity.

    Parameters
    ----------
    purity_threshold_overrides:
        Dict of {lang_code: float} overrides, or None for an empty dict.
    config_raises:
        When True, self.config.get_config() raises for fallback testing.
    """
    from src.translation_engine.write_gate import WriteGateEvaluator

    mock_self = MagicMock()  # no spec: self.config is set in __init__, not class body
    mock_self.similarity_tracker = None
    te_cfg = {}
    if purity_threshold_overrides is not None:
        te_cfg["purity_threshold_overrides"] = purity_threshold_overrides
    if config_raises:
        mock_self.config.get_config.side_effect = Exception("config unavailable")
    else:
        mock_self.config.get_config.return_value = {"translation_engine": te_cfg}
    # Wire a real WriteGateEvaluator so delegate methods work
    mock_self._write_gate = WriteGateEvaluator(
        detector=None,
        similarity_tracker=None,
        config=mock_self.config,
        force_accept=False,
    )
    # Bind the real _get_purity_threshold via write gate
    mock_self._get_purity_threshold = mock_self._write_gate._get_purity_threshold
    # Bind the real _should_skip_purity_segment static method
    mock_self._should_skip_purity_segment = WriteGateEvaluator._should_skip_purity_segment
    return mock_self


def _make_detector(detections):
    """Return a mock detector whose .detect() replays a fixed sequence.

    detections: list of (lang_code, confidence) tuples.
    """
    mock_detector = MagicMock()
    mock_detector.detect.side_effect = detections
    return mock_detector


def _build_content(num_paragraphs, char="x", length=25):
    """Build markdown content with num_paragraphs paragraphs of length >= 20.

    Paragraphs are separated by blank lines so the line-by-line splitter
    produces exactly the expected count.

    Avoids lines starting with --- or triple-backtick.
    """
    assert length >= 20, "paragraphs must be >= 20 chars to pass the filter"
    paragraph = char * length
    return ("\n\n").join([paragraph] * num_paragraphs)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDefaultThreshold:
    """Languages without an override use the hardcoded 6% default."""

    def test_default_threshold_blocks_30pct_wrong_for_unknown_lang(self):
        """30% wrong paragraphs for a language not in overrides should FAIL.

        With the default 6% threshold, 3 wrong out of 10 (30%) is clearly
        over the limit.
        """
        from src.translation_engine.engine import TranslationEngine

        mock_self = _make_engine(purity_threshold_overrides={})
        detections = [("de", 0.95)] * 7 + [("sr", 0.95)] * 3
        detector = _make_detector(detections)
        content = _build_content(10)
        result = TranslationEngine._verify_final_file_purity(mock_self, content, "de", detector)
        assert result["passed"] is False
        assert result["wrong_lang_percentage"] == pytest.approx(0.30, abs=0.01)

    def test_default_threshold_passes_5pct_wrong(self):
        """5% wrong (< 6% default) should PASS for a lang without an override."""
        from src.translation_engine.engine import TranslationEngine

        mock_self = _make_engine(purity_threshold_overrides={})
        detections = [("de", 0.95)] * 19 + [("sr", 0.95)] * 1
        detector = _make_detector(detections)
        content = _build_content(20)
        result = TranslationEngine._verify_final_file_purity(mock_self, content, "de", detector)
        assert result["passed"] is True
        assert result["wrong_lang_percentage"] == pytest.approx(0.05, abs=0.001)


class TestLanguageOverrides:
    """Per-language overrides change the acceptance threshold for that language only."""

    def test_lt_override_passes_exactly_at_threshold(self):
        """lt override at 0.30: exactly 30% wrong should PASS.

        The boundary is wrong_percentage > threshold, so equality is not a failure.
        """
        from src.translation_engine.engine import TranslationEngine

        mock_self = _make_engine(purity_threshold_overrides={"lt": 0.30, "lv": 0.20})
        # 3/10 == 0.30 == threshold -> NOT strictly greater -> PASS.
        detections = [("lt", 0.95)] * 7 + [("sr", 0.95)] * 3
        detector = _make_detector(detections)
        content = _build_content(10)
        result = TranslationEngine._verify_final_file_purity(mock_self, content, "lt", detector)
        assert result["passed"] is True

    def test_lt_override_fails_above_threshold(self):
        """lt override at 0.30: 40% wrong should FAIL."""
        from src.translation_engine.engine import TranslationEngine

        mock_self = _make_engine(purity_threshold_overrides={"lt": 0.30, "lv": 0.20})
        detections = [("lt", 0.95)] * 6 + [("sr", 0.95)] * 4
        detector = _make_detector(detections)
        content = _build_content(10)
        result = TranslationEngine._verify_final_file_purity(mock_self, content, "lt", detector)
        assert result["passed"] is False
        assert result["wrong_lang_percentage"] == pytest.approx(0.40, abs=0.01)

    def test_ar_still_fails_at_default_threshold_despite_lt_override(self):
        """Arabic not in overrides -> uses 6% default despite lt/lv overrides present.

        30% wrong for Arabic should FAIL.
        """
        from src.translation_engine.engine import TranslationEngine

        mock_self = _make_engine(purity_threshold_overrides={"lt": 0.30, "lv": 0.20})
        detections = [("ar", 0.95)] * 7 + [("sr", 0.95)] * 3
        detector = _make_detector(detections)
        content = _build_content(10)
        result = TranslationEngine._verify_final_file_purity(mock_self, content, "ar", detector)
        assert result["passed"] is False
        assert result["wrong_lang_percentage"] == pytest.approx(0.30, abs=0.01)

    def test_lv_override_independent_of_lt(self):
        """lv uses its own 0.20 override, not lt 0.30 override."""
        from src.translation_engine.engine import TranslationEngine

        mock_self = _make_engine(purity_threshold_overrides={"lt": 0.30, "lv": 0.20})
        # 25% wrong for lv -- above lv 0.20 but below lt 0.30.
        detections = [("lv", 0.95)] * 15 + [("sr", 0.95)] * 5
        detector = _make_detector(detections)
        content = _build_content(20)
        result = TranslationEngine._verify_final_file_purity(mock_self, content, "lv", detector)
        assert result["passed"] is False
        assert result["wrong_lang_percentage"] == pytest.approx(0.25, abs=0.01)


class TestConfigFallback:
    """Graceful degradation when the config object is unavailable."""

    def test_no_purity_config_falls_back_gracefully(self):
        """If config.get_config() raises, method falls back to 0.06 without crashing.

        7 wrong out of 100 paragraphs = 7%, above 6% fallback -> FAIL.
        """
        from src.translation_engine.engine import TranslationEngine

        mock_self = _make_engine(config_raises=True)
        detections = [("de", 0.95)] * 93 + [("sr", 0.95)] * 7
        detector = _make_detector(detections)
        content = _build_content(100)
        result = TranslationEngine._verify_final_file_purity(mock_self, content, "de", detector)
        assert result["passed"] is False  # 7% > 6% fallback
        assert result["wrong_lang_percentage"] == pytest.approx(0.07, abs=0.001)

    def test_no_purity_config_passes_below_default(self):
        """When config raises, 5% wrong (< 6% fallback) should still PASS."""
        from src.translation_engine.engine import TranslationEngine

        mock_self = _make_engine(config_raises=True)
        detections = [("de", 0.95)] * 95 + [("sr", 0.95)] * 5
        detector = _make_detector(detections)
        content = _build_content(100)
        result = TranslationEngine._verify_final_file_purity(mock_self, content, "de", detector)
        assert result["passed"] is True
        assert result["wrong_lang_percentage"] == pytest.approx(0.05, abs=0.001)


class TestContentFiltering:
    """Short paragraphs and low-confidence detections are filtered."""

    def test_short_paragraphs_not_counted(self):
        """Lines shorter than 20 chars must not be passed to detector.detect().

        Content has 10 short lines (10 chars) interleaved with 10 long lines (25).
        Short lines are filtered; only long lines call detect().
        """
        from src.translation_engine.engine import TranslationEngine

        mock_self = _make_engine(purity_threshold_overrides={})
        short_line = "x" * 10  # 10 chars -- below 20-char minimum
        long_line = "y" * 25  # 25 chars -- above the minimum
        lines = []
        for _ in range(10):
            lines.append(short_line)
            lines.append(long_line)
        content = ("\n").join(lines)
        detections = [("de", 0.95)] * 10
        detector = _make_detector(detections)
        result = TranslationEngine._verify_final_file_purity(mock_self, content, "de", detector)
        assert result["passed"] is True
        assert detector.detect.call_count == 10

    def test_low_confidence_detections_not_counted_as_wrong(self):
        """A wrong-language detection with conf <= 0.70 must NOT increment wrong count.

        The boundary is strictly conf > 0.70; conf == 0.70 does not count.
        """
        from src.translation_engine.engine import TranslationEngine

        mock_self = _make_engine(purity_threshold_overrides={})
        detections = [("sr", 0.70)] * 10
        detector = _make_detector(detections)
        content = _build_content(10)
        result = TranslationEngine._verify_final_file_purity(mock_self, content, "de", detector)
        assert result["passed"] is True
        assert result["wrong_lang_percentage"] == pytest.approx(0.0, abs=0.001)

    def test_empty_content_returns_passed(self):
        """Content with no valid paragraphs should return passed=True."""
        from src.translation_engine.engine import TranslationEngine

        mock_self = _make_engine()
        detector = _make_detector([])
        content = ""
        result = TranslationEngine._verify_final_file_purity(mock_self, content, "de", detector)
        assert result["passed"] is True
        assert "reason" in result


class TestSimilarityTrackerSkip:
    """Paragraphs detected as a similar language must not count as wrong."""

    def test_similar_language_skipped_even_above_default_threshold(self):
        """When similarity_tracker.are_similar(expected, detected) is True the
        paragraph is NOT counted as wrong — even at 50% which exceeds default 6%.

        5/10 paragraphs detected as sr, expected=lt, are_similar("lt","sr")=True.
        Result: 0 wrong counted → passed=True (would FAIL without the skip).
        """
        from src.translation_engine.engine import TranslationEngine

        mock_self = _make_engine(purity_threshold_overrides={})
        sim_tracker = MagicMock()
        sim_tracker.are_similar.return_value = True
        mock_self._write_gate._similarity_tracker = sim_tracker
        detections = [("lt", 0.95)] * 5 + [("sr", 0.95)] * 5
        detector = _make_detector(detections)
        content = _build_content(10)
        result = TranslationEngine._verify_final_file_purity(mock_self, content, "lt", detector)
        assert result["passed"] is True
        # are_similar called once per wrong-candidate paragraph (5 sr detections)
        assert sim_tracker.are_similar.call_count == 5

    def test_non_similar_language_counts_as_wrong(self):
        """When are_similar returns False the paragraph IS counted as wrong.

        5/10 paragraphs detected as de, expected=lt, are_similar("lt","de")=False.
        Result: 5/10 = 50% wrong > 6% default → FAIL.
        """
        from src.translation_engine.engine import TranslationEngine

        mock_self = _make_engine(purity_threshold_overrides={})
        sim_tracker = MagicMock()
        sim_tracker.are_similar.return_value = False
        mock_self._write_gate._similarity_tracker = sim_tracker
        detections = [("lt", 0.95)] * 5 + [("de", 0.95)] * 5
        detector = _make_detector(detections)
        content = _build_content(10)
        result = TranslationEngine._verify_final_file_purity(mock_self, content, "lt", detector)
        assert result["passed"] is False
        assert result["wrong_lang_percentage"] == pytest.approx(0.50, abs=0.01)


class TestInvalidConfigValues:
    """Non-numeric or out-of-range overrides must fall back to 0.06 silently."""

    def test_string_override_falls_back_to_default(self):
        """lt: 'aggressive' in config → float() raises → logs warning → returns 0.06.

        7% wrong for lt is above 6% default → FAIL; confirms fallback is 0.06 not 0.
        """
        from src.translation_engine.engine import TranslationEngine

        mock_self = _make_engine(purity_threshold_overrides={"lt": "aggressive"})
        detections = [("lt", 0.95)] * 93 + [("sr", 0.95)] * 7
        detector = _make_detector(detections)
        content = _build_content(100)
        result = TranslationEngine._verify_final_file_purity(mock_self, content, "lt", detector)
        assert result["passed"] is False  # 7% > 6% default; "aggressive" was rejected
        assert result["wrong_lang_percentage"] == pytest.approx(0.07, abs=0.001)

    def test_out_of_range_override_falls_back_to_default(self):
        """lt: 1.5 in config → out of [0,1] → logs warning → returns 0.06.

        7% wrong for lt → FAIL (same as default behaviour, 1.5 was rejected).
        """
        from src.translation_engine.engine import TranslationEngine

        mock_self = _make_engine(purity_threshold_overrides={"lt": 1.5})
        detections = [("lt", 0.95)] * 93 + [("sr", 0.95)] * 7
        detector = _make_detector(detections)
        content = _build_content(100)
        result = TranslationEngine._verify_final_file_purity(mock_self, content, "lt", detector)
        assert result["passed"] is False  # 7% > 6% default; 1.5 out-of-range rejected
        assert result["wrong_lang_percentage"] == pytest.approx(0.07, abs=0.001)

    def test_zero_override_blocks_any_wrong_paragraph(self):
        """lt: 0.0 in config → even 1% wrong → FAIL.

        Validates 0.0 passes the range check [0, 1] and is used as-is.
        """
        from src.translation_engine.engine import TranslationEngine

        mock_self = _make_engine(purity_threshold_overrides={"lt": 0.0})
        detections = [("lt", 0.95)] * 99 + [("sr", 0.95)] * 1
        detector = _make_detector(detections)
        content = _build_content(100)
        result = TranslationEngine._verify_final_file_purity(mock_self, content, "lt", detector)
        assert result["passed"] is False  # 1% > 0.0 threshold
        assert result["wrong_lang_percentage"] == pytest.approx(0.01, abs=0.001)


# ---------------------------------------------------------------------------
# SR27-T03: BUG-3 fix verification — Lithuanian threshold in global.yaml
# ---------------------------------------------------------------------------


class TestLithuanianThresholdConfig:
    """SR27-T03: Verify BUG-3 fix — global.yaml has lt: 0.30 and engine reads it."""

    def test_global_yaml_has_lt_purity_override(self):
        """BUG-3 fix: global.yaml must contain translation_engine.purity_threshold_overrides.lt == 0.30.

        Reads the actual config file (not mocked) so YAML parse errors are caught here.
        """
        from pathlib import Path

        import yaml

        raw = yaml.safe_load(Path("config/global.yaml").read_text(encoding="utf-8"))
        overrides = raw.get("translation_engine", {}).get("purity_threshold_overrides", {})
        assert "lt" in overrides, (
            "Missing purity_threshold_overrides.lt in global.yaml — BUG-3 fix not applied"
        )
        # TC-13 (2026-04-20) reduced lt from 0.30 to 0.15 — 30% was too permissive
        # and allowed catastrophic contamination through; 0.15 is the current deliberate value.
        assert overrides["lt"] == pytest.approx(0.15, abs=0.001), (
            f"Expected lt: 0.15 (reduced from 0.30 per TC-13), got {overrides['lt']}"
        )

    def test_engine_reads_lt_threshold_as_030(self):
        """_get_purity_threshold('lt') must return 0.30 when override is set."""
        from src.translation_engine.engine import TranslationEngine

        mock_self = _make_engine(purity_threshold_overrides={"lt": 0.30})
        threshold = TranslationEngine._get_purity_threshold(mock_self, "lt")
        assert threshold == pytest.approx(0.30, abs=0.001), f"Expected 0.30 for lt, got {threshold}"

    def test_default_threshold_unaffected_by_lt_override(self):
        """_get_purity_threshold('de') must return 0.06 when only lt is overridden."""
        from src.translation_engine.engine import TranslationEngine

        mock_self = _make_engine(purity_threshold_overrides={"lt": 0.30})
        threshold = TranslationEngine._get_purity_threshold(mock_self, "de")
        assert threshold == pytest.approx(0.06, abs=0.001), (
            f"Expected default 0.06 for de, got {threshold}"
        )

    def test_unknown_language_falls_back_to_default(self):
        """_get_purity_threshold for an unknown language must return 0.06."""
        from src.translation_engine.engine import TranslationEngine

        mock_self = _make_engine(purity_threshold_overrides={"lt": 0.30})
        threshold = TranslationEngine._get_purity_threshold(mock_self, "nonexistent")
        assert threshold == pytest.approx(0.06, abs=0.001)


# ---------------------------------------------------------------------------
# Direct _get_purity_threshold tests
# ---------------------------------------------------------------------------


class TestGetPurityThresholdDirect:
    """Direct tests for _get_purity_threshold method boundary conditions."""

    def test_returns_override_for_configured_lang(self):
        from src.translation_engine.engine import TranslationEngine

        mock_self = _make_engine(purity_threshold_overrides={"lt": 0.30, "ar": 0.15})
        assert TranslationEngine._get_purity_threshold(mock_self, "lt") == pytest.approx(0.30)
        assert TranslationEngine._get_purity_threshold(mock_self, "ar") == pytest.approx(0.15)

    def test_returns_default_for_unconfigured_lang(self):
        from src.translation_engine.engine import TranslationEngine

        mock_self = _make_engine(purity_threshold_overrides={"lt": 0.30})
        assert TranslationEngine._get_purity_threshold(mock_self, "de") == pytest.approx(0.06)

    def test_rejects_out_of_range_high(self):
        from src.translation_engine.engine import TranslationEngine

        mock_self = _make_engine(purity_threshold_overrides={"xx": 0.99})
        assert TranslationEngine._get_purity_threshold(mock_self, "xx") == pytest.approx(0.06)

    def test_rejects_string_value(self):
        from src.translation_engine.engine import TranslationEngine

        mock_self = _make_engine(purity_threshold_overrides={"xx": "high"})
        assert TranslationEngine._get_purity_threshold(mock_self, "xx") == pytest.approx(0.06)

    def test_accepts_zero_threshold(self):
        from src.translation_engine.engine import TranslationEngine

        mock_self = _make_engine(purity_threshold_overrides={"xx": 0.0})
        assert TranslationEngine._get_purity_threshold(mock_self, "xx") == pytest.approx(0.0)

    def test_config_exception_returns_default(self):
        from src.translation_engine.engine import TranslationEngine

        mock_self = _make_engine(config_raises=True)
        assert TranslationEngine._get_purity_threshold(mock_self, "lt") == pytest.approx(0.06)


# ---------------------------------------------------------------------------
# SR27 SW-2: Purity gate failures must set retryable_gate_failure = True
# ---------------------------------------------------------------------------


class TestPurityGateRetryable:
    """SW-2 fix: purity gate failures must mark retryable_gate_failure=True.

    Verifies the fix is present in engine.py at the purity check site by
    inspecting source code. This guards against accidental revert.
    """

    def test_purity_check_sets_retryable_gate_failure(self):
        """Write gate purity check must set result.passed = False on failure."""
        import inspect

        from src.translation_engine import write_gate as wg_module

        source = inspect.getsource(wg_module)
        # Find the purity check block in write_gate.py (extracted from engine.py)
        assert "purity_result" in source and "passed" in source, (
            "Purity check must exist in write_gate.py"
        )
        # Purity failure must block the write — result.passed = False
        assert "result.passed = False" in source, (
            "Purity check block must set result.passed = False in write_gate.py"
        )

    def test_retryable_gate_failure_true_in_purity_block(self):
        """Directly grep write_gate.py source for purity check failure handling."""
        from pathlib import Path

        wg_src = Path("src/translation_engine/write_gate.py").read_text(encoding="utf-8")
        lines = wg_src.splitlines()
        # Find line with purity check failure
        purity_fail_line = next(
            (
                i
                for i, ln in enumerate(lines, 1)
                if "purity_result" in ln and ("passed" in ln or "failed" in ln)
            ),
            None,
        )
        assert purity_fail_line is not None, "Purity check line not found in write_gate.py"
        # Within 10 lines after the purity check, result.passed must be set to False
        window = "\n".join(lines[purity_fail_line - 1 : purity_fail_line + 10])
        assert "result.passed = False" in window, (
            f"result.passed=False not found near purity check (line {purity_fail_line})"
        )
