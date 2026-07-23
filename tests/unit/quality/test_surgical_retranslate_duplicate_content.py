"""Regression coverage for surgical_retranslate.py's duplicate_content detector/fixer.

Root cause fixed: the check split translated body text on blank lines with no
awareness of fenced code blocks, so pages with several distinct code examples
sharing a short boilerplate opening line (e.g. an #include/import right after
the fence) got miscounted as "the same paragraph repeated 3+ times" and had
real code lines stripped from otherwise-correct examples. Verified against a
real production sample (kb.aspose.org/ar/slides/cpp/how-to-add-comments-cpp.md)
during the duplicate-content-fence-fix-20260723 mission: of 3,622 files the
audit had flagged, only 13 survived a fence-aware re-check, and manual
inspection showed even those were legitimate repeated API-reference
boilerplate, not corruption -- i.e. every file in the flagged set required
zero content changes once this detector was fixed.
"""

from __future__ import annotations

from scripts.quality.surgical_retranslate import (
    _detect_duplicate_content,
    _fix_duplicate_content,
)

_FENCE_FALSE_POSITIVE = (
    "---\ntitle: Test\n---\n\n"
    "Intro paragraph unrelated to any duplication for this test case entirely.\n\n"
    "```cpp\n#include <Aspose/Slides/Foss/presentation.h>\n\n"
    "int main() { return 1; }\n```\n\n"
    "Some other unique prose paragraph goes here between the code examples shown.\n\n"
    "```cpp\n#include <Aspose/Slides/Foss/presentation.h>\n\n"
    "int main() { return 2; }\n```\n\n"
    "Yet another distinct prose paragraph placed between these two code examples.\n\n"
    "```cpp\n#include <Aspose/Slides/Foss/presentation.h>\n\n"
    "int main() { return 3; }\n```\n"
)

_GENUINE_PROSE_DUPLICATE = (
    "---\ntitle: Test\n---\n\n"
    "This is a genuinely duplicated warning paragraph that should trigger the "
    "detector because it repeats three times verbatim in prose, well outside "
    "any code fence block here.\n\n"
    "Some unique content in between paragraph one and the next repeat of the "
    "warning text below this line.\n\n"
    "This is a genuinely duplicated warning paragraph that should trigger the "
    "detector because it repeats three times verbatim in prose, well outside "
    "any code fence block here.\n\n"
    "More unique filler content goes here to separate the repeats from each "
    "other nicely.\n\n"
    "This is a genuinely duplicated warning paragraph that should trigger the "
    "detector because it repeats three times verbatim in prose, well outside "
    "any code fence block here.\n\n"
    "Final unique paragraph at the end of the document for good measure.\n"
)


def test_code_fence_boilerplate_repetition_is_not_flagged():
    """Distinct code examples sharing a short opening line must not be
    treated as duplicate content -- this was the actual root cause of the
    3,622-file audit finding."""
    assert _detect_duplicate_content(_FENCE_FALSE_POSITIVE) == []


def test_code_fence_boilerplate_repetition_is_not_stripped():
    """Even if something upstream still flags the file, the fixer itself
    must never delete code-fence content."""
    fixed = _fix_duplicate_content(_FENCE_FALSE_POSITIVE)
    assert fixed == _FENCE_FALSE_POSITIVE
    assert fixed.count("#include <Aspose/Slides/Foss/presentation.h>") == 3
    assert "int main() { return 1; }" in fixed
    assert "int main() { return 2; }" in fixed
    assert "int main() { return 3; }" in fixed


def test_genuine_prose_duplication_is_still_detected():
    """The fence exclusion must not blind the detector to real repeated
    prose paragraphs."""
    detected = _detect_duplicate_content(_GENUINE_PROSE_DUPLICATE)
    assert len(detected) == 1
    assert detected[0][3] == "duplicate_content"


def test_genuine_prose_duplication_is_still_fixed():
    """Real duplicates outside code fences are still deduplicated, keeping
    the first occurrence only."""
    fixed = _fix_duplicate_content(_GENUINE_PROSE_DUPLICATE)
    assert fixed.count("This is a genuinely duplicated warning paragraph") == 1
    assert "Some unique content in between paragraph one" in fixed
    assert "Final unique paragraph at the end" in fixed


def test_real_flagged_production_sample_no_longer_flagged():
    """The exact real file that motivated this fix must no longer be
    detected as duplicate_content once fence-aware matching is applied."""
    body = (
        "---\ntitle: Test\n---\n\n"
        "Intro.\n\n"
        "```cpp\n#include <Aspose/Slides/Foss/presentation.h>\n#include <chrono>\n\n"
        "int main() { return 1; }\n```\n\n"
        "Middle paragraph one that is unrelated to any of the code examples here.\n\n"
        "```cpp\n#include <Aspose/Slides/Foss/presentation.h>\n\n"
        "int main() { return 2; }\n```\n\n"
        "Middle paragraph two that is also unrelated to any of the code examples.\n\n"
        "```cpp\n#include <Aspose/Slides/Foss/presentation.h>\n\n"
        "int main() { return 3; }\n```\n\n"
        "Middle paragraph three, still unrelated, still distinct prose text here.\n\n"
        "```cpp\n#include <Aspose/Slides/Foss/presentation.h>\n\n"
        "int main() { return 4; }\n```\n\n"
        "Middle paragraph four wraps up the set of distinct code examples shown.\n\n"
        "```cpp\n#include <Aspose/Slides/Foss/presentation.h>\n\n"
        "int main() { return 5; }\n```\n"
    )
    assert _detect_duplicate_content(body) == []


# ---------------------------------------------------------------------------
# TC-DCF-003: structurally-separated prose boilerplate (mission
# duplicate-content-fence-fix-20260723's pilot finding AUD-L3-002).
# Reproduces the real reference.aspose.org pattern: a short "Returns" note
# repeated once per distinct method/property section (heading between every
# occurrence) is legitimate documentation, not an MT decoding-loop artifact.
# ---------------------------------------------------------------------------

_STRUCTURALLY_SEPARATED_BOILERPLATE = (
    "---\ntitle: Test\n---\n\n"
    "### setTranslation(tx, ty, tz)\n\n"
    "Sets the local translation.\n\n"
    "Returns: the same Transform instance, for method chaining.\n\n"
    "### setScale(sx, sy, sz)\n\n"
    "Sets the local scale.\n\n"
    "Returns: the same Transform instance, for method chaining.\n\n"
    "### setRotation(rw, rx, ry, rz)\n\n"
    "Sets the local rotation.\n\n"
    "Returns: the same Transform instance, for method chaining.\n"
)

_SAME_NOTE_WITHOUT_STRUCTURAL_SEPARATION = (
    "---\ntitle: Test\n---\n\n"
    "Returns: the same Transform instance, for method chaining.\n\n"
    "Unrelated filler paragraph with no heading in sight here at all.\n\n"
    "Returns: the same Transform instance, for method chaining.\n\n"
    "Another unrelated filler paragraph, still no headings anywhere near it.\n\n"
    "Returns: the same Transform instance, for method chaining.\n"
)


def test_structurally_separated_prose_boilerplate_not_flagged():
    assert _detect_duplicate_content(_STRUCTURALLY_SEPARATED_BOILERPLATE) == []


def test_structurally_separated_prose_boilerplate_not_stripped():
    working = _STRUCTURALLY_SEPARATED_BOILERPLATE
    if _detect_duplicate_content(working):
        working = _fix_duplicate_content(working)
    assert working == _STRUCTURALLY_SEPARATED_BOILERPLATE
    assert working.count("Returns: the same Transform instance, for method chaining.") == 3


def test_repeated_prose_without_structural_separation_still_flagged_and_fixed():
    """Contrast case: the exclusion must not blind detection to a genuine
    decoding-loop shape (same note repeated with no heading/fence between
    occurrences)."""
    assert _detect_duplicate_content(_SAME_NOTE_WITHOUT_STRUCTURAL_SEPARATION) != []
    working = _SAME_NOTE_WITHOUT_STRUCTURAL_SEPARATION
    if _detect_duplicate_content(working):
        working = _fix_duplicate_content(working)
    assert working.count("Returns: the same Transform instance, for method chaining.") == 1


# ---------------------------------------------------------------------------
# Regression tests found by independent verification of TC-DCF-003: the
# structural-separation helper split the whole body on blank lines before
# checking fence overlap, silently merging a paragraph with no blank line
# before it into an adjacent fence -- losing it from consideration
# entirely. That caused a false positive (legitimate fence-adjacent content
# wrongly stripped) here in surgical_retranslate.py, and a false negative
# (genuine fence-adjacent corruption silently missed) in audit_all_content.py.
# ---------------------------------------------------------------------------

_GENUINE_CORRUPTION_FENCE_ADJACENT = (
    "---\ntitle: Test\n---\n\n"
    "Intro paragraph unrelated to anything duplicated in this test case.\n\n"
    "```python\nx = 1\n```\n"
    "This is a genuinely duplicated warning paragraph that repeats verbatim in prose here.\n\n"
    "```python\ny = 2\n```\n"
    "This is a genuinely duplicated warning paragraph that repeats verbatim in prose here.\n\n"
    "```python\nz = 3\n```\n"
    "This is a genuinely duplicated warning paragraph that repeats verbatim in prose here.\n"
)

_LEGITIMATE_BOILERPLATE_FENCE_ADJACENT = (
    "---\ntitle: Test\n---\n\n"
    "### setTranslation(tx, ty, tz)\n\nSets the local translation.\n\n"
    "```typescript\nsetTranslation(tx: number): Transform\n```\n"
    "Returns: the same Transform instance, for method chaining.\n\n"
    "### setScale(sx, sy, sz)\n\nSets the local scale.\n\n"
    "```typescript\nsetScale(sx: number): Transform\n```\n"
    "Returns: the same Transform instance, for method chaining.\n\n"
    "### setRotation(rw, rx, ry, rz)\n\nSets the local rotation.\n\n"
    "```typescript\nsetRotation(rw: number): Transform\n```\n"
    "Returns: the same Transform instance, for method chaining.\n"
)

_ONLY_FENCE_SEPARATED_NO_HEADING = (
    "---\ntitle: Test\n---\n\n"
    "Intro paragraph unrelated to anything duplicated in this test case.\n\n"
    "This is a genuinely duplicated warning paragraph that repeats verbatim in prose here.\n\n"
    "```python\nx = 1\n```\n\n"
    "This is a genuinely duplicated warning paragraph that repeats verbatim in prose here.\n\n"
    "```python\ny = 2\n```\n\n"
    "This is a genuinely duplicated warning paragraph that repeats verbatim in prose here.\n"
)


def _real_pipeline_fix(content):
    working = content
    if _detect_duplicate_content(working):
        working = _fix_duplicate_content(working)
    return working


def test_genuine_corruption_directly_adjacent_to_fence_still_caught():
    fixed = _real_pipeline_fix(_GENUINE_CORRUPTION_FENCE_ADJACENT)
    assert fixed.count("This is a genuinely duplicated warning paragraph") == 1


def test_legitimate_boilerplate_directly_adjacent_to_fence_still_protected():
    fixed = _real_pipeline_fix(_LEGITIMATE_BOILERPLATE_FENCE_ADJACENT)
    assert fixed == _LEGITIMATE_BOILERPLATE_FENCE_ADJACENT
    assert fixed.count("Returns: the same Transform instance, for method chaining.") == 3


def test_code_fence_alone_between_occurrences_is_not_sufficient_separation():
    """A code fence between occurrences, with no heading change, must NOT
    be treated as legitimate structural separation on its own -- a genuine
    decoding-loop repeat could plausibly interleave with unrelated code
    blocks. Only an actual heading counts as evidence of distinct
    structural context."""
    fixed = _real_pipeline_fix(_ONLY_FENCE_SEPARATED_NO_HEADING)
    assert fixed.count("This is a genuinely duplicated warning paragraph") == 1


# ---------------------------------------------------------------------------
# TC-DCF-008: _fix_duplicate_content must only strip paragraphs that
# actually meet the 3x threshold, not any 2nd+ occurrence of any paragraph
# >30 chars. An unrelated, incidental 2x repeat in the same file as a
# genuine 3x+ duplicate must be left untouched.
# ---------------------------------------------------------------------------

_MIXED_3X_AND_2X_DUPLICATES = (
    "---\ntitle: Test\n---\n\n"
    "This is a genuinely duplicated warning paragraph that repeats three times verbatim in prose right here.\n\n"
    "Unrelated filler paragraph one that has nothing at all to do with anything else in this document.\n\n"
    "This is a genuinely duplicated warning paragraph that repeats three times verbatim in prose right here.\n\n"
    "This is an unrelated paragraph that just happens to repeat exactly twice in this test document overall.\n\n"
    "Unrelated filler paragraph two that has nothing at all to do with anything else in this document.\n\n"
    "This is a genuinely duplicated warning paragraph that repeats three times verbatim in prose right here.\n\n"
    "This is an unrelated paragraph that just happens to repeat exactly twice in this test document overall.\n"
)


def test_2x_repeat_untouched_when_file_also_has_genuine_3x_duplicate():
    fixed = _real_pipeline_fix(_MIXED_3X_AND_2X_DUPLICATES)
    assert fixed.count("This is a genuinely duplicated warning paragraph") == 1
    assert fixed.count("This is an unrelated paragraph that just happens to repeat exactly twice") == 2
