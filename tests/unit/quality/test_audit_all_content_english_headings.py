"""Regression coverage for audit_all_content.py's english_headings_nonlatin
check (TC-DCF-007, mission duplicate-content-fence-fix-20260723).

Root cause: HEADING_RE (`^(#{1,6})\\s+(.+)$`) matches any #-prefixed line
anywhere in the body, including inside code fences -- Python/YAML/bash
comments ("# comment text") match it too. Confirmed on a real production
file (kb.aspose.org/ar/words/python/how-to-build-ldm-builder-python.md,
whose only "English headings" were Python comments like "# Read full text"
inside code blocks) and quantified corpus-wide: of 62,085 NON_LATIN-locale
files with code fences, 267 were false positives from this exact pattern,
0 new false negatives from excluding fenced content.
"""

from __future__ import annotations

from scripts.quality.audit_all_content import check_english_headings_nonlatin

_CODE_COMMENT_FALSE_POSITIVE = (
    "## مقدمة\n\n"
    "نص عربي غير ذي صلة.\n\n"
    "```python\n"
    "# Read full text\n"
    "text = doc.read()\n\n"
    "# Iterate sections\n"
    "for section in doc.sections:\n"
    "    print(section)\n"
    "```\n"
)

_GENUINE_UNTRANSLATED_HEADING = (
    "## Getting Started\n\n"
    "Some content here in a non-Latin locale file.\n"
)


def test_code_comment_inside_fence_not_flagged():
    assert check_english_headings_nonlatin(_CODE_COMMENT_FALSE_POSITIVE) == []


def test_real_untranslated_heading_still_flagged():
    result = check_english_headings_nonlatin(_GENUINE_UNTRANSLATED_HEADING)
    assert result == ["Getting Started"]


def test_real_production_sample_no_longer_flagged():
    """The exact real file that motivated this fix must return no
    English-looking headings once fence-aware matching is applied."""
    fp = (
        r"D:\onedrive\Documents\GitHub\aspose.org\content\kb.aspose.org\ar"
        r"\words\python\how-to-build-ldm-builder-python.md"
    )
    with open(fp, encoding="utf-8") as f:
        content = f.read()
    if content.startswith("---"):
        end = content.find("\n---", 4)
        body = content[end + 4:] if end != -1 else content
    else:
        body = content
    assert check_english_headings_nonlatin(body) == []
