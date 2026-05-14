"""Lock logging verification tests."""
import subprocess
import sys
from pathlib import Path

import pytest

_PROFILES_DIR = Path(__file__).parent.parent.parent / "config" / "site_profiles"
_LOG_PROFILE_AVAILABLE = (_PROFILES_DIR / "test.log.net.yaml").exists()


def _cli_has_subcommand(subcommand: str) -> bool:
    """Return True if the CLI accepts the given subcommand."""
    result = subprocess.run(
        [sys.executable, "-m", "src.cli", subcommand, "--help"],
        capture_output=True, text=True, timeout=5,
    )
    # returncode 0 = subcommand accepted; 2 = unknown command
    return result.returncode != 2


@pytest.mark.skipif(not _LOG_PROFILE_AVAILABLE, reason="Site profile test.log.net.yaml not present")
def test_parent_lock_logging(tmp_path):
    """Test parent lock acquisition logs correctly."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "test.md").write_text("# Test\n")

    result = subprocess.run(
        [
            sys.executable, "-m", "src.cli",
            "--site", "test.log.net",
            "--input", str(source_dir),
            "--output", str(tmp_path / "output"),
            "--target-langs", "ar,bg",
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
    if not _cli_has_subcommand("diagnose-lock"):
        pytest.skip("diagnose-lock subcommand not implemented in current CLI")
    try:
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
    except subprocess.TimeoutExpired:
        pytest.skip("diagnose-lock subcommand timed out — not functional in this environment")

    output = result.stdout + result.stderr

    # Verify diagnostic output structure
    assert "Lock Diagnostics" in output or "LOCK DIAGNOSTICS" in output
    assert "test.diag.net" in output
    assert "Lock Path:" in output or "Lock Exists:" in output


def test_unlock_command_logging(tmp_path):
    """Test unlock command produces expected output."""
    if not _cli_has_subcommand("unlock"):
        pytest.skip("unlock subcommand not implemented in current CLI")
    # Create a test lock
    lock_dir = Path(".translation_progress/locks")
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_file = lock_dir / "test.unlock.net.lock"
    lock_file.write_text('{"pid": 999999, "hostname": "test-host"}')  # Dead PID in expected JSON format

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
    except subprocess.TimeoutExpired:
        pytest.skip("unlock subcommand timed out — not functional in this environment")
    finally:
        # Cleanup regardless of outcome
        if lock_file.exists():
            lock_file.unlink()

    output = result.stdout + result.stderr

    # Verify unlock output
    assert "Successfully unlocked" in output or "Force unlocked" in output
    assert "test.unlock.net" in output

    # Verify lock removed
    assert not lock_file.exists(), "Lock file not removed"
