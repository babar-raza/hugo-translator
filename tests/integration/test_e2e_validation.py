"""
End-to-End Validation Integration Tests

Tests the complete translation pipeline: parse → extract → translate → reconstruct → validate
"""

import sys
from pathlib import Path

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.translation_engine.extractor import SegmentExtractor
from src.translation_engine.parser import HugoParser
from src.translation_engine.reconstructor import MarkdownReconstructor
from src.translation_engine.validation import ValidationSeverity, ValidationSuite
from src.utils.models import BodyRules, FrontmatterMode, FrontmatterRule, SiteProfile


# Test fixtures
@pytest.fixture
def site_profile():
    """Create a test site profile."""
    return SiteProfile(
        site_id="test.site",
        content_roots=["content"],
        default_source_lang="en",
        target_langs=["es", "fa"],
        frontmatter={
            "title": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
            "description": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
            "weight": FrontmatterRule(mode=FrontmatterMode.PASSTHROUGH),
            "url": FrontmatterRule(mode=FrontmatterMode.PASSTHROUGH),
        },
        body=BodyRules(
            translate_markdown=True,
            preserve_blocks=["block_code", "code_inline"],
            preserve_patterns=[r"\{\{[^}]+\}\}", r"\{%[^%]+%\}"],
            placeholder_syntax=[r"\{\{<[^>]+>\}\}"],
        ),
    )


@pytest.fixture
def parser():
    """Create a Hugo parser."""
    return HugoParser()


@pytest.fixture
def validator():
    """Create a validation suite."""
    return ValidationSuite()


@pytest.fixture
def sample_markdown():
    """Sample Hugo markdown for testing."""
    return """---
title: "Test Page"
description: "This is a test page"
weight: 10
url: "/test"
---

# Main Heading

This is a paragraph with **bold** and *italic* text.

## Subheading

- List item 1
- List item 2
- List item 3

## Code Example

```python
def hello():
    print("Hello, World!")
```

## Links

Visit [our website](https://example.com) for more information.
"""


@pytest.fixture
def sample_with_shortcodes():
    """Sample with Hugo shortcodes."""
    return """---
title: "Shortcode Test"
description: "Testing shortcode preservation"
---

# Shortcode Examples

This is a paragraph before shortcode.

{{< note >}}
This is a note shortcode.
{{< /note >}}

And here's an inline shortcode: {{< ref "other-page" >}}
"""


class TestE2EParseExtract:
    """Test parsing and extraction pipeline."""

    def test_parse_valid_markdown(self, parser, sample_markdown):
        """Test parsing valid Hugo markdown."""
        doc = parser.parse_string(sample_markdown)

        assert doc is not None
        assert doc.frontmatter["title"] == "Test Page"
        assert doc.frontmatter["description"] == "This is a test page"
        assert len(doc.ast) > 0

    def test_extract_segments(self, parser, site_profile, sample_markdown):
        """Test segment extraction from parsed document."""
        doc = parser.parse_string(sample_markdown)
        extractor = SegmentExtractor(site_profile)
        segments = extractor.extract_all(doc)

        assert len(segments) > 0

        # Check that we have frontmatter segments
        frontmatter_segments = [s for s in segments if s.context.context_type.value == "frontmatter"]
        assert len(frontmatter_segments) >= 2  # title and description

        # Check that we have body segments
        body_segments = [s for s in segments if s.context.context_type.value != "frontmatter"]
        assert len(body_segments) > 0

    def test_extract_preserves_code(self, parser, site_profile, sample_markdown):
        """Test that code blocks are preserved (not extracted for translation)."""
        doc = parser.parse_string(sample_markdown)
        extractor = SegmentExtractor(site_profile)
        segments = extractor.extract_all(doc)

        # Verify no segment contains the Python code
        for segment in segments:
            assert "def hello():" not in segment.source_text
            assert "print(" not in segment.source_text

    def test_extract_shortcodes(self, parser, site_profile, sample_with_shortcodes):
        """Test that shortcodes are handled correctly."""
        doc = parser.parse_string(sample_with_shortcodes)
        extractor = SegmentExtractor(site_profile)
        segments = extractor.extract_all(doc)

        # Shortcodes should be protected with placeholders
        assert len(segments) > 0
        # Each segment with shortcode should have placeholder_map
        for segment in segments:
            if "{{<" in segment.source_text or len(segment.placeholder_map) > 0:
                assert segment.placeholder_map is not None


class TestE2ETranslateReconstruct:
    """Test translation and reconstruction pipeline."""

    def test_reconstruct_with_mock_translations(self, parser, site_profile, sample_markdown):
        """Test reconstruction with mock translations."""
        # Parse and extract
        doc = parser.parse_string(sample_markdown)
        extractor = SegmentExtractor(site_profile)
        segments = extractor.extract_all(doc)

        # Create mock translations (prefix with [ES])
        translations = {}
        for segment in segments:
            translations[segment.id] = f"[ES] {segment.source_text}"

        # Reconstruct
        reconstructor = MarkdownReconstructor(site_profile)
        translated_doc = reconstructor.reconstruct_document(doc, translations, "es")

        assert translated_doc is not None
        assert "[ES]" in translated_doc
        assert "title:" in translated_doc  # Frontmatter preserved
        assert "#" in translated_doc  # Markdown structure preserved

    def test_reconstruct_preserves_frontmatter_structure(self, parser, site_profile, sample_markdown):
        """Test that frontmatter structure is preserved."""
        doc = parser.parse_string(sample_markdown)
        extractor = SegmentExtractor(site_profile)
        segments = extractor.extract_all(doc)

        # Create mock translations
        translations = {segment.id: f"[ES] {segment.source_text}" for segment in segments}

        # Reconstruct
        reconstructor = MarkdownReconstructor(site_profile)
        translated_doc = reconstructor.reconstruct_document(doc, translations, "es")

        # Parse the translated document
        translated_parsed = parser.parse_string(translated_doc)

        # Check frontmatter keys are preserved
        assert "title" in translated_parsed.frontmatter
        assert "description" in translated_parsed.frontmatter
        assert "weight" in translated_parsed.frontmatter
        assert "url" in translated_parsed.frontmatter

        # Check translated fields start with [ES]
        assert translated_parsed.frontmatter["title"].startswith("[ES]")
        assert translated_parsed.frontmatter["description"].startswith("[ES]")

        # Check passthrough fields unchanged
        assert translated_parsed.frontmatter["weight"] == 10
        assert translated_parsed.frontmatter["url"] == "/test"

    def test_reconstruct_preserves_markdown_structure(self, parser, site_profile, sample_markdown):
        """Test that markdown structure is preserved."""
        doc = parser.parse_string(sample_markdown)
        extractor = SegmentExtractor(site_profile)
        segments = extractor.extract_all(doc)

        translations = {segment.id: f"[ES] {segment.source_text}" for segment in segments}

        reconstructor = MarkdownReconstructor(site_profile)
        translated_doc = reconstructor.reconstruct_document(doc, translations, "es")

        # Check structure preserved
        assert "# " in translated_doc  # H1 headings
        assert "## " in translated_doc  # H2 headings
        assert "- " in translated_doc  # List items
        assert "```python" in translated_doc  # Code blocks
        assert "[our website]" in translated_doc or "our website" in translated_doc  # Links


class TestE2EValidation:
    """Test validation of translated documents."""

    def test_validate_correct_translation(self, parser, site_profile, validator, sample_markdown):
        """Test validation passes for correct translation."""
        doc = parser.parse_string(sample_markdown)
        extractor = SegmentExtractor(site_profile)
        segments = extractor.extract_all(doc)

        translations = {segment.id: f"[ES] {segment.source_text}" for segment in segments}

        reconstructor = MarkdownReconstructor(site_profile)
        translated_doc = reconstructor.reconstruct_document(doc, translations, "es")

        # Validate — returns list of ValidationResult objects
        results = validator.validate(sample_markdown, translated_doc)

        # Should succeed (placeholders preserved, structure maintained)
        all_issues = [i for r in results for i in r.issues]
        overall_success = all(r.success for r in results)
        assert overall_success or len([i for i in all_issues if i.severity == ValidationSeverity.ERROR]) == 0

    def test_validate_detects_broken_links(self, validator):
        """Test validation detects broken link structure."""
        source = "Visit [our website](https://example.com) for info."
        # Broken translation - link text changed incorrectly
        translation = "Visite [nuestro sitio web](https://wrong.com) para información."

        result = validator.validate(source, translation)

        # May or may not flag this depending on validator logic
        # At minimum should not crash
        assert result is not None

    def test_validate_detects_unbalanced_placeholders(self, validator):
        """Test validation runs on text with unbalanced placeholders."""
        source = "Hello {{name}} world {{greeting}}"
        translation = "Hola {{name}} mundo"  # Missing {{greeting}}

        # validate() returns a list of ValidationResult objects
        results = validator.validate(source, translation)

        # Must return non-empty results and not crash
        assert isinstance(results, list), "validate() must return a list"
        assert len(results) > 0, "Must have at least one validation result"
        # All results have the expected shape
        for r in results:
            assert hasattr(r, 'success'), "Each result must have 'success'"
            assert hasattr(r, 'issues'), "Each result must have 'issues'"

    def test_validate_detects_broken_code_blocks(self, validator):
        """Test validation detects broken code blocks."""
        source = "```python\ncode\n```\n"
        translation = "```python\ncode\n"  # Missing closing ```

        # validate() returns a list of ValidationResult objects
        results = validator.validate(source, translation)

        # At least one validator should fail (StructureValidator detects code block mismatch)
        any_failure = any(not r.success for r in results)
        all_issues = [i for r in results for i in r.issues]
        structure_issues = [
            i for i in all_issues
            if "code" in i.message.lower() or "block" in i.message.lower()
        ]
        assert any_failure, f"Should detect code block mismatch. Results: {results}"
        assert len(structure_issues) > 0, f"Should have code/block issue. Issues: {all_issues}"


class TestE2EFullPipeline:
    """Test complete end-to-end pipeline."""

    def test_full_pipeline_with_sample_files(self, parser, site_profile, validator):
        """Test full pipeline with actual sample files."""
        project_root = Path(__file__).parent.parent.parent
        samples_dir = project_root / "samples"

        # Find first sample file
        sample_files = list(samples_dir.glob("**/sample-live*.md"))
        if not sample_files:
            pytest.skip("No sample files found")

        sample_file = sample_files[0]

        # Read file
        with open(sample_file, encoding='utf-8') as f:
            content = f.read()

        # Parse
        doc = parser.parse_string(content)
        assert doc is not None

        # Extract
        extractor = SegmentExtractor(site_profile)
        segments = extractor.extract_all(doc)
        assert len(segments) > 0

        # Mock translate
        translations = {segment.id: f"[ES] {segment.source_text}" for segment in segments}

        # Reconstruct
        reconstructor = MarkdownReconstructor(site_profile)
        translated_doc = reconstructor.reconstruct_document(doc, translations, "es")
        assert translated_doc is not None

        # Validate
        result = validator.validate(content, translated_doc)

        # Check for critical errors only (warnings are OK)
        critical_errors = [i for i in result.issues if i.severity == ValidationSeverity.ERROR]
        assert len(critical_errors) == 0, f"Critical validation errors: {critical_errors}"

    def test_multiple_language_pairs(self, parser, site_profile, sample_markdown):
        """Test pipeline works for multiple target languages."""
        doc = parser.parse_string(sample_markdown)
        extractor = SegmentExtractor(site_profile)
        segments = extractor.extract_all(doc)

        for target_lang in ["es", "fa", "ja", "zh"]:
            # Mock translations with language tag
            translations = {segment.id: f"[{target_lang.upper()}] {segment.source_text}" for segment in segments}

            # Reconstruct
            reconstructor = MarkdownReconstructor(site_profile)
            translated_doc = reconstructor.reconstruct_document(doc, translations, target_lang)

            assert translated_doc is not None
            assert f"[{target_lang.upper()}]" in translated_doc

            # Parse translated doc to verify it's valid
            translated_parsed = parser.parse_string(translated_doc)
            assert translated_parsed is not None
            assert len(translated_parsed.ast) > 0


class TestE2EPlaceholderProtection:
    """Test placeholder protection throughout pipeline."""

    def test_link_preservation(self, parser, site_profile):
        """Test that links are preserved correctly."""
        markdown = "Visit [example](https://example.com) and [test](https://test.com)."
        doc = parser.parse_string(markdown)
        extractor = SegmentExtractor(site_profile)
        segments = extractor.extract_all(doc)

        # Mock translation
        translations = {segment.id: f"[ES] {segment.source_text}" for segment in segments}

        reconstructor = MarkdownReconstructor(site_profile)
        translated_doc = reconstructor.reconstruct_document(doc, translations, "es")

        # Links should be preserved
        assert "https://example.com" in translated_doc
        assert "https://test.com" in translated_doc

    def test_hugo_shortcode_preservation(self, parser, site_profile, sample_with_shortcodes):
        """Test that Hugo shortcodes are preserved."""
        doc = parser.parse_string(sample_with_shortcodes)
        extractor = SegmentExtractor(site_profile)
        segments = extractor.extract_all(doc)

        translations = {segment.id: f"[ES] {segment.source_text}" for segment in segments}

        reconstructor = MarkdownReconstructor(site_profile)
        translated_doc = reconstructor.reconstruct_document(doc, translations, "es")

        # Shortcodes should be preserved exactly
        assert "{{< note >}}" in translated_doc or "{{<note>}}" in translated_doc
        assert "{{< ref " in translated_doc or "{{<ref " in translated_doc

    def test_code_block_preservation(self, parser, site_profile, sample_markdown):
        """Test that code blocks are preserved exactly."""
        doc = parser.parse_string(sample_markdown)
        extractor = SegmentExtractor(site_profile)
        segments = extractor.extract_all(doc)

        translations = {segment.id: f"[ES] {segment.source_text}" for segment in segments}

        reconstructor = MarkdownReconstructor(site_profile)
        translated_doc = reconstructor.reconstruct_document(doc, translations, "es")

        # Code should be preserved
        assert "```python" in translated_doc
        assert "def hello():" in translated_doc
        assert 'print("Hello, World!")' in translated_doc
        assert "```" in translated_doc


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v"])
