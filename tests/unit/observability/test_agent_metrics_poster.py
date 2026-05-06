"""Tests for agent_metrics_poster — dry-run, secrets, 302, test-row limits."""
from __future__ import annotations

from unittest.mock import patch, MagicMock
import urllib.error

import pytest

from src.observability.agent_metrics_poster import (
    AgentMetricsPoster,
    _get_secret,
    reset_test_row_counter,
    get_test_rows_posted,
)


@pytest.fixture(autouse=True)
def _reset_counter():
    reset_test_row_counter()
    yield
    reset_test_row_counter()


SAMPLE_PAYLOAD = {"timestamp": "2026-05-06T00:00:00+00:00", "agent_name": "hugo-translator"}


class TestSecretHandling:
    def test_missing_env_var(self, monkeypatch):
        monkeypatch.delenv("AGENT_METRICS_ENDPOINT", raising=False)
        monkeypatch.delenv("AGENT_METRICS_TOKEN", raising=False)
        poster = AgentMetricsPoster(dry_run=False)
        assert poster.is_enabled is False

    def test_placeholder_rejected(self, monkeypatch):
        monkeypatch.setenv("AGENT_METRICS_ENDPOINT", "https://example.com")
        monkeypatch.setenv("AGENT_METRICS_TOKEN", "YOUR_TOKEN_HERE")
        poster = AgentMetricsPoster(dry_run=False)
        assert poster.is_enabled is False

    def test_valid_secrets_enable(self, monkeypatch):
        monkeypatch.setenv("AGENT_METRICS_ENDPOINT", "https://real.endpoint.com/api")
        monkeypatch.setenv("AGENT_METRICS_TOKEN", "real-secret-token-abc123")
        poster = AgentMetricsPoster(dry_run=False)
        assert poster.is_enabled is True

    def test_get_secret_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv("TEST_VAR", "  real-token  ")
        assert _get_secret("TEST_VAR") == "real-token"

    def test_get_secret_empty(self, monkeypatch):
        monkeypatch.setenv("TEST_VAR", "  ")
        assert _get_secret("TEST_VAR") is None


class TestDryRun:
    def test_dry_run_does_not_post(self):
        poster = AgentMetricsPoster(dry_run=True)
        result = poster.post(SAMPLE_PAYLOAD)
        assert result["dry_run"] is True
        assert result["posted"] is False

    def test_dry_run_no_error(self):
        poster = AgentMetricsPoster(dry_run=True)
        result = poster.post(SAMPLE_PAYLOAD)
        assert result["error"] is None


class TestDisabledPosting:
    def test_disabled_returns_error(self, monkeypatch):
        monkeypatch.delenv("AGENT_METRICS_ENDPOINT", raising=False)
        monkeypatch.delenv("AGENT_METRICS_TOKEN", raising=False)
        poster = AgentMetricsPoster(dry_run=False)
        result = poster.post(SAMPLE_PAYLOAD)
        assert "disabled" in result["error"]
        assert result["posted"] is False


class TestSyncPost:
    @patch("urllib.request.urlopen")
    def test_successful_sync_post(self, mock_urlopen, monkeypatch):
        monkeypatch.setenv("AGENT_METRICS_ENDPOINT", "https://api.test.com")
        monkeypatch.setenv("AGENT_METRICS_TOKEN", "real-token-123")
        mock_response = MagicMock()
        mock_response.getcode.return_value = 200
        mock_urlopen.return_value = mock_response

        poster = AgentMetricsPoster(dry_run=False, fire_and_forget=False)
        result = poster.post(SAMPLE_PAYLOAD)
        assert result["posted"] is True
        assert result["response_code"] == 200

    @patch("urllib.request.urlopen")
    def test_302_treated_as_success(self, mock_urlopen, monkeypatch):
        monkeypatch.setenv("AGENT_METRICS_ENDPOINT", "https://api.test.com")
        monkeypatch.setenv("AGENT_METRICS_TOKEN", "real-token-123")
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://api.test.com", code=302, msg="Found",
            hdrs=MagicMock(), fp=MagicMock(),
        )

        poster = AgentMetricsPoster(dry_run=False, fire_and_forget=False)
        result = poster.post(SAMPLE_PAYLOAD, job_type="test")
        assert result["posted"] is True
        assert result["response_code"] == 302

    @patch("urllib.request.urlopen")
    def test_http_error_captured(self, mock_urlopen, monkeypatch):
        monkeypatch.setenv("AGENT_METRICS_ENDPOINT", "https://api.test.com")
        monkeypatch.setenv("AGENT_METRICS_TOKEN", "real-token-123")
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://api.test.com", code=500, msg="Internal Server Error",
            hdrs=MagicMock(), fp=MagicMock(),
        )

        poster = AgentMetricsPoster(dry_run=False, fire_and_forget=False)
        result = poster.post(SAMPLE_PAYLOAD)
        assert result["posted"] is False
        assert result["response_code"] == 500
        assert "500" in result["error"]


class TestTestRowLimit:
    @patch("urllib.request.urlopen")
    def test_max_3_test_rows(self, mock_urlopen, monkeypatch):
        monkeypatch.setenv("AGENT_METRICS_ENDPOINT", "https://api.test.com")
        monkeypatch.setenv("AGENT_METRICS_TOKEN", "real-token-123")
        mock_response = MagicMock()
        mock_response.getcode.return_value = 200
        mock_urlopen.return_value = mock_response

        poster = AgentMetricsPoster(dry_run=False, fire_and_forget=False)

        for i in range(3):
            result = poster.post(SAMPLE_PAYLOAD, job_type="test")
            assert result["posted"] is True, f"Post {i+1} should succeed"

        # 4th should be blocked
        result = poster.post(SAMPLE_PAYLOAD, job_type="test")
        assert result["posted"] is False
        assert "limit" in result["error"]
        assert get_test_rows_posted() == 3

    @patch("urllib.request.urlopen")
    def test_non_test_not_limited(self, mock_urlopen, monkeypatch):
        monkeypatch.setenv("AGENT_METRICS_ENDPOINT", "https://api.test.com")
        monkeypatch.setenv("AGENT_METRICS_TOKEN", "real-token-123")
        mock_response = MagicMock()
        mock_response.getcode.return_value = 200
        mock_urlopen.return_value = mock_response

        poster = AgentMetricsPoster(dry_run=False, fire_and_forget=False)
        for _ in range(5):
            result = poster.post(SAMPLE_PAYLOAD, job_type="content_translation")
            assert result["posted"] is True

    @patch("urllib.request.urlopen")
    def test_test_post_always_sync(self, mock_urlopen, monkeypatch):
        """Test posts are synchronous even when fire_and_forget=True (Amendment #2)."""
        monkeypatch.setenv("AGENT_METRICS_ENDPOINT", "https://api.test.com")
        monkeypatch.setenv("AGENT_METRICS_TOKEN", "real-token-123")
        mock_response = MagicMock()
        mock_response.getcode.return_value = 200
        mock_urlopen.return_value = mock_response

        poster = AgentMetricsPoster(dry_run=False, fire_and_forget=True)
        result = poster.post(SAMPLE_PAYLOAD, job_type="test")
        # Synchronous means we get a real response_code back
        assert result["response_code"] == 200
        assert result["posted"] is True
