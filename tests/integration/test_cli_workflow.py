"""
CLI workflow integration tests (SR-02).

These tests invoke the CLI via subprocess to verify end-to-end behavior.
Unlike test_cli.py which mocks dependencies, these tests run the actual CLI
entry point via subprocess.

Gap Resolution: GAP-SR-02 - Missing CLI workflow integration tests
"""

import subprocess
import sys

# Get the Python executable from the current environment
PYTHON_EXE = sys.executable


class TestCLIHelp:
    """Test CLI help functionality via subprocess."""

    def test_cli_help_works(self):
        """Verify CLI help is accessible via subprocess."""
        result = subprocess.run(
            [PYTHON_EXE, "-m", "src.cli", "--help"], capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, f"Help command failed with stderr: {result.stderr}"

        # Verify help output contains expected content
        help_output = result.stdout.lower()
        assert "translate" in help_output or "usage" in help_output, (
            "Help output should mention translation or usage"
        )

    def test_help_shows_validation_flags(self):
        """Verify help text includes validation flags."""
        result = subprocess.run(
            [PYTHON_EXE, "-m", "src.cli", "--help"], capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0

        help_text = result.stdout
        assert "--validation-mode" in help_text, "Help should document --validation-mode"
        assert "--disable-validation" in help_text, "Help should document --disable-validation"

    def test_help_shows_resume_flags(self):
        """Verify help text includes resume flags."""
        result = subprocess.run(
            [PYTHON_EXE, "-m", "src.cli", "--help"], capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0

        help_text = result.stdout
        # RES-02: Resume control flags should be documented
        assert "--resume" in help_text or "resume" in help_text.lower(), (
            "Help should document resume functionality"
        )


class TestCLIResumeFlag:
    """Test resume flag recognition via subprocess."""

    def test_resume_flag_recognized(self):
        """Verify --resume flag is recognized by CLI parser."""
        result = subprocess.run(
            [PYTHON_EXE, "-m", "src.cli", "--help"], capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0

        # Check if resume is documented in help
        help_text = result.stdout.lower()
        assert "--resume" in help_text or "resume" in help_text, (
            "Resume flag should be in help text"
        )

    def test_no_resume_flag_recognized(self):
        """Verify --no-resume flag is recognized by CLI parser."""
        result = subprocess.run(
            [PYTHON_EXE, "-m", "src.cli", "--help"], capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0

        help_text = result.stdout.lower()
        assert "--no-resume" in help_text or "no-resume" in help_text, (
            "--no-resume flag should be in help text"
        )

    def test_force_restart_flag_recognized(self):
        """Verify --force-restart flag is recognized by CLI parser."""
        result = subprocess.run(
            [PYTHON_EXE, "-m", "src.cli", "--help"], capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0

        help_text = result.stdout.lower()
        assert "--force-restart" in help_text or "force-restart" in help_text, (
            "--force-restart flag should be in help text"
        )

    def test_progress_dir_flag_recognized(self):
        """Verify --progress-dir flag is recognized by CLI parser."""
        result = subprocess.run(
            [PYTHON_EXE, "-m", "src.cli", "--help"], capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0

        help_text = result.stdout.lower()
        assert "--progress-dir" in help_text or "progress-dir" in help_text, (
            "--progress-dir flag should be in help text"
        )


class TestCLIBasicInvocation:
    """Test basic CLI invocation patterns via subprocess."""

    def test_cli_requires_site_argument(self):
        """Verify CLI fails gracefully when --site is missing."""
        result = subprocess.run(
            [PYTHON_EXE, "-m", "src.cli"], capture_output=True, text=True, timeout=30
        )
        # Should exit with error code
        assert result.returncode != 0, "CLI should fail when --site is missing"

        # Error message should mention required argument
        error_output = result.stderr.lower()
        assert "required" in error_output or "site" in error_output, (
            "Error should mention missing required argument"
        )

    def test_cli_accepts_minimal_valid_args(self):
        """Verify CLI accepts minimal valid arguments (though execution may fail)."""
        # This test verifies argument parsing, not full execution
        # We expect this to fail during execution (missing config, model, etc.)
        # but the argument parsing should succeed
        result = subprocess.run(
            [PYTHON_EXE, "-m", "src.cli", "--site", "test-site", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # --help should work even with --site specified
        assert result.returncode == 0, "CLI with --site and --help should succeed"

    def test_cli_validation_mode_flag_parsing(self):
        """Verify validation-mode flag values are parsed correctly."""
        # Test with --help to avoid execution, just verify parsing
        for mode in ["strict", "normal", "lenient", "off"]:
            result = subprocess.run(
                [
                    PYTHON_EXE,
                    "-m",
                    "src.cli",
                    "--site",
                    "test",
                    "--validation-mode",
                    mode,
                    "--help",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert result.returncode == 0, f"CLI should accept validation-mode={mode}"

    def test_cli_invalid_validation_mode_rejected(self):
        """Verify invalid validation-mode values are rejected."""
        result = subprocess.run(
            [
                PYTHON_EXE,
                "-m",
                "src.cli",
                "--site",
                "test",
                "--validation-mode",
                "invalid-mode",
                "--help",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # Should fail during argument parsing
        assert result.returncode != 0, "CLI should reject invalid validation-mode value"

        # Error should mention the invalid choice
        assert "invalid" in result.stderr.lower() or "choice" in result.stderr.lower(), (
            "Error should mention invalid choice"
        )

    def test_cli_max_retries_accepts_integers(self):
        """Verify --max-retries accepts integer values."""
        result = subprocess.run(
            [PYTHON_EXE, "-m", "src.cli", "--site", "test", "--max-retries", "5", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, "CLI should accept integer --max-retries"

    def test_cli_max_retries_rejects_non_integers(self):
        """Verify --max-retries rejects non-integer values."""
        result = subprocess.run(
            [
                PYTHON_EXE,
                "-m",
                "src.cli",
                "--site",
                "test",
                "--max-retries",
                "not-a-number",
                "--help",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode != 0, "CLI should reject non-integer --max-retries"


class TestCLIBooleanFlags:
    """Test boolean flag handling via subprocess."""

    def test_dry_run_flag_accepted(self):
        """Verify --dry-run flag is accepted."""
        result = subprocess.run(
            [PYTHON_EXE, "-m", "src.cli", "--site", "test", "--dry-run", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, "--dry-run should be accepted"

    def test_force_accept_flag_accepted(self):
        """Verify --force-accept flag is accepted."""
        result = subprocess.run(
            [PYTHON_EXE, "-m", "src.cli", "--site", "test", "--force-accept", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, "--force-accept should be accepted"

    def test_strict_reject_flag_accepted(self):
        """Verify --strict-reject flag is accepted."""
        result = subprocess.run(
            [PYTHON_EXE, "-m", "src.cli", "--site", "test", "--strict-reject", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, "--strict-reject should be accepted"

    def test_enable_terminology_flag_accepted(self):
        """Verify --enable-terminology flag is accepted."""
        result = subprocess.run(
            [PYTHON_EXE, "-m", "src.cli", "--site", "test", "--enable-terminology", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, "--enable-terminology should be accepted"

    def test_disable_validation_flag_accepted(self):
        """Verify --disable-validation flag is accepted."""
        result = subprocess.run(
            [PYTHON_EXE, "-m", "src.cli", "--site", "test", "--disable-validation", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, "--disable-validation should be accepted"


class TestCLIFlagCombinations:
    """Test combinations of CLI flags via subprocess."""

    def test_multiple_validation_flags_combined(self):
        """Verify multiple validation flags can be combined."""
        result = subprocess.run(
            [
                PYTHON_EXE,
                "-m",
                "src.cli",
                "--site",
                "test",
                "--validation-mode",
                "strict",
                "--max-retries",
                "3",
                "--save-rejected",
                "--help",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, "CLI should accept multiple validation flags"

    def test_resume_flags_combined(self):
        """Verify resume-related flags can be combined."""
        result = subprocess.run(
            [
                PYTHON_EXE,
                "-m",
                "src.cli",
                "--site",
                "test",
                "--resume",
                "--progress-dir",
                "/tmp/progress",
                "--help",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, "CLI should accept resume flags combination"

    def test_terminology_flags_combined(self):
        """Verify terminology flags can be combined."""
        result = subprocess.run(
            [
                PYTHON_EXE,
                "-m",
                "src.cli",
                "--site",
                "test",
                "--enable-terminology",
                "--terminology-mode",
                "both",
                "--terminology-config",
                "/tmp/terminology.yaml",
                "--help",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, "CLI should accept terminology flags combination"


class TestCLIExecutionAbort:
    """Test CLI behavior when execution is aborted early."""

    def test_cli_with_nonexistent_config_fails_gracefully(self):
        """Verify CLI fails gracefully with clear error for missing config."""
        # Use a site that likely doesn't exist in config
        result = subprocess.run(
            [
                PYTHON_EXE,
                "-m",
                "src.cli",
                "--site",
                "nonexistent-test-site-12345",
                "--config-root",
                "/tmp/nonexistent-config",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # Should fail, but not crash
        assert result.returncode != 0, "CLI should fail with nonexistent config"

        # Should have some error output (either stdout or stderr)
        output = (result.stdout + result.stderr).lower()
        assert len(output) > 0, "CLI should produce error output for missing config"
