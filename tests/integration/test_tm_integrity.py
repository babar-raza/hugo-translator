"""TM integrity tests after concurrent writes."""
import json
import subprocess
import sys
import time
from pathlib import Path
import pytest


@pytest.fixture
def tm_snapshot(tmp_path):
    """Create TM snapshot before/after test."""
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()

    def _snapshot(name: str) -> Path:
        snapshot_file = snapshot_dir / f"{name}.json"
        subprocess.run(
            [
                sys.executable,
                "scripts/verify_tm_integrity.py",
                "--snapshot", str(snapshot_file),
            ],
            check=True,
        )
        return snapshot_file

    return _snapshot


def test_tm_integrity_after_concurrent_writes(tmp_path, tm_snapshot):
    """Test TM integrity after multi-language concurrent writes."""
    # Create test corpus
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "test.md").write_text("# Test\n\nHello world.\n")

    output_dir = tmp_path / "output"

    # Snapshot before
    before = tm_snapshot("before")

    # Run multi-language translation (5 concurrent subprocesses)
    result = subprocess.run(
        [
            sys.executable, "-m", "src.cli",
            "--site", "test.tm.net",
            "--source", str(source_dir),
            "--output", str(output_dir),
            "--target-langs", "ar,bg,cs,da,de",
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )

    assert result.returncode == 0, f"Translation failed: {result.stderr}"

    # Snapshot after
    after = tm_snapshot("after")

    # Compare snapshots
    result = subprocess.run(
        [
            sys.executable,
            "scripts/verify_tm_integrity.py",
            "--snapshot", str(after),
            "--compare", str(before),
        ],
        capture_output=True,
        text=True,
    )

    # Verify integrity (exit code 0 = no corruption)
    assert result.returncode == 0, f"TM integrity check failed:\n{result.stdout}"

    # Verify increase in TM entries (translations should add to TM)
    before_data = json.loads(before.read_text())
    after_data = json.loads(after.read_text())

    # L2 should have more entries
    if before_data.get("l2", {}).get("status") == "ok":
        before_l2 = before_data["l2"]["entry_count"]
        after_l2 = after_data["l2"]["entry_count"]
        assert after_l2 >= before_l2, f"L2 entries decreased: {before_l2} → {after_l2}"


def test_l3_lock_protection_under_load(tmp_path):
    """Test L3 save_index lock protection under concurrent writes."""
    # This test specifically stresses L3 saves with concurrent processes
    source_dir = tmp_path / "source"
    source_dir.mkdir()

    # Create corpus that triggers L3 save_interval
    for i in range(10):
        (source_dir / f"test{i}.md").write_text(f"# Test {i}\n\nContent {i}.\n")

    output_dir = tmp_path / "output"

    # Run with save_interval=5 to trigger multiple saves during translation
    result = subprocess.run(
        [
            sys.executable, "-m", "src.cli",
            "--site", "test.l3.net",
            "--source", str(source_dir),
            "--output", str(output_dir),
            "--target-langs", "ar,bg,cs,da,de",
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )

    assert result.returncode == 0, f"Translation failed: {result.stderr}"

    # Verify no L3 lock timeout errors
    assert "L3 save_index failed" not in result.stderr, \
        "L3 save encountered lock timeout"
    assert "Lock acquisition timeout" not in result.stderr, \
        "L3 lock timeout detected"

    # Verify L3 index is loadable
    result = subprocess.run(
        [
            sys.executable,
            "scripts/verify_tm_integrity.py",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"L3 integrity check failed: {result.stdout}"
