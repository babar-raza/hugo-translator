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

from scripts.quality.mine_heading_glossary import (
    _align_and_vote,
    _get_body,
    _headings,
    _mine_boilerplate,
    _mine_table_headers,
    _normalize_for_comparison,
    _prose_lines,
    _table_header_rows,
    _zip_align_and_vote,
)


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


class TestUniversalVoteRule:
    """reference-i18n-hardening-20260725: the ASCII-shape test on the
    LOCALE side was replaced with a normalize-and-compare rule so
    Latin-script locales (es, de, fr, ...) can be mined -- the old rule
    treated every Latin-script translation as still-English and mined
    nothing for those locales."""

    def test_latin_script_translation_is_voted(self):
        # Old ASCII-shape rule would have called this untranslated (it IS
        # ASCII-shaped modulo the accent) and never voted it.
        votes: dict = {}
        identifiers: Counter = Counter()
        _align_and_vote(["Overview"], ["Visión general"], votes, identifiers)
        assert votes["Overview"]["Visión general"] == 1

    def test_identical_latin_text_is_leakage_not_a_vote(self):
        votes: dict = {}
        identifiers: Counter = Counter()
        _align_and_vote(["Overview"], ["Overview"], votes, identifiers)
        assert "Overview" not in votes
        assert identifiers["Overview"] == 1

    def test_case_and_whitespace_variants_are_not_votes(self):
        votes: dict = {}
        identifiers: Counter = Counter()
        _align_and_vote(["See Also"], ["see   also"], votes, identifiers)
        assert "See Also" not in votes  # normalized-equal -> leakage, not a vote

    def test_trailing_colon_variant_is_not_a_vote(self):
        votes: dict = {}
        identifiers: Counter = Counter()
        _align_and_vote(["Namespace"], ["Namespace:"], votes, identifiers)
        assert "Namespace" not in votes


class TestNormalizeForComparison:
    def test_nfc_and_case_and_whitespace_and_colon(self):
        assert _normalize_for_comparison("  See  Also  ") == "see also"
        assert _normalize_for_comparison("Namespace:") == _normalize_for_comparison("Namespace")
        assert _normalize_for_comparison("Café") == _normalize_for_comparison("Café")


class TestZipAlignAndVoteFastPath:
    def test_equal_counts_uses_positional_zip(self):
        votes: dict = {}
        identifiers: Counter = Counter()
        _zip_align_and_vote(["Overview", "Methods"], ["概要", "方法"], votes, identifiers)
        assert votes["Overview"]["概要"] == 1
        assert votes["Methods"]["方法"] == 1

    def test_zip_and_two_pointer_agree_on_the_equal_count_case(self):
        # Sanity check: for an equal-count, no-dropped-section input, the
        # fast path and the fallback must produce identical votes.
        en = ["Overview", "Properties", "Methods"]
        loc = ["Visión general", "Propiedades", "Métodos"]
        votes_zip: dict = {}
        ident_zip: Counter = Counter()
        _zip_align_and_vote(en, loc, votes_zip, ident_zip)
        votes_walk: dict = {}
        ident_walk: Counter = Counter()
        _align_and_vote(en, loc, votes_walk, ident_walk)
        assert {k: dict(v) for k, v in votes_zip.items()} == {
            k: dict(v) for k, v in votes_walk.items()
        }


class TestTableHeaderMining:
    def test_extracts_header_row_cells(self):
        text = (
            "---\ntitle: X\n---\n"
            "## Properties\n\n"
            "| Name | Type | Access | Description |\n"
            "|------|------|--------|-------------|\n"
            "| `Text` | `string` | Read/Write | Gets the text. |\n"
        )
        rows = _table_header_rows(text)
        assert rows == [["Name", "Type", "Access", "Description"]]

    def test_votes_per_cell_when_column_counts_match(self):
        en = (
            "---\ntitle: X\n---\n"
            "| Name | Type | Access | Description |\n"
            "|------|------|--------|-------------|\n"
        )
        de = (
            "---\ntitle: X\n---\n"
            "| Name | Typ | Zugriff | Beschreibung |\n"
            "|------|------|--------|-------------|\n"
        )
        cell_votes: dict = {}
        row_votes: dict = {}
        cell_ident: Counter = Counter()
        misaligned: Counter = Counter()
        _mine_table_headers(en, de, cell_votes, row_votes, cell_ident, misaligned)
        assert cell_votes["Type"]["Typ"] == 1
        assert cell_votes["Description"]["Beschreibung"] == 1
        assert "Name" not in cell_votes  # "Name" left untranslated -> leakage
        assert cell_ident["Name"] == 1

    def test_full_row_hallucination_recorded_even_with_matching_column_count(self):
        en = (
            "---\ntitle: X\n---\n"
            "| Name | Type | Access | Description |\n"
            "|------|------|--------|-------------|\n"
        )
        de = (
            "---\ntitle: X\n---\n"
            "| Name der Person | Typ der | Zugriff | Beschreibung |\n"
            "|------|------|--------|-------------|\n"
        )
        cell_votes: dict = {}
        row_votes: dict = {}
        cell_ident: Counter = Counter()
        misaligned: Counter = Counter()
        _mine_table_headers(en, de, cell_votes, row_votes, cell_ident, misaligned)
        key = ("Name", "Type", "Access", "Description")
        assert row_votes[key][("Name der Person", "Typ der", "Zugriff", "Beschreibung")] == 1

    def test_cell_count_mismatch_is_tracked_and_does_not_crash(self):
        en = (
            "---\ntitle: X\n---\n"
            "| Name | Type | Description |\n"
            "|------|------|-------------|\n"
        )
        de = (
            "---\ntitle: X\n---\n"
            "| Name | Description |\n"
            "|------|-------------|\n"
        )
        cell_votes: dict = {}
        row_votes: dict = {}
        cell_ident: Counter = Counter()
        misaligned: Counter = Counter()
        _mine_table_headers(en, de, cell_votes, row_votes, cell_ident, misaligned)
        assert misaligned["cell_count_mismatch"] == 1


class TestBoilerplateMining:
    def test_inherits_from_recovers_locale_template(self):
        en = (
            "---\ntitle: X\n---\n\n"
            "`AbsorbedCell` is a class in Aspose.PDF FOSS for .NET.\n"
            "Inherits from: `IComparable<AbsorbedCell>`.\n\n"
            "Represents a cell.\n"
        )
        de = (
            "---\ntitle: X\n---\n\n"
            "`AbsorbedCell` ist eine Klasse in Aspose.PDF FOSS für .NET.\n"
            "Erbt von: `IComparable<AbsorbedCell>`.\n\n"
            "Stellt eine Zelle dar.\n"
        )
        phrase_votes: dict = {}
        corruption: Counter = Counter()
        _mine_boilerplate(en, de, phrase_votes, corruption)
        # Captured tokens (the identifier) are substituted back to {api} --
        # this recovers a REUSABLE locale template, not just a verbatim copy.
        assert phrase_votes["phrase.inherits_from"]["Erbt von: {api}."] == 1

    def test_enum_defines_values_only_templates_the_fixed_prefix(self):
        # The tail of this line (the actual `HTML`, `XPS`, ... list) is
        # THIS enum's own data, not reusable template text -- only the
        # "This enumeration defines N values:" prefix should be voted.
        en = "---\ntitle: X\n---\n\n" "This enumeration defines 19 values: `HTML`, `XPS`.\n"
        ja = (
            "---\ntitle: X\n---\n\n"
            "この列挙型は 19 個の値を定義します: `HTML`, `XPS`。\n"
        )
        phrase_votes: dict = {}
        corruption: Counter = Counter()
        _mine_boilerplate(en, ja, phrase_votes, corruption)
        # "19" is substituted back to {n}; the tail (`HTML`, `XPS`...) is
        # correctly EXCLUDED from the vote (that's per-enum data, not a
        # reusable phrase).
        assert (
            phrase_votes["phrase.enum_defines_values"]["この列挙型は {n} 個の値を定義します:"] == 1
        )

    def test_corrupted_captured_token_is_flagged_not_voted(self):
        en = "---\ntitle: X\n---\n\nInherits from: `IComparable<AbsorbedCell>`.\n"
        # The identifier itself got mangled by MT -- must not be counted as
        # a valid vote (a real template value would preserve it verbatim).
        de_corrupted = "---\ntitle: X\n---\n\nErbt von: Vergleichbar mit AbsorbedCell.\n"
        phrase_votes: dict = {}
        corruption: Counter = Counter()
        _mine_boilerplate(en, de_corrupted, phrase_votes, corruption)
        assert "phrase.inherits_from" not in phrase_votes
        assert corruption["phrase.inherits_from"] == 1

    def test_members_accessible_backreference_requires_matching_platform(self):
        en = (
            "---\ntitle: X\n---\n\n"
            "All public members are accessible to any .NET application after "
            "installing the Aspose.PDF FOSS for .NET package.\n"
        )
        de = (
            "---\ntitle: X\n---\n\n"
            "Alle Mitglieder sind fuer jede .NET Anwendung zugaenglich nach "
            "installation des Aspose.PDF FOSS for .NET package.\n"
        )
        phrase_votes: dict = {}
        corruption: Counter = Counter()
        _mine_boilerplate(en, de, phrase_votes, corruption)
        assert "phrase.members_accessible_after_install" in phrase_votes


class TestProseLines:
    def test_excludes_headings_table_rows_and_bullets(self):
        text = (
            "---\ntitle: X\n---\n\n"
            "## Overview\n\n"
            "A real prose line.\n"
            "Another prose line.\n\n"
            "| Name | Description |\n"
            "|------|-------------|\n"
            "- a bullet list item\n"
        )
        lines = _prose_lines(text)
        assert lines == ["A real prose line.", "Another prose line."]


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
