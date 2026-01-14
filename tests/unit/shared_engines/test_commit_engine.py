"""
Unit tests for CommitEngine.

Tests git commit wrapper with mocked GitCommitter.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from src.shared_engines.commit_engine import CommitEngine
from src.observability.git_commit import GitCommitConfig, GitCommitResult


class TestCommitEngine(unittest.TestCase):
    """Test CommitEngine wrapper."""

    @patch('src.shared_engines.commit_engine.GitCommitter')
    def test_initialization_default_config(self, mock_git_committer):
        """Test CommitEngine initializes with default config."""
        mock_committer_instance = Mock()
        mock_git_committer.return_value = mock_committer_instance

        engine = CommitEngine()

        self.assertIsNotNone(engine.config)
        self.assertTrue(engine.config.enabled)
        self.assertTrue(engine.config.auto_push)
        self.assertIsNone(engine.working_dir)
        mock_git_committer.assert_called_once()

    @patch('src.shared_engines.commit_engine.GitCommitter')
    def test_initialization_custom_config(self, mock_git_committer):
        """Test CommitEngine initializes with custom config."""
        mock_committer_instance = Mock()
        mock_git_committer.return_value = mock_committer_instance

        custom_config = GitCommitConfig(
            enabled=False,
            auto_push=False,
            timeout_seconds=120
        )
        working_dir = Path("/test/repo")

        engine = CommitEngine(config=custom_config, working_dir=working_dir)

        self.assertEqual(engine.config, custom_config)
        self.assertFalse(engine.config.enabled)
        self.assertFalse(engine.config.auto_push)
        self.assertEqual(engine.config.timeout_seconds, 120)
        self.assertEqual(engine.working_dir, working_dir)
        mock_git_committer.assert_called_once_with(config=custom_config)

    @patch('src.shared_engines.commit_engine.GitCommitter')
    def test_commit_if_enabled_success(self, mock_git_committer):
        """Test commit_if_enabled() commits successfully."""
        mock_committer_instance = Mock()
        mock_result = GitCommitResult(
            success=True,
            commit_hash="abc123def456",
            commit_hash_short="abc123d",
            remote_url="https://github.com/user/repo.git",
            branch="main",
            files_committed=5,
            push_success=True
        )
        mock_committer_instance.commit_translation_outputs.return_value = mock_result
        mock_git_committer.return_value = mock_committer_instance

        engine = CommitEngine()
        output_files = [Path("de/example.md"), Path("fr/example.md")]
        result = engine.commit_if_enabled(
            output_files=output_files,
            site_id="products.aspose.com",
            target_langs=["de", "fr"],
            run_id="run_123",
            model_id="m2m100_418m"
        )

        self.assertTrue(result.success)
        self.assertEqual(result.commit_hash_short, "abc123d")
        self.assertEqual(result.files_committed, 5)
        self.assertTrue(result.push_success)
        mock_committer_instance.commit_translation_outputs.assert_called_once_with(
            output_files=output_files,
            site_id="products.aspose.com",
            target_langs=["de", "fr"],
            run_id="run_123",
            translation_result=None,
            model_id="m2m100_418m",
            tm_stats=None
        )

    @patch('src.shared_engines.commit_engine.GitCommitter')
    def test_commit_if_enabled_with_all_params(self, mock_git_committer):
        """Test commit_if_enabled() with all optional parameters."""
        mock_committer_instance = Mock()
        mock_result = GitCommitResult(success=True, files_committed=3)
        mock_committer_instance.commit_translation_outputs.return_value = mock_result
        mock_git_committer.return_value = mock_committer_instance

        engine = CommitEngine()
        output_files = [Path("de/example.md")]
        translation_result = Mock()
        tm_stats = {"tm_hits": 42, "mt_segments": 58}

        result = engine.commit_if_enabled(
            output_files=output_files,
            site_id="docs.aspose.net",
            target_langs=["de"],
            run_id="run_456",
            translation_result=translation_result,
            model_id="nllb_600m",
            tm_stats=tm_stats
        )

        self.assertTrue(result.success)
        mock_committer_instance.commit_translation_outputs.assert_called_once_with(
            output_files=output_files,
            site_id="docs.aspose.net",
            target_langs=["de"],
            run_id="run_456",
            translation_result=translation_result,
            model_id="nllb_600m",
            tm_stats=tm_stats
        )

    @patch('src.shared_engines.commit_engine.GitCommitter')
    def test_commit_if_enabled_disabled(self, mock_git_committer):
        """Test commit_if_enabled() when commits are disabled."""
        mock_committer_instance = Mock()
        mock_git_committer.return_value = mock_committer_instance

        config = GitCommitConfig(enabled=False)
        engine = CommitEngine(config=config)

        result = engine.commit_if_enabled(
            output_files=[Path("de/example.md")],
            site_id="products.aspose.com",
            target_langs=["de"],
            run_id="run_123"
        )

        # Should return success without calling committer
        self.assertTrue(result.success)
        self.assertEqual(result.files_committed, 0)
        self.assertIn("disabled", result.error.lower())
        mock_committer_instance.commit_translation_outputs.assert_not_called()

    @patch('src.shared_engines.commit_engine.GitCommitter')
    def test_commit_if_enabled_failure(self, mock_git_committer):
        """Test commit_if_enabled() handles failure gracefully."""
        mock_committer_instance = Mock()
        mock_result = GitCommitResult(
            success=False,
            files_committed=0,
            push_success=False,
            error="Git repository not found"
        )
        mock_committer_instance.commit_translation_outputs.return_value = mock_result
        mock_git_committer.return_value = mock_committer_instance

        engine = CommitEngine()
        result = engine.commit_if_enabled(
            output_files=[Path("de/example.md")],
            site_id="products.aspose.com",
            target_langs=["de"],
            run_id="run_123"
        )

        self.assertFalse(result.success)
        self.assertEqual(result.files_committed, 0)
        self.assertIn("repository not found", result.error.lower())

    @patch('src.shared_engines.commit_engine.collect_output_files')
    @patch('src.shared_engines.commit_engine.GitCommitter')
    def test_collect_output_files(self, mock_git_committer, mock_collect):
        """Test collect_output_files() delegates to helper function."""
        mock_committer_instance = Mock()
        mock_git_committer.return_value = mock_committer_instance

        mock_files = [
            Path("de/file1.md"),
            Path("de/file2.md"),
            Path("fr/file1.md")
        ]
        mock_collect.return_value = mock_files

        engine = CommitEngine()
        output_root = Path("/content")
        target_langs = ["de", "fr"]

        files = engine.collect_output_files(
            output_root=output_root,
            target_langs=target_langs
        )

        self.assertEqual(files, mock_files)
        mock_collect.assert_called_once_with(
            output_root=output_root,
            target_langs=target_langs
        )

    @patch('src.shared_engines.commit_engine.GitCommitter')
    def test_is_enabled(self, mock_git_committer):
        """Test is_enabled() returns config state."""
        mock_committer_instance = Mock()
        mock_git_committer.return_value = mock_committer_instance

        # Enabled
        engine_enabled = CommitEngine(config=GitCommitConfig(enabled=True))
        self.assertTrue(engine_enabled.is_enabled())

        # Disabled
        engine_disabled = CommitEngine(config=GitCommitConfig(enabled=False))
        self.assertFalse(engine_disabled.is_enabled())

    @patch('src.shared_engines.commit_engine.GitCommitter')
    def test_get_config(self, mock_git_committer):
        """Test get_config() returns config object."""
        mock_committer_instance = Mock()
        mock_git_committer.return_value = mock_committer_instance

        custom_config = GitCommitConfig(
            enabled=True,
            auto_push=False,
            timeout_seconds=90
        )
        engine = CommitEngine(config=custom_config)

        config = engine.get_config()

        self.assertEqual(config, custom_config)
        self.assertTrue(config.enabled)
        self.assertFalse(config.auto_push)
        self.assertEqual(config.timeout_seconds, 90)

    @patch('src.shared_engines.commit_engine.GitCommitter')
    def test_update_config(self, mock_git_committer):
        """Test update_config() modifies config at runtime."""
        mock_committer_instance = Mock()
        mock_git_committer.return_value = mock_committer_instance

        engine = CommitEngine()

        # Update auto_push
        engine.update_config(auto_push=False)
        self.assertFalse(engine.config.auto_push)

        # Update timeout
        engine.update_config(timeout_seconds=120)
        self.assertEqual(engine.config.timeout_seconds, 120)

        # Update multiple fields
        engine.update_config(enabled=False, timeout_seconds=180)
        self.assertFalse(engine.config.enabled)
        self.assertEqual(engine.config.timeout_seconds, 180)

    @patch('src.shared_engines.commit_engine.GitCommitter')
    def test_update_config_invalid_key(self, mock_git_committer):
        """Test update_config() ignores invalid keys."""
        mock_committer_instance = Mock()
        mock_git_committer.return_value = mock_committer_instance

        engine = CommitEngine()
        original_config = engine.config.enabled

        # Try to update non-existent field (should be ignored)
        engine.update_config(invalid_field="value")

        # Config should remain unchanged
        self.assertEqual(engine.config.enabled, original_config)

    @patch('src.shared_engines.commit_engine.GitCommitter')
    def test_get_committer(self, mock_git_committer):
        """Test get_committer() returns underlying GitCommitter."""
        mock_committer_instance = Mock()
        mock_git_committer.return_value = mock_committer_instance

        engine = CommitEngine()
        committer = engine.get_committer()

        self.assertEqual(committer, mock_committer_instance)

    @patch('src.shared_engines.commit_engine.GitCommitter')
    def test_commit_without_push(self, mock_git_committer):
        """Test commit with push disabled."""
        mock_committer_instance = Mock()
        mock_result = GitCommitResult(
            success=True,
            commit_hash="abc123",
            commit_hash_short="abc123",
            files_committed=2,
            push_success=False
        )
        mock_committer_instance.commit_translation_outputs.return_value = mock_result
        mock_git_committer.return_value = mock_committer_instance

        config = GitCommitConfig(enabled=True, auto_push=False)
        engine = CommitEngine(config=config)

        result = engine.commit_if_enabled(
            output_files=[Path("de/example.md")],
            site_id="products.aspose.com",
            target_langs=["de"],
            run_id="run_123"
        )

        self.assertTrue(result.success)
        self.assertFalse(result.push_success)
        self.assertEqual(result.files_committed, 2)


if __name__ == "__main__":
    unittest.main()
