"""
Integration tests for Autonomous Content Translation Worker.

Tests the full worker flow with mocked TranslationEngine and git operations.
"""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from src.translation_engine.models import DirectoryResult
from src.workers.autonomous_content_translation_worker import (
    AutonomousContentTranslationWorker,
    AutonomousWorkerConfig,
)


@pytest.fixture
def mock_config_service():
    """Mock ConfigService with sample site profiles."""
    mock_service = Mock()

    # Mock site profile
    mock_profile = Mock()
    mock_profile.content_roots = ["/test/content/en"]
    mock_profile.target_langs = ["es", "fr"]
    mock_profile.default_source_lang = "en"

    mock_service.get_site_profile.return_value = mock_profile
    mock_service.list_sites.return_value = ["test-site"]
    mock_service.get_config.return_value = {
        "paths": {
            "tm_data_dir": "data/tm",
        }
    }
    mock_service.resolve_content_root.side_effect = lambda path: Path(path)

    return mock_service


@pytest.fixture
def mock_translation_engine():
    """Mock TranslationEngine with sample results."""
    mock_engine = Mock()

    # Mock successful translation result
    mock_result = DirectoryResult(
        success=True,
        directory=Path("/test/content/en"),
        total_files=10,
        successful_files=10,
        failed_files=0,
    )

    # Add telemetry context for git commit integration
    mock_result.telemetry_context = Mock()

    mock_engine.translate_directory.return_value = mock_result

    return mock_engine


@pytest.fixture
def worker_config():
    """Create test worker configuration."""
    return AutonomousWorkerConfig(
        config_root="config",
        site="test-site",
        mode="oneshot",
        device="cpu",
        max_gpu_memory_percent=60,
    )


class TestAutonomousWorkerOneshot:
    """Tests for oneshot mode execution."""

    def test_oneshot_single_site(self, worker_config, mock_config_service, mock_translation_engine):
        """Test oneshot mode with single site."""
        worker = AutonomousContentTranslationWorker(worker_config)

        # Patch dependencies
        with patch("src.workers.autonomous_content_translation_worker.ConfigService") as mock_cs, \
             patch("src.workers.autonomous_content_translation_worker.TranslationEngine") as mock_te, \
             patch("src.workers.autonomous_content_translation_worker.auto_commit_translations") as mock_commit, \
             patch("src.workers.autonomous_content_translation_worker.Path.exists", return_value=True):

            mock_cs.return_value = mock_config_service
            mock_te.return_value = mock_translation_engine
            mock_commit.return_value = True

            # Setup and run
            worker.setup()
            worker.run()

            # Verify ConfigService loaded
            mock_cs.assert_called_once_with(worker_config.config_root)

            # Verify site profile loaded
            mock_config_service.get_site_profile.assert_called_once_with("test-site")

            # Verify translation called with trigger_type="scheduled"
            mock_translation_engine.translate_directory.assert_called_once()
            call_kwargs = mock_translation_engine.translate_directory.call_args.kwargs
            assert call_kwargs["trigger_type"] == "scheduled"
            assert call_kwargs["site_id"] == "test-site"
            assert call_kwargs["directory"] == Path("/test/content/en")
            assert call_kwargs["target_langs"] == ["es", "fr"]
            assert call_kwargs["recursive"] is True
            assert call_kwargs["parallel"] is True

            # Verify git commit called
            mock_commit.assert_called_once()
            commit_kwargs = mock_commit.call_args.kwargs
            assert commit_kwargs["site_id"] == "test-site"
            assert commit_kwargs["target_langs"] == ["es", "fr"]
            assert commit_kwargs["config_service"] == mock_config_service

    def test_oneshot_all_sites(self, mock_config_service, mock_translation_engine):
        """Test oneshot mode processing all sites."""
        # Config without specific site
        config = AutonomousWorkerConfig(
            config_root="config",
            site=None,  # Process all sites
            mode="oneshot",
            device="cpu",
        )

        # Mock multiple sites
        mock_config_service.list_sites.return_value = ["site1", "site2", "site3"]

        worker = AutonomousContentTranslationWorker(config)

        with patch("src.workers.autonomous_content_translation_worker.ConfigService") as mock_cs, \
             patch("src.workers.autonomous_content_translation_worker.TranslationEngine") as mock_te, \
             patch("src.workers.autonomous_content_translation_worker.auto_commit_translations") as mock_commit, \
             patch("src.workers.autonomous_content_translation_worker.Path.exists", return_value=True):

            mock_cs.return_value = mock_config_service
            mock_te.return_value = mock_translation_engine
            mock_commit.return_value = True

            worker.setup()
            worker.run()

            # Verify all 3 sites processed
            assert mock_config_service.get_site_profile.call_count == 3
            mock_config_service.get_site_profile.assert_any_call("site1")
            mock_config_service.get_site_profile.assert_any_call("site2")
            mock_config_service.get_site_profile.assert_any_call("site3")

    def test_oneshot_max_sites_limit(self, mock_config_service, mock_translation_engine):
        """Test oneshot mode with max_sites_per_run limit."""
        config = AutonomousWorkerConfig(
            config_root="config",
            site=None,
            mode="oneshot",
            device="cpu",
            max_sites_per_run=2,  # Limit to 2 sites
        )

        # Mock 5 sites
        mock_config_service.list_sites.return_value = ["site1", "site2", "site3", "site4", "site5"]

        worker = AutonomousContentTranslationWorker(config)

        with patch("src.workers.autonomous_content_translation_worker.ConfigService") as mock_cs, \
             patch("src.workers.autonomous_content_translation_worker.TranslationEngine") as mock_te, \
             patch("src.workers.autonomous_content_translation_worker.auto_commit_translations") as mock_commit, \
             patch("src.workers.autonomous_content_translation_worker.Path.exists", return_value=True):

            mock_cs.return_value = mock_config_service
            mock_te.return_value = mock_translation_engine
            mock_commit.return_value = True

            worker.setup()
            worker.run()

            # Verify only 2 sites processed (due to limit)
            assert mock_config_service.get_site_profile.call_count == 2

    def test_oneshot_no_successful_files_skips_commit(self, worker_config, mock_config_service, mock_translation_engine):
        """Test that no commit is made when no files are successfully translated."""
        # Mock result with no successful files
        mock_result = DirectoryResult(
            success=False,
            directory=Path("/test/content/en"),
            total_files=10,
            successful_files=0,
            failed_files=10,
        )
        mock_translation_engine.translate_directory.return_value = mock_result

        worker = AutonomousContentTranslationWorker(worker_config)

        with patch("src.workers.autonomous_content_translation_worker.ConfigService") as mock_cs, \
             patch("src.workers.autonomous_content_translation_worker.TranslationEngine") as mock_te, \
             patch("src.workers.autonomous_content_translation_worker.auto_commit_translations") as mock_commit, \
             patch("src.workers.autonomous_content_translation_worker.Path.exists", return_value=True):

            mock_cs.return_value = mock_config_service
            mock_te.return_value = mock_translation_engine

            worker.setup()
            worker.run()

            # Verify git commit was NOT called
            mock_commit.assert_not_called()

    def test_oneshot_site_error_continues(self, mock_config_service, mock_translation_engine):
        """Test that worker continues processing after site error."""
        config = AutonomousWorkerConfig(
            config_root="config",
            site=None,
            mode="oneshot",
            device="cpu",
        )

        # Mock 3 sites, second one fails
        mock_config_service.list_sites.return_value = ["site1", "site2", "site3"]

        def mock_get_profile(site_id):
            if site_id == "site2":
                raise Exception("Failed to load site2")
            return Mock(content_roots=["/test/content"], target_langs=["es"])

        mock_config_service.get_site_profile.side_effect = mock_get_profile

        worker = AutonomousContentTranslationWorker(config)

        with patch("src.workers.autonomous_content_translation_worker.ConfigService") as mock_cs, \
             patch("src.workers.autonomous_content_translation_worker.TranslationEngine") as mock_te, \
             patch("src.workers.autonomous_content_translation_worker.auto_commit_translations") as mock_commit, \
             patch("src.workers.autonomous_content_translation_worker.Path.exists", return_value=True):

            mock_cs.return_value = mock_config_service
            mock_te.return_value = mock_translation_engine
            mock_commit.return_value = True

            worker.setup()
            worker.run()

            # Verify attempted to process all 3 sites
            assert mock_config_service.get_site_profile.call_count == 3

            # Verify site1 and site3 were translated (site2 failed)
            assert mock_translation_engine.translate_directory.call_count == 2

    def test_oneshot_content_root_does_not_exist(self, worker_config, mock_config_service, mock_translation_engine):
        """Test that nonexistent content_root is skipped."""
        worker = AutonomousContentTranslationWorker(worker_config)
        mock_config_service.get_site_profile.return_value = Mock(
            content_roots=["/path/that/should/not/exist/for/test"],
            target_langs=["es", "fr"],
            default_source_lang="en",
        )

        with patch("src.workers.autonomous_content_translation_worker.ConfigService") as mock_cs, \
             patch("src.workers.autonomous_content_translation_worker.TranslationEngine") as mock_te, \
             patch("src.workers.autonomous_content_translation_worker.auto_commit_translations") as mock_commit:

            mock_cs.return_value = mock_config_service
            mock_te.return_value = mock_translation_engine

            worker.setup()
            worker.run()

            # Verify translation was NOT called (content root doesn't exist)
            mock_translation_engine.translate_directory.assert_not_called()
            mock_commit.assert_not_called()


class TestAutonomousWorkerVRAM:
    """Tests for VRAM enforcement."""

    def test_vram_enforcement_cuda(self, mock_config_service, mock_translation_engine):
        """Test that VRAM enforcement is called for CUDA device."""
        config = AutonomousWorkerConfig(
            config_root="config",
            site="test-site",
            mode="oneshot",
            device="cuda",
            max_gpu_memory_percent=60,
        )

        worker = AutonomousContentTranslationWorker(config)

        with patch("src.workers.autonomous_content_translation_worker.ConfigService") as mock_cs, \
             patch("src.workers.autonomous_content_translation_worker.TranslationEngine") as mock_te, \
             patch("src.workers.autonomous_content_translation_worker.VRAMEnforcer") as mock_enforcer, \
             patch("src.workers.autonomous_content_translation_worker.Path.exists", return_value=True):

            mock_cs.return_value = mock_config_service
            mock_te.return_value = mock_translation_engine

            # Mock VRAMEnforcer
            mock_enforcer_instance = Mock()
            mock_enforcer.return_value = mock_enforcer_instance
            mock_enforcer_instance.enforce_from_config.return_value = (4915, Mock(percent=60.0))

            worker.setup()

            # Verify VRAM enforcer was called
            mock_enforcer.assert_called_once()
            mock_enforcer_instance.enforce_from_config.assert_called_once()

            # Verify hardware config passed to enforcer
            call_args = mock_enforcer_instance.enforce_from_config.call_args
            hardware_config = call_args[0][0]
            assert hardware_config["enable_gpu"] is True
            assert hardware_config["max_gpu_memory_percent"] == 60

    def test_vram_enforcement_skipped_cpu(self, mock_config_service, mock_translation_engine):
        """Test that VRAM enforcement is skipped for CPU device."""
        config = AutonomousWorkerConfig(
            config_root="config",
            site="test-site",
            mode="oneshot",
            device="cpu",
        )

        worker = AutonomousContentTranslationWorker(config)

        with patch("src.workers.autonomous_content_translation_worker.ConfigService") as mock_cs, \
             patch("src.workers.autonomous_content_translation_worker.TranslationEngine") as mock_te, \
             patch("src.workers.autonomous_content_translation_worker.VRAMEnforcer") as mock_enforcer, \
             patch("src.workers.autonomous_content_translation_worker.Path.exists", return_value=True):

            mock_cs.return_value = mock_config_service
            mock_te.return_value = mock_translation_engine

            worker.setup()

            # Verify VRAM enforcer was NOT called (CPU device)
            mock_enforcer.assert_not_called()


class TestAutonomousWorkerRunID:
    """Tests for run ID generation and tracking."""

    def test_run_id_includes_invocation_id(self, worker_config, mock_config_service, mock_translation_engine):
        """Test that run_id includes invocation_id for traceability."""
        worker = AutonomousContentTranslationWorker(worker_config)

        with patch("src.workers.autonomous_content_translation_worker.ConfigService") as mock_cs, \
             patch("src.workers.autonomous_content_translation_worker.TranslationEngine") as mock_te, \
             patch("src.workers.autonomous_content_translation_worker.auto_commit_translations") as mock_commit, \
             patch("src.workers.autonomous_content_translation_worker.Path.exists", return_value=True):

            mock_cs.return_value = mock_config_service
            mock_te.return_value = mock_translation_engine
            mock_commit.return_value = True

            worker.setup()
            worker.run()

            # Verify run_id passed to git commit
            mock_commit.assert_called_once()
            run_id = mock_commit.call_args.kwargs["run_id"]

            # Run ID should have format: {invocation_id}:{site_id}:{content_root_name}
            parts = run_id.split(":")
            assert len(parts) == 3
            assert parts[0] == worker.invocation_id
            assert parts[1] == "test-site"
            assert parts[2] == "en"  # content_root name


class TestAutonomousWorkerDaemonMode:
    """Tests for daemon mode execution."""

    def test_daemon_mode_scheduling(self, mock_config_service, mock_translation_engine):
        """Test that daemon mode uses WindowScheduler."""
        config = AutonomousWorkerConfig(
            config_root="config",
            site="test-site",
            mode="daemon",
            runs_per_day=5,
            window_start="10:00",
            window_end="22:00",
            timezone="America/Los_Angeles",
        )

        worker = AutonomousContentTranslationWorker(config)

        with patch("src.workers.autonomous_content_translation_worker.ConfigService") as mock_cs, \
             patch("src.workers.autonomous_content_translation_worker.TranslationEngine") as mock_te, \
             patch("src.workers.autonomous_content_translation_worker.WindowScheduler") as mock_scheduler, \
             patch("src.workers.autonomous_content_translation_worker.auto_commit_translations") as mock_commit, \
             patch("src.workers.autonomous_content_translation_worker.Path.exists", return_value=True):

            mock_cs.return_value = mock_config_service
            mock_te.return_value = mock_translation_engine
            mock_commit.return_value = True

            # Mock scheduler to run once then raise KeyboardInterrupt
            mock_scheduler_instance = Mock()
            mock_scheduler.return_value = mock_scheduler_instance
            mock_scheduler_instance.sleep_until_next_run.side_effect = [
                Mock(),  # First run
                KeyboardInterrupt(),  # Exit after first run
            ]

            worker.setup()

            # Verify WindowScheduler was created
            mock_scheduler.assert_called_once()

            try:
                worker.run()
            except KeyboardInterrupt:
                pass

            # Verify scheduler was called
            assert mock_scheduler_instance.sleep_until_next_run.call_count >= 1

            # Verify translation was executed
            assert mock_translation_engine.translate_directory.call_count >= 1
