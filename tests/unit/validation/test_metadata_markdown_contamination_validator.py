"""
Tests for MetadataMarkdownContaminationValidator (Fix 3.4 / RC-D prevention).

Covers the failure patterns observed in 683 pre-existing broken files:
  1. Trailing orphaned '#' in title (from English source ending in 'C#')
  2. Leading '# ' heading marker in title
  3. Trailing '#.' in step fields
  4. Valid 'C#' references in translated titles must NOT be flagged
"""

import pytest

from src.translation_engine.validation.metadata_markdown_contamination_validator import (
    MetadataMarkdownContaminationValidator,
)


@pytest.fixture
def validator():
    return MetadataMarkdownContaminationValidator()


def _doc(frontmatter: str, body: str = "Body text.") -> str:
    return f"---\n{frontmatter}\n---\n\n{body}\n"


class TestTrailingHash:
    def test_trailing_hash_in_title_is_error(self, validator):
        doc = _doc('title: "C#を使用してバーコードを読み取る方法#"')
        result = validator.validate("", doc)
        assert not result.success
        assert any("title" in i.message and "RC-D" in i.message for i in result.issues)

    def test_trailing_hash_dot_in_step_is_error(self, validator):
        doc = _doc('title: Hello\nstep2: "ロードします#."')
        result = validator.validate("", doc)
        assert not result.success
        assert any("step2" in i.message for i in result.issues)

    def test_trailing_hash_with_spaces_is_error(self, validator):
        doc = _doc('title: "Извлечь файлы RAR#  "')
        result = validator.validate("", doc)
        assert not result.success

    def test_clean_title_passes(self, validator):
        doc = _doc('title: "C#を使用してバーコードを読み取る方法"')
        result = validator.validate("", doc)
        assert result.success

    def test_valid_csharp_at_end_not_flagged(self, validator):
        """'C#' at end of value must not be flagged — it's a valid language name."""
        doc = _doc('title: "How to Read Barcodes Using C#"')
        result = validator.validate("", doc)
        assert result.success

    def test_valid_lowercase_csharp_not_flagged(self, validator):
        """'c#' (lowercase) at end must also not be flagged."""
        doc = _doc('title: "read barcodes using c#"')
        result = validator.validate("", doc)
        assert result.success


class TestLeadingHash:
    def test_leading_heading_marker_is_error(self, validator):
        doc = _doc("title: '# C#를 사용하여 바코드를 읽는 방법'")
        result = validator.validate("", doc)
        assert not result.success
        assert any("title" in i.message and "RC-D" in i.message for i in result.issues)

    def test_leading_double_hash_is_error(self, validator):
        doc = _doc('title: "## Extract ZIP Files"')
        result = validator.validate("", doc)
        assert not result.success

    def test_leading_triple_hash_is_error(self, validator):
        doc = _doc('description: "### Introduction"')
        result = validator.validate("", doc)
        assert not result.success

    def test_leading_hash_without_space_is_not_flagged(self, validator):
        """'#tag' format (no space after #) is not a heading marker — should pass."""
        doc = _doc('title: "#hashtag style title"')
        result = validator.validate("", doc)
        assert result.success  # '#hashtag' is not a heading marker (no space)


class TestCheckedFields:
    def test_all_step_fields_checked(self, validator):
        """step1..step10 should all be checked."""
        for i in range(1, 11):
            doc = _doc(f'title: Good\nstep{i}: "Something#"')
            result = validator.validate("", doc)
            assert not result.success, f"step{i} should be flagged"

    def test_head_title_checked(self, validator):
        doc = _doc('head_title: "Extract Using C# #"')
        result = validator.validate("", doc)
        assert not result.success

    def test_head_description_checked(self, validator):
        doc = _doc('head_description: "# Introduction"')
        result = validator.validate("", doc)
        assert not result.success

    def test_description_checked(self, validator):
        doc = _doc('description: "Some description#"')
        result = validator.validate("", doc)
        assert not result.success

    def test_unchecked_field_not_flagged(self, validator):
        """Fields not in _CHECKED_FIELDS (e.g. 'slug') are not checked."""
        doc = _doc('title: Good\nslug: "my-slug#weird"')
        result = validator.validate("", doc)
        assert result.success


class TestEdgeCases:
    def test_no_frontmatter_passes(self, validator):
        result = validator.validate("", "No frontmatter here, just body.")
        assert result.success

    def test_empty_translation_passes(self, validator):
        result = validator.validate("", "")
        assert result.success

    def test_empty_field_value_not_flagged(self, validator):
        doc = _doc("title: \"\"\ndescription: ''")
        result = validator.validate("", doc)
        assert result.success

    def test_multiple_errors_reported(self, validator):
        doc = _doc('title: "Method#"\ndescription: "# Intro"')
        result = validator.validate("", doc)
        assert not result.success
        assert len(result.issues) == 2

    def test_all_error_severity(self, validator):
        from src.translation_engine.validation.base import ValidationSeverity

        doc = _doc('title: "Bad#"')
        result = validator.validate("", doc)
        assert all(i.severity == ValidationSeverity.ERROR for i in result.issues)

    def test_source_not_checked(self, validator):
        """Source text contamination must not affect the result."""
        source = _doc('title: "English title#"')  # Source has the issue
        translation = _doc('title: "Translated title"')  # Translation is clean
        result = validator.validate(source, translation)
        assert result.success
