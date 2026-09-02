"""TC-APT-009 (G-04) regression: gate 12 cleans prose double-dots and NOTHING else.

The audit-phase7 finding was a *symptom-only* fix: the cleaner rewrote ``..`` -> ``.`` in every
non-fenced segment, so it could silently corrupt legitimate content -- relative links, inline
code, Hugo shortcode parameters, HTML attributes, bare URLs, reference definitions. These tests
pin the corrected blast radius: prose is still cleaned, protected spans survive byte-for-byte.

Blast-radius measurement that motivated the fix (live scan of the content repo, 2026-09-02):
10 defective targets out of 112,584 existing targets (data/quality/gate12_double_period_scan.json).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.translation_engine.write_gate import WriteGateEvaluator, WriteGateResult


@pytest.fixture()
def clean():
    evaluator = WriteGateEvaluator.__new__(WriteGateEvaluator)  # no config needed for this gate

    def _run(source: str, translated: str) -> str:
        return evaluator._gate_double_periods(
            source, translated, Path("out/de/page.md"), WriteGateResult(passed=True)
        )

    return _run


def _doc(body: str) -> str:
    return f"---\ntitle: t\n---\n{body}\n"


def test_prose_double_dot_is_still_cleaned(clean):
    out = clean(_doc("The file is written."), _doc("Die Datei wird geschrieben.."))
    assert out == _doc("Die Datei wird geschrieben.")


def test_ellipsis_is_never_touched(clean):
    body = "Loading... please wait"
    assert clean(_doc("Loading... please wait"), _doc(body)) == _doc(body)


def test_relative_link_target_survives(clean):
    body = "See [the guide](../guide/index.md) and [api](../../api/x.md) for details.."
    out = clean(_doc("See [the guide](../guide/index.md) for details."), _doc(body))
    assert "](../guide/index.md)" in out and "](../../api/x.md)" in out
    assert out.rstrip().endswith("for details.")  # the prose dot pair was still fixed


def test_inline_code_span_survives(clean):
    body = "Use `range(0..5)` and `a..b` in the loop.."
    out = clean(_doc("Use `range(0..5)` in the loop."), _doc(body))
    assert "`range(0..5)`" in out and "`a..b`" in out
    assert out.rstrip().endswith("in the loop.")


def test_hugo_shortcode_parameter_survives(clean):
    body = '{{< include path="../shared/note.md" >}} Weiter..'
    out = clean(_doc('{{< include path="../shared/note.md" >}} Continue.'), _doc(body))
    assert '{{< include path="../shared/note.md" >}}' in out
    assert out.rstrip().endswith("Weiter.")


def test_html_attribute_and_bare_url_survive(clean):
    body = '<img src="../img/a.png" alt="x"> siehe https://example.com/a..b für mehr..'
    out = clean(_doc('<img src="../img/a.png" alt="x"> see https://example.com/a..b'), _doc(body))
    assert '<img src="../img/a.png" alt="x">' in out
    assert "https://example.com/a..b" in out
    assert out.rstrip().endswith("für mehr.")


def test_reference_style_link_definition_survives(clean):
    body = "Text..\n\n[ref]: ../other/page.md"
    out = clean(_doc("Text.\n\n[ref]: ../other/page.md"), _doc(body))
    assert "[ref]: ../other/page.md" in out
    assert "Text." in out and "Text.." not in out


def test_fenced_code_block_still_protected(clean):
    body = "Prosa..\n\n```python\npath = '../x'\nrange(0..5)\n```\n"
    out = clean(_doc("Prose.\n\n```python\npath = '../x'\nrange(0..5)\n```\n"), _doc(body))
    assert "path = '../x'" in out and "range(0..5)" in out
    assert "Prosa." in out and "Prosa.." not in out


def test_source_with_double_dot_disables_the_gate_entirely(clean):
    body = "Beliebiger Text.. mit `code..` und ../pfad"
    out = clean(_doc("Any text.. in the source"), _doc(body))
    assert out == _doc(body)  # unchanged: the historical safety bail-out is preserved


def test_no_change_returns_the_original_object(clean):
    doc = _doc("Nothing to fix here.")
    assert clean(_doc("Nothing to fix here."), doc) == doc
