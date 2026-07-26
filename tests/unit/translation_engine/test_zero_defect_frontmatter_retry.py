"""Regression coverage for governed frontmatter retry routing."""

from types import SimpleNamespace

from src.translation_engine.segment_translator import (
    _retry_original_frontmatter_value,
    _strict_frontmatter_retry_model_id,
)


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


def test_strict_retry_uses_only_the_pinned_profile_field_override():
    engine = SimpleNamespace(
        validation_policy="zero-defect",
        config=SimpleNamespace(
            get_config=lambda: {
                "translation_engine": {
                    "zero_defect_frontmatter_retry_models": {
                        "blog.aspose.org": {"seoTitle": "nllb_200_1.3b"}
                    }
                }
            }
        ),
    )
    assert (
        _strict_frontmatter_retry_model_id(
            engine, "blog.aspose.org", "seoTitle", "m2m100_418m", "retry"
        )
        == "nllb_200_1.3b"
    )
    assert (
        _strict_frontmatter_retry_model_id(
            engine, "blog.aspose.org", "title", "m2m100_418m", "retry"
        )
        == "m2m100_418m"
    )
