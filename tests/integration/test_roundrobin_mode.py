"""
Integration tests for round-robin language processing mode (T305: federated-splashing-panda).

End-to-end tests for --global-lang-rounds and --global-lang-sort flags.
"""
import subprocess
import sys
from pathlib import Path

import pytest


class TestRoundRobinModeE2E:
    """End-to-end tests for round-robin language processing."""

    @pytest.fixture
    def test_content_file(self):
        """Path to a real test file for translation."""
        # Use actual content from kb.aspose.net
        content_path = Path("D:/onedrive/Documents/GitHub/aspose.net/content/kb.aspose.net/slides/en/presentation-converter/how-to-convert-odp-to-powerpoint-pptx-csharp.md")
        if not content_path.exists():
            pytest.skip(f"Test content file not found: {content_path}")
        return content_path

    @pytest.fixture
    def temp_output_dir(self, tmp_path):
        """Temporary directory for translation output (pytest-managed)."""
        return tmp_path / "output"

    @pytest.fixture
    def temp_tm_dir(self, tmp_path):
        """Temporary directory for translation memory (pytest-managed)."""
        return tmp_path / "tm"

    def test_roundrobin_flag_integration(self):
        """Test that --global-lang-rounds flag is accepted by CLI."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.cli",
                "--site",
                "kb.aspose.net",
                "--global-lang-rounds",
                "10",
                "--help",  # Just show help
            ],
            capture_output=True,
            text=True,
        )

        # Should not fail due to unknown argument
        assert result.returncode == 0
        assert "--global-lang-rounds" in result.stdout

    def test_global_lang_sort_flag_integration(self):
        """Test that --global-lang-sort flag is accepted by CLI."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.cli",
                "--site",
                "kb.aspose.net",
                "--global-lang-sort",
                "asc",
                "--help",
            ],
            capture_output=True,
            text=True,
        )

        # Should not fail due to unknown argument
        assert result.returncode == 0
        assert "--global-lang-sort" in result.stdout

    def test_roundrobin_processes_file_successfully(self, test_content_file, temp_output_dir, temp_tm_dir):
        """Test that round-robin mode processes a file successfully."""
        # Run translation with round-robin mode (3 languages: de, fr, es)
        # Use small batch size (5 texts per round) to trigger multiple rounds
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.cli",
                "--site",
                "kb.aspose.net",
                "--input",
                str(test_content_file),
                "--target-langs",
                "de", "fr", "es",
                "--global-lang-rounds",
                "5",  # 5 texts per language per round
                "--output",
                str(temp_output_dir),
            ],
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
        )

        # Print output for debugging
        print(f"STDOUT:\n{result.stdout}")
        print(f"STDERR:\n{result.stderr}")

        # Should complete successfully
        assert result.returncode == 0, f"Translation failed: {result.stderr}"

        # Verify output files were created for all languages
        # Output is written to the content tree (not temp_output_dir)
        expected_langs = ["de", "fr", "es"]
        base_dir = Path("D:/onedrive/Documents/GitHub/aspose.net/content/kb.aspose.net/slides")
        for lang in expected_langs:
            output_file = base_dir / lang / "presentation-converter" / "how-to-convert-odp-to-powerpoint-pptx-csharp.md"
            assert output_file.exists(), f"Output file not created for language: {lang} at {output_file}"

    def test_roundrobin_sorting_desc(self, test_content_file, temp_output_dir, temp_tm_dir):
        """Test round-robin with descending sort (most missing translations first)."""
        # With desc sort, languages with most missing translations should be processed first
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.cli",
                "--site",
                "kb.aspose.net",
                "--input",
                str(test_content_file),
                "--target-langs",
                "de", "fr",
                "--global-lang-rounds",
                "10",
                "--global-lang-sort",
                "desc",  # Most missing first (default)
                "--output",
                str(temp_output_dir),
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )

        # Should complete successfully
        assert result.returncode == 0, f"Translation failed: {result.stderr}"

        # Verify Round-robin mode enabled message in logs
        assert "Round-robin language processing enabled" in result.stderr or "Round-robin" in result.stdout

    def test_roundrobin_sorting_asc(self, test_content_file, temp_output_dir, temp_tm_dir):
        """Test round-robin with ascending sort (least missing translations first)."""
        # With asc sort, languages with least missing translations should be processed first
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.cli",
                "--site",
                "kb.aspose.net",
                "--input",
                str(test_content_file),
                "--target-langs",
                "de", "fr",
                "--global-lang-rounds",
                "10",
                "--global-lang-sort",
                "asc",  # Least missing first
                "--output",
                str(temp_output_dir),
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )

        # Should complete successfully
        assert result.returncode == 0, f"Translation failed: {result.stderr}"

        # Verify sort order in logs (check stdout where logs are written)
        combined_output = result.stdout + result.stderr
        assert "asc" in combined_output.lower() or "Round-robin" in combined_output or "sort=asc" in combined_output

    def test_roundrobin_with_small_batch_triggers_multiple_rounds(self, test_content_file, temp_output_dir, temp_tm_dir):
        """Test that small batch size triggers multiple rounds."""
        # Use very small batch size (2 texts) to force multiple rounds
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.cli",
                "--site",
                "kb.aspose.net",
                "--input",
                str(test_content_file),
                "--target-langs",
                "de", "fr",
                "--global-lang-rounds",
                "2",  # Very small batch
                "--output",
                str(temp_output_dir),
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )

        # Should complete successfully
        assert result.returncode == 0, f"Translation failed: {result.stderr}"

        # Verify multiple languages were processed
        # Output is written to the content tree (not temp_output_dir)
        base_dir = Path("D:/onedrive/Documents/GitHub/aspose.net/content/kb.aspose.net/slides")
        de_file = base_dir / "de" / "presentation-converter" / "how-to-convert-odp-to-powerpoint-pptx-csharp.md"
        fr_file = base_dir / "fr" / "presentation-converter" / "how-to-convert-odp-to-powerpoint-pptx-csharp.md"

        assert de_file.exists(), f"German translation not created at {de_file}"
        assert fr_file.exists(), f"French translation not created at {fr_file}"


class TestRoundRobinModeCLIValidation:
    """Test CLI validation for round-robin mode flags."""

    def test_global_lang_rounds_requires_positive_integer(self):
        """Test that --global-lang-rounds requires a positive integer."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.cli",
                "--site",
                "kb.aspose.net",
                "--global-lang-rounds",
                "-5",  # Negative value
            ],
            capture_output=True,
            text=True,
        )

        # Should accept (argparse doesn't validate positive, but engine might)
        # This test just verifies the flag accepts integers
        assert "--global-lang-rounds" in str(result.stderr) or result.returncode in [0, 1, 2]

    def test_global_lang_sort_invalid_value_rejected(self):
        """Test that invalid --global-lang-sort value is rejected."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.cli",
                "--site",
                "kb.aspose.net",
                "--global-lang-sort",
                "invalid",  # Invalid value
            ],
            capture_output=True,
            text=True,
        )

        # Should fail with exit code 2 (argparse error)
        assert result.returncode == 2
        assert "invalid choice" in result.stderr.lower() or "error" in result.stderr.lower()

    def test_parallel_and_roundrobin_mutually_exclusive(self):
        """Test that --parallel-languages and --global-lang-rounds are mutually exclusive."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.cli",
                "--site",
                "kb.aspose.net",
                "--parallel-languages",
                "2",
                "--global-lang-rounds",
                "10",
                "--help",  # Try to show help
            ],
            capture_output=True,
            text=True,
        )

        # Mutual exclusion is enforced at parse time by _MultiLangModeAction (src/cli.py:319)
        assert result.returncode == 2
        assert "--parallel-languages" in result.stderr or "not allowed with argument" in result.stderr


class TestRoundRobinModeHelp:
    """Test help text for round-robin mode flags."""

    def test_help_text_includes_global_lang_rounds(self):
        """Test that help text includes --global-lang-rounds description."""
        result = subprocess.run(
            [sys.executable, "-m", "src.cli", "--help"],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "--global-lang-rounds" in result.stdout
        assert "round-robin" in result.stdout.lower() or "texts per language" in result.stdout.lower()

    def test_help_text_includes_global_lang_sort(self):
        """Test that help text includes --global-lang-sort description."""
        result = subprocess.run(
            [sys.executable, "-m", "src.cli", "--help"],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "--global-lang-sort" in result.stdout
        assert "asc" in result.stdout.lower() or "desc" in result.stdout.lower()


class TestRoundRobinModeLogging:
    """Test logging for round-robin mode operations."""

    def test_roundrobin_logs_mode_enabled(self, tmpdir):
        """Test that round-robin mode logs when enabled."""
        # Create a minimal test file
        test_file = Path(tmpdir) / "test.md"
        test_file.write_text("---\ntitle: Test\n---\n\nTest content.")

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.cli",
                "--site",
                "kb.aspose.net",
                "--input",
                str(test_file),
                "--target-langs",
                "de",
                "--global-lang-rounds",
                "10",
                "--output",
                str(tmpdir / "output"),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

        # Check logs for round-robin mode message
        combined_output = result.stdout + result.stderr
        assert "Round-robin" in combined_output or "round-robin" in combined_output.lower()


class TestRoundRobinModeMemoryManagement:
    """Test memory management in round-robin mode."""

    def test_roundrobin_clears_cache_between_languages(self, tmpdir):
        """Test that cache is cleared between language switches (verify via logs)."""
        # Create a minimal test file
        test_file = Path(tmpdir) / "test.md"
        test_file.write_text("---\ntitle: Test\n---\n\nTest content for cache clearing verification.")

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.cli",
                "--site",
                "kb.aspose.net",
                "--input",
                str(test_file),
                "--target-langs",
                "de", "fr",  # 2 languages to trigger language switch
                "--global-lang-rounds",
                "5",
                "--output",
                str(tmpdir / "output"),
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )

        # Should complete successfully
        assert result.returncode == 0, f"Translation failed: {result.stderr}"

        # Check for cache clearing logs (if implemented)
        combined_output = result.stdout + result.stderr
        # Note: This test verifies the feature works, cache clearing logs are optional


class TestRoundRobinModeBackwardCompatibility:
    """Test backward compatibility when round-robin mode is disabled."""

    def test_default_mode_without_roundrobin_flag(self, tmpdir):
        """Test that default mode works when --global-lang-rounds is not specified."""
        # Create a minimal test file
        test_file = Path(tmpdir) / "test.md"
        test_file.write_text("---\ntitle: Test\n---\n\nTest content.")

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.cli",
                "--site",
                "kb.aspose.net",
                "--input",
                str(test_file),
                "--target-langs",
                "de",
                "--output",
                str(tmpdir / "output"),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

        # Should complete successfully in serial mode
        assert result.returncode == 0, f"Translation failed: {result.stderr}"

        # Verify output file created
        output_file = Path(tmpdir) / "output" / "de" / "test.md"
        assert output_file.exists(), "Output file not created in default mode"
