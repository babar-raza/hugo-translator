"""Regression coverage for audit_all_content.py's duplicate_content check.

This closes TC-DCF-005 (mission duplicate-content-fence-fix-20260723,
finding AUD-L1-004): the check was previously inline inside scan()'s
per-file loop with no committed test coverage, verified at closure only via
literal extraction+exec of the on-disk bytes. It has since been extracted
into the standalone `check_duplicate_content()` function specifically to
make it directly, repeatably testable like the other two implementations
(write_gate.py's Gate 16, surgical_retranslate.py's detector/fixer).

Also covers TC-DCF-003 (finding AUD-L3-002): a duplicate whose every
consecutive pair of occurrences is separated by a heading or a code fence is
legitimate structurally-repeating documentation (e.g. reference.aspose.org's
"Returns: same X instance for chaining" note repeated once per method), not
an MT decoding-loop artifact, and must not be flagged.
"""

from __future__ import annotations

from scripts.quality.audit_all_content import check_duplicate_content

_FENCE_FALSE_POSITIVE = (
    "```cpp\n#include <Aspose/Slides/Foss/presentation.h>\n\n"
    "int main() { return 1; }\n```\n\n"
    "Some other unique prose paragraph goes here between the code examples "
    "shown that is long enough to count as a real paragraph in this check.\n\n"
    "```cpp\n#include <Aspose/Slides/Foss/presentation.h>\n\n"
    "int main() { return 2; }\n```\n\n"
    "Yet another distinct prose paragraph placed between these two code "
    "examples, also comfortably over the fifty character minimum length.\n\n"
    "```cpp\n#include <Aspose/Slides/Foss/presentation.h>\n\n"
    "int main() { return 3; }\n```\n"
)

_GENUINE_PROSE_DUPLICATE = (
    "This is a genuinely duplicated warning paragraph that should trigger "
    "the detector because it repeats three times verbatim in prose, well "
    "outside any code fence block here.\n\n"
    "Some unique content in between paragraph one and the next repeat of "
    "the warning text below this line that is definitely over fifty "
    "characters long.\n\n"
    "This is a genuinely duplicated warning paragraph that should trigger "
    "the detector because it repeats three times verbatim in prose, well "
    "outside any code fence block here.\n\n"
    "More unique filler content goes here to separate the repeats from "
    "each other nicely and stay well past the fifty character minimum "
    "length.\n\n"
    "This is a genuinely duplicated warning paragraph that should trigger "
    "the detector because it repeats three times verbatim in prose, well "
    "outside any code fence block here.\n"
)

_STRUCTURALLY_SEPARATED_BOILERPLATE = (
    "### setTranslation(tx, ty, tz)\n\n"
    "Sets the local translation for this node in world space coordinates.\n\n"
    "Returns: the same Transform instance, for method chaining purposes.\n\n"
    "### setScale(sx, sy, sz)\n\n"
    "Sets the local scale factor applied to this node in each dimension.\n\n"
    "Returns: the same Transform instance, for method chaining purposes.\n\n"
    "### setRotation(rw, rx, ry, rz)\n\n"
    "Sets the local rotation quaternion components for this node here.\n\n"
    "Returns: the same Transform instance, for method chaining purposes.\n"
)

_SAME_NOTE_WITHOUT_STRUCTURAL_SEPARATION = (
    "Returns: the same Transform instance, for method chaining purposes.\n\n"
    "Unrelated filler paragraph with no heading in sight here at all today.\n\n"
    "Returns: the same Transform instance, for method chaining purposes.\n\n"
    "Another unrelated filler paragraph, still no headings anywhere near it.\n\n"
    "Returns: the same Transform instance, for method chaining purposes.\n"
)


def test_code_fence_boilerplate_repetition_not_flagged():
    assert check_duplicate_content(_FENCE_FALSE_POSITIVE) is False


def test_genuine_prose_duplication_flagged():
    assert check_duplicate_content(_GENUINE_PROSE_DUPLICATE) is True


def test_structurally_separated_boilerplate_not_flagged():
    assert check_duplicate_content(_STRUCTURALLY_SEPARATED_BOILERPLATE) is False


def test_prose_repetition_without_structural_separation_still_flagged():
    assert check_duplicate_content(_SAME_NOTE_WITHOUT_STRUCTURAL_SEPARATION) is True


# ---------------------------------------------------------------------------
# Regression tests found by independent verification of TC-DCF-003: this
# function's rewrite (extracted from an inline block) split the whole body
# on blank lines before checking fence overlap, silently merging a
# paragraph with no blank line before it into an adjacent fence -- a
# genuine decoding-loop repeat directly after a fence was silently missed
# entirely (never reached the >=3 count).
# ---------------------------------------------------------------------------

_GENUINE_CORRUPTION_FENCE_ADJACENT = (
    "Intro paragraph unrelated to anything duplicated in this test case that "
    "is long enough to count as a real paragraph in this check.\n\n"
    "```python\nx = 1\n```\n"
    "This is a genuinely duplicated warning paragraph that repeats verbatim "
    "in prose here, well past the fifty character minimum length.\n\n"
    "```python\ny = 2\n```\n"
    "This is a genuinely duplicated warning paragraph that repeats verbatim "
    "in prose here, well past the fifty character minimum length.\n\n"
    "```python\nz = 3\n```\n"
    "This is a genuinely duplicated warning paragraph that repeats verbatim "
    "in prose here, well past the fifty character minimum length.\n"
)

_LEGITIMATE_BOILERPLATE_FENCE_ADJACENT = (
    "### setTranslation(tx, ty, tz)\n\nSets the local translation for this node.\n\n"
    "```typescript\nsetTranslation(tx: number): Transform\n```\n"
    "Returns: the same Transform instance, for method chaining purposes here.\n\n"
    "### setScale(sx, sy, sz)\n\nSets the local scale factor for this node.\n\n"
    "```typescript\nsetScale(sx: number): Transform\n```\n"
    "Returns: the same Transform instance, for method chaining purposes here.\n\n"
    "### setRotation(rw, rx, ry, rz)\n\nSets the local rotation for this node.\n\n"
    "```typescript\nsetRotation(rw: number): Transform\n```\n"
    "Returns: the same Transform instance, for method chaining purposes here.\n"
)


def test_genuine_corruption_directly_adjacent_to_fence_still_flagged():
    assert check_duplicate_content(_GENUINE_CORRUPTION_FENCE_ADJACENT) is True


def test_legitimate_boilerplate_directly_adjacent_to_fence_still_protected():
    assert check_duplicate_content(_LEGITIMATE_BOILERPLATE_FENCE_ADJACENT) is False
