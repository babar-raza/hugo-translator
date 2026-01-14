"""
Unit tests for TelemetryEngine.

Tests telemetry wrapper with mocked TranslationTelemetry.
"""

import unittest
from unittest.mock import Mock, patch
from pathlib import Path
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from src.shared_engines.telemetry_engine import TelemetryEngine


class TestTelemetryEngine(unittest.TestCase):
    """Test TelemetryEngine wrapper."""

    @patch('src.shared_engines.telemetry_engine.get_telemetry')
    def test_initialization(self, mock_get_telemetry):
        """Test TelemetryEngine initializes correctly."""
        mock_telemetry = Mock()
        mock_get_telemetry.return_value = mock_telemetry

        engine = TelemetryEngine(agent_name="test-agent", enabled=True)

        self.assertEqual(engine.agent_name, "test-agent")
        self.assertTrue(engine.enabled)
        mock_get_telemetry.assert_called_once_with(agent_name="test-agent")

    @patch('src.shared_engines.telemetry_engine.configure_telemetry')
    def test_initialization_with_config(self, mock_configure):
        """Test TelemetryEngine initializes with custom config."""
        mock_telemetry = Mock()
        mock_configure.return_value = mock_telemetry
        mock_config = Mock()

        engine = TelemetryEngine(
            agent_name="test-agent",
            enabled=True,
            config=mock_config
        )

        mock_configure.assert_called_once_with(
            agent_name="test-agent",
            enabled=True,
            config=mock_config
        )

    @patch('src.shared_engines.telemetry_engine.get_telemetry')
    def test_track_translation_session(self, mock_get_telemetry):
        """Test track_translation_session() delegates to TranslationTelemetry."""
        mock_context = Mock()
        mock_telemetry = Mock()
        mock_telemetry.track_translation_session.return_value = mock_context
        mock_get_telemetry.return_value = mock_telemetry

        engine = TelemetryEngine()

        # Track session
        result = engine.track_translation_session(
            job_type="translate_file",
            file_path=Path("example.md"),
            target_langs=["es", "fr"],
            site_id="products.aspose.com"
        )

        self.assertEqual(result, mock_context)
        mock_telemetry.track_translation_session.assert_called_once_with(
            job_type="translate_file",
            trigger_type="cli",
            file_path=Path("example.md"),
            target_langs=["es", "fr"],
            errors=None,
            site_id="products.aspose.com"
        )

    @patch('src.shared_engines.telemetry_engine.get_telemetry')
    def test_emit_event(self, mock_get_telemetry):
        """Test emit() logs event (no-op currently)."""
        mock_telemetry = Mock()
        mock_get_telemetry.return_value = mock_telemetry

        engine = TelemetryEngine(enabled=True)

        # Emit event (currently just logs)
        engine.emit("model_loaded", {"model_id": "m2m100_418m"})

        # No assertion needed - just verify it doesn't crash

    @patch('src.shared_engines.telemetry_engine.get_telemetry')
    def test_is_enabled(self, mock_get_telemetry):
        """Test is_enabled() returns correct status."""
        mock_telemetry = Mock()
        mock_telemetry.enabled = True
        mock_get_telemetry.return_value = mock_telemetry

        engine = TelemetryEngine(enabled=True)
        self.assertTrue(engine.is_enabled())

        # Test with disabled telemetry
        mock_telemetry.enabled = False
        self.assertFalse(engine.is_enabled())

    @patch('src.shared_engines.telemetry_engine.get_telemetry')
    def test_get_telemetry_client(self, mock_get_telemetry):
        """Test get_telemetry_client() returns underlying client."""
        mock_telemetry = Mock()
        mock_get_telemetry.return_value = mock_telemetry

        engine = TelemetryEngine(enabled=True)
        client = engine.get_telemetry_client()

        self.assertEqual(client, mock_telemetry)

    @patch('src.shared_engines.telemetry_engine.get_telemetry')
    def test_shutdown(self, mock_get_telemetry):
        """Test shutdown() cleanup."""
        mock_telemetry = Mock()
        mock_telemetry.client = Mock()
        mock_get_telemetry.return_value = mock_telemetry

        engine = TelemetryEngine(enabled=True)
        engine.shutdown()

        # Should not crash (currently no cleanup needed)


if __name__ == "__main__":
    unittest.main()
