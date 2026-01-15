"""
Main orchestrator service that coordinates all translation operations.

Manages job queue, file watcher, and sweep scheduler.
"""

import logging
import warnings
from typing import Optional

from src.utils.config_loader import ConfigService

from .models import TranslationJob
from .queue import JobQueue
from .scheduler import SweepScheduler
from .watcher import FileWatcher

logger = logging.getLogger(__name__)


class TranslationOrchestrator:
    """
    Main orchestrator for the translation system.

    Coordinates:
    - Job queue for managing translation jobs
    - File watcher for auto-mode translations
    - Sweep scheduler for periodic content scanning
    """

    def __init__(
        self,
        config_service: ConfigService = None,
        enable_file_watcher: bool = True,
        enable_sweep_scheduler: bool = True,
        sweep_interval_minutes: int = 60,
        queue: Optional[JobQueue] = None,
        engines: Optional["SharedEngines"] = None,  # NEW: SharedEngines support
    ):
        """
        Initialize orchestrator.

        Args:
            config_service: Configuration service (ignored if engines provided)
            enable_file_watcher: Whether to enable file watching
            enable_sweep_scheduler: Whether to enable periodic sweeps
            sweep_interval_minutes: Interval between sweeps
            queue: Optional job queue (ignored if engines provided)
            engines: SharedEngines container (NEW - Phase 5.2 migration)
                    If provided, uses shared engines instead of direct instantiation.
                    Enables unified telemetry, logging, and configuration.
        """
        # PHASE 5.2: Detect if using SharedEngines or legacy mode
        self._using_shared_engines = engines is not None
        self.engines = engines

        if self._using_shared_engines:
            logger.info("Orchestrator using SharedEngines (Phase 5.2)")

            # Use SharedEngines components
            self.config_service = engines.profile.config_service
            self.queue = engines.job.queue

            # Emit telemetry event for orchestrator startup
            try:
                engines.telemetry.track_event(
                    event_type="orchestrator_started",
                    mode="shared_engines",
                    file_watcher_enabled=enable_file_watcher,
                    sweep_scheduler_enabled=enable_sweep_scheduler
                )
            except Exception as e:
                logger.debug(f"Telemetry event failed (non-fatal): {e}")
        else:
            # Legacy mode: Direct instantiation
            if config_service is None:
                raise ValueError("config_service required when engines not provided")

            warnings.warn(
                "Instantiating TranslationOrchestrator without SharedEngines is deprecated. "
                "Use CompositionRoot.create_from_config() and pass engines parameter. "
                "Legacy mode will be removed in a future release.",
                DeprecationWarning,
                stacklevel=2
            )
            logger.warning(
                "Orchestrator running in LEGACY mode (direct instantiation). "
                "Consider migrating to SharedEngines for unified telemetry and configuration."
            )

            self.config_service = config_service
            self.queue = queue if queue is not None else JobQueue()

        # Initialize file watcher (if enabled)
        self.file_watcher: Optional[FileWatcher] = None
        if enable_file_watcher:
            self.file_watcher = FileWatcher(
                config_service=self.config_service,
                job_enqueue_callback=self.enqueue_job,
                debounce_seconds=2.0,
            )

        # Initialize sweep scheduler (if enabled)
        self.scheduler: Optional[SweepScheduler] = None
        if enable_sweep_scheduler:
            self.scheduler = SweepScheduler(
                config_service=self.config_service,
                job_enqueue_callback=self.enqueue_job,
                sweep_interval_minutes=sweep_interval_minutes,
            )

        self._running = False

    def start(self) -> None:
        """Start all orchestrator components."""
        if self._running:
            logger.warning("Orchestrator already running")
            return

        self._running = True

        # Start file watcher
        if self.file_watcher:
            self.file_watcher.start()
            logger.info("File watcher started")

        # Start sweep scheduler
        if self.scheduler:
            self.scheduler.start()
            logger.info("Sweep scheduler started")

        logger.info("Translation orchestrator started")

    def stop(self) -> None:
        """Stop all orchestrator components."""
        if not self._running:
            return

        self._running = False

        # PHASE 5.2: Emit telemetry event for orchestrator shutdown
        if self._using_shared_engines:
            try:
                self.engines.telemetry.track_event(
                    event_type="orchestrator_stopped",
                    mode="shared_engines"
                )
            except Exception as e:
                logger.debug(f"Telemetry event failed (non-fatal): {e}")

        # Stop file watcher
        if self.file_watcher:
            self.file_watcher.stop()
            logger.info("File watcher stopped")

        # Stop sweep scheduler
        if self.scheduler:
            self.scheduler.stop()
            logger.info("Sweep scheduler stopped")

        logger.info("Translation orchestrator stopped")

    def enqueue_job(self, job: TranslationJob) -> str:
        """
        Enqueue a translation job.

        Args:
            job: Translation job to enqueue

        Returns:
            Job ID
        """
        return self.queue.enqueue(job)

    def dequeue_job(self) -> Optional[TranslationJob]:
        """
        Get next job from queue.

        Returns:
            Next translation job or None if queue is empty
        """
        return self.queue.dequeue()

    def is_running(self) -> bool:
        """Check if orchestrator is running."""
        return self._running
