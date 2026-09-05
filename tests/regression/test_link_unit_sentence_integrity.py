"""TC-APT-036: a sentence containing an inline link must reach the model whole.

Forcing leaf-level extraction on any paragraph containing a link split the sentence
at each link boundary, so the prose fragment and the link text were translated with
no knowledge of each other -- the same failure the CODE_SPAN exclusion already
documents.

Measured consequences before this change, on real reviewed output:
  * cells-spreadsheet-management-go wraps as "...or cloud integration, the" /
    "[Aspose.Cells - Enterprise Product Family](...) is a". The prose fragment ended
    in a bare article governing a noun it never saw: 11 of 23 locales emitted the
    English "the" verbatim, ru/fa substituted a demonstrative with no antecedent,
    and de/nl lost V2 inversion.
  * introducing-words-foss-net's "[<Product> repository]" head noun was unorderable
    in 15 of 15 locales.

The exclusion is only sound when a preserve_pattern masks the "](url)" tail, so it
is conditional on that rather than on every site profile having been edited
correctly. Both directions are pinned here.
"""

from pathlib import Path

import pytest

from src.translation_engine.extractor.text_unit_extractor import TextUnitExtractor
from src.translation_engine.parser.hugo_parser import HugoParser
from src.utils.config_loader import ConfigService

TAIL_PATTERN = r"\]\(([^)]+)\)"
WHOLE_LINK_PATTERN = r"\[([^\]]+)\]\(([^)]+)\)"
URL = "https://github.com/aspose-words-foss/x"

IN_PROSE_LINK = (
    "---\ntitle: t\n---\n\n"
    f"The full source is available on GitHub in the [Aspose.Words repository]({URL}).\n"
)


def _units(markdown: str, patterns: list[str]) -> list[str]:
    parsed = HugoParser().parse_string(markdown)
    plan = TextUnitExtractor(preserve_patterns=patterns).extract_from_ast(
        parsed.ast, parsed.frontmatter or {}
    )
    texts = []
    for unit in getattr(plan, "units", plan):
        text = getattr(unit, "source_text", None) or getattr(unit, "text", "")
        if text and text.strip() and text.strip() != "t":
            texts.append(text)
    return texts


def test_sentence_with_a_link_is_one_unit_when_the_tail_is_protected():
    units = _units(IN_PROSE_LINK, [TAIL_PATTERN])

    prose = [u for u in units if "available on GitHub" in u]
    assert len(prose) == 1, f"sentence was split: {units}"
    whole = prose[0]
    assert whole.rstrip().endswith("."), "the sentence must carry its own terminator"
    assert "in the [" in whole, "the article must stay attached to its noun phrase"
    assert "repository" in whole, "the link text must remain translatable"


def test_no_unit_ends_in_a_dangling_article():
    """The exact shape that leaked a raw English 'the' into 11 of 23 locales."""
    units = _units(IN_PROSE_LINK, [TAIL_PATTERN])

    for unit in units:
        assert not unit.rstrip().endswith(" the"), f"dangling article in {unit!r}"


def test_the_url_is_never_placed_in_translatable_text():
    """True in both configurations -- this is the property that must not regress."""
    for patterns in ([TAIL_PATTERN], [], [WHOLE_LINK_PATTERN]):
        for unit in _units(IN_PROSE_LINK, patterns):
            assert URL not in unit, f"URL leaked with patterns={patterns}: {unit!r}"


def test_without_link_protection_it_falls_back_to_leaf_extraction():
    """The exclusion must not rest on an unenforced config invariant.

    websites.aspose.org carries no markdown-link pattern at all, and the extractor
    is constructed with preserve_patterns=[] in several suites.
    """
    units = _units(IN_PROSE_LINK, [])

    assert len(units) > 1, "unprotected config must keep the old leaf behaviour"
    assert any(u.rstrip().endswith("in the") for u in units)


def test_whole_link_pattern_also_counts_as_protection_but_masks_the_text():
    """Documents why the pattern was narrowed rather than left as-is."""
    units = _units(IN_PROSE_LINK, [WHOLE_LINK_PATTERN])

    prose = [u for u in units if "available on GitHub" in u]
    assert len(prose) == 1
    assert "repository" not in prose[0], (
        "the whole-span pattern masks the link TEXT too, so it would never be "
        "translated -- this is the reason for the tail-only form"
    )


def test_bold_still_forces_leaf_extraction():
    """Nothing protects **bold** syntax, so FIX-B's guard stays load-bearing."""
    markdown = "---\ntitle: t\n---\n\nSome **bold text** and more prose here.\n"

    units = _units(markdown, [TAIL_PATTERN])

    assert len(units) > 1, f"bold must not be merged into one unit: {units}"


def test_the_shipped_blog_profile_actually_protects_link_tails():
    """The config half of the change, asserted against the real profile."""
    profile = ConfigService(Path("config")).get_site_profile("blog.aspose.org")
    patterns = profile.body.preserve_patterns

    extractor = TextUnitExtractor(preserve_patterns=patterns)
    assert extractor._link_syntax_is_protected(), patterns

    units = _units(IN_PROSE_LINK, patterns)
    prose = [u for u in units if "available on GitHub" in u]
    assert len(prose) == 1
    assert "repository" in prose[0]


@pytest.mark.parametrize(
    "body",
    [
        "- [GitHub Repository](https://github.com/x)\n",
        "Text with two [one](https://a/x) and [two](https://b/y) links.\n",
        "A [link](https://a/x) at the start of prose.\n",
    ],
)
def test_url_protection_holds_across_link_shapes(body):
    for unit in _units("---\ntitle: t\n---\n\n" + body, [TAIL_PATTERN]):
        assert "https://" not in unit, unit
