import pytest

from src.translation_engine.engine import _frontmatter_script_metrics


def test_hindi_frontmatter_script_metrics_are_payload_free():
    metrics = _frontmatter_script_metrics(
        "यह हिंदी विवरण है with Aspose.Cells XLSX",
        "hi",
    )

    assert metrics["letter_count"] > 0
    assert 0.0 < metrics["target_script_ratio"] < 1.0
    assert 0.0 < metrics["latin_letter_ratio"] < 1.0
    assert sum(
        (
            metrics["target_script_ratio"],
            metrics["latin_letter_ratio"],
        )
    ) == pytest.approx(1.0)


def test_untranslated_hindi_frontmatter_has_zero_target_script_ratio():
    metrics = _frontmatter_script_metrics(
        "English spreadsheet description with technical terms",
        "hi",
    )

    assert metrics["target_script_ratio"] == 0.0
    assert metrics["latin_letter_ratio"] == 1.0
