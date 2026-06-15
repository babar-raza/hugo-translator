"""Tests for TC-AGT-09: Reviewer App MCP Bridge."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add scripts to path for import
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.ops.reviewer_bridge import (
    MCPClient,
    ReviewerBridgeError,
    _is_posted,
    _map_signal_to_directive,
    _mark_posted,
    load_signal,
    post_signal,
    process_signals,
)


SAMPLE_SIGNAL = {
    "run_id": "test-run-001",
    "timestamp": "2026-06-13T12:00:00Z",
    "mission": "Content Translation",
    "site_id": "docs.aspose.net.words",
    "status": "completed",
    "files": {"processed": 10, "accepted": 8, "rejected": 1, "retried": 1},
    "validators": {"run": 100, "passed": 95, "failed": 5},
    "llm_usage": {"calls": 2, "tokens": 1500},
    "verdict": "CLEAN_RUN",
    "autonomy_score": 0.85,
    "blockers": [],
    "evidence_path": ".local/evidences/test/",
}


@pytest.fixture()
def signals_dir(tmp_path):
    """Create a signals directory with a sample signal."""
    sdir = tmp_path / "signals"
    sdir.mkdir()
    signal_file = sdir / "run-signal-test-run-001.json"
    signal_file.write_text(json.dumps(SAMPLE_SIGNAL), encoding="utf-8")
    return sdir


@pytest.fixture()
def posted_dir(signals_dir):
    """Create the posted markers directory."""
    pdir = signals_dir / ".posted"
    pdir.mkdir()
    return pdir


class TestMapSignalToDirective:
    def test_maps_all_fields(self):
        directive = _map_signal_to_directive(SAMPLE_SIGNAL)
        assert directive["run_id"] == "test-run-001"
        assert directive["source"] == "hugo-translator"
        assert directive["mission"] == "Content Translation"
        assert directive["site_id"] == "docs.aspose.net.words"
        assert directive["status"] == "completed"
        assert directive["verdict"] == "CLEAN_RUN"
        assert directive["autonomy_score"] == 0.85

    def test_maps_metrics(self):
        directive = _map_signal_to_directive(SAMPLE_SIGNAL)
        metrics = directive["metrics"]
        assert metrics["files_processed"] == 10
        assert metrics["files_accepted"] == 8
        assert metrics["files_rejected"] == 1
        assert metrics["validators_run"] == 100
        assert metrics["llm_calls"] == 2
        assert metrics["llm_tokens"] == 1500

    def test_handles_missing_fields(self):
        minimal = {"run_id": "x", "status": "completed", "verdict": "CLEAN_RUN"}
        directive = _map_signal_to_directive(minimal)
        assert directive["run_id"] == "x"
        assert directive["metrics"]["files_processed"] == 0


class TestLoadSignal:
    def test_load_valid(self, signals_dir):
        signal_file = signals_dir / "run-signal-test-run-001.json"
        signal = load_signal(signal_file)
        assert signal["run_id"] == "test-run-001"

    def test_load_missing_file(self, tmp_path):
        with pytest.raises(ReviewerBridgeError, match="not found"):
            load_signal(tmp_path / "nonexistent.json")

    def test_load_invalid_json(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("NOT JSON", encoding="utf-8")
        with pytest.raises(ReviewerBridgeError, match="Invalid JSON"):
            load_signal(bad_file)

    def test_load_missing_fields(self, tmp_path):
        incomplete = tmp_path / "incomplete.json"
        incomplete.write_text('{"run_id": "x"}', encoding="utf-8")
        with pytest.raises(ReviewerBridgeError, match="missing required"):
            load_signal(incomplete)


class TestPostedMarkers:
    def test_not_posted_initially(self, signals_dir):
        signal_file = signals_dir / "run-signal-test.json"
        signal_file.write_text("{}", encoding="utf-8")
        assert _is_posted(signal_file) is False

    def test_mark_and_check(self, signals_dir):
        signal_file = signals_dir / "run-signal-test.json"
        signal_file.write_text("{}", encoding="utf-8")
        # Use monkeypatch to set the posted dir
        import scripts.ops.reviewer_bridge as bridge

        old_dir = bridge._POSTED_MARKERS_DIR
        bridge._POSTED_MARKERS_DIR = signals_dir / ".posted"
        try:
            _mark_posted(signal_file)
            assert _is_posted(signal_file) is True
        finally:
            bridge._POSTED_MARKERS_DIR = old_dir


class TestPostSignal:
    def test_dry_run(self):
        result = post_signal(SAMPLE_SIGNAL, dry_run=True)
        assert result["posted"] is False
        assert result["dry_run"] is True
        assert result["directive"]["run_id"] == "test-run-001"

    def test_no_client(self):
        result = post_signal(SAMPLE_SIGNAL, client=None, dry_run=False)
        assert result["posted"] is False
        assert "No MCP client" in result["error"]

    def test_successful_post(self):
        mock_client = MagicMock(spec=MCPClient)
        mock_client.call_tool.return_value = {"status": "accepted"}
        result = post_signal(SAMPLE_SIGNAL, client=mock_client, dry_run=False)
        assert result["posted"] is True
        assert result["response"]["status"] == "accepted"
        mock_client.call_tool.assert_called_once_with(
            "review_agent.start_run",
            {"runId": "test-run-001", "directive": _map_signal_to_directive(SAMPLE_SIGNAL)},
        )

    def test_failed_post(self):
        mock_client = MagicMock(spec=MCPClient)
        mock_client.call_tool.side_effect = ReviewerBridgeError("Connection refused")
        result = post_signal(SAMPLE_SIGNAL, client=mock_client, dry_run=False)
        assert result["posted"] is False
        assert "Connection refused" in result["error"]


class TestProcessSignals:
    def test_dry_run_no_env(self, signals_dir):
        """Without env vars, falls back to dry-run."""
        results = process_signals(signals_dir=signals_dir)
        assert len(results) == 1
        assert results[0]["dry_run"] is True

    def test_process_latest_only(self, signals_dir):
        # Add a second signal
        (signals_dir / "run-signal-test-run-002.json").write_text(
            json.dumps({**SAMPLE_SIGNAL, "run_id": "test-run-002"}),
            encoding="utf-8",
        )
        results = process_signals(signals_dir=signals_dir, dry_run=True)
        assert len(results) == 1
        assert "002" in results[0]["signal_file"]

    def test_process_all(self, signals_dir):
        (signals_dir / "run-signal-test-run-002.json").write_text(
            json.dumps({**SAMPLE_SIGNAL, "run_id": "test-run-002"}),
            encoding="utf-8",
        )
        results = process_signals(
            signals_dir=signals_dir,
            all_signals=True,
            dry_run=True,
        )
        assert len(results) == 2

    def test_process_specific_signal(self, signals_dir):
        signal_file = signals_dir / "run-signal-test-run-001.json"
        results = process_signals(signal_path=signal_file, dry_run=True)
        assert len(results) == 1

    def test_empty_signals_dir(self, tmp_path):
        results = process_signals(signals_dir=tmp_path / "nonexistent")
        assert results == []


class TestMCPClient:
    def test_rpc_id_increments(self):
        client = MCPClient("http://test", "token")
        assert client._next_id() == 1
        assert client._next_id() == 2

    @patch("scripts.ops.reviewer_bridge.MCPClient.rpc")
    def test_initialize(self, mock_rpc):
        mock_rpc.return_value = {}
        client = MCPClient("http://test", "token")
        client.initialize()
        mock_rpc.assert_called_once()
        assert client._initialized is True
        # Second call should be no-op
        client.initialize()
        assert mock_rpc.call_count == 1

    @patch("scripts.ops.reviewer_bridge.MCPClient.rpc")
    @patch("scripts.ops.reviewer_bridge.MCPClient.initialize")
    def test_call_tool(self, mock_init, mock_rpc):
        mock_rpc.return_value = {"status": "ok"}
        client = MCPClient("http://test", "token")
        result = client.call_tool("review_agent.start_run", {"runId": "r1", "directive": {}})
        mock_init.assert_called_once()
        mock_rpc.assert_called_once_with(
            "tools/call",
            {"name": "review_agent.start_run", "arguments": {"runId": "r1", "directive": {}}},
        )
