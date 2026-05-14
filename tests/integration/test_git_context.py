"""
Tests for git_context module (TEL-05-C).

Tests git and environment context capture with mocked subprocess calls.
"""
import subprocess
from unittest.mock import MagicMock, patch

from src.observability.git_context import (
    get_git_branch,
    get_git_context,
    get_git_repo,
    get_git_run_tag,
    get_host,
)


class TestGetGitRepo:
    """Tests for get_git_repo()."""

    def test_returns_remote_url_when_available(self):
        """Happy path: returns remote origin URL."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "https://github.com/user/repo.git\n"

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = get_git_repo()

        assert result == "https://github.com/user/repo.git"
        mock_run.assert_called_once_with(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=None,
        )

    def test_returns_none_when_not_in_repo(self):
        """Returns None when not in a git repository."""
        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stdout = ""

        with patch("subprocess.run", return_value=mock_result):
            result = get_git_repo()

        assert result is None

    def test_returns_none_when_git_not_installed(self):
        """Returns None when git command not found."""
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = get_git_repo()

        assert result is None

    def test_returns_none_on_timeout(self):
        """Returns None when git command times out."""
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 5)):
            result = get_git_repo()

        assert result is None


class TestGetGitBranch:
    """Tests for get_git_branch()."""

    def test_returns_branch_name_when_available(self):
        """Happy path: returns current branch name."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "main\n"

        with patch("subprocess.run", return_value=mock_result):
            result = get_git_branch()

        assert result == "main"

    def test_returns_feature_branch_name(self):
        """Returns feature branch name with slashes."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "feature/TEL-05-telemetry\n"

        with patch("subprocess.run", return_value=mock_result):
            result = get_git_branch()

        assert result == "feature/TEL-05-telemetry"

    def test_returns_none_when_detached_head(self):
        """Returns None when in detached HEAD state (empty output)."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""

        with patch("subprocess.run", return_value=mock_result):
            result = get_git_branch()

        assert result is None

    def test_returns_none_when_not_in_repo(self):
        """Returns None when not in a git repository."""
        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stdout = ""

        with patch("subprocess.run", return_value=mock_result):
            result = get_git_branch()

        assert result is None


class TestGetGitRunTag:
    """Tests for get_git_run_tag()."""

    def test_returns_short_sha_when_available(self):
        """Happy path: returns short commit SHA."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "abc1234\n"

        with patch("subprocess.run", return_value=mock_result):
            result = get_git_run_tag()

        assert result == "abc1234"

    def test_returns_none_when_not_in_repo(self):
        """Returns None when not in a git repository."""
        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stdout = ""

        with patch("subprocess.run", return_value=mock_result):
            result = get_git_run_tag()

        assert result is None


class TestGetHost:
    """Tests for get_host()."""

    def test_returns_hostname(self):
        """Returns system hostname."""
        with patch("socket.gethostname", return_value="my-workstation"):
            result = get_host()

        assert result == "my-workstation"

    def test_returns_unknown_on_error(self):
        """Returns 'unknown' when hostname cannot be determined."""
        with patch("socket.gethostname", side_effect=Exception("socket error")):
            result = get_host()

        assert result == "unknown"


class TestGetGitContext:
    """Tests for get_git_context() combined function."""

    def test_returns_all_fields_when_in_repo(self):
        """Returns complete context dict when in git repo."""
        mock_results = {
            ("git", "remote", "get-url", "origin"): ("https://github.com/user/repo.git\n", 0),
            ("git", "branch", "--show-current"): ("main\n", 0),
            ("git", "rev-parse", "--short", "HEAD"): ("abc1234\n", 0),
        }

        def mock_run(cmd, **kwargs):
            key = tuple(cmd)
            stdout, returncode = mock_results.get(key, ("", 128))
            result = MagicMock()
            result.stdout = stdout
            result.returncode = returncode
            return result

        with patch("subprocess.run", side_effect=mock_run):
            with patch("socket.gethostname", return_value="test-host"):
                result = get_git_context()

        assert result == {
            "git_repo": "https://github.com/user/repo.git",
            "git_branch": "main",
            "git_run_tag": "abc1234",
            "host": "test-host",
        }

    def test_returns_partial_context_when_not_in_repo(self):
        """Returns dict with None values when not in git repo."""
        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stdout = ""

        with patch("subprocess.run", return_value=mock_result):
            with patch("socket.gethostname", return_value="test-host"):
                result = get_git_context()

        assert result == {
            "git_repo": None,
            "git_branch": None,
            "git_run_tag": None,
            "host": "test-host",
        }

    def test_host_always_has_value(self):
        """Host field always has a value (never None)."""
        with patch("subprocess.run", side_effect=FileNotFoundError):
            with patch("socket.gethostname", return_value="fallback-host"):
                result = get_git_context()

        assert result["host"] == "fallback-host"
        assert result["host"] is not None
