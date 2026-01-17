"""
Unit tests for git_commit_helper._extract_model_id.

Tests all 3 tiers of model_id extraction and edge cases.
"""
import unittest
from unittest.mock import Mock, MagicMock
from dataclasses import dataclass
from typing import List, Optional

from src.observability.git_commit_helper import _extract_model_id


# Mock classes matching DirectoryResult structure
@dataclass
class MockAggregateStats:
    """Mock AggregateStats for testing."""
    model_used: Optional[str] = None


@dataclass
class MockTranslationStats:
    """Mock TranslationStats for testing."""
    model_used: Optional[str] = None


@dataclass
class MockFileResult:
    """Mock file result for testing."""
    stats: Optional[MockTranslationStats] = None


@dataclass
class MockDirectoryResult:
    """Mock DirectoryResult for testing."""
    aggregate_stats: Optional[MockAggregateStats] = None
    file_results: List[MockFileResult] = None

    def __post_init__(self):
        if self.file_results is None:
            self.file_results = []


class TestExtractModelId(unittest.TestCase):
    """Test _extract_model_id function with all tiers and edge cases."""

    def test_tier1_aggregate_stats_success(self):
        """Test Tier 1: Extract from aggregate_stats.model_used."""
        # Setup: dir_result with aggregate_stats.model_used = "facebook/nllb-200"
        dir_result = MockDirectoryResult(
            aggregate_stats=MockAggregateStats(model_used="facebook/nllb-200")
        )
        config = {"model_defaults": {"fallback_model": "m2m100_418m"}}

        # Act
        result = _extract_model_id(dir_result, config=config)

        # Assert
        self.assertEqual(result, "facebook/nllb-200")

    def test_tier1_with_empty_string_falls_through(self):
        """Test that empty string from Tier 1 triggers fallback."""
        # Setup: aggregate_stats.model_used = "" (empty string)
        dir_result = MockDirectoryResult(
            aggregate_stats=MockAggregateStats(model_used="")
        )
        config = {"model_defaults": {"fallback_model": "m2m100_418m"}}

        # Act
        result = _extract_model_id(dir_result, config=config)

        # Assert: Should fall through to Tier 3
        self.assertEqual(result, "m2m100_418m")

    def test_tier2_file_results_success(self):
        """Test Tier 2: Extract from file_results[0].stats.model_used when Tier 1 fails."""
        # Setup: dir_result with no aggregate_stats, but file_results[0].stats.model_used = "m2m100"
        dir_result = MockDirectoryResult(
            aggregate_stats=None,
            file_results=[
                MockFileResult(
                    stats=MockTranslationStats(model_used="m2m100")
                )
            ]
        )
        config = {"model_defaults": {"fallback_model": "m2m100_418m"}}

        # Act
        result = _extract_model_id(dir_result, config=config)

        # Assert
        self.assertEqual(result, "m2m100")

    def test_tier2_with_empty_string_falls_through(self):
        """Test that empty string from Tier 2 triggers fallback."""
        # Setup: file_results[0].stats.model_used = ""
        dir_result = MockDirectoryResult(
            aggregate_stats=None,
            file_results=[
                MockFileResult(
                    stats=MockTranslationStats(model_used="")
                )
            ]
        )
        config = {"model_defaults": {"fallback_model": "m2m100_418m"}}

        # Act
        result = _extract_model_id(dir_result, config=config)

        # Assert: Should fall through to Tier 3
        self.assertEqual(result, "m2m100_418m")

    def test_tier3_fallback_with_dict(self):
        """Test Tier 3: Use config fallback when Tier 1 and 2 fail (dict config)."""
        # Setup: dir_result with no model info, config with model_defaults.fallback_model = "m2m100_418m"
        dir_result = MockDirectoryResult(
            aggregate_stats=None,
            file_results=[]
        )
        config = {"model_defaults": {"fallback_model": "m2m100_418m"}}

        # Act
        result = _extract_model_id(dir_result, config=config)

        # Assert
        self.assertEqual(result, "m2m100_418m")

    def test_tier3_fallback_with_pydantic_model(self):
        """Test Tier 3: Use config fallback when model_defaults is a Pydantic model."""
        # Setup: dir_result with no model info, config with Pydantic model
        dir_result = MockDirectoryResult(
            aggregate_stats=None,
            file_results=[]
        )

        # Mock a Pydantic model
        mock_model_defaults = Mock()
        mock_model_defaults.fallback_model = "custom_model"

        config = {"model_defaults": mock_model_defaults}

        # Act
        result = _extract_model_id(dir_result, config=config)

        # Assert
        self.assertEqual(result, "custom_model")

    def test_tier3_missing_model_defaults_key(self):
        """Test Tier 3: Handle missing model_defaults key gracefully."""
        # Setup: dir_result with no model info, config without model_defaults
        dir_result = MockDirectoryResult(
            aggregate_stats=None,
            file_results=[]
        )
        config = {"other_key": "other_value"}

        # Act
        result = _extract_model_id(dir_result, config=config)

        # Assert: Should use hardcoded default
        self.assertEqual(result, "m2m100_418m")

    def test_no_config_returns_none(self):
        """Test that None is returned when no config provided and no model in results."""
        # Setup: dir_result with no model info, config=None
        dir_result = MockDirectoryResult(
            aggregate_stats=None,
            file_results=[]
        )

        # Act
        result = _extract_model_id(dir_result, config=None)

        # Assert
        self.assertIsNone(result)

    def test_exception_uses_fallback_with_dict(self):
        """Test that exceptions fall back to config if available (dict config)."""
        # Setup: dir_result that raises exception, valid config
        dir_result = Mock()
        dir_result.aggregate_stats = Mock()
        # Make accessing model_used raise an exception
        type(dir_result.aggregate_stats).model_used = property(
            lambda self: (_ for _ in ()).throw(RuntimeError("Test exception"))
        )

        config = {"model_defaults": {"fallback_model": "fallback_model"}}

        # Act
        result = _extract_model_id(dir_result, config=config)

        # Assert: Should use fallback despite exception
        self.assertEqual(result, "fallback_model")

    def test_exception_uses_fallback_with_pydantic(self):
        """Test that exceptions fall back to config if available (Pydantic config)."""
        # Setup: dir_result that raises exception, Pydantic config
        dir_result = Mock()
        dir_result.aggregate_stats = Mock()
        type(dir_result.aggregate_stats).model_used = property(
            lambda self: (_ for _ in ()).throw(RuntimeError("Test exception"))
        )

        mock_model_defaults = Mock()
        mock_model_defaults.fallback_model = "pydantic_fallback"
        config = {"model_defaults": mock_model_defaults}

        # Act
        result = _extract_model_id(dir_result, config=config)

        # Assert
        self.assertEqual(result, "pydantic_fallback")

    def test_exception_without_config_returns_none(self):
        """Test that exceptions without config return None."""
        # Setup: dir_result that raises exception, no config
        dir_result = Mock()
        dir_result.aggregate_stats = Mock()
        type(dir_result.aggregate_stats).model_used = property(
            lambda self: (_ for _ in ()).throw(RuntimeError("Test exception"))
        )

        # Act
        result = _extract_model_id(dir_result, config=None)

        # Assert
        self.assertIsNone(result)

    def test_tier1_with_none_falls_through(self):
        """Test that None from Tier 1 triggers fallback."""
        # Setup: aggregate_stats.model_used = None
        dir_result = MockDirectoryResult(
            aggregate_stats=MockAggregateStats(model_used=None)
        )
        config = {"model_defaults": {"fallback_model": "m2m100_418m"}}

        # Act
        result = _extract_model_id(dir_result, config=config)

        # Assert: Should fall through to Tier 3
        self.assertEqual(result, "m2m100_418m")

    def test_tier2_with_none_falls_through(self):
        """Test that None from Tier 2 triggers fallback."""
        # Setup: file_results[0].stats.model_used = None
        dir_result = MockDirectoryResult(
            aggregate_stats=None,
            file_results=[
                MockFileResult(
                    stats=MockTranslationStats(model_used=None)
                )
            ]
        )
        config = {"model_defaults": {"fallback_model": "m2m100_418m"}}

        # Act
        result = _extract_model_id(dir_result, config=config)

        # Assert: Should fall through to Tier 3
        self.assertEqual(result, "m2m100_418m")

    def test_empty_file_results_falls_through(self):
        """Test that empty file_results list triggers fallback."""
        # Setup: file_results = []
        dir_result = MockDirectoryResult(
            aggregate_stats=None,
            file_results=[]
        )
        config = {"model_defaults": {"fallback_model": "m2m100_418m"}}

        # Act
        result = _extract_model_id(dir_result, config=config)

        # Assert: Should fall through to Tier 3
        self.assertEqual(result, "m2m100_418m")

    def test_file_result_without_stats_falls_through(self):
        """Test that file_result without stats triggers fallback."""
        # Setup: file_results[0].stats = None
        dir_result = MockDirectoryResult(
            aggregate_stats=None,
            file_results=[MockFileResult(stats=None)]
        )
        config = {"model_defaults": {"fallback_model": "m2m100_418m"}}

        # Act
        result = _extract_model_id(dir_result, config=config)

        # Assert: Should fall through to Tier 3
        self.assertEqual(result, "m2m100_418m")

    def test_custom_fallback_model_respected(self):
        """Test that custom fallback_model in config is respected."""
        # Setup: No model in results, custom fallback in config
        dir_result = MockDirectoryResult(
            aggregate_stats=None,
            file_results=[]
        )
        config = {"model_defaults": {"fallback_model": "custom_fallback_model_v2"}}

        # Act
        result = _extract_model_id(dir_result, config=config)

        # Assert
        self.assertEqual(result, "custom_fallback_model_v2")

    def test_tier1_overrides_tier2(self):
        """Test that Tier 1 takes precedence over Tier 2 when both exist."""
        # Setup: Both aggregate_stats and file_results have model_used
        dir_result = MockDirectoryResult(
            aggregate_stats=MockAggregateStats(model_used="tier1_model"),
            file_results=[
                MockFileResult(
                    stats=MockTranslationStats(model_used="tier2_model")
                )
            ]
        )
        config = {"model_defaults": {"fallback_model": "m2m100_418m"}}

        # Act
        result = _extract_model_id(dir_result, config=config)

        # Assert: Should return Tier 1 model
        self.assertEqual(result, "tier1_model")


if __name__ == "__main__":
    unittest.main()
