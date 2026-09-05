"""TC-APT-085: a governed brand-navigation label must survive in a list item too.

The brand-navigation-label check ran only on the LINK extraction path
(_extract_link). A label sitting inside a paragraph therefore survived, but the
same label standing alone in a list item routes through full-sentence extraction
instead and was translated.

Measured on introducing-cells-foss-go, which is what localised the gap: the same
label preserved 17/18 locales inside a paragraph link, but only 8/18 alone in a
list item. "API Reference" survived that position solely because it carries an
independent config/terminology.yaml entry.

The first attempt at this fix was INERT and the real page caught it: on the
full-sentence path the candidate text is the raw markdown
"[Aspose.Cells - Enterprise Blog](https://blog.aspose.com/)", not the anchor
text, so testing the brand predicate against it failed on the leading bracket.
test_the_raw_markdown_form_is_what_gets_tested pins that specific trap.
"""

import pytest

from src.translation_engine.extractor.text_unit_extractor import (
    _link_text_is_brand_navigation_label,
    _whole_node_is_brand_navigation_link,
)


@pytest.mark.parametrize(
    "markdown",
    [
        "[Aspose.Cells — Enterprise Blog](https://blog.aspose.com/)",
        "[Aspose.3D KB](https://kb.aspose.com/3d/)",
        "[Aspose.Slides API Reference](https://reference.aspose.com/slides/)",
    ],
)
def test_a_whole_list_item_that_is_a_brand_nav_link_is_protected(markdown):
    assert _whole_node_is_brand_navigation_link(markdown) is True


def test_the_raw_markdown_form_is_what_gets_tested():
    """The trap the first attempt fell into.

    The anchor text passes the brand predicate; the raw markdown does not,
    because of the leading bracket. The full-sentence path only ever sees the
    raw form, so the check must unwrap it.
    """
    anchor = "Aspose.Cells — Enterprise Blog"
    raw = f"[{anchor}](https://blog.aspose.com/)"

    assert _link_text_is_brand_navigation_label(anchor) is True
    assert _link_text_is_brand_navigation_label(raw) is False
    assert _whole_node_is_brand_navigation_link(raw) is True


def test_prose_mixed_with_a_nav_link_stays_translatable():
    """Narrowness: only a WHOLE-node link qualifies."""
    assert _whole_node_is_brand_navigation_link(
        "See the [Aspose.Cells KB](https://kb.aspose.com/) for details"
    ) is False


def test_a_product_phrase_with_a_lowercase_connector_stays_translatable():
    """'Aspose.Words FOSS for .NET' is prose, not a navigation label."""
    assert _whole_node_is_brand_navigation_link(
        "[Aspose.Words FOSS for .NET](https://products.aspose.com/words/net/)"
    ) is False


def test_a_non_brand_link_is_not_claimed_here():
    """API Reference alone has no brand prefix; terminology.yaml governs it."""
    assert _whole_node_is_brand_navigation_link(
        "[API Reference](https://reference.aspose.com/)"
    ) is False


def test_plain_text_is_unaffected():
    for text in ("Install it via NuGet", "Read cells back from a worksheet", ""):
        assert _whole_node_is_brand_navigation_link(text) is False
