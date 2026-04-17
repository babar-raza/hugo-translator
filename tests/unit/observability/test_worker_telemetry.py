"""
Unit tests for worker_telemetry helper module.

All tests mock the HTTP layer to verify correct payload shape,
non-fatal failure handling, and lifecycle (POST + PATCH) flows.
"""

import unittest
from unittest.mock import Mock, patch

from src.observability.worker_telemetry import (
    _build_base_run,
    _patch_run,
    _post_run,
    complete_worker_run,
    emit_worker_event,
    start_worker_run,
)


class TestBuildBaseRun(unittest.TestCase):
    """Test _build_base_run produces correct structure."""

    def test_base_run_has_required_fields(self):
        run = _build_base_run("test-agent", "test-job")
        required = {"event_id", "run_id", "agent_name", "job_type",
                     "trigger_type", "start_time", "host", "environment"}
        self.assertTrue(required.issubset(set(run.keys())))

    def test_base_run_agent_name(self):
        run = _build_base_run("content_worker", "worker_preflight")
        self.assertEqual(run["agent_name"], "content_worker")
        self.assertEqual(run["job_type"], "worker_preflight")

    def test_base_run_trigger_type_default(self):
        run = _build_base_run("a", "b")
        self.assertEqual(run["trigger_type"], "scheduled")

    def test_base_run_trigger_type_override(self):
        run = _build_base_run("a", "b", trigger_type="cli")
        self.assertEqual(run["trigger_type"], "cli")

    def test_base_run_start_time_is_iso8601_utc(self):
        run = _build_base_run("a", "b")
        self.assertIn("+00:00", run["start_time"])

    def test_base_run_event_id_is_uuid(self):
        import uuid
        run = _build_base_run("a", "b")
        uuid.UUID(run["event_id"])  # Raises if invalid


class TestPostRun(unittest.TestCase):
    """Test _post_run HTTP layer."""

    @patch("src.observability.worker_telemetry._get_api_url", return_value="http://test:8765")
    def test_post_success_returns_event_id(self, _mock_url):
        with patch("requests.post") as mock_post:
            mock_resp = Mock()
            mock_resp.status_code = 201
            mock_post.return_value = mock_resp

            eid = _post_run({"event_id": "abc-123", "job_type": "test"})
            self.assertEqual(eid, "abc-123")
            mock_post.assert_called_once()

    @patch("src.observability.worker_telemetry._get_api_url", return_value="http://test:8765")
    def test_post_non_201_returns_none(self, _mock_url):
        with patch("requests.post") as mock_post:
            mock_resp = Mock()
            mock_resp.status_code = 422
            mock_resp.text = "validation error"
            mock_post.return_value = mock_resp

            eid = _post_run({"event_id": "abc", "job_type": "test"})
            self.assertIsNone(eid)

    @patch("src.observability.worker_telemetry._get_api_url", return_value="http://test:8765")
    def test_post_connection_error_returns_none(self, _mock_url):
        with patch("requests.post", side_effect=ConnectionError("refused")):
            eid = _post_run({"event_id": "abc", "job_type": "test"})
            self.assertIsNone(eid)

    @patch("src.observability.worker_telemetry._get_api_url", return_value="http://test:8765")
    def test_post_timeout_returns_none(self, _mock_url):
        import requests
        with patch("requests.post", side_effect=requests.exceptions.Timeout("timeout")):
            eid = _post_run({"event_id": "abc", "job_type": "test"})
            self.assertIsNone(eid)


class TestPatchRun(unittest.TestCase):
    """Test _patch_run HTTP layer."""

    @patch("src.observability.worker_telemetry._get_api_url", return_value="http://test:8765")
    def test_patch_success_returns_true(self, _mock_url):
        with patch("requests.patch") as mock_patch:
            mock_resp = Mock()
            mock_resp.status_code = 200
            mock_patch.return_value = mock_resp

            result = _patch_run("abc-123", {"status": "success"})
            self.assertTrue(result)

    @patch("src.observability.worker_telemetry._get_api_url", return_value="http://test:8765")
    def test_patch_404_returns_false(self, _mock_url):
        with patch("requests.patch") as mock_patch:
            mock_resp = Mock()
            mock_resp.status_code = 404
            mock_resp.text = "not found"
            mock_patch.return_value = mock_resp

            result = _patch_run("abc-123", {"status": "success"})
            self.assertFalse(result)

    @patch("src.observability.worker_telemetry._get_api_url", return_value="http://test:8765")
    def test_patch_exception_returns_false(self, _mock_url):
        with patch("requests.patch", side_effect=ConnectionError("refused")):
            result = _patch_run("abc-123", {"status": "success"})
            self.assertFalse(result)


class TestEmitWorkerEvent(unittest.TestCase):
    """Test emit_worker_event fire-and-forget pattern."""

    @patch("src.observability.worker_telemetry._post_run")
    def test_emit_basic_event(self, mock_post):
        mock_post.return_value = "evt-123"

        eid = emit_worker_event(
            agent_name="content_worker",
            job_type="worker_preflight",
            status="success",
        )
        self.assertEqual(eid, "evt-123")
        call_data = mock_post.call_args[0][0]
        self.assertEqual(call_data["agent_name"], "content_worker")
        self.assertEqual(call_data["job_type"], "worker_preflight")
        self.assertEqual(call_data["status"], "success")
        self.assertIn("end_time", call_data)

    @patch("src.observability.worker_telemetry._post_run")
    def test_emit_with_metrics(self, mock_post):
        mock_post.return_value = "evt-456"

        emit_worker_event(
            agent_name="tm_worker",
            job_type="worker_gpu_check",
            status="failure",
            metrics={"gpu_usage_percent": 95.2, "threshold": 90},
            error_summary="GPU usage 95.2% exceeds threshold",
        )
        call_data = mock_post.call_args[0][0]
        self.assertEqual(call_data["metrics_json"]["gpu_usage_percent"], 95.2)
        self.assertEqual(call_data["error_summary"], "GPU usage 95.2% exceeds threshold")

    @patch("src.observability.worker_telemetry._post_run")
    def test_emit_with_items(self, mock_post):
        mock_post.return_value = "evt-789"

        emit_worker_event(
            agent_name="content_worker",
            job_type="worker_site_discovery",
            items_discovered=5,
            items_succeeded=3,
            items_failed=2,
        )
        call_data = mock_post.call_args[0][0]
        self.assertEqual(call_data["items_discovered"], 5)
        self.assertEqual(call_data["items_succeeded"], 3)
        self.assertEqual(call_data["items_failed"], 2)

    @patch("src.observability.worker_telemetry._post_run", return_value=None)
    def test_emit_failure_returns_none(self, mock_post):
        eid = emit_worker_event("a", "b", status="failure")
        self.assertIsNone(eid)


class TestStartAndCompleteWorkerRun(unittest.TestCase):
    """Test start/complete lifecycle pattern."""

    @patch("src.observability.worker_telemetry._post_run")
    def test_start_run_posts_running(self, mock_post):
        mock_post.return_value = "run-001"

        eid = start_worker_run("content_worker", "worker_lifecycle")
        self.assertEqual(eid, "run-001")
        call_data = mock_post.call_args[0][0]
        self.assertEqual(call_data["status"], "running")
        self.assertNotIn("end_time", call_data)

    @patch("src.observability.worker_telemetry._post_run")
    def test_start_run_with_context(self, mock_post):
        mock_post.return_value = "run-002"

        start_worker_run(
            "content_worker", "worker_lifecycle",
            context={"mode": "daemon", "runs_per_day": 4},
        )
        call_data = mock_post.call_args[0][0]
        self.assertEqual(call_data["context_json"]["mode"], "daemon")

    @patch("src.observability.worker_telemetry._patch_run")
    def test_complete_run_patches_success(self, mock_patch):
        mock_patch.return_value = True

        ok = complete_worker_run(
            "run-001",
            status="success",
            duration_ms=30000,
            items_succeeded=5,
        )
        self.assertTrue(ok)
        call_update = mock_patch.call_args[0][1]
        self.assertEqual(call_update["status"], "success")
        self.assertEqual(call_update["duration_ms"], 30000)
        self.assertEqual(call_update["items_succeeded"], 5)
        self.assertIn("end_time", call_update)

    @patch("src.observability.worker_telemetry._patch_run")
    def test_complete_run_with_error(self, mock_patch):
        mock_patch.return_value = True

        complete_worker_run(
            "run-001",
            status="failure",
            error_summary="Preflight GPU check failed",
        )
        call_update = mock_patch.call_args[0][1]
        self.assertEqual(call_update["status"], "failure")
        self.assertEqual(call_update["error_summary"], "Preflight GPU check failed")

    @patch("src.observability.worker_telemetry._patch_run", return_value=False)
    def test_complete_run_failure_returns_false(self, mock_patch):
        ok = complete_worker_run("run-001", status="success")
        self.assertFalse(ok)


class TestStartCompleteIntegration(unittest.TestCase):
    """Test the full start → work → complete pattern."""

    @patch("src.observability.worker_telemetry._patch_run", return_value=True)
    @patch("src.observability.worker_telemetry._post_run", return_value="run-integration")
    def test_full_lifecycle(self, mock_post, mock_patch):
        eid = start_worker_run("content_worker", "worker_lifecycle",
                               context={"mode": "daemon"})
        self.assertIsNotNone(eid)

        ok = complete_worker_run(
            eid,
            status="success",
            duration_ms=15000,
            metrics={"runs_completed": 4},
            output_summary="4 translation runs completed",
        )
        self.assertTrue(ok)

        # Verify POST was called with running status
        post_data = mock_post.call_args[0][0]
        self.assertEqual(post_data["status"], "running")

        # Verify PATCH was called with success
        patch_data = mock_patch.call_args[0][1]
        self.assertEqual(patch_data["status"], "success")
        self.assertEqual(patch_data["output_summary"], "4 translation runs completed")


if __name__ == "__main__":
    unittest.main()
