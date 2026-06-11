"""Unit tests for translation progress tracking.

Tests cover:
- Progress initialization
- Save/load roundtrip
- Marking completions and failures
- Getting pending work
- Corruption detection
- Finding latest progress
- Concurrent run isolation
- Atomic write guarantees
"""

import sys
import time
from pathlib import Path

import pytest

# Add src to path for imports
src_path = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_path))

# Import directly to avoid triggering translation_engine.__init__ imports
import importlib.util

# First load atomic_write module
spec_atomic = importlib.util.spec_from_file_location(
    "utils.atomic_write", src_path / "utils" / "atomic_write.py"
)
atomic_write_module = importlib.util.module_from_spec(spec_atomic)
sys.modules["utils.atomic_write"] = atomic_write_module
spec_atomic.loader.exec_module(atomic_write_module)

# Now load progress module (it will use fallback import for atomic_write)
spec = importlib.util.spec_from_file_location(
    "progress", src_path / "translation_engine" / "progress.py"
)
progress_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(progress_module)

ProgressTracker = progress_module.ProgressTracker
ProgressState = progress_module.ProgressState
ProgressCorruptionError = progress_module.ProgressCorruptionError


class TestProgressState:
    """Tests for ProgressState dataclass."""

    def test_state_to_dict(self):
        """Test conversion to dictionary."""
        state = ProgressState(
            run_id="test-123",
            site_id="test.site",
            source_dir="/source",
            output_dir="/output",
            target_langs=["es", "fr"],
            total_files=10,
            translations_completed=5,
        )

        d = state.to_dict()

        assert d["run_id"] == "test-123"
        assert d["site_id"] == "test.site"
        assert d["target_langs"] == ["es", "fr"]
        assert d["total_files"] == 10
        assert d["translations_completed"] == 5

    def test_state_from_dict(self):
        """Test creation from dictionary."""
        data = {
            "run_id": "test-456",
            "schema_version": "1.0",
            "site_id": "my.site",
            "source_dir": "/src",
            "output_dir": "/out",
            "target_langs": ["de"],
            "total_files": 5,
            "completed_files": {},
            "failed_files": {},
            "files_processed": 0,
            "translations_completed": 0,
            "translations_failed": 0,
            "started_at": "2025-01-01T00:00:00",
            "last_updated": "2025-01-01T00:00:00",
        }

        state = ProgressState.from_dict(data)

        assert state.run_id == "test-456"
        assert state.site_id == "my.site"
        assert state.target_langs == ["de"]

    def test_state_unsupported_version(self):
        """Test rejection of unsupported schema version."""
        data = {"run_id": "test", "schema_version": "99.0"}

        with pytest.raises(ValueError, match="Unsupported schema version"):
            ProgressState.from_dict(data)


class TestProgressTrackerInitialization:
    """Tests for ProgressTracker initialization."""

    def test_initialization_creates_directory(self, tmp_path):
        """Test progress directory is created."""
        progress_dir = tmp_path / "progress"

        assert not progress_dir.exists()

        tracker = ProgressTracker(
            progress_dir=progress_dir, site_id="test.site", target_langs=["es"]
        )

        assert progress_dir.exists()

    def test_initialization_generates_run_id(self, tmp_path):
        """Test run_id is generated if not provided."""
        tracker = ProgressTracker(progress_dir=tmp_path / "progress", site_id="test.site")

        assert tracker.run_id is not None
        assert len(tracker.run_id) == 36  # UUID format

    def test_initialization_uses_provided_run_id(self, tmp_path):
        """Test provided run_id is used."""
        tracker = ProgressTracker(
            progress_dir=tmp_path / "progress", run_id="my-custom-id", site_id="test.site"
        )

        assert tracker.run_id == "my-custom-id"

    def test_initialization_sets_state(self, tmp_path):
        """Test initial state is set correctly."""
        tracker = ProgressTracker(
            progress_dir=tmp_path / "progress",
            site_id="my.site",
            source_dir=Path("/source"),
            output_dir=Path("/output"),
            target_langs=["es", "fr", "de"],
        )

        assert tracker.state.site_id == "my.site"
        # Compare as Path objects to handle OS differences
        assert Path(tracker.state.source_dir) == Path("/source")
        assert Path(tracker.state.output_dir) == Path("/output")
        assert tracker.state.target_langs == ["es", "fr", "de"]
        assert tracker.state.translations_completed == 0


class TestProgressTrackerSaveLoad:
    """Tests for saving and loading progress."""

    def test_save_load_roundtrip(self, tmp_path):
        """Test saving and loading progress state."""
        progress_dir = tmp_path / "progress"

        # Create and save
        tracker1 = ProgressTracker(
            progress_dir=progress_dir,
            run_id="roundtrip-test",
            site_id="test.site",
            target_langs=["es", "fr"],
        )
        tracker1.initialize([Path("file1.md"), Path("file2.md")])
        tracker1.mark_completed(Path("file1.md"), "es")

        # Load in new tracker
        tracker2 = ProgressTracker(progress_dir=progress_dir, run_id="roundtrip-test")

        assert tracker2.state.site_id == "test.site"
        assert tracker2.state.total_files == 2
        assert tracker2.state.translations_completed == 1
        assert "file1.md" in tracker2.state.completed_files

    def test_progress_file_location(self, tmp_path):
        """Test progress file is created in correct location."""
        progress_dir = tmp_path / "progress"

        tracker = ProgressTracker(
            progress_dir=progress_dir, run_id="location-test", site_id="test.site"
        )
        tracker.initialize([Path("file.md")])

        expected_file = progress_dir / "progress_location-test.json"
        assert expected_file.exists()


class TestProgressTrackerCompletion:
    """Tests for marking translations as completed."""

    def test_mark_completed_single(self, tmp_path):
        """Test marking a single translation as completed."""
        tracker = ProgressTracker(
            progress_dir=tmp_path / "progress", site_id="test.site", target_langs=["es"]
        )
        tracker.initialize([Path("file.md")])

        tracker.mark_completed(Path("file.md"), "es")

        assert tracker.state.translations_completed == 1
        assert "es" in tracker.state.completed_files["file.md"]

    def test_mark_completed_multiple_langs(self, tmp_path):
        """Test completing all languages for a file."""
        tracker = ProgressTracker(
            progress_dir=tmp_path / "progress", site_id="test.site", target_langs=["es", "fr"]
        )
        tracker.initialize([Path("file.md")])

        tracker.mark_completed(Path("file.md"), "es")
        assert tracker.state.files_processed == 0  # Not done yet

        tracker.mark_completed(Path("file.md"), "fr")
        assert tracker.state.files_processed == 1  # Now complete

    def test_mark_completed_idempotent(self, tmp_path):
        """Test marking same completion twice is idempotent."""
        tracker = ProgressTracker(
            progress_dir=tmp_path / "progress", site_id="test.site", target_langs=["es"]
        )
        tracker.initialize([Path("file.md")])

        tracker.mark_completed(Path("file.md"), "es")
        tracker.mark_completed(Path("file.md"), "es")  # Again

        assert tracker.state.translations_completed == 1  # Still 1

    def test_mark_completed_removes_from_failed(self, tmp_path):
        """Test completion removes entry from failed list."""
        tracker = ProgressTracker(
            progress_dir=tmp_path / "progress", site_id="test.site", target_langs=["es"]
        )
        tracker.initialize([Path("file.md")])

        # First fail, then succeed
        tracker.mark_failed(Path("file.md"), "es", "Error 1")
        assert "file.md" in tracker.state.failed_files

        tracker.mark_completed(Path("file.md"), "es")
        assert "file.md" not in tracker.state.failed_files


class TestProgressTrackerFailure:
    """Tests for marking translations as failed."""

    def test_mark_failed(self, tmp_path):
        """Test marking a translation as failed."""
        tracker = ProgressTracker(
            progress_dir=tmp_path / "progress", site_id="test.site", target_langs=["es"]
        )
        tracker.initialize([Path("file.md")])

        tracker.mark_failed(Path("file.md"), "es", "Connection timeout")

        assert tracker.state.translations_failed == 1
        assert tracker.state.failed_files["file.md"]["es"] == "Connection timeout"

    def test_mark_failed_multiple_langs(self, tmp_path):
        """Test multiple failures for same file."""
        tracker = ProgressTracker(
            progress_dir=tmp_path / "progress", site_id="test.site", target_langs=["es", "fr"]
        )
        tracker.initialize([Path("file.md")])

        tracker.mark_failed(Path("file.md"), "es", "Error 1")
        tracker.mark_failed(Path("file.md"), "fr", "Error 2")

        assert tracker.state.translations_failed == 2
        assert tracker.state.failed_files["file.md"]["es"] == "Error 1"
        assert tracker.state.failed_files["file.md"]["fr"] == "Error 2"


class TestProgressTrackerPending:
    """Tests for getting pending work."""

    def test_get_pending_all(self, tmp_path):
        """Test all work is pending initially."""
        tracker = ProgressTracker(
            progress_dir=tmp_path / "progress", site_id="test.site", target_langs=["es", "fr"]
        )

        files = [Path("file1.md"), Path("file2.md")]
        tracker.initialize(files)

        pending = tracker.get_pending(files)

        # 2 files * 2 langs = 4 pending
        assert len(pending) == 4

    def test_get_pending_partial(self, tmp_path):
        """Test pending excludes completed work."""
        tracker = ProgressTracker(
            progress_dir=tmp_path / "progress", site_id="test.site", target_langs=["es", "fr"]
        )

        files = [Path("file1.md"), Path("file2.md")]
        tracker.initialize(files)

        # Complete one translation
        tracker.mark_completed(Path("file1.md"), "es")

        pending = tracker.get_pending(files)

        # 4 - 1 = 3 pending
        assert len(pending) == 3
        assert (Path("file1.md"), "es") not in pending

    def test_get_pending_none(self, tmp_path):
        """Test no pending when all complete."""
        tracker = ProgressTracker(
            progress_dir=tmp_path / "progress", site_id="test.site", target_langs=["es"]
        )

        files = [Path("file.md")]
        tracker.initialize(files)
        tracker.mark_completed(Path("file.md"), "es")

        pending = tracker.get_pending(files)

        assert len(pending) == 0


class TestProgressTrackerStatistics:
    """Tests for progress statistics."""

    def test_get_statistics(self, tmp_path):
        """Test statistics calculation."""
        tracker = ProgressTracker(
            progress_dir=tmp_path / "progress",
            run_id="stats-test",
            site_id="test.site",
            target_langs=["es", "fr"],
        )

        files = [Path("file1.md"), Path("file2.md")]
        tracker.initialize(files)
        tracker.mark_completed(Path("file1.md"), "es")
        tracker.mark_failed(Path("file2.md"), "fr", "Error")

        stats = tracker.get_statistics()

        assert stats["run_id"] == "stats-test"
        assert stats["site_id"] == "test.site"
        assert stats["total_files"] == 2
        assert stats["translations_completed"] == 1
        assert stats["translations_failed"] == 1
        assert stats["translations_pending"] == 3  # 4 total - 1 completed = 3 pending
        assert stats["progress_percent"] == 25.0  # 1 of 4

    def test_is_complete_true(self, tmp_path):
        """Test is_complete when all done."""
        tracker = ProgressTracker(
            progress_dir=tmp_path / "progress", site_id="test.site", target_langs=["es"]
        )
        tracker.initialize([Path("file.md")])
        tracker.mark_completed(Path("file.md"), "es")

        assert tracker.is_complete() is True

    def test_is_complete_false(self, tmp_path):
        """Test is_complete when work remains."""
        tracker = ProgressTracker(
            progress_dir=tmp_path / "progress", site_id="test.site", target_langs=["es", "fr"]
        )
        tracker.initialize([Path("file.md")])
        tracker.mark_completed(Path("file.md"), "es")

        assert tracker.is_complete() is False


class TestProgressTrackerClear:
    """Tests for clearing progress."""

    def test_clear_removes_file(self, tmp_path):
        """Test clear removes progress file."""
        progress_dir = tmp_path / "progress"

        tracker = ProgressTracker(
            progress_dir=progress_dir, run_id="clear-test", site_id="test.site"
        )
        tracker.initialize([Path("file.md")])

        progress_file = progress_dir / "progress_clear-test.json"
        assert progress_file.exists()

        tracker.clear()

        assert not progress_file.exists()

    def test_clear_nonexistent_ok(self, tmp_path):
        """Test clear on non-existent file doesn't error."""
        tracker = ProgressTracker(progress_dir=tmp_path / "progress", site_id="test.site")
        # Don't initialize (no file created)

        tracker.clear()  # Should not raise


class TestProgressTrackerCorruption:
    """Tests for corruption detection."""

    def test_detect_invalid_json(self, tmp_path):
        """Test detection of invalid JSON."""
        progress_dir = tmp_path / "progress"
        progress_dir.mkdir()

        # Write invalid JSON
        progress_file = progress_dir / "progress_corrupt-test.json"
        progress_file.write_text("not valid json {{{")

        with pytest.raises(ProgressCorruptionError, match="invalid JSON"):
            ProgressTracker(progress_dir=progress_dir, run_id="corrupt-test")

    def test_detect_missing_fields(self, tmp_path):
        """Test detection of missing required fields."""
        progress_dir = tmp_path / "progress"
        progress_dir.mkdir()

        # Write JSON missing required field
        progress_file = progress_dir / "progress_missing-test.json"
        progress_file.write_text('{"some_field": "value"}')

        with pytest.raises(ProgressCorruptionError):
            ProgressTracker(progress_dir=progress_dir, run_id="missing-test")


class TestProgressTrackerFindLatest:
    """Tests for finding latest progress."""

    def test_find_latest_returns_most_recent(self, tmp_path):
        """Test find_latest returns most recent for site."""
        progress_dir = tmp_path / "progress"

        # Create older progress
        tracker1 = ProgressTracker(
            progress_dir=progress_dir, run_id="older", site_id="test.site", target_langs=["es"]
        )
        tracker1.initialize([Path("file.md")])

        # Wait a bit
        time.sleep(0.1)

        # Create newer progress
        tracker2 = ProgressTracker(
            progress_dir=progress_dir, run_id="newer", site_id="test.site", target_langs=["es"]
        )
        tracker2.initialize([Path("file.md")])
        tracker2.mark_completed(Path("file.md"), "es")

        # Find latest
        latest = ProgressTracker.find_latest(progress_dir, "test.site")

        assert latest is not None
        assert latest.run_id == "newer"
        assert latest.state.translations_completed == 1

    def test_find_latest_filters_by_site(self, tmp_path):
        """Test find_latest only returns matching site."""
        progress_dir = tmp_path / "progress"

        # Create progress for different sites
        tracker1 = ProgressTracker(
            progress_dir=progress_dir, run_id="site-a", site_id="site.a", target_langs=["es"]
        )
        tracker1.initialize([Path("file.md")])

        tracker2 = ProgressTracker(
            progress_dir=progress_dir, run_id="site-b", site_id="site.b", target_langs=["es"]
        )
        tracker2.initialize([Path("file.md")])

        # Find for site.a
        latest = ProgressTracker.find_latest(progress_dir, "site.a")

        assert latest is not None
        assert latest.run_id == "site-a"

    def test_find_latest_returns_none_no_match(self, tmp_path):
        """Test find_latest returns None when no match."""
        progress_dir = tmp_path / "progress"

        tracker = ProgressTracker(
            progress_dir=progress_dir, site_id="other.site", target_langs=["es"]
        )
        tracker.initialize([Path("file.md")])

        latest = ProgressTracker.find_latest(progress_dir, "nonexistent.site")

        assert latest is None

    def test_find_latest_empty_dir(self, tmp_path):
        """Test find_latest with empty directory."""
        progress_dir = tmp_path / "progress"
        progress_dir.mkdir()

        latest = ProgressTracker.find_latest(progress_dir, "any.site")

        assert latest is None

    def test_find_latest_nonexistent_dir(self, tmp_path):
        """Test find_latest with non-existent directory."""
        progress_dir = tmp_path / "nonexistent"

        latest = ProgressTracker.find_latest(progress_dir, "any.site")

        assert latest is None


class TestProgressTrackerConcurrency:
    """Tests for concurrent run isolation."""

    def test_concurrent_runs_isolated(self, tmp_path):
        """Test multiple concurrent runs don't interfere."""
        progress_dir = tmp_path / "progress"

        # Create two concurrent trackers
        tracker1 = ProgressTracker(
            progress_dir=progress_dir, run_id="run-1", site_id="test.site", target_langs=["es"]
        )
        tracker1.initialize([Path("file1.md")])

        tracker2 = ProgressTracker(
            progress_dir=progress_dir, run_id="run-2", site_id="test.site", target_langs=["es"]
        )
        tracker2.initialize([Path("file2.md")])

        # Mark different completions
        tracker1.mark_completed(Path("file1.md"), "es")
        tracker2.mark_completed(Path("file2.md"), "es")

        # Reload and verify isolation
        reload1 = ProgressTracker(progress_dir=progress_dir, run_id="run-1")
        reload2 = ProgressTracker(progress_dir=progress_dir, run_id="run-2")

        assert "file1.md" in reload1.state.completed_files
        assert "file2.md" not in reload1.state.completed_files

        assert "file2.md" in reload2.state.completed_files
        assert "file1.md" not in reload2.state.completed_files


class TestProgressTrackerListAll:
    """Tests for listing all progress files."""

    def test_list_all(self, tmp_path):
        """Test listing all progress files."""
        progress_dir = tmp_path / "progress"

        # Create multiple progress files
        for i in range(3):
            tracker = ProgressTracker(
                progress_dir=progress_dir,
                run_id=f"run-{i}",
                site_id=f"site-{i}",
                target_langs=["es"],
            )
            tracker.initialize([Path("file.md")])
            time.sleep(0.05)  # Ensure different timestamps

        results = ProgressTracker.list_all(progress_dir)

        assert len(results) == 3
        # Should be sorted by last_updated descending
        assert results[0]["run_id"] == "run-2"

    def test_list_all_empty(self, tmp_path):
        """Test listing with no progress files."""
        progress_dir = tmp_path / "progress"
        progress_dir.mkdir()

        results = ProgressTracker.list_all(progress_dir)

        assert results == []
