"""GitLab CI context collector with local-run fallback."""
from __future__ import annotations

import os
import socket
from dataclasses import dataclass, field


_CI_VARS = [
    "CI_PROJECT_PATH",
    "CI_PROJECT_URL",
    "CI_PIPELINE_ID",
    "CI_PIPELINE_URL",
    "CI_JOB_ID",
    "CI_JOB_NAME",
    "CI_JOB_URL",
    "CI_COMMIT_SHA",
    "CI_COMMIT_REF_NAME",
    "CI_RUNNER_DESCRIPTION",
]


@dataclass
class GitLabContext:
    is_ci: bool = False
    ci_project_path: str | None = None
    ci_project_url: str | None = None
    ci_pipeline_id: str | None = None
    ci_pipeline_url: str | None = None
    ci_job_id: str | None = None
    ci_job_name: str | None = None
    ci_job_url: str | None = None
    ci_commit_sha: str | None = None
    ci_commit_ref_name: str | None = None
    ci_runner_description: str | None = None
    hostname: str = field(default_factory=socket.gethostname)

    def to_dict(self) -> dict:
        return {
            "is_ci": self.is_ci,
            "ci_project_path": self.ci_project_path,
            "ci_project_url": self.ci_project_url,
            "ci_pipeline_id": self.ci_pipeline_id,
            "ci_pipeline_url": self.ci_pipeline_url,
            "ci_job_id": self.ci_job_id,
            "ci_job_name": self.ci_job_name,
            "ci_job_url": self.ci_job_url,
            "ci_commit_sha": self.ci_commit_sha,
            "ci_commit_ref_name": self.ci_commit_ref_name,
            "ci_runner_description": self.ci_runner_description,
            "hostname": self.hostname,
        }


def collect_gitlab_context() -> GitLabContext:
    """Collect GitLab CI context from environment variables.

    If any CI_* variable is set, treats the run as CI mode.
    Otherwise, falls back to local mode with hostname.
    """
    ctx = GitLabContext()
    found_any = False
    for var in _CI_VARS:
        val = os.environ.get(var)
        if val:
            found_any = True
            attr = var.lower()
            setattr(ctx, attr, val)
    ctx.is_ci = found_any
    return ctx
