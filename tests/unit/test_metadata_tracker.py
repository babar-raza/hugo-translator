"""Unit tests for metadata tracker."""

import json
import pytest
from pathlib import Path
from datetime import datetime, timezone
from src.utils.metadata_tracker import MetadataTracker, FileMetadata


def test_metadata_tracker_init(tmp_path):
    """Test MetadataTracker initialization."""
    metadata_file = tmp_path / "metadata.json"
    tracker = MetadataTracker(metadata_file, hash_algorithm="md5", site_id="test")

    assert tracker.metadata_file == metadata_file
    assert tracker.hash_algorithm == "md5"
    assert tracker.site_id == "test"
    assert tracker._loaded is False


def test_load_nonexistent_file(tmp_path):
    """Test loading when metadata file doesn't exist."""
    metadata_file = tmp_path / "metadata.json"
    tracker = MetadataTracker(metadata_file)

    tracker.load()

    assert tracker._loaded is True
    assert len(tracker._data) == 0


def test_load_valid_metadata(tmp_path):
    """Test loading valid metadata from disk."""
    metadata_file = tmp_path / "metadata.json"

    # Create valid metadata
    data = {
        "schema_version": "1.0",
        "site_id": "test",
        "tracking_config": {
            "hash_algorithm": "md5",
            "track_output_integrity": True,
        },
        "files": {
            "test.md": {
                "source": {
                    "path": "test.md",
                    "hash": "abc123",
                    "last_modified": "2025-01-01T00:00:00+00:00",
                    "size_bytes": 100,
                    "hash_computed_at": "2025-01-01T00:00:00+00:00",
                },
                "outputs": {
                    "es": {
                        "path": "out/es/test.md",
                        "hash": "def456",
                        "translated_at": "2025-01-01T00:01:00+00:00",
                        "source_hash_at_translation": "abc123",
                        "size_bytes": 120,
                        "status": "success",
                    }
                }
            }
        },
        "statistics": {
            "total_files_tracked": 1,
            "total_translations": 1,
            "last_updated": "2025-01-01T00:01:00+00:00",
        }
    }

    metadata_file.write_text(json.dumps(data))

    tracker = MetadataTracker(metadata_file)
    tracker.load()

    assert tracker._loaded is True
    assert len(tracker._data) == 1
    assert "test.md" in tracker._data
    assert tracker._data["test.md"].source.hash == "abc123"
    assert "es" in tracker._data["test.md"].outputs


def test_load_corrupted_metadata(tmp_path):
    """Test loading corrupted metadata (graceful recovery)."""
    metadata_file = tmp_path / "metadata.json"
    metadata_file.write_text("{invalid json")

    tracker = MetadataTracker(metadata_file)
    tracker.load()

    # Should recover gracefully with empty data
    assert tracker._loaded is True
    assert len(tracker._data) == 0


def test_save_metadata(tmp_path):
    """Test saving metadata to disk."""
    metadata_file = tmp_path / "metadata.json"
    test_file = tmp_path / "source.txt"
    test_file.write_text("Hello")

    tracker = MetadataTracker(metadata_file, site_id="test")
    tracker.load()
    tracker.update_source(test_file)
    tracker.save()

    # Verify file created
    assert metadata_file.exists()

    # Verify valid JSON
    with open(metadata_file) as f:
        data = json.load(f)

    assert data["schema_version"] == "1.0"
    assert data["site_id"] == "test"
    assert str(test_file) in data["files"]


def test_get_source_hash_not_found(tmp_path):
    """Test getting hash for non-tracked file."""
    metadata_file = tmp_path / "metadata.json"
    tracker = MetadataTracker(metadata_file)
    tracker.load()

    result = tracker.get_source_hash(Path("nonexistent.txt"))

    assert result is None


def test_update_source(tmp_path):
    """Test updating source file metadata."""
    metadata_file = tmp_path / "metadata.json"
    test_file = tmp_path / "source.txt"
    test_file.write_text("Hello")

    tracker = MetadataTracker(metadata_file, hash_algorithm="md5")
    tracker.load()

    file_hash = tracker.update_source(test_file)

    assert file_hash is not None
    assert len(file_hash) == 32  # MD5 hex digest
    assert tracker.get_source_hash(test_file) == file_hash


def test_update_output(tmp_path):
    """Test updating output file metadata."""
    metadata_file = tmp_path / "metadata.json"
    source_file = tmp_path / "source.txt"
    output_file = tmp_path / "output.txt"

    source_file.write_text("Hello")
    output_file.write_text("Hola")

    tracker = MetadataTracker(metadata_file)
    tracker.load()

    source_hash = tracker.update_source(source_file)
    tracker.update_output(source_file, output_file, "es", source_hash, "success")

    assert str(source_file) in tracker._data
    assert "es" in tracker._data[str(source_file)].outputs
    assert tracker._data[str(source_file)].outputs["es"].status == "success"


def test_check_source_changed_first_run(tmp_path):
    """Test check_source_changed for new file."""
    metadata_file = tmp_path / "metadata.json"
    test_file = tmp_path / "source.txt"
    test_file.write_text("Hello")

    tracker = MetadataTracker(metadata_file)
    tracker.load()

    changed, reason = tracker.check_source_changed(test_file)

    assert changed is True
    assert "first run" in reason


def test_check_source_unchanged(tmp_path):
    """Test check_source_changed for unchanged file."""
    metadata_file = tmp_path / "metadata.json"
    test_file = tmp_path / "source.txt"
    test_file.write_text("Hello")

    tracker = MetadataTracker(metadata_file)
    tracker.load()

    # First time: record hash
    tracker.update_source(test_file)

    # Check again: should be unchanged
    changed, reason = tracker.check_source_changed(test_file, fast_path_mtime=False)

    assert changed is False
    assert "unchanged" in reason


def test_check_source_changed_content_modified(tmp_path):
    """Test check_source_changed for modified file."""
    metadata_file = tmp_path / "metadata.json"
    test_file = tmp_path / "source.txt"
    test_file.write_text("Hello")

    tracker = MetadataTracker(metadata_file)
    tracker.load()

    # First time: record hash
    tracker.update_source(test_file)

    # Modify content
    test_file.write_text("Goodbye")

    # Check again: should be changed
    changed, reason = tracker.check_source_changed(test_file, fast_path_mtime=False)

    assert changed is True
    assert "changed" in reason


def test_fast_path_mtime_optimization(tmp_path):
    """Test fast-path mtime optimization."""
    metadata_file = tmp_path / "metadata.json"
    test_file = tmp_path / "source.txt"
    test_file.write_text("Hello")

    tracker = MetadataTracker(metadata_file)
    tracker.load()

    # Record initial hash
    tracker.update_source(test_file)

    # Check with fast_path enabled (should use mtime, not recompute hash)
    changed, reason = tracker.check_source_changed(test_file, fast_path_mtime=True)

    assert changed is False
    assert "mtime unchanged" in reason or "unchanged" in reason
