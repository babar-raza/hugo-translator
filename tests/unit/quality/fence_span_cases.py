"""Shared edge cases for every consumer of the canonical code-region mask."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CodeRegionCase:
    name: str
    body: str
    expected_mask: list[bool]


CODE_REGION_CASES = (
    CodeRegionCase(
        "tilde_fence",
        "prose\n~~~python\ncode\n~~~\nmore prose\n",
        [False, True, True, True, False],
    ),
    CodeRegionCase(
        "long_backtick_fence_with_nested_marker",
        "prose\n````python\ncode\n```\nstill code\n````\nmore prose\n",
        [False, True, True, True, True, True, False],
    ),
    CodeRegionCase(
        "unterminated_fence",
        "prose\n```python\ncode\nstill code\n",
        [False, True, True, True],
    ),
    CodeRegionCase(
        "indented_code_block",
        "prose\n\n    code\n    still code\n\nmore prose\n",
        [False, False, True, True, False, False],
    ),
    CodeRegionCase(
        "crlf_fence",
        "prose\r\n~~~\r\ncode\r\n~~~\r\nmore prose\r\n",
        [False, True, True, True, False],
    ),
)
