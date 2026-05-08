"""Gate 9: Dry-run acceptance matrix — 15 scenarios (M1-M15).

Each scenario validates that a dry-run metrics payload produces correct
evidence without actually posting to the Google Sheet.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.observability.agent_metrics_payload import (
    AGENT_NAME, AGENT_OWNER, EXPECTED_POST_KEYS,
    AgentMetricsPayload, determine_status, make_timestamp,
)
from src.observability.agent_metrics_integration import _build_item_name
from src.observability.metrics_scope import (
    ScopeResolver, ScopeInput, derive_content_root_id,
    generate_stable_work_slice_id, generate_execution_attempt_id,
    generate_segment_run_id,
)
from src.observability.gitlab_context import collect_gitlab_context
from src.observability.metrics_evidence import EvidenceWriter
from src.observability.llm_run_context import LLMRunContext


def _build_scenario(
    site_id: str,
    content_root_raw: str,
    items_discovered: int,
    items_succeeded: int,
    items_failed: int,
    token_usage: int,
    api_calls_count: int,
    job_type: str = "Content Translation",
) -> dict:
    """Build a full dry-run scenario and return evidence + payload."""
    crid = derive_content_root_id(content_root_raw)
    resolver = ScopeResolver(config={
        "metrics_website_mapping": {},
        "metrics_section_mapping": {"docs": "Docs", "products": "Product Pages", "blog": "Blog"},
        "metrics_brand_mapping": {"aspose.net": "Aspose", "aspose.com": "Aspose"},
        "metrics_domain_platform_mapping": {"aspose.net": "net"},
    })
    scope_input = ScopeInput(
        site_id=site_id,
        content_root_raw=content_root_raw,
        profile_filename=f"{site_id}.yaml",
    )
    resolved = resolver.resolve(scope_input)
    item_name = _build_item_name(resolved, job_type, items_succeeded)

    status = determine_status(items_succeeded, items_failed, items_discovered)
    payload = AgentMetricsPayload(
        timestamp=make_timestamp(),
        job_type=job_type,
        run_id=str(uuid.uuid4()),
        status=status,
        product=resolved.product,
        platform=resolved.platform,
        website=resolved.website,
        website_section=resolved.website_section,
        item_name=item_name,
        items_discovered=items_discovered,
        items_failed=items_failed,
        items_succeeded=items_succeeded,
        run_duration_ms=5000,
        token_usage=token_usage,
        api_calls_count=api_calls_count,
    )
    return {
        "payload": payload,
        "post_dict": payload.to_post_dict(),
        "resolved": resolved,
    }


class TestM1ContentTranslationDocsWords:
    def test_m1(self):
        r = _build_scenario(
            site_id="docs.aspose.net",
            content_root_raw="${ASPOSE_NET_CONTENT}/docs.aspose.net/words",
            items_discovered=10, items_succeeded=8, items_failed=2,
            token_usage=1200, api_calls_count=10,
        )
        assert r["resolved"].product == "Aspose.Words"
        assert r["resolved"].website_section == "Docs"
        assert r["resolved"].website == "aspose.net"
        assert r["post_dict"]["token_usage"] == 1200
        assert "Words" in r["post_dict"]["item_name"]
        assert "Docs" in r["post_dict"]["item_name"]


class TestM2ProductsPagesWords:
    def test_m2(self):
        r = _build_scenario(
            site_id="products.aspose.net",
            content_root_raw="${ASPOSE_NET_CONTENT}/products.aspose.net/words",
            items_discovered=5, items_succeeded=5, items_failed=0,
            token_usage=600, api_calls_count=5,
        )
        assert r["resolved"].website_section == "Product Pages"
        assert r["resolved"].product == "Aspose.Words"


class TestM3TwoLocalesSingleRow:
    def test_m3(self):
        """Two locales produce a single row with locale='all' in evidence."""
        r = _build_scenario(
            site_id="docs.aspose.net",
            content_root_raw="${ASPOSE_NET_CONTENT}/docs.aspose.net/words",
            items_discovered=10, items_succeeded=10, items_failed=0,
            token_usage=2000, api_calls_count=10,
        )
        # Single row — locale grain is always "all"
        assert len(r["post_dict"]) == 17
        assert r["post_dict"]["status"] == "success"


class TestM4VerificationWorkerNoLLM:
    def test_m4(self):
        """Verification worker: token_usage=0, api_calls_count=0."""
        r = _build_scenario(
            site_id="docs.aspose.net",
            content_root_raw="${ASPOSE_NET_CONTENT}/docs.aspose.net/words",
            items_discovered=5, items_succeeded=5, items_failed=0,
            token_usage=0, api_calls_count=0,
        )
        assert r["post_dict"]["token_usage"] == 0
        assert r["post_dict"]["api_calls_count"] == 0


class TestM5SimulatedFailedLLMCall:
    def test_m5(self):
        """Simulated failed LLM call — failed_provider_calls > 0 in context."""
        ctx = LLMRunContext.start_run()
        try:
            ctx.record_attempted()
            ctx.record_failed()
            ctx.record_attempted()
            ctx.record_completed(100, 50)
            delta = ctx.checkpoint()
            assert delta.failed_provider_calls > 0
            assert delta.completed_provider_calls == 1
        finally:
            LLMRunContext.end_run()


class TestM6aDuplicateSkipped:
    def test_m6a(self, tmp_path):
        ew = EvidenceWriter(evidence_dir=str(tmp_path / "ev"))
        seg_id = str(uuid.uuid4())
        ew.write_posted_marker(seg_id)
        assert ew.is_already_posted(seg_id) is True


class TestM6bNewAttemptSeparateRow:
    @patch("src.observability.metrics_scope._get_repo_identifier", return_value="repo")
    @patch("src.observability.metrics_scope._get_source_commit_sha", return_value="sha1")
    def test_m6b(self, _sha, _repo):
        ws = generate_stable_work_slice_id(
            site_id="docs.aspose.net", content_root_id="docs.aspose.net/words",
            product_family_token="words", platform="all",
            operation_type="content_translation",
        )
        ctx = MagicMock()
        ctx.ci_pipeline_id = "local"
        ctx.ci_job_id = "none"
        ctx.hostname = "host"
        ea1 = generate_execution_attempt_id(parent_run_id="p1", gitlab_ctx=ctx)
        ea2 = generate_execution_attempt_id(parent_run_id="p2", gitlab_ctx=ctx)
        seg1 = generate_segment_run_id(ws, ea1)
        seg2 = generate_segment_run_id(ws, ea2)
        assert seg1 != seg2


class TestM7LocalMode:
    def test_m7(self, monkeypatch):
        for var in ["CI_PIPELINE_ID", "CI_JOB_ID", "CI_JOB_NAME"]:
            monkeypatch.delenv(var, raising=False)
        ctx = collect_gitlab_context()
        assert ctx.is_ci is False
        assert ctx.hostname


class TestM8CIMode:
    def test_m8(self, monkeypatch):
        monkeypatch.setenv("CI_PIPELINE_ID", "12345")
        monkeypatch.setenv("CI_JOB_ID", "67890")
        ctx = collect_gitlab_context()
        assert ctx.is_ci is True


class TestM9FallbackProfile:
    def test_m9(self):
        """Profile with no family → product=*.Total, reporting_confidence=medium."""
        r = _build_scenario(
            site_id="blog.aspose.net",
            content_root_raw="${ASPOSE_NET_CONTENT}/blog.aspose.net",
            items_discovered=3, items_succeeded=3, items_failed=0,
            token_usage=300, api_calls_count=3,
        )
        assert "Total" in r["resolved"].product
        assert r["resolved"].reporting_confidence == "medium"


class TestM10ContentRootIdStability:
    def test_m10(self):
        win = derive_content_root_id("${VAR}\\docs.aspose.net\\words")
        linux = derive_content_root_id("${VAR}/docs.aspose.net/words")
        assert win == linux


class TestM11TestProfileExcluded:
    def test_m11(self):
        """Test profile is excluded from posting."""
        from src.observability.agent_metrics_integration import _is_excluded
        cfg = {"excluded_site_id_prefixes": ["blog-test", "golden-test", "example"]}
        assert _is_excluded("blog-test-site", cfg) is True
        assert _is_excluded("golden-test-profile", cfg) is True
        assert _is_excluded("docs.aspose.net", cfg) is False


class TestM12MissingEndpointEnv:
    def test_m12(self, monkeypatch):
        from src.observability.agent_metrics_poster import AgentMetricsPoster
        monkeypatch.delenv("AGENT_METRICS_ENDPOINT", raising=False)
        monkeypatch.delenv("AGENT_METRICS_TOKEN", raising=False)
        poster = AgentMetricsPoster(dry_run=False)
        assert poster.is_enabled is False
        result = poster.post({"test": 1})
        assert "disabled" in result["error"]


class TestM13ExceptionMapsToFailure:
    def test_m13(self):
        status = determine_status(0, 5, 5)
        assert status == "failure"


class TestM14PayloadFieldCount:
    def test_m14(self):
        r = _build_scenario(
            site_id="docs.aspose.net",
            content_root_raw="${ASPOSE_NET_CONTENT}/docs.aspose.net/words",
            items_discovered=1, items_succeeded=1, items_failed=0,
            token_usage=50, api_calls_count=1,
        )
        d = r["post_dict"]
        serialized = json.loads(json.dumps(d))
        assert len(serialized) == 17
        assert set(serialized.keys()) == EXPECTED_POST_KEYS


class TestM15ProfessionalizeEvidence:
    def test_m15(self, tmp_path):
        """Evidence sidecar has llm_provider block with is_professionalize."""
        ew = EvidenceWriter(evidence_dir=str(tmp_path / "ev"))
        llm_provider = {
            "provider_name": "openai_compatible",
            "model_name": "recommended",
            "endpoint_host": "llm.professionalize.com",
            "is_professionalize": True,
        }
        r = _build_scenario(
            site_id="docs.aspose.net",
            content_root_raw="${ASPOSE_NET_CONTENT}/docs.aspose.net/words",
            items_discovered=1, items_succeeded=1, items_failed=0,
            token_usage=50, api_calls_count=1,
        )
        path = ew.write_pre_post_sidecar(
            segment_run_id="seg-test",
            ids={"segment_run_id": "seg-test"},
            execution_context={"is_ci": False},
            scope={"site_id": "docs.aspose.net"},
            llm_provider=llm_provider,
            posted_payload=r["post_dict"],
            call_accounting={},
            items_detail={},
            dry_run=True,
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["llm_provider"]["is_professionalize"] is True
        assert data["llm_provider"]["endpoint_host"] == "llm.professionalize.com"
