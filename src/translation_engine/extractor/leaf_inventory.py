"""TD-02 (TC-APT-105 audit): a single, shared answer to one question that
multiple mechanisms across this codebase have needed --

    "Does this AST subtree have exactly one leaf TextUnit descendant in
    total, and if so, is that leaf `do_not_translate`?"

Extracted as the reference implementation of RC-01's fix
(segment_translator.py's AST-reuse safety check): a Segment covering a whole
container node's combined translation may only be reused for a single
TextUnit when the container has EXACTLY ONE leaf descendant overall --
counting `do_not_translate` leaves is mandatory, not optional. Excluding
them (the pre-RC-01 bug) makes a container holding one protected leaf plus
one ordinary leaf look like "exactly one leaf", so the ordinary leaf
silently absorbs the container's whole combined translation -- including
the protected leaf's own markdown -- duplicating it. Confirmed live on
content/docs.aspose.org/en/cells/go/getting-started/quickstart.md's
"Next Steps" list.

Returns a tri-state ``LeafClassification`` keyed strictly by ``node_addr``
identity against the caller-supplied ``units`` list -- never by re-derived
or re-normalized text, since two structurally distinct nodes can share
identical text (this module answers "which node", not "which text").

Audited but NOT migrated (2026-09-10): ast_renderer.py's
_correct_cross_references/_build_heading_translation_map,
frontmatter_consistency.py, and heading_uniqueness.py were each checked
against this exact contract and found not to need it -- none of them merge
or reuse ONE combined translation across MULTIPLE leaf descendants of a
container the way segment_translator.py's Segment-to-TextUnit reuse does.
Each already carries its own, sufficient, unit-level `do_not_translate`
exclusion filter for its own (non-subtree, non-leaf-counting) algorithm:
ast_renderer.py guards its one call site directly
(`not unit.do_not_translate`) before ever calling
_correct_cross_references; frontmatter_consistency.py's
find_cross_field_residuals and heading_uniqueness.py's
find_duplicate_heading_translations both filter `do_not_translate` units
out of their eligible set before doing their own, unrelated text-diffing /
translated-text-grouping work. None of the three ever counts descendant
leaves of a node_addr subtree. Wiring them to this module regardless would
be a speculative, unmotivated change to already-hardened code with no
confirmed bug behind it and no genuine duplicated logic to remove -- see
this taskcard's execution evidence for the full audit trail per file.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .text_unit import TextUnit

__all__ = ["LeafClassification", "LeafInventoryResult", "classify_sole_leaf"]


class LeafClassification(Enum):
    """The tri-state answer to "is this node's subtree exactly one leaf,
    and is that leaf protected?"."""

    ORDINARY_SOLE_LEAF = "ordinary_sole_leaf"
    """Exactly one leaf descendant in total, and it is NOT do_not_translate
    -- safe to reuse a container-level combined translation for it."""

    PROTECTED_SOLE_LEAF = "protected_sole_leaf"
    """Exactly one leaf descendant in total, but it IS do_not_translate --
    never reuse a combined translation here; the leaf's own value must be
    preserved verbatim."""

    NOT_SOLE_LEAF = "not_sole_leaf"
    """Zero leaf descendants, or more than one -- a combined translation
    cannot be soundly attributed to any single leaf."""


@dataclass(frozen=True)
class LeafInventoryResult:
    """`classification` is the tri-state answer; `sole_unit` is the single
    matching TextUnit when `classification` is ORDINARY_SOLE_LEAF or
    PROTECTED_SOLE_LEAF, else None."""

    classification: LeafClassification
    sole_unit: TextUnit | None


def classify_sole_leaf(node_addr: str, units: list[TextUnit]) -> LeafInventoryResult:
    """Classify `node_addr`'s subtree against the given `units` list.

    A unit is a descendant of `node_addr` when its own `node_addr` equals
    `node_addr` exactly, or starts with `node_addr + "."` (the AST
    addressing scheme's own child-path convention). Units with empty
    `source_text` are not counted as leaves (matches RC-01's own
    `_body_units` filter: nothing there to translate or reuse).

    `units` should already be scoped to whatever population the caller
    considers "in scope" for this check (e.g. body units only, excluding
    frontmatter) -- this function does no scoping of its own beyond the
    node_addr/source_text match, by design, so it fits any caller's own
    notion of scope without silently re-deriving one.
    """
    sole_unit = None
    match_count = 0
    prefix = node_addr + "."
    for unit in units:
        if not unit.source_text:
            continue
        addr = unit.node_addr
        if addr == node_addr or addr.startswith(prefix):
            match_count += 1
            if match_count > 1:
                return LeafInventoryResult(LeafClassification.NOT_SOLE_LEAF, None)
            sole_unit = unit

    if sole_unit is None:
        return LeafInventoryResult(LeafClassification.NOT_SOLE_LEAF, None)

    classification = (
        LeafClassification.PROTECTED_SOLE_LEAF
        if sole_unit.do_not_translate
        else LeafClassification.ORDINARY_SOLE_LEAF
    )
    return LeafInventoryResult(classification, sole_unit)
