"""Unit tests for mine_heading_glossary.py's core alignment algorithm.

Mission heading-i18n-governance-20260723, taskcard TC-HT-I18N-002. This
script had zero automated test coverage at delivery (verified only via a
one-off manual run against the live content corpus) -- a real, disclosed
gap surfaced during TC-HT-I18N-009's closure scoring. `_align_and_vote()`
is pure and self-contained (no filesystem/content-repo access), so it is
directly testable without any of the read-only-corpus-scanning machinery
around it.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from scripts.quality.mine_heading_glossary import _align_and_vote, _get_body, _headings


def _run(en_headings, locale_headings):
    votes: dict[str, Counter] = {}
    identifiers: Counter = Counter()
    _align_and_vote(en_headings, locale_headings, votes, identifiers)
    return votes, identifiers


class TestAlignAndVote:
    def test_simple_one_to_one_translation_is_voted(self):
        votes, identifiers = _run(["Overview", "Methods"], ["概要", "方法"])
        assert votes["Overview"]["概要"] == 1
        assert votes["Methods"]["方法"] == 1
        assert identifiers["Overview"] == 1
        assert identifiers["Methods"] == 1

    def test_locale_missing_a_trailing_section_does_not_crash(self):
        # Locale file is shorter than EN (a dropped/missing section) -- the
        # forward-only two-pointer walk must stop cleanly, not IndexError.
        votes, identifiers = _run(["Overview", "Methods", "See Also"], ["概要"])
        assert votes["Overview"]["概要"] == 1
        assert "Methods" not in votes
        assert "See Also" not in votes

    def test_untranslated_english_heading_is_not_voted_but_is_counted(self):
        # Both sides ASCII at this position: the heading is still in
        # English in the translation -- must be recorded as an identifier
        # occurrence (candidate for Track C) but never as a translation
        # vote (Track B), and the locale pointer must not be consumed.
        votes, identifiers = _run(["Overview"], ["Overview"])
        assert "Overview" not in votes
        assert identifiers["Overview"] == 1

    def test_non_ascii_en_heading_syncs_pointer_without_voting(self):
        # An EN heading that isn't ASCII-heading-shaped (e.g. already
        # punctuation/non-English) should not be treated as a Track B/C
        # candidate at all, but must still advance the locale pointer so
        # later real candidates stay aligned.
        votes, identifiers = _run(["日本語", "Overview"], ["何か", "概要"])
        assert "日本語" not in votes
        assert "日本語" not in identifiers
        assert votes["Overview"]["概要"] == 1

    def test_repeated_translation_accumulates_vote_counts(self):
        votes, _ = _run(["Overview", "Overview", "Overview"], ["概要", "概要", "概観"])
        assert votes["Overview"]["概要"] == 2
        assert votes["Overview"]["概観"] == 1

    def test_split_vote_across_multiple_files_is_additive(self):
        # Simulates the real mining loop calling _align_and_vote() once per
        # file with a shared votes/identifiers accumulator across files.
        votes: dict[str, Counter] = {}
        identifiers: Counter = Counter()
        _align_and_vote(["Properties"], ["プロパティ"], votes, identifiers)
        _align_and_vote(["Properties"], ["特性について"], votes, identifiers)
        _align_and_vote(["Properties"], ["プロパティ"], votes, identifiers)
        assert votes["Properties"]["プロパティ"] == 2
        assert votes["Properties"]["特性について"] == 1
        assert identifiers["Properties"] == 3

    def test_empty_locale_headings_produces_no_votes(self):
        votes, identifiers = _run(["Overview", "Methods"], [])
        assert votes == {}
        assert identifiers == {}


class TestGetBodyAndHeadings:
    def test_get_body_splits_frontmatter(self):
        text = "---\ntitle: X\n---\n## Overview\nbody text\n"
        assert _get_body(text).strip() == "## Overview\nbody text"

    def test_get_body_returns_whole_text_when_no_frontmatter_delimiters(self):
        text = "## Overview\nno frontmatter here\n"
        assert _get_body(text) == text

    def test_headings_extracts_heading_text_only(self):
        text = "---\ntitle: X\n---\n## Overview\ntext\n### Methods\nmore\n"
        assert _headings(text) == ["Overview", "Methods"]
