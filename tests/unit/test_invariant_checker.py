"""
Unit tests for invariant checker CLI.

Run with:
    pytest tests/unit/test_invariant_checker.py -v
"""

import sys
from pathlib import Path

# Add scripts to path to import check_invariants
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from check_invariants import (
    BasicTerminologyChecker,
    BoundaryInvariantChecker,
    CodeBlockPolicyChecker,
    PlaceholderInvariantChecker,
    StructuralIntegrityChecker,
)


class TestPlaceholderInvariants:
    """Test placeholder preservation invariants"""

    def test_exact_count_pass(self):
        checker = PlaceholderInvariantChecker()
        source = "This is ⟦P0_AST⟧ and ⟦P1_TERM⟧"
        translated = "Ceci est ⟦P0_AST⟧ et ⟦P1_TERM⟧"
        result = checker.check_exact_count(source, translated)
        assert result.passed
        assert result.details["expected_count"] == 2
        assert result.details["actual_count"] == 2

    def test_exact_count_fail_missing(self):
        checker = PlaceholderInvariantChecker()
        source = "This is ⟦P0_AST⟧ and ⟦P1_TERM⟧"
        translated = "Ceci est ⟦P0_AST⟧"  # Missing P1_TERM
        result = checker.check_exact_count(source, translated)
        assert not result.passed
        assert "P1_TERM" in result.details["missing"]

    def test_exact_count_fail_extra(self):
        checker = PlaceholderInvariantChecker()
        source = "This is ⟦P0_AST⟧"
        translated = "Ceci est ⟦P0_AST⟧ et ⟦P1_EXTRA⟧"  # Extra placeholder
        result = checker.check_exact_count(source, translated)
        assert not result.passed
        assert "P1_EXTRA" in result.details["extra"]

    def test_set_equality_pass(self):
        checker = PlaceholderInvariantChecker()
        source = "Test ⟦ABC⟧ and ⟦XYZ⟧"
        translated = "Essai ⟦XYZ⟧ et ⟦ABC⟧"  # Order changed but set identical
        result = checker.check_set_equality(source, translated)
        assert result.passed

    def test_set_equality_fail(self):
        checker = PlaceholderInvariantChecker()
        source = "Test ⟦ABC⟧ and ⟦XYZ⟧"
        translated = "Essai ⟦ABC⟧ et ⟦WRONG⟧"  # Different placeholder
        result = checker.check_set_equality(source, translated)
        assert not result.passed
        assert "XYZ" in result.details["missing"]
        assert "WRONG" in result.details["extra"]

    def test_checksum_pass(self):
        checker = PlaceholderInvariantChecker()
        source = "Test ⟦ABC⟧ and ⟦XYZ⟧"
        translated = "Essai ⟦XYZ⟧ et ⟦ABC⟧"  # Order changed but set identical
        result = checker.check_checksum(source, translated)
        assert result.passed

    def test_checksum_fail(self):
        checker = PlaceholderInvariantChecker()
        source = "Test ⟦ABC⟧"
        translated = "Essai ⟦XYZ⟧"  # Different placeholder
        result = checker.check_checksum(source, translated)
        assert not result.passed

    def test_no_duplicates_pass(self):
        checker = PlaceholderInvariantChecker()
        text = "Test ⟦P0_AST⟧ and ⟦P1_TERM⟧"
        result = checker.check_no_duplicates(text, "test")
        assert result.passed

    def test_no_duplicates_fail(self):
        checker = PlaceholderInvariantChecker()
        text = "Test ⟦P0_AST⟧ and ⟦P0_AST⟧ again"  # Duplicate
        result = checker.check_no_duplicates(text, "test")
        assert not result.passed
        assert "P0_AST" in result.details["duplicates"]
        assert result.details["duplicates"]["P0_AST"] == 2

    def test_no_placeholders(self):
        """Edge case: Document with no placeholders"""
        checker = PlaceholderInvariantChecker()
        source = "Plain text without placeholders"
        translated = "Texte simple sans placeholders"
        result = checker.check_exact_count(source, translated)
        assert result.passed
        assert result.details["expected_count"] == 0
        assert result.details["actual_count"] == 0


class TestBoundaryInvariants:
    """Test placeholder boundary validation"""

    def test_left_boundary_pass_space(self):
        checker = BoundaryInvariantChecker()
        text = " ⟦P0_AST⟧ test"  # Space before placeholder (valid)
        result = checker.check_left_boundary(text)
        assert result.passed

    def test_left_boundary_pass_punctuation(self):
        checker = BoundaryInvariantChecker()
        text = ".⟦P0_AST⟧ test"  # Punctuation before placeholder (valid)
        result = checker.check_left_boundary(text)
        assert result.passed

    def test_left_boundary_fail_alphanumeric(self):
        checker = BoundaryInvariantChecker()
        text = "test⟦P0_AST⟧ code"  # 't' before placeholder (invalid)
        result = checker.check_left_boundary(text)
        assert not result.passed
        assert len(result.details["violations"]) > 0

    def test_right_boundary_pass_space(self):
        checker = BoundaryInvariantChecker()
        text = "t⟦P0_AST⟧ test"  # Space after placeholder (valid)
        result = checker.check_right_boundary(text)
        assert result.passed

    def test_right_boundary_fail_alphanumeric(self):
        checker = BoundaryInvariantChecker()
        text = "t⟦P0_AST⟧test"  # 't' after placeholder (invalid)
        result = checker.check_right_boundary(text)
        assert not result.passed
        assert len(result.details["violations"]) > 0

    def test_unicode_boundary_greek_letter(self):
        """Unicode test: Greek letters should be treated as word chars"""
        checker = BoundaryInvariantChecker()
        text = "λ⟦P0_AST⟧"  # Greek letter (should fail - is word char)
        result = checker.check_left_boundary(text)
        assert not result.passed  # Greek letters are word chars

    def test_multiple_violations(self):
        """Test multiple boundary violations in same document"""
        checker = BoundaryInvariantChecker()
        text = "test⟦P0⟧word and bad⟦P1⟧end"
        result = checker.check_left_boundary(text)
        assert not result.passed
        assert len(result.details["violations"]) == 2


class TestCodeBlockPolicy:
    """Test code block handling policies"""

    def test_python_unchanged(self):
        checker = CodeBlockPolicyChecker()
        source = "```python\ndef foo():\n    pass\n```"
        translated_correct = "```python\ndef foo():\n    pass\n```"
        result = checker.check_full_bypass_unchanged(source, translated_correct)
        assert result.passed

    def test_python_modified_fail(self):
        checker = CodeBlockPolicyChecker()
        source = "```python\ndef foo():\n    pass\n```"
        translated_wrong = "```python\ndef bar():\n    pass\n```"  # Modified!
        result = checker.check_full_bypass_unchanged(source, translated_wrong)
        assert not result.passed
        assert len(result.details["violations"]) > 0

    def test_java_unchanged(self):
        checker = CodeBlockPolicyChecker()
        source = "```java\npublic class Test {}\n```"
        translated = "```java\npublic class Test {}\n```"
        result = checker.check_full_bypass_unchanged(source, translated)
        assert result.passed

    def test_csharp_unchanged(self):
        checker = CodeBlockPolicyChecker()
        source = "```csharp\nnamespace Test { }\n```"
        translated = "```csharp\nnamespace Test { }\n```"
        result = checker.check_full_bypass_unchanged(source, translated)
        assert result.passed

    def test_non_bypass_language_ignored(self):
        """YAML blocks can be modified (not in bypass list)"""
        checker = CodeBlockPolicyChecker()
        source = "```yaml\nkey: value\n```"
        translated = "```yaml\nkey: valeur\n```"  # YAML can change
        result = checker.check_full_bypass_unchanged(source, translated)
        assert result.passed  # YAML not in bypass languages

    def test_no_code_blocks(self):
        """Edge case: Document without code blocks"""
        checker = CodeBlockPolicyChecker()
        source = "Plain text document"
        translated = "Document texte simple"
        result = checker.check_full_bypass_unchanged(source, translated)
        assert result.passed


class TestStructuralIntegrity:
    """Test document structure preservation"""

    def test_frontmatter_keys_preserved(self):
        checker = StructuralIntegrityChecker()
        source = "---\ntitle: Test\ndate: 2025-01-01\n---\nContent"
        translated = "---\ntitle: Essai\ndate: 2025-01-01\n---\nContenu"
        result = checker.check_frontmatter_keys(source, translated)
        assert result.passed

    def test_frontmatter_keys_modified_fail(self):
        checker = StructuralIntegrityChecker()
        source = "---\ntitle: Test\ndate: 2025-01-01\n---\nContent"
        translated = "---\ntitle: Essai\nauthor: Someone\n---\nContenu"  # Different keys!
        result = checker.check_frontmatter_keys(source, translated)
        assert not result.passed

    def test_no_frontmatter(self):
        """Edge case: Documents without frontmatter"""
        checker = StructuralIntegrityChecker()
        source = "Just content"
        translated = "Juste contenu"
        result = checker.check_frontmatter_keys(source, translated)
        assert result.passed  # Both have no frontmatter

    def test_broken_shortcode_unclosed_angle(self):
        checker = StructuralIntegrityChecker()
        source = "Test {{< ref >}}"
        translated = "Essai {{< ref"  # Broken!
        result = checker.check_shortcode_syntax(translated)
        assert not result.passed

    def test_broken_shortcode_unclosed_percent(self):
        checker = StructuralIntegrityChecker()
        source = "Test {{% note %}}"
        translated = "Essai {{% note"  # Broken!
        result = checker.check_shortcode_syntax(translated)
        assert not result.passed

    def test_broken_placeholder(self):
        checker = StructuralIntegrityChecker()
        source = "Test ⟦P0_AST⟧"
        translated = "Essai ⟦P0_AST"  # Broken placeholder!
        result = checker.check_shortcode_syntax(translated)
        assert not result.passed

    def test_valid_shortcodes(self):
        checker = StructuralIntegrityChecker()
        source = "Test {{< ref >}} and {{% note %}}"
        translated = "Essai {{< ref >}} et {{% note %}}"
        result = checker.check_shortcode_syntax(translated)
        assert result.passed


class TestIntegration:
    """Integration tests for full checker pipeline"""

    def test_run_all_placeholder_checks(self):
        checker = PlaceholderInvariantChecker()
        source = "Test ⟦P0⟧ and ⟦P1⟧"
        translated = "Essai ⟦P0⟧ et ⟦P1⟧"
        results = checker.run_all(source, translated)
        assert len(results) == 5  # 5 checks
        assert all(r.passed for r in results)

    def test_run_all_boundary_checks(self):
        checker = BoundaryInvariantChecker()
        text = " ⟦P0⟧ test"
        results = checker.run_all(text)
        assert len(results) == 2  # left + right
        assert all(r.passed for r in results)

    def test_run_all_code_block_checks(self):
        checker = CodeBlockPolicyChecker()
        source = "```python\ncode\n```"
        translated = "```python\ncode\n```"
        results = checker.run_all(source, translated)
        assert len(results) == 1
        assert all(r.passed for r in results)

    def test_run_all_structural_checks(self):
        checker = StructuralIntegrityChecker()
        source = "---\ntitle: Test\n---\nContent"
        translated = "---\ntitle: Essai\n---\nContenu"
        results = checker.run_all(source, translated)
        assert len(results) == 2  # frontmatter + shortcodes
        assert all(r.passed for r in results)


class TestBasicTerminology:
    """Test basic terminology preservation checks"""

    def test_api_term_preserved(self):
        checker = BasicTerminologyChecker()
        source = "Use the REST API endpoint"
        translated = "Utilisez le REST API endpoint"
        result = checker.check_common_terms(source, translated)
        assert result.passed
        assert result.name == "common_technical_terms_preserved"

    def test_api_term_translated_fail(self):
        checker = BasicTerminologyChecker()
        source = "Use the REST API endpoint"
        translated = "Utilisez le interfaz REST"  # "API" and "endpoint" were translated
        result = checker.check_common_terms(source, translated)
        assert not result.passed
        # Check that violations exist (could be API, endpoint, or both)
        violations_str = str(result.details["violations"])
        assert "API" in violations_str or "endpoint" in violations_str

    def test_dataframe_preserved(self):
        checker = BasicTerminologyChecker()
        source = "The DataFrame.groupby() method"
        translated = "La méthode DataFrame.groupby()"
        result = checker.check_common_terms(source, translated)
        assert result.passed

    def test_dataframe_translated_fail(self):
        checker = BasicTerminologyChecker()
        source = "The DataFrame supports async operations"
        translated = "Le cadre de données supporte les opérations parallèles"
        result = checker.check_common_terms(source, translated)
        assert not result.passed
        # Both DataFrame and async should be violations
        violations_str = str(result.details["violations"])
        assert "DataFrame" in violations_str
        assert "async" in violations_str

    def test_multiple_terms_preserved(self):
        checker = BasicTerminologyChecker()
        source = "Use REST API with JSON and XML via HTTP endpoint"
        translated = "Utilisez REST API avec JSON et XML via HTTP endpoint"
        result = checker.check_common_terms(source, translated)
        assert result.passed
        assert result.message.startswith("Checked 6 common technical terms")

    def test_no_technical_terms(self):
        checker = BasicTerminologyChecker()
        source = "This is simple text"
        translated = "Ceci est un texte simple"
        result = checker.check_common_terms(source, translated)
        assert result.passed
        assert "0 violations" in result.message

    def test_run_all(self):
        checker = BasicTerminologyChecker()
        source = "Use the API"
        translated = "Utilisez le API"
        results = checker.run_all(source, translated)
        assert len(results) == 1
        assert results[0].passed
