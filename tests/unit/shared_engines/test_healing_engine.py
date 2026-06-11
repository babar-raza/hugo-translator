"""
Unit tests for HealingEngine.

Tests retry and recovery wrapper with mocked RetryHandler.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

# Mock all external dependencies before importing modules that need them
for module in [
    "torch",
    "transformers",
    "lmdb",
    "sentence_transformers",
    "faiss",
    "frontmatter",
    "yaml",
    "markdown",
    "markdown_it",
    "pydantic",
    "redis",
    "structlog",
    "psutil",
]:
    sys.modules[module] = MagicMock()

# Special handling for ruamel.yaml namespace package
ruamel_mock = MagicMock()
ruamel_mock.yaml = MagicMock()
ruamel_mock.yaml.comments = MagicMock()
ruamel_mock.yaml.scalarstring = MagicMock()
sys.modules["ruamel"] = ruamel_mock
sys.modules["ruamel.yaml"] = ruamel_mock.yaml
sys.modules["ruamel.yaml.comments"] = ruamel_mock.yaml.comments
sys.modules["ruamel.yaml.scalarstring"] = ruamel_mock.yaml.scalarstring

from src.shared_engines.healing_engine import HealingEngine


class TestHealingEngine(unittest.TestCase):
    """Test HealingEngine wrapper."""

    @patch("src.shared_engines.healing_engine.RetryHandler")
    def test_initialization_default_config(self, mock_retry_handler):
        """Test HealingEngine initializes with default config."""
        mock_handler_instance = Mock()
        mock_retry_handler.return_value = mock_handler_instance

        engine = HealingEngine()

        self.assertEqual(engine.max_retries, 3)
        self.assertEqual(engine.batch_reduction_factor, 0.5)
        self.assertEqual(engine.min_batch_size, 1)
        mock_retry_handler.assert_called_once_with(
            max_retries=3, batch_reduction_factor=0.5, min_batch_size=1
        )

    @patch("src.shared_engines.healing_engine.RetryHandler")
    def test_initialization_custom_config(self, mock_retry_handler):
        """Test HealingEngine initializes with custom config."""
        mock_handler_instance = Mock()
        mock_retry_handler.return_value = mock_handler_instance

        engine = HealingEngine(max_retries=5, batch_reduction_factor=0.6, min_batch_size=2)

        self.assertEqual(engine.max_retries, 5)
        self.assertEqual(engine.batch_reduction_factor, 0.6)
        self.assertEqual(engine.min_batch_size, 2)
        mock_retry_handler.assert_called_once_with(
            max_retries=5, batch_reduction_factor=0.6, min_batch_size=2
        )

    @patch("src.shared_engines.healing_engine.RetryHandler")
    def test_with_retry_success_first_attempt(self, mock_retry_handler):
        """Test with_retry() succeeds on first attempt."""
        mock_handler_instance = Mock()
        mock_result = Mock()
        mock_handler_instance.translate_file_with_retry.return_value = mock_result
        mock_retry_handler.return_value = mock_handler_instance

        engine = HealingEngine()
        mock_func = Mock()
        file_path = Path("example.md")

        result = engine.with_retry(
            func=mock_func, file_path=file_path, initial_batch_size=9, target_lang="es"
        )

        self.assertEqual(result, mock_result)
        mock_handler_instance.translate_file_with_retry.assert_called_once_with(
            translate_func=mock_func,
            file_path=file_path,
            initial_batch_size=9,
            on_oom_recovery=None,
            target_lang="es",
        )

    @patch("src.shared_engines.healing_engine.RetryHandler")
    def test_with_retry_with_recovery_callback(self, mock_retry_handler):
        """Test with_retry() with recovery callback."""
        mock_handler_instance = Mock()
        mock_result = Mock()
        mock_handler_instance.translate_file_with_retry.return_value = mock_result
        mock_retry_handler.return_value = mock_handler_instance

        engine = HealingEngine()
        mock_func = Mock()
        file_path = Path("example.md")
        mock_callback = Mock()

        result = engine.with_retry(
            func=mock_func, file_path=file_path, initial_batch_size=9, on_oom_recovery=mock_callback
        )

        self.assertEqual(result, mock_result)
        mock_handler_instance.translate_file_with_retry.assert_called_once_with(
            translate_func=mock_func,
            file_path=file_path,
            initial_batch_size=9,
            on_oom_recovery=mock_callback,
        )

    @patch("src.shared_engines.healing_engine.RetryHandler")
    def test_with_retry_with_additional_kwargs(self, mock_retry_handler):
        """Test with_retry() passes additional kwargs."""
        mock_handler_instance = Mock()
        mock_result = Mock()
        mock_handler_instance.translate_file_with_retry.return_value = mock_result
        mock_retry_handler.return_value = mock_handler_instance

        engine = HealingEngine()
        mock_func = Mock()
        file_path = Path("example.md")

        result = engine.with_retry(
            func=mock_func,
            file_path=file_path,
            initial_batch_size=9,
            target_lang="es",
            model="m2m100_418m",
            use_gpu=True,
        )

        mock_handler_instance.translate_file_with_retry.assert_called_once_with(
            translate_func=mock_func,
            file_path=file_path,
            initial_batch_size=9,
            on_oom_recovery=None,
            target_lang="es",
            model="m2m100_418m",
            use_gpu=True,
        )

    @patch("src.shared_engines.healing_engine.RetryHandler")
    def test_is_oom_error_true(self, mock_retry_handler):
        """Test is_oom_error() returns True for OOM errors."""
        mock_handler_instance = Mock()
        mock_handler_instance._is_oom_error.return_value = True
        mock_retry_handler.return_value = mock_handler_instance

        engine = HealingEngine()
        test_exception = Exception("CUDA out of memory")

        result = engine.is_oom_error(test_exception)

        self.assertTrue(result)
        mock_handler_instance._is_oom_error.assert_called_once_with(test_exception)

    @patch("src.shared_engines.healing_engine.RetryHandler")
    def test_is_oom_error_false(self, mock_retry_handler):
        """Test is_oom_error() returns False for non-OOM errors."""
        mock_handler_instance = Mock()
        mock_handler_instance._is_oom_error.return_value = False
        mock_retry_handler.return_value = mock_handler_instance

        engine = HealingEngine()
        test_exception = Exception("File not found")

        result = engine.is_oom_error(test_exception)

        self.assertFalse(result)
        mock_handler_instance._is_oom_error.assert_called_once_with(test_exception)

    @patch("src.shared_engines.healing_engine.RetryHandler")
    def test_reduce_batch_size(self, mock_retry_handler):
        """Test reduce_batch_size() calculates reduced size."""
        mock_handler_instance = Mock()
        mock_retry_handler.return_value = mock_handler_instance

        engine = HealingEngine(batch_reduction_factor=0.5, min_batch_size=1)

        # Test normal reduction
        self.assertEqual(engine.reduce_batch_size(9), 4)
        self.assertEqual(engine.reduce_batch_size(4), 2)
        self.assertEqual(engine.reduce_batch_size(2), 1)

        # Test minimum boundary
        self.assertEqual(engine.reduce_batch_size(1), 1)

    @patch("src.shared_engines.healing_engine.RetryHandler")
    def test_reduce_batch_size_respects_minimum(self, mock_retry_handler):
        """Test reduce_batch_size() respects min_batch_size."""
        mock_handler_instance = Mock()
        mock_retry_handler.return_value = mock_handler_instance

        engine = HealingEngine(batch_reduction_factor=0.5, min_batch_size=2)

        # Should not go below min_batch_size
        self.assertEqual(engine.reduce_batch_size(4), 2)
        self.assertEqual(engine.reduce_batch_size(2), 2)

    @patch("src.shared_engines.healing_engine.RetryHandler")
    def test_get_max_retries(self, mock_retry_handler):
        """Test get_max_retries() returns correct value."""
        mock_handler_instance = Mock()
        mock_retry_handler.return_value = mock_handler_instance

        engine = HealingEngine(max_retries=5)

        self.assertEqual(engine.get_max_retries(), 5)

    @patch("src.shared_engines.healing_engine.RetryHandler")
    def test_get_reduction_factor(self, mock_retry_handler):
        """Test get_reduction_factor() returns correct value."""
        mock_handler_instance = Mock()
        mock_retry_handler.return_value = mock_handler_instance

        engine = HealingEngine(batch_reduction_factor=0.6)

        self.assertEqual(engine.get_reduction_factor(), 0.6)

    @patch("src.shared_engines.healing_engine.RetryHandler")
    def test_get_min_batch_size(self, mock_retry_handler):
        """Test get_min_batch_size() returns correct value."""
        mock_handler_instance = Mock()
        mock_retry_handler.return_value = mock_handler_instance

        engine = HealingEngine(min_batch_size=2)

        self.assertEqual(engine.get_min_batch_size(), 2)

    @patch("src.shared_engines.healing_engine.RetryHandler")
    def test_update_config(self, mock_retry_handler):
        """Test update_config() modifies config at runtime."""
        mock_handler_instance = Mock()
        mock_retry_handler.return_value = mock_handler_instance

        engine = HealingEngine()

        # Update config
        engine.update_config(max_retries=5, batch_reduction_factor=0.6, min_batch_size=2)

        self.assertEqual(engine.max_retries, 5)
        self.assertEqual(engine.batch_reduction_factor, 0.6)
        self.assertEqual(engine.min_batch_size, 2)

        # Verify handler updated too
        self.assertEqual(mock_handler_instance.max_retries, 5)
        self.assertEqual(mock_handler_instance.batch_reduction_factor, 0.6)
        self.assertEqual(mock_handler_instance.min_batch_size, 2)

    @patch("src.shared_engines.healing_engine.RetryHandler")
    def test_update_config_partial(self, mock_retry_handler):
        """Test update_config() with partial updates."""
        mock_handler_instance = Mock()
        mock_retry_handler.return_value = mock_handler_instance

        engine = HealingEngine(max_retries=3, batch_reduction_factor=0.5)

        # Update only one field
        engine.update_config(max_retries=7)

        self.assertEqual(engine.max_retries, 7)
        self.assertEqual(engine.batch_reduction_factor, 0.5)  # Unchanged

    @patch("src.shared_engines.healing_engine.RetryHandler")
    def test_update_config_invalid_key(self, mock_retry_handler):
        """Test update_config() ignores invalid keys."""
        mock_handler_instance = Mock()
        mock_retry_handler.return_value = mock_handler_instance

        engine = HealingEngine(max_retries=3)

        # Try to update invalid field
        engine.update_config(invalid_field="value")

        # Config should remain unchanged
        self.assertEqual(engine.max_retries, 3)

    @patch("src.shared_engines.healing_engine.RetryHandler")
    def test_get_retry_handler(self, mock_retry_handler):
        """Test get_retry_handler() returns underlying RetryHandler."""
        mock_handler_instance = Mock()
        mock_retry_handler.return_value = mock_handler_instance

        engine = HealingEngine()
        handler = engine.get_retry_handler()

        self.assertEqual(handler, mock_handler_instance)


if __name__ == "__main__":
    unittest.main()
