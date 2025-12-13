"""
Sweep scheduler for periodic content scanning.

Scans content directories for files that need translation or updating.
"""

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional

from src.utils.config_loader import ConfigService
from src.utils.models import SiteProfile

from .models import JobMode, JobType, TranslationJob

logger = logging.getLogger(__name__)


@dataclass
class SweepStats:
    """Statistics from a sweep operation."""

    site_id: str
    total_files_scanned: int
    files_needing_translation: int
    jobs_created: int
    duration_seconds: float
    timestamp: datetime


class SweepScheduler:
    """
    Periodic scheduler for sweeping content directories.

    Identifies files that need translation and enqueues batch jobs.
    """

    def __init__(
        self,
        config_service: ConfigService,
        job_enqueue_callback: Callable[[TranslationJob], str],
        sweep_interval_minutes: int = 60,
    ):
        """
        Initialize sweep scheduler.

        Args:
            config_service: Configuration service
            job_enqueue_callback: Callback to enqueue jobs
            sweep_interval_minutes: Time between sweeps
        """
        self.config_service = config_service
        self.job_enqueue_callback = job_enqueue_callback
        self.sweep_interval_minutes = sweep_interval_minutes

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_sweep: Dict[str, datetime] = {}  # site_id -> last_sweep_time
        self._sweep_stats: List[SweepStats] = []
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start the sweep scheduler."""
        with self._lock:
            if self._running:
                logger.warning("SweepScheduler already running")
                return

            self._running = True
            self._stop_event.clear()

            # Start background thread
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()

            logger.info(
                f"SweepScheduler started (interval: {self.sweep_interval_minutes} minutes)"
            )

    def stop(self) -> None:
        """Stop the sweep scheduler."""
        with self._lock:
            if not self._running:
                return

            self._running = False
            self._stop_event.set()

            if self._thread:
                self._thread.join(timeout=5.0)
                self._thread = None

            logger.info("SweepScheduler stopped")

    def trigger_sweep(self, site_id: Optional[str] = None) -> None:
        """
        Manually trigger a sweep operation.

        Args:
            site_id: Site to sweep (if None, sweeps all sites)
        """
        if not self._running:
            logger.warning("SweepScheduler not running, cannot trigger sweep")
            return

        if site_id:
            self._sweep_site(site_id)
        else:
            self._sweep_all_sites()

    def get_stats(self, limit: int = 10) -> List[SweepStats]:
        """
        Get recent sweep statistics.

        Args:
            limit: Maximum number of stats to return

        Returns:
            List of recent SweepStats
        """
        with self._lock:
            return self._sweep_stats[-limit:]

    def is_running(self) -> bool:
        """Check if scheduler is running."""
        with self._lock:
            return self._running

    def _run_loop(self) -> None:
        """Main scheduler loop."""
        while not self._stop_event.is_set():
            try:
                self._sweep_all_sites()
            except Exception as e:
                logger.error(f"Error during sweep: {e}", exc_info=True)

            # Wait for next interval or stop signal
            self._stop_event.wait(timeout=self.sweep_interval_minutes * 60)

    def _sweep_all_sites(self) -> None:
        """Sweep all configured sites."""
        for site_id in self.config_service.list_sites():
            if self._stop_event.is_set():
                break

            try:
                self._sweep_site(site_id)
            except Exception as e:
                logger.error(f"Error sweeping site {site_id}: {e}", exc_info=True)

    def _sweep_site(self, site_id: str) -> None:
        """
        Sweep a single site for files needing translation.

        Args:
            site_id: Site identifier
        """
        start_time = time.time()

        try:
            site_profile = self.config_service.get_site_profile(site_id)
        except Exception as e:
            logger.error(f"Failed to get profile for site {site_id}: {e}")
            return

        logger.info(f"Starting sweep for site {site_id}")

        total_files = 0
        files_needing_translation = []

        # Scan each content root
        for content_root in site_profile.content_roots:
            content_dir = Path(content_root)

            if not content_dir.exists():
                logger.warning(f"Content directory does not exist: {content_dir}")
                continue

            # Find all markdown files
            for file_path in content_dir.rglob("*.md"):
                if self._stop_event.is_set():
                    return

                total_files += 1

                # Skip target language files
                if self._is_target_lang_file(file_path, site_profile.target_langs):
                    continue

                # Check if file needs translation
                if self._needs_translation(file_path, site_profile):
                    files_needing_translation.append(file_path)

        # Create batch job if there are files to translate
        jobs_created = 0
        if files_needing_translation:
            jobs_created = self._create_batch_jobs(
                site_id, site_profile, files_needing_translation
            )

        duration = time.time() - start_time

        # Record statistics
        stats = SweepStats(
            site_id=site_id,
            total_files_scanned=total_files,
            files_needing_translation=len(files_needing_translation),
            jobs_created=jobs_created,
            duration_seconds=duration,
            timestamp=datetime.now(),
        )

        with self._lock:
            self._sweep_stats.append(stats)
            self._last_sweep[site_id] = datetime.now()

            # Keep only recent stats (last 100)
            if len(self._sweep_stats) > 100:
                self._sweep_stats = self._sweep_stats[-100:]

        logger.info(
            f"Sweep complete for {site_id}: "
            f"{total_files} files scanned, "
            f"{len(files_needing_translation)} need translation, "
            f"{jobs_created} jobs created "
            f"({duration:.2f}s)"
        )

    def _is_target_lang_file(self, file_path: Path, target_langs: List[str]) -> bool:
        """
        Check if file is in a target language directory.

        Args:
            file_path: File path
            target_langs: Target language codes

        Returns:
            True if file is a translation
        """
        path_str = str(file_path)

        for lang in target_langs:
            if f"/{lang}/" in path_str or f"\\{lang}\\" in path_str:
                return True

        return False

    def _needs_translation(self, file_path: Path, site_profile: SiteProfile) -> bool:
        """
        Check if a source file needs translation.

        Args:
            file_path: Source file path
            site_profile: Site profile

        Returns:
            True if file needs translation
        """
        # For each target language, check if translation exists and is up-to-date
        for target_lang in site_profile.target_langs:
            target_path = self._get_target_path(file_path, target_lang, site_profile)

            # If translation doesn't exist, needs translation
            if not target_path.exists():
                return True

            # If source is newer than translation, needs re-translation
            try:
                source_mtime = file_path.stat().st_mtime
                target_mtime = target_path.stat().st_mtime

                if source_mtime > target_mtime:
                    return True
            except OSError:
                # If we can't stat files, assume needs translation
                return True

        return False

    def _get_target_path(
        self, source_path: Path, target_lang: str, site_profile: SiteProfile
    ) -> Path:
        """
        Get expected translation file path.

        Args:
            source_path: Source file path
            target_lang: Target language code
            site_profile: Site profile

        Returns:
            Expected translation path
        """
        # Find which content root this file is under
        for content_root in site_profile.content_roots:
            content_dir = Path(content_root)
            try:
                rel_path = source_path.relative_to(content_dir)

                # Construct target path using output layout pattern
                if site_profile.output_layout and site_profile.output_layout.per_language_folders:
                    # Per-language folder structure: content/de/path/to/file.md
                    target_path = content_dir / target_lang / rel_path
                    return target_path
                else:
                    # Alternative patterns could go here
                    pass

            except ValueError:
                continue

        # Fallback: assume per-language structure
        content_root = Path(site_profile.content_roots[0])
        rel_path = source_path.relative_to(content_root)
        return content_root / target_lang / rel_path

    def _create_batch_jobs(
        self, site_id: str, site_profile: SiteProfile, files: List[Path]
    ) -> int:
        """
        Create batch translation jobs.

        Args:
            site_id: Site identifier
            site_profile: Site profile
            files: List of files needing translation

        Returns:
            Number of jobs created
        """
        # Group files into batches (max 50 files per job)
        batch_size = 50
        jobs_created = 0

        for i in range(0, len(files), batch_size):
            batch = files[i : i + batch_size]

            job = TranslationJob(
                job_id="",  # Will be generated
                job_type=JobType.SWEEP_BATCH,
                site_id=site_id,
                target_langs=site_profile.target_langs,
                input_paths=batch,
                priority=7,  # Lower priority than auto-mode
                mode=JobMode.AUTO,
                metadata={"sweep_timestamp": datetime.now().isoformat()},
            )

            try:
                job_id = self.job_enqueue_callback(job)
                jobs_created += 1
                logger.debug(
                    f"Created batch job {job_id} with {len(batch)} files for {site_id}"
                )
            except Exception as e:
                logger.error(f"Failed to enqueue batch job: {e}")

        return jobs_created
