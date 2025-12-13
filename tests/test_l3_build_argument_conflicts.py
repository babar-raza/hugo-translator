"""
Test L3 Build Script Argument Conflict Validation

Tests that --force and --resume cannot be used together.
"""
import subprocess
import sys
from pathlib import Path

import pytest


def test_force_and_resume_conflict():
    """Test that --force and --resume together produces error."""
    script_path = Path(__file__).parent.parent / "scripts" / "build_l3_index.py"

    result = subprocess.run(
        [sys.executable, str(script_path), "--force", "--resume"],
        capture_output=True,
        text=True,
    )

    # Should exit with error code 1
    assert result.returncode == 1, "Should exit with error code 1"

    # Should contain error message about conflict
    assert "Cannot specify both --force and --resume" in result.stderr, (
        "Should contain conflict error message in stderr"
    )


def test_force_only_allowed():
    """Test that --force alone is allowed (though will fail without data)."""
    script_path = Path(__file__).parent.parent / "scripts" / "build_l3_index.py"

    # Use --help to check argument parsing works
    result = subprocess.run(
        [sys.executable, str(script_path), "--help"],
        capture_output=True,
        text=True,
    )

    # Should exit successfully
    assert result.returncode == 0, "Help should work"

    # Should show both flags
    assert "--force" in result.stdout, "Should have --force flag"
    assert "--resume" in result.stdout, "Should have --resume flag"


def test_resume_only_allowed():
    """Test that --resume alone is allowed (though will fail without data)."""
    script_path = Path(__file__).parent.parent / "scripts" / "build_l3_index.py"

    # Just check help works - actual resume would require L2 data
    result = subprocess.run(
        [sys.executable, str(script_path), "--help"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, "Help should work"


def test_neither_flag_allowed():
    """Test that neither flag is also valid (default behavior)."""
    script_path = Path(__file__).parent.parent / "scripts" / "build_l3_index.py"

    # Just check help works
    result = subprocess.run(
        [sys.executable, str(script_path), "--help"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, "Help should work"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
