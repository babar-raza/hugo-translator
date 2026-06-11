"""
Unit tests for TextUnitExtractor site profile configuration loading.

Tests TASK-B002: Resolve TODOs in text_unit_extractor.py
"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.translation_engine.extractor.text_unit_extractor import (
    FALLBACK_RATE_THRESHOLD,
    LANGUAGE_PURITY_MIN_LENGTH,
    LANGUAGE_PURITY_MIN_SCRIPT_RATIO,
    NON_TRANSLATABLE_FRONTMATTER_FIELDS,
    SCRIPT_SIMILAR_LANGUAGES,
    TOKEN_PER_WORD_ESTIMATE,
    TRANSLATABLE_FRONTMATTER_FIELDS,
    TextUnitExtractor,
)


class TestFrontmatterConfigLoading:
    """Test frontmatter field configuration from site profiles."""

    def test_translatable_fields_default_fallback(self):
        """Test default translatable fields when no site profile provided."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        fields = extractor._get_translatable_frontmatter_fields()

        assert fields == TRANSLATABLE_FRONTMATTER_FIELDS
        assert "title" in fields
        assert "description" in fields

    def test_protected_fields_default_fallback(self):
        """Test default protected fields when no site profile provided."""
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        fields = extractor._get_protected_frontmatter_fields()

        assert fields == NON_TRANSLATABLE_FRONTMATTER_FIELDS
        assert "slug" in fields
        assert "date" in fields

    def test_translatable_fields_from_site_profile_pydantic_object(self):
        """Test loading translatable fields from site profile (Pydantic object)."""
        # Create mock site profile with Pydantic-like structure
        mock_profile = Mock()

        # Mock FrontmatterRule objects
        title_rule = Mock()
        title_rule.mode = "translate"

        description_rule = Mock()
        description_rule.mode = "translate"

        summary_rule = Mock()
        summary_rule.mode = "translate_list"

        slug_rule = Mock()
        slug_rule.mode = "passthrough"

        mock_profile.frontmatter = {
            "title": title_rule,
            "description": description_rule,
            "summary": summary_rule,
            "slug": slug_rule,
        }

        extractor = TextUnitExtractor(segmentation_strategy="leaf_only", site_profile=mock_profile)

        fields = extractor._get_translatable_frontmatter_fields()

        assert "title" in fields
        assert "description" in fields
        assert "summary" in fields  # translate_list should be translatable
        assert "slug" not in fields  # passthrough should not be translatable

    def test_protected_fields_from_site_profile_pydantic_object(self):
        """Test loading protected fields from site profile (Pydantic object)."""
        # Create mock site profile
        mock_profile = Mock()

        title_rule = Mock()
        title_rule.mode = "translate"

        slug_rule = Mock()
        slug_rule.mode = "passthrough"

        date_rule = Mock()
        date_rule.mode = "passthrough"

        mock_profile.frontmatter = {"title": title_rule, "slug": slug_rule, "date": date_rule}

        extractor = TextUnitExtractor(segmentation_strategy="leaf_only", site_profile=mock_profile)

        fields = extractor._get_protected_frontmatter_fields()

        assert "slug" in fields
        assert "date" in fields
        assert "title" not in fields  # translate should not be protected

    def test_translatable_fields_from_site_profile_dict(self):
        """Test loading translatable fields from site profile (dict format)."""
        # Create mock site profile with dict-based frontmatter rules
        mock_profile = Mock()
        mock_profile.frontmatter = {
            "title": {"mode": "translate", "strategy": None},
            "description": {"mode": "translate", "strategy": None},
            "slug": {"mode": "passthrough", "strategy": None},
            "keywords": {"mode": "translate_list", "strategy": None},
        }

        extractor = TextUnitExtractor(segmentation_strategy="leaf_only", site_profile=mock_profile)

        fields = extractor._get_translatable_frontmatter_fields()

        assert "title" in fields
        assert "description" in fields
        assert "keywords" in fields
        assert "slug" not in fields

    def test_protected_fields_from_site_profile_dict(self):
        """Test loading protected fields from site profile (dict format)."""
        mock_profile = Mock()
        mock_profile.frontmatter = {
            "title": {"mode": "translate", "strategy": None},
            "slug": {"mode": "passthrough", "strategy": None},
            "date": {"mode": "passthrough", "strategy": None},
            "productkey": {"mode": "passthrough", "strategy": None},
        }

        extractor = TextUnitExtractor(segmentation_strategy="leaf_only", site_profile=mock_profile)

        fields = extractor._get_protected_frontmatter_fields()

        assert "slug" in fields
        assert "date" in fields
        assert "productkey" in fields
        assert "title" not in fields

    def test_empty_frontmatter_config_fallback(self):
        """Test fallback to defaults when frontmatter config is empty."""
        mock_profile = Mock()
        mock_profile.frontmatter = {}

        extractor = TextUnitExtractor(segmentation_strategy="leaf_only", site_profile=mock_profile)

        translatable = extractor._get_translatable_frontmatter_fields()
        protected = extractor._get_protected_frontmatter_fields()

        # Should fall back to defaults
        assert translatable == TRANSLATABLE_FRONTMATTER_FIELDS
        assert protected == NON_TRANSLATABLE_FRONTMATTER_FIELDS

    def test_missing_frontmatter_attribute_fallback(self):
        """Test fallback to defaults when site profile has no frontmatter attribute."""
        mock_profile = Mock(spec=[])  # Empty spec = no attributes

        extractor = TextUnitExtractor(segmentation_strategy="leaf_only", site_profile=mock_profile)

        translatable = extractor._get_translatable_frontmatter_fields()
        protected = extractor._get_protected_frontmatter_fields()

        # Should fall back to defaults
        assert translatable == TRANSLATABLE_FRONTMATTER_FIELDS
        assert protected == NON_TRANSLATABLE_FRONTMATTER_FIELDS

    def test_custom_field_names(self):
        """Test custom frontmatter field names from site profile."""
        mock_profile = Mock()

        # Custom fields not in defaults
        step1_rule = Mock()
        step1_rule.mode = "translate"

        step2_rule = Mock()
        step2_rule.mode = "translate"

        custom_protected = Mock()
        custom_protected.mode = "passthrough"

        mock_profile.frontmatter = {
            "step1": step1_rule,
            "step2": step2_rule,
            "custom_field": custom_protected,
        }

        extractor = TextUnitExtractor(segmentation_strategy="leaf_only", site_profile=mock_profile)

        translatable = extractor._get_translatable_frontmatter_fields()
        protected = extractor._get_protected_frontmatter_fields()

        assert "step1" in translatable
        assert "step2" in translatable
        assert "custom_field" in protected

    def test_mode_filtering_comprehensive(self):
        """Test comprehensive mode filtering (all mode types)."""
        mock_profile = Mock()
        mock_profile.frontmatter = {
            "translate_field": {"mode": "translate"},
            "passthrough_field": {"mode": "passthrough"},
            "translate_list_field": {"mode": "translate_list"},
            "computed_field": {"mode": "computed"},  # Should not appear in either set
            "ignore_field": {"mode": "ignore"},  # Should not appear in either set
        }

        extractor = TextUnitExtractor(segmentation_strategy="leaf_only", site_profile=mock_profile)

        translatable = extractor._get_translatable_frontmatter_fields()
        protected = extractor._get_protected_frontmatter_fields()

        # Translatable: translate + translate_list
        assert "translate_field" in translatable
        assert "translate_list_field" in translatable

        # Protected: passthrough only
        assert "passthrough_field" in protected

        # Not in either set
        assert "computed_field" not in translatable
        assert "computed_field" not in protected
        assert "ignore_field" not in translatable
        assert "ignore_field" not in protected

    def test_malformed_rule_handled_gracefully(self):
        """Test graceful handling of malformed frontmatter rules."""
        mock_profile = Mock()
        mock_profile.frontmatter = {
            "good_field": {"mode": "translate"},
            "bad_field": None,  # Invalid rule
            "another_good": {"mode": "passthrough"},
        }

        extractor = TextUnitExtractor(segmentation_strategy="leaf_only", site_profile=mock_profile)

        translatable = extractor._get_translatable_frontmatter_fields()
        protected = extractor._get_protected_frontmatter_fields()

        # Good fields should still work
        assert "good_field" in translatable
        assert "another_good" in protected

        # Bad field should be skipped silently
        assert "bad_field" not in translatable
        assert "bad_field" not in protected

    def test_backward_compatibility_with_existing_tests(self):
        """Test backward compatibility - existing tests without site_profile still work."""
        # This mimics how existing tests create extractors
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        # Should use defaults
        translatable = extractor._get_translatable_frontmatter_fields()
        protected = extractor._get_protected_frontmatter_fields()

        # Default fields should be present
        assert "title" in translatable
        assert "description" in translatable
        assert "keywords" in translatable

        assert "slug" in protected
        assert "date" in protected
        assert "productname" in protected


class TestIntegrationWithExtraction:
    """Test integration of config loading with frontmatter extraction."""

    def test_frontmatter_extraction_uses_site_profile(self):
        """Test that frontmatter extraction respects site profile configuration."""

        # Create site profile with custom fields
        mock_profile = Mock()
        custom_title = Mock()
        custom_title.mode = "translate"
        custom_meta = Mock()
        custom_meta.mode = "passthrough"

        mock_profile.frontmatter = {"custom_title": custom_title, "custom_meta": custom_meta}

        extractor = TextUnitExtractor(segmentation_strategy="leaf_only", site_profile=mock_profile)

        frontmatter = {"custom_title": "My Custom Title", "custom_meta": "metadata123"}

        plan = extractor.extract_from_ast([], frontmatter=frontmatter)

        # Should extract custom_title (translatable)
        frontmatter_units = [
            u for u in plan.units if u.node_addr and u.node_addr.startswith("frontmatter.")
        ]
        field_names = {u.metadata.get("field_name") for u in frontmatter_units}

        assert "custom_title" in field_names
        assert "custom_meta" not in field_names  # Protected, not extracted

    def test_default_frontmatter_extraction_unchanged(self):
        """Test that default frontmatter extraction still works without site profile."""

        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        frontmatter = {
            "title": "Test Title",
            "description": "Test Description",
            "slug": "test-slug",  # Protected
            "date": "2025-01-01",  # Protected
        }

        plan = extractor.extract_from_ast([], frontmatter=frontmatter)

        frontmatter_units = [
            u for u in plan.units if u.node_addr and u.node_addr.startswith("frontmatter.")
        ]
        field_names = {u.metadata.get("field_name") for u in frontmatter_units}

        # Should extract default translatable fields
        assert "title" in field_names
        assert "description" in field_names

        # Should not extract default protected fields
        assert "slug" not in field_names
        assert "date" not in field_names


class TestExtractionConfigLoading:
    """Test extraction config loading from site profiles (TASK-B002)."""

    def test_default_config_no_site_profile(self):
        """Test that default values are used when no site profile is provided."""
        extractor = TextUnitExtractor(site_profile=None)

        # Should use module-level defaults
        assert extractor.language_purity_min_length == LANGUAGE_PURITY_MIN_LENGTH
        assert extractor.language_purity_min_script_ratio == LANGUAGE_PURITY_MIN_SCRIPT_RATIO
        assert extractor.fallback_rate_threshold == FALLBACK_RATE_THRESHOLD
        assert extractor.token_per_word_estimate == TOKEN_PER_WORD_ESTIMATE
        assert extractor.script_similar_languages == SCRIPT_SIMILAR_LANGUAGES

    def test_default_config_empty_site_profile(self):
        """Test that default values are used when site profile has no extraction config."""
        site_profile = {}
        extractor = TextUnitExtractor(site_profile=site_profile)

        # Should use module-level defaults
        assert extractor.language_purity_min_length == LANGUAGE_PURITY_MIN_LENGTH
        assert extractor.language_purity_min_script_ratio == LANGUAGE_PURITY_MIN_SCRIPT_RATIO
        assert extractor.fallback_rate_threshold == FALLBACK_RATE_THRESHOLD
        assert extractor.token_per_word_estimate == TOKEN_PER_WORD_ESTIMATE
        assert extractor.script_similar_languages == SCRIPT_SIMILAR_LANGUAGES

    def test_custom_language_purity_config(self):
        """Test loading custom language purity configuration."""
        site_profile = {
            "extraction": {
                "language_purity": {
                    "min_length": 20,
                    "min_script_ratio": 0.35,
                    "script_similar_languages": {
                        "ar": ["fa", "ur"],
                        "hi": ["ne", "mr"],
                    },
                }
            }
        }
        extractor = TextUnitExtractor(site_profile=site_profile)

        assert extractor.language_purity_min_length == 20
        assert extractor.language_purity_min_script_ratio == 0.35
        assert extractor.script_similar_languages == {
            "ar": ["fa", "ur"],
            "hi": ["ne", "mr"],
        }
        # Other configs should use defaults
        assert extractor.fallback_rate_threshold == FALLBACK_RATE_THRESHOLD
        assert extractor.token_per_word_estimate == TOKEN_PER_WORD_ESTIMATE

    def test_custom_batch_translation_config(self):
        """Test loading custom batch translation configuration."""
        site_profile = {
            "extraction": {
                "batch_translation": {
                    "fallback_rate_threshold": 0.10,
                    "token_per_word_estimate": 1.5,
                }
            }
        }
        extractor = TextUnitExtractor(site_profile=site_profile)

        assert extractor.fallback_rate_threshold == 0.10
        assert extractor.token_per_word_estimate == 1.5
        # Other configs should use defaults
        assert extractor.language_purity_min_length == LANGUAGE_PURITY_MIN_LENGTH
        assert extractor.language_purity_min_script_ratio == LANGUAGE_PURITY_MIN_SCRIPT_RATIO
        assert extractor.script_similar_languages == SCRIPT_SIMILAR_LANGUAGES

    def test_full_custom_config(self):
        """Test loading all custom configuration values."""
        site_profile = {
            "extraction": {
                "language_purity": {
                    "min_length": 25,
                    "min_script_ratio": 0.55,
                    "script_similar_languages": {
                        "sr": ["ru", "uk", "bg"],
                    },
                },
                "batch_translation": {
                    "fallback_rate_threshold": 0.08,
                    "token_per_word_estimate": 1.4,
                },
            }
        }
        extractor = TextUnitExtractor(site_profile=site_profile)

        assert extractor.language_purity_min_length == 25
        assert extractor.language_purity_min_script_ratio == 0.55
        assert extractor.script_similar_languages == {"sr": ["ru", "uk", "bg"]}
        assert extractor.fallback_rate_threshold == 0.08
        assert extractor.token_per_word_estimate == 1.4

    def test_object_attribute_access(self):
        """Test loading config from site profile with object attribute access."""
        # Simulate config loaded from YAML as object attributes
        extraction_config = SimpleNamespace(
            language_purity=SimpleNamespace(
                min_length=30, min_script_ratio=0.6, script_similar_languages={"ar": ["fa"]}
            ),
            batch_translation=SimpleNamespace(
                fallback_rate_threshold=0.07, token_per_word_estimate=1.6
            ),
        )
        site_profile = SimpleNamespace(extraction=extraction_config)
        extractor = TextUnitExtractor(site_profile=site_profile)

        assert extractor.language_purity_min_length == 30
        assert extractor.language_purity_min_script_ratio == 0.6
        assert extractor.script_similar_languages == {"ar": ["fa"]}
        assert extractor.fallback_rate_threshold == 0.07
        assert extractor.token_per_word_estimate == 1.6

    def test_partial_config_uses_defaults(self):
        """Test that partial config uses defaults for missing values."""
        site_profile = {
            "extraction": {
                "language_purity": {
                    "min_length": 18
                    # script_similar_languages is missing
                }
                # batch_translation is missing
            }
        }
        extractor = TextUnitExtractor(site_profile=site_profile)

        assert extractor.language_purity_min_length == 18
        assert extractor.language_purity_min_script_ratio == LANGUAGE_PURITY_MIN_SCRIPT_RATIO
        # Missing values should use defaults
        assert extractor.script_similar_languages == SCRIPT_SIMILAR_LANGUAGES
        assert extractor.fallback_rate_threshold == FALLBACK_RATE_THRESHOLD
        assert extractor.token_per_word_estimate == TOKEN_PER_WORD_ESTIMATE


class TestExtractionConfigValidation:
    """Test validation of extraction configuration values (TASK-B002)."""

    def test_invalid_min_length_too_low(self):
        """Test that min_length < 5 raises ValueError."""
        site_profile = {
            "extraction": {
                "language_purity": {
                    "min_length": 3  # Too low (< 5)
                }
            }
        }
        with pytest.raises(
            ValueError, match="language_purity.min_length must be between 5 and 100"
        ):
            TextUnitExtractor(site_profile=site_profile)

    def test_invalid_min_length_too_high(self):
        """Test that min_length > 100 raises ValueError."""
        site_profile = {
            "extraction": {
                "language_purity": {
                    "min_length": 150  # Too high (> 100)
                }
            }
        }
        with pytest.raises(
            ValueError, match="language_purity.min_length must be between 5 and 100"
        ):
            TextUnitExtractor(site_profile=site_profile)

    def test_invalid_min_script_ratio_too_low(self):
        """Test that min_script_ratio < 0.0 raises ValueError."""
        site_profile = {
            "extraction": {
                "language_purity": {
                    "min_script_ratio": -0.1  # Too low (< 0.0)
                }
            }
        }
        with pytest.raises(
            ValueError, match="language_purity.min_script_ratio must be between 0.0 and 1.0"
        ):
            TextUnitExtractor(site_profile=site_profile)

    def test_invalid_min_script_ratio_too_high(self):
        """Test that min_script_ratio > 1.0 raises ValueError."""
        site_profile = {
            "extraction": {
                "language_purity": {
                    "min_script_ratio": 1.2  # Too high (> 1.0)
                }
            }
        }
        with pytest.raises(
            ValueError, match="language_purity.min_script_ratio must be between 0.0 and 1.0"
        ):
            TextUnitExtractor(site_profile=site_profile)

    def test_invalid_fallback_threshold_too_low(self):
        """Test that fallback_rate_threshold < 0.01 raises ValueError."""
        site_profile = {
            "extraction": {
                "batch_translation": {
                    "fallback_rate_threshold": 0.001  # Too low (< 0.01)
                }
            }
        }
        with pytest.raises(
            ValueError, match="fallback_rate_threshold must be between 0.01 and 0.5"
        ):
            TextUnitExtractor(site_profile=site_profile)

    def test_invalid_fallback_threshold_too_high(self):
        """Test that fallback_rate_threshold > 0.5 raises ValueError."""
        site_profile = {
            "extraction": {
                "batch_translation": {
                    "fallback_rate_threshold": 0.8  # Too high (> 0.5)
                }
            }
        }
        with pytest.raises(
            ValueError, match="fallback_rate_threshold must be between 0.01 and 0.5"
        ):
            TextUnitExtractor(site_profile=site_profile)

    def test_invalid_token_estimate_too_low(self):
        """Test that token_per_word_estimate < 0.5 raises ValueError."""
        site_profile = {
            "extraction": {
                "batch_translation": {
                    "token_per_word_estimate": 0.3  # Too low (< 0.5)
                }
            }
        }
        with pytest.raises(ValueError, match="token_per_word_estimate must be between 0.5 and 3.0"):
            TextUnitExtractor(site_profile=site_profile)

    def test_invalid_token_estimate_too_high(self):
        """Test that token_per_word_estimate > 3.0 raises ValueError."""
        site_profile = {
            "extraction": {
                "batch_translation": {
                    "token_per_word_estimate": 5.0  # Too high (> 3.0)
                }
            }
        }
        with pytest.raises(ValueError, match="token_per_word_estimate must be between 0.5 and 3.0"):
            TextUnitExtractor(site_profile=site_profile)

    def test_invalid_script_similar_languages_type(self):
        """Test that script_similar_languages must be a dict."""
        site_profile = {
            "extraction": {
                "language_purity": {
                    "script_similar_languages": ["ar", "fa"]  # Should be dict, not list
                }
            }
        }
        with pytest.raises(ValueError, match="script_similar_languages must be a dictionary"):
            TextUnitExtractor(site_profile=site_profile)

    def test_valid_edge_case_values(self):
        """Test that edge case values within valid ranges are accepted."""
        site_profile = {
            "extraction": {
                "language_purity": {
                    "min_length": 5,  # Minimum valid value
                    "min_script_ratio": 0.0,  # Minimum valid value
                    "script_similar_languages": {},  # Empty dict is valid
                },
                "batch_translation": {
                    "fallback_rate_threshold": 0.01,  # Minimum valid value
                    "token_per_word_estimate": 0.5,  # Minimum valid value
                },
            }
        }
        extractor = TextUnitExtractor(site_profile=site_profile)

        assert extractor.language_purity_min_length == 5
        assert extractor.language_purity_min_script_ratio == 0.0
        assert extractor.fallback_rate_threshold == 0.01
        assert extractor.token_per_word_estimate == 0.5
        assert extractor.script_similar_languages == {}

    def test_valid_maximum_values(self):
        """Test that maximum valid values are accepted."""
        site_profile = {
            "extraction": {
                "language_purity": {
                    "min_length": 100,  # Maximum valid value
                    "min_script_ratio": 1.0,  # Maximum valid value
                },
                "batch_translation": {
                    "fallback_rate_threshold": 0.5,  # Maximum valid value
                    "token_per_word_estimate": 3.0,  # Maximum valid value
                },
            }
        }
        extractor = TextUnitExtractor(site_profile=site_profile)

        assert extractor.language_purity_min_length == 100
        assert extractor.language_purity_min_script_ratio == 1.0
        assert extractor.fallback_rate_threshold == 0.5
        assert extractor.token_per_word_estimate == 3.0


class TestExtractionConfigBehavior:
    """Test that extraction config affects runtime behavior (TASK-B002)."""

    def test_custom_token_estimate_affects_batch_sizing(self):
        """Test that custom token_per_word_estimate affects token calculation."""
        site_profile = {
            "extraction": {
                "batch_translation": {
                    "token_per_word_estimate": 2.0  # Higher than default 1.3
                }
            }
        }
        extractor = TextUnitExtractor(site_profile=site_profile)

        # Test token estimation
        text = "This is a test sentence with ten words here"
        estimated_tokens = extractor._estimate_token_count(text)

        word_count = len(text.split())
        expected_tokens = int(word_count * 2.0)

        assert estimated_tokens == expected_tokens
        assert estimated_tokens > int(word_count * 1.3)  # Should be higher than default

    def test_custom_script_similar_languages_stored(self):
        """Test that custom script_similar_languages is properly stored."""
        site_profile = {
            "extraction": {
                "language_purity": {
                    "script_similar_languages": {
                        "de": ["nl", "da"],  # German similar to Dutch and Danish
                        "hi": ["ne", "mr"],  # Hindi similar to Nepali and Marathi
                    }
                }
            }
        }
        extractor = TextUnitExtractor(site_profile=site_profile)

        # Verify config is loaded
        assert extractor.script_similar_languages == {
            "de": ["nl", "da"],
            "hi": ["ne", "mr"],
        }

        # Verify it doesn't have the default Arabic-Farsi mapping
        assert "ar" not in extractor.script_similar_languages


class TestBackwardCompatibilityExtraction:
    """Test backward compatibility for extraction config (TASK-B002)."""

    def test_existing_code_without_site_profile_works(self):
        """Test that existing code without site_profile continues to work."""
        # This simulates existing code that doesn't pass site_profile
        extractor = TextUnitExtractor(
            segmentation_strategy="adaptive",
            terminology_file=None,
            mt_model=None,
            preserve_patterns=None,
        )

        # Should work with defaults
        assert extractor.language_purity_min_length == LANGUAGE_PURITY_MIN_LENGTH
        assert extractor.language_purity_min_script_ratio == LANGUAGE_PURITY_MIN_SCRIPT_RATIO
        assert extractor.fallback_rate_threshold == FALLBACK_RATE_THRESHOLD
        assert extractor.token_per_word_estimate == TOKEN_PER_WORD_ESTIMATE

    def test_site_profile_without_extraction_section_works(self):
        """Test that site profiles without extraction section still work."""
        # This simulates existing site profiles that don't have extraction config yet
        site_profile = {
            "site_id": "test.com",
            "frontmatter": {"title": {"mode": "translate"}, "slug": {"mode": "passthrough"}},
            "body": {"translate_markdown": True},
        }
        extractor = TextUnitExtractor(site_profile=site_profile)

        # Should work with defaults
        assert extractor.language_purity_min_length == LANGUAGE_PURITY_MIN_LENGTH
        assert extractor.language_purity_min_script_ratio == LANGUAGE_PURITY_MIN_SCRIPT_RATIO
        assert extractor.fallback_rate_threshold == FALLBACK_RATE_THRESHOLD
