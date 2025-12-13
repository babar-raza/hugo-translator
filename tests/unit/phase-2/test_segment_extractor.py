"""
Unit tests for Segment Extractor.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from translation_engine.extractor import (
    PlaceholderManager,
    Segment,
    SegmentContext,
    SegmentContextType,
    SegmentExtractor,
)
from translation_engine.parser import HugoParser
from utils.models import BodyRules, FrontmatterMode, FrontmatterRule, SiteProfile


class TestPlaceholderManager:
    """Test placeholder management."""

    def test_protect_and_restore(self) -> None:
        """Test basic protect and restore."""
        pm = PlaceholderManager()
        text = "Hello {{< shortcode >}} world"
        patterns = [r"\{\{<.*?>\}\}"]

        protected, placeholder_map = pm.protect(text, patterns)

        assert "{PLACEHOLDER_0}" in protected
        assert "{{< shortcode >}}" not in protected
        assert len(placeholder_map) == 1

        restored = pm.restore(protected, placeholder_map)
        assert restored == text

    def test_multiple_patterns(self) -> None:
        """Test protecting multiple patterns."""
        pm = PlaceholderManager()
        text = "Text {{< sc1 >}} and {{%  sc2 %}} and `code`"
        patterns = [r"\{\{<.*?>\}\}", r"\{\{%.*?%\}\}", r"`[^`]+`"]

        protected, placeholder_map = pm.protect(text, patterns)

        assert protected.count("{PLACEHOLDER_") == 3
        assert len(placeholder_map) == 3

        restored = pm.restore(protected, placeholder_map)
        assert restored == text

    def test_extract_placeholders(self) -> None:
        """Test extracting placeholder tokens."""
        pm = PlaceholderManager()
        text = "Text {PLACEHOLDER_0} and {PLACEHOLDER_1}"

        placeholders = pm.extract_placeholders(text)
        assert len(placeholders) == 2
        assert "{PLACEHOLDER_0}" in placeholders
        assert "{PLACEHOLDER_1}" in placeholders


class TestSegment:
    """Test Segment model."""

    def test_create_id(self) -> None:
        """Test segment ID generation."""
        context = SegmentContext(
            context_type=SegmentContextType.FRONTMATTER,
            frontmatter_key="title",
        )

        seg_id1 = Segment.create_id("Test Title", context, "test-site")
        seg_id2 = Segment.create_id("Test Title", context, "test-site")
        seg_id3 = Segment.create_id("Different Title", context, "test-site")

        # Same content should produce same ID
        assert seg_id1 == seg_id2

        # Different content should produce different ID
        assert seg_id1 != seg_id3

        # ID should be hex string
        assert len(seg_id1) == 16
        assert all(c in "0123456789abcdef" for c in seg_id1)


class TestSegmentExtractor:
    """Test SegmentExtractor functionality."""

    @pytest.fixture
    def simple_profile(self) -> SiteProfile:
        """Create a simple test profile."""
        return SiteProfile(
            site_id="test-site",
            content_roots=["/content/test"],
            default_source_lang="en",
            target_langs=["es", "fr"],
            frontmatter={
                "title": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
                "description": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
                "tags": FrontmatterRule(mode=FrontmatterMode.TRANSLATE_LIST),
                "draft": FrontmatterRule(mode=FrontmatterMode.PASSTHROUGH),
                "banner.title": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
                "banner.content": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
            },
            body=BodyRules(
                translate_markdown=True,
                preserve_blocks=["block_code", "inline_code"],
                preserve_patterns=[],
                placeholder_syntax=[r"\{\{<.*?>\}\}", r"\{\{%.*?%\}\}"],
            ),
        )

    def test_extractor_initialization(self, simple_profile: SiteProfile) -> None:
        """Test extractor can be initialized."""
        extractor = SegmentExtractor(simple_profile)
        assert extractor is not None
        assert extractor.site_profile == simple_profile

    def test_extract_from_frontmatter_simple(
        self, simple_profile: SiteProfile
    ) -> None:
        """Test extracting simple frontmatter fields."""
        extractor = SegmentExtractor(simple_profile)
        frontmatter = {
            "title": "Test Title",
            "description": "Test Description",
            "draft": False,
        }

        segments = extractor.extract_from_frontmatter(frontmatter, "en")

        assert len(segments) == 2
        assert any(s.source_text == "Test Title" for s in segments)
        assert any(s.source_text == "Test Description" for s in segments)
        assert all(s.context.context_type == SegmentContextType.FRONTMATTER for s in segments)

    def test_extract_from_frontmatter_list(
        self, simple_profile: SiteProfile
    ) -> None:
        """Test extracting list frontmatter fields."""
        extractor = SegmentExtractor(simple_profile)
        frontmatter = {
            "tags": ["tag1", "tag2", "tag3"],
        }

        segments = extractor.extract_from_frontmatter(frontmatter, "en")

        assert len(segments) == 3
        assert any(s.source_text == "tag1" for s in segments)
        assert any(s.source_text == "tag2" for s in segments)
        assert any(s.source_text == "tag3" for s in segments)

    def test_extract_from_frontmatter_nested(
        self, simple_profile: SiteProfile
    ) -> None:
        """Test extracting nested frontmatter fields."""
        extractor = SegmentExtractor(simple_profile)
        frontmatter = {
            "banner": {
                "title": "Banner Title",
                "content": "Banner Content",
            }
        }

        segments = extractor.extract_from_frontmatter(frontmatter, "en")

        assert len(segments) == 2
        assert any(s.source_text == "Banner Title" for s in segments)
        assert any(s.source_text == "Banner Content" for s in segments)

    def test_extract_from_body_paragraphs(
        self, simple_profile: SiteProfile
    ) -> None:
        """Test extracting paragraph segments."""
        parser = HugoParser()
        content = "# Heading\n\nThis is a paragraph.\n\nAnother paragraph."
        doc = parser.parse_string(content)

        extractor = SegmentExtractor(simple_profile)
        segments = extractor.extract_from_body(doc.ast, "en")

        # Should extract: heading + 2 paragraphs
        assert len(segments) >= 3

        # Check for heading
        heading_segs = [
            s for s in segments
            if s.context.context_type == SegmentContextType.HEADING
        ]
        assert len(heading_segs) == 1
        assert "Heading" in heading_segs[0].source_text

        # Check for paragraphs
        para_segs = [
            s for s in segments
            if s.context.context_type == SegmentContextType.BODY_TEXT
        ]
        assert len(para_segs) == 2

    def test_extract_with_inline_code(self, simple_profile: SiteProfile) -> None:
        """Test that inline code is preserved in segments."""
        parser = HugoParser()
        content = "This has `inline code` in it."
        doc = parser.parse_string(content)

        extractor = SegmentExtractor(simple_profile)
        segments = extractor.extract_from_body(doc.ast, "en")

        assert len(segments) == 1
        # Inline code should be included in the text
        assert "`inline code`" in segments[0].source_text

    def test_extract_with_shortcodes(self, simple_profile: SiteProfile) -> None:
        """Test that Hugo shortcodes are protected."""
        parser = HugoParser()
        content = "Text with {{< shortcode >}} embedded."
        doc = parser.parse_string(content)

        extractor = SegmentExtractor(simple_profile)
        segments = extractor.extract_from_body(doc.ast, "en")

        assert len(segments) == 1
        segment = segments[0]

        # Shortcode should be replaced with placeholder
        assert "{PLACEHOLDER_" in segment.source_text
        assert "{{< shortcode >}}" not in segment.source_text

        # Placeholder map should contain the shortcode
        assert len(segment.placeholder_map) == 1
        assert "{{< shortcode >}}" in segment.placeholder_map.values()

    def test_extract_skips_code_blocks(self, simple_profile: SiteProfile) -> None:
        """Test that code blocks are not extracted."""
        parser = HugoParser()
        content = """# Heading

```python
def hello():
    print("Hello")
```

Text after code.
"""
        doc = parser.parse_string(content)

        extractor = SegmentExtractor(simple_profile)
        segments = extractor.extract_from_body(doc.ast, "en")

        # Should extract heading and paragraph, but not code block
        assert len(segments) == 2

        # No segment should contain the code
        assert not any("def hello" in s.source_text for s in segments)

    def test_extract_all(self, simple_profile: SiteProfile) -> None:
        """Test extracting from entire document."""
        parser = HugoParser()
        content = """---
title: "Test Document"
description: "Test description"
tags:
  - tag1
  - tag2
---

# Introduction

This is the introduction paragraph.

## Details

More details here.
"""
        doc = parser.parse_string(content)

        extractor = SegmentExtractor(simple_profile)
        segments = extractor.extract_all(doc, source_lang="en")

        # Should have frontmatter + body segments
        assert len(segments) > 4

        # Check frontmatter segments
        fm_segments = [
            s for s in segments
            if s.context.context_type == SegmentContextType.FRONTMATTER
        ]
        assert len(fm_segments) >= 4  # title, description, tag1, tag2

        # Check body segments
        body_segments = [
            s for s in segments
            if s.context.context_type != SegmentContextType.FRONTMATTER
        ]
        assert len(body_segments) >= 4  # 2 headings + 2 paragraphs

    def test_extract_from_fixture(
        self, simple_profile: SiteProfile, test_data_dir: Path
    ) -> None:
        """Test extracting from fixture file."""
        parser = HugoParser()
        fixture_path = (
            test_data_dir.parent / "fixtures" / "sample_content" / "extraction_test.md"
        )

        if not fixture_path.exists():
            pytest.skip(f"Fixture not found: {fixture_path}")

        doc = parser.parse_file(fixture_path)

        extractor = SegmentExtractor(simple_profile)
        segments = extractor.extract_all(doc)

        # Should extract multiple segments
        assert len(segments) > 5

        # Check that shortcodes are protected
        protected_segments = [s for s in segments if s.placeholder_map]
        assert len(protected_segments) > 0

        # Check segment types
        context_types = {s.context.context_type for s in segments}
        assert SegmentContextType.FRONTMATTER in context_types
        assert SegmentContextType.HEADING in context_types

    def test_empty_document(self, simple_profile: SiteProfile) -> None:
        """Test extracting from empty document."""
        parser = HugoParser()
        doc = parser.parse_string("")

        extractor = SegmentExtractor(simple_profile)
        segments = extractor.extract_all(doc)

        assert len(segments) == 0

    def test_segment_ids_unique(self, simple_profile: SiteProfile) -> None:
        """Test that segment IDs are unique within document."""
        parser = HugoParser()
        content = """---
title: "Unique Test"
---

# Heading One

Paragraph one.

# Heading Two

Paragraph two.
"""
        doc = parser.parse_string(content)

        extractor = SegmentExtractor(simple_profile)
        segments = extractor.extract_all(doc)

        segment_ids = [s.id for s in segments]
        # All IDs should be unique
        assert len(segment_ids) == len(set(segment_ids))
