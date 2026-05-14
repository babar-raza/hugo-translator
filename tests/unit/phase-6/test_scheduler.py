"""
Unit tests for sweep scheduler.
"""

import tempfile
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.orchestrator.models import JobMode, JobType, TranslationJob
from src.orchestrator.scheduler import SweepScheduler, SweepStats
from src.utils.models import BodyRules, OutputLayout, SiteProfile


@pytest.fixture
def temp_content_dir():
    """Create temporary content directory structure."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        content_dir = Path(tmpdir) / "content"
        content_dir.mkdir()
        yield content_dir


@pytest.fixture
def site_profile(temp_content_dir):
    """Create test site profile."""
    return SiteProfile(
        site_id="test.site",
        content_roots=[str(temp_content_dir)],
        default_source_lang="en",
        target_langs=["fr", "es"],
        body=BodyRules(translate_markdown=True),
        output_layout=OutputLayout(per_language_folders=True),
    )


@pytest.fixture
def mock_config_service(site_profile):
    """Create mock config service."""
    service = Mock()
    service.list_sites.return_value = ["test.site"]
    service.get_site_profile.return_value = site_profile
    return service


@pytest.fixture
def mock_enqueue_callback():
    """Create mock enqueue callback."""
    callback = Mock()
    callback.return_value = "job_123"
    return callback


class TestSweepScheduler:
    """Test SweepScheduler."""

    def test_scheduler_initialization(self, mock_config_service, mock_enqueue_callback):
        """Test scheduler initialization."""
        scheduler = SweepScheduler(
            config_service=mock_config_service,
            job_enqueue_callback=mock_enqueue_callback,
            sweep_interval_minutes=30,
        )

        assert scheduler.config_service == mock_config_service
        assert scheduler.job_enqueue_callback == mock_enqueue_callback
        assert scheduler.sweep_interval_minutes == 30
        assert not scheduler.is_running()

    def test_start_stop(self, mock_config_service, mock_enqueue_callback):
        """Test starting and stopping scheduler."""
        scheduler = SweepScheduler(
            config_service=mock_config_service,
            job_enqueue_callback=mock_enqueue_callback,
            sweep_interval_minutes=60,
        )

        # Start
        scheduler.start()
        assert scheduler.is_running()

        # Stop
        scheduler.stop()
        assert not scheduler.is_running()

    def test_double_start_ignored(self, mock_config_service, mock_enqueue_callback):
        """Test that starting twice is ignored."""
        scheduler = SweepScheduler(
            config_service=mock_config_service,
            job_enqueue_callback=mock_enqueue_callback,
        )

        scheduler.start()
        assert scheduler.is_running()

        # Second start should be ignored
        scheduler.start()
        assert scheduler.is_running()

        scheduler.stop()

    def test_manual_sweep_trigger(
        self, mock_config_service, mock_enqueue_callback, temp_content_dir
    ):
        """Test manually triggering a sweep."""
        scheduler = SweepScheduler(
            config_service=mock_config_service,
            job_enqueue_callback=mock_enqueue_callback,
        )

        scheduler.start()

        try:
            # Create a source file without translation
            source_file = temp_content_dir / "test.md"
            source_file.write_text("# Test content")

            # Trigger sweep
            scheduler.trigger_sweep("test.site")

            # Wait a bit for sweep to complete
            time.sleep(0.2)

            # Should have created a job
            assert mock_enqueue_callback.call_count >= 1

            # Check job properties
            call_args = mock_enqueue_callback.call_args_list[0]
            job: TranslationJob = call_args[0][0]

            assert job.job_type == JobType.SWEEP_BATCH
            assert job.site_id == "test.site"
            assert job.mode == JobMode.AUTO
            assert job.priority == 7  # Sweep priority
            assert source_file in job.input_paths

        finally:
            scheduler.stop()

    def test_sweep_finds_untranslated_files(
        self, mock_config_service, mock_enqueue_callback, temp_content_dir
    ):
        """Test that sweep finds files without translations."""
        # Reset mock to avoid cross-contamination
        mock_enqueue_callback.reset_mock()

        # Create a fresh temp dir for this test to avoid leftover files
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as fresh_tmpdir:
            fresh_content_dir = Path(fresh_tmpdir) / "content"
            fresh_content_dir.mkdir()

            # Update mock to use fresh directory
            fresh_profile = SiteProfile(
                site_id="test.site",
                content_roots=[str(fresh_content_dir)],
                default_source_lang="en",
                target_langs=["fr", "es"],
                body=BodyRules(translate_markdown=True),
                output_layout=OutputLayout(per_language_folders=True),
            )
            mock_config_service.get_site_profile.return_value = fresh_profile

            scheduler = SweepScheduler(
                config_service=mock_config_service,
                job_enqueue_callback=mock_enqueue_callback,
            )

            scheduler.start()

            try:
                # Create multiple source files without translations
                for i in range(3):
                    source_file = fresh_content_dir / f"unique_test_{i}.md"
                    source_file.write_text(f"# Test content {i}")

                # Trigger sweep
                scheduler.trigger_sweep("test.site")

                # Wait for sweep to complete
                time.sleep(0.2)

                # Should have created job
                assert mock_enqueue_callback.call_count >= 1

                # Check that our 3 specific files are included
                all_file_names = set()
                for call in mock_enqueue_callback.call_args_list:
                    job = call[0][0]
                    for path in job.input_paths:
                        all_file_names.add(path.name)

                # Our 3 unique test files should be there
                assert "unique_test_0.md" in all_file_names
                assert "unique_test_1.md" in all_file_names
                assert "unique_test_2.md" in all_file_names

            finally:
                scheduler.stop()

    def test_sweep_skips_existing_translations(
        self, mock_config_service, mock_enqueue_callback, temp_content_dir
    ):
        """Test that sweep skips files with up-to-date translations."""
        # Reset mock
        mock_enqueue_callback.reset_mock()

        scheduler = SweepScheduler(
            config_service=mock_config_service,
            job_enqueue_callback=mock_enqueue_callback,
        )

        scheduler.start()

        try:
            # Create translations first (so they are older than source in filesystem time)
            for lang in ["fr", "es"]:
                lang_dir = temp_content_dir / lang
                lang_dir.mkdir(exist_ok=True)
                target_file = lang_dir / "test.md"
                target_file.write_text(f"# Contenu de test ({lang})")

            # Small delay to ensure different mtime
            time.sleep(0.05)

            # Create source file after translations
            source_file = temp_content_dir / "test.md"
            source_file.write_text("# Test content")

            # Touch the translations to make them newer than source
            for lang in ["fr", "es"]:
                target_file = temp_content_dir / lang / "test.md"
                target_file.touch()

            # Trigger sweep
            scheduler.trigger_sweep("test.site")

            # Wait for sweep to complete
            time.sleep(0.2)

            # Should not have created any jobs (all translations exist and are newer)
            mock_enqueue_callback.assert_not_called()

        finally:
            scheduler.stop()

    def test_sweep_detects_outdated_translations(
        self, mock_config_service, mock_enqueue_callback, temp_content_dir
    ):
        """Test that sweep detects when source is newer than translation."""
        scheduler = SweepScheduler(
            config_service=mock_config_service,
            job_enqueue_callback=mock_enqueue_callback,
        )

        scheduler.start()

        try:
            # Create old translations
            for lang in ["fr", "es"]:
                lang_dir = temp_content_dir / lang
                lang_dir.mkdir(exist_ok=True)
                target_file = lang_dir / "test.md"
                target_file.write_text(f"# Old translation ({lang})")

            # Wait a bit
            time.sleep(0.1)

            # Create newer source file
            source_file = temp_content_dir / "test.md"
            source_file.write_text("# Updated test content")

            # Trigger sweep
            scheduler.trigger_sweep("test.site")

            # Wait for sweep to complete
            time.sleep(0.2)

            # Should have created a job (source is newer)
            assert mock_enqueue_callback.call_count >= 1

        finally:
            scheduler.stop()

    def test_sweep_ignores_target_lang_files(
        self, mock_config_service, mock_enqueue_callback, temp_content_dir
    ):
        """Test that sweep doesn't scan files in target language directories."""
        scheduler = SweepScheduler(
            config_service=mock_config_service,
            job_enqueue_callback=mock_enqueue_callback,
        )

        scheduler.start()

        try:
            # Create files in target language directories
            for lang in ["fr", "es"]:
                lang_dir = temp_content_dir / lang
                lang_dir.mkdir(exist_ok=True)
                target_file = lang_dir / "translated.md"
                target_file.write_text(f"# Translated ({lang})")

            # Trigger sweep
            scheduler.trigger_sweep("test.site")

            # Wait for sweep to complete
            time.sleep(0.2)

            # Should not create jobs for translation files
            mock_enqueue_callback.assert_not_called()

        finally:
            scheduler.stop()

    def test_sweep_creates_batch_jobs(
        self, mock_config_service, mock_enqueue_callback, temp_content_dir
    ):
        """Test that large sweeps create multiple batch jobs."""
        # Reset mock
        mock_enqueue_callback.reset_mock()

        # Use fresh directory
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as fresh_tmpdir:
            fresh_content_dir = Path(fresh_tmpdir) / "content"
            fresh_content_dir.mkdir()

            fresh_profile = SiteProfile(
                site_id="test.site",
                content_roots=[str(fresh_content_dir)],
                default_source_lang="en",
                target_langs=["fr", "es"],
                body=BodyRules(translate_markdown=True),
                output_layout=OutputLayout(per_language_folders=True),
            )
            mock_config_service.get_site_profile.return_value = fresh_profile

            scheduler = SweepScheduler(
                config_service=mock_config_service,
                job_enqueue_callback=mock_enqueue_callback,
            )

            scheduler.start()

            try:
                # Create 75 source files (should create 2 batch jobs of 50 and 25)
                for i in range(75):
                    source_file = fresh_content_dir / f"batch_test_{i}.md"
                    source_file.write_text(f"# Test content {i}")

                # Trigger sweep
                scheduler.trigger_sweep("test.site")

                # Wait for sweep to complete
                time.sleep(0.3)

                # Filter to jobs with our specific test files
                our_jobs = []
                for call in mock_enqueue_callback.call_args_list:
                    job = call[0][0]
                    # Check if this job contains our test files
                    if any("batch_test_" in str(p) for p in job.input_paths):
                        our_jobs.append(job)

                # Should have created at least 2 jobs for our 75 files (batch size is 50)
                assert len(our_jobs) >= 2

                # Check total files across our jobs
                total_files = sum(len(job.input_paths) for job in our_jobs)
                assert total_files >= 75

                # Check that batching occurred - at least one batch should be large (near 50)
                max_batch_size = max(len(job.input_paths) for job in our_jobs)
                assert max_batch_size >= 25  # At least one large batch

            finally:
                scheduler.stop()

    def test_sweep_statistics(
        self, mock_config_service, mock_enqueue_callback, temp_content_dir
    ):
        """Test sweep statistics collection."""
        scheduler = SweepScheduler(
            config_service=mock_config_service,
            job_enqueue_callback=mock_enqueue_callback,
        )

        scheduler.start()

        try:
            # Create some files
            for i in range(5):
                source_file = temp_content_dir / f"test{i}.md"
                source_file.write_text(f"# Test {i}")

            # Trigger sweep
            scheduler.trigger_sweep("test.site")

            # Wait for sweep to complete
            time.sleep(0.2)

            # Get statistics
            stats = scheduler.get_stats()

            assert len(stats) > 0
            latest_stats = stats[-1]

            assert isinstance(latest_stats, SweepStats)
            assert latest_stats.site_id == "test.site"
            assert latest_stats.total_files_scanned == 5
            assert latest_stats.files_needing_translation == 5
            assert latest_stats.jobs_created == 1
            assert latest_stats.duration_seconds > 0

        finally:
            scheduler.stop()

    def test_sweep_all_sites(self, mock_enqueue_callback):
        """Test sweeping all configured sites."""
        # Create profiles for multiple sites
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir1, tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir2:
            content_dir1 = Path(tmpdir1) / "content"
            content_dir1.mkdir()

            content_dir2 = Path(tmpdir2) / "content"
            content_dir2.mkdir()

            profile1 = SiteProfile(
                site_id="site1.com",
                content_roots=[str(content_dir1)],
                default_source_lang="en",
                target_langs=["fr"],
                body=BodyRules(translate_markdown=True),
                output_layout=OutputLayout(per_language_folders=True),
            )

            profile2 = SiteProfile(
                site_id="site2.com",
                content_roots=[str(content_dir2)],
                default_source_lang="en",
                target_langs=["es"],
                body=BodyRules(translate_markdown=True),
                output_layout=OutputLayout(per_language_folders=True),
            )

            mock_config_service = Mock()
            mock_config_service.list_sites.return_value = ["site1.com", "site2.com"]
            mock_config_service.get_site_profile.side_effect = lambda site_id: (
                profile1 if site_id == "site1.com" else profile2
            )

            scheduler = SweepScheduler(
                config_service=mock_config_service,
                job_enqueue_callback=mock_enqueue_callback,
            )

            scheduler.start()

            try:
                # Create files in both sites
                (content_dir1 / "test.md").write_text("# Test 1")
                (content_dir2 / "test.md").write_text("# Test 2")

                # Trigger sweep for all sites
                scheduler.trigger_sweep()  # No site_id = sweep all

                # Wait for sweeps to complete
                time.sleep(0.3)

                # Should have created jobs for both sites (at least 2)
                assert mock_enqueue_callback.call_count >= 2

                # Check that both sites were processed
                sites_processed = {call[0][0].site_id for call in mock_enqueue_callback.call_args_list}
                assert "site1.com" in sites_processed
                assert "site2.com" in sites_processed

            finally:
                scheduler.stop()

    def test_nonexistent_content_dir_handled(self, mock_enqueue_callback):
        """Test that nonexistent content directories are handled gracefully."""
        bad_profile = SiteProfile(
            site_id="bad.site",
            content_roots=["/nonexistent/path/content"],
            default_source_lang="en",
            target_langs=["fr"],
            body=BodyRules(translate_markdown=True),
            output_layout=OutputLayout(per_language_folders=True),
        )

        mock_config_service = Mock()
        mock_config_service.list_sites.return_value = ["bad.site"]
        mock_config_service.get_site_profile.return_value = bad_profile

        scheduler = SweepScheduler(
            config_service=mock_config_service,
            job_enqueue_callback=mock_enqueue_callback,
        )

        scheduler.start()

        try:
            # Trigger sweep - should not crash
            scheduler.trigger_sweep("bad.site")

            # Wait a bit
            time.sleep(0.2)

            # Should not have created any jobs
            mock_enqueue_callback.assert_not_called()

        finally:
            scheduler.stop()
