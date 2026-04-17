"""Unit tests for terminology data models.

Tests cover:
- TermRule initialization and validation
- DetectedTerm creation
- ProtectedSegment creation
- TerminologyConfig creation
- Enum values
- Edge cases and error conditions
"""

import pytest

from src.translation_engine.terminology.models import (
    DetectedTerm,
    PreserveMode,
    ProtectedSegment,
    TerminologyConfig,
    TermRule,
    TermSeverity,
)


class TestPreserveMode:
    """Test PreserveMode enum."""

    def test_preserve_mode_values(self):
        """Test all PreserveMode enum values."""
        assert PreserveMode.PROTECT.value == "protect"
        assert PreserveMode.VALIDATE.value == "validate"
        assert PreserveMode.BOTH.value == "both"
        assert PreserveMode.NONE.value == "none"

    def test_preserve_mode_string_comparison(self):
        """Test PreserveMode can be compared with strings."""
        assert PreserveMode.PROTECT == "protect"
        assert PreserveMode.VALIDATE == "validate"
        assert PreserveMode.BOTH == "both"
        assert PreserveMode.NONE == "none"


class TestTermSeverity:
    """Test TermSeverity enum."""

    def test_term_severity_values(self):
        """Test all TermSeverity enum values."""
        assert TermSeverity.ERROR.value == "error"
        assert TermSeverity.WARNING.value == "warning"
        assert TermSeverity.INFO.value == "info"

    def test_term_severity_string_comparison(self):
        """Test TermSeverity can be compared with strings."""
        assert TermSeverity.ERROR == "error"
        assert TermSeverity.WARNING == "warning"
        assert TermSeverity.INFO == "info"


class TestTermRule:
    """Test TermRule dataclass."""

    def test_term_rule_exact_match(self):
        """Test TermRule with exact term matching."""
        rule = TermRule(
            term="Aspose",
            category="company_name",
            preserve_mode=PreserveMode.BOTH,
            severity=TermSeverity.ERROR
        )
        assert rule.term == "Aspose"
        assert rule.pattern is None
        assert rule.category == "company_name"
        assert rule.preserve_mode == PreserveMode.BOTH
        assert rule.severity == TermSeverity.ERROR
        assert rule.case_sensitive is True
        assert rule.description is None

    def test_term_rule_pattern(self):
        """Test TermRule with regex pattern matching."""
        rule = TermRule(
            pattern=r"Aspose\.\w+",
            category="product_family",
            preserve_mode=PreserveMode.PROTECT,
            severity=TermSeverity.WARNING
        )
        assert rule.pattern == r"Aspose\.\w+"
        assert rule.term is None
        assert rule.category == "product_family"
        assert rule.preserve_mode == PreserveMode.PROTECT
        assert rule.severity == TermSeverity.WARNING

    def test_term_rule_case_insensitive(self):
        """Test TermRule with case-insensitive matching."""
        rule = TermRule(
            term="aspose",
            category="company_name",
            preserve_mode=PreserveMode.VALIDATE,
            severity=TermSeverity.INFO,
            case_sensitive=False
        )
        assert rule.case_sensitive is False

    def test_term_rule_with_description(self):
        """Test TermRule with description."""
        rule = TermRule(
            term="Aspose",
            category="company_name",
            preserve_mode=PreserveMode.BOTH,
            severity=TermSeverity.ERROR,
            description="Company name must be preserved"
        )
        assert rule.description == "Company name must be preserved"

    def test_term_rule_validation_error_neither(self):
        """Test TermRule raises ValueError when neither term nor pattern specified."""
        with pytest.raises(ValueError, match="Either 'term' or 'pattern' must be specified"):
            TermRule(
                category="test",
                preserve_mode=PreserveMode.PROTECT,
                severity=TermSeverity.ERROR
            )

    def test_term_rule_validation_error_both(self):
        """Test TermRule raises ValueError when both term and pattern specified."""
        with pytest.raises(ValueError, match="Cannot specify both 'term' and 'pattern'"):
            TermRule(
                term="Aspose",
                pattern=r"Aspose\.\w+",
                category="test",
                preserve_mode=PreserveMode.PROTECT,
                severity=TermSeverity.ERROR
            )

    def test_term_rule_all_preserve_modes(self):
        """Test TermRule with all preserve modes."""
        for mode in PreserveMode:
            rule = TermRule(
                term="Test",
                category="test",
                preserve_mode=mode,
                severity=TermSeverity.INFO
            )
            assert rule.preserve_mode == mode

    def test_term_rule_all_severities(self):
        """Test TermRule with all severity levels."""
        for severity in TermSeverity:
            rule = TermRule(
                term="Test",
                category="test",
                preserve_mode=PreserveMode.PROTECT,
                severity=severity
            )
            assert rule.severity == severity


class TestDetectedTerm:
    """Test DetectedTerm dataclass."""

    def test_detected_term(self):
        """Test DetectedTerm creation with all fields."""
        rule = TermRule(
            term="Aspose",
            category="company_name",
            preserve_mode=PreserveMode.BOTH,
            severity=TermSeverity.ERROR
        )
        detected = DetectedTerm(
            term_text="Aspose",
            rule=rule,
            start_pos=10,
            end_pos=16,
            confidence=1.0
        )
        assert detected.term_text == "Aspose"
        assert detected.rule == rule
        assert detected.start_pos == 10
        assert detected.end_pos == 16
        assert detected.confidence == 1.0

    def test_detected_term_default_confidence(self):
        """Test DetectedTerm with default confidence."""
        rule = TermRule(
            term="Aspose",
            category="company_name",
            preserve_mode=PreserveMode.BOTH,
            severity=TermSeverity.ERROR
        )
        detected = DetectedTerm(
            term_text="Aspose",
            rule=rule,
            start_pos=0,
            end_pos=6
        )
        assert detected.confidence == 1.0

    def test_detected_term_partial_confidence(self):
        """Test DetectedTerm with partial confidence."""
        rule = TermRule(
            term="Aspose",
            category="company_name",
            preserve_mode=PreserveMode.BOTH,
            severity=TermSeverity.ERROR
        )
        detected = DetectedTerm(
            term_text="aspose",
            rule=rule,
            start_pos=0,
            end_pos=6,
            confidence=0.8
        )
        assert detected.confidence == 0.8

    def test_detected_term_pattern_match(self):
        """Test DetectedTerm with pattern-based rule."""
        rule = TermRule(
            pattern=r"Aspose\.\w+",
            category="product_family",
            preserve_mode=PreserveMode.PROTECT,
            severity=TermSeverity.WARNING
        )
        detected = DetectedTerm(
            term_text="Aspose.Words",
            rule=rule,
            start_pos=5,
            end_pos=17
        )
        assert detected.term_text == "Aspose.Words"
        assert detected.rule.pattern == r"Aspose\.\w+"

    def test_detected_term_zero_position(self):
        """Test DetectedTerm at start of text."""
        rule = TermRule(
            term="Aspose",
            category="company_name",
            preserve_mode=PreserveMode.BOTH,
            severity=TermSeverity.ERROR
        )
        detected = DetectedTerm(
            term_text="Aspose",
            rule=rule,
            start_pos=0,
            end_pos=6
        )
        assert detected.start_pos == 0
        assert detected.end_pos == 6


class TestProtectedSegment:
    """Test ProtectedSegment dataclass."""

    def test_protected_segment_empty(self):
        """Test ProtectedSegment with no terms."""
        segment = ProtectedSegment(
            original_text="This is plain text",
            protected_text="This is plain text"
        )
        assert segment.original_text == "This is plain text"
        assert segment.protected_text == "This is plain text"
        assert len(segment.term_mapping) == 0

    def test_protected_segment_with_terms(self):
        """Test ProtectedSegment with protected terms."""
        rule = TermRule(
            term="Aspose",
            category="company_name",
            preserve_mode=PreserveMode.PROTECT,
            severity=TermSeverity.ERROR
        )
        detected = DetectedTerm(
            term_text="Aspose",
            rule=rule,
            start_pos=0,
            end_pos=6
        )
        segment = ProtectedSegment(
            original_text="Aspose is great",
            protected_text="{{TERM_0}} is great",
            term_mapping={0: detected}
        )
        assert segment.original_text == "Aspose is great"
        assert segment.protected_text == "{{TERM_0}} is great"
        assert len(segment.term_mapping) == 1
        assert 0 in segment.term_mapping
        assert segment.term_mapping[0].term_text == "Aspose"

    def test_protected_segment_multiple_terms(self):
        """Test ProtectedSegment with multiple protected terms."""
        rule1 = TermRule(
            term="Aspose",
            category="company_name",
            preserve_mode=PreserveMode.PROTECT,
            severity=TermSeverity.ERROR
        )
        rule2 = TermRule(
            term=".NET",
            category="platform",
            preserve_mode=PreserveMode.PROTECT,
            severity=TermSeverity.ERROR
        )
        detected1 = DetectedTerm(
            term_text="Aspose",
            rule=rule1,
            start_pos=0,
            end_pos=6
        )
        detected2 = DetectedTerm(
            term_text=".NET",
            rule=rule2,
            start_pos=11,
            end_pos=15
        )
        segment = ProtectedSegment(
            original_text="Aspose for .NET is great",
            protected_text="{{TERM_0}} for {{TERM_1}} is great",
            term_mapping={0: detected1, 1: detected2}
        )
        assert len(segment.term_mapping) == 2
        assert segment.term_mapping[0].term_text == "Aspose"
        assert segment.term_mapping[1].term_text == ".NET"

    def test_protected_segment_default_mapping(self):
        """Test ProtectedSegment with default empty mapping."""
        segment = ProtectedSegment(
            original_text="Text",
            protected_text="Text"
        )
        assert segment.term_mapping == {}
        assert isinstance(segment.term_mapping, dict)


class TestTerminologyConfig:
    """Test TerminologyConfig dataclass."""

    def test_terminology_config_minimal(self):
        """Test TerminologyConfig with only version."""
        config = TerminologyConfig(version="1.0")
        assert config.version == "1.0"
        assert len(config.global_rules) == 0
        assert len(config.site_overrides) == 0
        assert len(config.auto_discovery) == 0

    def test_terminology_config_with_global_rules(self):
        """Test TerminologyConfig with global rules."""
        rule1 = TermRule(
            term="Aspose",
            category="company_name",
            preserve_mode=PreserveMode.BOTH,
            severity=TermSeverity.ERROR
        )
        rule2 = TermRule(
            term=".NET",
            category="platform",
            preserve_mode=PreserveMode.PROTECT,
            severity=TermSeverity.WARNING
        )
        config = TerminologyConfig(
            version="1.0",
            global_rules=[rule1, rule2]
        )
        assert len(config.global_rules) == 2
        assert config.global_rules[0].term == "Aspose"
        assert config.global_rules[1].term == ".NET"

    def test_terminology_config_with_site_overrides(self):
        """Test TerminologyConfig with site-specific overrides."""
        rule1 = TermRule(
            term="Aspose",
            category="company_name",
            preserve_mode=PreserveMode.BOTH,
            severity=TermSeverity.ERROR
        )
        rule2 = TermRule(
            term="CustomTerm",
            category="custom",
            preserve_mode=PreserveMode.VALIDATE,
            severity=TermSeverity.INFO
        )
        config = TerminologyConfig(
            version="1.0",
            site_overrides={
                "site1": [rule1],
                "site2": [rule2]
            }
        )
        assert len(config.site_overrides) == 2
        assert "site1" in config.site_overrides
        assert "site2" in config.site_overrides
        assert config.site_overrides["site1"][0].term == "Aspose"
        assert config.site_overrides["site2"][0].term == "CustomTerm"

    def test_terminology_config_with_auto_discovery(self):
        """Test TerminologyConfig with auto-discovery settings."""
        config = TerminologyConfig(
            version="1.0",
            auto_discovery={
                "enabled": True,
                "min_frequency": 3,
                "confidence_threshold": 0.8
            }
        )
        assert config.auto_discovery["enabled"] is True
        assert config.auto_discovery["min_frequency"] == 3
        assert config.auto_discovery["confidence_threshold"] == 0.8

    def test_terminology_config_complete(self):
        """Test TerminologyConfig with all fields populated."""
        rule = TermRule(
            term="Aspose",
            category="company_name",
            preserve_mode=PreserveMode.BOTH,
            severity=TermSeverity.ERROR
        )
        override_rule = TermRule(
            term="SiteTerm",
            category="custom",
            preserve_mode=PreserveMode.VALIDATE,
            severity=TermSeverity.WARNING
        )
        config = TerminologyConfig(
            version="2.0",
            global_rules=[rule],
            site_overrides={"site1": [override_rule]},
            auto_discovery={"enabled": False}
        )
        assert config.version == "2.0"
        assert len(config.global_rules) == 1
        assert len(config.site_overrides) == 1
        assert config.auto_discovery["enabled"] is False

    def test_terminology_config_default_factories(self):
        """Test TerminologyConfig default factory fields are mutable."""
        config1 = TerminologyConfig(version="1.0")
        config2 = TerminologyConfig(version="2.0")

        # Ensure separate instances have separate default dicts/lists
        rule = TermRule(
            term="Test",
            category="test",
            preserve_mode=PreserveMode.PROTECT,
            severity=TermSeverity.INFO
        )
        config1.global_rules.append(rule)

        assert len(config1.global_rules) == 1
        assert len(config2.global_rules) == 0

    def test_terminology_config_empty_site_override(self):
        """Test TerminologyConfig with empty site override."""
        config = TerminologyConfig(
            version="1.0",
            site_overrides={"site1": []}
        )
        assert "site1" in config.site_overrides
        assert len(config.site_overrides["site1"]) == 0
