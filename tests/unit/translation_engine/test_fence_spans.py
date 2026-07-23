"""HT-QUALITY-GATES-001 Phase 8 (F2): tests for the canonical fence-span
primitive (src/translation_engine/fence_spans.py) shared between write_gate.py
and scripts/quality's repair functions.
"""
from __future__ import annotations

from src.translation_engine.fence_spans import (
    count_fence_open_reopens,
    get_fence_char_spans,
    is_in_fence,
    strip_fenced,
)


def test_get_fence_char_spans_single_block():
    text = "before\n\n```python\ncode line\n```\n\nafter"
    spans = get_fence_char_spans(text)
    assert len(spans) == 1
    start, end = spans[0]
    assert text[start:end].startswith("```python")
    assert text[start:end].rstrip("\n").endswith("```")


def test_get_fence_char_spans_no_fence():
    assert get_fence_char_spans("just prose, no code here") == []


def test_is_in_fence_true_and_false():
    text = "prose\n```\ncode\n```\nmore prose"
    spans = get_fence_char_spans(text)
    fence_pos = text.index("code")
    prose_pos = text.index("more prose")
    assert is_in_fence(fence_pos, spans) is True
    assert is_in_fence(prose_pos, spans) is False


def test_strip_fenced_removes_code_keeps_prose():
    text = "keep this\n```\ndrop this\n```\nand keep this too"
    stripped = strip_fenced(text)
    assert "drop this" not in stripped
    assert "keep this" in stripped
    assert "keep this too" in stripped


def test_count_fence_open_reopens_well_formed_is_zero():
    text = "```python\ndef foo():\n    pass\n```\n\n```python\ndef bar():\n    pass\n```"
    assert count_fence_open_reopens(text) == 0


def test_count_fence_open_reopens_empty_block_is_zero():
    # An empty fenced block (open immediately followed by close) is legitimate
    # markdown, not a reopen -- must not false-positive.
    text = "```python\n```"
    assert count_fence_open_reopens(text) == 0


def test_count_fence_open_reopens_detects_duplicated_header():
    # The LLM emitted a second "```python" opener mid-snippet instead of a
    # real closing fence -- markdown-it correctly keeps the first fence open
    # and swallows the duplicate opener as content, which is exactly the
    # corruption signature this function targets.
    text = (
        "```python\n"
        "def foo():\n"
        "    pass\n"
        "```python\n"
        "def bar():\n"
        "    pass\n"
        "```\n"
    )
    assert count_fence_open_reopens(text) == 1


def test_count_fence_open_reopens_multiple_files_independent():
    text_a = "```\ncode a\n```"
    text_b = "```\ncode b\n```python\nmore\n```"
    assert count_fence_open_reopens(text_a) == 0
    assert count_fence_open_reopens(text_b) == 1
