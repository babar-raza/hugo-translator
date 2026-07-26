"""Regression coverage for governed frontmatter retry routing."""

from src.translation_engine.segment_translator import _retry_original_frontmatter_value


def test_zero_defect_retry_uses_immutable_frontmatter_value_after_failure():
    assert _retry_original_frontmatter_value(
        "m2m100_418m", "language_detection failed", "zero-defect"
    )


def test_initial_primary_attempt_keeps_placeholder_protection():
    assert not _retry_original_frontmatter_value("m2m100_418m", None, "zero-defect")


def test_llm_escalation_always_uses_original_frontmatter_value():
    assert _retry_original_frontmatter_value("professionalize_llm", None, "zero-defect")


def test_legacy_placement_invariant_is_not_authoritative_on_strict_retry():
    assert _retry_original_frontmatter_value(
        "m2m100_418m", "frontmatter language failure", "zero-defect"
    )
