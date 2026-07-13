"""Tests for repair_mojibake() function — TC-HDN-001."""
import pytest
from src.model_runtime.loader import repair_mojibake


class TestRepairMojibake:
    """Unit tests for repair_mojibake()."""

    def test_em_dash(self):
        assert repair_mojibake("Hello \u00e2\u20ac\u2014 world") == "Hello \u2014 world"

    def test_en_dash(self):
        assert repair_mojibake("pages 1\u00e2\u20ac\u20132") == "pages 1\u20132"

    def test_right_single_quote(self):
        assert repair_mojibake("it\u00e2\u20ac\u2122s fine") == "it\u2019s fine"

    def test_left_double_quote(self):
        result = repair_mojibake("\u00e2\u20ac\u0153Hello\u00e2\u20ac\u009d")
        assert result == "\u201cHello\u201d"

    def test_e_acute(self):
        assert repair_mojibake("caf\u00c3\u00a9") == "caf\u00e9"

    def test_e_grave(self):
        assert repair_mojibake("pr\u00c3\u00a8s") == "pr\u00e8s"

    def test_u_umlaut(self):
        assert repair_mojibake("\u00c3\u00bcber") == "\u00fcber"

    def test_o_umlaut(self):
        assert repair_mojibake("sch\u00c3\u00b6n") == "sch\u00f6n"

    def test_clean_text_unchanged(self):
        # Ukrainian clean text — must not be altered
        text = "\u041f\u0440\u0438\u0432\u0456\u0442 \u0441\u0432\u0456\u0442\u0435"
        assert repair_mojibake(text) == text

    def test_clean_arabic_unchanged(self):
        text = "\u0645\u0631\u062d\u0628\u0627 \u0628\u0627\u0644\u0639\u0627\u0644\u0645"
        assert repair_mojibake(text) == text

    def test_clean_japanese_unchanged(self):
        text = "\u3053\u3093\u306b\u3061\u306f\u4e16\u754c"
        assert repair_mojibake(text) == text

    def test_empty_string(self):
        assert repair_mojibake("") == ""

    def test_no_mojibake(self):
        text = "Clean ASCII text with no corruption."
        assert repair_mojibake(text) == text

    def test_multiple_patterns_same_string(self):
        text = "dash\u00e2\u20ac\u2014and\u00c3\u00a9"
        assert repair_mojibake(text) == "dash\u2014and\u00e9"

    def test_ellipsis(self):
        assert repair_mojibake("wait\u00e2\u20ac\u00a6") == "wait\u2026"
