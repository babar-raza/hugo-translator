"""Tests for segment_run_id idempotency and duplicate suppression."""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from src.observability.metrics_scope import (
    generate_stable_work_slice_id,
    generate_execution_attempt_id,
    generate_segment_run_id,
)
from src.observability.metrics_evidence import EvidenceWriter


def _mock_gitlab_ctx(**overrides):
    ctx = MagicMock()
    ctx.ci_pipeline_id = overrides.get("ci_pipeline_id", "123")
    ctx.ci_job_id = overrides.get("ci_job_id", "456")
    ctx.hostname = overrides.get("hostname", "runner-1")
    return ctx


class TestIdGeneration:
    @patch("src.observability.metrics_scope._get_repo_identifier", return_value="repo")
    @patch("src.observability.metrics_scope._get_source_commit_sha", return_value="abc123")
    def test_same_inputs_same_slice_id(self, _sha, _repo):
        args = {
            "site_id": "docs.aspose.net",
            "content_root_id": "docs.aspose.net/words",
            "product_family_token": "words",
            "platform": "all",
            "operation_type": "content_translation",
        }
        id1 = generate_stable_work_slice_id(**args)
        id2 = generate_stable_work_slice_id(**args)
        assert id1 == id2

    @patch("src.observability.metrics_scope._get_repo_identifier", return_value="repo")
    @patch("src.observability.metrics_scope._get_source_commit_sha", return_value="abc123")
    def test_different_content_root_different_slice_id(self, _sha, _repo):
        base = {
            "site_id": "docs.aspose.net",
            "product_family_token": "words",
            "platform": "all",
            "operation_type": "content_translation",
        }
        id1 = generate_stable_work_slice_id(content_root_id="docs.aspose.net/words", **base)
        id2 = generate_stable_work_slice_id(content_root_id="docs.aspose.net/cells", **base)
        assert id1 != id2

    def test_same_attempt_same_execution_id(self):
        ctx = _mock_gitlab_ctx()
        id1 = generate_execution_attempt_id(parent_run_id="parent-001", gitlab_ctx=ctx)
        id2 = generate_execution_attempt_id(parent_run_id="parent-001", gitlab_ctx=ctx)
        assert id1 == id2

    def test_different_parent_run_different_execution_id(self):
        ctx = _mock_gitlab_ctx()
        id1 = generate_execution_attempt_id(parent_run_id="parent-001", gitlab_ctx=ctx)
        id2 = generate_execution_attempt_id(parent_run_id="parent-002", gitlab_ctx=ctx)
        assert id1 != id2

    def test_same_slice_and_attempt_same_segment_id(self):
        import uuid
        ws = uuid.uuid4()
        ea = uuid.uuid4()
        sid1 = generate_segment_run_id(ws, ea)
        sid2 = generate_segment_run_id(ws, ea)
        assert sid1 == sid2

    def test_different_attempt_different_segment_id(self):
        import uuid
        ws = uuid.uuid4()
        ea1 = uuid.uuid4()
        ea2 = uuid.uuid4()
        sid1 = generate_segment_run_id(ws, ea1)
        sid2 = generate_segment_run_id(ws, ea2)
        assert sid1 != sid2


class TestDuplicateSuppression:
    def test_first_post_allowed(self, tmp_path):
        ew = EvidenceWriter(evidence_dir=str(tmp_path / "ev"))
        assert ew.is_already_posted("seg-001") is False

    def test_second_post_blocked(self, tmp_path):
        ew = EvidenceWriter(evidence_dir=str(tmp_path / "ev"))
        ew.write_posted_marker("seg-001")
        assert ew.is_already_posted("seg-001") is True

    @patch("src.observability.metrics_scope._get_repo_identifier", return_value="repo")
    @patch("src.observability.metrics_scope._get_source_commit_sha", return_value="sha1")
    def test_new_attempt_for_same_work_is_new_segment(self, _sha, _repo):
        """Different parent_run_id -> different segment_run_id -> separate row."""
        ws = generate_stable_work_slice_id(
            site_id="docs.aspose.net",
            content_root_id="docs.aspose.net/words",
            product_family_token="words",
            platform="all",
            operation_type="content_translation",
        )
        ctx = _mock_gitlab_ctx()
        ea1 = generate_execution_attempt_id(parent_run_id="p1", gitlab_ctx=ctx)
        ea2 = generate_execution_attempt_id(parent_run_id="p2", gitlab_ctx=ctx)
        seg1 = generate_segment_run_id(ws, ea1)
        seg2 = generate_segment_run_id(ws, ea2)
        assert seg1 != seg2
