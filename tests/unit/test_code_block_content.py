"""TC-H1B: Code block content integrity validator tests.

Four cases:
  1. test_code_content_preserved — identical content → PASS
  2. test_code_content_corrupted — def foo(): pass → def foo(): bestaan → WARNING
  3. test_code_lang_tag_stripped — ```python → ``` → WARNING
  4. test_code_count_mismatch_keeps_tc_h1a_error — different count → ERROR (existing behavior)
"""
from __future__ import annotations

import pytest
from src.translation_engine.validation.structure_validator import StructureValidator


def _validator():
    return StructureValidator()


class TestCodeBlockContents:
    def test_code_content_preserved(self):
        """Identical fenced code block content → no warnings."""
        src = "```python\ndef foo():\n    pass\n```\n"
        tgt = "```python\ndef foo():\n    pass\n```\n"
        result = _validator().validate(src, tgt)
        warnings = [i for i in result.issues if i.severity.value == "warning"]
        assert not warnings, f"Expected no warnings for identical code block, got: {warnings}"

    def test_code_content_corrupted(self):
        """Content modification (def foo(): pass → def foo(): bestaan) → WARNING."""
        src = "Text\n```python\ndef foo():\n    pass\n```\nMore text\n"
        tgt = "Tekst\n```python\ndef foo():\n    bestaan\n```\nMeer tekst\n"
        result = _validator().validate(src, tgt)
        warnings = [i for i in result.issues if "content was modified" in i.message]
        assert warnings, "Expected WARNING for corrupted code block content"

    def test_code_lang_tag_stripped(self):
        """Language tag stripped (```python → ```) → WARNING."""
        src = "```python\nprint('hello')\n```\n"
        tgt = "```\nprint('hello')\n```\n"
        result = _validator().validate(src, tgt)
        warnings = [i for i in result.issues if "language tag changed" in i.message]
        assert warnings, "Expected WARNING for stripped language tag"

    def test_code_count_mismatch_blocks_tc_h1a(self):
        """Different fenced block count → ERROR (TC-H1A preserved)."""
        src = "```python\ncode1\n```\n\n```\ncode2\n```\n"
        tgt = "```python\ncode1\n```\n"
        result = _validator().validate(src, tgt)
        errors = [i for i in result.issues if i.severity.value == "error"]
        assert errors, "Expected ERROR for code block count mismatch (TC-H1A)"
        assert not result.success

    def test_no_false_positive_for_empty_lang_tag(self):
        """Empty lang tag in both source and target → no language tag warning."""
        src = "```\nsome code\n```\n"
        tgt = "```\nsome code\n```\n"
        result = _validator().validate(src, tgt)
        tag_warnings = [i for i in result.issues if "language tag" in i.message]
        assert not tag_warnings

    def test_content_check_skipped_on_count_mismatch(self):
        """Content check must not run when block count differs (avoids index errors)."""
        src = "```\nfoo\n```\n\n```\nbar\n```\n"
        tgt = "```\nfoo\n```\n"
        result = _validator().validate(src, tgt)
        content_warnings = [i for i in result.issues if "content was modified" in i.message]
        assert not content_warnings, "Content check must not fire when counts differ"
