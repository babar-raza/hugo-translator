"""
SR-03: Interrupt and resume verification tests.

Tests verify that:
1. Progress is saved during normal operation
2. Partial progress can be recovered
3. Resume correctly identifies pending work
"""

import json


class TestGracefulShutdown:
    """Test graceful shutdown behavior via progress persistence."""

    def test_progress_saved_on_mark_completed(self, test_environment, progress_tracker_class):
        """Verify progress is saved immediately when mark_completed is called."""
        ProgressTracker = progress_tracker_class
        env = test_environment

        tracker = ProgressTracker(
            site_id="interrupt-test",
            source_dir=env["source_dir"],
            output_dir=env["output_dir"],
            target_langs=["es"],
            progress_dir=env["progress_dir"],
        )

        tracker.state.total_files = 3
        tracker.mark_completed("file1.md", "es")

        # Verify saved immediately (auto-save behavior)
        assert tracker.progress_file.exists()

        data = json.loads(tracker.progress_file.read_text())
        assert "file1.md" in data["completed_files"]
        assert data["completed_files"]["file1.md"] == ["es"]

    def test_progress_persists_across_multiple_completions(
        self, test_environment, progress_tracker_class
    ):
        """Verify each completion is persisted."""
        ProgressTracker = progress_tracker_class
        env = test_environment

        tracker = ProgressTracker(
            site_id="multi-complete-test",
            source_dir=env["source_dir"],
            output_dir=env["output_dir"],
            target_langs=["es", "fr"],
            progress_dir=env["progress_dir"],
        )

        tracker.state.total_files = 2

        # Complete file1 for es
        tracker.mark_completed("file1.md", "es")
        data1 = json.loads(tracker.progress_file.read_text())
        assert len(data1["completed_files"]) == 1

        # Complete file1 for fr
        tracker.mark_completed("file1.md", "fr")
        data2 = json.loads(tracker.progress_file.read_text())
        assert data2["completed_files"]["file1.md"] == ["es", "fr"]

        # Complete file2 for es
        tracker.mark_completed("file2.md", "es")
        data3 = json.loads(tracker.progress_file.read_text())
        assert len(data3["completed_files"]) == 2


class TestPartialProgressRecovery:
    """Test recovery from partial progress."""

    def test_partial_progress_recoverable(self, test_environment, progress_tracker_class):
        """Verify partial progress can be recovered after simulated crash."""
        ProgressTracker = progress_tracker_class
        env = test_environment

        # Phase 1: Create initial progress (simulating work before crash)
        tracker1 = ProgressTracker(
            site_id="resume-test",
            source_dir=env["source_dir"],
            output_dir=env["output_dir"],
            target_langs=["es", "fr"],
            progress_dir=env["progress_dir"],
        )
        tracker1.state.total_files = 5
        tracker1.mark_completed("file1.md", "es")
        tracker1.mark_completed("file1.md", "fr")
        tracker1.mark_completed("file2.md", "es")

        progress_file = tracker1.progress_file

        # Phase 2: Simulate crash/restart - recover from saved state
        tracker2 = ProgressTracker.recover_progress_file(progress_file)

        assert tracker2 is not None
        assert "file1.md" in tracker2.state.completed_files
        assert "file2.md" in tracker2.state.completed_files
        assert tracker2.state.translations_completed == 3

    def test_recovery_preserves_all_fields(self, test_environment, progress_tracker_class):
        """Verify recovery preserves site_id and target_langs."""
        ProgressTracker = progress_tracker_class
        env = test_environment

        # Create progress
        tracker1 = ProgressTracker(
            site_id="field-preservation-test",
            source_dir=env["source_dir"],
            output_dir=env["output_dir"],
            target_langs=["es", "fr", "de"],
            progress_dir=env["progress_dir"],
        )
        tracker1.state.total_files = 10
        tracker1.mark_completed("doc.md", "es")

        progress_file = tracker1.progress_file

        # Recover
        tracker2 = ProgressTracker.recover_progress_file(progress_file)

        assert tracker2 is not None
        assert tracker2.state.site_id == "field-preservation-test"
        assert set(tracker2.state.target_langs) == {"es", "fr", "de"}


class TestResumeCapability:
    """Test resume from saved progress."""

    def test_pending_files_calculated_correctly(self, test_environment, progress_tracker_class):
        """Verify get_pending returns only incomplete work."""
        ProgressTracker = progress_tracker_class
        env = test_environment

        # Create test files
        files = [
            env["source_dir"] / "file1.md",
            env["source_dir"] / "file2.md",
            env["source_dir"] / "file3.md",
        ]
        for f in files:
            f.write_text("test content")

        tracker = ProgressTracker(
            site_id="pending-test",
            source_dir=env["source_dir"],
            output_dir=env["output_dir"],
            target_langs=["es", "fr"],
            progress_dir=env["progress_dir"],
        )
        tracker.state.total_files = 3

        # Complete some translations
        tracker.mark_completed(files[0], "es")
        tracker.mark_completed(files[0], "fr")  # file1 fully done
        tracker.mark_completed(files[1], "es")  # file2 partial

        # Get pending
        pending = tracker.get_pending(files)

        # Should have: file2/fr, file3/es, file3/fr
        assert len(pending) == 3
        pending_set = {(str(p[0]), p[1]) for p in pending}
        assert (str(files[1]), "fr") in pending_set
        assert (str(files[2]), "es") in pending_set
        assert (str(files[2]), "fr") in pending_set

    def test_fully_completed_files_excluded(self, test_environment, progress_tracker_class):
        """Verify fully completed files are excluded from pending."""
        ProgressTracker = progress_tracker_class
        env = test_environment

        files = [env["source_dir"] / "only_file.md"]
        files[0].write_text("content")

        tracker = ProgressTracker(
            site_id="complete-test",
            source_dir=env["source_dir"],
            output_dir=env["output_dir"],
            target_langs=["es"],
            progress_dir=env["progress_dir"],
        )
        tracker.state.total_files = 1

        # Complete the only file
        tracker.mark_completed(files[0], "es")

        # No pending work
        pending = tracker.get_pending(files)
        assert len(pending) == 0


class TestFailedFilesTracking:
    """Test that failed files are tracked for retry."""

    def test_failed_files_tracked(self, test_environment, progress_tracker_class):
        """Verify failed files are recorded with error messages."""
        ProgressTracker = progress_tracker_class
        env = test_environment

        tracker = ProgressTracker(
            site_id="failed-test",
            source_dir=env["source_dir"],
            output_dir=env["output_dir"],
            target_langs=["es"],
            progress_dir=env["progress_dir"],
        )
        tracker.state.total_files = 2

        # Mark one as failed
        tracker.mark_failed("error_file.md", "es", "Translation timeout")

        # Verify persisted
        data = json.loads(tracker.progress_file.read_text())
        assert "error_file.md" in data["failed_files"]
        assert data["failed_files"]["error_file.md"]["es"] == "Translation timeout"

    def test_failed_then_completed_removes_from_failed(
        self, test_environment, progress_tracker_class
    ):
        """Verify completing a previously failed file removes it from failed list."""
        ProgressTracker = progress_tracker_class
        env = test_environment

        tracker = ProgressTracker(
            site_id="retry-test",
            source_dir=env["source_dir"],
            output_dir=env["output_dir"],
            target_langs=["es"],
            progress_dir=env["progress_dir"],
        )
        tracker.state.total_files = 1

        # First attempt fails
        tracker.mark_failed("retry_file.md", "es", "First attempt failed")
        assert "retry_file.md" in tracker.state.failed_files

        # Second attempt succeeds
        tracker.mark_completed("retry_file.md", "es")

        # Should be in completed, not in failed
        assert "retry_file.md" in tracker.state.completed_files
        assert "retry_file.md" not in tracker.state.failed_files
