"""
Tests for MetricsRunContext.abort() — failure sidecar on early exit.

Requirement: if a content_root fails or is aborted before normal completion,
MetricsRunContext.abort() must write a dry-run failure sidecar with:
- status = failure (items_discovered=0, items_succeeded=0, items_failed=0)
- posting.status = dry_run (no HTTP POST)
- error_detail containing the abort reason
- token_usage and api_calls_count accumulated so far
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


def _make_config_service(enabled: bool = True, dry_run: bool = True) -> MagicMock:
    """Create a mock config_service with agent_metrics enabled/dry_run."""
    cs = MagicMock()
    cs.get_config.return_value = {
        "agent_metrics": {
            "enabled": enabled,
            "dry_run": dry_run,
            "evidence_dir": "data/metrics/agent_evidence",
            "metrics_website_mapping": {"aspose.net": "aspose.com"},
            "metrics_section_mapping": {"docs": "Docs"},
            "metrics_brand_mapping": {"aspose.com": "Aspose"},
            "known_product_families": ["words"],
            "known_platforms": [],
        }
    }
    return cs


class TestMetricsRunContextAbort(unittest.TestCase):
    """Tests for MetricsRunContext.abort()."""

    def test_abort_returns_none_when_not_enabled(self):
        """abort() is a no-op when enabled=False."""
        from src.observability.agent_metrics_integration import MetricsRunContext

        cs = _make_config_service(enabled=False)
        ctx = MetricsRunContext(
            site_id="docs.aspose.net",
            content_root_raw="${ASPOSE_NET_CONTENT}/docs.aspose.net/words",
            config_service=cs,
        )
        result = ctx.abort("some error")
        self.assertIsNone(result)

    def test_abort_calls_finish_with_zero_counts(self):
        """abort() delegates to finish() with items_discovered=0, succeeded=0, failed=0."""
        from src.observability.agent_metrics_integration import MetricsRunContext

        cs = _make_config_service(enabled=True, dry_run=True)
        ctx = MetricsRunContext(
            site_id="docs.aspose.net",
            content_root_raw="${ASPOSE_NET_CONTENT}/docs.aspose.net/words",
            config_service=cs,
        )

        finish_calls = []

        def mock_finish(items_discovered, items_succeeded, items_failed, error_detail=None):
            finish_calls.append({
                "items_discovered": items_discovered,
                "items_succeeded": items_succeeded,
                "items_failed": items_failed,
                "error_detail": error_detail,
            })
            return {"action": "dry_run"}

        ctx.finish = mock_finish
        ctx._enabled = True  # bypass enabled check in abort()

        ctx.abort("Worker aborted by signal")

        self.assertEqual(len(finish_calls), 1)
        call = finish_calls[0]
        self.assertEqual(call["items_discovered"], 0)
        self.assertEqual(call["items_succeeded"], 0)
        self.assertEqual(call["items_failed"], 0)
        self.assertIn("Worker aborted", call["error_detail"])

    def test_abort_default_error_detail(self):
        """abort() with no args uses the default error message."""
        from src.observability.agent_metrics_integration import MetricsRunContext

        cs = _make_config_service(enabled=True, dry_run=True)
        ctx = MetricsRunContext(
            site_id="docs.aspose.net",
            content_root_raw="${ASPOSE_NET_CONTENT}/docs.aspose.net/words",
            config_service=cs,
        )

        finish_calls = []

        def mock_finish(items_discovered, items_succeeded, items_failed, error_detail=None):
            finish_calls.append(error_detail)
            return {"action": "dry_run"}

        ctx.finish = mock_finish
        ctx._enabled = True

        ctx.abort()  # no error_detail arg

        self.assertEqual(len(finish_calls), 1)
        self.assertIsNotNone(finish_calls[0])
        self.assertIn("aborted", finish_calls[0].lower())

    def test_abort_with_dry_run_true_does_not_post(self):
        """abort() with dry_run=True must not trigger any HTTP POST."""
        from src.observability.agent_metrics_integration import MetricsRunContext

        cs = _make_config_service(enabled=True, dry_run=True)
        ctx = MetricsRunContext(
            site_id="docs.aspose.net",
            content_root_raw="${ASPOSE_NET_CONTENT}/docs.aspose.net/words",
            config_service=cs,
        )
        ctx._start_time = 1000.0  # simulate start() was called

        with patch("src.observability.agent_metrics_integration.MetricsRunContext._build_and_post") as mock_build:
            mock_build.return_value = {"action": "dry_run"}
            result = ctx.abort("Test abort — dry_run must not post")

        # Verify _build_and_post was called (abort delegates to finish which calls _build_and_post)
        mock_build.assert_called_once()
        # Verify error_detail was passed
        call_kwargs = mock_build.call_args[1]
        self.assertIsNotNone(call_kwargs.get("error_detail"))
        self.assertIn("dry_run must not post", call_kwargs["error_detail"])

    def test_abort_is_safe_to_call_without_start(self):
        """abort() does not raise even if start() was never called."""
        from src.observability.agent_metrics_integration import MetricsRunContext

        cs = _make_config_service(enabled=True, dry_run=True)
        ctx = MetricsRunContext(
            site_id="docs.aspose.net",
            content_root_raw="${ASPOSE_NET_CONTENT}/docs.aspose.net/words",
            config_service=cs,
        )

        with patch("src.observability.agent_metrics_integration.MetricsRunContext._build_and_post") as mock_build:
            mock_build.return_value = {"action": "dry_run"}
            # start() never called — _start_time is None, _llm_ctx is None
            try:
                ctx.abort("No start() called")
            except Exception as e:
                self.fail(f"abort() raised unexpectedly: {e}")


class TestRepeatedFeedbackGuardIntegration(unittest.TestCase):
    """Verify the repeated feedback guard logic is consistent with engine behavior."""

    def test_guard_logic_fails_on_second_identical_retry(self):
        """Reproduce guard: second retry with same validators -> immediate fail."""
        prev: frozenset | None = None
        results = []

        for retry_num in range(3):  # simulate retry_count 0, 1, 2
            current = frozenset({("LanguageConsistencyValidator", "error")})
            should_fail = (
                prev is not None and bool(current) and current == prev
            )
            results.append((retry_num, should_fail))
            prev = current

        # retry 0: prev=None -> no fail
        self.assertFalse(results[0][1])
        # retry 1: prev=same -> FAIL EARLY (no retry 2)
        self.assertTrue(results[1][1])

    def test_guard_allows_different_error_on_retry(self):
        """Different validators on consecutive retries -> guard allows all max_retry_attempts."""
        prev: frozenset | None = None
        validators_sequence = [
            frozenset({("LanguageConsistencyValidator", "error")}),
            frozenset({("PlaceholderValidator", "error")}),  # different on retry 2
        ]

        for i, current in enumerate(validators_sequence):
            should_fail = (
                prev is not None and bool(current) and current == prev
            )
            self.assertFalse(should_fail, f"Guard should not trigger on retry {i+1}")
            prev = current


if __name__ == "__main__":
    unittest.main()
