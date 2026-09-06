"""TC-APT-087: a governed "Aspose.X -- Enterprise Y" navigation label must
stay masked even when its link is embedded in a paragraph alongside other
prose, not just when the link is the whole node (TC-APT-085's LIST_ITEM fix).

Measured on introducing-cells-foss-go, held from the heal-cells-go-w2 commit:
"...the [Aspose.Cells -- Enterprise Product Family](url) is a separate
commercial offering." -- the label survived 17 of 18 locales by the model's
own judgment but was translated into Arabic, which a review caught.

Root cause, confirmed LIVE (not by static reading, after a first,
misleadingly negative synthetic-extractor test): this paragraph extracts as
ONE full-sentence unit (TC-APT-036/078's link-in-sentence path). Only the
bare "Aspose.Cells" brand token was masked by the pre-existing generic brand
pattern; "-- Enterprise Product Family" survived as ordinary translatable
text within that unit's source_text, e.g.
"...the {PLACEHOLDER_0}{PLACEHOLDER_2} -- Enterprise Product
Family{PLACEHOLDER_1} is a...". A synthetic TextUnitExtractor built without
this exact constructor's preserve_patterns/mt_model kwargs produced a
misleading leaf-split result that looked like the bug didn't exist --
these tests intentionally mirror _translate_body_ast's real construction
(segment_translator.py) instead of a simplified stand-in, learning that
lesson directly (same "stand-in reimplements the verdict" hazard the
TC-APT-090 real-method tests exist to avoid).
"""

from src.translation_engine.extractor.text_unit_extractor import TextUnitExtractor
from src.translation_engine.parser.hugo_parser import HugoParser
from src.utils.config_loader import ConfigService

REAL_PARAGRAPH = (
    "Commercial use is permitted under the MIT license terms. If your project requires\n"
    "enterprise-grade support, extended format coverage, or cloud integration, the\n"
    "[Aspose.Cells — Enterprise Product Family](https://products.aspose.com/cells/) is a\n"
    "separate commercial offering."
)

LIST_ITEM_LABEL = "- [Aspose.Cells — Enterprise Blog](https://blog.aspose.com/)"


def _extract_body_units(markdown_body: str):
    """Mirrors _translate_body_ast's real TextUnitExtractor construction
    (segment_translator.py) closely enough to reproduce its segmentation
    decisions -- a bare site_profile= kwarg alone is NOT sufficient, which is
    exactly the gap that produced a false negative while diagnosing this bug.
    """
    config = ConfigService("config")
    profile = config.get_site_profile("blog.aspose.org")
    doc = HugoParser().parse_string(f"---\ntitle: test\n---\n\n{markdown_body}\n")
    extractor = TextUnitExtractor(
        segmentation_strategy=profile.body.ast_segmentation_strategy,
        mt_model=None,
        preserve_patterns=profile.body.preserve_patterns,
        site_profile=profile,
        target_lang="ar",
    )
    plan = extractor.extract_from_ast(doc.ast, doc.frontmatter)
    return [u for u in plan.units if u.node_addr and u.node_addr.startswith("body.")]


def test_the_label_stays_one_masked_span_inside_a_full_sentence_paragraph():
    units = _extract_body_units(REAL_PARAGRAPH)
    assert len(units) == 1, f"expected the paragraph to extract as one unit, got {len(units)}"
    unit = units[0]
    assert "Enterprise" not in unit.source_text, (
        f"the label suffix leaked into translatable text: {unit.source_text!r}"
    )
    assert "Product Family" not in unit.source_text


def test_the_full_label_round_trips_through_placeholder_restoration():
    units = _extract_body_units(REAL_PARAGRAPH)
    unit = units[0]
    unit.translated_text = unit.source_text  # identity: proves round-trip neutrality
    from src.translation_engine.extractor.placeholder_manager import PlaceholderManager

    restored = PlaceholderManager().restore(unit.translated_text, unit.metadata.get("placeholder_map", {}))
    assert "Aspose.Cells — Enterprise Product Family" in restored
    assert restored == REAL_PARAGRAPH.replace("\n", " ")


def test_the_list_item_whole_link_path_is_unaffected():
    """Regression guard: TC-APT-085's already-working LIST_ITEM path must not
    be disturbed by this pattern (it uses a different mechanism -- do_not_translate
    on the LINK_TEXT unit -- which doesn't depend on this preserve_pattern)."""
    units = _extract_body_units(LIST_ITEM_LABEL)
    label_units = [u for u in units if "Enterprise Blog" in (u.source_text or "")]
    assert label_units, "expected a unit carrying the list-item label text"
    assert all(u.do_not_translate for u in label_units)


def test_ordinary_prose_mentioning_a_brand_without_the_dash_shape_is_unaffected():
    """The pattern requires the dash-separated 'Enterprise' shape -- it must not
    mask ordinary sentences that happen to mention a product and enterprise use."""
    units = _extract_body_units(
        "Aspose.Cells is trusted by enterprise teams building large financial reports."
    )
    assert len(units) == 1
    assert "enterprise teams" in units[0].source_text
