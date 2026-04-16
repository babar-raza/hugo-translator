"""
Contract test: CLI must fail (exit non-zero) when 0 files are discovered.

This prevents silent no-op successes that can hide configuration errors.
"""
import subprocess
import sys
from pathlib import Path
import tempfile
import pytest


def test_cli_exits_nonzero_on_empty_directory():
    """
    When CLI is invoked on an empty directory, it must exit with non-zero code.

    Regression guard for: bulk rollout Stage A silent failure
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create empty directory as input
        empty_input = Path(tmpdir) / "empty_input"
        empty_input.mkdir()

        empty_output = Path(tmpdir) / "empty_output"
        empty_output.mkdir()

        # Run CLI on empty directory
        result = subprocess.run(
            [
                sys.executable, "-m", "src.cli",
                "--site", "e2e-reference-fixture",
                "--input", str(empty_input),
                "--output", str(empty_output),
                "--target-langs", "fr",
                "--log-level", "ERROR",
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent,  # repo root
        )

        # Assert: CLI must return non-zero exit code
        assert result.returncode != 0, (
            f"CLI must fail when 0 files discovered. "
            f"Got exit code {result.returncode}. "
            f"stderr: {result.stderr}"
        )

        # Assert: Error message must mention no files (check both stdout and stderr)
        output = result.stdout + result.stderr
        assert ("No" in output and "files" in output) or "0" in output, (
            f"Error message should indicate 0 files. "
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


def test_cli_exits_nonzero_on_nonexistent_input():
    """
    When CLI is invoked with non-existent input path, it must exit with non-zero code.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        nonexistent_input = Path(tmpdir) / "does_not_exist"
        empty_output = Path(tmpdir) / "output"
        empty_output.mkdir()

        # Run CLI with non-existent input
        result = subprocess.run(
            [
                sys.executable, "-m", "src.cli",
                "--site", "e2e-reference-fixture",
                "--input", str(nonexistent_input),
                "--output", str(empty_output),
                "--target-langs", "fr",
                "--log-level", "ERROR",
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent,
        )

        # Assert: CLI must return non-zero exit code
        assert result.returncode != 0, (
            f"CLI must fail when input path doesn't exist. "
            f"Got exit code {result.returncode}."
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
