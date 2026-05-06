"""Tests for GitLab context collection."""
import os

import pytest

from src.observability.gitlab_context import GitLabContext, collect_gitlab_context


class TestGitLabContext:
    def test_local_mode_no_ci_vars(self, monkeypatch):
        # Remove any CI vars
        for var in ["CI_PIPELINE_ID", "CI_JOB_ID", "CI_JOB_NAME", "CI_COMMIT_SHA",
                     "CI_PROJECT_PATH", "CI_PROJECT_URL", "CI_PIPELINE_URL",
                     "CI_JOB_URL", "CI_COMMIT_REF_NAME", "CI_RUNNER_DESCRIPTION"]:
            monkeypatch.delenv(var, raising=False)
        ctx = collect_gitlab_context()
        assert ctx.is_ci is False
        assert ctx.hostname  # should be populated

    def test_ci_mode_with_vars(self, monkeypatch):
        monkeypatch.setenv("CI_PIPELINE_ID", "12345")
        monkeypatch.setenv("CI_JOB_ID", "67890")
        monkeypatch.setenv("CI_JOB_NAME", "translate")
        ctx = collect_gitlab_context()
        assert ctx.is_ci is True
        assert ctx.ci_pipeline_id == "12345"
        assert ctx.ci_job_id == "67890"
        assert ctx.ci_job_name == "translate"

    def test_partial_ci_vars(self, monkeypatch):
        for var in ["CI_PIPELINE_ID", "CI_JOB_ID", "CI_JOB_NAME", "CI_COMMIT_SHA",
                     "CI_PROJECT_PATH", "CI_PROJECT_URL", "CI_PIPELINE_URL",
                     "CI_JOB_URL", "CI_COMMIT_REF_NAME", "CI_RUNNER_DESCRIPTION"]:
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("CI_PIPELINE_ID", "99")
        ctx = collect_gitlab_context()
        assert ctx.is_ci is True
        assert ctx.ci_pipeline_id == "99"
        assert ctx.ci_job_id is None

    def test_hostname_always_populated(self):
        ctx = collect_gitlab_context()
        assert ctx.hostname is not None
        assert len(ctx.hostname) > 0

    def test_to_dict(self, monkeypatch):
        for var in ["CI_PIPELINE_ID", "CI_JOB_ID", "CI_JOB_NAME", "CI_COMMIT_SHA",
                     "CI_PROJECT_PATH", "CI_PROJECT_URL", "CI_PIPELINE_URL",
                     "CI_JOB_URL", "CI_COMMIT_REF_NAME", "CI_RUNNER_DESCRIPTION"]:
            monkeypatch.delenv(var, raising=False)
        ctx = collect_gitlab_context()
        d = ctx.to_dict()
        assert "is_ci" in d
        assert "hostname" in d
        assert "ci_pipeline_id" in d
