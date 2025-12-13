"""Unit tests for TerminologyManager.

Tests cover:
- Configuration loading from YAML
- Rule merging (global + site-specific)
- End-to-end protection/restoration cycle
- Error handling
"""

import pytest
import tempfile
import os
from pathlib import Path
from src.translation_engine.terminology.terminology_manager import TerminologyManager
from src.translation_engine.terminology.models import PreserveMode, TermSeverity


class TestTerminologyManager:
    """Test suite for TerminologyManager class."""

    @pytest.fixture
    def config_file(self):
        """Create a temporary config file for testing."""
        config_content = """
version: "1.0"

global:
  exact_matches:
    - term: "Aspose"
      category: company_name
      case_sensitive: true
      preserve_mode: both
      severity: error

    - term: ".NET"
      category: platform
      case_sensitive: true
      preserve_mode: both
      severity: error

  patterns:
    - pattern: 'Aspose\\.[A-Z][a-z]+'
      category: product_family
      description: "Aspose product families"
      preserve_mode: protect
      severity: error

site_overrides:
  reference.aspose.net:
    inherit_global: true
    patterns:
      - pattern: '\\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\\b'
        category: pascal_case_identifier
        description: "PascalCase API identifiers"
        preserve_mode: protect
        severity: error

  docs.aspose.com:
    inherit_global: false
    exact_matches:
      - term: "API"
        category: technical_term
        case_sensitive: true
        preserve_mode: protect
        severity: warning

auto_discovery:
  enabled: false
  min_frequency: 3
  confidence_threshold: 0.8
"""
        # Create temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as f:
            f.write(config_content)
            temp_path = f.name

        yield temp_path

        # Cleanup
        os.unlink(temp_path)

    def test_config_loading(self, config_file):
        """Test that configuration loads correctly from YAML."""
        manager = TerminologyManager(config_file)

        # Check version
        assert manager.version == "1.0"

        # Check global rules loaded
        assert len(manager.global_rules) > 0

        # Check site overrides loaded
        assert "reference.aspose.net" in manager.site_overrides
        assert "docs.aspose.com" in manager.site_overrides

        # Check auto_discovery settings
        assert manager.auto_discovery.get('enabled') == False

    def test_config_file_not_found(self):
        """Test error handling when config file doesn't exist."""
        with pytest.raises(FileNotFoundError, match="Configuration file not found"):
            TerminologyManager("nonexistent/config.yaml")

    def test_get_rules_global_only(self, config_file):
        """Test getting global rules when no site specified."""
        manager = TerminologyManager(config_file)
        rules = manager.get_rules()

        # Should return global rules only
        assert len(rules) > 0

        # Check that Aspose rule is present
        aspose_rules = [r for r in rules if r.term == "Aspose"]
        assert len(aspose_rules) == 1
        assert aspose_rules[0].category == "company_name"
        assert aspose_rules[0].preserve_mode == PreserveMode.BOTH
        assert aspose_rules[0].severity == TermSeverity.ERROR

    def test_get_rules_unknown_site(self, config_file):
        """Test getting rules for unknown site returns global rules."""
        manager = TerminologyManager(config_file)
        rules = manager.get_rules("unknown.site.com")

        # Should return global rules only
        global_rules = manager.get_rules()
        assert len(rules) == len(global_rules)

    def test_rule_merging_with_inheritance(self, config_file):
        """Test that site rules merge with global when inherit_global is true."""
        manager = TerminologyManager(config_file)

        # Get rules for reference.aspose.net (inherits global)
        rules = manager.get_rules("reference.aspose.net")

        # Should have global rules + site-specific rules
        assert len(rules) > len(manager.global_rules)

        # Check global rule is present
        aspose_rules = [r for r in rules if r.term == "Aspose"]
        assert len(aspose_rules) == 1

        # Check site-specific pattern is present
        pascal_rules = [r for r in rules if r.category == "pascal_case_identifier"]
        assert len(pascal_rules) == 1

    def test_rule_merging_without_inheritance(self, config_file):
        """Test that site rules replace global when inherit_global is false."""
        manager = TerminologyManager(config_file)

        # Get rules for docs.aspose.com (does not inherit global)
        rules = manager.get_rules("docs.aspose.com")

        # Should have only site-specific rules
        assert len(rules) < len(manager.global_rules)

        # Check global rule is NOT present
        aspose_rules = [r for r in rules if r.term == "Aspose"]
        assert len(aspose_rules) == 0

        # Check site-specific rule IS present
        api_rules = [r for r in rules if r.term == "API"]
        assert len(api_rules) == 1
        assert api_rules[0].preserve_mode == PreserveMode.PROTECT
        assert api_rules[0].severity == TermSeverity.WARNING

    def test_end_to_end_protection_simple(self, config_file):
        """Test detect -> protect -> restore full cycle with simple text."""
        manager = TerminologyManager(config_file)

        # Original text with terminology
        original_text = "Aspose is great for .NET development"

        # Protect
        protected = manager.protect(original_text)

        # Verify protection occurred
        assert protected.original_text == original_text
        assert "{TERM_" in protected.protected_text
        assert len(protected.term_mapping) == 2  # Aspose and .NET

        # Restore
        restored = manager.restore(protected)

        # Should match original
        assert restored == original_text

    def test_end_to_end_protection_with_product(self, config_file):
        """Test protection with product family patterns."""
        manager = TerminologyManager(config_file)

        # Text with product family
        original_text = "Use Aspose.Words for document processing in .NET"

        # Protect
        protected = manager.protect(original_text)

        # Should detect Aspose.Words (product pattern) and .NET
        assert len(protected.term_mapping) >= 2
        assert "{TERM_" in protected.protected_text

        # Restore
        restored = manager.restore(protected)
        assert restored == original_text

    def test_end_to_end_protection_with_site_rules(self, config_file):
        """Test protection with site-specific rules."""
        manager = TerminologyManager(config_file)

        # Text with PascalCase identifier
        original_text = "Use DocumentBuilder class in Aspose.Words"

        # Protect with site-specific rules
        protected = manager.protect(original_text, site="reference.aspose.net")

        # Should detect DocumentBuilder (PascalCase pattern), Aspose.Words, and possibly Aspose
        assert len(protected.term_mapping) >= 1
        assert "{TERM_" in protected.protected_text

        # Restore
        restored = manager.restore(protected)
        assert restored == original_text

    def test_end_to_end_protection_no_terms(self, config_file):
        """Test protection when no terms are detected."""
        manager = TerminologyManager(config_file)

        # Text with no terminology
        original_text = "This is a simple sentence with no special terms"

        # Protect
        protected = manager.protect(original_text)

        # No protection should occur
        assert protected.original_text == original_text
        assert protected.protected_text == original_text
        assert len(protected.term_mapping) == 0

        # Restore (should be no-op)
        restored = manager.restore(protected)
        assert restored == original_text

    def test_end_to_end_protection_multiple_occurrences(self, config_file):
        """Test protection with multiple occurrences of same term."""
        manager = TerminologyManager(config_file)

        # Text with repeated terms
        original_text = "Aspose is great and Aspose rocks. Use Aspose today!"

        # Protect
        protected = manager.protect(original_text)

        # Should detect all occurrences
        assert len(protected.term_mapping) >= 3
        assert protected.protected_text.count("{TERM_") >= 3

        # Restore
        restored = manager.restore(protected)
        assert restored == original_text

    def test_end_to_end_protection_adjacent_terms(self, config_file):
        """Test protection with adjacent terms."""
        manager = TerminologyManager(config_file)

        # Text with adjacent terms
        original_text = "Aspose.Words is a .NET library"

        # Protect
        protected = manager.protect(original_text)

        # Should detect both Aspose.Words and .NET
        assert len(protected.term_mapping) >= 2

        # Restore
        restored = manager.restore(protected)
        assert restored == original_text

    def test_protection_preserves_whitespace(self, config_file):
        """Test that protection preserves exact whitespace."""
        manager = TerminologyManager(config_file)

        # Text with various whitespace
        original_text = "  Aspose  \n  .NET  "

        # Protect
        protected = manager.protect(original_text)

        # Restore
        restored = manager.restore(protected)

        # Should preserve whitespace exactly
        assert restored == original_text

    def test_protection_case_sensitivity(self, config_file):
        """Test that case sensitivity is respected."""
        manager = TerminologyManager(config_file)

        # Text with different cases
        original_text = "Aspose vs aspose vs ASPOSE"

        # Protect (Aspose rule is case-sensitive)
        protected = manager.protect(original_text)

        # Should only detect "Aspose" (exact case match)
        aspose_terms = [t for t in protected.term_mapping.values() if t.term_text == "Aspose"]
        assert len(aspose_terms) == 1

        # Restore
        restored = manager.restore(protected)
        # Should preserve all cases
        assert "aspose" in restored
        assert "ASPOSE" in restored

    def test_real_world_config_loading(self):
        """Test loading the actual production config file."""
        # Path to real config
        config_path = r"c:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\config\terminology.yaml"

        if not Path(config_path).exists():
            pytest.skip("Production config not found")

        # Load real config
        manager = TerminologyManager(config_path)

        # Verify it loaded successfully
        assert manager.version is not None
        assert len(manager.global_rules) > 0

        # Test with real rules
        original_text = "Aspose.Words for .NET is great"
        protected = manager.protect(original_text)
        restored = manager.restore(protected)
        assert restored == original_text
