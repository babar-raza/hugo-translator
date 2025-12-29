"""
Main orchestrator service that coordinates all translation operations.

Manages job queue, file watcher, and sweep scheduler.
"""

import logging
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
        config_service: ConfigService,
        enable_file_watcher: bool = True,
        enable_sweep_scheduler: bool = True,
        sweep_interval_minutes: int = 60,
        queue: Optional[JobQueue] = None,
    ):
        """
        Initialize orchestrator.

        Args:
            config_service: Configuration service
            enable_file_watcher: Whether to enable file watching
            enable_sweep_scheduler: Whether to enable periodic sweeps
            sweep_interval_minutes: Interval between sweeps
            queue: Optional job queue (defaults to in-memory JobQueue)
        """
        self.config_service = config_service

        # Initialize job queue
        self.queue = queue if queue is not None else JobQueue()

        # Initialize file watcher (if enabled)
        self.file_watcher: Optional[FileWatcher] = None
        if enable_file_watcher:
            self.file_watcher = FileWatcher(
                config_service=config_service,
                job_enqueue_callback=self.enqueue_job,
                debounce_seconds=2.0,
            )

        # Initialize sweep scheduler (if enabled)
        self.scheduler: Optional[SweepScheduler] = None
        if enable_sweep_scheduler:
            self.scheduler = SweepScheduler(
                config_service=config_service,
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
