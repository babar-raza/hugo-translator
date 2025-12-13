"""
Unit tests for structure validator.
"""

import pytest

from src.translation_engine.validation import (
    StructureValidator,
    ValidationSeverity,
)


class TestStructureValidator:
    """Test StructureValidator."""

    @pytest.fixture
    def validator(self):
        """Create structure validator."""
        return StructureValidator()

    def test_simple_text(self, validator):
        """Test with simple text (no structure)."""
        source = "This is simple text"
        translation = "Ceci est un texte simple"

        result = validator.validate(source, translation)

        assert result.success is True

    def test_matching_headings(self, validator):
        """Test with matching heading structure."""
        source = """
# Title
## Subtitle
### Section
"""
        translation = """
# Titre
## Sous-titre
### Section
"""
        result = validator.validate(source, translation)

        assert result.success is True
        assert len(result.issues) == 0

    def test_heading_count_mismatch(self, validator):
        """Test with different heading counts."""
        source = """
# Title
## Section 1
## Section 2
"""
        translation = """
# Titre
## Section 1
"""
        result = validator.validate(source, translation)

        assert result.warning_count > 0
        assert any("heading count" in issue.message.lower() for issue in result.issues)

    def test_heading_level_mismatch(self, validator):
        """Test with different heading levels."""
        source = """
# Title
## Subtitle
"""
        translation = """
# Titre
### Sous-titre
"""
        result = validator.validate(source, translation)

        assert result.warning_count > 0
        assert any("heading level" in issue.message.lower() for issue in result.issues)

    def test_list_preservation(self, validator):
        """Test list structure preservation."""
        source = """
- Item 1
- Item 2
- Item 3
"""
        translation = """
- Élément 1
- Élément 2
- Élément 3
"""
        result = validator.validate(source, translation)

        assert result.success is True

    def test_list_count_mismatch(self, validator):
        """Test with different list item counts."""
        source = """
- Item 1
- Item 2
- Item 3
"""
        translation = """
- Élément 1
- Élément 2
"""
        result = validator.validate(source, translation)

        assert result.warning_count > 0
        assert any("list item count" in issue.message.lower() for issue in result.issues)

    def test_code_block_preservation(self, validator):
        """Test code block preservation."""
        source = """
Some text

```python
def hello():
    print("Hello")
```

More text with `inline code`.
"""
        translation = """
Du texte

```python
def hello():
    print("Hello")
```

Plus de texte avec `code en ligne`.
"""
        result = validator.validate(source, translation)

        assert result.success is True

    def test_code_block_mismatch(self, validator):
        """Test with code block count mismatch."""
        source = """
```python
code
```

More text with `inline`.
"""
        translation = """
```python
code
```

Plus de texte sans code en ligne.
"""
        result = validator.validate(source, translation)

        # Code block count mismatch should be an error
        assert result.error_count > 0
        assert any("code block" in issue.message.lower() for issue in result.issues)

    def test_link_preservation(self, validator):
        """Test link/image preservation."""
        source = """
Check [this link](https://example.com) and ![this image](image.png).
"""
        translation = """
Vérifiez [ce lien](https://example.com) et ![cette image](image.png).
"""
        result = validator.validate(source, translation)

        assert result.success is True

    def test_link_count_mismatch(self, validator):
        """Test with link count mismatch."""
        source = """
[Link 1](url1) and [Link 2](url2)
"""
        translation = """
[Lien 1](url1)
"""
        result = validator.validate(source, translation)

        assert result.warning_count > 0
        assert any("link" in issue.message.lower() for issue in result.issues)

    def test_formatting_preservation(self, validator):
        """Test bold/italic formatting."""
        source = """
This is **bold** and this is *italic*.
"""
        translation = """
Ceci est **gras** et ceci est *italique*.
"""
        result = validator.validate(source, translation)

        assert result.success is True

    def test_formatting_significant_difference(self, validator):
        """Test with significant formatting differences."""
        source = """
**Bold 1** **Bold 2** **Bold 3** **Bold 4** **Bold 5**
"""
        translation = """
**Gras 1**
"""
        result = validator.validate(source, translation)

        # Should have info about formatting difference (> 2 difference)
        assert result.info_count > 0

    def test_complex_document(self, validator):
        """Test with complex document structure."""
        source = """
# Main Title

## Section 1

Some text with [a link](url) and **bold**.

- List item 1
- List item 2

```python
code = "example"
```

## Section 2

More text with `inline code`.
"""
        translation = """
# Titre Principal

## Section 1

Du texte avec [un lien](url) et **gras**.

- Élément de liste 1
- Élément de liste 2

```python
code = "example"
```

## Section 2

Plus de texte avec `code en ligne`.
"""
        result = validator.validate(source, translation)

        assert result.success is True
        assert len(result.issues) == 0
