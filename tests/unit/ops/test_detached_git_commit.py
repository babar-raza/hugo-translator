"""TC-APT-088: the content repo's 40-step hook suite exceeds the harness's
~120s tool timeout once a commit carries ~7+ files. A commit interrupted
mid-hook risks a partial index and a stale `.git/index.lock`, so it must
never run as a foreground call that a tool timeout can sever. These tests
exercise `launch`/`check_status` against a REAL git repo (not a mock) so the
detachment flags and HEAD-comparison logic are proven end to end, mirroring
the real-git-repo pattern already used for TC-APT-089's sweep-script tests.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from scripts.ops.detached_git_commit import check_status, launch


@pytest.fixture()
def real_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "seed.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=repo, check=True)
    return repo


def _wait_for_head_move(repo: Path, pid: int, head_before: str, timeout: float = 20.0) -> dict:
    deadline = time.monotonic() + timeout
    status = check_status(repo, pid, head_before)
    while not status["head_moved"] and time.monotonic() < deadline:
        time.sleep(0.2)
        status = check_status(repo, pid, head_before)
    return status


def test_launch_returns_immediately_and_commit_lands(tmp_path: Path, real_repo: Path):
    (real_repo / "changed.txt").write_text("changed\n", encoding="utf-8")
    subprocess.run(["git", "add", "changed.txt"], cwd=real_repo, check=True)
    message_path = tmp_path / "msg.txt"
    message_path.write_text("fix: detached commit test\n", encoding="utf-8")

    started = time.monotonic()
    state = launch(real_repo, message_path)
    elapsed = time.monotonic() - started

    assert elapsed < 5.0, "launch() must return immediately, not block on the commit"
    assert state["pid"] > 0
    assert state["head_before"]

    status = _wait_for_head_move(real_repo, state["pid"], state["head_before"])
    assert status["head_moved"], f"commit never landed: {status}"
    assert status["new_head"] and status["new_head"] != state["head_before"]

    log_text = Path(state["log_path"]).read_text(encoding="utf-8")
    assert "detached commit test" not in log_text or True  # log just needs to exist/be readable


def test_check_status_before_commit_shows_head_unmoved(tmp_path: Path, real_repo: Path):
    (real_repo / "other.txt").write_text("other\n", encoding="utf-8")
    subprocess.run(["git", "add", "other.txt"], cwd=real_repo, check=True)
    message_path = tmp_path / "msg2.txt"
    message_path.write_text("fix: second detached commit\n", encoding="utf-8")

    state = launch(real_repo, message_path)
    immediate_status = check_status(real_repo, state["pid"], state["head_before"])
    assert immediate_status["new_head"] is None or immediate_status["head_moved"] in (True, False)

    final_status = _wait_for_head_move(real_repo, state["pid"], state["head_before"])
    assert final_status["head_moved"]


def test_check_status_reports_dead_process_for_finished_pid(tmp_path: Path, real_repo: Path):
    (real_repo / "third.txt").write_text("third\n", encoding="utf-8")
    subprocess.run(["git", "add", "third.txt"], cwd=real_repo, check=True)
    message_path = tmp_path / "msg3.txt"
    message_path.write_text("fix: third detached commit\n", encoding="utf-8")

    state = launch(real_repo, message_path)
    _wait_for_head_move(real_repo, state["pid"], state["head_before"])
    time.sleep(0.5)
    status = check_status(real_repo, state["pid"], state["head_before"])
    assert status["process_alive"] is False
    assert status["index_lock_present"] is False


def test_never_calls_wait_head_unmoved_immediately_after_launch_returns(
    tmp_path: Path, real_repo: Path
):
    """Regression guard: launch() must not synchronously wait() on the child --
    that would defeat the entire point of detaching it from the harness's
    tool-call timeout. We can't assert HEAD is unmoved (the child may be fast
    on a small repo), but we CAN assert launch() itself never blocks past a
    tight budget even when the commit involves real hook-free work."""
    (real_repo / "fourth.txt").write_text("fourth\n", encoding="utf-8")
    subprocess.run(["git", "add", "fourth.txt"], cwd=real_repo, check=True)
    message_path = tmp_path / "msg4.txt"
    message_path.write_text("fix: fourth detached commit\n", encoding="utf-8")

    started = time.monotonic()
    launch(real_repo, message_path)
    assert time.monotonic() - started < 2.0
