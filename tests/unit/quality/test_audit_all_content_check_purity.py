"""Regression coverage for the fence-aware purity audit (TC-DCF-012)."""
from __future__ import annotations

import pytest

from scripts.quality.audit_all_content import check_purity

_ARABIC_PROSE = "هذه فقرة مترجمة طويلة بما يكفي لكي تعد محتوى عاديا وليست شيفرة برمجية."
_ENGLISH_PROSE = (
    "This is an untranslated English prose paragraph with enough ordinary words "
    "to be counted by the purity audit as a real language defect."
)


@pytest.mark.parametrize(
    "code_block",
    [
        "~~~python\n" + _ENGLISH_PROSE + "\n~~~",
        "````python\n" + _ENGLISH_PROSE + "\n```\nstill code\n````",
        "```python\n" + _ENGLISH_PROSE,
        "    " + _ENGLISH_PROSE,
    ],
    ids=["tilde", "long-backtick", "unterminated", "indented"],
)
def test_code_regions_do_not_count_as_english_purity_paragraphs(code_block):
    issue, ratio = check_purity(_ARABIC_PROSE + "\n\n" + code_block, "ar")
    assert (issue, ratio) == (False, 0.0)


def test_real_english_prose_directly_adjacent_to_code_remains_detectable():
    """A closing fence must not swallow immediately following prose."""
    body = _ARABIC_PROSE + "\n\n~~~~\nignored code\n~~~~\n" + _ENGLISH_PROSE
    issue, ratio = check_purity(body, "ar")
    assert issue is True
    assert ratio == pytest.approx(0.5)


def test_crlf_paragraphs_and_fences_keep_the_same_purity_result():
    body = _ARABIC_PROSE + "\r\n\r\n~~~\r\n" + _ENGLISH_PROSE + "\r\n~~~\r\n\r\n" + _ENGLISH_PROSE
    issue, ratio = check_purity(body, "ar")
    assert issue is True
    assert ratio == pytest.approx(0.5)
