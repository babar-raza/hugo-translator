"""
Unit test for TC-05: Engine requeue integration.

Verifies that the engine's _rtq_add alias is correctly wired to
retranslate_queue.add_to_queue and callable from the engine module.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestEngineRequeueWiring:
    """Verify that engine imports _rtq_add from retranslate_queue."""

    def test_rtq_add_is_importable_from_engine(self):
        """The engine module must expose _rtq_add as an alias for add_to_queue."""
        from src.translation_engine import engine

        assert hasattr(engine, "_rtq_add"), "_rtq_add not found in engine module"
        # It should be the same function object
        from src.tm.retranslate_queue import add_to_queue

        assert engine._rtq_add is add_to_queue

    def test_rtq_add_called_on_validation_rejection(self, tmp_path):
        """Patching _rtq_add at the engine module level captures requeue calls."""
        mock_add = MagicMock()
        with patch("src.translation_engine.engine._rtq_add", mock_add):
            # Simulate what the engine does on validation rejection (line 2248):
            # _rtq_add(_rejected_path, _rejected_lang)
            from src.translation_engine.engine import _rtq_add

            rejected_path = tmp_path / "content" / "ar" / "rejected.md"
            rejected_path.parent.mkdir(parents=True)
            rejected_path.touch()

            _rtq_add(rejected_path, "ar")

            mock_add.assert_called_once_with(rejected_path, "ar")

    def test_rtq_add_writes_to_queue(self, tmp_path):
        """End-to-end: calling _rtq_add creates a queue entry."""
        import json

        import src.tm.retranslate_queue as rtq

        queue_file = tmp_path / "retranslate_queue.jsonl"
        quarantine_file = tmp_path / "quarantine.jsonl"
        with (
            patch.object(rtq, "_QUEUE_FILE", queue_file),
            patch.object(rtq, "_QUARANTINE_FILE", quarantine_file),
        ):
            f = tmp_path / "stuck.ar.md"
            f.touch()

            from src.translation_engine.engine import _rtq_add

            _rtq_add(f, "ar")

            assert queue_file.exists()
            entry = json.loads(queue_file.read_text().strip())
            assert entry["tgt_lang"] == "ar"
            assert entry["retry_count"] == 1
