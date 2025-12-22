"""
Unit tests for cache refresh CLI flags (Phase 2 redesign: federated-splashing-panda).

Tests --force-retranslate and --cache-write-mode flags.
"""
import argparse

import pytest

from src.cli import CLIConfigOverrides, create_parser


class TestCacheRefreshFlags:
    """Test cache refresh and write behavior CLI flags."""

    def test_force_retranslate_flag_default_false(self):
        """Test --force-retranslate defaults to False."""
        parser = create_parser()
        args = parser.parse_args(["--site", "test"])
        overrides = CLIConfigOverrides(args)

        assert overrides.force_retranslate is False

    def test_force_retranslate_flag_enabled(self):
        """Test --force-retranslate when specified."""
        parser = create_parser()
        args = parser.parse_args([
            "--site", "test",
            "--force-retranslate"
        ])
        overrides = CLIConfigOverrides(args)

        assert overrides.force_retranslate is True

    def test_force_retranslate_in_engine_overrides(self):
        """Test force_retranslate always added to engine overrides."""
        parser = create_parser()
        args = parser.parse_args([
            "--site", "test",
            "--force-retranslate"
        ])
        overrides = CLIConfigOverrides(args)

        engine_overrides = overrides.get_engine_overrides()
        assert "force_retranslate" in engine_overrides
        assert engine_overrides["force_retranslate"] is True

    def test_force_retranslate_false_in_engine_overrides(self):
        """Test force_retranslate=False also in engine overrides."""
        parser = create_parser()
        args = parser.parse_args(["--site", "test"])
        overrides = CLIConfigOverrides(args)

        engine_overrides = overrides.get_engine_overrides()
        assert "force_retranslate" in engine_overrides
        assert engine_overrides["force_retranslate"] is False

    def test_cache_write_mode_default_auto(self):
        """Test --cache-write-mode defaults to 'auto'."""
        parser = create_parser()
        args = parser.parse_args(["--site", "test"])
        overrides = CLIConfigOverrides(args)

        assert overrides.cache_write_mode == "auto"

    def test_cache_write_mode_always(self):
        """Test --cache-write-mode always."""
        parser = create_parser()
        args = parser.parse_args([
            "--site", "test",
            "--cache-write-mode", "always"
        ])
        overrides = CLIConfigOverrides(args)

        assert overrides.cache_write_mode == "always"

    def test_cache_write_mode_never(self):
        """Test --cache-write-mode never."""
        parser = create_parser()
        args = parser.parse_args([
            "--site", "test",
            "--cache-write-mode", "never"
        ])
        overrides = CLIConfigOverrides(args)

        assert overrides.cache_write_mode == "never"

    def test_cache_write_mode_auto_not_in_engine_overrides(self):
        """Test cache_write_mode='auto' not added to engine overrides (default)."""
        parser = create_parser()
        args = parser.parse_args(["--site", "test"])
        overrides = CLIConfigOverrides(args)

        engine_overrides = overrides.get_engine_overrides()
        assert "cache_write_mode" not in engine_overrides

    def test_cache_write_mode_always_in_engine_overrides(self):
        """Test cache_write_mode='always' added to engine overrides."""
        parser = create_parser()
        args = parser.parse_args([
            "--site", "test",
            "--cache-write-mode", "always"
        ])
        overrides = CLIConfigOverrides(args)

        engine_overrides = overrides.get_engine_overrides()
        assert "cache_write_mode" in engine_overrides
        assert engine_overrides["cache_write_mode"] == "always"

    def test_cache_write_mode_never_in_engine_overrides(self):
        """Test cache_write_mode='never' added to engine overrides."""
        parser = create_parser()
        args = parser.parse_args([
            "--site", "test",
            "--cache-write-mode", "never"
        ])
        overrides = CLIConfigOverrides(args)

        engine_overrides = overrides.get_engine_overrides()
        assert "cache_write_mode" in engine_overrides
        assert engine_overrides["cache_write_mode"] == "never"

    def test_cache_write_mode_invalid_rejected(self):
        """Test --cache-write-mode rejects invalid values."""
        parser = create_parser()

        with pytest.raises(SystemExit):
            parser.parse_args([
                "--site", "test",
                "--cache-write-mode", "invalid"
            ])

    def test_force_retranslate_with_cache_write_mode_always(self):
        """Test --force-retranslate with --cache-write-mode always."""
        parser = create_parser()
        args = parser.parse_args([
            "--site", "test",
            "--force-retranslate",
            "--cache-write-mode", "always"
        ])
        overrides = CLIConfigOverrides(args)

        assert overrides.force_retranslate is True
        assert overrides.cache_write_mode == "always"

        engine_overrides = overrides.get_engine_overrides()
        assert engine_overrides["force_retranslate"] is True
        assert engine_overrides["cache_write_mode"] == "always"

    def test_force_retranslate_with_cache_write_mode_never(self):
        """Test --force-retranslate with --cache-write-mode never (unusual but valid)."""
        parser = create_parser()
        args = parser.parse_args([
            "--site", "test",
            "--force-retranslate",
            "--cache-write-mode", "never"
        ])
        overrides = CLIConfigOverrides(args)

        # Unusual: force retranslate but don't write to cache
        # Semantically: fresh translation but don't persist
        assert overrides.force_retranslate is True
        assert overrides.cache_write_mode == "never"
