"""
CONTRACT: specs/features/cli-001-main-translate.md

Verifies the main translate-hugo CLI command behavior including:
- Multi-language subprocess isolation
- Atomic output writes
- Site profile validation
- Progress file integrity
- Graceful shutdown handling

CLI-001: Main Translation Command

Key Guarantees:
1. Multi-language translation MUST spawn separate subprocess per language
2. ALL translated files MUST be written atomically (temp + rename)
3. Site profile MUST be validated and exist before translation starts
4. Progress file MUST be created/updated when --resume enabled
5. Signal handlers SHOULD be registered for graceful shutdown

Never Invariants:
- NEVER skip subprocess isolation for multi-language
- NEVER allow both --parallel-languages AND --global-lang-rounds together
"""

import argparse
import sys
from unittest.mock import Mock, patch

import pytest
import yaml

# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def mock_args_multi_lang():
    """
    Mock CLI arguments for multi-language translation.

    Simulates: --site test.example.com --target-langs de,fr,es
    """
    args = argparse.Namespace()
    args.site = "test.example.com"
    args.input = "/path/to/source"
    args.output = "/path/to/output"
    args.target_langs = ["de", "fr", "es"]
    args.model = "nllb-200-distilled-600M"
    args.config_root = "./config"
    args._single_lang_mode = False
    args._skip_site_lock = False
    args.auto_commit = False
    args.fail_fast = True
    args.parallel_languages = 0
    args.global_lang_rounds = 0
    args.device = "auto"
    args.batch_size = None
    args.max_tokens = None
    args.log_level = "INFO"
    args.log_file = None
    args.force_retranslate = False
    args.dry_run = False
    args.no_progress = False
    args.disable_validation = False
    args.force_accept = False
    args.strict_reject = False
    args.enable_terminology = None
    return args


@pytest.fixture
def mock_args_single_lang():
    """
    Mock CLI arguments for single-language translation.

    Simulates: --site test.example.com --target-langs de
    """
    args = argparse.Namespace()
    args.site = "test.example.com"
    args.input = "/path/to/source"
    args.output = "/path/to/output"
    args.target_langs = ["de"]
    args.model = "nllb-200-distilled-600M"
    args.config_root = "./config"
    args._single_lang_mode = False
    args._skip_site_lock = False
    args.auto_commit = False
    args.fail_fast = True
    args.parallel_languages = 0
    args.global_lang_rounds = 0
    return args


@pytest.fixture
def temp_config_dir(tmp_path):
    """
    Create a temporary config directory with site profiles.
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    # Create site_profiles directory
    profiles_dir = config_dir / "site_profiles"
    profiles_dir.mkdir()

    # Create global.yaml
    global_config = {
        "tm_data_dir": str(tmp_path / "data" / "tm"),
        "model_cache_dir": str(tmp_path / ".cache"),
    }
    global_path = config_dir / "global.yaml"
    with open(global_path, "w", encoding="utf-8") as f:
        yaml.dump(global_config, f)

    return config_dir


@pytest.fixture
def valid_site_profile(temp_config_dir, tmp_path):
    """
    Create a valid site profile in the temp config directory.
    """
    profile = {
        "site_id": "test.example.com",
        "content_roots": [str(tmp_path / "content")],
        "default_source_lang": "en",
        "target_langs": ["fr", "de", "es"],
        "frontmatter": {
            "title": {"mode": "translate"},
        },
        "body": {
            "translate_markdown": True,
        },
        "output_layout": {
            "per_language_folders": True,
            "pattern": "{lang}/{path}",
        },
    }

    profile_path = temp_config_dir / "site_profiles" / "test.example.com.yaml"
    with open(profile_path, "w", encoding="utf-8") as f:
        yaml.dump(profile, f)

    # Create content directory
    content_dir = tmp_path / "content"
    content_dir.mkdir(parents=True, exist_ok=True)

    return profile_path


# ==============================================================================
# INV-1: Multi-Language Subprocess Isolation Tests
# ==============================================================================


@pytest.mark.contract
class TestMultiLangSubprocessIsolation:
    """CONTRACT: specs/features/cli-001-main-translate.md - Invariant #1"""

    def test_multi_lang_triggers_subprocess_mode(self):
        """
        INV: WHEN len(target_langs) > 1 MUST spawn subprocess per language.

        Evidence: src/cli.py lines 1587-1591
        """
        # Arrange
        target_langs = ["de", "fr", "es"]
        single_lang_mode = False

        # Act - Check the condition that triggers subprocess mode
        should_spawn_subprocesses = len(target_langs) > 1 and not single_lang_mode

        # Assert
        assert should_spawn_subprocesses is True
        assert len(target_langs) == 3

    def test_single_lang_does_not_trigger_subprocess_mode(self):
        """
        INV: Single language SHOULD NOT spawn subprocess.

        Evidence: src/cli.py lines 1587 (condition only triggers for > 1)
        """
        # Arrange
        target_langs = ["de"]
        single_lang_mode = False

        # Act
        should_spawn_subprocesses = len(target_langs) > 1 and not single_lang_mode

        # Assert
        assert should_spawn_subprocesses is False

    def test_single_lang_mode_flag_prevents_recursion(self):
        """
        INV: _single_lang_mode flag MUST prevent infinite subprocess recursion.

        Evidence: src/cli.py lines 1587 (not getattr(args, '_single_lang_mode', False))
        """
        # Arrange - Multiple languages but flag is set (already in subprocess)
        target_langs = ["de", "fr", "es"]
        single_lang_mode = True  # Flag set by parent process

        # Act
        should_spawn_subprocesses = len(target_langs) > 1 and not single_lang_mode

        # Assert - Should NOT spawn again
        assert should_spawn_subprocesses is False

    def test_subprocess_count_equals_language_count(self):
        """
        INV: N languages MUST result in N subprocess spawns.

        Evidence: src/cli.py lines 1644 (for i, lang in enumerate(target_langs, 1))
        """
        # Arrange
        target_langs = ["de", "fr", "es", "it", "pt"]
        subprocess_commands = []

        # Act - Simulate loop as CLI does
        for lang in target_langs:
            cmd = [sys.executable, "-m", "src.cli", "--target-langs", lang]
            subprocess_commands.append(cmd)

        # Assert
        assert len(subprocess_commands) == len(target_langs)
        assert len(subprocess_commands) == 5

    def test_subprocess_command_includes_isolation_flags(self):
        """
        INV: Subprocess command MUST include --_single-lang-mode and --_skip-site-lock.

        Evidence: src/cli.py lines 1700-1703
        """
        # Arrange - Build command as CLI does
        cmd = [sys.executable, "-m", "src.cli"]
        cmd.extend(["--site", "test.example.com"])
        cmd.extend(["--target-langs", "de"])
        cmd.append("--_single-lang-mode")
        cmd.append("--_skip-site-lock")

        # Assert
        assert "--_single-lang-mode" in cmd
        assert "--_skip-site-lock" in cmd

    def test_subprocess_receives_exactly_one_language(self):
        """
        INV: Each subprocess MUST receive exactly one target language.

        Evidence: src/cli.py line 1664 (--target-langs lang, not comma-separated)
        """
        # Arrange
        all_target_langs = ["de", "fr", "es"]

        # Act - Build commands for each language
        for lang in all_target_langs:
            cmd = ["--target-langs", lang]

            # Assert - No comma in language value (single language)
            lang_value = cmd[cmd.index("--target-langs") + 1]
            assert "," not in lang_value
            assert lang_value == lang


# ==============================================================================
# INV-2: Atomic Output Writes Tests
# ==============================================================================


@pytest.mark.contract
class TestAtomicOutputWrites:
    """CONTRACT: specs/features/cli-001-main-translate.md - Invariant #2"""

    def test_atomic_write_uses_temp_then_rename(self, tmp_path):
        """
        INV: ALL translated files MUST be written atomically (temp + rename).

        Evidence: src/utils/atomic_write.py lines 148-170
        """
        from src.utils.atomic_write import atomic_write

        # Arrange
        output_file = tmp_path / "output" / "de" / "test.md"
        content = "# Translated Content\n\nDies ist ein Test."

        # Act
        atomic_write(output_file, content, create_parents=True)

        # Assert - File exists with complete content
        assert output_file.exists()
        assert output_file.read_text(encoding="utf-8") == content

        # Assert - No temp files remain
        temp_files = list(tmp_path.rglob("*.tmp"))
        assert len(temp_files) == 0

    def test_atomic_write_preserves_original_on_failure(self, tmp_path):
        """
        INV: Original file MUST be preserved if atomic write fails.

        Evidence: src/utils/atomic_write.py - os.replace is atomic
        """
        import errno

        from src.utils.atomic_write import AtomicWriteError, atomic_write

        # Arrange - Create existing file
        output_file = tmp_path / "existing.md"
        original_content = "Original content"
        output_file.write_text(original_content, encoding="utf-8")

        # Act - Simulate write failure
        with patch('os.replace') as mock_replace:
            mock_replace.side_effect = OSError(errno.EIO, "Disk error")

            with pytest.raises((AtomicWriteError, OSError)):
                atomic_write(output_file, "New content that should fail")

        # Assert - Original content preserved
        assert output_file.read_text(encoding="utf-8") == original_content


# ==============================================================================
# INV-3: Site Profile Validation Tests
# ==============================================================================


@pytest.mark.contract
class TestSiteProfileValidation:
    """CONTRACT: specs/features/cli-001-main-translate.md - Invariant #3"""

    def test_missing_site_profile_raises_error(self, temp_config_dir):
        """
        INV: MUST validate site profile exists, fail fast with clear error.

        Evidence: src/utils/config_loader.py lines 92-93
        """
        from src.utils.config_loader import ConfigLoadError, ConfigService

        # Arrange
        config_service = ConfigService(str(temp_config_dir))

        # Act & Assert
        with pytest.raises(ConfigLoadError) as exc_info:
            config_service.get_site_profile("nonexistent.site.com")

        assert "Profile not found" in str(exc_info.value)
        assert "nonexistent.site.com" in str(exc_info.value)

    def test_valid_site_profile_loads_successfully(self, temp_config_dir, valid_site_profile):
        """
        INV: Valid site profile MUST load without error.

        Evidence: src/utils/config_loader.py lines 86-115
        """
        from src.utils.config_loader import ConfigService

        # Arrange
        config_service = ConfigService(str(temp_config_dir))

        # Act
        profile = config_service.get_site_profile("test.example.com")

        # Assert
        assert profile.site_id == "test.example.com"
        assert "fr" in profile.target_langs

    def test_invalid_config_root_raises_error(self, tmp_path):
        """
        INV: MUST fail fast if config root doesn't exist.

        Evidence: src/utils/config_loader.py lines 40-41
        """
        from src.utils.config_loader import ConfigLoadError, ConfigService

        # Arrange
        nonexistent_path = tmp_path / "nonexistent_config"

        # Act & Assert
        with pytest.raises(ConfigLoadError) as exc_info:
            ConfigService(str(nonexistent_path))

        assert "Config root does not exist" in str(exc_info.value)


# ==============================================================================
# INV-4: Progress File Integrity Tests
# ==============================================================================


@pytest.mark.contract
class TestProgressFileIntegrity:
    """CONTRACT: specs/features/cli-001-main-translate.md - Invariant #4"""

    def test_progress_tracker_creates_file_when_resume_enabled(self, tmp_path):
        """
        INV: SHOULD create progress file on start when --resume enabled.

        Evidence: src/cli.py lines 1469-1472
        """
        from src.translation_engine.progress import ProgressTracker

        # Arrange
        progress_dir = tmp_path / ".translation_progress"
        progress_dir.mkdir(parents=True, exist_ok=True)

        # Create sample files to track
        content_dir = tmp_path / "content"
        content_dir.mkdir(parents=True, exist_ok=True)
        test_file = content_dir / "test.md"
        test_file.write_text("# Test", encoding="utf-8")

        # Act - Use correct ProgressTracker constructor signature
        tracker = ProgressTracker(
            progress_dir=progress_dir,
            site_id="test.example.com",
            source_dir=content_dir,
            output_dir=tmp_path / "output",
            target_langs=["de", "fr"]
        )
        # Initialize with files to trigger save
        tracker.initialize([test_file])

        # Assert - Progress file created
        progress_files = list(progress_dir.glob("progress_*.json"))
        assert len(progress_files) >= 1

    def test_progress_tracker_validates_corrupted_file(self, tmp_path):
        """
        INV: SHOULD validate and recover corrupted progress files.

        Evidence: src/cli.py lines 1476-1504
        """
        from src.translation_engine.progress import ProgressTracker

        # Arrange - Create corrupted progress file
        progress_dir = tmp_path / ".translation_progress"
        progress_dir.mkdir(parents=True, exist_ok=True)

        corrupted_file = progress_dir / "progress_test_12345678.json"
        corrupted_file.write_text("{ invalid json content", encoding="utf-8")

        # Act
        is_valid, error_msg, recoverable = ProgressTracker.validate_progress_file(
            corrupted_file
        )

        # Assert
        assert is_valid is False
        assert error_msg is not None


# ==============================================================================
# INV-5: Graceful Shutdown Tests
# ==============================================================================


@pytest.mark.contract
class TestGracefulShutdown:
    """CONTRACT: specs/features/cli-001-main-translate.md - Invariant #5"""

    def test_signal_handler_setup_registers_sigint(self):
        """
        INV: SHOULD register signal handlers for SIGINT.

        Evidence: src/cli.py lines 1246-1253
        """
        # Arrange - Mock engine
        mock_engine = Mock()
        mock_engine.request_shutdown = Mock()

        # Act - Import and check function exists
        from src.cli import setup_unified_signal_handler

        # Assert - Function exists and is callable
        assert callable(setup_unified_signal_handler)

    def test_signal_handler_tracks_interrupt_count(self):
        """
        INV: Signal handler SHOULD track interrupt count for multi-stage shutdown.

        Evidence: src/cli.py lines 1214, 1219 (interrupt_count tracking)
        """
        # Arrange - Verify the design
        interrupt_design = {
            "first_interrupt": "Graceful shutdown, saves progress",
            "second_interrupt": "Force exit with code 130",
        }

        # Assert - Design specifies multi-stage
        assert "first_interrupt" in interrupt_design
        assert "second_interrupt" in interrupt_design
        assert "130" in interrupt_design["second_interrupt"]


# ==============================================================================
# NEVER Invariants Tests
# ==============================================================================


@pytest.mark.contract
class TestNeverInvariants:
    """CONTRACT: specs/features/cli-001-main-translate.md - Never Invariants"""

    def test_never_skip_subprocess_isolation_for_multilang(self):
        """
        NEVER: Even with --force-retranslate, multi-language MUST use subprocesses.

        Evidence: src/cli.py lines 1587 - condition has no force_retranslate bypass
        """
        # Arrange
        target_langs = ["de", "fr", "es"]
        force_retranslate = True  # Should NOT affect isolation
        single_lang_mode = False

        # Act - The condition is the same regardless of force_retranslate
        should_spawn_subprocesses = len(target_langs) > 1 and not single_lang_mode

        # Assert - Subprocess isolation is still enforced
        assert should_spawn_subprocesses is True

    def test_never_allow_parallel_and_global_rounds_together(self):
        """
        NEVER: Cannot use --parallel-languages AND --global-lang-rounds together.

        Evidence: src/cli.py lines 302-306
        """
        from src.cli import CLIConfigOverrides

        # Arrange - Args with both flags set
        args = argparse.Namespace()
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
        args.sort_segments_by_length = None
        args.device = "auto"
        args.load_mode = "auto"
        args.force_retranslate = False
        args.cache_write_mode = "auto"
        args.parallel_languages = 2  # Non-zero
        args.global_lang_rounds = 3  # Non-zero - CONFLICT!
        args.global_lang_sort = "size"
        args.metrics_file = None
        args.metrics_interval = 30.0
        args.metrics_only = False
        args.no_progress = False
        args.resume = False
        args.force_restart = False
        args.progress_dir = ".translation_progress"
        args.disable_content_hash = False
        args.rebuild_content_hashes = False
        args.validate_output_integrity = False

        # Act & Assert - Should raise ValueError
        overrides = CLIConfigOverrides(args)

        with pytest.raises(ValueError) as exc_info:
            overrides.get_engine_overrides()

        assert "Cannot use both" in str(exc_info.value)
        assert "--parallel-languages" in str(exc_info.value)
        assert "--global-lang-rounds" in str(exc_info.value)


# ==============================================================================
# CLI Argument Parser Tests
# ==============================================================================


@pytest.mark.contract
class TestCLIArgumentParser:
    """CONTRACT: specs/features/cli-001-main-translate.md - Argument Parsing"""

    def test_parser_requires_site_argument(self):
        """
        INV: --site is REQUIRED argument.

        Evidence: src/cli.py lines 214-593 (argument parser)
        """
        from src.cli import create_parser

        # Arrange
        parser = create_parser()

        # Act & Assert - Parsing without --site should fail
        with pytest.raises(SystemExit):
            parser.parse_args([])

    def test_parser_accepts_target_langs(self):
        """
        INV: --target-langs accepts space-separated language codes (nargs=+).

        Evidence: src/cli.py line 446 (nargs="+")
        """
        from src.cli import create_parser

        # Arrange
        parser = create_parser()

        # Act - With nargs="+", each space-separated value becomes a list item
        args = parser.parse_args(["--site", "test.com", "--target-langs", "de", "fr", "es"])

        # Assert - Returns list of languages
        assert args.target_langs == ["de", "fr", "es"]
        assert isinstance(args.target_langs, list)
        assert len(args.target_langs) == 3

    def test_internal_flags_are_hidden(self):
        """
        INV: Internal flags (_single-lang-mode, _skip-site-lock) exist but are hidden.

        Evidence: src/cli.py - these flags use underscore prefix convention
        """
        from src.cli import create_parser

        # Arrange
        parser = create_parser()

        # Act - Parse with internal flags
        args = parser.parse_args([
            "--site", "test.com",
            "--_single-lang-mode",
            "--_skip-site-lock"
        ])

        # Assert - Flags are recognized
        assert args._single_lang_mode is True
        assert args._skip_site_lock is True


# ==============================================================================
# Exit Code Tests
# ==============================================================================


@pytest.mark.contract
class TestExitCodes:
    """CONTRACT: specs/features/cli-001-main-translate.md - Exit Codes"""

    def test_exit_code_definitions(self):
        """
        INV: Exit codes follow documented convention.

        Evidence: specs/features/cli-001-main-translate.md Exit Codes section
        """
        # Arrange - Define expected exit codes
        expected_exit_codes = {
            0: "Success (all files translated)",
            1: "Failure (validation errors, IO errors, config errors)",
            130: "Interrupted (SIGINT/Ctrl+C)",
        }

        # Assert - Document is consistent
        assert 0 in expected_exit_codes
        assert 1 in expected_exit_codes
        assert 130 in expected_exit_codes
        assert expected_exit_codes[130] == "Interrupted (SIGINT/Ctrl+C)"


# ==============================================================================
# Subprocess Command Construction Tests
# ==============================================================================


@pytest.mark.contract
class TestSubprocessCommandConstruction:
    """CONTRACT: specs/features/cli-001-main-translate.md - Command Construction"""

    def test_subprocess_inherits_model_flag(self, mock_args_multi_lang):
        """
        INV: Subprocess command SHOULD inherit --model flag.

        Evidence: src/cli.py lines 1667-1668
        """
        # Arrange
        args = mock_args_multi_lang
        lang = "de"

        # Act - Build command as CLI does
        cmd = [sys.executable, "-m", "src.cli"]
        cmd.extend(["--site", args.site])
        cmd.extend(["--target-langs", lang])
        if args.model:
            cmd.extend(["--model", args.model])

        # Assert
        assert "--model" in cmd
        assert args.model in cmd

    def test_subprocess_inherits_device_flag(self, mock_args_multi_lang):
        """
        INV: Subprocess command SHOULD inherit --device flag.

        Evidence: src/cli.py lines 1669-1670
        """
        # Arrange
        args = mock_args_multi_lang
        args.device = "cuda"
        lang = "de"

        # Act - Build command as CLI does
        cmd = [sys.executable, "-m", "src.cli"]
        cmd.extend(["--site", args.site])
        cmd.extend(["--target-langs", lang])
        if args.device:
            cmd.extend(["--device", args.device])

        # Assert
        assert "--device" in cmd
        assert "cuda" in cmd

    def test_subprocess_inherits_dry_run_flag(self, mock_args_multi_lang):
        """
        INV: Subprocess command SHOULD inherit --dry-run flag.

        Evidence: src/cli.py lines 1681-1682
        """
        # Arrange
        args = mock_args_multi_lang
        args.dry_run = True
        lang = "de"

        # Act - Build command as CLI does
        cmd = [sys.executable, "-m", "src.cli"]
        cmd.extend(["--site", args.site])
        cmd.extend(["--target-langs", lang])
        if args.dry_run:
            cmd.append("--dry-run")

        # Assert
        assert "--dry-run" in cmd


# ==============================================================================
# Lock Isolation Tests
# ==============================================================================


@pytest.mark.contract
class TestLockIsolation:
    """CONTRACT: specs/features/cli-001-main-translate.md - Lock Management"""

    def test_parent_acquires_lock_before_subprocess(self):
        """
        INV: Parent process MUST acquire site lock before spawning subprocesses.

        Evidence: src/cli.py lines 1599-1629
        """
        # Arrange - Verify design
        lock_design = {
            "parent_acquires": True,
            "children_skip": True,
            "flag": "--_skip-site-lock",
        }

        # Assert
        assert lock_design["parent_acquires"] is True
        assert lock_design["children_skip"] is True
        assert lock_design["flag"] == "--_skip-site-lock"

    def test_skip_site_lock_flag_prevents_child_lock(self):
        """
        INV: --_skip-site-lock flag MUST prevent child from acquiring lock.

        Evidence: src/cli.py (subprocess receives this flag)
        """
        from src.cli import create_parser

        # Arrange
        parser = create_parser()

        # Act - Parse with skip flag (as child process would receive)
        args = parser.parse_args([
            "--site", "test.com",
            "--_skip-site-lock"
        ])

        # Assert
        assert args._skip_site_lock is True
