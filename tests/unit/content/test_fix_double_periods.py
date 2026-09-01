"""TC-P7-04 acceptance: unit tests for scripts/content/fix_double_periods.py.

The critical property under test: unlike Gate 12's own unprotected regex
(confirmed root cause of most link_path_corrupted findings), this fixer
must NEVER collapse ".." inside a markdown link target.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_CONTENT_DIR = Path(__file__).resolve().parents[3] / "scripts" / "content"
if str(_SCRIPTS_CONTENT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_CONTENT_DIR))

from fix_double_periods import fix_double_periods_in_body, fix_file  # noqa: E402


def test_collapses_double_period_in_prose():
    body, changed = fix_double_periods_in_body("Eine Zeile mit Fehler.. Ende.")
    assert changed is True
    assert body == "Eine Zeile mit Fehler. Ende."


def test_leaves_ellipsis_untouched():
    body, changed = fix_double_periods_in_body("Warten Sie... bitte.")
    assert changed is False
    assert body == "Warten Sie... bitte."


def test_ignores_code_fences():
    text = "```python\nx = a..b\n```\nEnde."
    body, changed = fix_double_periods_in_body(text)
    assert changed is False
    assert body == text


def test_protects_markdown_link_targets_the_critical_regression_guard():
    # This is exactly the confirmed root-cause-1 corruption pattern: Gate 12's
    # unprotected regex turned "../developer-guide/" into "./developer-guide/"
    # because it doesn't distinguish a link target's ".." from prose "..".
    # A DOUBLE_PERIOD match inside a link target must be left alone.
    text = "[Guide](../developer-guide/) und Text mit Fehler.. Ende."
    body, changed = fix_double_periods_in_body(text)
    assert changed is True
    assert "[Guide](../developer-guide/)" in body  # link untouched
    assert "Fehler. Ende." in body  # prose still fixed


def test_protects_link_target_with_multiple_dotdot_segments():
    text = "[X](../../developer-guide/)"
    body, changed = fix_double_periods_in_body(text)
    assert changed is False
    assert body == text


def test_fix_file_is_idempotent(tmp_path):
    tr = tmp_path / "tr.md"
    tr.write_text("---\ntitle: X\n---\nFehler.. Ende.\n", encoding="utf-8")

    outcome1 = fix_file(tr, write=True)
    assert outcome1.changed is True
    fixed = tr.read_text(encoding="utf-8")
    assert "Fehler. Ende." in fixed

    outcome2 = fix_file(tr, write=True)
    assert outcome2.changed is False
    assert tr.read_text(encoding="utf-8") == fixed  # unchanged by the no-op


def test_fix_file_dry_run_does_not_write(tmp_path):
    tr = tmp_path / "tr.md"
    original = "---\ntitle: X\n---\nFehler.. Ende.\n"
    tr.write_text(original, encoding="utf-8")

    outcome = fix_file(tr, write=False)

    assert outcome.changed is True
    assert tr.read_text(encoding="utf-8") == original
