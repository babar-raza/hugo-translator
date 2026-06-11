"""
Integration tests for cache refresh functionality (T205: federated-splashing-panda).

End-to-end tests for --force-retranslate and --cache-write-mode flags.
"""

import subprocess
from pathlib import Path

import pytest


class TestCacheRefreshE2E:
    """End-to-end tests for cache refresh functionality."""

    @pytest.fixture
    def test_fixture_path(self):
        """Path to test fixture file."""
        fixture_path = (
            Path(__file__).parent.parent / "fixtures" / "cache_refresh_test" / "sample.md"
        )
        if not fixture_path.exists():
            pytest.skip(f"Test fixture not found: {fixture_path}")
        return fixture_path

    @pytest.fixture
    def site_profile_exists(self):
        """Check if example site profile exists."""
        profile_path = Path("config/site_profiles/example.yaml")
        if not profile_path.exists():
            pytest.skip("Example site profile not found")
        return True

    def test_force_retranslate_flag_integration(self, test_fixture_path, site_profile_exists):
        """Test that --force-retranslate flag is accepted by CLI."""
        # This test only verifies the flag is accepted (doesn't require full translation environment)
        result = subprocess.run(
            [
                "python",
                "-m",
                "src.cli",
                "--site",
                "example",
                "--force-retranslate",
                "--help",  # Just show help, don't actually run
            ],
            capture_output=True,
            text=True,
        )

        # Should not fail due to unknown argument
        assert result.returncode == 0
        assert "--force-retranslate" in result.stdout

    def test_cache_write_mode_flag_integration(self, test_fixture_path, site_profile_exists):
        """Test that --cache-write-mode flag is accepted by CLI."""
        # This test only verifies the flag is accepted
        result = subprocess.run(
            [
                "python",
                "-m",
                "src.cli",
                "--site",
                "example",
                "--cache-write-mode",
                "always",
                "--help",  # Just show help
            ],
            capture_output=True,
            text=True,
        )

        # Should not fail due to unknown argument
        assert result.returncode == 0
        assert "--cache-write-mode" in result.stdout

    def test_force_retranslate_refreshes_cache(self, test_fixture_path, site_profile_exists):
        """Test --force-retranslate bypasses cache and updates it."""
        pytest.skip("Requires translation environment (model, dependencies)")

        # This test would:
        # 1. Run translation once to populate cache
        # 2. Modify translations in cache manually
        # 3. Run with --force-retranslate
        # 4. Verify cache was updated with fresh translations

    def test_cache_write_mode_always_overwrites(self, test_fixture_path, site_profile_exists):
        """Test --cache-write-mode always overwrites existing cache entries."""
        pytest.skip("Requires translation environment (model, dependencies)")

        # This test would:
        # 1. Populate cache with initial translations
        # 2. Run translation with --cache-write-mode always
        # 3. Verify cache entries were overwritten

    def test_cache_write_mode_never_readonly(self, test_fixture_path, site_profile_exists):
        """Test --cache-write-mode never runs in read-only mode (no cache writes)."""
        pytest.skip("Requires translation environment (model, dependencies)")

        # This test would:
        # 1. Clear cache
        # 2. Run translation with --cache-write-mode never
        # 3. Verify cache remains empty (no writes)

    def test_combined_force_and_write_mode(self, test_fixture_path, site_profile_exists):
        """Test combining --force-retranslate with --cache-write-mode."""
        pytest.skip("Requires translation environment (model, dependencies)")

        # This test would:
        # 1. Run with --force-retranslate --cache-write-mode always
        # 2. Verify cache bypassed and entries overwritten
        # 3. Run with --force-retranslate --cache-write-mode never
        # 4. Verify cache bypassed and no writes

    def test_backward_compatibility_default_behavior(self, test_fixture_path, site_profile_exists):
        """Test default behavior unchanged (backward compatibility)."""
        pytest.skip("Requires translation environment (model, dependencies)")

        # This test would:
        # 1. Run translation without any cache refresh flags
        # 2. Verify default behavior (cache lookup → translate if missing → store)

    def test_cache_integrity_under_refresh(self, test_fixture_path, site_profile_exists):
        """Test cache integrity maintained under all refresh modes."""
        pytest.skip("Requires translation environment (model, dependencies)")

        # This test would:
        # 1. Run multiple refresh operations
        # 2. Verify cache not corrupted
        # 3. Verify all entries valid
        # 4. Verify atomic writes (no partial entries)


class TestCacheRefreshCLIValidation:
    """Test CLI validation for cache refresh flags."""

    def test_cache_write_mode_invalid_value_rejected(self):
        """Test that invalid --cache-write-mode value is rejected."""
        result = subprocess.run(
            [
                "python",
                "-m",
                "src.cli",
                "--site",
                "example",
                "--cache-write-mode",
                "invalid",  # Invalid value
            ],
            capture_output=True,
            text=True,
        )

        # Should fail with exit code 2 (argparse error)
        assert result.returncode == 2
        assert "invalid choice" in result.stderr.lower() or "error" in result.stderr.lower()

    def test_force_retranslate_no_argument_required(self):
        """Test that --force-retranslate doesn't require an argument."""
        result = subprocess.run(
            [
                "python",
                "-m",
                "src.cli",
                "--site",
                "example",
                "--force-retranslate",
                "--help",  # Just show help
            ],
            capture_output=True,
            text=True,
        )

        # Should succeed (flag accepted)
        assert result.returncode == 0

    def test_cache_write_mode_requires_argument(self):
        """Test that --cache-write-mode requires an argument."""
        result = subprocess.run(
            [
                "python",
                "-m",
                "src.cli",
                "--site",
                "example",
                "--cache-write-mode",  # Missing argument
                "--help",
            ],
            capture_output=True,
            text=True,
        )

        # Should fail (missing required argument)
        assert result.returncode == 2


class TestCacheRefreshHelp:
    """Test help text for cache refresh flags."""

    def test_help_text_includes_force_retranslate(self):
        """Test that help text includes --force-retranslate description."""
        result = subprocess.run(
            ["python", "-m", "src.cli", "--help"],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "--force-retranslate" in result.stdout
        assert "bypass cache" in result.stdout.lower() or "force" in result.stdout.lower()

    def test_help_text_includes_cache_write_mode(self):
        """Test that help text includes --cache-write-mode description."""
        result = subprocess.run(
            ["python", "-m", "src.cli", "--help"],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "--cache-write-mode" in result.stdout
        assert (
            "auto" in result.stdout.lower()
            or "always" in result.stdout.lower()
            or "never" in result.stdout.lower()
        )

    def test_help_text_shows_cache_write_mode_choices(self):
        """Test that help text shows cache write mode choices."""
        result = subprocess.run(
            ["python", "-m", "src.cli", "--help"],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        # Should mention the three choices
        help_text = result.stdout.lower()
        assert "auto" in help_text
        assert "always" in help_text or "overwrite" in help_text
        assert "never" in help_text or "read-only" in help_text


class TestCacheRefreshLogging:
    """Test logging for cache refresh operations."""

    def test_force_retranslate_logs_bypass_message(self):
        """Test that --force-retranslate logs cache bypass message."""
        pytest.skip("Requires translation environment to see logs")

        # This test would:
        # 1. Run translation with --force-retranslate
        # 2. Capture logs
        # 3. Verify "Force retranslate enabled" message appears

    def test_cache_write_mode_logs_mode(self):
        """Test that non-default --cache-write-mode logs the mode."""
        pytest.skip("Requires translation environment to see logs")

        # This test would:
        # 1. Run translation with --cache-write-mode always
        # 2. Capture logs
        # 3. Verify "Cache write mode: always" message appears
