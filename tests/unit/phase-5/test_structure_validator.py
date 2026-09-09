"""
Unit tests for structure validator.
"""

import pytest

from src.translation_engine.validation import (
    StructureValidator,
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
        """Test with a list item count drift beyond the tolerated +/-2 (TC-APT-053)."""
        source = """
- Item 1
- Item 2
- Item 3
- Item 4
- Item 5
- Item 6
"""
        translation = """
- Élément 1
- Élément 2
"""
        result = validator.validate(source, translation)

        assert result.warning_count > 0
        assert any("list item count" in issue.message.lower() for issue in result.issues)

    def test_list_count_small_drift_tolerated(self, validator):
        """TC-APT-053: a translator splitting one list item into two (or merging
        two into one) is ordinary stylistic variance, not lost/duplicated
        content. Confirmed live on introducing-pdf-foss-cpp/cs: a genuinely
        correct professionalize_llm translation (source 10 items, translation
        11) was rejected outright for this alone, cascading into a cross-model
        escalation that then badly corrupted the page's code blocks -- the
        real defect was rejecting a fine translation over a 1-item drift.
        """
        source = """
- Item 1
- Item 2
- Item 3
"""
        translation = """
- Élément 1a
- Élément 1b
- Élément 2
- Élément 3
"""
        result = validator.validate(source, translation)

        assert result.success is True
        assert not any("list item count" in issue.message.lower() for issue in result.issues)

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

    def test_code_block_count_small_drift_tolerated_on_dense_page(self, validator):
        """TC-APT-053 precedent extended to code elements: confirmed live on
        introducing-cells-foss-cpp (wave15, 2026-09-07) -- every one of 25
        languages, under both professionalize_llm and m2m100_418m, produced an
        otherwise-clean translation with exactly one fewer combined
        fenced+inline code element (73 -> 72 in production) than the source.
        A page with many inline `code spans` has no reason to demand a
        byte-for-byte identical count; a 1-of-2 document still does
        (test_code_block_mismatch above), so the tolerance only engages once
        there are enough code elements that a single-element drift isn't
        itself the whole signal.
        """
        source = "\n".join(f"Use `member_{i}()` for step {i}." for i in range(12))
        translation = "\n".join(f"Utilisez `member_{i}()` pour l'etape {i}." for i in range(11))
        result = validator.validate(source, translation)

        assert result.success is True
        assert not any("code block" in issue.message.lower() for issue in result.issues)

    def test_code_block_count_drift_tolerated_on_very_dense_page(self, validator):
        """TC-APT-104: a flat +/-2 tolerance does not scale to very
        code-reference-dense pages. Live-instrumented on
        cells/go/developer-guide/features.md -> de (professionalize_llm,
        scripts/ops/debug_code_block_count_diff.py): source=93 code elements
        (5 fenced + 88 inline), translation=90 -- correctly rejected under the
        old flat tolerance of 2, but diffing the actual source/translation
        inline-span sets found no dropped identifier: every apparent
        difference was the counting regex losing backtick pairing sync after
        a benign adjacent-span merge in a dense API-summary table, the same
        class of noise test_code_block_count_small_drift_tolerated_on_dense_page
        already exists to absorb, just past its fixed ceiling.
        """
        # 45 lines x 2 inline spans = 90 code elements; add 3 fenced blocks to
        # reach 93, matching the real page's 5 fenced + 88 inline = 93 total.
        source = "\n".join(f"Use `member_{i}()` and `Field_{i}` together." for i in range(45))
        source = "```go\ncode\n```\n\n" + source + "\n\n```go\ncode\n```\n\n```go\ncode\n```\n"
        translation = "\n".join(
            f"Utilisez `member_{i}()` et `Field_{i}` ensemble." for i in range(43)
        )
        translation = "```go\ncode\n```\n\n" + translation + "\n\n```go\ncode\n```\n\n```go\ncode\n```\n"
        result = validator.validate(source, translation)

        assert result.success is True
        assert not any("code block" in issue.message.lower() for issue in result.issues)

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
