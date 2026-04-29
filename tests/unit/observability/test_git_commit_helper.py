"""
Unit tests for git_commit_helper._extract_model_id.

Tests all 3 tiers of model_id extraction and edge cases.
"""
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import Mock

from src.observability.git_commit_helper import _extract_model_id


# Mock classes matching DirectoryResult structure
@dataclass
class MockAggregateStats:
    """Mock AggregateStats for testing."""
    model_used: str | None = None


@dataclass
class MockTranslationStats:
    """Mock TranslationStats for testing."""
    model_used: str | None = None


@dataclass
class MockFileResult:
    """Mock file result for testing."""
    stats: MockTranslationStats | None = None


@dataclass
class MockDirectoryResult:
    """Mock DirectoryResult for testing."""
    aggregate_stats: MockAggregateStats | None = None
    file_results: list[MockFileResult] = None

    def __post_init__(self):
        if self.file_results is None:
            self.file_results = []


class TestExtractModelId(unittest.TestCase):
    """Test _extract_model_id function with all tiers and edge cases."""

    def test_tier1_aggregate_stats_success(self):
        """Test Tier 1: Extract from aggregate_stats.model_used."""
        # Setup: dir_result with aggregate_stats.model_used = "facebook/nllb-200"
        dir_result = MockDirectoryResult(
            aggregate_stats=MockAggregateStats(model_used="facebook/nllb-200")
        )
        config = {"model_defaults": {"fallback_model": "m2m100_418m"}}

        # Act
        result = _extract_model_id(dir_result, config=config)

        # Assert
        self.assertEqual(result, "facebook/nllb-200")

    def test_tier1_with_empty_string_falls_through(self):
        """Test that empty string from Tier 1 triggers fallback."""
        # Setup: aggregate_stats.model_used = "" (empty string)
        dir_result = MockDirectoryResult(
            aggregate_stats=MockAggregateStats(model_used="")
        )
        config = {"model_defaults": {"fallback_model": "m2m100_418m"}}

        # Act
        result = _extract_model_id(dir_result, config=config)

        # Assert: Should fall through to Tier 3
        self.assertEqual(result, "m2m100_418m")

    def test_tier2_file_results_success(self):
        """Test Tier 2: Extract from file_results[0].stats.model_used when Tier 1 fails."""
        # Setup: dir_result with no aggregate_stats, but file_results[0].stats.model_used = "m2m100"
        dir_result = MockDirectoryResult(
            aggregate_stats=None,
            file_results=[
                MockFileResult(
                    stats=MockTranslationStats(model_used="m2m100")
                )
            ]
        )
        config = {"model_defaults": {"fallback_model": "m2m100_418m"}}

        # Act
        result = _extract_model_id(dir_result, config=config)

        # Assert
        self.assertEqual(result, "m2m100")

    def test_tier2_with_empty_string_falls_through(self):
        """Test that empty string from Tier 2 triggers fallback."""
        # Setup: file_results[0].stats.model_used = ""
        dir_result = MockDirectoryResult(
            aggregate_stats=None,
            file_results=[
                MockFileResult(
                    stats=MockTranslationStats(model_used="")
                )
            ]
        )
        config = {"model_defaults": {"fallback_model": "m2m100_418m"}}

        # Act
        result = _extract_model_id(dir_result, config=config)

        # Assert: Should fall through to Tier 3
        self.assertEqual(result, "m2m100_418m")

    def test_tier3_fallback_with_dict(self):
        """Test Tier 3: Use config fallback when Tier 1 and 2 fail (dict config)."""
        # Setup: dir_result with no model info, config with model_defaults.fallback_model = "m2m100_418m"
        dir_result = MockDirectoryResult(
            aggregate_stats=None,
            file_results=[]
        )
        config = {"model_defaults": {"fallback_model": "m2m100_418m"}}

        # Act
        result = _extract_model_id(dir_result, config=config)

        # Assert
        self.assertEqual(result, "m2m100_418m")

    def test_tier3_fallback_with_pydantic_model(self):
        """Test Tier 3: Use config fallback when model_defaults is a Pydantic model."""
        # Setup: dir_result with no model info, config with Pydantic model
        dir_result = MockDirectoryResult(
            aggregate_stats=None,
            file_results=[]
        )

        # Mock a Pydantic model
        mock_model_defaults = Mock()
        mock_model_defaults.fallback_model = "custom_model"

        config = {"model_defaults": mock_model_defaults}

        # Act
        result = _extract_model_id(dir_result, config=config)

        # Assert
        self.assertEqual(result, "custom_model")

    def test_tier3_missing_model_defaults_key(self):
        """Test Tier 3: Handle missing model_defaults key gracefully."""
        # Setup: dir_result with no model info, config without model_defaults
        dir_result = MockDirectoryResult(
            aggregate_stats=None,
            file_results=[]
        )
        config = {"other_key": "other_value"}

        # Act
        result = _extract_model_id(dir_result, config=config)

        # Assert: Should use hardcoded default
        self.assertEqual(result, "m2m100_418m")

    def test_no_config_returns_none(self):
        """Test that None is returned when no config provided and no model in results."""
        # Setup: dir_result with no model info, config=None
        dir_result = MockDirectoryResult(
            aggregate_stats=None,
            file_results=[]
        )

        # Act
        result = _extract_model_id(dir_result, config=None)

        # Assert
        self.assertIsNone(result)

    def test_exception_uses_fallback_with_dict(self):
        """Test that exceptions fall back to config if available (dict config)."""
        # Setup: dir_result that raises exception, valid config
        dir_result = Mock()
        dir_result.aggregate_stats = Mock()
        # Make accessing model_used raise an exception
        type(dir_result.aggregate_stats).model_used = property(
            lambda self: (_ for _ in ()).throw(RuntimeError("Test exception"))
        )

        config = {"model_defaults": {"fallback_model": "fallback_model"}}

        # Act
        result = _extract_model_id(dir_result, config=config)

        # Assert: Should use fallback despite exception
        self.assertEqual(result, "fallback_model")

    def test_exception_uses_fallback_with_pydantic(self):
        """Test that exceptions fall back to config if available (Pydantic config)."""
        # Setup: dir_result that raises exception, Pydantic config
        dir_result = Mock()
        dir_result.aggregate_stats = Mock()
        type(dir_result.aggregate_stats).model_used = property(
            lambda self: (_ for _ in ()).throw(RuntimeError("Test exception"))
        )

        mock_model_defaults = Mock()
        mock_model_defaults.fallback_model = "pydantic_fallback"
        config = {"model_defaults": mock_model_defaults}

        # Act
        result = _extract_model_id(dir_result, config=config)

        # Assert
        self.assertEqual(result, "pydantic_fallback")

    def test_exception_without_config_returns_none(self):
        """Test that exceptions without config return None."""
        # Setup: dir_result that raises exception, no config
        dir_result = Mock()
        dir_result.aggregate_stats = Mock()
        type(dir_result.aggregate_stats).model_used = property(
            lambda self: (_ for _ in ()).throw(RuntimeError("Test exception"))
        )

        # Act
        result = _extract_model_id(dir_result, config=None)

        # Assert
        self.assertIsNone(result)

    def test_tier1_with_none_falls_through(self):
        """Test that None from Tier 1 triggers fallback."""
        # Setup: aggregate_stats.model_used = None
        dir_result = MockDirectoryResult(
            aggregate_stats=MockAggregateStats(model_used=None)
        )
        config = {"model_defaults": {"fallback_model": "m2m100_418m"}}

        # Act
        result = _extract_model_id(dir_result, config=config)

        # Assert: Should fall through to Tier 3
        self.assertEqual(result, "m2m100_418m")

    def test_tier2_with_none_falls_through(self):
        """Test that None from Tier 2 triggers fallback."""
        # Setup: file_results[0].stats.model_used = None
        dir_result = MockDirectoryResult(
            aggregate_stats=None,
            file_results=[
                MockFileResult(
                    stats=MockTranslationStats(model_used=None)
                )
            ]
        )
        config = {"model_defaults": {"fallback_model": "m2m100_418m"}}

        # Act
        result = _extract_model_id(dir_result, config=config)

        # Assert: Should fall through to Tier 3
        self.assertEqual(result, "m2m100_418m")

    def test_empty_file_results_falls_through(self):
        """Test that empty file_results list triggers fallback."""
        # Setup: file_results = []
        dir_result = MockDirectoryResult(
            aggregate_stats=None,
            file_results=[]
        )
        config = {"model_defaults": {"fallback_model": "m2m100_418m"}}

        # Act
        result = _extract_model_id(dir_result, config=config)

        # Assert: Should fall through to Tier 3
        self.assertEqual(result, "m2m100_418m")

    def test_file_result_without_stats_falls_through(self):
        """Test that file_result without stats triggers fallback."""
        # Setup: file_results[0].stats = None
        dir_result = MockDirectoryResult(
            aggregate_stats=None,
            file_results=[MockFileResult(stats=None)]
        )
        config = {"model_defaults": {"fallback_model": "m2m100_418m"}}

        # Act
        result = _extract_model_id(dir_result, config=config)

        # Assert: Should fall through to Tier 3
        self.assertEqual(result, "m2m100_418m")

    def test_custom_fallback_model_respected(self):
        """Test that custom fallback_model in config is respected."""
        # Setup: No model in results, custom fallback in config
        dir_result = MockDirectoryResult(
            aggregate_stats=None,
            file_results=[]
        )
        config = {"model_defaults": {"fallback_model": "custom_fallback_model_v2"}}

        # Act
        result = _extract_model_id(dir_result, config=config)

        # Assert
        self.assertEqual(result, "custom_fallback_model_v2")

    def test_tier1_overrides_tier2(self):
        """Test that Tier 1 takes precedence over Tier 2 when both exist."""
        # Setup: Both aggregate_stats and file_results have model_used
        dir_result = MockDirectoryResult(
            aggregate_stats=MockAggregateStats(model_used="tier1_model"),
            file_results=[
                MockFileResult(
                    stats=MockTranslationStats(model_used="tier2_model")
                )
            ]
        )
        config = {"model_defaults": {"fallback_model": "m2m100_418m"}}

        # Act
        result = _extract_model_id(dir_result, config=config)

        # Assert: Should return Tier 1 model
        self.assertEqual(result, "tier1_model")


class TestCollectModifiedFilesFromGit(unittest.TestCase):
    """Test collect_modified_files_from_git fallback function."""

    def _make_dir_result(self):
        """Create a minimal mock DirectoryResult."""
        mock = Mock()
        mock.file_results = []
        mock.successful_files = 0
        return mock

    @unittest.mock.patch("src.observability.git_commit_helper.subprocess.run")
    @unittest.mock.patch("src.observability.git_context.find_git_root")
    def test_catches_untracked_files(self, mock_find_root, mock_run):
        """Untracked (??) .md files must be collected."""
        import tempfile
        from pathlib import Path

        from src.observability.git_commit_helper import collect_modified_files_from_git

        with tempfile.TemporaryDirectory() as tmpdir:
            git_root = Path(tmpdir)
            mock_find_root.return_value = git_root

            # Create the files so .exists() returns True
            (git_root / "content" / "ar").mkdir(parents=True)
            (git_root / "content" / "bg").mkdir(parents=True)
            (git_root / "content" / "ar" / "file1.md").touch()
            (git_root / "content" / "bg" / "file2.md").touch()

            mock_run.return_value = Mock(
                returncode=0,
                stdout="?? content/ar/file1.md\n?? content/bg/file2.md\n",
            )

            content_dir = git_root / "content"
            result = collect_modified_files_from_git(
                content_dir,
                self._make_dir_result(),
                content_root=content_dir,
            )

        self.assertEqual(len(result), 2)

    @unittest.mock.patch("src.observability.git_commit_helper.subprocess.run")
    @unittest.mock.patch("src.observability.git_context.find_git_root")
    def test_catches_modified_files(self, mock_find_root, mock_run):
        """Modified (M) .md files must be collected."""
        import tempfile
        from pathlib import Path

        from src.observability.git_commit_helper import collect_modified_files_from_git

        with tempfile.TemporaryDirectory() as tmpdir:
            git_root = Path(tmpdir)
            mock_find_root.return_value = git_root

            (git_root / "content" / "ar").mkdir(parents=True)
            (git_root / "content" / "bg").mkdir(parents=True)
            (git_root / "content" / "ar" / "file1.md").touch()
            (git_root / "content" / "bg" / "file2.md").touch()

            mock_run.return_value = Mock(
                returncode=0,
                stdout=" M content/ar/file1.md\nMM content/bg/file2.md\n",
            )

            content_dir = git_root / "content"
            result = collect_modified_files_from_git(
                content_dir,
                self._make_dir_result(),
                content_root=content_dir,
            )

        self.assertEqual(len(result), 2)

    @unittest.mock.patch("src.observability.git_commit_helper.subprocess.run")
    @unittest.mock.patch("src.observability.git_context.find_git_root")
    def test_filters_non_md_files(self, mock_find_root, mock_run):
        """Non-.md files must NOT be collected."""
        import tempfile
        from pathlib import Path

        from src.observability.git_commit_helper import collect_modified_files_from_git

        with tempfile.TemporaryDirectory() as tmpdir:
            git_root = Path(tmpdir)
            mock_find_root.return_value = git_root

            (git_root / "content" / "ar").mkdir(parents=True)
            (git_root / "content" / "ar" / "file.md").touch()
            (git_root / "content" / "config.yaml").write_text("x")
            (git_root / "content" / "script.py").write_text("x")

            mock_run.return_value = Mock(
                returncode=0,
                stdout="?? content/config.yaml\n?? content/ar/file.md\n M content/script.py\n",
            )

            content_dir = git_root / "content"
            result = collect_modified_files_from_git(
                content_dir,
                self._make_dir_result(),
                content_root=content_dir,
            )

        # Only the .md file should be collected
        self.assertEqual(len(result), 1)
        self.assertTrue(str(result[0]).endswith("file.md"))

    @unittest.mock.patch("src.observability.git_commit_helper.subprocess.run")
    @unittest.mock.patch("src.observability.git_context.find_git_root")
    def test_content_root_overrides_output_dir(self, mock_find_root, mock_run):
        """content_root should be used as scan directory, not output_dir."""
        import tempfile
        from pathlib import Path

        from src.observability.git_commit_helper import collect_modified_files_from_git

        with tempfile.TemporaryDirectory() as tmpdir:
            git_root = Path(tmpdir)
            mock_find_root.return_value = git_root

            # Create both directories
            narrow_dir = git_root / "content" / "site" / "ar"
            wide_dir = git_root / "content" / "site"
            narrow_dir.mkdir(parents=True)

            mock_run.return_value = Mock(returncode=0, stdout="")

            collect_modified_files_from_git(
                narrow_dir,  # narrow output_dir
                self._make_dir_result(),
                content_root=wide_dir,  # wide content_root
            )

        # The git status should have been called (not short-circuited)
        mock_run.assert_called_once()
        # The path argument should contain "site" (from content_root), not "site/ar" (from output_dir)
        git_cmd = mock_run.call_args[0][0]
        path_arg = git_cmd[3]  # ["git", "status", "--porcelain", <path>]
        self.assertFalse(path_arg.endswith("ar"), f"Should use content_root, not output_dir: {path_arg}")

    @unittest.mock.patch("src.observability.git_commit_helper.subprocess.run")
    @unittest.mock.patch("src.observability.git_context.find_git_root")
    def test_empty_git_status_returns_empty_list(self, mock_find_root, mock_run):
        """Empty git status output should return empty list."""
        import tempfile
        from pathlib import Path

        from src.observability.git_commit_helper import collect_modified_files_from_git

        with tempfile.TemporaryDirectory() as tmpdir:
            git_root = Path(tmpdir)
            mock_find_root.return_value = git_root
            content_dir = git_root / "content"
            content_dir.mkdir(parents=True)

            mock_run.return_value = Mock(returncode=0, stdout="")

            result = collect_modified_files_from_git(
                content_dir,
                self._make_dir_result(),
            )

        self.assertEqual(result, [])


class TestWritePendingCommitFallback(unittest.TestCase):
    """Tests for _write_pending_commit_fallback() — SEO watcher integration."""

    def setUp(self):
        from src.observability.git_commit_helper import _write_pending_commit_fallback
        self._fn = _write_pending_commit_fallback

    def test_writes_valid_json(self):
        """Happy path: writes .pending_commit.json with correct fields."""
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            git_root = Path(tmpdir)
            output_files = [git_root / "content" / "de" / "index.md"]
            (git_root / "content" / "de").mkdir(parents=True)
            output_files[0].touch()

            result = self._fn(
                output_files=output_files,
                git_root=git_root,
                site_id="blog.aspose.net",
                target_langs=["de", "fr", "es"],
            )

            self.assertTrue(result)
            pending = git_root / ".pending_commit.json"
            self.assertTrue(pending.exists())
            data = json.loads(pending.read_text())
            self.assertIn("files", data)
            self.assertIn("commit_message", data)
            self.assertEqual(data["author_name"], "Hugo Translator")
            self.assertEqual(data["author_email"], "hugo-translator@aspose.net")
            self.assertIn("created_at", data)
            self.assertIn("blog.aspose.net", data["commit_message"])
            self.assertIn("de, fr, es", data["commit_message"])

    def test_relative_paths_use_forward_slashes(self):
        """File paths in JSON use forward slashes regardless of OS."""
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            git_root = Path(tmpdir)
            sub = git_root / "content" / "blog" / "ar"
            sub.mkdir(parents=True)
            f = sub / "index.md"
            f.touch()

            self._fn(
                output_files=[f],
                git_root=git_root,
                site_id="blog.aspose.net",
                target_langs=["ar"],
            )

            data = json.loads((git_root / ".pending_commit.json").read_text())
            for rel in data["files"]:
                self.assertNotIn("\\", rel, f"Path should use forward slashes: {rel}")

    def test_skips_files_outside_git_root(self):
        """Files not under git_root are silently skipped."""
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            git_root = Path(tmpdir) / "repo"
            git_root.mkdir()
            inside = git_root / "file.md"
            inside.touch()
            outside = Path(tmpdir) / "other" / "file.md"
            Path(tmpdir, "other").mkdir()
            outside.touch()

            result = self._fn(
                output_files=[inside, outside],
                git_root=git_root,
                site_id="test.net",
                target_langs=["de"],
            )

            self.assertTrue(result)
            data = json.loads((git_root / ".pending_commit.json").read_text())
            self.assertEqual(len(data["files"]), 1)
            self.assertEqual(data["files"][0], "file.md")

    def test_returns_false_when_no_files_in_git_root(self):
        """Returns False when all files are outside the git root."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            git_root = Path(tmpdir) / "repo"
            git_root.mkdir()
            outside = Path(tmpdir) / "outside.md"
            outside.touch()

            result = self._fn(
                output_files=[outside],
                git_root=git_root,
                site_id="test.net",
                target_langs=["de"],
            )

            self.assertFalse(result)
            self.assertFalse((git_root / ".pending_commit.json").exists())

    def test_lang_list_truncates_beyond_six(self):
        """commit_message truncates to 6 langs + '+N more' when many languages."""
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            git_root = Path(tmpdir)
            f = git_root / "file.md"
            f.touch()
            langs = ["ar", "bg", "ca", "cs", "da", "de", "el", "es", "fa", "fi"]

            self._fn(
                output_files=[f],
                git_root=git_root,
                site_id="test.net",
                target_langs=langs,
            )

            data = json.loads((git_root / ".pending_commit.json").read_text())
            self.assertIn("+4 more", data["commit_message"])


class TestValidateFileIntegrity(unittest.TestCase):
    """Tests for _validate_file_integrity() nested in recover_pending_commits.

    Since the function is defined inside recover_pending_commits and not
    directly importable, we replicate its logic here for unit testing.
    The rules are: exists, >100 bytes, contains '---' in first 500 chars.
    """

    @staticmethod
    def _validate(file_path: Path) -> bool:
        """Mirror of git_commit_helper._validate_file_integrity logic."""
        try:
            if not file_path.exists():
                return False
            size = file_path.stat().st_size
            if size < 100:
                return False
            content = file_path.read_text(encoding="utf-8", errors="replace")[:500]
            if "---" not in content:
                return False
            return True
        except Exception:
            return False

    def test_small_file_rejected(self):
        """File < 100 bytes must be rejected."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "tiny.md"
            f.write_text("---\ntitle: x\n---\n", encoding="utf-8")
            self.assertFalse(self._validate(f))

    def test_valid_md_passes(self):
        """File with front matter + body > 100 bytes must pass."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "good.md"
            content = "---\ntitle: Test Article\ndate: 2026-01-01\n---\n" + "A" * 100
            f.write_text(content, encoding="utf-8")
            self.assertTrue(self._validate(f))

    def test_no_front_matter_rejected(self):
        """File > 100 bytes but without '---' must be rejected."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "nofm.md"
            f.write_text("A" * 200, encoding="utf-8")
            self.assertFalse(self._validate(f))

    def test_nonexistent_file_rejected(self):
        """Missing file must be rejected."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "ghost.md"
            self.assertFalse(self._validate(f))


if __name__ == "__main__":
    unittest.main()
