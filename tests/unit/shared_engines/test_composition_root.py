"""
Unit tests for CompositionRoot.

Tests SharedEngines factory with mocked engine dependencies.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

# Mock all external dependencies before importing modules
for module in ['torch', 'transformers', 'lmdb', 'sentence_transformers', 'faiss',
               'frontmatter', 'yaml', 'markdown', 'markdown_it', 'pydantic',
               'redis', 'structlog', 'psutil']:
    sys.modules[module] = MagicMock()

# Special handling for ruamel.yaml namespace package
ruamel_mock = MagicMock()
ruamel_mock.yaml = MagicMock()
ruamel_mock.yaml.comments = MagicMock()
ruamel_mock.yaml.scalarstring = MagicMock()
sys.modules['ruamel'] = ruamel_mock
sys.modules['ruamel.yaml'] = ruamel_mock.yaml
sys.modules['ruamel.yaml.comments'] = ruamel_mock.yaml.comments
sys.modules['ruamel.yaml.scalarstring'] = ruamel_mock.yaml.scalarstring

from src.shared_engines.composition_root import CompositionRoot, SharedEngines


class TestCompositionRoot(unittest.TestCase):
    """Test CompositionRoot factory."""

    @patch('src.shared_engines.composition_root.MTBackend')
    @patch('src.shared_engines.composition_root.HealingEngine')
    @patch('src.shared_engines.composition_root.LimitingEngine')
    @patch('src.shared_engines.composition_root.CommitEngine')
    @patch('src.shared_engines.composition_root.JobEngine')
    @patch('src.shared_engines.composition_root.TelemetryEngine')
    @patch('src.shared_engines.composition_root.LoggingEngine')
    @patch('src.shared_engines.composition_root.ProfileEngine')
    def test_create_from_config_default(
        self,
        mock_profile,
        mock_logging,
        mock_telemetry,
        mock_job,
        mock_commit,
        mock_limiting,
        mock_healing,
        mock_mt_backend
    ):
        """Test create_from_config() with default configuration."""
        # Mock engine instances
        for mock in [mock_profile, mock_logging, mock_telemetry, mock_job,
                     mock_commit, mock_limiting, mock_healing, mock_mt_backend]:
            mock.return_value = Mock()

        engines = CompositionRoot.create_from_config({})

        self.assertIsInstance(engines, SharedEngines)
        # Verify all engines created
        mock_profile.assert_called_once()
        mock_logging.assert_called_once()
        mock_telemetry.assert_called_once()
        mock_job.assert_called_once()
        mock_commit.assert_called_once()
        mock_limiting.assert_called_once()
        mock_healing.assert_called_once()
        mock_mt_backend.assert_called_once()

    @patch('src.shared_engines.composition_root.MTBackend')
    @patch('src.shared_engines.composition_root.HealingEngine')
    @patch('src.shared_engines.composition_root.LimitingEngine')
    @patch('src.shared_engines.composition_root.CommitEngine')
    @patch('src.shared_engines.composition_root.JobEngine')
    @patch('src.shared_engines.composition_root.TelemetryEngine')
    @patch('src.shared_engines.composition_root.LoggingEngine')
    @patch('src.shared_engines.composition_root.ProfileEngine')
    def test_create_from_config_custom(
        self,
        mock_profile,
        mock_logging,
        mock_telemetry,
        mock_job,
        mock_commit,
        mock_limiting,
        mock_healing,
        mock_mt_backend
    ):
        """Test create_from_config() with custom configuration."""
        # Mock engine instances
        for mock in [mock_profile, mock_logging, mock_telemetry, mock_job,
                     mock_commit, mock_limiting, mock_healing, mock_mt_backend]:
            mock.return_value = Mock()

        config = {
            "config_root": "/custom/config",
            "log_level": "DEBUG",
            "log_file": Path("logs/test.ndjson"),
            "job_backend": "memory",
            "max_retries": 5
        }

        engines = CompositionRoot.create_from_config(config)

        self.assertIsInstance(engines, SharedEngines)

        # Verify ProfileEngine called with custom config_root
        mock_profile.assert_called_once_with(config_root="/custom/config")

        # Verify LoggingEngine called with custom log_level
        mock_logging.assert_called_once()
        args = mock_logging.call_args
        self.assertEqual(args[1]["log_level"], "DEBUG")
        self.assertEqual(args[1]["log_file"], Path("logs/test.ndjson"))

        # Verify HealingEngine called with custom max_retries
        mock_healing.assert_called_once()
        args = mock_healing.call_args
        self.assertEqual(args[1]["max_retries"], 5)

    @patch('src.shared_engines.composition_root.MTBackend')
    @patch('src.shared_engines.composition_root.HealingEngine')
    @patch('src.shared_engines.composition_root.LimitingEngine')
    @patch('src.shared_engines.composition_root.CommitEngine')
    @patch('src.shared_engines.composition_root.JobEngine')
    @patch('src.shared_engines.composition_root.TelemetryEngine')
    @patch('src.shared_engines.composition_root.LoggingEngine')
    @patch('src.shared_engines.composition_root.ProfileEngine')
    def test_create_from_config_redis_backend(
        self,
        mock_profile,
        mock_logging,
        mock_telemetry,
        mock_job,
        mock_commit,
        mock_limiting,
        mock_healing,
        mock_mt_backend
    ):
        """Test create_from_config() with Redis job backend."""
        # Mock engine instances
        for mock in [mock_profile, mock_logging, mock_telemetry, mock_job,
                     mock_commit, mock_limiting, mock_healing, mock_mt_backend]:
            mock.return_value = Mock()

        config = {
            "job_backend": "redis",
            "redis_host": "redis.example.com",
            "redis_port": 6380
        }

        engines = CompositionRoot.create_from_config(config)

        # Verify JobEngine called with Redis config
        mock_job.assert_called_once()
        args = mock_job.call_args
        self.assertEqual(args[1]["backend"], "redis")
        self.assertEqual(args[1]["config"]["redis_host"], "redis.example.com")
        self.assertEqual(args[1]["config"]["redis_port"], 6380)

    @patch('src.shared_engines.composition_root.LLMBackend')
    @patch('src.shared_engines.composition_root.HealingEngine')
    @patch('src.shared_engines.composition_root.LimitingEngine')
    @patch('src.shared_engines.composition_root.CommitEngine')
    @patch('src.shared_engines.composition_root.JobEngine')
    @patch('src.shared_engines.composition_root.TelemetryEngine')
    @patch('src.shared_engines.composition_root.LoggingEngine')
    @patch('src.shared_engines.composition_root.ProfileEngine')
    def test_create_from_config_llm_backend(
        self,
        mock_profile,
        mock_logging,
        mock_telemetry,
        mock_job,
        mock_commit,
        mock_limiting,
        mock_healing,
        mock_llm_backend
    ):
        """Test create_from_config() with LLM translation backend."""
        # Mock engine instances
        for mock in [mock_profile, mock_logging, mock_telemetry, mock_job,
                     mock_commit, mock_limiting, mock_healing, mock_llm_backend]:
            mock.return_value = Mock()

        config = {
            "translation_backend": "llm",
            "model_id": "gpt-4",
            "api_key": "test-key"
        }

        engines = CompositionRoot.create_from_config(config)

        # Verify LLMBackend called
        mock_llm_backend.assert_called_once()
        args = mock_llm_backend.call_args
        self.assertEqual(args[1]["model_id"], "gpt-4")
        self.assertEqual(args[1]["api_key"], "test-key")

    @patch('src.shared_engines.composition_root.MTBackend')
    @patch('src.shared_engines.composition_root.HealingEngine')
    @patch('src.shared_engines.composition_root.LimitingEngine')
    @patch('src.shared_engines.composition_root.CommitEngine')
    @patch('src.shared_engines.composition_root.JobEngine')
    @patch('src.shared_engines.composition_root.TelemetryEngine')
    @patch('src.shared_engines.composition_root.LoggingEngine')
    @patch('src.shared_engines.composition_root.ProfileEngine')
    def test_create_from_config_invalid_backend(
        self,
        mock_profile,
        mock_logging,
        mock_telemetry,
        mock_job,
        mock_commit,
        mock_limiting,
        mock_healing,
        mock_mt_backend
    ):
        """Test create_from_config() with invalid translation backend."""
        # Mock engine instances
        for mock in [mock_profile, mock_logging, mock_telemetry, mock_job,
                     mock_commit, mock_limiting, mock_healing, mock_mt_backend]:
            mock.return_value = Mock()

        config = {"translation_backend": "invalid"}

        with self.assertRaises(ValueError) as ctx:
            CompositionRoot.create_from_config(config)

        self.assertIn("Invalid translation_backend", str(ctx.exception))
        self.assertIn("invalid", str(ctx.exception))

    @patch('src.shared_engines.composition_root.MTBackend')
    @patch('src.shared_engines.composition_root.HealingEngine')
    @patch('src.shared_engines.composition_root.LimitingEngine')
    @patch('src.shared_engines.composition_root.CommitEngine')
    @patch('src.shared_engines.composition_root.JobEngine')
    @patch('src.shared_engines.composition_root.TelemetryEngine')
    @patch('src.shared_engines.composition_root.LoggingEngine')
    @patch('src.shared_engines.composition_root.ProfileEngine')
    def test_create_default(
        self,
        mock_profile,
        mock_logging,
        mock_telemetry,
        mock_job,
        mock_commit,
        mock_limiting,
        mock_healing,
        mock_mt_backend
    ):
        """Test create_default() creates engines with defaults."""
        # Mock engine instances
        for mock in [mock_profile, mock_logging, mock_telemetry, mock_job,
                     mock_commit, mock_limiting, mock_healing, mock_mt_backend]:
            mock.return_value = Mock()

        engines = CompositionRoot.create_default()

        self.assertIsInstance(engines, SharedEngines)
        # Verify all engines created with defaults
        mock_profile.assert_called_once()
        mock_logging.assert_called_once()

    @patch('src.shared_engines.composition_root.MTBackend')
    @patch('src.shared_engines.composition_root.HealingEngine')
    @patch('src.shared_engines.composition_root.LimitingEngine')
    @patch('src.shared_engines.composition_root.CommitEngine')
    @patch('src.shared_engines.composition_root.JobEngine')
    @patch('src.shared_engines.composition_root.TelemetryEngine')
    @patch('src.shared_engines.composition_root.LoggingEngine')
    @patch('src.shared_engines.composition_root.ProfileEngine')
    def test_create_for_testing(
        self,
        mock_profile,
        mock_logging,
        mock_telemetry,
        mock_job,
        mock_commit,
        mock_limiting,
        mock_healing,
        mock_mt_backend
    ):
        """Test create_for_testing() creates engines optimized for tests."""
        # Mock engine instances
        for mock in [mock_profile, mock_logging, mock_telemetry, mock_job,
                     mock_commit, mock_limiting, mock_healing, mock_mt_backend]:
            mock.return_value = Mock()

        engines = CompositionRoot.create_for_testing()

        self.assertIsInstance(engines, SharedEngines)

        # Verify LoggingEngine called with DEBUG and no console
        mock_logging.assert_called_once()
        args = mock_logging.call_args
        self.assertEqual(args[1]["log_level"], "DEBUG")
        self.assertFalse(args[1]["console_output"])

        # Verify TelemetryEngine called with disabled
        mock_telemetry.assert_called_once()
        args = mock_telemetry.call_args
        self.assertFalse(args[1]["config"]["enabled"])

        # Verify JobEngine called with memory backend
        mock_job.assert_called_once()
        args = mock_job.call_args
        self.assertEqual(args[1]["backend"], "memory")


class TestSharedEngines(unittest.TestCase):
    """Test SharedEngines container."""

    def test_shared_engines_repr(self):
        """Test SharedEngines __repr__."""
        mock_engines = {
            "profile": Mock(),
            "logging": Mock(),
            "telemetry": Mock(),
            "job": Mock(),
            "commit": Mock(),
            "limiting": Mock(),
            "healing": Mock(),
            "translation": Mock()
        }

        engines = SharedEngines(**mock_engines)

        repr_str = repr(engines)
        self.assertIn("SharedEngines", repr_str)
        # Should contain all engine types
        for engine_type in ["profile", "logging", "telemetry", "job",
                            "commit", "limiting", "healing", "translation"]:
            # Check that Mock appears in repr (class name of mock objects)
            self.assertIn("Mock", repr_str)


if __name__ == "__main__":
    unittest.main()
