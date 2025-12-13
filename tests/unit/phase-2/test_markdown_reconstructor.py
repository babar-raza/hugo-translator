"""
Unit tests for Markdown Reconstructor.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from translation_engine.extractor import SegmentExtractor
from translation_engine.parser import HugoParser
from translation_engine.reconstructor import MarkdownReconstructor
from translation_engine.reconstructor.yaml_formatter import YAMLFormatter
from utils.models import BodyRules, FrontmatterMode, FrontmatterRule, SiteProfile


class TestYAMLFormatter:
    """Test YAML formatting utilities."""

    def test_format_frontmatter(self) -> None:
        """Test YAML frontmatter formatting."""
        formatter = YAMLFormatter()
        data = {
            "title": "Test Title",
            "draft": False,
            "tags": ["tag1", "tag2"],
        }

        result = formatter.format_frontmatter(data)

        assert result.startswith("---\n")
        assert result.endswith("---\n")
        assert "title: Test Title" in result
        assert "draft: false" in result

    def test_set_nested_value(self) -> None:
        """Test setting nested dictionary values."""
        formatter = YAMLFormatter()
        data = {}

        formatter.set_nested_value(data, "banner.title", "Hello")
        assert data == {"banner": {"title": "Hello"}}

        formatter.set_nested_value(data, "banner.subtitle", "World")
        assert data == {"banner": {"title": "Hello", "subtitle": "World"}}

    def test_get_nested_value(self) -> None:
        """Test getting nested dictionary values."""
        formatter = YAMLFormatter()
        data = {
            "banner": {
                "title": "Hello",
                "content": "World",
            }
        }

        assert formatter.get_nested_value(data, "banner.title") == "Hello"
        assert formatter.get_nested_value(data, "banner.content") == "World"
        assert formatter.get_nested_value(data, "missing.key", "default") == "default"


class TestMarkdownReconstructor:
    """Test MarkdownReconstructor functionality."""

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
                "lang": FrontmatterRule(mode=FrontmatterMode.COMPUTED),
            },
            body=BodyRules(
                translate_markdown=True,
                preserve_blocks=["block_code"],
                preserve_patterns=[],
                placeholder_syntax=[r"\{\{<.*?>\}\}", r"\{\{%.*?%\}\}"],
            ),
        )

    def test_reconstructor_initialization(self, simple_profile: SiteProfile) -> None:
        """Test reconstructor can be initialized."""
        reconstructor = MarkdownReconstructor(simple_profile)
        assert reconstructor is not None
        assert reconstructor.site_profile == simple_profile

    def test_reconstruct_frontmatter_translate(
        self, simple_profile: SiteProfile
    ) -> None:
        """Test reconstructing frontmatter with translated fields."""
        reconstructor = MarkdownReconstructor(simple_profile)
        parser = HugoParser()
        extractor = SegmentExtractor(simple_profile)

        # Original document
        content = """---
title: "Hello World"
description: "A test document"
draft: false
---

Content here.
"""
        doc = parser.parse_string(content)

        # Extract segments
        segments = extractor.extract_all(doc, "en")

        # Create mock translations
        translations = {}
        for seg in segments:
            if seg.context.frontmatter_key == "title":
                translations[seg.id] = "Hola Mundo"
            elif seg.context.frontmatter_key == "description":
                translations[seg.id] = "Un documento de prueba"

        # Reconstruct frontmatter
        result = reconstructor.reconstruct_frontmatter(
            doc.frontmatter, translations, "es"
        )

        assert result["title"] == "Hola Mundo"
        assert result["description"] == "Un documento de prueba"
        assert result["draft"] is False  # Passthrough

    def test_reconstruct_frontmatter_list(
        self, simple_profile: SiteProfile
    ) -> None:
        """Test reconstructing list frontmatter fields."""
        reconstructor = MarkdownReconstructor(simple_profile)
        parser = HugoParser()
        extractor = SegmentExtractor(simple_profile)

        content = """---
title: "Test"
tags:
  - python
  - hugo
---

Content.
"""
        doc = parser.parse_string(content)
        segments = extractor.extract_all(doc, "en")

        # Create translations
        translations = {}
        for seg in segments:
            if seg.context.frontmatter_key == "tags[0]":
                translations[seg.id] = "pitón"
            elif seg.context.frontmatter_key == "tags[1]":
                translations[seg.id] = "hugo"
            elif seg.context.frontmatter_key == "title":
                translations[seg.id] = "Prueba"

        result = reconstructor.reconstruct_frontmatter(
            doc.frontmatter, translations, "es"
        )

        assert result["tags"] == ["pitón", "hugo"]

    def test_reconstruct_body_paragraphs(self, simple_profile: SiteProfile) -> None:
        """Test reconstructing body paragraphs."""
        reconstructor = MarkdownReconstructor(simple_profile)
        parser = HugoParser()
        extractor = SegmentExtractor(simple_profile)

        content = """# Heading

This is a paragraph.

Another paragraph here.
"""
        doc = parser.parse_string(content)
        segments = extractor.extract_all(doc, "en")

        # Create translations and segment map
        translations = {}
        segment_map = {}
        for seg in segments:
            if seg.context.node_id:
                segment_map[seg.context.node_id] = seg.id

            if "Heading" in seg.source_text:
                translations[seg.id] = "Título"
            elif "This is a paragraph" in seg.source_text:
                translations[seg.id] = "Este es un párrafo."
            elif "Another paragraph" in seg.source_text:
                translations[seg.id] = "Otro párrafo aquí."

        # Set segment map
        reconstructor._segment_map = segment_map
        result = reconstructor.reconstruct_body(doc.ast, translations, "es")

        assert "# Título" in result
        assert "Este es un párrafo." in result
        assert "Otro párrafo aquí." in result

    def test_reconstruct_preserves_code_blocks(
        self, simple_profile: SiteProfile
    ) -> None:
        """Test that code blocks are preserved unchanged."""
        reconstructor = MarkdownReconstructor(simple_profile)
        parser = HugoParser()

        content = """# Heading

```python
def hello():
    print("Hello")
```

Text after code.
"""
        doc = parser.parse_string(content)
        result = reconstructor.reconstruct_body(doc.ast, {}, "es")

        assert "```python" in result
        assert 'def hello():' in result
        assert 'print("Hello")' in result

    def test_reconstruct_full_document(self, simple_profile: SiteProfile) -> None:
        """Test reconstructing complete document."""
        reconstructor = MarkdownReconstructor(simple_profile)
        parser = HugoParser()
        extractor = SegmentExtractor(simple_profile)

        content = """---
title: "Test Document"
draft: false
---

# Introduction

This is the introduction.
"""
        doc = parser.parse_string(content)
        segments = extractor.extract_all(doc, "en")

        # Create translations and segment map
        translations = {}
        segment_map = {}
        for seg in segments:
            if seg.context.node_id:
                segment_map[seg.context.node_id] = seg.id

            if seg.context.frontmatter_key == "title":
                translations[seg.id] = "Documento de Prueba"
            elif "Introduction" in seg.source_text:
                translations[seg.id] = "Introducción"
            elif "This is the introduction" in seg.source_text:
                translations[seg.id] = "Esta es la introducción."

        result = reconstructor.reconstruct_document(doc, translations, "es", segment_map)

        # Check frontmatter
        assert "---" in result
        assert "title: Documento de Prueba" in result
        assert "draft: false" in result

        # Check body
        assert "# Introducción" in result
        assert "Esta es la introducción." in result

    def test_reconstruct_with_no_translations(
        self, simple_profile: SiteProfile
    ) -> None:
        """Test reconstruction with no translations (fallback to original)."""
        reconstructor = MarkdownReconstructor(simple_profile)
        parser = HugoParser()

        content = """---
title: "Original Title"
---

# Original Heading

Original paragraph.
"""
        doc = parser.parse_string(content)

        # Empty translations
        result = reconstructor.reconstruct_document(doc, {}, "es")

        # Should fall back to original content
        assert "title: Original Title" in result
        # Body should attempt reconstruction even without translations
        assert "# Original Heading" in result or "Original Heading" in result

    def test_computed_field_lang(self, simple_profile: SiteProfile) -> None:
        """Test computed lang field."""
        reconstructor = MarkdownReconstructor(simple_profile)

        original = {"title": "Test", "draft": False}
        result = reconstructor.reconstruct_frontmatter(original, {}, "fr")

        assert result["lang"] == "fr"


class TestRoundtrip:
    """Test roundtrip: parse → extract → translate → reconstruct."""

    @pytest.fixture
    def roundtrip_profile(self) -> SiteProfile:
        """Profile for roundtrip testing."""
        return SiteProfile(
            site_id="roundtrip-test",
            content_roots=["/content/test"],
            default_source_lang="en",
            target_langs=["es"],
            frontmatter={
                "title": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
                "description": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
                "draft": FrontmatterRule(mode=FrontmatterMode.PASSTHROUGH),
                "date": FrontmatterRule(mode=FrontmatterMode.PASSTHROUGH),
            },
            body=BodyRules(
                translate_markdown=True,
                preserve_blocks=["block_code"],
                preserve_patterns=[],
                placeholder_syntax=[],
            ),
        )

    def test_roundtrip_simple(self, roundtrip_profile: SiteProfile) -> None:
        """Test simple roundtrip with identity translation."""
        parser = HugoParser()
        extractor = SegmentExtractor(roundtrip_profile)
        reconstructor = MarkdownReconstructor(roundtrip_profile)

        original = """---
title: "Simple Test"
description: "A simple test"
draft: false
date: 2024-01-01
---

# Heading

This is a paragraph.
"""
        # Parse
        doc = parser.parse_string(original)

        # Extract
        segments = extractor.extract_all(doc, "en")

        # Identity translation (translate to same text)
        translations = {seg.id: seg.source_text for seg in segments}

        # Reconstruct
        result = reconstructor.reconstruct_document(doc, translations, "en")

        # Verify key components are present
        assert "title: Simple Test" in result
        assert "description: A simple test" in result
        assert "draft: false" in result
        assert "# Heading" in result
        assert "This is a paragraph" in result

    def test_roundtrip_with_code(self, roundtrip_profile: SiteProfile) -> None:
        """Test roundtrip with code blocks."""
        parser = HugoParser()
        extractor = SegmentExtractor(roundtrip_profile)
        reconstructor = MarkdownReconstructor(roundtrip_profile)

        original = """---
title: "Code Test"
---

# Example

Here's some code:

```python
def hello():
    return "Hello"
```

That's the code.
"""
        doc = parser.parse_string(original)
        segments = extractor.extract_all(doc, "en")
        translations = {seg.id: seg.source_text for seg in segments}
        result = reconstructor.reconstruct_document(doc, translations, "en")

        # Check code block preservation
        assert "```python" in result
        assert "def hello():" in result
        assert 'return "Hello"' in result

    def test_roundtrip_formatting(self, roundtrip_profile: SiteProfile) -> None:
        """Test that basic formatting is preserved."""
        parser = HugoParser()
        extractor = SegmentExtractor(roundtrip_profile)
        reconstructor = MarkdownReconstructor(roundtrip_profile)

        original = """---
title: "Format Test"
---

# Heading 1

## Heading 2

### Heading 3

Paragraph one.

Paragraph two.
"""
        doc = parser.parse_string(original)
        segments = extractor.extract_all(doc, "en")
        translations = {seg.id: seg.source_text for seg in segments}
        result = reconstructor.reconstruct_document(doc, translations, "en")

        # Check heading levels preserved
        assert "# Heading 1" in result
        assert "## Heading 2" in result
        assert "### Heading 3" in result

        # Check paragraphs present
        assert "Paragraph one" in result
        assert "Paragraph two" in result
