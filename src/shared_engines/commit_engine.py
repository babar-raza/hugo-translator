"""
CommitEngine - Unified git commit automation.

Wraps existing GitCommitter to provide consistent interface for
automated git commits of translation outputs.
"""

import logging
from pathlib import Path
from typing import Any

from src.observability.git_commit import (
    GitCommitConfig,
    GitCommitResult,
    GitCommitter,
    collect_output_files,
)

logger = logging.getLogger(__name__)


class CommitEngine:
    """
    Unified commit engine for git automation.

    Wraps GitCommitter to provide consistent interface for:
    - Staging translation output files
    - Creating commits with enhanced messages
    - Pushing to remote repositories
    - Co-author attribution

    Args:
        config: GitCommitConfig with commit settings (default: auto-push enabled)
        working_dir: Optional working directory for git operations

    Example:
        # Initialize engine
        config = GitCommitConfig(
            enabled=True,
            auto_push=True,
            commit_template="chore: translate {file_count} files to {languages}"
        )
        commit_engine = CommitEngine(config=config)

        # Commit translation outputs
        result = commit_engine.commit_if_enabled(
            output_files=[Path("de/example.md")],
            site_id="products.aspose.com",
            target_langs=["de", "fr"],
            run_id="run_123"
        )

        if result.success:
            print(f"Committed: {result.commit_hash_short}")
            if result.push_success:
                print(f"Pushed to {result.remote_url}")
    """

    def __init__(
        self,
        config: GitCommitConfig | None = None,
        working_dir: Path | None = None
    ):
        """Initialize commit engine."""
        self.config = config or GitCommitConfig()
        self.working_dir = working_dir

        # Create GitCommitter
        self.committer = GitCommitter(config=self.config)

        logger.info(
            f"CommitEngine initialized: enabled={self.config.enabled}, "
            f"auto_push={self.config.auto_push}, "
            f"working_dir={working_dir}"
        )

    def commit_if_enabled(
        self,
        output_files: list[Path],
        site_id: str,
        target_langs: list[str],
        run_id: str,
        translation_result: Any | None = None,
        model_id: str | None = None,
        tm_stats: dict | None = None,
    ) -> GitCommitResult:
        """
        Commit translation outputs if commits are enabled.

        Stages specific output files, creates a commit with enhanced message,
        and optionally pushes to remote repository.

        Args:
            output_files: List of translated output files to commit
            site_id: Site identifier (e.g., "products.aspose.com")
            target_langs: List of target language codes (e.g., ["de", "fr"])
            run_id: Unique run identifier for tracking
            translation_result: Optional DirectoryResult for enhanced message
            model_id: Optional model identifier for commit message
            tm_stats: Optional translation memory statistics

        Returns:
            GitCommitResult with commit details and status

        Example:
            result = engine.commit_if_enabled(
                output_files=[Path("de/example.md"), Path("fr/example.md")],
                site_id="docs.aspose.net",
                target_langs=["de", "fr"],
                run_id="run_20240115_123456",
                model_id="m2m100_418m"
            )

            if result.success:
                logger.info(f"Committed {result.files_committed} files")
        """
        if not self.config.enabled:
            logger.debug("Commits disabled, skipping git operations")
            return GitCommitResult(
                success=True,
                files_committed=0,
                error="Commits disabled in configuration"
            )

        logger.info(
            f"Committing {len(output_files)} files for {site_id} "
            f"(langs: {', '.join(target_langs)})"
        )

        result = self.committer.commit_translation_outputs(
            output_files=output_files,
            site_id=site_id,
            target_langs=target_langs,
            run_id=run_id,
            translation_result=translation_result,
            model_id=model_id,
            tm_stats=tm_stats,
        )

        if result.success:
            logger.info(
                f"Commit successful: {result.commit_hash_short} "
                f"({result.files_committed} files)"
            )
            if result.push_success:
                logger.info(f"Pushed to {result.remote_url} (branch: {result.branch})")
        else:
            logger.warning(f"Commit failed: {result.error}")

        return result

    def collect_output_files(
        self,
        output_root: Path,
        target_langs: list[str]
    ) -> list[Path]:
        """
        Collect all output files for specified target languages.

        Args:
            output_root: Root directory containing translated files
            target_langs: List of target language codes

        Returns:
            List of Path objects for all translated files

        Example:
            files = engine.collect_output_files(
                output_root=Path("/content"),
                target_langs=["de", "fr", "es"]
            )
            # Returns: [de/file1.md, de/file2.md, fr/file1.md, ...]
        """
        return collect_output_files(
            output_root=output_root,
            target_langs=target_langs
        )

    def is_enabled(self) -> bool:
        """
        Check if commits are enabled.

        Returns:
            True if commits enabled, False otherwise

        Example:
            if engine.is_enabled():
                result = engine.commit_if_enabled(...)
        """
        return self.config.enabled

    def get_config(self) -> GitCommitConfig:
        """
        Get commit configuration.

        Returns:
            GitCommitConfig instance

        Example:
            config = engine.get_config()
            print(f"Auto-push: {config.auto_push}")
            print(f"Timeout: {config.timeout_seconds}s")
        """
        return self.config

    def update_config(self, **kwargs: Any) -> None:
        """
        Update commit configuration at runtime.

        Args:
            **kwargs: Configuration fields to update (enabled, auto_push, etc.)

        Example:
            # Disable auto-push
            engine.update_config(auto_push=False)

            # Change timeout
            engine.update_config(timeout_seconds=120)
        """
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
                logger.info(f"Updated config: {key}={value}")
            else:
                logger.warning(f"Unknown config key: {key}")

    def get_committer(self) -> GitCommitter:
        """
        Get underlying GitCommitter for advanced usage.

        Returns:
            GitCommitter instance

        Note:
            Most code should use CommitEngine methods instead of
            accessing the committer directly.

        Example:
            committer = engine.get_committer()
            # Advanced git operations...
        """
        return self.committer
