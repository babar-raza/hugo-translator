"""
Unit tests for telemetry cleanup module.

Tests the API-based cleanup functionality for stale telemetry runs.
All tests use mocked HTTP requests - no actual network calls or database access.
"""

from unittest.mock import Mock, patch

import pytest
import requests

from src.observability.telemetry_cleanup import cleanup_stale_runs


class TestCleanupStaleRuns:
    """Test suite for cleanup_stale_runs() function."""

    @pytest.fixture
    def mock_response_success(self):
        """Mock successful API response with stale runs."""
        response = Mock()
        response.status_code = 200
        response.json.return_value = [
            {
                "event_id": "evt-123",
                "run_id": "run-123",
                "job_type": "translate_file",
                "created_at": "2025-12-23T10:00:00+00:00",
                "status": "running",
            },
            {
                "event_id": "evt-456",
                "run_id": "run-456",
                "job_type": "translate_directory",
                "created_at": "2025-12-23T11:00:00+00:00",
                "status": "running",
            },
        ]
        return response

    @pytest.fixture
    def mock_response_empty(self):
        """Mock API response with no stale runs."""
        response = Mock()
        response.status_code = 200
        response.json.return_value = []
        return response

    @pytest.fixture
    def mock_response_404(self):
        """Mock 404 response (endpoints not available)."""
        response = Mock()
        response.status_code = 404
        return response

    @pytest.fixture
    def mock_patch_success(self):
        """Mock successful PATCH response."""
        response = Mock()
        response.status_code = 200
        return response

    def test_cleanup_successful(self, mock_response_success, mock_patch_success):
        """Test successful cleanup of stale runs."""
        with patch("src.observability.telemetry_cleanup.requests.get") as mock_get:
            with patch("src.observability.telemetry_cleanup.requests.patch") as mock_patch:
                mock_get.return_value = mock_response_success
                mock_patch.return_value = mock_patch_success

                stats = cleanup_stale_runs(
                    api_url="http://localhost:8765",
                    max_age_hours=1,
                    dry_run=False,
                )

                # Verify stats
                assert stats["stale_runs_found"] == 2
                assert stats["updated"] == 2
                assert stats["errors"] == []
                assert stats["api_available"] is True

                # Verify GET request made
                mock_get.assert_called_once()
                call_args = mock_get.call_args
                assert call_args[0][0] == "http://localhost:8765/api/v1/runs"
                assert call_args[1]["params"]["agent_name"] == "hugo-translator"
                assert call_args[1]["params"]["status"] == "running"

                # Verify PATCH requests made for each run
                assert mock_patch.call_count == 2
                first_call = mock_patch.call_args_list[0]
                assert "evt-123" in first_call[0][0]
                assert first_call[1]["json"]["status"] == "cancelled"
                assert "end_time" in first_call[1]["json"]

    def test_cleanup_no_stale_runs(self, mock_response_empty):
        """Test cleanup when no stale runs found."""
        with patch("src.observability.telemetry_cleanup.requests.get") as mock_get:
            mock_get.return_value = mock_response_empty

            stats = cleanup_stale_runs(api_url="http://localhost:8765")

            assert stats["stale_runs_found"] == 0
            assert stats["updated"] == 0
            assert stats["errors"] == []
            assert stats["api_available"] is True

    def test_cleanup_api_404(self, mock_response_404):
        """Test graceful handling when API endpoints not available."""
        with patch("src.observability.telemetry_cleanup.requests.get") as mock_get:
            mock_get.return_value = mock_response_404

            stats = cleanup_stale_runs(api_url="http://localhost:8765")

            # Should return early with empty stats
            assert stats["stale_runs_found"] == 0
            assert stats["updated"] == 0
            assert stats["api_available"] is False
            # No errors - 404 is expected until API upgraded
            assert stats["errors"] == []

    def test_cleanup_connection_error(self):
        """Test graceful handling when API not reachable."""
        with patch("src.observability.telemetry_cleanup.requests.get") as mock_get:
            mock_get.side_effect = requests.ConnectionError("Connection refused")

            stats = cleanup_stale_runs(api_url="http://localhost:8765")

            assert stats["stale_runs_found"] == 0
            assert stats["updated"] == 0
            assert stats["api_available"] is False
            assert len(stats["errors"]) == 1
            assert "not reachable" in stats["errors"][0]

    def test_cleanup_timeout(self):
        """Test graceful handling when API request times out."""
        with patch("src.observability.telemetry_cleanup.requests.get") as mock_get:
            mock_get.side_effect = requests.Timeout("Request timeout")

            stats = cleanup_stale_runs(api_url="http://localhost:8765", timeout=5)

            assert stats["stale_runs_found"] == 0
            assert stats["updated"] == 0
            assert stats["api_available"] is False
            assert len(stats["errors"]) == 1
            assert "timeout" in stats["errors"][0].lower()

    def test_cleanup_invalid_response_format(self):
        """Test handling of invalid API response format."""
        with patch("src.observability.telemetry_cleanup.requests.get") as mock_get:
            response = Mock()
            response.status_code = 200
            response.json.return_value = {"invalid": "format"}  # Not a list
            mock_get.return_value = response

            stats = cleanup_stale_runs(api_url="http://localhost:8765")

            assert stats["stale_runs_found"] == 0
            assert stats["updated"] == 0
            assert len(stats["errors"]) == 1
            assert "Invalid API response" in stats["errors"][0]

    def test_cleanup_patch_failure(self, mock_response_success):
        """Test handling when PATCH request fails for some runs."""
        with patch("src.observability.telemetry_cleanup.requests.get") as mock_get:
            with patch("src.observability.telemetry_cleanup.requests.patch") as mock_patch:
                mock_get.return_value = mock_response_success
                # First PATCH succeeds, second fails
                mock_patch.side_effect = [
                    Mock(status_code=200),
                    requests.RequestException("Network error"),
                ]

                stats = cleanup_stale_runs(api_url="http://localhost:8765")

                # Should have partial success
                assert stats["stale_runs_found"] == 2
                assert stats["updated"] == 1  # Only first succeeded
                assert len(stats["errors"]) == 1
                assert "Failed to update run" in stats["errors"][0]

    def test_cleanup_dry_run(self, mock_response_success):
        """Test dry run mode (no actual updates)."""
        with patch("src.observability.telemetry_cleanup.requests.get") as mock_get:
            with patch("src.observability.telemetry_cleanup.requests.patch") as mock_patch:
                mock_get.return_value = mock_response_success

                stats = cleanup_stale_runs(
                    api_url="http://localhost:8765",
                    dry_run=True,
                )

                # Should find stale runs but not update
                assert stats["stale_runs_found"] == 2
                assert stats["updated"] == 0
                assert stats["errors"] == []

                # Verify no PATCH requests made
                mock_patch.assert_not_called()

    def test_cleanup_missing_event_id(self):
        """Test handling of runs missing event_id."""
        with patch("src.observability.telemetry_cleanup.requests.get") as mock_get:
            with patch("src.observability.telemetry_cleanup.requests.patch") as mock_patch:
                response = Mock()
                response.status_code = 200
                response.json.return_value = [
                    {
                        "run_id": "run-123",
                        "job_type": "translate_file",
                        # Missing event_id
                    }
                ]
                mock_get.return_value = response

                stats = cleanup_stale_runs(api_url="http://localhost:8765")

                assert stats["stale_runs_found"] == 1
                assert stats["updated"] == 0
                assert len(stats["errors"]) == 1
                assert "Missing event_id" in stats["errors"][0]
                mock_patch.assert_not_called()

    def test_cleanup_custom_parameters(self, mock_response_success, mock_patch_success):
        """Test cleanup with custom parameters."""
        with patch("src.observability.telemetry_cleanup.requests.get") as mock_get:
            with patch("src.observability.telemetry_cleanup.requests.patch") as mock_patch:
                mock_get.return_value = mock_response_success
                mock_patch.return_value = mock_patch_success

                stats = cleanup_stale_runs(
                    api_url="http://custom:9000",
                    max_age_hours=2,
                    agent_name="custom-agent",
                    timeout=10,
                )

                # Verify custom parameters used
                call_args = mock_get.call_args
                assert call_args[0][0] == "http://custom:9000/api/v1/runs"
                assert call_args[1]["params"]["agent_name"] == "custom-agent"
                assert call_args[1]["timeout"] == 10

    def test_cleanup_exception_handling(self):
        """Test handling of unexpected exceptions."""
        with patch("src.observability.telemetry_cleanup.requests.get") as mock_get:
            mock_get.side_effect = Exception("Unexpected error")

            stats = cleanup_stale_runs(api_url="http://localhost:8765")

            assert stats["stale_runs_found"] == 0
            assert stats["updated"] == 0
            assert len(stats["errors"]) == 1
            assert "cleanup failed" in stats["errors"][0].lower()

    def test_cleanup_http_error_response(self):
        """Test handling of HTTP error responses (500, etc.)."""
        with patch("src.observability.telemetry_cleanup.requests.get") as mock_get:
            response = Mock()
            response.status_code = 500
            response.raise_for_status.side_effect = requests.HTTPError("Server error")
            mock_get.return_value = response

            stats = cleanup_stale_runs(api_url="http://localhost:8765")

            assert stats["stale_runs_found"] == 0
            assert stats["updated"] == 0
            assert len(stats["errors"]) == 1
            assert "query failed" in stats["errors"][0].lower()
