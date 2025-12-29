"""Unit tests for CLI import compatibility (TC-BM-04)."""

import subprocess
import sys
from pathlib import Path

import pytest


def test_cli_module_mode_help():
    """Test CLI works when invoked as module (python -m src.cli)."""
    result = subprocess.run(
        [sys.executable, "-m", "src.cli", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )

    # Should succeed
    assert result.returncode == 0, f"CLI failed in module mode:\n{result.stderr}"

    # Should show usage
    assert "usage:" in result.stdout.lower() or "Usage:" in result.stdout


def test_cli_script_mode_help():
    """Test CLI works when invoked as script (python src/cli.py)."""
    cli_path = Path("src/cli.py")
    assert cli_path.exists(), "src/cli.py not found"

    result = subprocess.run(
        [sys.executable, str(cli_path), "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )

    # Should succeed
    assert result.returncode == 0, f"CLI failed in script mode:\n{result.stderr}"

    # Should show usage
    assert "usage:" in result.stdout.lower() or "Usage:" in result.stdout


def test_cli_module_mode_with_benchmarking_imports():
    """Test CLI module mode can import benchmarking modules when needed."""
    # This tests that relative imports work (from .benchmarking.storage)
    result = subprocess.run(
        [sys.executable, "-m", "src.cli", "translate", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )

    # Should succeed (translate subcommand exists)
    assert result.returncode == 0, f"CLI translate failed in module mode:\n{result.stderr}"


def test_cli_script_mode_with_benchmarking_imports():
    """Test CLI script mode can import benchmarking modules when needed."""
    # This tests that fallback imports work (from benchmarking.storage)
    cli_path = Path("src/cli.py")

    result = subprocess.run(
        [sys.executable, str(cli_path), "translate", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )

    # Should succeed (translate subcommand exists)
    assert result.returncode == 0, f"CLI translate failed in script mode:\n{result.stderr}"
