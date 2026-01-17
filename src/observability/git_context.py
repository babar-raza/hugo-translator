"""
Git and environment context capture for telemetry (TEL-05-C, TFR-03).

Provides functions to capture git repository info and host context
for correlation in telemetry. All functions gracefully degrade if
git is unavailable or not in a repository.

TFR-03: Functions now accept optional `cwd` parameter to extract
git context from a specific directory (e.g., input content repo)
rather than defaulting to the translator tool's repo.

Logging: WARN level messages are emitted when git commands fail,
to aid debugging when git context is unexpectedly empty.
"""
import logging
import socket
import subprocess
from pathlib import Path
from typing import Dict, Optional, Union

logger = logging.getLogger(__name__)


def find_git_root(path: Union[str, Path]) -> Optional[Path]:
    """
    Find the git repository root containing the given path (TFR-03).

    Args:
        path: File or directory path to start searching from.

    Returns:
        Path to git repository root, or None if not in a git repo.
    """
    logger.debug(f"find_git_root called with: {path} (type: {type(path)})")
    try:
        path = Path(path).resolve()
        logger.debug(f"Resolved path: {path}")
        logger.debug(f"Path exists: {path.exists()}")
        logger.debug(f"Path is file: {path.is_file()}")

        # If path is a file, start from its parent directory
        if path.is_file():
            path = path.parent
            logger.debug(f"Using parent directory: {path}")

        logger.debug(f"Running git rev-parse in cwd: {path}")
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(path),
        )
        logger.debug(f"Git command return code: {result.returncode}")
        logger.debug(f"Git command stdout: {result.stdout.strip()}")
        logger.debug(f"Git command stderr: {result.stderr.strip()}")

        if result.returncode == 0 and result.stdout.strip():
            git_root = Path(result.stdout.strip())
            logger.debug(f"Found git root: {git_root}")
            return git_root
        else:
            logger.debug(f"Git command failed or returned empty output")
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logger.debug(f"find_git_root exception for {path}: {e}")

    logger.debug(f"find_git_root returning None for path: {path}")
    return None


def get_git_repo(cwd: Optional[Union[str, Path]] = None) -> Optional[str]:
    """
    Get the git remote origin URL or local repo path (TFR-03).

    Args:
        cwd: Optional working directory. If provided, extracts git info from
             that directory's repo instead of the current working directory.

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
            cwd=str(cwd) if cwd else None,
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


def get_git_branch(cwd: Optional[Union[str, Path]] = None) -> Optional[str]:
    """
    Get the current git branch name (TFR-03).

    Args:
        cwd: Optional working directory. If provided, extracts git info from
             that directory's repo instead of the current working directory.

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
            cwd=str(cwd) if cwd else None,
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


def get_git_run_tag(cwd: Optional[Union[str, Path]] = None) -> Optional[str]:
    """
    Get the short SHA of HEAD commit (TFR-03).

    Args:
        cwd: Optional working directory. If provided, extracts git info from
             that directory's repo instead of the current working directory.

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
            cwd=str(cwd) if cwd else None,
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


def get_git_context(input_path: Optional[Union[str, Path]] = None) -> Dict[str, Optional[str]]:
    """
    Get all git and environment context in a single dict (TFR-03).

    Args:
        input_path: Optional file/directory path. If provided, extracts git context
                    from the repository containing that path (e.g., input content repo)
                    instead of the current working directory.

    Returns:
        Dict with keys: git_repo, git_branch, git_run_tag, host.
        Values are None if not available (except host which defaults to "unknown").
    """
    # TFR-03: If input_path provided, find its git repo root and use that
    cwd = None
    if input_path:
        git_root = find_git_root(input_path)
        if git_root:
            cwd = git_root
            logger.debug(f"Using input repo for git context: {git_root}")

    return {
        "git_repo": get_git_repo(cwd),
        "git_branch": get_git_branch(cwd),
        "git_run_tag": get_git_run_tag(cwd),
        "host": get_host(),
    }
