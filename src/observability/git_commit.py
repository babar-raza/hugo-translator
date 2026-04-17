"""
Git commit operations for auto-committing translation outputs (GIT-COMMIT-01).

Provides functionality to stage, commit, and push translation results
to git repositories with configurable commit messages and co-authoring.

Key Features:
- Auto-detect git repository from output paths
- Stage only specific translation output files (not git add -A)
- Enhanced commit messages with product/section detection and quality metrics
- Co-author trailer for audit trail
- Always push after commit
- Graceful degradation - never fails translation

Usage:
    from src.observability.git_commit import GitCommitter, GitCommitConfig

    config = GitCommitConfig(
        commit_template="chore: translate {file_count} files to {languages}",
        co_author_email="hugo-translator@aspose.net",
    )
    committer = GitCommitter(config)
    result = committer.commit_translation_outputs(
        output_files=[Path("/repo/de/file.md")],
        site_id="example.com",
        target_langs=["de", "fr"],
        run_id="abc123",
        translation_result=dir_result,  # Optional for enhanced messages
        model_id="facebook/nllb-200-distilled-600M",  # Optional
        tm_stats={"hit_rate": 0.78},  # Optional
    )
"""
import logging
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from ..translation_engine.models import ValidationDecision
from .commit_message_generator import CommitMessageGenerator
from .git_context import find_git_root, get_git_branch, get_git_repo

if TYPE_CHECKING:
    from src.translation_engine.models import DirectoryResult

logger = logging.getLogger(__name__)

# Constants
DEFAULT_CO_AUTHOR_EMAIL = "hugo-translator@aspose.net"
DEFAULT_CO_AUTHOR_NAME = "Hugo Translator"
DEFAULT_COMMIT_TEMPLATE = "chore: translate {file_count} files to {languages}"


@dataclass
class GitCommitConfig:
    """Configuration for git commit behavior."""

    enabled: bool = True
    auto_push: bool = True
    commit_template: str = DEFAULT_COMMIT_TEMPLATE
    co_author_email: str = DEFAULT_CO_AUTHOR_EMAIL
    co_author_name: str = DEFAULT_CO_AUTHOR_NAME
    timeout_seconds: int = 60
    block_signals: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> "GitCommitConfig":
        """Create config from dictionary (e.g., from YAML)."""
        return cls(
            enabled=data.get("enabled", True),
            auto_push=data.get("auto_push", True),
            commit_template=data.get("commit_template", DEFAULT_COMMIT_TEMPLATE),
            co_author_email=data.get("co_author_email", DEFAULT_CO_AUTHOR_EMAIL),
            co_author_name=data.get("co_author_name", DEFAULT_CO_AUTHOR_NAME),
            timeout_seconds=data.get("timeout_seconds", 60),
            block_signals=data.get("block_signals", False),
        )


@dataclass
class GitCommitResult:
    """Result of git commit operation."""

    success: bool
    commit_hash: str | None = None
    commit_hash_short: str | None = None
    remote_url: str | None = None
    branch: str | None = None
    files_committed: int = 0
    push_success: bool = False
    error: str | None = None
    commit_author: str | None = None  # Git commit author (e.g., "Name <email>")
    commit_timestamp: str | None = None  # ISO timestamp of commit


class GitCommitter:
    """
    Handles git staging, committing, and pushing of translation outputs.

    Key design decisions:
    - Uses subprocess for git operations (consistent with git_context.py)
    - Only stages specific files (not git add -A) to avoid unrelated changes
    - 60-second timeout on all git operations
    - Graceful degradation: logs warnings but doesn't fail translation
    """

    def __init__(self, config: GitCommitConfig):
        """Initialize GitCommitter with configuration.

        Args:
            config: GitCommitConfig with commit settings
        """
        self.config = config
        self._timeout = config.timeout_seconds
        self._last_error: str | None = None  # Track last error for better reporting

    def is_git_repo(self, path: Path) -> bool:
        """Check if path is within a git repository.

        Args:
            path: Path to check

        Returns:
            True if path is in a git repo, False otherwise
        """
        return find_git_root(path) is not None

    def _recover_stale_index_lock(self, git_root: Path) -> None:
        """Remove stale .git/index.lock if no git process holds it.

        External tools (SEO automation, editors) can leave behind a stale
        index.lock if they crash or time out. This blocks ALL subsequent
        git add/commit/push operations until manually deleted.

        Safety: only removes the lock if it's older than 60 seconds.
        Note: git status is read-only and succeeds even with a stale lock,
        so we cannot use it to test if the lock is blocking. The age check
        alone is sufficient — any legitimate git operation finishes in <60s.
        """
        lock_file = git_root / ".git" / "index.lock"
        if not lock_file.exists():
            return

        try:
            lock_age = time.time() - lock_file.stat().st_mtime
            if lock_age < 60:
                logger.info(f"index.lock exists but is fresh ({lock_age:.0f}s old), leaving it")
                return

            lock_file.unlink()
            logger.warning(
                f"Removed stale .git/index.lock ({lock_age:.0f}s old) from {git_root}. "
                f"This was likely left by a crashed git process or external tool."
            )
        except OSError as e:
            logger.warning(f"Could not remove stale index.lock: {e}")

    def commit_translation_outputs(
        self,
        output_files: list[Path],
        site_id: str,
        target_langs: list[str],
        run_id: str,
        translation_result: Optional["DirectoryResult"] = None,
        model_id: str | None = None,
        tm_stats: dict | None = None,
    ) -> GitCommitResult:
        """
        Stage, commit, and push translation output files.

        Args:
            output_files: List of output file paths to commit
            site_id: Site identifier for commit message
            target_langs: Languages translated (for commit message)
            run_id: Translation run ID for tracking
            translation_result: Optional DirectoryResult for quality metrics
            model_id: Optional model identifier for commit message
            tm_stats: Optional TM statistics for commit message

        Returns:
            GitCommitResult with commit details or error
        """
        if not output_files:
            return GitCommitResult(success=False, error="No files to commit")

        # Debug: Log output files being committed
        logger.debug(f"Attempting to commit {len(output_files)} files")
        logger.debug(f"First output file: {output_files[0]}")
        logger.debug(f"First output file type: {type(output_files[0])}")
        logger.debug(f"First output file exists: {output_files[0].exists() if hasattr(output_files[0], 'exists') else 'N/A'}")

        # Find git root from first output file
        git_root = find_git_root(output_files[0])
        logger.debug(f"find_git_root returned: {git_root}")

        if git_root is None:
            logger.error(f"Failed to find git root from: {output_files[0]}")
            logger.error(f"Output file absolute path: {Path(output_files[0]).resolve() if output_files[0] else 'None'}")
            return GitCommitResult(
                success=False, error="Output directory is not a git repository"
            )

        # Pre-check: recover from stale index.lock
        self._recover_stale_index_lock(git_root)

        try:
            # Step 1: Stage specific files
            staged_count = self._stage_files(output_files, git_root)
            if staged_count == 0:
                return GitCommitResult(
                    success=False,
                    error="No files staged (all unchanged or ignored)",
                )

            # Step 2: Build commit message (use staged_count for accuracy)
            message = self._build_commit_message(
                output_files=output_files,
                file_count=staged_count,
                languages=target_langs,
                site_id=site_id,
                run_id=run_id,
                translation_result=translation_result,
                model_id=model_id,
                tm_stats=tm_stats,
            )

            # Step 3: Create commit with co-author
            commit_hash = self._create_commit(message, git_root)
            if not commit_hash:
                # Use detailed error message from _create_commit
                error_msg = self._last_error or "Commit failed (unknown reason)"
                return GitCommitResult(success=False, error=error_msg)

            # Get metadata
            remote_url = get_git_repo(git_root)
            branch = get_git_branch(git_root)

            # Get commit author and timestamp for telemetry association
            commit_author = self._get_commit_author(git_root)
            commit_timestamp = self._get_commit_timestamp(git_root)

            result = GitCommitResult(
                success=True,
                commit_hash=commit_hash,
                commit_hash_short=commit_hash[:7] if commit_hash else None,
                remote_url=remote_url,
                branch=branch,
                files_committed=staged_count,
                commit_author=commit_author,
                commit_timestamp=commit_timestamp,
            )

            # Step 4: Push if configured
            if self.config.auto_push:
                result.push_success = self._push(git_root, branch)
                if not result.push_success:
                    logger.warning(
                        f"Push failed for commit {commit_hash[:7]}. "
                        "Changes are committed locally."
                    )

            return result

        except Exception as e:
            logger.error(f"Git commit operation failed: {e}")
            return GitCommitResult(success=False, error=str(e))

    def _stage_files(self, files: list[Path], git_root: Path) -> int:
        """
        Stage specific files for commit.

        Args:
            files: List of file paths to stage
            git_root: Git repository root

        Returns:
            Number of files staged (may be less than input if some unchanged)
        """
        for file_path in files:
            if not file_path.exists():
                logger.warning(f"Skipping non-existent file: {file_path}")
                continue

            try:
                # Use relative path from git root
                try:
                    rel_path = file_path.relative_to(git_root)
                except ValueError:
                    logger.warning(f"File not under git root: {file_path}")
                    continue

                result = subprocess.run(
                    ["git", "add", "--", str(rel_path)],
                    cwd=str(git_root),
                    capture_output=True,
                    text=True,
                    timeout=self._timeout,
                )
                if result.returncode != 0:
                    logger.warning(f"Failed to stage {file_path}: {result.stderr}")
            except subprocess.TimeoutExpired:
                logger.warning(f"Timeout staging {file_path}")

        # Count files actually staged (git add on unchanged file returns 0 but stages nothing)
        try:
            diff_result = subprocess.run(
                ["git", "diff", "--cached", "--name-only"],
                cwd=str(git_root),
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
            staged = len([l for l in diff_result.stdout.splitlines() if l.strip()])
        except Exception:
            staged = len(files)  # Fallback to input count if query fails

        return staged

    def _build_commit_message(
        self,
        output_files: list[Path],
        file_count: int,
        languages: list[str],
        site_id: str,
        run_id: str,
        translation_result: Optional["DirectoryResult"] = None,
        model_id: str | None = None,
        tm_stats: dict | None = None,
    ) -> str:
        """Build enhanced commit message with detailed information.

        Uses CommitMessageGenerator to create structured commit messages with:
        - Product/section detection from file paths
        - Quality metrics (TM hit rates, validation results)
        - Model information
        - Detailed body with path patterns

        Falls back to simple template if generator fails.

        Args:
            output_files: List of output file paths
            file_count: Number of files being committed
            languages: List of target languages
            site_id: Site identifier
            run_id: Translation run ID
            translation_result: Optional DirectoryResult for quality metrics
            model_id: Optional model identifier
            tm_stats: Optional TM statistics

        Returns:
            Formatted commit message with co-author trailer
        """
        try:
            # Load site profile to get display_name
            site_profile = None
            try:
                from src.utils.config_loader import ConfigService
                config_service = ConfigService("./config")
                site_profile_obj = config_service.get_site_profile(site_id)

                # Convert to dict for easier access
                site_profile = {
                    "display_name": site_profile_obj.display_name if hasattr(site_profile_obj, "display_name") else None,
                }
            except Exception as e:
                logger.warning(f"Failed to load site profile for {site_id}: {e}")

            # Use enhanced commit message generator (pass file_count = actual staged count)
            generator = CommitMessageGenerator()
            subject, body = generator.generate(
                output_files=output_files,
                target_langs=languages,
                site_id=site_id,
                run_id=run_id,
                site_profile=site_profile,
                translation_result=translation_result,
                model_id=model_id,
                tm_stats=tm_stats,
                file_count=file_count,
            )

            # Combine subject and body
            message = f"{subject}\n\n{body}"

            logger.debug(f"Generated enhanced commit message: {subject}")

        except Exception as e:
            # Fallback to simple template if generator fails
            logger.warning(f"Commit message generator failed, using simple template: {e}")

            langs_str = ", ".join(sorted(languages))
            message = self.config.commit_template.format(
                file_count=file_count,
                languages=langs_str,
                site_id=site_id,
                run_id=run_id,
            )

        # Add co-author trailer
        co_author = (
            f"\n\nCo-authored-by: {self.config.co_author_name} "
            f"<{self.config.co_author_email}>"
        )

        return message + co_author

    def _create_commit(self, message: str, git_root: Path) -> str | None:
        """Create commit and return commit hash.

        Args:
            message: Commit message
            git_root: Git repository root

        Returns:
            Full commit SHA if successful, None otherwise
        """
        self._last_error = None  # Clear previous error

        try:
            result = subprocess.run(
                ["git", "commit", "-m", message],
                cwd=str(git_root),
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )

            if result.returncode != 0:
                # Check if nothing to commit (not an error)
                if "nothing to commit" in result.stdout.lower():
                    logger.info("Nothing to commit (files unchanged)")
                    self._last_error = "Nothing to commit (files unchanged)"
                    return None

                # Store detailed error including both stdout and stderr
                error_detail = (result.stderr or result.stdout).strip()
                self._last_error = f"git commit failed (exit {result.returncode}): {error_detail}"
                logger.error(f"Commit failed: {error_detail}")
                return None

            # Get commit hash
            hash_result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(git_root),
                capture_output=True,
                text=True,
                timeout=5,
            )

            if hash_result.returncode == 0:
                return hash_result.stdout.strip()

            self._last_error = "Failed to get commit hash after successful commit"
            return None

        except subprocess.TimeoutExpired:
            self._last_error = "Commit operation timed out (60s)"
            logger.error(self._last_error)
            return None
        except Exception as e:
            self._last_error = f"Unexpected error during commit: {str(e)}"
            logger.error(self._last_error)
            return None

    def _get_commit_author(self, git_root: Path) -> str | None:
        """
        Get the author of the most recent commit.

        Args:
            git_root: Git repository root

        Returns:
            Commit author in format "Name <email>" or None if failed
        """
        try:
            result = subprocess.run(
                ["git", "log", "-1", "--format=%an <%ae>", "HEAD"],
                cwd=str(git_root),
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode == 0:
                return result.stdout.strip()

            logger.warning("Failed to get commit author")
            return None

        except Exception as e:
            logger.warning(f"Error getting commit author: {e}")
            return None

    def _get_commit_timestamp(self, git_root: Path) -> str | None:
        """
        Get the timestamp of the most recent commit in ISO format.

        Args:
            git_root: Git repository root

        Returns:
            ISO timestamp or None if failed
        """
        try:
            result = subprocess.run(
                ["git", "log", "-1", "--format=%aI", "HEAD"],
                cwd=str(git_root),
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode == 0:
                return result.stdout.strip()

            logger.warning("Failed to get commit timestamp")
            return None

        except Exception as e:
            logger.warning(f"Error getting commit timestamp: {e}")
            return None

    def _push(self, git_root: Path, branch: str | None) -> bool:
        """Push to remote origin.

        Args:
            git_root: Git repository root
            branch: Branch name to push

        Returns:
            True if push succeeded, False otherwise
        """
        try:
            cmd = ["git", "push"]
            if branch:
                cmd.extend(["origin", branch])

            result = subprocess.run(
                cmd,
                cwd=str(git_root),
                capture_output=True,
                text=True,
                timeout=self._timeout * 2,  # Double timeout for network
            )

            if result.returncode != 0:
                logger.warning(f"Push failed: {result.stderr}")
                return False

            logger.info(f"Pushed to origin/{branch or 'default'}")
            return True

        except subprocess.TimeoutExpired:
            logger.warning("Push operation timed out")
            return False


def _is_file_modified_in_git(file_path: Path) -> bool:
    """
    Check if file is modified in git working directory.

    Returns True if file shows as modified in git status.
    Used to catch cases where files marked as "skipped" were actually modified.
    """
    try:
        # Import here to avoid circular dependencies
        import subprocess

        # Run git status for specific file
        result = subprocess.run(
            ["git", "status", "--porcelain", str(file_path)],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(file_path.parent)
        )

        # Modified files show as " M " or "M  " or "MM"
        # Any output means file is modified/staged/untracked
        return bool(result.stdout.strip())

    except Exception as e:
        logger.debug(f"Git status check failed for {file_path}: {e}")
        return False


def collect_output_files(result: "DirectoryResult") -> list[Path]:
    """
    Collect output file paths that were actually written during this translation run.

    Only includes files for languages that were not skipped (i.e., languages that
    were actually translated or updated during this run).

    Args:
        result: DirectoryResult from translate_directory

    Returns:
        List of output file paths that were written (modified or created) in this run
    """
    files = []

    # Diagnostic counters
    total_results = len(result.file_results) if hasattr(result, 'file_results') else 0
    successful_results = 0
    total_outputs = 0
    skipped_outputs = 0
    nonexistent_outputs = 0

    for file_result in result.file_results:
        if file_result.success:
            successful_results += 1
            # Only include files for languages that were NOT skipped
            # skipped_langs contains languages where output already existed and was unchanged
            for lang, output_path in file_result.outputs.items():
                total_outputs += 1

                # Check existence and skip status
                exists = output_path.exists()
                is_skipped = lang in file_result.skipped_langs

                # Check if validation passed for this language.
                # None means validation was not run (allowed); ACCEPT means it passed.
                # Only RETRY/REJECT should block the commit.
                validation_passed = (
                    lang not in file_result.errors
                    and (
                        file_result.validation_decision is None
                        or file_result.validation_decision == ValidationDecision.ACCEPT
                    )
                )

                if exists and not is_skipped and validation_passed:
                    files.append(output_path)
                elif exists and is_skipped:
                    # CRITICAL FIX: Check if skipped file was actually modified
                    # This catches the write-after-skip bug where files get overwritten
                    # despite being marked as skipped
                    if _is_file_modified_in_git(output_path):
                        logger.warning(
                            f"[collect_output_files] File marked as skipped but IS modified in git: {output_path}. "
                            f"Collecting for commit to capture unexpected changes (possible corruption)."
                        )
                        files.append(output_path)
                    else:
                        skipped_outputs += 1
                        logger.debug(f"[collect_output_files] Skipped lang {lang}: {output_path}")
                else:
                    skipped_outputs += 1
                    if not exists:
                        nonexistent_outputs += 1
                        logger.warning(f"[collect_output_files] File doesn't exist: {output_path}")

    # Log diagnostic summary
    logger.info("[collect_output_files] Collection summary:")
    logger.info(f"  - Total file_results: {total_results}")
    logger.info(f"  - Successful results: {successful_results}")
    logger.info(f"  - Total outputs: {total_outputs}")
    logger.info(f"  - Files collected for commit: {len(files)}")
    logger.info(f"  - Skipped outputs: {skipped_outputs}")
    logger.info(f"  - Nonexistent outputs: {nonexistent_outputs}")

    return files
