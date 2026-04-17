"""
Integration tests for telemetry HTTP API client.

Tests HTTP API client behavior without making real network calls.
Verifies POST, retry logic, error handling, and idempotency.

These tests replace the removed direct-DB tests with tests focused on
the new HTTP API architecture.
"""
import json
from unittest.mock import Mock, patch

import pytest
import requests

# Skip all tests if telemetry module not available
pytest.importorskip("telemetry", reason="telemetry module not installed")

from telemetry.http_client import (
    APIError,
    APIUnavailableError,
    APIValidationError,
    HTTPAPIClient,
)


class TestHTTPAPIClientInitialization:
    """Tests for HTTPAPIClient initialization."""

    def test_initializes_with_default_settings(self):
        """Client initializes with default timeout and retry settings."""
        client = HTTPAPIClient(api_url="http://localhost:8765")

        assert client.api_url == "http://localhost:8765"
        assert client.timeout == 10
        assert client.max_retries == 3
        assert client.retry_delay == 1.0

    def test_initializes_with_custom_settings(self):
        """Client can be initialized with custom settings."""
        client = HTTPAPIClient(
            api_url="http://example.com:9999",
            timeout=30,
            max_retries=5,
            retry_delay=2.0,
        )

        assert client.api_url == "http://example.com:9999"
        assert client.timeout == 30
        assert client.max_retries == 5
        assert client.retry_delay == 2.0

    def test_strips_trailing_slash_from_url(self):
        """Trailing slash is removed from API URL."""
        client = HTTPAPIClient(api_url="http://localhost:8765/")

        assert client.api_url == "http://localhost:8765"

    def test_sets_json_content_type_header(self):
        """Session has JSON content type header set."""
        client = HTTPAPIClient(api_url="http://localhost:8765")

        assert client.session.headers["Content-Type"] == "application/json"


class TestHTTPAPIClientPostEvent:
    """Tests for posting single events to API."""

    @patch('requests.Session.post')
    def test_successful_post_returns_created_status(self, mock_post):
        """Successful POST returns 'created' status."""
        mock_response = Mock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "status": "created",
            "event_id": "test-123",
            "run_id": "20251220T120000Z-agent-abc",
        }
        mock_post.return_value = mock_response

        client = HTTPAPIClient(api_url="http://localhost:8765")
        event = {"event_id": "test-123", "run_id": "20251220T120000Z-agent-abc"}

        result = client.post_event(event)

        assert result["status"] == "created"
        assert result["event_id"] == "test-123"
        mock_post.assert_called_once()

    @patch('requests.Session.post')
    def test_duplicate_event_returns_duplicate_status(self, mock_post):
        """Duplicate event returns 'duplicate' status (idempotent)."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "duplicate",
            "event_id": "test-123",
            "run_id": "20251220T120000Z-agent-abc",
        }
        mock_post.return_value = mock_response

        client = HTTPAPIClient(api_url="http://localhost:8765")
        event = {"event_id": "test-123", "run_id": "20251220T120000Z-agent-abc"}

        result = client.post_event(event)

        assert result["status"] == "duplicate"
        assert result["event_id"] == "test-123"

    @patch('requests.Session.post')
    def test_posts_to_correct_endpoint(self, mock_post):
        """POST is sent to /api/v1/runs endpoint."""
        mock_response = Mock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "status": "created",
            "event_id": "test-123",
        }
        mock_post.return_value = mock_response

        client = HTTPAPIClient(api_url="http://localhost:8765")
        event = {"event_id": "test-123"}

        client.post_event(event)

        # Verify endpoint
        call_args = mock_post.call_args
        assert call_args[1]['json'] == event
        assert "http://localhost:8765/api/v1/runs" in str(call_args)

    @patch('requests.Session.post')
    def test_validation_error_raises_api_validation_error(self, mock_post):
        """400 Bad Request raises APIValidationError."""
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.text = "Missing required field: event_id"
        mock_post.return_value = mock_response

        client = HTTPAPIClient(api_url="http://localhost:8765")
        event = {"run_id": "no-event-id"}

        with pytest.raises(APIValidationError, match="Invalid event"):
            client.post_event(event)

    @patch('requests.Session.post')
    def test_server_error_raises_api_error(self, mock_post):
        """500 Internal Server Error raises APIError."""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal server error"
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError()
        mock_post.return_value = mock_response

        client = HTTPAPIClient(api_url="http://localhost:8765")
        event = {"event_id": "test-123"}

        with pytest.raises(APIError, match="API error"):
            client.post_event(event)


class TestHTTPAPIClientRetryLogic:
    """Tests for retry logic on transient errors."""

    @patch('requests.Session.post')
    @patch('time.sleep')  # Mock sleep to speed up tests
    def test_retries_on_connection_error(self, mock_sleep, mock_post):
        """Retries POST on connection error."""
        # First two attempts fail, third succeeds
        mock_post.side_effect = [
            requests.exceptions.ConnectionError("Connection refused"),
            requests.exceptions.ConnectionError("Connection refused"),
            Mock(status_code=201, json=lambda: {"status": "created", "event_id": "test-123"}),
        ]

        client = HTTPAPIClient(api_url="http://localhost:8765", retry_delay=0.1)
        event = {"event_id": "test-123"}

        result = client.post_event(event)

        assert result["status"] == "created"
        assert mock_post.call_count == 3
        assert mock_sleep.call_count == 2

    @patch('requests.Session.post')
    @patch('time.sleep')
    def test_retries_on_timeout(self, mock_sleep, mock_post):
        """Retries POST on timeout."""
        # First attempt times out, second succeeds
        mock_post.side_effect = [
            requests.exceptions.Timeout("Request timed out"),
            Mock(status_code=201, json=lambda: {"status": "created", "event_id": "test-123"}),
        ]

        client = HTTPAPIClient(api_url="http://localhost:8765", retry_delay=0.1)
        event = {"event_id": "test-123"}

        result = client.post_event(event)

        assert result["status"] == "created"
        assert mock_post.call_count == 2
        assert mock_sleep.call_count == 1

    @patch('requests.Session.post')
    @patch('time.sleep')
    def test_raises_api_unavailable_after_max_retries(self, mock_sleep, mock_post):
        """Raises APIUnavailableError after max retries exceeded."""
        mock_post.side_effect = requests.exceptions.ConnectionError("Connection refused")

        client = HTTPAPIClient(api_url="http://localhost:8765", max_retries=3, retry_delay=0.1)
        event = {"event_id": "test-123"}

        with pytest.raises(APIUnavailableError, match="Cannot reach telemetry API"):
            client.post_event(event)

        assert mock_post.call_count == 3  # max_retries

    @patch('requests.Session.post')
    @patch('time.sleep')
    def test_respects_custom_retry_delay(self, mock_sleep, mock_post):
        """Uses custom retry delay between attempts."""
        mock_post.side_effect = [
            requests.exceptions.ConnectionError("Connection refused"),
            Mock(status_code=201, json=lambda: {"status": "created"}),
        ]

        client = HTTPAPIClient(api_url="http://localhost:8765", retry_delay=5.0)
        event = {"event_id": "test-123"}

        client.post_event(event)

        mock_sleep.assert_called_with(5.0)


class TestHTTPAPIClientBatchPost:
    """Tests for posting batches of events."""

    @patch('requests.Session.post')
    def test_successful_batch_post(self, mock_post):
        """Batch POST successfully inserts multiple events."""
        mock_response = Mock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "inserted": 5,
            "duplicates": 0,
            "errors": [],
            "total": 5,
        }
        mock_post.return_value = mock_response

        client = HTTPAPIClient(api_url="http://localhost:8765")
        events = [{"event_id": f"test-{i}"} for i in range(5)]

        result = client.post_batch(events)

        assert result["inserted"] == 5
        assert result["duplicates"] == 0
        assert result["total"] == 5

    @patch('requests.Session.post')
    def test_batch_with_duplicates(self, mock_post):
        """Batch POST reports duplicates correctly."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "inserted": 3,
            "duplicates": 2,
            "errors": [],
            "total": 5,
        }
        mock_post.return_value = mock_response

        client = HTTPAPIClient(api_url="http://localhost:8765")
        events = [{"event_id": f"test-{i}"} for i in range(5)]

        result = client.post_batch(events)

        assert result["inserted"] == 3
        assert result["duplicates"] == 2

    @patch('requests.Session.post')
    def test_batch_with_errors(self, mock_post):
        """Batch POST reports individual event errors."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "inserted": 3,
            "duplicates": 0,
            "errors": [
                "Event test-1: Missing required field 'run_id'",
                "Event test-3: Invalid timestamp format",
            ],
            "total": 5,
        }
        mock_post.return_value = mock_response

        client = HTTPAPIClient(api_url="http://localhost:8765")
        events = [{"event_id": f"test-{i}"} for i in range(5)]

        result = client.post_batch(events)

        assert result["inserted"] == 3
        assert len(result["errors"]) == 2

    @patch('requests.Session.post')
    def test_empty_batch_returns_zeros(self, mock_post):
        """Empty batch returns zero counts without API call."""
        client = HTTPAPIClient(api_url="http://localhost:8765")

        result = client.post_batch([])

        assert result["inserted"] == 0
        assert result["duplicates"] == 0
        assert result["total"] == 0
        mock_post.assert_not_called()

    @patch('requests.Session.post')
    def test_batch_posts_to_correct_endpoint(self, mock_post):
        """Batch POST is sent to /api/v1/runs/batch endpoint."""
        mock_response = Mock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "inserted": 1,
            "duplicates": 0,
            "errors": [],
            "total": 1,
        }
        mock_post.return_value = mock_response

        client = HTTPAPIClient(api_url="http://localhost:8765")
        events = [{"event_id": "test-1"}]

        client.post_batch(events)

        # Verify endpoint
        call_args = mock_post.call_args
        assert call_args[1]['json'] == events
        assert "http://localhost:8765/api/v1/runs/batch" in str(call_args)

    @patch('requests.Session.post')
    def test_batch_uses_longer_timeout(self, mock_post):
        """Batch POST uses 2x timeout for larger payload."""
        mock_response = Mock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "inserted": 1,
            "duplicates": 0,
            "errors": [],
            "total": 1,
        }
        mock_post.return_value = mock_response

        client = HTTPAPIClient(api_url="http://localhost:8765", timeout=10)
        events = [{"event_id": "test-1"}]

        client.post_batch(events)

        # Verify timeout is 2x base timeout
        call_args = mock_post.call_args
        assert call_args[1]['timeout'] == 20  # 2x base timeout


class TestHTTPAPIClientHealthCheck:
    """Tests for health check endpoint."""

    @patch('requests.Session.get')
    def test_health_check_returns_true_when_healthy(self, mock_get):
        """Health check returns True when API is healthy."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "ok", "version": "2.0.0"}
        mock_get.return_value = mock_response

        client = HTTPAPIClient(api_url="http://localhost:8765")

        is_healthy = client.check_health()

        assert is_healthy is True
        mock_get.assert_called_once()

    @patch('requests.Session.get')
    def test_health_check_returns_false_when_unhealthy(self, mock_get):
        """Health check returns False when API returns unhealthy status."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "degraded"}
        mock_get.return_value = mock_response

        client = HTTPAPIClient(api_url="http://localhost:8765")

        is_healthy = client.check_health()

        assert is_healthy is False

    @patch('requests.Session.get')
    def test_health_check_returns_false_on_connection_error(self, mock_get):
        """Health check returns False when API is unreachable."""
        mock_get.side_effect = requests.exceptions.ConnectionError("Connection refused")

        client = HTTPAPIClient(api_url="http://localhost:8765")

        is_healthy = client.check_health()

        assert is_healthy is False

    @patch('requests.Session.get')
    def test_health_check_uses_correct_endpoint(self, mock_get):
        """Health check uses /health endpoint."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "ok"}
        mock_get.return_value = mock_response

        client = HTTPAPIClient(api_url="http://localhost:8765")
        client.check_health()

        # Verify endpoint
        call_args = mock_get.call_args
        assert "http://localhost:8765/health" in str(call_args)


class TestHTTPAPIClientMetrics:
    """Tests for metrics endpoint."""

    @patch('requests.Session.get')
    def test_get_metrics_returns_metrics_dict(self, mock_get):
        """get_metrics returns metrics dictionary."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "total_runs": 1234,
            "agents": {
                "hugo-translator": {"runs": 100, "last_run": "2025-12-20T10:00:00Z"}
            },
            "recent_24h": 50,
        }
        mock_get.return_value = mock_response

        client = HTTPAPIClient(api_url="http://localhost:8765")

        metrics = client.get_metrics()

        assert metrics["total_runs"] == 1234
        assert "hugo-translator" in metrics["agents"]
        assert metrics["recent_24h"] == 50

    @patch('requests.Session.get')
    def test_get_metrics_returns_none_on_error(self, mock_get):
        """get_metrics returns None when API is unavailable."""
        mock_get.side_effect = requests.exceptions.ConnectionError("Connection refused")

        client = HTTPAPIClient(api_url="http://localhost:8765")

        metrics = client.get_metrics()

        assert metrics is None

    @patch('requests.Session.get')
    def test_get_metrics_uses_correct_endpoint(self, mock_get):
        """get_metrics uses /metrics endpoint."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"total_runs": 0}
        mock_get.return_value = mock_response

        client = HTTPAPIClient(api_url="http://localhost:8765")
        client.get_metrics()

        # Verify endpoint
        call_args = mock_get.call_args
        assert "http://localhost:8765/metrics" in str(call_args)


class TestHTTPAPIClientContextManager:
    """Tests for context manager support."""

    def test_can_be_used_as_context_manager(self):
        """Client can be used with 'with' statement."""
        with HTTPAPIClient(api_url="http://localhost:8765") as client:
            assert client.api_url == "http://localhost:8765"

    @patch('requests.Session.close')
    def test_closes_session_on_exit(self, mock_close):
        """Session is closed when exiting context manager."""
        with HTTPAPIClient(api_url="http://localhost:8765") as client:
            pass

        mock_close.assert_called_once()


class TestHTTPAPIClientErrorHandling:
    """Tests for error handling and edge cases."""

    @patch('requests.Session.post')
    def test_handles_malformed_json_response(self, mock_post):
        """Handles malformed JSON response gracefully."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.side_effect = json.JSONDecodeError("Invalid JSON", "", 0)
        mock_post.return_value = mock_response

        client = HTTPAPIClient(api_url="http://localhost:8765")
        event = {"event_id": "test-123"}

        with pytest.raises(APIError, match="Unexpected API error"):
            client.post_event(event)

    @patch('requests.Session.post')
    def test_does_not_retry_validation_errors(self, mock_post):
        """Does not retry 400 validation errors."""
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.text = "Missing event_id"
        mock_post.return_value = mock_response

        client = HTTPAPIClient(api_url="http://localhost:8765", max_retries=3)
        event = {"run_id": "test"}

        with pytest.raises(APIValidationError):
            client.post_event(event)

        # Should fail immediately, not retry
        assert mock_post.call_count == 1

    @patch('requests.Session.post')
    @patch('time.sleep')
    def test_batch_retries_on_connection_error(self, mock_sleep, mock_post):
        """Batch POST retries on connection error."""
        mock_post.side_effect = [
            requests.exceptions.ConnectionError("Connection refused"),
            Mock(
                status_code=201,
                json=lambda: {"inserted": 1, "duplicates": 0, "errors": [], "total": 1}
            ),
        ]

        client = HTTPAPIClient(api_url="http://localhost:8765", retry_delay=0.1)
        events = [{"event_id": "test-1"}]

        result = client.post_batch(events)

        assert result["inserted"] == 1
        assert mock_post.call_count == 2
