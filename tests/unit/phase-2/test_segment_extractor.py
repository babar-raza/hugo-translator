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


class TestArrayExtraction:
    """Test array-based field extraction (SE-01, SE-03)."""

    @pytest.fixture
    def array_profile(self) -> SiteProfile:
        """Create profile with array-based fields like products.aspose.net."""
        return SiteProfile(
            site_id="test-array-site",
            content_roots=["/content/test"],
            default_source_lang="en",
            target_langs=["de", "fr"],
            frontmatter={
                "title": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
                "body.block.title_left": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
                "body.block.content_left": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
                "body.block.title_right": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
                "content.block.title": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
                "faq.list.question": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
                "faq.list.answer": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
            },
            body=BodyRules(
                translate_markdown=True,
                preserve_blocks=[],
                preserve_patterns=[],
                placeholder_syntax=[],
            ),
        )

    def test_extract_single_level_array(self, array_profile: SiteProfile) -> None:
        """Test extracting from simple array structure."""
        extractor = SegmentExtractor(array_profile)
        frontmatter = {
            "title": "Main Title",
            "faq": {
                "list": [
                    {"question": "Q1", "answer": "A1"},
                    {"question": "Q2", "answer": "A2"},
                    {"question": "Q3", "answer": "A3"},
                ]
            }
        }

        segments = extractor.extract_from_frontmatter(frontmatter, "en")

        # Should extract: 1 title + 3 questions + 3 answers = 7 segments
        assert len(segments) == 7

        # Check questions extracted
        questions = [s for s in segments if s.context.frontmatter_key and "question" in s.context.frontmatter_key]
        assert len(questions) == 3
        assert any(s.source_text == "Q1" for s in questions)
        assert any(s.source_text == "Q2" for s in questions)
        assert any(s.source_text == "Q3" for s in questions)

        # Check answers extracted
        answers = [s for s in segments if s.context.frontmatter_key and "answer" in s.context.frontmatter_key]
        assert len(answers) == 3
        assert any(s.source_text == "A1" for s in answers)
        assert any(s.source_text == "A2" for s in answers)

        # Verify indexed keys are generated
        question_keys = [s.context.frontmatter_key for s in questions]
        assert any("[0]" in k for k in question_keys)
        assert any("[1]" in k for k in question_keys)
        assert any("[2]" in k for k in question_keys)

    def test_extract_nested_array_body_block(self, array_profile: SiteProfile) -> None:
        """Test extracting from nested array like body.block."""
        extractor = SegmentExtractor(array_profile)
        frontmatter = {
            "body": {
                "block": [
                    {
                        "title_left": "First Block Left Title",
                        "content_left": "First Block Left Content",
                        "title_right": "First Block Right Title",
                    },
                    {
                        "title_left": "Second Block Left Title",
                        "content_left": "Second Block Left Content",
                        "title_right": "Second Block Right Title",
                    },
                ]
            }
        }

        segments = extractor.extract_from_frontmatter(frontmatter, "en")

        # Should extract: 2 blocks × 3 fields = 6 segments
        assert len(segments) == 6

        # Check first block
        first_left_title = [s for s in segments if s.source_text == "First Block Left Title"]
        assert len(first_left_title) == 1
        assert "[0]" in first_left_title[0].context.frontmatter_key

        # Check second block
        second_left_title = [s for s in segments if s.source_text == "Second Block Left Title"]
        assert len(second_left_title) == 1
        assert "[1]" in second_left_title[0].context.frontmatter_key

        # Verify all indexed keys
        keys = [s.context.frontmatter_key for s in segments]
        assert any("body.block[0].title_left" in k for k in keys)
        assert any("body.block[1].title_left" in k for k in keys)

    def test_extract_multiple_array_fields(self, array_profile: SiteProfile) -> None:
        """Test extracting from multiple independent array fields."""
        extractor = SegmentExtractor(array_profile)
        frontmatter = {
            "body": {
                "block": [
                    {"title_left": "Body Block 1"},
                    {"title_left": "Body Block 2"},
                ]
            },
            "content": {
                "block": [
                    {"title": "Content Block 1"},
                    {"title": "Content Block 2"},
                    {"title": "Content Block 3"},
                ]
            },
        }

        segments = extractor.extract_from_frontmatter(frontmatter, "en")

        # Should extract: 2 body blocks + 3 content blocks = 5 segments
        assert len(segments) == 5

        # Check body.block extraction
        body_segments = [s for s in segments if s.context.frontmatter_key and "body.block" in s.context.frontmatter_key]
        assert len(body_segments) == 2

        # Check content.block extraction
        content_segments = [s for s in segments if s.context.frontmatter_key and "content.block" in s.context.frontmatter_key]
        assert len(content_segments) == 3

    def test_extract_empty_array(self, array_profile: SiteProfile) -> None:
        """Test handling of empty arrays."""
        extractor = SegmentExtractor(array_profile)
        frontmatter = {
            "title": "Main Title",
            "faq": {
                "list": []  # Empty array
            }
        }

        segments = extractor.extract_from_frontmatter(frontmatter, "en")

        # Should extract only title (no array items)
        assert len(segments) == 1
        assert segments[0].source_text == "Main Title"

    def test_extract_array_with_missing_fields(self, array_profile: SiteProfile) -> None:
        """Test handling arrays where some items lack expected fields."""
        extractor = SegmentExtractor(array_profile)
        frontmatter = {
            "faq": {
                "list": [
                    {"question": "Q1", "answer": "A1"},
                    {"question": "Q2"},  # Missing answer
                    {"answer": "A3"},    # Missing question
                ]
            }
        }

        segments = extractor.extract_from_frontmatter(frontmatter, "en")

        # Should extract: 2 questions + 2 answers = 4 segments
        assert len(segments) == 4

        questions = [s for s in segments if "question" in s.context.frontmatter_key]
        answers = [s for s in segments if "answer" in s.context.frontmatter_key]

        assert len(questions) == 2
        assert len(answers) == 2

    def test_array_extraction_preserves_order(self, array_profile: SiteProfile) -> None:
        """Test that array item order is preserved in indexed keys."""
        extractor = SegmentExtractor(array_profile)
        frontmatter = {
            "faq": {
                "list": [
                    {"question": "First"},
                    {"question": "Second"},
                    {"question": "Third"},
                    {"question": "Fourth"},
                    {"question": "Fifth"},
                ]
            }
        }

        segments = extractor.extract_from_frontmatter(frontmatter, "en")

        # Extract indices from keys
        for i in range(5):
            matching = [s for s in segments if f"[{i}]" in s.context.frontmatter_key]
            assert len(matching) == 1, f"Should have exactly one segment with index [{i}]"

    def test_get_all_nested_values_direct(self, array_profile: SiteProfile) -> None:
        """Test _get_all_nested_values() method directly."""
        extractor = SegmentExtractor(array_profile)
        data = {
            "body": {
                "block": [
                    {"title_left": "A", "content_left": "Content A"},
                    {"title_left": "B", "content_left": "Content B"},
                ]
            }
        }

        # Test extracting title_left
        results = extractor._get_all_nested_values(data, "body.block.title_left")

        assert len(results) == 2
        keys = [k for k, v in results]
        values = [v for k, v in results]

        assert "body.block[0].title_left" in keys
        assert "body.block[1].title_left" in keys
        assert "A" in values
        assert "B" in values

    def test_integration_products_aspose_structure(self, array_profile: SiteProfile) -> None:
        """Integration test with products.aspose.net-like structure."""
        extractor = SegmentExtractor(array_profile)

        # Simulate real products.aspose.net frontmatter structure
        frontmatter = {
            "title": "Product Page",
            "body": {
                "block": [
                    {
                        "title_left": "Feature 1",
                        "content_left": "Feature 1 description",
                        "title_right": "Demo 1",
                    },
                    {
                        "title_left": "Feature 2",
                        "content_left": "Feature 2 description",
                        "title_right": "Demo 2",
                    },
                ]
            },
            "faq": {
                "list": [
                    {"question": "How to install?", "answer": "Use NuGet package manager"},
                    {"question": "What platforms?", "answer": ".NET Framework 4.6.1+"},
                ]
            },
        }

        segments = extractor.extract_from_frontmatter(frontmatter, "en")

        # Count expected segments:
        # - 1 title
        # - 2 blocks × 3 fields = 6
        # - 2 FAQ items × 2 fields = 4
        # Total: 11
        assert len(segments) == 11

        # Verify body.block segments
        body_segments = [s for s in segments if s.context.frontmatter_key and "body.block" in s.context.frontmatter_key]
        assert len(body_segments) == 6

        # Verify faq.list segments
        faq_segments = [s for s in segments if s.context.frontmatter_key and "faq.list" in s.context.frontmatter_key]
        assert len(faq_segments) == 4

        # Verify content
        assert any(s.source_text == "Feature 1" for s in segments)
        assert any(s.source_text == "How to install?" for s in segments)
        assert any(s.source_text == "Use NuGet package manager" for s in segments)
