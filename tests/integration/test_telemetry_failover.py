"""
Integration tests for telemetry failover behavior.

Tests the failover mechanism when the HTTP API is unavailable.
Verifies that events are buffered locally and synced when API recovers.

These tests replace the removed direct-DB tests with tests focused on
the new HTTP API + buffer architecture.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# Skip all tests if telemetry module not available
pytest.importorskip("telemetry", reason="telemetry module not installed")

from telemetry.buffer import BufferFile
from telemetry.client import TelemetryClient
from telemetry.config import TelemetryConfig
from telemetry.http_client import APIUnavailableError


class TestTelemetryClientFailover:
    """Tests for TelemetryClient failover when API is unavailable."""

    def test_buffers_event_when_api_unavailable(self):
        """Events are buffered locally when API is unavailable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create config with temporary buffer directory
            config = TelemetryConfig(
                api_url="http://localhost:8765",
                api_enabled=False,
                metrics_dir=tmpdir,
                database_path=f"{tmpdir}/telemetry.sqlite",
                ndjson_dir=f"{tmpdir}/ndjson",
            )
            # Override buffer_dir
            config.buffer_dir = f"{tmpdir}/buffer"

            client = TelemetryClient(config=config)

            # Mock HTTP API to raise APIUnavailableError
            with patch.object(
                client.http_api, "post_event", side_effect=APIUnavailableError("API down")
            ):
                run_id = client.start_run(
                    agent_name="test-agent",
                    job_type="test-job",
                )

                # Verify event was buffered
                buffer_files = list(Path(config.buffer_dir).glob("*.jsonl.active"))
                assert len(buffer_files) >= 1

                # Read buffer file
                with open(buffer_files[0]) as f:
                    lines = f.readlines()

                # Should have at least one event
                assert len(lines) >= 1

                # Parse event
                event = json.loads(lines[0])
                assert event["agent_name"] == "test-agent"
                assert event["job_type"] == "test-job"

    def test_posts_to_api_when_available(self):
        """Events are posted to API when it's available."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TelemetryConfig(
                api_url="http://localhost:8765",
                api_enabled=False,
                metrics_dir=tmpdir,
                database_path=f"{tmpdir}/telemetry.sqlite",
                ndjson_dir=f"{tmpdir}/ndjson",
            )
            config.buffer_dir = f"{tmpdir}/buffer"

            client = TelemetryClient(config=config)

            # Mock successful API response
            mock_response = {"status": "created", "event_id": "test-123", "run_id": "test-run"}
            with patch.object(
                client.http_api, "post_event", return_value=mock_response
            ) as mock_post:
                run_id = client.start_run(
                    agent_name="test-agent",
                    job_type="test-job",
                )

                # Verify API was called
                mock_post.assert_called_once()

                # Verify event was still buffered (backup)
                buffer_files = list(Path(config.buffer_dir).glob("*.jsonl.active"))
                assert len(buffer_files) >= 1

    def test_fallback_to_buffer_on_api_timeout(self):
        """Falls back to buffer when API times out."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TelemetryConfig(
                api_url="http://localhost:8765",
                api_enabled=False,
                metrics_dir=tmpdir,
                database_path=f"{tmpdir}/telemetry.sqlite",
                ndjson_dir=f"{tmpdir}/ndjson",
            )
            config.buffer_dir = f"{tmpdir}/buffer"

            client = TelemetryClient(config=config)

            # Mock timeout error
            with patch.object(
                client.http_api, "post_event", side_effect=APIUnavailableError("Timeout")
            ):
                run_id = client.start_run(
                    agent_name="test-agent",
                    job_type="test-job",
                )

                # Verify event was buffered
                buffer_files = list(Path(config.buffer_dir).glob("*.jsonl.active"))
                assert len(buffer_files) >= 1

                # Read buffer file
                with open(buffer_files[0]) as f:
                    event = json.loads(f.readline())

                assert event["agent_name"] == "test-agent"

    def test_end_run_buffers_when_api_unavailable(self):
        """end_run() buffers event when API is unavailable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TelemetryConfig(
                api_url="http://localhost:8765",
                api_enabled=False,
                metrics_dir=tmpdir,
                database_path=f"{tmpdir}/telemetry.sqlite",
                ndjson_dir=f"{tmpdir}/ndjson",
            )
            config.buffer_dir = f"{tmpdir}/buffer"

            client = TelemetryClient(config=config)

            # Mock API unavailable for both start_run and end_run
            with patch.object(
                client.http_api, "post_event", side_effect=APIUnavailableError("API down")
            ):
                run_id = client.start_run(
                    agent_name="test-agent",
                    job_type="test-job",
                )

                # End the run
                client.end_run(run_id, status="success", items_succeeded=10)

                # Verify both events were buffered
                buffer_files = list(Path(config.buffer_dir).glob("*.jsonl.active"))
                assert len(buffer_files) >= 1

                # Read buffer file
                with open(buffer_files[0]) as f:
                    lines = f.readlines()

                # Should have 2 events (start + end)
                assert len(lines) >= 2

                # Parse end_run event (last line)
                end_event = json.loads(lines[-1])
                assert end_event["status"] == "success"
                assert end_event.get("items_succeeded") == 10

    def test_track_run_context_manager_buffers_on_api_failure(self):
        """track_run() context manager buffers events when API fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TelemetryConfig(
                api_url="http://localhost:8765",
                api_enabled=False,
                metrics_dir=tmpdir,
                database_path=f"{tmpdir}/telemetry.sqlite",
                ndjson_dir=f"{tmpdir}/ndjson",
            )
            config.buffer_dir = f"{tmpdir}/buffer"

            client = TelemetryClient(config=config)

            # Mock API unavailable
            with patch.object(
                client.http_api, "post_event", side_effect=APIUnavailableError("API down")
            ):
                with client.track_run("test-agent", "test-job") as ctx:
                    ctx.set_metrics(items_discovered=5, items_succeeded=3)

                # Verify events were buffered
                buffer_files = list(Path(config.buffer_dir).glob("*.jsonl.active"))
                assert len(buffer_files) >= 1

                # Read buffer file
                with open(buffer_files[0]) as f:
                    lines = f.readlines()

                # Should have 2 events (start + end)
                assert len(lines) >= 2


class TestBufferFileFailoverIntegration:
    """Tests for BufferFile integration with TelemetryClient."""

    def test_buffer_file_created_automatically(self):
        """Buffer directory and file are created automatically."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buffer_dir = Path(tmpdir) / "nonexistent" / "buffer"
            assert not buffer_dir.exists()

            config = TelemetryConfig(
                api_url="http://localhost:8765",
                api_enabled=False,
                metrics_dir=tmpdir,
                database_path=f"{tmpdir}/telemetry.sqlite",
                ndjson_dir=f"{tmpdir}/ndjson",
            )
            config.buffer_dir = str(buffer_dir)

            client = TelemetryClient(config=config)

            # Verify buffer directory was created
            assert buffer_dir.exists()
            assert buffer_dir.is_dir()

    def test_buffer_file_appends_multiple_events(self):
        """Multiple events are appended to same buffer file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TelemetryConfig(
                api_url="http://localhost:8765",
                api_enabled=False,
                metrics_dir=tmpdir,
                database_path=f"{tmpdir}/telemetry.sqlite",
                ndjson_dir=f"{tmpdir}/ndjson",
            )
            config.buffer_dir = f"{tmpdir}/buffer"

            client = TelemetryClient(config=config)

            # Mock API unavailable
            with patch.object(
                client.http_api, "post_event", side_effect=APIUnavailableError("API down")
            ):
                # Create multiple runs
                for i in range(3):
                    run_id = client.start_run(
                        agent_name=f"test-agent-{i}",
                        job_type="test-job",
                    )
                    client.end_run(run_id, status="success")

                # Verify all events in buffer file
                buffer_files = list(Path(config.buffer_dir).glob("*.jsonl.active"))
                assert len(buffer_files) >= 1

                # Read buffer file
                with open(buffer_files[0]) as f:
                    lines = f.readlines()

                # Should have 6 events (3 starts + 3 ends)
                assert len(lines) >= 6

    def test_buffer_file_rotation_on_size_limit(self):
        """Buffer file rotates when size limit is reached."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TelemetryConfig(
                api_url="http://localhost:8765",
                api_enabled=False,
                metrics_dir=tmpdir,
                database_path=f"{tmpdir}/telemetry.sqlite",
                ndjson_dir=f"{tmpdir}/ndjson",
            )
            config.buffer_dir = f"{tmpdir}/buffer"

            # Create buffer with very small max size
            buffer = BufferFile(buffer_dir=config.buffer_dir, max_size_mb=0.001)  # 1KB

            first_file = buffer.current_file

            # Write large event to exceed threshold
            large_event = {"event_id": "test-123", "data": "x" * 2000}  # ~2KB
            buffer.append(large_event)

            # Trigger rotation
            buffer.append({"event_id": "test-124"})

            # Verify rotation occurred
            assert buffer.current_file != first_file

            # Verify old file is .ready
            ready_files = list(Path(config.buffer_dir).glob("*.jsonl.ready"))
            assert len(ready_files) == 1


class TestFailoverRecovery:
    """Tests for recovery when API comes back online."""

    def test_resumes_api_posting_after_recovery(self):
        """Resumes posting to API after it comes back online."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TelemetryConfig(
                api_url="http://localhost:8765",
                api_enabled=False,
                metrics_dir=tmpdir,
                database_path=f"{tmpdir}/telemetry.sqlite",
                ndjson_dir=f"{tmpdir}/ndjson",
            )
            config.buffer_dir = f"{tmpdir}/buffer"

            client = TelemetryClient(config=config)

            # First run: API unavailable
            with patch.object(
                client.http_api, "post_event", side_effect=APIUnavailableError("API down")
            ):
                run_id_1 = client.start_run(
                    agent_name="test-agent",
                    job_type="test-job-1",
                )

            # Second run: API available
            mock_response = {"status": "created", "event_id": "test-456"}
            with patch.object(
                client.http_api, "post_event", return_value=mock_response
            ) as mock_post:
                run_id_2 = client.start_run(
                    agent_name="test-agent",
                    job_type="test-job-2",
                )

                # Verify API was called for second run
                mock_post.assert_called_once()

                # Verify API call had correct data
                call_args = mock_post.call_args[0][0]
                assert call_args["job_type"] == "test-job-2"

    def test_buffer_preserves_events_during_outage(self):
        """Buffer preserves all events during API outage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TelemetryConfig(
                api_url="http://localhost:8765",
                api_enabled=False,
                metrics_dir=tmpdir,
                database_path=f"{tmpdir}/telemetry.sqlite",
                ndjson_dir=f"{tmpdir}/ndjson",
            )
            config.buffer_dir = f"{tmpdir}/buffer"

            client = TelemetryClient(config=config)

            # Simulate extended outage
            with patch.object(
                client.http_api, "post_event", side_effect=APIUnavailableError("API down")
            ):
                # Create 10 runs
                run_ids = []
                for i in range(10):
                    run_id = client.start_run(
                        agent_name="test-agent",
                        job_type=f"test-job-{i}",
                    )
                    run_ids.append(run_id)
                    client.end_run(run_id, status="success", items_succeeded=i)

                # Verify all 20 events (10 starts + 10 ends) are in buffer
                buffer_files = list(Path(config.buffer_dir).glob("*.jsonl.active"))
                assert len(buffer_files) >= 1

                with open(buffer_files[0]) as f:
                    lines = f.readlines()

                assert len(lines) >= 20

                # Verify events are valid JSON
                for line in lines:
                    event = json.loads(line)
                    assert "event_id" in event
                    assert "agent_name" in event


class TestFailoverErrorHandling:
    """Tests for error handling during failover scenarios."""

    def test_never_crashes_agent_on_buffer_failure(self):
        """Client never crashes even if buffer write fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TelemetryConfig(
                api_url="http://localhost:8765",
                api_enabled=False,
                metrics_dir=tmpdir,
                database_path=f"{tmpdir}/telemetry.sqlite",
                ndjson_dir=f"{tmpdir}/ndjson",
            )
            config.buffer_dir = "/invalid/readonly/path"

            # This should not crash
            try:
                client = TelemetryClient(config=config)
                # Mock API unavailable and buffer write fails
                with patch.object(
                    client.buffer, "append", side_effect=OSError("Permission denied")
                ):
                    run_id = client.start_run(
                        agent_name="test-agent",
                        job_type="test-job",
                    )
                    # Should return valid run_id (or error-prefixed ID)
                    assert run_id is not None
            except Exception:
                pytest.fail("TelemetryClient crashed on buffer failure")

    def test_handles_buffer_corruption_gracefully(self):
        """Handles corrupted buffer files gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            buffer_dir = Path(tmpdir) / "buffer"
            buffer_dir.mkdir()

            # Create corrupted buffer file
            corrupted_file = buffer_dir / "telemetry_test.jsonl.active"
            corrupted_file.write_text("{invalid json\n")

            # Create client (should handle corruption)
            buffer = BufferFile(buffer_dir=str(buffer_dir))

            # Should be able to append new events
            buffer.append({"event_id": "test-123", "agent_name": "test"})

            # Verify new event was appended
            with open(buffer.current_file) as f:
                lines = f.readlines()

            # Should have both lines (corrupted + valid)
            assert len(lines) >= 2

    def test_handles_network_intermittent_failures(self):
        """Handles intermittent network failures correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TelemetryConfig(
                api_url="http://localhost:8765",
                api_enabled=False,
                metrics_dir=tmpdir,
                database_path=f"{tmpdir}/telemetry.sqlite",
                ndjson_dir=f"{tmpdir}/ndjson",
            )
            config.buffer_dir = f"{tmpdir}/buffer"

            client = TelemetryClient(config=config)

            # Simulate intermittent failures (fail, succeed, fail, succeed)
            responses = [
                APIUnavailableError("Connection refused"),
                {"status": "created", "event_id": "test-1"},
                APIUnavailableError("Timeout"),
                {"status": "created", "event_id": "test-2"},
            ]

            with patch.object(client.http_api, "post_event", side_effect=responses):
                # All runs should succeed without crashing
                run_id_1 = client.start_run("test-agent", "job-1")  # Fails, buffered
                run_id_2 = client.start_run("test-agent", "job-2")  # Succeeds
                run_id_3 = client.start_run("test-agent", "job-3")  # Fails, buffered
                run_id_4 = client.start_run("test-agent", "job-4")  # Succeeds

                # All should return valid run IDs
                assert run_id_1 is not None
                assert run_id_2 is not None
                assert run_id_3 is not None
                assert run_id_4 is not None


class TestNDJSONBackup:
    """Tests for NDJSON backup writes alongside API/buffer."""

    def test_ndjson_backup_always_written(self):
        """NDJSON backup is written regardless of API status."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ndjson_dir = Path(tmpdir) / "ndjson"

            config = TelemetryConfig(
                api_url="http://localhost:8765",
                api_enabled=False,
                metrics_dir=tmpdir,
                database_path=f"{tmpdir}/telemetry.sqlite",
                ndjson_dir=str(ndjson_dir),
            )
            config.buffer_dir = f"{tmpdir}/buffer"

            client = TelemetryClient(config=config)

            # Mock successful API call
            mock_response = {"status": "created", "event_id": "test-123"}
            with patch.object(client.http_api, "post_event", return_value=mock_response):
                run_id = client.start_run(
                    agent_name="test-agent",
                    job_type="test-job",
                )

                # Verify NDJSON backup was written
                ndjson_files = list(ndjson_dir.glob("*.jsonl"))
                assert len(ndjson_files) >= 1

                # Read NDJSON file
                with open(ndjson_files[0]) as f:
                    lines = f.readlines()

                assert len(lines) >= 1
                event = json.loads(lines[0])
                assert event["agent_name"] == "test-agent"

    def test_ndjson_backup_written_when_api_fails(self):
        """NDJSON backup is written even when API fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ndjson_dir = Path(tmpdir) / "ndjson"

            config = TelemetryConfig(
                api_url="http://localhost:8765",
                api_enabled=False,
                metrics_dir=tmpdir,
                database_path=f"{tmpdir}/telemetry.sqlite",
                ndjson_dir=str(ndjson_dir),
            )
            config.buffer_dir = f"{tmpdir}/buffer"

            client = TelemetryClient(config=config)

            # Mock API failure
            with patch.object(
                client.http_api, "post_event", side_effect=APIUnavailableError("API down")
            ):
                run_id = client.start_run(
                    agent_name="test-agent",
                    job_type="test-job",
                )

                # Verify NDJSON backup was still written
                ndjson_files = list(ndjson_dir.glob("*.jsonl"))
                assert len(ndjson_files) >= 1

                # Read NDJSON file
                with open(ndjson_files[0]) as f:
                    event = json.loads(f.readline())

                assert event["agent_name"] == "test-agent"
