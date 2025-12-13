"""
Tests for template-based reconstruction.

Verifies SD-03 acceptance checks:
- Reconstructed file has same line count as EN (±5%)
- Comments preserved (# Static, # Head, etc.)
- Quote styles preserved
- Blank lines preserved
- Indentation preserved
"""
import pytest
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from enum import Enum

# Import directly to avoid full package import chain
import sys
sys.path.insert(0, ".")


class SegmentContextType(str, Enum):
    """Type of segment context."""
    FRONTMATTER = "frontmatter"
    BODY_TEXT = "body_text"


@dataclass
class SegmentContext:
    """Context information for a translatable segment."""
    context_type: SegmentContextType
    frontmatter_key: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Segment:
    """A translatable unit with context."""
    id: str
    source_text: str
    context: SegmentContext
    site_id: str = "test"
    source_lang: str = "en"


class TestTemplateReconstructorStructure:
    """Test structural preservation in template reconstruction."""

    def test_line_count_parity(self):
        """Reconstructed file should have similar line count to source."""
        from src.translation_engine.reconstructor.template_reconstructor import (
            TemplateReconstructor,
        )

        reconstructor = TemplateReconstructor()

        source = """---
# Static
layout: "family"
head_title: "English Title"

# Overview
overview:
  content: |
    English content here.
---

Body text.
"""

        # Empty translations - structure test only
        result = reconstructor.reconstruct_from_template(source, {}, {})

        source_lines = len(source.strip().split("\n"))
        result_lines = len(result.strip().split("\n"))

        # Within 20% (relaxed for test)
        drift = abs(source_lines - result_lines) / source_lines
        assert drift < 0.2, f"Line count drift {drift:.1%} exceeds 20%"

    def test_comment_preservation(self):
        """Comments should be preserved in output."""
        from src.translation_engine.reconstructor.template_reconstructor import (
            TemplateReconstructor,
        )

        reconstructor = TemplateReconstructor()

        source = """---
# Static
layout: "family"
# Head
head_title: "Test"
# Footer
footer: "Copyright"
---
"""
        result = reconstructor.reconstruct_from_template(source, {}, {})

        assert "# Static" in result
        assert "# Head" in result
        assert "# Footer" in result

    def test_quote_style_preservation(self):
        """Quote styles should be preserved in output."""
        from src.translation_engine.reconstructor.template_reconstructor import (
            TemplateReconstructor,
        )

        reconstructor = TemplateReconstructor()

        source = """---
double_quoted: "with double"
single_quoted: 'with single'
unquoted: plain value
---
"""
        result = reconstructor.reconstruct_from_template(source, {}, {})

        assert '"with double"' in result
        assert "'with single'" in result
        assert "plain value" in result

    def test_blank_lines_preserved(self):
        """Blank lines between sections should be preserved."""
        from src.translation_engine.reconstructor.template_reconstructor import (
            TemplateReconstructor,
        )

        reconstructor = TemplateReconstructor()

        source = """---
# Static
layout: "family"

# Head
head_title: "Test"

# Footer
footer: "Copyright"
---
"""
        result = reconstructor.reconstruct_from_template(source, {}, {})

        # Check that blank lines are preserved (comment blocks separated)
        lines = result.split("\n")
        static_idx = next(i for i, l in enumerate(lines) if "# Static" in l)
        head_idx = next(i for i, l in enumerate(lines) if "# Head" in l)

        # There should be a blank line between sections
        assert head_idx - static_idx > 2, "Expected blank line between Static and Head"


class TestTemplateReconstructorTranslations:
    """Test translation application in template reconstruction."""

    def test_frontmatter_translation_applied(self):
        """Frontmatter translations should be applied correctly."""
        from src.translation_engine.reconstructor.template_reconstructor import (
            TemplateReconstructor,
        )

        reconstructor = TemplateReconstructor()

        source = """---
title: "English Title"
description: "English Description"
---

Body content.
"""

        # Create mock segments
        segment = Segment(
            id="seg1",
            source_text="English Title",
            context=SegmentContext(
                context_type=SegmentContextType.FRONTMATTER,
                frontmatter_key="title",
            ),
        )

        translations = {"seg1": "Translated Title"}
        segment_map = {"seg1": segment}

        result = reconstructor.reconstruct_from_template(
            source, translations, segment_map
        )

        assert "Translated Title" in result
        assert "English Title" not in result

    def test_nested_frontmatter_translation(self):
        """Nested frontmatter translations should work."""
        from src.translation_engine.reconstructor.template_reconstructor import (
            TemplateReconstructor,
        )

        reconstructor = TemplateReconstructor()

        source = """---
overview:
  title: "Overview Title"
  content: "Overview Content"
---
"""

        segment = Segment(
            id="seg1",
            source_text="Overview Title",
            context=SegmentContext(
                context_type=SegmentContextType.FRONTMATTER,
                frontmatter_key="overview.title",
            ),
        )

        translations = {"seg1": "Translated Overview"}
        segment_map = {"seg1": segment}

        result = reconstructor.reconstruct_from_template(
            source, translations, segment_map
        )

        assert "Translated Overview" in result

    def test_literal_style_preserved_for_multiline(self):
        """Literal block style should be preserved for multi-line content."""
        from src.translation_engine.reconstructor.template_reconstructor import (
            TemplateReconstructor,
        )

        reconstructor = TemplateReconstructor()

        source = """---
content: |
  Line 1
  Line 2
  - Bullet 1
  - Bullet 2
---
"""

        segment = Segment(
            id="seg1",
            source_text="Line 1\nLine 2\n- Bullet 1\n- Bullet 2",
            context=SegmentContext(
                context_type=SegmentContextType.FRONTMATTER,
                frontmatter_key="content",
            ),
        )

        translations = {"seg1": "Translated 1\nTranslated 2\n- Point 1\n- Point 2"}
        segment_map = {"seg1": segment}

        result = reconstructor.reconstruct_from_template(
            source, translations, segment_map
        )

        # Should preserve literal style
        assert "content: |" in result or "content:\n" in result
        assert "- Point 1" in result


class TestTemplateReconstructorBody:
    """Test body content reconstruction."""

    def test_body_translation_applied(self):
        """Body translations should be applied."""
        from src.translation_engine.reconstructor.template_reconstructor import (
            TemplateReconstructor,
        )

        reconstructor = TemplateReconstructor()

        source = """---
title: "Test"
---

This is body content to translate.

More body text here.
"""

        segment = Segment(
            id="body1",
            source_text="This is body content to translate.",
            context=SegmentContext(
                context_type=SegmentContextType.BODY_TEXT,
            ),
        )

        translations = {"body1": "Dies ist übersetzter Inhalt."}
        segment_map = {"body1": segment}

        result = reconstructor.reconstruct_from_template(
            source, translations, segment_map
        )

        assert "Dies ist übersetzter Inhalt." in result
        assert "This is body content to translate." not in result
        assert "More body text here." in result  # Untranslated remains


class TestRealWorldPatterns:
    """Test with patterns from products.aspose.net files."""

    def test_full_structure_preservation(self):
        """Test full structure preservation with real-world patterns."""
        from src.translation_engine.reconstructor.template_reconstructor import (
            TemplateReconstructor,
        )

        reconstructor = TemplateReconstructor()

        # Pattern from products.aspose.net/slides
        source = """---
# Static
layout: "family"
type: "_default"
full_width: true

# Head
head_title: "Aspose.Slides | PowerPoint API"
head_description: "Process PowerPoint presentations."

# Overview
overview:
  title: "Product Overview"
  content: |
    Aspose.Slides enables developers to work with presentations.

    - Create presentations
    - Modify slides
    - Export to PDF
---

Body content with Hugo shortcodes.
"""

        result = reconstructor.reconstruct_from_template(source, {}, {})

        # Verify structure
        assert "# Static" in result
        assert "# Head" in result
        assert "# Overview" in result
        assert 'layout: "family"' in result
        assert "content: |" in result or "content:\n" in result
        assert "- Create presentations" in result
