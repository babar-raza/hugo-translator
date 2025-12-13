"""
Tests for Quality Validator

Tests validation of:
- Frontmatter YAML
- Placeholders
- Code blocks
- Headings
- Lists
- Links
"""

import pytest
import tempfile
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.validation.quality_validator import QualityValidator
from src.translation_engine.validation import ValidationSeverity


class TestFrontmatterValidation:
    """Test frontmatter YAML validation."""

    def test_valid_frontmatter(self):
        """Test that valid frontmatter passes validation."""
        validator = QualityValidator()

        source = """---
title: "Test"
description: "Description"
---

Body content.
"""

        translation = """---
title: "Prueba"
description: "Descripción"
---

Contenido del cuerpo.
"""

        result = validator.validate_content(source, translation)
        assert result.success or result.error_count == 0

    def test_malformed_yaml(self):
        """Test detection of malformed YAML in translation."""
        validator = QualityValidator()

        source = """---
title: "Test"
---

Body.
"""

        translation = """---
title: "Test
description: [unclosed
---

Body.
"""

        result = validator.validate_content(source, translation)
        assert result.error_count > 0
        assert any("YAML error" in issue.message for issue in result.issues)

    def test_missing_frontmatter_keys(self):
        """Test detection of missing frontmatter keys."""
        validator = QualityValidator()

        source = """---
title: "Test"
description: "Description"
weight: 10
---

Body.
"""

        translation = """---
title: "Prueba"
---

Body.
"""

        result = validator.validate_content(source, translation)
        # Should have warnings about missing keys
        warnings = [i for i in result.issues if i.severity == ValidationSeverity.WARNING]
        assert len(warnings) > 0
        assert any("missing" in i.message.lower() for i in warnings)

    def test_extra_frontmatter_keys(self):
        """Test detection of extra frontmatter keys."""
        validator = QualityValidator()

        source = """---
title: "Test"
---

Body.
"""

        translation = """---
title: "Prueba"
extra_key: "Extra"
another_key: "Another"
---

Body.
"""

        result = validator.validate_content(source, translation)
        # Should have info about extra keys
        info_issues = [i for i in result.issues if i.severity == ValidationSeverity.INFO]
        assert len(info_issues) > 0
        assert any("extra" in i.message.lower() for i in info_issues)


class TestPlaceholderValidation:
    """Test placeholder integrity validation."""

    def test_placeholder_balance(self):
        """Test that balanced placeholders pass."""
        validator = QualityValidator()

        source = "Hello {{name}} and {{greeting}}!"
        translation = "Hola {{name}} y {{greeting}}!"

        result = validator.validate_content(source, translation)
        assert result.success or result.error_count == 0

    def test_missing_placeholder(self):
        """Test detection of missing placeholders."""
        validator = QualityValidator()

        source = "Hello {{name}} and {{greeting}}!"
        translation = "Hola {{name}}!"  # Missing {{greeting}}

        result = validator.validate_content(source, translation)
        assert result.error_count > 0
        assert any("missing" in issue.message.lower() for issue in result.issues)

    def test_extra_placeholder(self):
        """Test detection of extra placeholders."""
        validator = QualityValidator()

        source = "Hello {{name}}!"
        translation = "Hola {{name}} y {{greeting}}!"  # Extra {{greeting}}

        result = validator.validate_content(source, translation)
        assert result.warning_count > 0
        assert any("extra" in issue.message.lower() for issue in result.issues)

    def test_hugo_shortcode_preservation(self):
        """Test that Hugo shortcodes are validated."""
        validator = QualityValidator()

        source = "Content {{< ref \"page\" >}} more."
        translation = "Contenido {{< ref \"page\" >}} más."

        result = validator.validate_content(source, translation)
        assert result.success or result.error_count == 0

    def test_missing_shortcode(self):
        """Test detection of missing shortcodes."""
        validator = QualityValidator()

        source = "Content {{< ref \"page\" >}} more."
        translation = "Contenido más."  # Missing shortcode

        result = validator.validate_content(source, translation)
        assert result.error_count > 0


class TestCodeBlockValidation:
    """Test code block balance validation."""

    def test_balanced_code_blocks(self):
        """Test that balanced code blocks pass."""
        validator = QualityValidator()

        source = """
Text before.

```python
code here
```

Text after.
"""

        translation = """
Texto antes.

```python
code here
```

Texto después.
"""

        result = validator.validate_content(source, translation)
        assert result.success or result.error_count == 0

    def test_unbalanced_code_blocks_in_translation(self):
        """Test detection of unbalanced code blocks."""
        validator = QualityValidator()

        source = """
```python
code
```
"""

        translation = """
```python
code
"""  # Missing closing ```

        result = validator.validate_content(source, translation)
        assert result.error_count > 0
        assert any("unbalanced" in issue.message.lower() or "code" in issue.message.lower()
                   for issue in result.issues)

    def test_different_code_block_count(self):
        """Test warning for different code block counts."""
        validator = QualityValidator()

        source = """
```
block 1
```

```
block 2
```
"""

        translation = """
```
block 1
```
"""  # Only one block

        result = validator.validate_content(source, translation)
        # Should have warning about different counts
        assert result.warning_count > 0 or result.error_count > 0


class TestHeadingValidation:
    """Test heading structure validation."""

    def test_preserved_heading_structure(self):
        """Test that preserved heading structure passes."""
        validator = QualityValidator()

        source = """
# Heading 1

## Heading 2

### Heading 3
"""

        translation = """
# Encabezado 1

## Encabezado 2

### Encabezado 3
"""

        result = validator.validate_content(source, translation)
        assert result.success or result.error_count == 0

    def test_different_heading_count(self):
        """Test detection of different heading counts."""
        validator = QualityValidator()

        source = """
# Heading 1

## Heading 2

## Heading 3
"""

        translation = """
# Encabezado 1

## Encabezado 2
"""  # Missing one heading

        result = validator.validate_content(source, translation)
        assert result.warning_count > 0
        assert any("heading" in issue.message.lower() for issue in result.issues)

    def test_different_heading_levels(self):
        """Test detection of different heading levels."""
        validator = QualityValidator()

        source = """
# Heading 1

## Heading 2
"""

        translation = """
# Encabezado 1

### Encabezado 3
"""  # Changed level

        result = validator.validate_content(source, translation)
        assert result.warning_count > 0


class TestListValidation:
    """Test list structure validation."""

    def test_preserved_list_structure(self):
        """Test that preserved list structure passes."""
        validator = QualityValidator()

        source = """
- Item 1
- Item 2
- Item 3
"""

        translation = """
- Artículo 1
- Artículo 2
- Artículo 3
"""

        result = validator.validate_content(source, translation)
        assert result.success or result.error_count == 0

    def test_different_list_item_count(self):
        """Test warning for significantly different item counts."""
        validator = QualityValidator()

        source = """
- Item 1
- Item 2
- Item 3
- Item 4
- Item 5
"""

        translation = """
- Artículo 1
- Artículo 2
"""  # Only 2 items vs 5

        result = validator.validate_content(source, translation)
        # Should warn if difference is > 20%
        assert result.warning_count > 0


class TestLinkValidation:
    """Test link validation."""

    def test_valid_links(self):
        """Test that valid links pass."""
        validator = QualityValidator()

        source = "Visit [example](https://example.com)"
        translation = "Visite [ejemplo](https://example.com)"

        result = validator.validate_content(source, translation)
        assert result.success or result.error_count == 0

    def test_empty_link_url(self):
        """Test detection of empty link URLs."""
        validator = QualityValidator()

        source = "Visit [example](https://example.com)"
        translation = "Visite [ejemplo]()"  # Empty URL

        result = validator.validate_content(source, translation)
        assert result.error_count > 0
        assert any("empty" in issue.message.lower() for issue in result.issues)

    def test_relative_link_validation_with_base_dir(self):
        """Test relative link validation when base_dir is set."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)

            # Create a test file
            test_file = base_dir / "existing.md"
            test_file.write_text("content")

            validator = QualityValidator(base_dir=base_dir)

            source = "See [link](existing.md)"
            translation = "Ver [enlace](existing.md)"

            result = validator.validate_content(source, translation)
            # Should not warn about existing file
            link_warnings = [i for i in result.issues
                           if "link" in i.message.lower() and i.severity == ValidationSeverity.WARNING]
            assert len([w for w in link_warnings if "existing.md" in w.message]) == 0

    def test_missing_relative_link(self):
        """Test detection of missing relative link targets."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            validator = QualityValidator(base_dir=base_dir)

            source = "See [link](existing.md)"
            translation = "Ver [enlace](missing.md)"  # File doesn't exist

            result = validator.validate_content(source, translation)
            # Should warn about missing file
            assert result.warning_count > 0
            assert any("not found" in issue.message.lower() for issue in result.issues)


class TestFileValidation:
    """Test file-based validation."""

    def test_validate_file(self):
        """Test validating file pairs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)

            # Create source file
            source_file = base_dir / "source.md"
            source_file.write_text("""---
title: "Test"
---

# Heading

Content.
""")

            # Create translation file
            trans_file = base_dir / "translation.md"
            trans_file.write_text("""---
title: "Prueba"
---

# Encabezado

Contenido.
""")

            validator = QualityValidator()
            result = validator.validate_file(source_file, trans_file, "es")

            assert result is not None
            assert result.file_path == trans_file

    def test_validate_directory(self):
        """Test validating directory of translations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)

            # Create source directory and files
            source_dir = base_dir / "source"
            source_dir.mkdir()
            (source_dir / "file1.md").write_text("---\ntitle: Test 1\n---\nContent 1")
            (source_dir / "file2.md").write_text("---\ntitle: Test 2\n---\nContent 2")

            # Create translation directory and files
            trans_dir = base_dir / "translation"
            trans_dir.mkdir()
            (trans_dir / "file1.md").write_text("---\ntitle: Prueba 1\n---\nContenido 1")
            (trans_dir / "file2.md").write_text("---\ntitle: Prueba 2\n---\nContenido 2")

            validator = QualityValidator()
            results = validator.validate_directory(source_dir, trans_dir, "es", recursive=False)

            assert len(results) == 2
            assert all(result.success or result.error_count == 0 for result in results.values())


class TestComplexScenarios:
    """Test complex validation scenarios."""

    def test_full_hugo_document(self):
        """Test validation of a complete Hugo document."""
        validator = QualityValidator()

        source = """---
title: "Complex Document"
description: "A complex test document"
weight: 10
tags: ["test", "example"]
---

# Main Heading

This is a paragraph with {{< ref "other" >}} shortcode.

## Subheading

- List item 1
- List item 2 with [link](https://example.com)
- List item 3

```python
def hello():
    print("Hello")
```

Another paragraph with {{variable}} placeholder.
"""

        translation = """---
title: "Documento Complejo"
description: "Un documento de prueba complejo"
weight: 10
tags: ["prueba", "ejemplo"]
---

# Encabezado Principal

Este es un párrafo con {{< ref "other" >}} shortcode.

## Subencabezado

- Artículo de lista 1
- Artículo de lista 2 con [enlace](https://example.com)
- Artículo de lista 3

```python
def hello():
    print("Hello")
```

Otro párrafo con {{variable}} placeholder.
"""

        result = validator.validate_content(source, translation)

        # Should pass without critical errors
        assert result.error_count == 0
        # May have warnings, but that's OK

    def test_multiple_issues(self):
        """Test document with multiple issues."""
        validator = QualityValidator()

        source = """---
title: "Test"
description: "Description"
---

# Heading

Paragraph with {{placeholder}}.

```
code
```
"""

        translation = """---
title: "Prueba"
---

## Heading

Paragraph without placeholder.

```
code
"""  # Missing description, wrong heading level, missing placeholder, unclosed code

        result = validator.validate_content(source, translation)

        # Should have multiple issues
        assert len(result.issues) > 2
        assert result.error_count > 0 or result.warning_count > 0


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v"])
