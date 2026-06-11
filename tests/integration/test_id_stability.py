"""Integration test: stable_work_slice_id is identical across path styles."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.observability.metrics_scope import (
    derive_content_root_id,
    generate_stable_work_slice_id,
)


class TestIdStability:
    def test_content_root_id_same_from_windows_and_linux_paths(self):
        win_path = "${ASPOSE_NET_CONTENT}\\docs.aspose.net\\words"
        linux_path = "${ASPOSE_NET_CONTENT}/docs.aspose.net/words"
        assert derive_content_root_id(win_path) == derive_content_root_id(linux_path)

    @patch("src.observability.metrics_scope._get_repo_identifier", return_value="repo")
    @patch("src.observability.metrics_scope._get_source_commit_sha", return_value="abc123")
    def test_work_slice_id_stable_across_path_formats(self, _sha, _repo):
        cid = derive_content_root_id("${VAR}/docs.aspose.net/words")
        id1 = generate_stable_work_slice_id(
            site_id="docs.aspose.net",
            content_root_id=cid,
            product_family_token="words",
            platform="all",
            operation_type="content_translation",
        )
        cid2 = derive_content_root_id("${VAR}\\docs.aspose.net\\words")
        id2 = generate_stable_work_slice_id(
            site_id="docs.aspose.net",
            content_root_id=cid2,
            product_family_token="words",
            platform="all",
            operation_type="content_translation",
        )
        assert id1 == id2
