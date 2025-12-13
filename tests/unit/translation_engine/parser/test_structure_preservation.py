"""
Tests for structure preservation through the full translation pipeline.

Verifies that YAML comments, literal blocks, and quote styles are preserved
through the HugoParser -> MarkdownReconstructor -> YAMLFormatter pipeline.
"""
import pytest
from io import StringIO

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from src.translation_engine.parser.hugo_parser import HugoParser
from src.translation_engine.reconstructor.markdown_reconstructor import MarkdownReconstructor
from src.translation_engine.reconstructor.yaml_formatter import YAMLFormatter
from src.utils.models import BodyRules, FrontmatterMode, FrontmatterRule, SiteProfile


SAMPLE_WITH_FULL_STRUCTURE = '''---
# Static
layout: "plugin"
cart_id: ""

# Head
head_title: "Test Title"
head_description: "Test Description"

# Overview
overview:
  enable: true
  title: "Overview Title"
  content: |
    This is a multi-line literal block.
    It should preserve newlines and formatting.

# Body
body:
  enable: true
  block:
    - title_left: "First Block"
      content_left: |
        First block content
        with multiple lines
    - title_left: "Second Block"
      content_left: |
        Second block content
---

Body content here.
'''


@pytest.fixture
def test_profile() -> SiteProfile:
    """Create test profile for reconstruction."""
    return SiteProfile(
        site_id="test-site",
        content_roots=["/content/test"],
        default_source_lang="en",
        target_langs=["bg"],
        frontmatter={
            "layout": FrontmatterRule(mode=FrontmatterMode.PASSTHROUGH),
            "cart_id": FrontmatterRule(mode=FrontmatterMode.PASSTHROUGH),
            "head_title": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
            "head_description": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
            "overview.title": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
            "overview.content": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
            "body.block.title_left": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
            "body.block.content_left": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
        },
        body=BodyRules(
            translate_markdown=True,
            preserve_blocks=["block_code"],
            preserve_patterns=[],
            placeholder_syntax=[],
        ),
    )


class TestCommentedMapPreservation:
    """Test that CommentedMap is preserved through reconstruction."""

    def test_parser_returns_commented_map(self):
        """Parser should return CommentedMap for YAML with comments."""
        parser = HugoParser()
        doc = parser.parse_string(SAMPLE_WITH_FULL_STRUCTURE)

        assert isinstance(doc.frontmatter, CommentedMap), \
            f"Expected CommentedMap, got {type(doc.frontmatter).__name__}"

    def test_copy_commented_map_preserves_type(self, test_profile):
        """_copy_commented_map should return CommentedMap."""
        parser = HugoParser()
        reconstructor = MarkdownReconstructor(test_profile)

        doc = parser.parse_string(SAMPLE_WITH_FULL_STRUCTURE)
        copied = reconstructor._copy_commented_map(doc.frontmatter)

        assert isinstance(copied, CommentedMap), \
            f"Expected CommentedMap, got {type(copied).__name__}"

    def test_copy_commented_map_preserves_comments(self, test_profile):
        """_copy_commented_map should preserve YAML comments."""
        parser = HugoParser()
        reconstructor = MarkdownReconstructor(test_profile)

        doc = parser.parse_string(SAMPLE_WITH_FULL_STRUCTURE)
        copied = reconstructor._copy_commented_map(doc.frontmatter)

        # Dump and check for comments
        yaml = YAML()
        yaml.preserve_quotes = True
        stream = StringIO()
        yaml.dump(copied, stream)
        output = stream.getvalue()

        assert '# Static' in output, "Static comment should be preserved"
        assert '# Head' in output, "Head comment should be preserved"
        assert '# Overview' in output, "Overview comment should be preserved"
        assert '# Body' in output, "Body comment should be preserved"

    def test_reconstruct_frontmatter_preserves_commented_map(self, test_profile):
        """reconstruct_frontmatter should preserve CommentedMap type."""
        parser = HugoParser()
        reconstructor = MarkdownReconstructor(test_profile)

        doc = parser.parse_string(SAMPLE_WITH_FULL_STRUCTURE)
        result = reconstructor.reconstruct_frontmatter(doc.frontmatter, {}, "bg")

        assert isinstance(result, CommentedMap), \
            f"Expected CommentedMap, got {type(result).__name__}"

    def test_reconstruct_frontmatter_preserves_comments(self, test_profile):
        """reconstruct_frontmatter should preserve YAML comments."""
        parser = HugoParser()
        reconstructor = MarkdownReconstructor(test_profile)

        doc = parser.parse_string(SAMPLE_WITH_FULL_STRUCTURE)
        result = reconstructor.reconstruct_frontmatter(doc.frontmatter, {}, "bg")

        # Dump and check for comments
        yaml = YAML()
        yaml.preserve_quotes = True
        stream = StringIO()
        yaml.dump(result, stream)
        output = stream.getvalue()

        assert '# Static' in output, "Static comment should be preserved"
        assert '# Head' in output, "Head comment should be preserved"


class TestLiteralBlockPreservation:
    """Test that literal blocks (|) are preserved through reconstruction."""

    def test_literal_blocks_in_parsed_frontmatter(self):
        """Literal blocks should be recognized in parsed frontmatter."""
        parser = HugoParser()
        doc = parser.parse_string(SAMPLE_WITH_FULL_STRUCTURE)

        # Check that literal block content contains newlines
        overview_content = doc.frontmatter['overview']['content']
        assert '\n' in overview_content, "Literal block should preserve newlines"

    def test_literal_blocks_in_output(self, test_profile):
        """Literal blocks should use | style in output."""
        parser = HugoParser()
        reconstructor = MarkdownReconstructor(test_profile)

        doc = parser.parse_string(SAMPLE_WITH_FULL_STRUCTURE)
        result = reconstructor.reconstruct_frontmatter(doc.frontmatter, {}, "bg")

        # Format and check
        output = YAMLFormatter.format_frontmatter(result)

        # Should have literal block indicators
        assert 'content: |' in output or 'content: |-' in output, \
            f"Literal block style should be preserved. Got:\n{output}"


class TestFullPipelinePreservation:
    """Test full pipeline preserves structure."""

    def test_full_document_reconstruction(self, test_profile):
        """Full document reconstruction should preserve all structure."""
        parser = HugoParser()
        reconstructor = MarkdownReconstructor(test_profile)

        doc = parser.parse_string(SAMPLE_WITH_FULL_STRUCTURE)

        # Reconstruct without translations (structure preservation test)
        result = reconstructor.reconstruct_document(doc, {}, "bg")

        # Check comments are in final output
        assert '# Static' in result, "Static comment should be in final output"
        assert '# Head' in result, "Head comment should be in final output"

        # Check literal blocks are preserved
        assert 'content: |' in result or 'content: |-' in result, \
            "Literal blocks should be preserved"

    def test_structure_drift_measurement(self, test_profile):
        """Structure drift should be minimal."""
        parser = HugoParser()
        reconstructor = MarkdownReconstructor(test_profile)

        doc = parser.parse_string(SAMPLE_WITH_FULL_STRUCTURE)
        result = reconstructor.reconstruct_document(doc, {}, "bg")

        # Count structural elements in original
        original_lines = SAMPLE_WITH_FULL_STRUCTURE.split('\n')
        original_comments = len([l for l in original_lines if l.strip().startswith('#')])
        original_literal = SAMPLE_WITH_FULL_STRUCTURE.count(': |')

        # Count in result
        result_lines = result.split('\n')
        result_comments = len([l for l in result_lines if l.strip().startswith('#')])
        result_literal = result.count(': |') + result.count(': |-')

        # Calculate drift
        comment_retention = result_comments / original_comments * 100 if original_comments > 0 else 100
        literal_retention = result_literal / original_literal * 100 if original_literal > 0 else 100

        # Assert minimal drift
        assert comment_retention >= 80, f"Comment retention {comment_retention:.1f}% should be >= 80%"
        assert literal_retention >= 80, f"Literal block retention {literal_retention:.1f}% should be >= 80%"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
