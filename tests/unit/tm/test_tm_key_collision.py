"""TC-HT-TMKEY-001: TM key must not collide across unrelated documents.

Root cause (DELIVERABLE 53, Root Cause 1): frontmatter description segments are
placeholder-protected before being hashed for the TM key. The placeholder
substitution replaces identifying content (e.g. a backtick-wrapped class name)
with a generic, position-only token, so two different classes whose
descriptions follow the same short template (e.g. "`X` class with N methods")
reduced to the byte-identical protected string and collided on the same TM
key -- silently serving one class's cached translation for a different class.

The fix: Segment carries a separate `tm_key_text` (the original,
pre-placeholder-protection text) used for TM key derivation; the
placeholder-protected `source_text` remains what is sent to the model.
"""

from src.translation_engine.extractor.segment_extractor import (
    Segment,
    SegmentContext,
    SegmentContextType,
    SegmentExtractor,
)
from src.tm.normalization import hash_text


def _make_site_profile():
    """Minimal SiteProfile-like object with the preserve_patterns SegmentExtractor needs."""
    from unittest.mock import MagicMock

    profile = MagicMock()
    profile.site_id = "reference.aspose.org"
    profile.body.preserve_patterns = [r"`[^`]+`"]
    profile.body.preserve_blocks = []
    profile.body.placeholder_syntax = None
    return profile


class TestFrontmatterSegmentRetainsOriginalTextForTmKey:
    """SegmentExtractor._create_frontmatter_segment sets tm_key_text."""

    def test_tm_key_text_is_original_unprotected_value(self):
        extractor = SegmentExtractor(_make_site_profile())
        seg = extractor._create_frontmatter_segment(
            "description", "`Alignment` class with 1 method and 8 properties", "en"
        )
        assert seg.tm_key_text == "`Alignment` class with 1 method and 8 properties"

    def test_source_text_is_placeholder_protected_for_model_input(self):
        """source_text (sent to the model) still has the class name replaced."""
        extractor = SegmentExtractor(_make_site_profile())
        seg = extractor._create_frontmatter_segment(
            "description", "`Alignment` class with 1 method and 8 properties", "en"
        )
        assert "Alignment" not in seg.source_text
        assert "{PLACEHOLDER_0}" in seg.source_text

    def test_two_different_classes_same_template_collide_on_protected_text(self):
        """Confirms the bug's precondition still holds: two unrelated classes
        with the same template DO reduce to the same protected source_text.
        This is what makes hashing source_text directly unsafe."""
        extractor = SegmentExtractor(_make_site_profile())
        seg_a = extractor._create_frontmatter_segment(
            "description", "`Alignment` class with 1 method and 8 properties", "en"
        )
        seg_b = extractor._create_frontmatter_segment(
            "description", "`Matrix` class with 1 method and 8 properties", "en"
        )
        assert seg_a.source_text == seg_b.source_text, (
            "Precondition: protected text collides across different classes "
            "sharing a template -- this is exactly why hashing source_text is unsafe."
        )

    def test_two_different_classes_do_not_collide_on_tm_key_text(self):
        """The actual fix: tm_key_text differs even though source_text collides."""
        extractor = SegmentExtractor(_make_site_profile())
        seg_a = extractor._create_frontmatter_segment(
            "description", "`Alignment` class with 1 method and 8 properties", "en"
        )
        seg_b = extractor._create_frontmatter_segment(
            "description", "`Matrix` class with 1 method and 8 properties", "en"
        )
        assert seg_a.tm_key_text != seg_b.tm_key_text
        assert hash_text(seg_a.tm_key_text) != hash_text(seg_b.tm_key_text)

    def test_enum_template_with_no_distinguishing_count_also_does_not_collide(self):
        """Confirmed real-world instance: `ChartType` enum vs `SaveFormat` enum --
        the simplest, most collision-prone template (no method/property counts
        at all to even coincidentally differ on)."""
        extractor = SegmentExtractor(_make_site_profile())
        seg_a = extractor._create_frontmatter_segment("description", "`ChartType` enum", "en")
        seg_b = extractor._create_frontmatter_segment("description", "`SaveFormat` enum", "en")
        assert seg_a.source_text == seg_b.source_text  # still collides pre-fix
        assert seg_a.tm_key_text != seg_b.tm_key_text  # fixed: distinct TM keys

    def test_body_segments_now_also_get_tm_key_text(self):
        """HT-QUALITY-GATES-001 Part 22 (root cause A): the original TC-HT-TMKEY-001
        fix was deliberately scoped to frontmatter only. Further root-cause
        investigation this session confirmed body segments have the exact
        same collision precondition (placeholder protection collapsing
        distinguishing content, e.g. two different Aspose product names both
        protecting to the same brand-token placeholder) and is the confirmed
        explanation for the kb.aspose.org cross-family body-content
        contamination pattern (e.g. identical boilerplate paragraphs shared
        across unrelated product families). The scope was widened to match --
        see test_segment_extractor_body_tm_key_scoping.py for the full
        collision-reproduction test using this exact mechanism."""
        from src.translation_engine.parser.ast_nodes import ASTNode, NodeType

        extractor = SegmentExtractor(_make_site_profile())
        node = ASTNode(type=NodeType.PARAGRAPH, raw="Some prose text.")
        seg = extractor._create_body_segment(
            "Some prose text.",
            node,
            SegmentContextType.BODY_TEXT,
            "en",
            depth=0,
            parent_type=None,
        )
        assert seg.tm_key_text == "Some prose text."


class TestSegmentTmKeyTextDefaultsNone:
    """A bare Segment() without tm_key_text must default to None (backward compat)."""

    def test_default_is_none(self):
        seg = Segment(
            id="x",
            source_text="hello",
            context=SegmentContext(context_type=SegmentContextType.BODY_TEXT),
            site_id="site",
            source_lang="en",
        )
        assert seg.tm_key_text is None
