"""Tests for Agent Metrics posting guards.

TC-ENABLE-03: Zero-item suppression guard
TC-ENABLE-04: Low-confidence scope suppression guard
TC-ENABLE-06: Config toggle guard (runtime env var)

CI scope: included in unit-tests agentic module block (gitlab-ci.yml +
release_gate.yml). 6 tests validate implemented behaviour; 3 xfail for
unimplemented guards (TC-ENABLE-03/04/06).

xfail policy:
  Tests for TC-ENABLE-03/04/06 are marked xfail(strict=False) because the
  corresponding guard features are not yet implemented in
  agent_metrics_integration.py.  When those features land the markers
  should be removed.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

import pytest


def _make_config_service(enabled: bool = True, dry_run: bool = True) -> MagicMock:
    cs = MagicMock()
    cs.get_config.return_value = {
        "agent_metrics": {
            "enabled": enabled,
            "dry_run": dry_run,
            "evidence_dir": "data/metrics/agent_evidence",
            "metrics_website_mapping": {},
            "metrics_section_mapping": {"docs": "Docs"},
            "metrics_brand_mapping": {"aspose.net": "Aspose"},
            "known_product_families": ["words"],
            "known_platforms": [],
        }
    }
    return cs


class TestZeroItemSuppression(unittest.TestCase):
    """TC-ENABLE-03: finish() skips posting when items_discovered == 0."""

    def test_zero_items_returns_skipped(self):
        from src.observability.agent_metrics_integration import MetricsRunContext

        cs = _make_config_service(enabled=True, dry_run=True)
        ctx = MetricsRunContext(
            site_id="docs.aspose.net",
            content_root_raw="/tmp/test",
            config_service=cs,
        )
        ctx._start_time = 1000.0

        with patch.object(ctx, "_build_and_post") as mock_build:
            result = ctx.finish(items_discovered=0, items_succeeded=0, items_failed=0)

        mock_build.assert_not_called()
        self.assertEqual(result["action"], "skipped_zero_items")
        self.assertEqual(result["site_id"], "docs.aspose.net")

    def test_zero_items_with_error_detail_still_posts(self):
        """abort() passes error_detail — zero-item guard should NOT suppress aborts."""
        from src.observability.agent_metrics_integration import MetricsRunContext

        cs = _make_config_service(enabled=True, dry_run=True)
        ctx = MetricsRunContext(
            site_id="docs.aspose.net",
            content_root_raw="/tmp/test",
            config_service=cs,
        )
        ctx._start_time = 1000.0

        with patch.object(ctx, "_build_and_post", return_value={"action": "dry_run"}) as mock_build:
            result = ctx.finish(
                items_discovered=0,
                items_succeeded=0,
                items_failed=0,
                error_detail="Worker crashed",
            )

        mock_build.assert_called_once()

    def test_nonzero_items_not_suppressed(self):
        from src.observability.agent_metrics_integration import MetricsRunContext

        cs = _make_config_service(enabled=True, dry_run=True)
        ctx = MetricsRunContext(
            site_id="docs.aspose.net",
            content_root_raw="/tmp/test",
            config_service=cs,
        )
        ctx._start_time = 1000.0

        with patch.object(ctx, "_build_and_post", return_value={"action": "dry_run"}) as mock_build:
            result = ctx.finish(items_discovered=5, items_succeeded=5, items_failed=0)

        mock_build.assert_called_once()


class TestLowConfidenceSuppression(unittest.TestCase):
    """TC-ENABLE-04: _build_and_post() skips when reporting_confidence == 'low'."""

    def _make_low_confidence_resolved(self):
        resolved = MagicMock()
        resolved.reporting_confidence = "low"
        resolved.product = "Aspose.Mixed"
        resolved.site_id = "about.aspose.net"
        resolved.source_site_domain = "aspose.net"
        resolved.content_root_id = "about.aspose.net"
        resolved.website = "aspose.net"
        resolved.website_section = "About"
        resolved.product_family_token = "unknown"
        resolved.platform = ".NET"
        resolved.detection_method = "fallback"
        resolved.fallback_used = True
        resolved.warnings = ["product_family_token could not be resolved"]
        return resolved

    @patch("src.observability.agent_metrics_integration.MetricsRunContext._detect_llm_provider")
    @patch("src.observability.metrics_scope.ScopeResolver.resolve")
    def test_low_confidence_returns_skipped(self, mock_resolve, mock_llm):
        from src.observability.agent_metrics_integration import MetricsRunContext

        mock_resolve.return_value = self._make_low_confidence_resolved()

        cs = _make_config_service(enabled=True, dry_run=True)
        ctx = MetricsRunContext(
            site_id="about.aspose.net",
            content_root_raw="/tmp/about",
            config_service=cs,
        )
        ctx._start_time = 1000.0

        result = ctx._build_and_post(
            items_discovered=23,
            items_succeeded=23,
            items_failed=0,
            run_duration_ms=5000,
            token_usage=0,
            api_calls_count=0,
            call_accounting={},
            error_detail=None,
        )

        self.assertEqual(result["action"], "skipped_low_confidence")
        self.assertEqual(result["site_id"], "about.aspose.net")
        self.assertEqual(result["product"], "Aspose.Mixed")

    @patch("src.observability.agent_metrics_integration.MetricsRunContext._detect_llm_provider")
    @patch("src.observability.metrics_scope.ScopeResolver.resolve")
    def test_high_confidence_not_suppressed(self, mock_resolve, mock_llm):
        from src.observability.agent_metrics_integration import MetricsRunContext

        resolved = self._make_low_confidence_resolved()
        resolved.reporting_confidence = "high"
        resolved.fallback_used = False
        mock_resolve.return_value = resolved
        mock_llm.return_value = {
            "provider_name": "unknown",
            "model_name": "unknown",
            "endpoint_host": "unknown",
            "is_professionalize": False,
        }

        cs = _make_config_service(enabled=True, dry_run=True)
        ctx = MetricsRunContext(
            site_id="docs.aspose.net",
            content_root_raw="/tmp/docs",
            config_service=cs,
        )

        with patch("src.observability.metrics_evidence.EvidenceWriter") as mock_ew:
            mock_ew_inst = MagicMock()
            mock_ew.return_value = mock_ew_inst
            mock_ew_inst.full_post_lifecycle.return_value = {"action": "dry_run"}

            result = ctx._build_and_post(
                items_discovered=5,
                items_succeeded=5,
                items_failed=0,
                run_duration_ms=5000,
                token_usage=100,
                api_calls_count=1,
                call_accounting={},
                error_detail=None,
            )

        self.assertNotEqual(result.get("action"), "skipped_low_confidence")


class TestConfigToggleGuard(unittest.TestCase):
    """TC-ENABLE-06: Runtime guard requires AGENT_METRICS_LIVE_APPROVED=1."""

    def test_live_posting_without_env_var_forces_dry_run(self):
        from src.observability.agent_metrics_integration import MetricsRunContext

        env = os.environ.copy()
        env.pop("AGENT_METRICS_LIVE_APPROVED", None)

        with patch.dict(os.environ, env, clear=True):
            cs = _make_config_service(enabled=True, dry_run=False)
            ctx = MetricsRunContext(
                site_id="docs.aspose.net",
                content_root_raw="/tmp/test",
                config_service=cs,
            )

        self.assertTrue(ctx._dry_run, "dry_run should be forced True without env var")

    def test_live_posting_with_env_var_allows_live(self):
        from src.observability.agent_metrics_integration import MetricsRunContext

        with patch.dict(os.environ, {"AGENT_METRICS_LIVE_APPROVED": "1"}):
            cs = _make_config_service(enabled=True, dry_run=False)
            ctx = MetricsRunContext(
                site_id="docs.aspose.net",
                content_root_raw="/tmp/test",
                config_service=cs,
            )

        self.assertFalse(ctx._dry_run, "dry_run should remain False when env var is set")

    def test_dry_run_true_unaffected_by_guard(self):
        from src.observability.agent_metrics_integration import MetricsRunContext

        env = os.environ.copy()
        env.pop("AGENT_METRICS_LIVE_APPROVED", None)

        with patch.dict(os.environ, env, clear=True):
            cs = _make_config_service(enabled=True, dry_run=True)
            ctx = MetricsRunContext(
                site_id="docs.aspose.net",
                content_root_raw="/tmp/test",
                config_service=cs,
            )

        self.assertTrue(ctx._dry_run)

    def test_disabled_unaffected_by_guard(self):
        from src.observability.agent_metrics_integration import MetricsRunContext

        env = os.environ.copy()
        env.pop("AGENT_METRICS_LIVE_APPROVED", None)

        with patch.dict(os.environ, env, clear=True):
            cs = _make_config_service(enabled=False, dry_run=False)
            ctx = MetricsRunContext(
                site_id="docs.aspose.net",
                content_root_raw="/tmp/test",
                config_service=cs,
            )

        # When enabled=False, the guard should not interfere
        self.assertFalse(ctx._dry_run)


if __name__ == "__main__":
    unittest.main()
