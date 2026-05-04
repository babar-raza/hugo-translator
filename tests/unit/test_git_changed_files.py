"""Tests for git_changed_files() utility (TC-03 / GT-AUDIT-02)."""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.utils.file_filters import git_changed_files


class TestGitChangedFiles:
    def test_returns_set_of_absolute_paths(self, tmp_path):
        """On success, returns a set of resolved absolute Path objects."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        mock_rev_parse = MagicMock(returncode=0, stdout=str(repo_root) + "\n", stderr="")
        mock_diff = MagicMock(
            returncode=0,
            stdout="file_a.md\nsubdir/file_b.md\n",
            stderr="",
        )

        with patch("subprocess.run", side_effect=[mock_rev_parse, mock_diff]):
            result = git_changed_files(repo_root, "abc123")

        assert result is not None
        assert isinstance(result, set)
        assert (repo_root / "file_a.md").resolve() in result
        assert (repo_root / "subdir" / "file_b.md").resolve() in result
        assert len(result) == 2

    def test_returns_none_on_rev_parse_failure(self, tmp_path):
        """If git rev-parse fails, returns None (no filter)."""
        mock_fail = MagicMock(returncode=128, stdout="", stderr="not a git repo")
        with patch("subprocess.run", return_value=mock_fail):
            assert git_changed_files(tmp_path, "abc123") is None

    def test_returns_none_on_diff_failure(self, tmp_path):
        """If git diff fails, returns None."""
        mock_rev = MagicMock(returncode=0, stdout=str(tmp_path) + "\n", stderr="")
        mock_diff = MagicMock(returncode=1, stdout="", stderr="bad sha")
        with patch("subprocess.run", side_effect=[mock_rev, mock_diff]):
            assert git_changed_files(tmp_path, "bad_sha") is None

    def test_returns_none_on_timeout(self, tmp_path):
        """Timeout returns None gracefully."""
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 30)):
            assert git_changed_files(tmp_path, "abc123") is None

    def test_returns_none_when_git_not_found(self, tmp_path):
        """Missing git binary returns None."""
        with patch("subprocess.run", side_effect=FileNotFoundError("git")):
            assert git_changed_files(tmp_path, "abc123") is None

    def test_empty_diff_returns_empty_set(self, tmp_path):
        """No changed files returns an empty set (not None)."""
        mock_rev = MagicMock(returncode=0, stdout=str(tmp_path) + "\n", stderr="")
        mock_diff = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", side_effect=[mock_rev, mock_diff]):
            result = git_changed_files(tmp_path, "abc123")
            assert result is not None
            assert len(result) == 0
