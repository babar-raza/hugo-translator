"""
Regression tests: Cross-field contamination guard (RC-4 prevention).

RC-4 root cause: Japanese KB file had body text (DocumentBuilder, cursor methods)
populate frontmatter fields (title, description, step1-step7). Investigation
showed this could occur via TM lookup returning the wrong cached translation
when two segments share the same source text but belong to different fields.

TC-CFC-01: Frontmatter title segment and body paragraph with identical source text
           → different segment IDs (no TM collision possible)
TC-CFC-02: Two different frontmatter keys with identical source text
           → different segment IDs
TC-CFC-03: Body segment cannot retrieve frontmatter segment from TM
TC-CFC-04: Frontmatter segment ID includes frontmatter_key discriminator
TC-CFC-05: Body segment ID includes context_type=body_text discriminator
TC-CFC-06: Same text, same frontmatter key → same ID (TM hit works correctly)
TC-CFC-07: SegmentContext.context_type distinguishes FRONTMATTER from BODY_TEXT
"""
from __future__ import annotations

import pytest

try:
    from src.translation_engine.extractor.segment_extractor import (
        Segment,
        SegmentContext,
        SegmentContextType,
    )

    HAS_EXTRACTOR = True
except ImportError:
    HAS_EXTRACTOR = False


pytestmark = pytest.mark.skipif(not HAS_EXTRACTOR, reason="segment_extractor not importable")

SITE_ID = "test_site"
SOURCE_TEXT = "DocumentBuilder allows you to insert content"


# ---------------------------------------------------------------------------
# TC-CFC-01: Frontmatter title vs identical body paragraph
# ---------------------------------------------------------------------------

class TestFrontmatterVsBodyIsolation:
    """Same source text in frontmatter title and body paragraph → different IDs."""

    def test_tc_cfc_01_frontmatter_title_vs_body_paragraph(self):
        """TC-CFC-01: title frontmatter segment != body text segment for identical source."""
        fm_ctx = SegmentContext(
            context_type=SegmentContextType.FRONTMATTER,
            frontmatter_key="title",
        )
        body_ctx = SegmentContext(
            context_type=SegmentContextType.BODY_TEXT,
            node_id="node_001",
        )

        fm_id = Segment.create_id(SOURCE_TEXT, fm_ctx, SITE_ID)
        body_id = Segment.create_id(SOURCE_TEXT, body_ctx, SITE_ID)

        assert fm_id != body_id, (
            f"Frontmatter 'title' and body paragraph with identical source text "
            f"must produce different segment IDs to prevent TM cross-contamination. "
            f"Got same ID: {fm_id}"
        )

    def test_tc_cfc_05_body_context_type_in_id(self):
        """TC-CFC-05: Body segment ID includes BODY_TEXT context_type discriminator."""
        body_ctx = SegmentContext(
            context_type=SegmentContextType.BODY_TEXT,
            node_id="node_42",
        )
        body_id = Segment.create_id(SOURCE_TEXT, body_ctx, SITE_ID)

        # Verify a hypothetical frontmatter context produces a different ID
        fm_ctx = SegmentContext(
            context_type=SegmentContextType.FRONTMATTER,
            frontmatter_key="description",
        )
        fm_id = Segment.create_id(SOURCE_TEXT, fm_ctx, SITE_ID)

        assert body_id != fm_id


# ---------------------------------------------------------------------------
# TC-CFC-02: Two different frontmatter keys with same text
# ---------------------------------------------------------------------------

class TestDifferentFrontmatterKeysIsolation:
    """Same source text in two different frontmatter keys → different IDs."""

    STEP_TEXT = "Click the button to proceed"

    def test_tc_cfc_02_different_frontmatter_keys_differ(self):
        """TC-CFC-02: 'title' and 'description' frontmatter keys produce different IDs."""
        title_ctx = SegmentContext(
            context_type=SegmentContextType.FRONTMATTER,
            frontmatter_key="title",
        )
        desc_ctx = SegmentContext(
            context_type=SegmentContextType.FRONTMATTER,
            frontmatter_key="description",
        )

        title_id = Segment.create_id(self.STEP_TEXT, title_ctx, SITE_ID)
        desc_id = Segment.create_id(self.STEP_TEXT, desc_ctx, SITE_ID)

        assert title_id != desc_id, (
            f"'title' and 'description' frontmatter keys with same source text "
            f"must produce different segment IDs. Got same ID: {title_id}"
        )

    def test_tc_cfc_02_step1_vs_step2_differ(self):
        """TC-CFC-02b: 'step1' and 'step2' frontmatter keys produce different IDs."""
        step1_ctx = SegmentContext(
            context_type=SegmentContextType.FRONTMATTER,
            frontmatter_key="step1",
        )
        step2_ctx = SegmentContext(
            context_type=SegmentContextType.FRONTMATTER,
            frontmatter_key="step2",
        )

        step1_id = Segment.create_id(self.STEP_TEXT, step1_ctx, SITE_ID)
        step2_id = Segment.create_id(self.STEP_TEXT, step2_ctx, SITE_ID)

        assert step1_id != step2_id, (
            f"'step1' and 'step2' frontmatter keys with same source text "
            f"must produce different IDs. Got same ID: {step1_id}"
        )


# ---------------------------------------------------------------------------
# TC-CFC-04: Frontmatter segment ID includes frontmatter_key discriminator
# ---------------------------------------------------------------------------

class TestFrontmatterKeyDiscriminator:
    """Verify frontmatter_key is incorporated into segment ID."""

    def test_tc_cfc_04_frontmatter_key_in_id(self):
        """TC-CFC-04: Segment ID differs when frontmatter_key differs (same text, same context_type)."""
        with_key_ctx = SegmentContext(
            context_type=SegmentContextType.FRONTMATTER,
            frontmatter_key="title",
        )
        without_key_ctx = SegmentContext(
            context_type=SegmentContextType.FRONTMATTER,
            frontmatter_key=None,  # No key — should produce different hash
        )

        id_with = Segment.create_id("Some Title Text", with_key_ctx, SITE_ID)
        id_without = Segment.create_id("Some Title Text", without_key_ctx, SITE_ID)

        assert id_with != id_without, (
            "Segment with frontmatter_key='title' must differ from segment "
            "with frontmatter_key=None for the same source text"
        )

    def test_tc_cfc_06_same_key_same_text_same_id(self):
        """TC-CFC-06: Identical key + text → identical ID (TM cache hits work correctly)."""
        ctx_a = SegmentContext(
            context_type=SegmentContextType.FRONTMATTER,
            frontmatter_key="title",
        )
        ctx_b = SegmentContext(
            context_type=SegmentContextType.FRONTMATTER,
            frontmatter_key="title",
        )

        id_a = Segment.create_id("Add Watermarks to Word", ctx_a, SITE_ID)
        id_b = Segment.create_id("Add Watermarks to Word", ctx_b, SITE_ID)

        assert id_a == id_b, (
            "Two segments with the same key, text, and site_id must produce "
            "the same ID so that TM cache hits function correctly"
        )


# ---------------------------------------------------------------------------
# TC-CFC-03: Body segment cannot retrieve a frontmatter TM entry
# ---------------------------------------------------------------------------

class TestTMCannotCrossContaminate:
    """
    Verify that a body segment's ID cannot accidentally match a frontmatter
    entry stored in the TM (because their IDs differ).

    This test is a pure unit test of ID isolation — it does not require a
    running TM store. If body_id != fm_id, a TM lookup keyed by body_id
    will never return the translation stored under fm_id.
    """

    def test_tc_cfc_03_body_id_never_equals_frontmatter_id(self):
        """TC-CFC-03: Body segment cannot retrieve a frontmatter TM entry by ID."""
        # Simulate Japanese KB RC-4 scenario:
        # English source body paragraph that matches the 'title' field text
        shared_text = "How to Add Watermarks to Word Documents"

        fm_ctx = SegmentContext(
            context_type=SegmentContextType.FRONTMATTER,
            frontmatter_key="title",
        )
        body_ctx = SegmentContext(
            context_type=SegmentContextType.BODY_TEXT,
            node_id="heading_h1_0",
        )

        fm_id = Segment.create_id(shared_text, fm_ctx, SITE_ID)
        body_id = Segment.create_id(shared_text, body_ctx, SITE_ID)

        assert fm_id != body_id, (
            f"A body segment and a frontmatter 'title' segment with identical "
            f"source text must have different IDs. This prevents TM lookups for "
            f"body content from returning frontmatter translations (RC-4 guard). "
            f"Got same ID: {fm_id}"
        )


# ---------------------------------------------------------------------------
# TC-CFC-07: SegmentContextType enum values
# ---------------------------------------------------------------------------

class TestSegmentContextTypeEnum:
    """SegmentContextType distinguishes all expected context types."""

    def test_tc_cfc_07_context_types_are_distinct(self):
        """TC-CFC-07: FRONTMATTER and BODY_TEXT context types are distinct string values."""
        assert SegmentContextType.FRONTMATTER != SegmentContextType.BODY_TEXT
        assert SegmentContextType.FRONTMATTER.value == "frontmatter"
        assert SegmentContextType.BODY_TEXT.value == "body_text"

    def test_context_type_used_in_id_generation(self):
        """Changing context_type alone (same text, same key) changes the ID."""
        fm_ctx = SegmentContext(
            context_type=SegmentContextType.FRONTMATTER,
            frontmatter_key=None,
        )
        # HEADING has no frontmatter_key
        heading_ctx = SegmentContext(
            context_type=SegmentContextType.HEADING,
            node_id="heading_1",
        )

        fm_id = Segment.create_id("Introduction", fm_ctx, SITE_ID)
        heading_id = Segment.create_id("Introduction", heading_ctx, SITE_ID)

        assert fm_id != heading_id, (
            "FRONTMATTER and HEADING context types must produce different IDs "
            "for the same source text"
        )
