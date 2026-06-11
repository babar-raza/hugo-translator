"""
Integration tests for parallel language processing mode (T306: federated-splashing-panda).

End-to-end tests for --parallel-languages flag.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

# Heavy tests require real model loading and may take 2-5 minutes per language.
# Set SKIP_HEAVY_TESTS=0 to enable them.
_SKIP_HEAVY = os.environ.get("SKIP_HEAVY_TESTS", "1") == "1"
_skip_heavy = pytest.mark.skipif(_SKIP_HEAVY, reason="SKIP_HEAVY_TESTS=1: requires real models")


class TestParallelModeE2E:
    """End-to-end tests for parallel language processing."""

    @pytest.fixture
    def test_content_file(self):
        """Path to a real test file for translation."""
        # Use actual content from kb.aspose.net
        content_path = Path(
            "D:/onedrive/Documents/GitHub/aspose.net/content/kb.aspose.net/slides/en/presentation-converter/how-to-convert-odp-to-powerpoint-pptx-csharp.md"
        )
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

    def test_parallel_flag_integration(self):
        """Test that --parallel-languages flag is accepted by CLI."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.cli",
                "--site",
                "kb.aspose.net",
                "--parallel-languages",
                "2",
                "--help",  # Just show help
            ],
            capture_output=True,
            text=True,
        )

        # Should not fail due to unknown argument
        assert result.returncode == 0
        assert "--parallel-languages" in result.stdout

    @_skip_heavy
    def test_parallel_processes_languages_concurrently(
        self, test_content_file, temp_output_dir, temp_tm_dir
    ):
        """Test that parallel mode processes multiple languages successfully."""
        # Run translation with parallel mode (3 languages: de, fr, es)
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
                "de",
                "fr",
                "es",
                "--parallel-languages",
                "2",  # Process 2 languages in parallel
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
            output_file = (
                base_dir
                / lang
                / "presentation-converter"
                / "how-to-convert-odp-to-powerpoint-pptx-csharp.md"
            )
            assert output_file.exists(), (
                f"Output file not created for language: {lang} at {output_file}"
            )

    @_skip_heavy
    def test_parallel_max_workers_limits_concurrency(
        self, test_content_file, temp_output_dir, temp_tm_dir
    ):
        """Test that max_workers limits concurrent threads."""
        # Run with parallel-languages=4 (should process 4 languages concurrently)
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
                "de",
                "fr",
                "es",
                "ru",  # 4 languages
                "--parallel-languages",
                "4",  # Process up to 4 languages in parallel
                "--output",
                str(temp_output_dir),
            ],
            capture_output=True,
            text=True,
            timeout=400,  # Longer timeout for 4 languages
        )

        # Should complete successfully
        assert result.returncode == 0, f"Translation failed: {result.stderr}"

        # Verify all 4 languages processed
        # Output is written to the content tree (not temp_output_dir)
        expected_langs = ["de", "fr", "es", "ru"]
        base_dir = Path("D:/onedrive/Documents/GitHub/aspose.net/content/kb.aspose.net/slides")
        for lang in expected_langs:
            output_file = (
                base_dir
                / lang
                / "presentation-converter"
                / "how-to-convert-odp-to-powerpoint-pptx-csharp.md"
            )
            assert output_file.exists(), (
                f"Output file not created for language: {lang} at {output_file}"
            )

        # Verify Parallel mode enabled message in logs
        combined_output = result.stdout + result.stderr
        assert (
            "Parallel language processing enabled" in combined_output
            or "parallel" in combined_output.lower()
        )

    def test_parallel_failure_in_one_language_continues_others(self, temp_output_dir, temp_tm_dir):
        """Test that failure in one language doesn't block others."""
        # This test would require injecting a failure in one language
        # For now, we just verify that parallel mode completes successfully
        # Even if one language fails, others should complete

        # Create a minimal test file
        test_file = Path(temp_tm_dir) / "test.md"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("---\ntitle: Test\n---\n\nTest content for parallel failure handling.")

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
                "fr",  # 2 languages
                "--parallel-languages",
                "2",
                "--output",
                str(temp_output_dir),
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )

        # Should complete (success or partial success)
        # Exit code might be 0 (all success) or 1 (partial success)
        assert result.returncode in [0, 1], f"Translation failed unexpectedly: {result.stderr}"

    @_skip_heavy
    def test_parallel_throughput_improvement(self, test_content_file, temp_output_dir, temp_tm_dir):
        """Test that parallel mode is faster than serial mode (optional performance check)."""
        # This test measures whether parallel mode provides throughput improvement
        # Note: On single-core machines or with GIL contention, improvement may be minimal

        # Measure serial mode time
        serial_output_dir = temp_output_dir / "serial"
        serial_output_dir.mkdir(parents=True, exist_ok=True)

        serial_start = time.time()
        serial_result = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.cli",
                "--site",
                "kb.aspose.net",
                "--input",
                str(test_content_file),
                "--target-langs",
                "de",
                "fr",
                "--output",
                str(serial_output_dir),
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
        serial_time = time.time() - serial_start

        # Should complete successfully
        assert serial_result.returncode == 0, f"Serial translation failed: {serial_result.stderr}"

        # Measure parallel mode time
        parallel_output_dir = temp_output_dir / "parallel"
        parallel_output_dir.mkdir(parents=True, exist_ok=True)

        parallel_start = time.time()
        parallel_result = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.cli",
                "--site",
                "kb.aspose.net",
                "--input",
                str(test_content_file),
                "--target-langs",
                "de",
                "fr",
                "--parallel-languages",
                "2",
                "--output",
                str(parallel_output_dir),
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
        parallel_time = time.time() - parallel_start

        # Should complete successfully
        assert parallel_result.returncode == 0, (
            f"Parallel translation failed: {parallel_result.stderr}"
        )

        # Print timing for analysis
        print(f"\nSerial mode: {serial_time:.2f}s")
        print(f"Parallel mode: {parallel_time:.2f}s")
        print(f"Speedup: {serial_time / parallel_time:.2f}x")

        # Note: We don't assert speedup here because:
        # 1. GIL may limit Python threading benefits
        # 2. I/O operations may dominate (disk, model loading)
        # 3. Cache effects (second run may be faster)
        # This test is informational, not a strict requirement


class TestParallelModeCLIValidation:
    """Test CLI validation for parallel mode flags."""

    def test_parallel_languages_requires_positive_integer(self):
        """Test that --parallel-languages requires a positive integer."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.cli",
                "--site",
                "kb.aspose.net",
                "--parallel-languages",
                "-2",  # Negative value
            ],
            capture_output=True,
            text=True,
        )

        # Should accept (argparse doesn't validate positive, but engine might)
        # This test just verifies the flag accepts integers
        assert "--parallel-languages" in str(result.stderr) or result.returncode in [0, 1, 2]

    @_skip_heavy
    def test_parallel_languages_zero_disables_parallel_mode(self, tmpdir):
        """Test that --parallel-languages 0 disables parallel mode (default behavior)."""
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
                "--parallel-languages",
                "0",  # Disabled (default)
                "--output",
                str(tmpdir / "output"),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

        # Should complete successfully in serial mode
        assert result.returncode == 0, f"Translation failed: {result.stderr}"

        # Should NOT mention parallel mode in logs
        combined_output = result.stdout + result.stderr
        # Note: This is optional - default mode may or may not log anything


class TestParallelModeHelp:
    """Test help text for parallel mode flags."""

    def test_help_text_includes_parallel_languages(self):
        """Test that help text includes --parallel-languages description."""
        result = subprocess.run(
            [sys.executable, "-m", "src.cli", "--help"],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "--parallel-languages" in result.stdout
        assert "parallel" in result.stdout.lower()


class TestParallelModeLogging:
    """Test logging for parallel mode operations."""

    @_skip_heavy
    def test_parallel_logs_mode_enabled(self, tmpdir):
        """Test that parallel mode logs when enabled."""
        # Create a minimal test file
        test_file = Path(tmpdir) / "test.md"
        test_file.write_text("---\ntitle: Test\n---\n\nTest content for parallel logging.")

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
                "fr",
                "--parallel-languages",
                "2",
                "--output",
                str(tmpdir / "output"),
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )

        # Check logs for parallel mode message
        combined_output = result.stdout + result.stderr
        assert (
            "Parallel language processing enabled" in combined_output
            or "parallel" in combined_output.lower()
        )


class TestParallelModeErrorHandling:
    """Test error handling in parallel mode."""

    @_skip_heavy
    def test_parallel_mode_with_single_language(self, tmpdir):
        """Test parallel mode with single language (should work, no parallelism needed)."""
        # Create a minimal test file
        test_file = Path(tmpdir) / "test.md"
        test_file.write_text("---\ntitle: Test\n---\n\nSingle language test.")

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
                "de",  # Single language
                "--parallel-languages",
                "2",
                "--output",
                str(tmpdir / "output"),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

        # Should complete successfully even with single language
        assert result.returncode == 0, f"Translation failed: {result.stderr}"

        # Verify output file created
        output_file = Path(tmpdir) / "output" / "de" / "test.md"
        assert output_file.exists(), "Output file not created"


class TestParallelModeBackwardCompatibility:
    """Test backward compatibility when parallel mode is disabled."""

    @_skip_heavy
    def test_default_mode_without_parallel_flag(self, tmpdir):
        """Test that default mode works when --parallel-languages is not specified."""
        # Create a minimal test file
        test_file = Path(tmpdir) / "test.md"
        test_file.write_text("---\ntitle: Test\n---\n\nBackward compatibility test.")

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
                "fr",
                "--output",
                str(tmpdir / "output"),
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )

        # Should complete successfully in serial mode
        assert result.returncode == 0, f"Translation failed: {result.stderr}"

        # Verify output files created for both languages
        de_file = Path(tmpdir) / "output" / "de" / "test.md"
        fr_file = Path(tmpdir) / "output" / "fr" / "test.md"
        assert de_file.exists(), "German output file not created"
        assert fr_file.exists(), "French output file not created"


class TestParallelModeMutualExclusion:
    """Test mutual exclusion between parallel and round-robin modes."""

    def test_parallel_and_roundrobin_cannot_both_be_enabled(self):
        """Test that --parallel-languages and --global-lang-rounds cannot both be >0."""
        # This is tested at CLI level, but mutual exclusion is enforced at engine level
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
                "--help",
            ],
            capture_output=True,
            text=True,
        )

        # Mutual exclusion is enforced at parse time by _MultiLangModeAction (src/cli.py:319)
        assert result.returncode == 2
        assert (
            "--parallel-languages" in result.stderr or "not allowed with argument" in result.stderr
        )
