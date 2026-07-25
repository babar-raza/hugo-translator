"""
HT-QUALITY-GATES-001 Part 22 (root cause A): body segments must set
tm_key_text to the pre-protection source text, mirroring the fix
_create_frontmatter_segment already had.

Root cause: PlaceholderManager.protect() collapses distinguishing content
(e.g. "Aspose.Cells" and "Aspose.Words" both protect to the identical
"{PLACEHOLDER_0}" shape under a brand-token preserve pattern). Body segments
never set tm_key_text, so the TM key hash fell back to source_text -- the
PROTECTED text -- meaning two genuinely different paragraphs from different
product families that happen to share a template can hash to the identical
TM key and silently serve each other's cached translation. This is the
confirmed root cause for the kb.aspose.org cross-family contamination
pattern documented in the plan (e.g. German "Das ist ein Scherz."
identical across cells/email/note/slides family pages).
"""
from unittest.mock import MagicMock

from src.translation_engine.extractor.segment_extractor import SegmentExtractor
from src.translation_engine.parser.ast_nodes import paragraph_node, text_node
from src.utils.models import BodyRules


def _make_site_profile(preserve_patterns=None):
    profile = MagicMock()
    profile.site_id = "kb.aspose.org"
    profile.body = BodyRules(translate_markdown=True)
    profile.body.preserve_patterns = preserve_patterns or []
    profile.body.preserve_blocks = []
    profile.body.placeholder_syntax = None
    return profile


class TestBodySegmentTmKeyTextScoping:
    def test_body_segment_sets_tm_key_text_to_unprotected_source(self):
        """The fix itself: tm_key_text must equal the original, unprotected
        paragraph text -- not None (the pre-fix default) and not the
        placeholder-protected source_text."""
        profile = _make_site_profile(preserve_patterns=[r"\bAspose(?:\.[A-Za-z0-9]+)?\b"])
        extractor = SegmentExtractor(profile)
        ast = [paragraph_node([text_node("Aspose.Cells FOSS is a free, open-source library.")])]

        segments = extractor.extract_from_body(ast, "en")

        assert len(segments) == 1
        seg = segments[0]
        assert seg.tm_key_text == "Aspose.Cells FOSS is a free, open-source library."
        # Confirms protection actually ran and collapsed the brand token --
        # otherwise this test would not be exercising the bug it pins.
        assert seg.tm_key_text != seg.source_text
        assert "{PLACEHOLDER_0}" in seg.source_text

    def test_two_different_families_no_longer_collide_on_tm_key_text(self):
        """The confirmed real-world defect shape: two paragraphs differing
        only in product name protect down to an IDENTICAL source_text
        (both brand tokens collapse to the same placeholder), which is
        exactly the collision that caused cross-family contamination.
        tm_key_text must still distinguish them."""
        profile = _make_site_profile(preserve_patterns=[r"\bAspose(?:\.[A-Za-z0-9]+)?\b"])
        extractor = SegmentExtractor(profile)

        cells_ast = [paragraph_node([text_node("Aspose.Cells FOSS is a free, open-source library.")])]
        words_ast = [paragraph_node([text_node("Aspose.Words FOSS is a free, open-source library.")])]

        cells_seg = extractor.extract_from_body(cells_ast, "en")[0]
        words_seg = extractor.extract_from_body(words_ast, "en")[0]

        # The bug this fix closes: without it, both would share this exact
        # protected shape and therefore the same (wrong) TM key.
        assert cells_seg.source_text == words_seg.source_text == (
            "{PLACEHOLDER_0} FOSS is a free, open-source library."
        )
        # The fix: tm_key_text still tells them apart.
        assert cells_seg.tm_key_text != words_seg.tm_key_text
        assert cells_seg.tm_key_text == "Aspose.Cells FOSS is a free, open-source library."
        assert words_seg.tm_key_text == "Aspose.Words FOSS is a free, open-source library."

    def test_heading_and_list_item_segments_also_set_tm_key_text(self):
        """The fix lives in the shared _create_body_segment() helper, so
        every body context type (not just paragraphs) benefits -- spot-check
        a heading."""
        from src.translation_engine.parser.ast_nodes import heading_node

        profile = _make_site_profile()
        extractor = SegmentExtractor(profile)
        ast = [heading_node(2, [text_node("Getting Started")])]

        segments = extractor.extract_from_body(ast, "en")

        assert len(segments) == 1
        assert segments[0].tm_key_text == "Getting Started"
