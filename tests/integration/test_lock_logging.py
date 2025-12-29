"""Lock logging verification tests."""
import subprocess
import sys
from pathlib import Path
import pytest


def test_parent_lock_logging(tmp_path):
    """Test parent lock acquisition logs correctly."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "test.md").write_text("# Test\n")

    result = subprocess.run(
        [
            sys.executable, "-m", "src.cli",
            "--site", "test.log.net",
            "--source", str(source_dir),
            "--output", str(tmp_path / "output"),
            "--target-langs", "ar,bg",
            "--skip-tm",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )

    output = result.stdout + result.stderr

    # Verify parent lock messages
    assert "Acquiring site lock for test.log.net" in output
    assert "Site lock acquired by parent process" in output
    assert "Releasing site lock" in output or "Cleaning up parent lock" in output

    # Verify child skip messages
    assert output.count("Skipping site lock acquisition") >= 2  # One per language


def test_diagnostic_command_logging(tmp_path):
    """Test diagnose-lock command produces expected output."""
    result = subprocess.run(
        [
            sys.executable, "-m", "src.cli",
            "diagnose-lock",
            "--site", "test.diag.net",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )

    output = result.stdout + result.stderr

    # Verify diagnostic output structure
    assert "Lock Diagnostics" in output or "LOCK DIAGNOSTICS" in output
    assert "test.diag.net" in output
    assert "Lock Path:" in output or "Lock Exists:" in output


def test_unlock_command_logging(tmp_path):
    """Test unlock command produces expected output."""
    # Create a test lock
    lock_dir = Path(".translation_progress/locks")
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_file = lock_dir / "test.unlock.net.lock"
    lock_file.write_text("999999")  # Dead PID

    try:
        result = subprocess.run(
            [
                sys.executable, "-m", "src.cli",
                "unlock",
                "--site", "test.unlock.net",
                "--yes",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        output = result.stdout + result.stderr

        # Verify unlock output
        assert "Successfully unlocked" in output or "Force unlocked" in output
        assert "test.unlock.net" in output

        # Verify lock removed
        assert not lock_file.exists(), "Lock file not removed"

    finally:
        # Cleanup
        if lock_file.exists():
            lock_file.unlink()
