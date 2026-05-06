"""Tests for AgentMetricsPayload — exact 17 Google Sheet fields."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.observability.agent_metrics_payload import (
    AGENT_NAME,
    AGENT_OWNER,
    EXPECTED_POST_KEYS,
    AgentMetricsPayload,
    determine_status,
    make_timestamp,
)


def _valid_kwargs() -> dict:
    """Return a minimal valid payload dict."""
    return {
        "timestamp": "2026-05-06T14:30:00+00:00",
        "agent_name": AGENT_NAME,
        "agent_owner": AGENT_OWNER,
        "job_type": "content_translation",
        "run_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "status": "success",
        "product": "Aspose.Words",
        "platform": ".NET",
        "website": "aspose.com",
        "website_section": "Docs",
        "item_name": "docs.aspose.net/words content_translation",
        "items_discovered": 10,
        "items_failed": 0,
        "items_succeeded": 10,
        "run_duration_ms": 5000,
        "token_usage": 1200,
        "api_calls_count": 5,
    }


class TestPayloadConstruction:
    def test_valid_payload(self):
        p = AgentMetricsPayload(**_valid_kwargs())
        assert p.agent_name == AGENT_NAME
        assert p.agent_owner == AGENT_OWNER

    def test_to_post_dict_has_exactly_17_keys(self):
        p = AgentMetricsPayload(**_valid_kwargs())
        d = p.to_post_dict()
        assert len(d) == 17
        assert set(d.keys()) == EXPECTED_POST_KEYS

    def test_no_extra_keys_in_post_dict(self):
        p = AgentMetricsPayload(**_valid_kwargs())
        d = p.to_post_dict()
        extra = set(d.keys()) - EXPECTED_POST_KEYS
        assert extra == set(), f"Extra keys found: {extra}"


class TestAgentConstants:
    def test_wrong_agent_name_rejected(self):
        kw = _valid_kwargs()
        kw["agent_name"] = "wrong-agent"
        with pytest.raises(ValidationError, match="agent_name"):
            AgentMetricsPayload(**kw)

    def test_wrong_agent_owner_rejected(self):
        kw = _valid_kwargs()
        kw["agent_owner"] = "Someone Else"
        with pytest.raises(ValidationError, match="agent_owner"):
            AgentMetricsPayload(**kw)


class TestStatusValidation:
    @pytest.mark.parametrize("status", ["success", "partial_success", "failure"])
    def test_valid_statuses(self, status):
        kw = _valid_kwargs()
        kw["status"] = status
        if status == "failure":
            kw["items_succeeded"] = 0
            kw["items_failed"] = 10
        elif status == "partial_success":
            kw["items_succeeded"] = 5
            kw["items_failed"] = 5
        p = AgentMetricsPayload(**kw)
        assert p.status == status

    def test_error_status_rejected(self):
        kw = _valid_kwargs()
        kw["status"] = "error"
        with pytest.raises(ValidationError, match="status"):
            AgentMetricsPayload(**kw)

    def test_unknown_status_rejected(self):
        kw = _valid_kwargs()
        kw["status"] = "warning"
        with pytest.raises(ValidationError, match="status"):
            AgentMetricsPayload(**kw)


class TestItemCountValidation:
    def test_succeeded_plus_failed_exceeds_discovered(self):
        kw = _valid_kwargs()
        kw["items_discovered"] = 5
        kw["items_succeeded"] = 3
        kw["items_failed"] = 3
        with pytest.raises(ValidationError, match="items_succeeded"):
            AgentMetricsPayload(**kw)

    def test_negative_items_rejected(self):
        kw = _valid_kwargs()
        kw["items_discovered"] = -1
        with pytest.raises(ValidationError):
            AgentMetricsPayload(**kw)


class TestTokenConsistency:
    def test_zero_calls_nonzero_tokens_rejected(self):
        kw = _valid_kwargs()
        kw["api_calls_count"] = 0
        kw["token_usage"] = 100
        with pytest.raises(ValidationError, match="token_usage must be 0"):
            AgentMetricsPayload(**kw)

    def test_zero_calls_zero_tokens_ok(self):
        kw = _valid_kwargs()
        kw["api_calls_count"] = 0
        kw["token_usage"] = 0
        p = AgentMetricsPayload(**kw)
        assert p.token_usage == 0

    def test_nonzero_calls_with_tokens_ok(self):
        kw = _valid_kwargs()
        kw["api_calls_count"] = 3
        kw["token_usage"] = 500
        p = AgentMetricsPayload(**kw)
        assert p.api_calls_count == 3


class TestFieldValidation:
    def test_empty_website_rejected(self):
        kw = _valid_kwargs()
        kw["website"] = "  "
        with pytest.raises(ValidationError, match="website"):
            AgentMetricsPayload(**kw)

    def test_empty_item_name_rejected(self):
        kw = _valid_kwargs()
        kw["item_name"] = ""
        with pytest.raises(ValidationError, match="item_name"):
            AgentMetricsPayload(**kw)

    def test_negative_run_duration_rejected(self):
        kw = _valid_kwargs()
        kw["run_duration_ms"] = -1
        with pytest.raises(ValidationError):
            AgentMetricsPayload(**kw)


class TestDetermineStatus:
    def test_zero_discovered_is_success(self):
        assert determine_status(0, 0, 0) == "success"

    def test_no_failures_is_success(self):
        assert determine_status(5, 0, 5) == "success"

    def test_no_successes_is_failure(self):
        assert determine_status(0, 5, 5) == "failure"

    def test_mixed_is_partial(self):
        assert determine_status(3, 2, 5) == "partial_success"


class TestMakeTimestamp:
    def test_timestamp_is_iso_format(self):
        ts = make_timestamp()
        assert "T" in ts
        assert "+" in ts or "Z" in ts
