"""Fence-aware segmentation, shared across write_gate.py and scripts/quality.

HT-QUALITY-GATES-001 Phase 8 (F2): every fence-boundary-aware check in this
codebase used to re-derive "is this content inside a fenced code block"
independently -- a naive ```` toggle in hugo_parser.py's
normalize_table_cells(), a DOTALL regex in write_gate.py, a manual
line-by-line loop in several individual gates, and yet another DOTALL regex
in scripts/quality/audit_all_content.py. None of these share code, and the
naive toggle in particular has no way to detect two consecutive fence-open
markers with no close between them (a genuine corruption shape -- see Gate
26's reopened-fence extension).

This module is the single canonical fence-boundary primitive, backed by the
real markdown-it tokenizer (the same parser HugoParser wraps), so it
respects CommonMark fence-matching rules (fence length, indentation,
character ```` vs ~~~~) instead of a regex approximation. New gates should
use it; existing gates are not retrofitted in this pass (see HT-QUALITY-
GATES-001 Phase 8 plan, "what should be preserved" -- avoid destabilizing
35 already-tested gates for a non-correctness-bearing refactor).

scripts/quality/fence_spans.py re-exports this module's line-oriented
functions unchanged, so existing script imports keep working.
"""
from __future__ import annotations

from markdown_it import MarkdownIt

_md = MarkdownIt("commonmark")


def fenced_line_mask(body: str) -> list[bool]:
    """Return one bool per physical line of ``body``: True for Markdown code.

    This deliberately includes both CommonMark ``fence`` tokens and indented
    ``code_block`` tokens.  The historical function name is retained for
    compatibility with existing callers, but its contract is code-region
    masking rather than backtick-fence matching.
    """
    lines = body.splitlines()
    mask = [False] * len(lines)
    tokens = _md.parse(body)
    for tok in tokens:
        if tok.type in {"fence", "code_block"} and tok.map:
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


def get_fence_char_spans(text: str) -> list[tuple[int, int]]:
    """Return (start, end) character-offset spans of Markdown code blocks in
    ``text``, merging any immediately-adjacent spans (e.g. a reopened fence
    with no prose between the close of one block and the open of the next
    still reads as "inside code" for span-containment purposes).

    Character-offset form is what regex-based gates need: they locate a
    finding via ``re.finditer`` over the full string and must ask "does this
    match's start position fall inside a fence" -- the line-oriented
    functions above answer a different question (which physical lines are
    fenced) and would require re-deriving an offset table at every call site.
    """
    lines = text.splitlines(keepends=True)
    mask = fenced_line_mask(text)
    if len(mask) < len(lines):
        mask = mask + [mask[-1] if mask else False] * (len(lines) - len(mask))
    elif len(mask) > len(lines):
        mask = mask[: len(lines)]

    spans: list[tuple[int, int]] = []
    offset = 0
    span_start: int | None = None
    for line, flagged in zip(lines, mask):
        if flagged and span_start is None:
            span_start = offset
        elif not flagged and span_start is not None:
            spans.append((span_start, offset))
            span_start = None
        offset += len(line)
    if span_start is not None:
        spans.append((span_start, offset))
    return spans


def is_in_fence(pos: int, fence_spans: list[tuple[int, int]]) -> bool:
    """Return True if character offset ``pos`` falls inside any fence span."""
    return any(start <= pos < end for start, end in fence_spans)


def strip_fenced(text: str) -> str:
    """Return ``text`` with all Markdown code block content removed (spans
    replaced with nothing), for checks that must never fire on code content.
    """
    spans = get_fence_char_spans(text)
    if not spans:
        return text
    out = []
    prev_end = 0
    for start, end in spans:
        out.append(text[prev_end:start])
        prev_end = end
    out.append(text[prev_end:])
    return "".join(out)


def count_fence_open_reopens(text: str) -> int:
    """Return the count of fence blocks whose captured CONTENT itself
    contains a line that looks like another fence-open marker (backtick or
    tilde fence, optionally with a language tag) -- the "reopened
    mid-snippet / duplicated header" corruption shape.

    A closing backtick fence is, per CommonMark, a line of only backtick
    characters (no info string) -- a line like "```python" can never validly
    CLOSE a fence, only open one. So when an LLM duplicates the opening
    ```` ```python ```` line mid-snippet instead of emitting a real closing
    ```` ``` ````, markdown-it's real tokenizer correctly keeps the original
    fence open and swallows the spurious "```python" line as ordinary
    content, searching for the next line that actually IS a valid close. That
    swallowed line is exactly the signal this function looks for: a fence
    whose content contains an embedded fence-marker-shaped line. A naive
    ``` /``` toggle (used elsewhere in this codebase, e.g.
    hugo_parser.normalize_table_cells) cannot see this at all, since it
    flips state on every marker line and treats the spurious open as a
    (wrong) close.
    """
    tokens = _md.parse(text)
    reopens = 0
    for tok in tokens:
        if tok.type != "fence":
            continue
        for line in tok.content.splitlines():
            stripped = line.strip()
            if stripped.startswith("```") or stripped.startswith("~~~"):
                reopens += 1
    return reopens
