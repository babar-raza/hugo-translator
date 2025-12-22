"""
Unit tests for multi-language CLI flags (T301: federated-splashing-panda).

Tests --parallel-languages, --global-lang-rounds, and --global-lang-sort flags.
"""
import pytest
from src.cli import create_parser, CLIConfigOverrides


class TestMultiLanguageFlags:
    """Test multi-language processing CLI flags."""

    def test_parallel_languages_flag_default_zero(self):
        """Test --parallel-languages defaults to 0."""
        parser = create_parser()
        args = parser.parse_args(["--site", "test"])
        overrides = CLIConfigOverrides(args)

        assert overrides.parallel_languages == 0

    def test_parallel_languages_flag_parsing(self):
        """Test --parallel-languages flag parsing."""
        parser = create_parser()
        args = parser.parse_args([
            "--site", "test",
            "--parallel-languages", "4"
        ])
        overrides = CLIConfigOverrides(args)

        assert overrides.parallel_languages == 4

    def test_global_lang_rounds_flag_default_zero(self):
        """Test --global-lang-rounds defaults to 0."""
        parser = create_parser()
        args = parser.parse_args(["--site", "test"])
        overrides = CLIConfigOverrides(args)

        assert overrides.global_lang_rounds == 0

    def test_global_lang_rounds_flag_parsing(self):
        """Test --global-lang-rounds flag parsing."""
        parser = create_parser()
        args = parser.parse_args([
            "--site", "test",
            "--global-lang-rounds", "100"
        ])
        overrides = CLIConfigOverrides(args)

        assert overrides.global_lang_rounds == 100

    def test_global_lang_sort_flag_default_desc(self):
        """Test --global-lang-sort defaults to 'desc'."""
        parser = create_parser()
        args = parser.parse_args(["--site", "test"])
        overrides = CLIConfigOverrides(args)

        assert overrides.global_lang_sort == "desc"

    def test_global_lang_sort_flag_parsing_asc(self):
        """Test --global-lang-sort flag parsing with 'asc'."""
        parser = create_parser()
        args = parser.parse_args([
            "--site", "test",
            "--global-lang-sort", "asc"
        ])
        overrides = CLIConfigOverrides(args)

        assert overrides.global_lang_sort == "asc"

    def test_global_lang_sort_flag_parsing_desc(self):
        """Test --global-lang-sort flag parsing with 'desc'."""
        parser = create_parser()
        args = parser.parse_args([
            "--site", "test",
            "--global-lang-sort", "desc"
        ])
        overrides = CLIConfigOverrides(args)

        assert overrides.global_lang_sort == "desc"

    def test_global_lang_sort_invalid_value_rejected(self):
        """Test --global-lang-sort rejects invalid values."""
        parser = create_parser()

        with pytest.raises(SystemExit):
            parser.parse_args([
                "--site", "test",
                "--global-lang-sort", "invalid"
            ])

    def test_parallel_languages_in_engine_overrides(self):
        """Test parallel_languages added to engine overrides when > 0."""
        parser = create_parser()
        args = parser.parse_args([
            "--site", "test",
            "--parallel-languages", "2"
        ])
        overrides = CLIConfigOverrides(args)

        engine_overrides = overrides.get_engine_overrides()
        assert "parallel_languages" in engine_overrides
        assert engine_overrides["parallel_languages"] == 2

    def test_parallel_languages_zero_not_in_engine_overrides(self):
        """Test parallel_languages not added to engine overrides when 0 (default)."""
        parser = create_parser()
        args = parser.parse_args(["--site", "test"])
        overrides = CLIConfigOverrides(args)

        engine_overrides = overrides.get_engine_overrides()
        assert "parallel_languages" not in engine_overrides

    def test_global_lang_rounds_in_engine_overrides(self):
        """Test global_lang_rounds added to engine overrides when > 0."""
        parser = create_parser()
        args = parser.parse_args([
            "--site", "test",
            "--global-lang-rounds", "50"
        ])
        overrides = CLIConfigOverrides(args)

        engine_overrides = overrides.get_engine_overrides()
        assert "global_lang_rounds" in engine_overrides
        assert engine_overrides["global_lang_rounds"] == 50
        assert "global_lang_sort" in engine_overrides
        assert engine_overrides["global_lang_sort"] == "desc"

    def test_global_lang_rounds_zero_not_in_engine_overrides(self):
        """Test global_lang_rounds not added to engine overrides when 0 (default)."""
        parser = create_parser()
        args = parser.parse_args(["--site", "test"])
        overrides = CLIConfigOverrides(args)

        engine_overrides = overrides.get_engine_overrides()
        assert "global_lang_rounds" not in engine_overrides
        assert "global_lang_sort" not in engine_overrides

    def test_global_lang_sort_in_engine_overrides_with_rounds(self):
        """Test global_lang_sort added to engine overrides along with rounds."""
        parser = create_parser()
        args = parser.parse_args([
            "--site", "test",
            "--global-lang-rounds", "100",
            "--global-lang-sort", "asc"
        ])
        overrides = CLIConfigOverrides(args)

        engine_overrides = overrides.get_engine_overrides()
        assert "global_lang_rounds" in engine_overrides
        assert "global_lang_sort" in engine_overrides
        assert engine_overrides["global_lang_sort"] == "asc"


class TestMutualExclusion:
    """Test mutual exclusion between parallel and round-robin modes."""

    def test_parallel_and_roundrobin_mutually_exclusive(self):
        """Test that using both --parallel-languages and --global-lang-rounds raises ValueError."""
        parser = create_parser()
        args = parser.parse_args([
            "--site", "test",
            "--parallel-languages", "2",
            "--global-lang-rounds", "50"
        ])
        overrides = CLIConfigOverrides(args)

        # get_engine_overrides() should raise ValueError
        with pytest.raises(ValueError, match="Cannot use both"):
            overrides.get_engine_overrides()

    def test_parallel_only_succeeds(self):
        """Test that using only --parallel-languages succeeds."""
        parser = create_parser()
        args = parser.parse_args([
            "--site", "test",
            "--parallel-languages", "3"
        ])
        overrides = CLIConfigOverrides(args)

        # Should not raise
        engine_overrides = overrides.get_engine_overrides()
        assert "parallel_languages" in engine_overrides
        assert "global_lang_rounds" not in engine_overrides

    def test_roundrobin_only_succeeds(self):
        """Test that using only --global-lang-rounds succeeds."""
        parser = create_parser()
        args = parser.parse_args([
            "--site", "test",
            "--global-lang-rounds", "100"
        ])
        overrides = CLIConfigOverrides(args)

        # Should not raise
        engine_overrides = overrides.get_engine_overrides()
        assert "global_lang_rounds" in engine_overrides
        assert "parallel_languages" not in engine_overrides

    def test_neither_parallel_nor_roundrobin_succeeds(self):
        """Test that using neither flag succeeds (serial mode)."""
        parser = create_parser()
        args = parser.parse_args(["--site", "test"])
        overrides = CLIConfigOverrides(args)

        # Should not raise
        engine_overrides = overrides.get_engine_overrides()
        assert "parallel_languages" not in engine_overrides
        assert "global_lang_rounds" not in engine_overrides


class TestFlagCombinations:
    """Test combinations of multi-language flags with other flags."""

    def test_parallel_with_force_retranslate(self):
        """Test --parallel-languages with --force-retranslate."""
        parser = create_parser()
        args = parser.parse_args([
            "--site", "test",
            "--parallel-languages", "2",
            "--force-retranslate"
        ])
        overrides = CLIConfigOverrides(args)

        engine_overrides = overrides.get_engine_overrides()
        assert engine_overrides["parallel_languages"] == 2
        assert engine_overrides["force_retranslate"] is True

    def test_roundrobin_with_cache_write_mode(self):
        """Test --global-lang-rounds with --cache-write-mode."""
        parser = create_parser()
        args = parser.parse_args([
            "--site", "test",
            "--global-lang-rounds", "50",
            "--cache-write-mode", "always"
        ])
        overrides = CLIConfigOverrides(args)

        engine_overrides = overrides.get_engine_overrides()
        assert engine_overrides["global_lang_rounds"] == 50
        assert engine_overrides["cache_write_mode"] == "always"

    def test_parallel_with_device_and_load_mode(self):
        """Test --parallel-languages with --device and --load-mode."""
        parser = create_parser()
        args = parser.parse_args([
            "--site", "test",
            "--parallel-languages", "3",
            "--device", "cpu",
            "--load-mode", "int8"
        ])
        overrides = CLIConfigOverrides(args)

        engine_overrides = overrides.get_engine_overrides()
        assert engine_overrides["parallel_languages"] == 3
        assert overrides.device == "cpu"
        assert overrides.load_mode == "int8"
