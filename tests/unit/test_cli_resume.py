"""Unit tests for CLI resume/restart flags (RES-02).

Tests cover:
- --resume flag behavior (default enabled)
- --no-resume flag behavior
- --force-restart flag behavior
- Flag conflict handling
- --progress-dir custom path
- Progress cleanup functionality
- Help text for resume flags
"""

import importlib.util
import json
import sys
from pathlib import Path
from unittest import mock

import pytest


# Load cli module directly to avoid import chain issues
def load_cli_module():
    """Load cli module with mocked dependencies."""
    src_path = Path(__file__).parent.parent.parent / "src"

    # Create mock modules for dependencies
    mock_modules = [
        'translation_engine',
        'translation_engine.TranslationEngine',
        'translation_engine.models',
        'translation_engine.models.TranslationResult',
        'translation_engine.models.DirectoryResult',
        'translation_engine.progress',
        'translation_engine.progress.ProgressTracker',
        'tm',
        'tm.TranslationMemory',
        'tm.l1_cache',
        'tm.l1_cache.L1Cache',
        'tm.l2_persistent',
        'tm.l2_persistent.L2PersistentTM',
        'tm.l3_semantic',
        'tm.l3_semantic.L3SemanticTM',
        'model_runtime',
        'model_runtime.ModelLoader',
        'model_runtime.registry',
        'model_runtime.registry.ModelRegistry',
        'model_runtime.cpu_optimizer',
        'model_runtime.cpu_optimizer.CPUOptimizer',
        'utils',
        'utils.config_loader',
        'utils.config_loader.ConfigService',
        'utils.models',
        'utils.models.ValidationSettings',
        'utils.models.TerminologySettings',
        'verification',
        'verification.report',
        'verification.report.write_report',
        'observability',
        'observability.progress',
    ]

    for mod_name in mock_modules:
        if mod_name not in sys.modules:
            sys.modules[mod_name] = mock.MagicMock()

    # Now load cli module
    spec = importlib.util.spec_from_file_location("cli", src_path / "cli.py")
    cli_module = importlib.util.module_from_spec(spec)
    sys.modules['cli'] = cli_module
    spec.loader.exec_module(cli_module)

    return cli_module


# Load the module
cli_module = load_cli_module()
create_parser = cli_module.create_parser
_cleanup_progress = cli_module._cleanup_progress
CLIConfigOverrides = cli_module.CLIConfigOverrides


class TestCLIResumeFlags:
    """Tests for resume-related CLI flags."""

    @pytest.fixture
    def parser(self):
        """Create CLI parser."""
        return create_parser()

    def test_resume_flag_default_enabled(self, parser):
        """Test --resume is enabled by default."""
        args = parser.parse_args([
            "--site", "test.site"
        ])
        assert args.resume is True

    def test_resume_flag_explicit(self, parser):
        """Test --resume can be explicitly set."""
        args = parser.parse_args([
            "--site", "test.site",
            "--resume"
        ])
        assert args.resume is True

    def test_no_resume_flag(self, parser):
        """Test --no-resume disables resume."""
        args = parser.parse_args([
            "--site", "test.site",
            "--no-resume"
        ])
        assert args.resume is False

    def test_force_restart_flag_default(self, parser):
        """Test --force-restart is disabled by default."""
        args = parser.parse_args([
            "--site", "test.site"
        ])
        assert args.force_restart is False

    def test_force_restart_flag_enabled(self, parser):
        """Test --force-restart can be enabled."""
        args = parser.parse_args([
            "--site", "test.site",
            "--force-restart"
        ])
        assert args.force_restart is True

    def test_progress_dir_default(self, parser):
        """Test --progress-dir has correct default."""
        args = parser.parse_args([
            "--site", "test.site"
        ])
        assert args.progress_dir == ".translation_progress"

    def test_progress_dir_custom(self, parser):
        """Test --progress-dir accepts custom path."""
        args = parser.parse_args([
            "--site", "test.site",
            "--progress-dir", "/tmp/my_progress"
        ])
        assert args.progress_dir == "/tmp/my_progress"

    def test_help_includes_resume_flags(self, parser, capsys):
        """Test --help shows resume flags."""
        with pytest.raises(SystemExit):
            parser.parse_args(["--help"])

        captured = capsys.readouterr()
        assert "--resume" in captured.out
        assert "--no-resume" in captured.out
        assert "--force-restart" in captured.out
        assert "--progress-dir" in captured.out
        assert "Resume Control" in captured.out


class TestCLIConfigOverridesResume:
    """Tests for CLIConfigOverrides resume attributes."""

    @pytest.fixture
    def mock_args(self):
        """Create mock args with all required attributes."""
        args = mock.MagicMock()
        # Set all required attributes
        args.validation_mode = None
        args.disable_validation = False
        args.force_accept = False
        args.strict_reject = False
        args.enable_terminology = False
        args.disable_terminology = False
        args.terminology_mode = None
        args.max_retries = None
        args.validation_config = None
        args.terminology_config = None
        args.dry_run = False
        args.save_rejected = False
        args.verify = False
        args.fix = False
        args.verification_report = None
        args.max_tokens = None
        args.model = None
        args.batch_size = None
        args.device = "auto"
        args.load_mode = "auto"
        args.force_retranslate = False
        args.cache_write_mode = "auto"
        args.parallel_languages = 0
        args.global_lang_rounds = 0
        args.global_lang_sort = "desc"
        args.metrics_file = None
        args.metrics_interval = 2.0
        args.metrics_only = False
        args.no_progress = False
        args.resume = True
        args.force_restart = False
        args.progress_dir = ".translation_progress"
        return args

    def test_overrides_resume_default(self, mock_args):
        """Test resume is True by default."""
        overrides = CLIConfigOverrides(mock_args)
        assert overrides.resume is True
        assert overrides.force_restart is False

    def test_overrides_force_restart(self, mock_args):
        """Test force_restart attribute."""
        mock_args.force_restart = True
        overrides = CLIConfigOverrides(mock_args)
        assert overrides.force_restart is True

    def test_overrides_no_resume(self, mock_args):
        """Test no-resume attribute."""
        mock_args.resume = False
        overrides = CLIConfigOverrides(mock_args)
        assert overrides.resume is False

    def test_overrides_custom_progress_dir(self, mock_args):
        """Test custom progress_dir attribute."""
        mock_args.progress_dir = "/custom/path"
        overrides = CLIConfigOverrides(mock_args)
        assert overrides.progress_dir == "/custom/path"


class TestCleanupProgress:
    """Tests for _cleanup_progress helper function."""

    @pytest.fixture
    def progress_dir(self, tmp_path):
        """Create temporary progress directory with test files."""
        progress_dir = tmp_path / "progress"
        progress_dir.mkdir()
        return progress_dir

    def test_cleanup_nonexistent_dir(self, tmp_path):
        """Test cleanup with non-existent directory."""
        nonexistent = tmp_path / "nonexistent"
        result = _cleanup_progress(nonexistent, "test.site")
        assert result == 0

    def test_cleanup_empty_dir(self, progress_dir):
        """Test cleanup with empty directory."""
        result = _cleanup_progress(progress_dir, "test.site")
        assert result == 0

    def test_cleanup_removes_matching_files(self, progress_dir):
        """Test cleanup removes progress files for matching site."""
        # Create progress file for test.site
        pf1 = progress_dir / "progress_abc123.json"
        pf1.write_text(json.dumps({
            "site_id": "test.site",
            "run_id": "abc123"
        }))

        # Create progress file for other.site
        pf2 = progress_dir / "progress_def456.json"
        pf2.write_text(json.dumps({
            "site_id": "other.site",
            "run_id": "def456"
        }))

        # Clean up test.site
        result = _cleanup_progress(progress_dir, "test.site")

        assert result == 1
        assert not pf1.exists()
        assert pf2.exists()  # Other site's file preserved

    def test_cleanup_handles_invalid_json(self, progress_dir):
        """Test cleanup handles corrupted JSON files."""
        # Create valid file
        pf1 = progress_dir / "progress_valid.json"
        pf1.write_text(json.dumps({
            "site_id": "test.site",
            "run_id": "valid"
        }))

        # Create invalid JSON file
        pf2 = progress_dir / "progress_invalid.json"
        pf2.write_text("not valid json {{{")

        # Should remove valid file and skip invalid
        result = _cleanup_progress(progress_dir, "test.site")

        assert result == 1
        assert not pf1.exists()
        assert pf2.exists()  # Invalid file left alone

    def test_cleanup_multiple_files(self, progress_dir):
        """Test cleanup removes multiple matching files."""
        # Create 3 progress files for same site
        for i in range(3):
            pf = progress_dir / f"progress_run{i}.json"
            pf.write_text(json.dumps({
                "site_id": "test.site",
                "run_id": f"run{i}"
            }))

        result = _cleanup_progress(progress_dir, "test.site")

        assert result == 3
        assert len(list(progress_dir.glob("progress_*.json"))) == 0


class TestFlagConflictHandling:
    """Tests for flag conflict scenarios."""

    @pytest.fixture
    def parser(self):
        """Create CLI parser."""
        return create_parser()

    def test_force_restart_with_resume(self, parser):
        """Test --force-restart and --resume can coexist (force-restart wins)."""
        args = parser.parse_args([
            "--site", "test.site",
            "--resume",
            "--force-restart"
        ])
        # Both can be parsed, but force_restart should win in implementation
        assert args.resume is True
        assert args.force_restart is True

    def test_force_restart_with_no_resume(self, parser):
        """Test --force-restart with --no-resume."""
        args = parser.parse_args([
            "--site", "test.site",
            "--no-resume",
            "--force-restart"
        ])
        assert args.resume is False
        assert args.force_restart is True
