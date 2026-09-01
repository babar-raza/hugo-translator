"""HT-INLINE-CODE-001 TC-ICR-004: audit_all_content.py's
check_inline_code_translated() delegates to the shared
inline_code_repair primitive instead of its own naive regex.
"""
from __future__ import annotations

from scripts.quality.audit_all_content import check_inline_code_translated


def test_detects_real_corruption():
    en = "Use `equals`, `close`, and `create` here."
    tr = "Utilisez `identité`, `close`, et `create` ici."
    has_issue, detail = check_inline_code_translated(en, tr)
    assert has_issue is True
    assert "equals" in detail


def test_clean_translation_not_flagged():
    en = "Use `equals`, `close`, and `create` here."
    tr = "Utilisez `equals`, `close`, et `create` ici."
    has_issue, _ = check_inline_code_translated(en, tr)
    assert has_issue is False


def test_stray_table_backtick_does_not_produce_a_false_positive():
    """The exact failure mode confirmed against the real Phase 7 audit
    JSONL: a stray unpaired backtick before a table row swallowing the
    next paragraph across a line break, mispairing spans from that point
    on. The shared primitive's newline exclusion + count guard closes it."""
    en = (
        "The `AssetInfo` class has `GetName` and `SetName` methods.\n\n"
        "| Col |\n| --- |\n| data |\n"
    )
    tr = (
        "La classe `AssetInfo` a des méthodes `GetName` et `SetName`.\n\n"
        "` | Данные |\n| --- |\n| données |\n"
    )
    has_issue, _ = check_inline_code_translated(en, tr)
    assert has_issue is False


def test_span_count_mismatch_not_flagged_as_a_confirmed_hit():
    en = "Use `create`, `close`, and `equals` here."
    tr = "Utilisez `create`, `equals`, et `extra` ici."  # dropped + added a span
    has_issue, _ = check_inline_code_translated(en, tr)
    assert has_issue is False
