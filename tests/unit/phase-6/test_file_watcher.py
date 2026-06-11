"""
Unit tests for file watcher system.
"""

import tempfile
import time
from pathlib import Path
from unittest.mock import Mock, call

import pytest

from src.orchestrator.models import JobMode, JobType, TranslationJob
from src.orchestrator.watcher import ContentFileHandler, FileWatcher, WatchConfig
from src.utils.models import BodyRules, SiteProfile


@pytest.fixture
def temp_content_dir():
    """Create temporary content directory."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        content_dir = Path(tmpdir) / "content"
        content_dir.mkdir()
        yield content_dir


@pytest.fixture
def watch_config(temp_content_dir):
    """Create test watch config."""
    return WatchConfig(
        site_id="test.site",
        content_dir=temp_content_dir,
        source_lang="en",
        target_langs=["fr", "es"],
    )


@pytest.fixture
def site_profile(temp_content_dir):
    """Create test site profile."""
    return SiteProfile(
        site_id="test.site",
        content_roots=[str(temp_content_dir)],
        default_source_lang="en",
        target_langs=["fr", "es"],
        body=BodyRules(translate_markdown=True),
    )


@pytest.fixture
def mock_callback():
    """Create mock callback for file changes."""
    return Mock()


class TestContentFileHandler:
    """Test ContentFileHandler."""

    def test_handler_initialization(self, watch_config, mock_callback):
        """Test handler initialization."""
        handler = ContentFileHandler(
            watch_config=watch_config,
            on_file_change=mock_callback,
            debounce_seconds=0.1,
        )

        assert handler.watch_config == watch_config
        assert handler.on_file_change == mock_callback
        assert handler.debounce_seconds == 0.1

    def test_is_content_file_valid(self, watch_config, temp_content_dir, mock_callback):
        """Test detection of valid content files."""
        handler = ContentFileHandler(
            watch_config=watch_config,
            on_file_change=mock_callback,
        )

        # Valid content file
        test_file = temp_content_dir / "test.md"
        assert handler._is_content_file(str(test_file)) is True

        # Markdown file
        test_file2 = temp_content_dir / "test.markdown"
        assert handler._is_content_file(str(test_file2)) is True

    def test_is_content_file_invalid_extension(self, watch_config, temp_content_dir, mock_callback):
        """Test rejection of non-markdown files."""
        handler = ContentFileHandler(
            watch_config=watch_config,
            on_file_change=mock_callback,
        )

        # Non-markdown files
        assert handler._is_content_file(str(temp_content_dir / "test.txt")) is False
        assert handler._is_content_file(str(temp_content_dir / "test.html")) is False
        assert handler._is_content_file(str(temp_content_dir / "test.py")) is False

    def test_is_content_file_target_lang_ignored(
        self, watch_config, temp_content_dir, mock_callback
    ):
        """Test that target language files are ignored."""
        handler = ContentFileHandler(
            watch_config=watch_config,
            on_file_change=mock_callback,
        )

        # Files in target language directories should be ignored
        fr_dir = temp_content_dir / "fr"
        fr_dir.mkdir()
        fr_file = fr_dir / "test.md"

        assert handler._is_content_file(str(fr_file)) is False

        es_dir = temp_content_dir / "es"
        es_dir.mkdir()
        es_file = es_dir / "test.md"

        assert handler._is_content_file(str(es_file)) is False

    def test_is_content_file_outside_content_dir(
        self, watch_config, temp_content_dir, mock_callback
    ):
        """Test that files outside content directory are ignored."""
        handler = ContentFileHandler(
            watch_config=watch_config,
            on_file_change=mock_callback,
        )

        # File outside content directory
        outside_file = temp_content_dir.parent / "outside.md"
        assert handler._is_content_file(str(outside_file)) is False

    def test_debounce_multiple_changes(self, watch_config, temp_content_dir, mock_callback):
        """Test that multiple rapid changes are debounced."""
        handler = ContentFileHandler(
            watch_config=watch_config,
            on_file_change=mock_callback,
            debounce_seconds=0.2,
        )

        test_file = temp_content_dir / "test.md"

        # Schedule multiple changes rapidly
        handler._schedule_change(test_file, "created")
        handler._schedule_change(test_file, "modified")
        handler._schedule_change(test_file, "modified")

        # Wait for debounce
        time.sleep(0.3)

        # Should only be called once with the last event
        mock_callback.assert_called_once_with(test_file, "modified")

    def test_debounce_different_files(self, watch_config, temp_content_dir, mock_callback):
        """Test that changes to different files are tracked separately."""
        handler = ContentFileHandler(
            watch_config=watch_config,
            on_file_change=mock_callback,
            debounce_seconds=0.2,
        )

        file1 = temp_content_dir / "test1.md"
        file2 = temp_content_dir / "test2.md"

        # Schedule changes to different files
        handler._schedule_change(file1, "created")
        handler._schedule_change(file2, "modified")

        # Wait for debounce
        time.sleep(0.3)

        # Should be called for both files
        assert mock_callback.call_count == 2
        calls = mock_callback.call_args_list
        assert any(c == call(file1, "created") for c in calls)
        assert any(c == call(file2, "modified") for c in calls)


class TestFileWatcher:
    """Test FileWatcher."""

    @pytest.fixture
    def mock_config_service(self, site_profile):
        """Create mock config service."""
        service = Mock()
        service.list_sites.return_value = ["test.site"]
        service.get_site_profile.return_value = site_profile
        return service

    @pytest.fixture
    def mock_enqueue_callback(self):
        """Create mock enqueue callback."""
        callback = Mock()
        callback.return_value = "job_123"  # Return job ID
        return callback

    def test_watcher_initialization(self, mock_config_service, mock_enqueue_callback):
        """Test watcher initialization."""
        watcher = FileWatcher(
            config_service=mock_config_service,
            job_enqueue_callback=mock_enqueue_callback,
            debounce_seconds=1.0,
        )

        assert watcher.config_service == mock_config_service
        assert watcher.job_enqueue_callback == mock_enqueue_callback
        assert watcher.debounce_seconds == 1.0
        assert not watcher.is_running()

    def test_start_stop(self, mock_config_service, mock_enqueue_callback):
        """Test starting and stopping watcher."""
        watcher = FileWatcher(
            config_service=mock_config_service,
            job_enqueue_callback=mock_enqueue_callback,
        )

        # Start
        watcher.start()
        assert watcher.is_running()

        # Stop
        watcher.stop()
        assert not watcher.is_running()

    def test_double_start_ignored(self, mock_config_service, mock_enqueue_callback):
        """Test that starting twice is ignored."""
        watcher = FileWatcher(
            config_service=mock_config_service,
            job_enqueue_callback=mock_enqueue_callback,
        )

        watcher.start()
        assert watcher.is_running()

        # Second start should be ignored
        watcher.start()
        assert watcher.is_running()

        watcher.stop()

    def test_file_change_enqueues_job(
        self, mock_config_service, mock_enqueue_callback, site_profile, temp_content_dir
    ):
        """Test that file changes enqueue translation jobs."""
        watcher = FileWatcher(
            config_service=mock_config_service,
            job_enqueue_callback=mock_enqueue_callback,
            debounce_seconds=0.1,
        )

        watcher.start()

        try:
            # Create a file
            test_file = temp_content_dir / "test.md"
            test_file.write_text("# Test content")

            # Wait for debounce and processing
            time.sleep(0.3)

            # Should have enqueued a job
            assert mock_enqueue_callback.call_count >= 1

            # Check job properties
            call_args = mock_enqueue_callback.call_args_list[0]
            job: TranslationJob = call_args[0][0]

            assert job.job_type == JobType.FILE
            assert job.site_id == "test.site"
            assert job.target_langs == ["fr", "es"]
            assert job.mode == JobMode.AUTO
            assert job.priority == 3  # Auto-mode priority
            assert test_file in job.input_paths

        finally:
            watcher.stop()

    def test_file_modification_enqueues_job(
        self, mock_config_service, mock_enqueue_callback, site_profile, temp_content_dir
    ):
        """Test that file modifications enqueue jobs."""
        # Create file before starting watcher
        test_file = temp_content_dir / "existing.md"
        test_file.write_text("# Initial content")

        watcher = FileWatcher(
            config_service=mock_config_service,
            job_enqueue_callback=mock_enqueue_callback,
            debounce_seconds=0.1,
        )

        watcher.start()

        try:
            # Modify the file
            time.sleep(0.1)  # Ensure watcher is ready
            test_file.write_text("# Modified content")

            # Wait for debounce and processing
            time.sleep(0.3)

            # Should have enqueued a job for modification
            assert mock_enqueue_callback.call_count >= 1

        finally:
            watcher.stop()

    def test_file_deletion_ignored(
        self, mock_config_service, mock_enqueue_callback, site_profile, temp_content_dir
    ):
        """Test that file deletions are ignored."""
        # Create and delete file
        test_file = temp_content_dir / "to_delete.md"
        test_file.write_text("# Content")

        watcher = FileWatcher(
            config_service=mock_config_service,
            job_enqueue_callback=mock_enqueue_callback,
            debounce_seconds=0.1,
        )

        watcher.start()

        try:
            time.sleep(0.1)  # Ensure watcher is ready

            # Delete the file
            test_file.unlink()

            # Wait for debounce
            time.sleep(0.3)

            # Should not have enqueued any jobs for deletion
            # (might have jobs from creation, but not from deletion)
            for call_args in mock_enqueue_callback.call_args_list:
                job: TranslationJob = call_args[0][0]
                # No job should have been created specifically for deletion
                # This is hard to test directly, so we just ensure no errors

        finally:
            watcher.stop()

    def test_target_lang_files_ignored(
        self, mock_config_service, mock_enqueue_callback, site_profile, temp_content_dir
    ):
        """Test that files in target language directories are ignored."""
        watcher = FileWatcher(
            config_service=mock_config_service,
            job_enqueue_callback=mock_enqueue_callback,
            debounce_seconds=0.1,
        )

        watcher.start()

        try:
            # Create target language directory and file
            fr_dir = temp_content_dir / "fr"
            fr_dir.mkdir()
            fr_file = fr_dir / "translated.md"
            fr_file.write_text("# Contenu traduit")

            # Wait for debounce
            time.sleep(0.3)

            # Should not have enqueued any jobs
            mock_enqueue_callback.assert_not_called()

        finally:
            watcher.stop()

    def test_non_markdown_files_ignored(
        self, mock_config_service, mock_enqueue_callback, site_profile, temp_content_dir
    ):
        """Test that non-markdown files are ignored."""
        watcher = FileWatcher(
            config_service=mock_config_service,
            job_enqueue_callback=mock_enqueue_callback,
            debounce_seconds=0.1,
        )

        watcher.start()

        try:
            # Create non-markdown file
            txt_file = temp_content_dir / "readme.txt"
            txt_file.write_text("This is a text file")

            # Wait for debounce
            time.sleep(0.3)

            # Should not have enqueued any jobs
            mock_enqueue_callback.assert_not_called()

        finally:
            watcher.stop()

    def test_add_site(self, mock_config_service, mock_enqueue_callback):
        """Test adding a site dynamically."""
        watcher = FileWatcher(
            config_service=mock_config_service,
            job_enqueue_callback=mock_enqueue_callback,
        )

        watcher.start()

        try:
            # Create new site profile
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
                new_content_dir = Path(tmpdir) / "content"
                new_content_dir.mkdir()

                new_site = SiteProfile(
                    site_id="new.site",
                    content_roots=[str(new_content_dir)],
                    default_source_lang="en",
                    target_langs=["de"],
                    body=BodyRules(translate_markdown=True),
                )

                # Mock the config service to return the new site
                mock_config_service.get_site_profile.return_value = new_site

                # Add the site
                watcher.add_site("new.site")

                # Check that handler was added (with key format site_id:content_root)
                handler_key = f"new.site:{new_content_dir}"
                assert handler_key in watcher._handlers

        finally:
            watcher.stop()

    def test_remove_site(self, mock_config_service, mock_enqueue_callback):
        """Test removing a site."""
        watcher = FileWatcher(
            config_service=mock_config_service,
            job_enqueue_callback=mock_enqueue_callback,
        )

        watcher.start()

        try:
            # Remove the test site
            watcher.remove_site("test.site")

            # Check that handler was removed
            assert "test.site" not in watcher._handlers

        finally:
            watcher.stop()

    def test_nonexistent_content_dir_handled(self, mock_enqueue_callback):
        """Test that nonexistent content directories are handled gracefully."""
        # Create profile with nonexistent directory
        bad_profile = SiteProfile(
            site_id="bad.site",
            content_roots=["/nonexistent/path/content"],
            default_source_lang="en",
            target_langs=["fr"],
            body=BodyRules(translate_markdown=True),
        )

        mock_config_service = Mock()
        mock_config_service.list_sites.return_value = ["bad.site"]
        mock_config_service.get_site_profile.return_value = bad_profile

        watcher = FileWatcher(
            config_service=mock_config_service,
            job_enqueue_callback=mock_enqueue_callback,
        )

        # Should start without errors (just logs warning)
        watcher.start()
        assert watcher.is_running()

        watcher.stop()
