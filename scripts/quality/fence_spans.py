"""Fence-aware line segmentation for scripts/quality repair functions.

TC-HT-002: line-level repairs (artifact/shortcode/EU-hallucination cleanup)
previously operated blindly over the raw body with regex, which could
delete or mangle lines *inside* fenced code blocks (e.g. example code that
legitimately contains a shortcode-like string). This module segments a
markdown body into contiguous fenced/unfenced line runs using the real
markdown-it tokenizer (the same parser HugoParser wraps) so repairs can be
scoped to unfenced prose only, leaving fenced regions untouched.
"""
from __future__ import annotations

from markdown_it import MarkdownIt

_md = MarkdownIt("commonmark")


def fenced_line_mask(body: str) -> list[bool]:
    """Return one bool per physical line of ``body``: True if inside a fenced code block."""
    lines = body.splitlines()
    mask = [False] * len(lines)
    tokens = _md.parse(body)
    for tok in tokens:
        if tok.type == "fence" and tok.map:
            start, end = tok.map
            for i in range(max(start, 0), min(end, len(mask))):
                mask[i] = True
    return mask


def split_fenced_segments(body: str) -> list[tuple[bool, list[str]]]:
    """Group body lines (with line endings preserved) into contiguous
    ``(is_fenced, lines)`` runs, in original order.
    """
    lines = body.splitlines(keepends=True)
    mask = fenced_line_mask(body)
    # splitlines(keepends=True) and splitlines() can disagree by one entry
    # only when body ends without a trailing newline; mask is built from the
    # non-keepends split, so pad/truncate defensively to stay in lockstep.
    if len(mask) < len(lines):
        mask = mask + [mask[-1] if mask else False] * (len(lines) - len(mask))
    elif len(mask) > len(lines):
        mask = mask[: len(lines)]

    segments: list[tuple[bool, list[str]]] = []
    cur_flag: bool | None = None
    cur: list[str] = []
    for line, flag in zip(lines, mask):
        if flag != cur_flag and cur:
            segments.append((bool(cur_flag), cur))
            cur = []
        cur_flag = flag
        cur.append(line)
    if cur:
        segments.append((bool(cur_flag), cur))
    return segments
