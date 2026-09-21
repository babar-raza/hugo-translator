"""GC-01: `_git_commit_with_ref_lock_retry` must retry a git ref-lock race
(confirmed live this session: "fatal: cannot lock ref 'HEAD': is at X but
expected Y", produced when two sessions sharing one checkout commit at the
same instant) but must never mask or retry a genuinely different failure
(hook rejection, nothing to commit, merge conflict, ...).

Direct unit coverage of the new method in isolation (`CampaignRunner.__new__`
+ a mocked `subprocess.run`), matching the fixture style already used by
`TestPrimaryBackendIsDeterministic` in
test_campaign_runner_deterministic_retry_collapse.py, rather than wiring up
the full `_commit_verified_outputs` flow (a real git repo, receipts, etc.)
for a fix scoped entirely to this one retry loop.
"""
from __future__ import annotations

import subprocess
from unittest.mock import patch

from src.workers.campaign_runner import CampaignRunner


def _runner() -> CampaignRunner:
    runner = CampaignRunner.__new__(CampaignRunner)
    runner.content_repo = "/fake/content-repo"
    return runner


def _ref_lock_error() -> subprocess.CalledProcessError:
    return subprocess.CalledProcessError(
        returncode=128,
        cmd=["git", "commit", "-m", "x"],
        stderr="fatal: cannot lock ref 'HEAD': is at abc123 but expected def456\n",
    )


def _hook_rejection_error() -> subprocess.CalledProcessError:
    return subprocess.CalledProcessError(
        returncode=1,
        cmd=["git", "commit", "-m", "x"],
        stderr="pre-commit hook rejected: forbidden path\n",
    )


class TestGitCommitRefLockRetry:
    def test_succeeds_immediately_with_no_contention(self):
        runner = _runner()
        with patch("src.workers.campaign_runner.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["git", "commit"], returncode=0
            )
            runner._git_commit_with_ref_lock_retry(["title"])
        assert mock_run.call_count == 1

    def test_retries_transparently_on_ref_lock_then_succeeds(self):
        runner = _runner()
        with (
            patch("src.workers.campaign_runner.subprocess.run") as mock_run,
            patch("src.workers.campaign_runner.time.sleep") as mock_sleep,
        ):
            mock_run.side_effect = [
                _ref_lock_error(),
                subprocess.CompletedProcess(args=["git", "commit"], returncode=0),
            ]
            runner._git_commit_with_ref_lock_retry(["title"])
        assert mock_run.call_count == 2
        mock_sleep.assert_called_once()

    def test_gives_up_after_max_attempts_still_contended(self):
        runner = _runner()
        with (
            patch("src.workers.campaign_runner.subprocess.run") as mock_run,
            patch("src.workers.campaign_runner.time.sleep"),
        ):
            mock_run.side_effect = [
                _ref_lock_error(),
                _ref_lock_error(),
                _ref_lock_error(),
            ]
            try:
                runner._git_commit_with_ref_lock_retry(["title"])
                raise AssertionError("expected CalledProcessError to propagate")
            except subprocess.CalledProcessError:
                pass
        assert mock_run.call_count == CampaignRunner._GIT_REF_LOCK_MAX_ATTEMPTS

    def test_non_ref_lock_failure_propagates_immediately_without_retry(self):
        """A genuine hook rejection must fail on the FIRST attempt -- the
        retry loop must never mask or delay a real failure."""
        runner = _runner()
        with (
            patch("src.workers.campaign_runner.subprocess.run") as mock_run,
            patch("src.workers.campaign_runner.time.sleep") as mock_sleep,
        ):
            mock_run.side_effect = _hook_rejection_error()
            try:
                runner._git_commit_with_ref_lock_retry(["title"])
                raise AssertionError("expected CalledProcessError to propagate")
            except subprocess.CalledProcessError as exc:
                assert "hook rejected" in exc.stderr
        assert mock_run.call_count == 1
        mock_sleep.assert_not_called()
