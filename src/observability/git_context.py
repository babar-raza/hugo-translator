"""
Git and environment context capture for telemetry (TEL-05-C).

Provides functions to capture git repository info and host context
for correlation in telemetry. All functions gracefully degrade if
git is unavailable or not in a repository.

Logging: WARN level messages are emitted when git commands fail,
to aid debugging when git context is unexpectedly empty.
"""
import logging
import socket
import subprocess
from typing import Dict, Optional

logger = logging.getLogger(__name__)


def get_git_repo() -> Optional[str]:
    """
    Get the git remote origin URL or local repo path.

    Returns:
        Remote URL if available, otherwise None.
        Gracefully returns None if not in a git repo or git unavailable.
    """
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        else:
            logger.debug(f"git remote get-url origin returned: rc={result.returncode}, stderr={result.stderr.strip()}")
    except subprocess.TimeoutExpired:
        logger.warning("git remote get-url origin timed out")
    except FileNotFoundError:
        logger.warning("git executable not found in PATH")
    except OSError as e:
        logger.warning(f"git remote get-url origin failed: {e}")
    return None


def get_git_branch() -> Optional[str]:
    """
    Get the current git branch name.

    Returns:
        Branch name if available, otherwise None.
        Gracefully returns None if not in a git repo or git unavailable.
    """
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        else:
            logger.debug(f"git branch --show-current returned: rc={result.returncode}, stderr={result.stderr.strip()}")
    except subprocess.TimeoutExpired:
        logger.warning("git branch --show-current timed out")
    except FileNotFoundError:
        logger.warning("git executable not found in PATH")
    except OSError as e:
        logger.warning(f"git branch --show-current failed: {e}")
    return None


def get_git_run_tag() -> Optional[str]:
    """
    Get the short SHA of HEAD commit.

    Returns:
        Short commit SHA if available, otherwise None.
        Gracefully returns None if not in a git repo or git unavailable.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        else:
            logger.debug(f"git rev-parse --short HEAD returned: rc={result.returncode}, stderr={result.stderr.strip()}")
    except subprocess.TimeoutExpired:
        logger.warning("git rev-parse --short HEAD timed out")
    except FileNotFoundError:
        logger.warning("git executable not found in PATH")
    except OSError as e:
        logger.warning(f"git rev-parse --short HEAD failed: {e}")
    return None


def get_host() -> str:
    """
    Get the system hostname.

    Returns:
        Hostname string. Returns "unknown" if hostname cannot be determined.
    """
    try:
        return socket.gethostname()
    except Exception:
        return "unknown"


def get_git_context() -> Dict[str, Optional[str]]:
    """
    Get all git and environment context in a single dict.

    Returns:
        Dict with keys: git_repo, git_branch, git_run_tag, host.
        Values are None if not available (except host which defaults to "unknown").
    """
    return {
        "git_repo": get_git_repo(),
        "git_branch": get_git_branch(),
        "git_run_tag": get_git_run_tag(),
        "host": get_host(),
    }
