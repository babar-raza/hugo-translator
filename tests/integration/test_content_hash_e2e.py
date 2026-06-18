"""End-to-end integration tests for content hash tracking (CHT-06)."""

import time
from unittest.mock import patch

import pytest

from src.utils.content_hash import compute_file_hash
from src.utils.metadata_tracker import MetadataTracker


def test_e2e_touch_without_changes_skip(tmp_path):
    """E2E: Touch file without changes → skip translation (hash detects no change)."""
    # Setup
    source_file = tmp_path / "source.md"
    output_file = tmp_path / "output.md"
    metadata_file = tmp_path / ".translation_metadata.json"

    source_file.write_text("# Test\n\nContent here.")
    output_file.write_text("# Prueba\n\nContenido aquí.")

    # Create metadata tracker and record initial state
    tracker = MetadataTracker(metadata_file, hash_algorithm="md5")
    tracker.load()
    source_hash = tracker.update_source(source_file)
    tracker.update_output(source_file, output_file, "es", source_hash, "success")
    tracker.save()

    # Touch file (changes mtime but not content)
    time.sleep(0.01)  # Ensure mtime will change
    source_file.touch()

    # Check if translation should be skipped
    changed, reason = tracker.check_source_changed(source_file, fast_path_mtime=False)

    # Should NOT be changed (hash match)
    assert changed is False
    assert "unchanged" in reason
    assert "hash match" in reason


def test_e2e_content_modification_retranslate(tmp_path):
    """E2E: Modify file content → retranslate (hash detects change)."""
    # Setup
    source_file = tmp_path / "source.md"
    output_file = tmp_path / "output.md"
    metadata_file = tmp_path / ".translation_metadata.json"

    source_file.write_text("# Test\n\nOriginal content.")
    output_file.write_text("# Prueba\n\nContenido original.")

    # Create metadata tracker and record initial state
    tracker = MetadataTracker(metadata_file, hash_algorithm="md5")
    tracker.load()
    source_hash = tracker.update_source(source_file)
    tracker.update_output(source_file, output_file, "es", source_hash, "success")
    tracker.save()

    # Modify content
    source_file.write_text("# Test\n\nModified content!")

    # Check if translation should be skipped
    changed, reason = tracker.check_source_changed(source_file, fast_path_mtime=False)

    # Should be changed (hash mismatch)
    assert changed is True
    assert "changed" in reason


def test_e2e_metadata_persistence_across_sessions(tmp_path):
    """E2E: Metadata survives tracker restart (load/save cycle)."""
    # Setup
    source_file = tmp_path / "source.md"
    output_file = tmp_path / "output.md"
    metadata_file = tmp_path / ".translation_metadata.json"

    source_file.write_text("# Test\n\nContent.")
    output_file.write_text("# Prueba\n\nContenido.")

    # Session 1: Create and save metadata
    tracker1 = MetadataTracker(metadata_file, hash_algorithm="md5", site_id="test")
    tracker1.load()
    source_hash = tracker1.update_source(source_file)
    tracker1.update_output(source_file, output_file, "es", source_hash, "success")
    tracker1.save()

    # Session 2: New tracker instance, load from disk
    tracker2 = MetadataTracker(metadata_file, hash_algorithm="md5", site_id="test")
    tracker2.load()

    # Should have the same hash
    loaded_hash = tracker2.get_source_hash(source_file)
    assert loaded_hash == source_hash
    assert loaded_hash is not None

    # Should detect no changes
    changed, reason = tracker2.check_source_changed(source_file, fast_path_mtime=False)
    assert changed is False


def test_e2e_graceful_degradation_on_corruption(tmp_path):
    """E2E: Corrupted metadata → gracefully recover with empty state."""
    # Setup
    source_file = tmp_path / "source.md"
    metadata_file = tmp_path / ".translation_metadata.json"

    source_file.write_text("# Test\n\nContent.")

    # Create valid metadata first
    tracker1 = MetadataTracker(metadata_file, hash_algorithm="md5")
    tracker1.load()
    tracker1.update_source(source_file)
    tracker1.save()

    # Corrupt the metadata file
    metadata_file.write_text("{invalid json content")

    # Load with new tracker (should recover gracefully)
    tracker2 = MetadataTracker(metadata_file, hash_algorithm="md5")
    tracker2.load()  # Should not crash

    # Should be in clean state
    stored_hash = tracker2.get_source_hash(source_file)
    assert stored_hash is None  # Metadata was reset

    # Should detect as first run
    changed, reason = tracker2.check_source_changed(source_file)
    assert changed is True
    assert "first run" in reason


def test_e2e_fast_path_mtime_optimization(tmp_path):
    """E2E: Fast-path mtime check skips hash recomputation."""
    # Setup
    source_file = tmp_path / "source.md"
    metadata_file = tmp_path / ".translation_metadata.json"

    source_file.write_text("# Test\n\nContent.")

    # Create metadata with initial hash
    tracker = MetadataTracker(metadata_file, hash_algorithm="md5")
    tracker.load()
    tracker.update_source(source_file)
    tracker.save()

    # Check with fast_path enabled (should use mtime, not recompute hash)
    with patch("src.utils.metadata_tracker.compute_file_hash") as mock_hash:
        changed, reason = tracker.check_source_changed(source_file, fast_path_mtime=True)

        # Should NOT have called compute_file_hash (fast path used mtime)
        mock_hash.assert_not_called()
        assert changed is False


def test_e2e_output_integrity_tracking(tmp_path):
    """E2E: Track output file hashes for integrity validation."""
    # Setup
    source_file = tmp_path / "source.md"
    output_file = tmp_path / "output.md"
    metadata_file = tmp_path / ".translation_metadata.json"

    source_file.write_text("# Test\n\nContent.")
    output_file.write_text("# Prueba\n\nContenido.")

    # Create metadata tracker
    tracker = MetadataTracker(metadata_file, hash_algorithm="md5")
    tracker.load()

    # Record source and output
    source_hash = tracker.update_source(source_file)
    tracker.update_output(source_file, output_file, "es", source_hash, "success")
    tracker.save()

    # Verify output metadata was recorded
    file_metadata = tracker._data.get(str(source_file))
    assert file_metadata is not None
    assert "es" in file_metadata.outputs
    assert file_metadata.outputs["es"].status == "success"
    assert file_metadata.outputs["es"].source_hash_at_translation == source_hash


def test_e2e_multi_language_tracking(tmp_path):
    """E2E: Track multiple output languages for same source."""
    # Setup
    source_file = tmp_path / "source.md"
    output_es = tmp_path / "output_es.md"
    output_fr = tmp_path / "output_fr.md"
    metadata_file = tmp_path / ".translation_metadata.json"

    source_file.write_text("# Test\n\nContent.")
    output_es.write_text("# Prueba\n\nContenido.")
    output_fr.write_text("# Test\n\nContenu.")

    # Create metadata tracker
    tracker = MetadataTracker(metadata_file, hash_algorithm="md5")
    tracker.load()

    # Record source and multiple outputs
    source_hash = tracker.update_source(source_file)
    tracker.update_output(source_file, output_es, "es", source_hash, "success")
    tracker.update_output(source_file, output_fr, "fr", source_hash, "success")
    tracker.save()

    # Verify both outputs tracked
    file_metadata = tracker._data.get(str(source_file))
    assert file_metadata is not None
    assert "es" in file_metadata.outputs
    assert "fr" in file_metadata.outputs
    assert file_metadata.outputs["es"].status == "success"
    assert file_metadata.outputs["fr"].status == "success"


def test_e2e_schema_validation(tmp_path):
    """E2E: Validate metadata schema version on load."""
    # Setup
    source_file = tmp_path / "source.md"
    metadata_file = tmp_path / ".translation_metadata.json"

    source_file.write_text("# Test")

    # Create valid metadata
    tracker1 = MetadataTracker(metadata_file, hash_algorithm="md5", site_id="test")
    tracker1.load()
    tracker1.update_source(source_file)
    tracker1.save()

    # Verify schema version in saved file
    import json

    with open(metadata_file) as f:
        data = json.load(f)

    assert data["schema_version"] == "1.0"
    assert data["site_id"] == "test"
    assert "tracking_config" in data
    assert data["tracking_config"]["hash_algorithm"] == "md5"


@pytest.mark.flaky(reruns=3, reruns_delay=1)
def test_e2e_hash_performance(tmp_path):
    """E2E: 10MB file should hash in reasonable time (<100ms)."""
    # Create 10MB test file
    test_file = tmp_path / "large.bin"
    content = b"X" * (10 * 1024 * 1024)  # 10 MB
    test_file.write_bytes(content)

    # Measure hash computation time
    start = time.perf_counter()
    hash_result = compute_file_hash(test_file, algorithm="md5")
    elapsed_ms = (time.perf_counter() - start) * 1000

    # Verify result and performance
    assert len(hash_result) == 32  # MD5 hex digest
    assert elapsed_ms < 100, f"Hash took {elapsed_ms:.1f}ms (expected <100ms)"
