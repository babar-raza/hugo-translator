"""HT-INLINE-CODE-001 TC-ICR-008: unit_heal.py's _retranslate_unit() gains
a no-model structural-fix branch for inline_code_integrity_detector,
matching the existing mojibake_detector/duplicate_run_detector/
link_path_detector branches (all no-LLM/MT-call structural fixes).
"""
from __future__ import annotations

from scripts.quality.unit_heal import _retranslate_unit


def test_inline_code_corruption_is_fixed_without_a_model_call():
    en = "Use `equals`, `close`, and `create` here."
    original_tr = "Utilisez `identité`, `close`, et `create` ici."
    fixed = _retranslate_unit(
        en_text=en,
        original_tr=original_tr,
        locale="fr",
        site_id="reference.aspose.org",
        issue_type="inline_code_integrity_detector",
    )
    assert fixed == "Utilisez `equals`, `close`, et `create` ici."


def test_clean_unit_returns_none_no_op():
    en = "Use `equals`, `close`, and `create` here."
    original_tr = "Utilisez `equals`, `close`, et `create` ici."
    fixed = _retranslate_unit(
        en_text=en,
        original_tr=original_tr,
        locale="fr",
        site_id="reference.aspose.org",
        issue_type="inline_code_integrity_detector",
    )
    assert fixed is None


def test_span_count_mismatch_returns_none_not_a_guess():
    en = "Use `create`, `close`, and `equals` here."
    original_tr = "Utilisez `create`, `equals`, et `extra` ici."
    fixed = _retranslate_unit(
        en_text=en,
        original_tr=original_tr,
        locale="fr",
        site_id="reference.aspose.org",
        issue_type="inline_code_integrity_detector",
    )
    assert fixed is None


def test_other_issue_types_unaffected():
    """Regression guard: adding this branch must not change dispatch for
    any pre-existing issue type."""
    fixed = _retranslate_unit(
        en_text="Some English text.",
        original_tr="â€™ mojibake here",
        locale="fr",
        site_id="reference.aspose.org",
        issue_type="mojibake_detector",
    )
    assert fixed is not None
    assert "â€™" not in fixed
