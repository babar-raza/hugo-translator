"""Integration test: serialized payload has exactly 17 keys matching Sheet columns."""

from __future__ import annotations

import json

import pytest

from src.observability.agent_metrics_payload import (
    AGENT_NAME,
    AGENT_OWNER,
    EXPECTED_POST_KEYS,
    AgentMetricsPayload,
    make_timestamp,
)


class TestPayloadSchemaIntegration:
    def test_serialized_payload_exact_17_keys(self):
        p = AgentMetricsPayload(
            timestamp=make_timestamp(),
            agent_name=AGENT_NAME,
            agent_owner=AGENT_OWNER,
            job_type="Test",
            run_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            status="success",
            product="Aspose.Words",
            platform=".NET",
            website="aspose.net",
            website_section="Docs",
            item_name="Tested Words Docs — 2 files",
            items_discovered=2,
            items_failed=0,
            items_succeeded=2,
            run_duration_ms=1000,
            token_usage=100,
            api_calls_count=2,
        )
        d = p.to_post_dict()
        # Serialize to JSON and back to simulate actual POST
        serialized = json.loads(json.dumps(d))
        assert len(serialized) == 17, (
            f"Expected 17 keys, got {len(serialized)}: {sorted(serialized.keys())}"
        )
        assert set(serialized.keys()) == EXPECTED_POST_KEYS

    def test_no_extra_model_fields_leak(self):
        """Ensure model_dump() doesn't add extra keys beyond to_post_dict()."""
        p = AgentMetricsPayload(
            timestamp=make_timestamp(),
            agent_name=AGENT_NAME,
            agent_owner=AGENT_OWNER,
            job_type="Content Translation",
            run_id="run-123",
            status="success",
            product="Aspose.Total",
            platform="all",
            website="aspose.net",
            website_section="Docs",
            item_name="Translated All Products Docs — 0 files",
            items_discovered=0,
            items_failed=0,
            items_succeeded=0,
            run_duration_ms=0,
            token_usage=0,
            api_calls_count=0,
        )
        post_keys = set(p.to_post_dict().keys())
        model_keys = set(p.model_dump().keys())
        assert post_keys == model_keys, f"model_dump has extra keys: {model_keys - post_keys}"
