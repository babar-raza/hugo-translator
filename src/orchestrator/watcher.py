"""
File watcher for auto-translation mode.

Monitors content directories for changes and automatically enqueues translation jobs.
"""

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from src.utils.config_loader import ConfigService
from src.utils.models import SiteProfile

from .models import JobMode, JobType, TranslationJob

logger = logging.getLogger(__name__)


@dataclass
class WatchConfig:
    """Configuration for watching a content directory."""

    site_id: str
    content_dir: Path
    source_lang: str
    target_langs: List[str]


class ContentFileHandler(FileSystemEventHandler):
    """
    Handler for file system events in content directories.

    Debounces events and triggers callbacks for translation-relevant changes.
    """

    def __init__(
        self,
        watch_config: WatchConfig,
        on_file_change: Callable[[Path, str], None],
        debounce_seconds: float = 2.0,
    ):
        """
        Initialize handler.

        Args:
            watch_config: Watch configuration
            on_file_change: Callback(file_path, event_type) for file changes
            debounce_seconds: Time to wait before processing changes
        """
        super().__init__()
        self.watch_config = watch_config
        self.on_file_change = on_file_change
        self.debounce_seconds = debounce_seconds

        # Debounce tracking
        self._pending_changes: Dict[Path, str] = {}  # path -> event_type
        self._lock = threading.Lock()
        self._debounce_timer: Optional[threading.Timer] = None

    def on_created(self, event: FileSystemEvent) -> None:
        """Handle file creation."""
        if not event.is_directory and self._is_content_file(event.src_path):
            self._schedule_change(Path(event.src_path), "created")

    def on_modified(self, event: FileSystemEvent) -> None:
        """Handle file modification."""
        if not event.is_directory and self._is_content_file(event.src_path):
            self._schedule_change(Path(event.src_path), "modified")

    def on_deleted(self, event: FileSystemEvent) -> None:
        """Handle file deletion."""
        if not event.is_directory and self._is_content_file(event.src_path):
            self._schedule_change(Path(event.src_path), "deleted")

    def _is_content_file(self, file_path: str) -> bool:
        """
        Check if file is a translatable content file.

        Args:
            file_path: Path to file

        Returns:
            True if file should trigger translation
        """
        path = Path(file_path)

        # Check extension
        if path.suffix.lower() not in {".md", ".markdown"}:
            return False

        # Must be within content directory
        try:
            content_dir = self.watch_config.content_dir.resolve()
            file_resolved = path.resolve()

            if not str(file_resolved).startswith(str(content_dir)):
                return False
        except Exception:
            return False

        # Check if it's a source language file (not already translated)
        target_langs = self.watch_config.target_langs

        # If file is in a target language directory, ignore it
        for target_lang in target_langs:
            if f"/{target_lang}/" in str(path) or f"\\{target_lang}\\" in str(path):
                return False

        return True

    def _schedule_change(self, file_path: Path, event_type: str) -> None:
        """
        Schedule a change for processing (with debouncing).

        Args:
            file_path: Path to changed file
            event_type: Type of change (created, modified, deleted)
        """
        with self._lock:
            # Record the change
            self._pending_changes[file_path] = event_type

            # Cancel existing timer
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()

            # Schedule new processing
            self._debounce_timer = threading.Timer(
                self.debounce_seconds, self._process_pending_changes
            )
            self._debounce_timer.start()

    def _process_pending_changes(self) -> None:
        """Process all pending changes after debounce period."""
        with self._lock:
            changes = dict(self._pending_changes)
            self._pending_changes.clear()
            self._debounce_timer = None

        # Trigger callbacks
        for file_path, event_type in changes.items():
            try:
                self.on_file_change(file_path, event_type)
            except Exception as e:
                logger.error(f"Error processing file change for {file_path}: {e}")


class FileWatcher:
    """
    Watches content directories for changes and enqueues translation jobs.

    Supports multiple sites with independent monitoring.
    """

    def __init__(
        self,
        config_service: ConfigService,
        job_enqueue_callback: Callable[[TranslationJob], str],
        debounce_seconds: float = 2.0,
    ):
        """
        Initialize file watcher.

        Args:
            config_service: Configuration service
            job_enqueue_callback: Callback to enqueue jobs
            debounce_seconds: Debounce time for file changes
        """
        self.config_service = config_service
        self.job_enqueue_callback = job_enqueue_callback
        self.debounce_seconds = debounce_seconds

        self._observer = Observer()
        self._handlers: Dict[str, ContentFileHandler] = {}  # site_id -> handler
        self._watched_dirs: Set[str] = set()
        self._running = False
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start watching all configured sites."""
        with self._lock:
            if self._running:
                logger.warning("FileWatcher already running")
                return

            self._running = True

            # Watch all sites
            for site_id in self.config_service.list_sites():
                try:
                    site_profile = self.config_service.get_site_profile(site_id)
                    self._watch_site(site_id, site_profile)
                except Exception as e:
                    logger.error(f"Failed to watch site {site_id}: {e}")

            # Start observer
            self._observer.start()
            logger.info("FileWatcher started")

    def stop(self) -> None:
        """Stop watching."""
        with self._lock:
            if not self._running:
                return

            self._running = False
            self._observer.stop()
            self._observer.join(timeout=5.0)

            self._handlers.clear()
            self._watched_dirs.clear()

            logger.info("FileWatcher stopped")

    def add_site(self, site_id: str) -> None:
        """
        Add a site to watch.

        Args:
            site_id: Site identifier
        """
        with self._lock:
            if not self._running:
                logger.warning("FileWatcher not running, cannot add site")
                return

            try:
                site_profile = self.config_service.get_site_profile(site_id)
                self._watch_site(site_id, site_profile)
            except Exception as e:
                logger.error(f"Failed to add site {site_id}: {e}")

    def remove_site(self, site_id: str) -> None:
        """
        Stop watching a site.

        Args:
            site_id: Site identifier
        """
        with self._lock:
            if site_id in self._handlers:
                # Remove handler
                self._handlers.pop(site_id)
                logger.info(f"Removed site {site_id} from watching")

    def _watch_site(self, site_id: str, site_profile: SiteProfile) -> None:
        """
        Set up watching for a site's content directories.

        Args:
            site_id: Site identifier
            site_profile: Site profile configuration
        """
        # Watch each content root
        for content_root in site_profile.content_roots:
            content_dir = Path(content_root)

            if not content_dir.exists():
                logger.warning(f"Content directory does not exist: {content_dir}")
                continue

            # Create watch config
            watch_config = WatchConfig(
                site_id=site_id,
                content_dir=content_dir,
                source_lang=site_profile.default_source_lang,
                target_langs=site_profile.target_langs,
            )

            # Create handler
            handler = ContentFileHandler(
                watch_config=watch_config,
                on_file_change=lambda path, event_type, cfg=watch_config: self._on_file_change(
                    cfg.site_id, cfg.target_langs, path, event_type
                ),
                debounce_seconds=self.debounce_seconds,
            )

            handler_key = f"{site_id}:{content_root}"
            self._handlers[handler_key] = handler

            # Schedule directory watch
            watch_path = str(content_dir.resolve())
            if watch_path not in self._watched_dirs:
                self._observer.schedule(handler, watch_path, recursive=True)
                self._watched_dirs.add(watch_path)
                logger.info(f"Watching {watch_path} for site {site_id}")

    def _on_file_change(
        self, site_id: str, target_langs: List[str], file_path: Path, event_type: str
    ) -> None:
        """
        Handle file change by enqueueing translation job.

        Args:
            site_id: Site identifier
            target_langs: Target languages for translation
            file_path: Path to changed file
            event_type: Type of change
        """
        logger.info(f"File {event_type}: {file_path} (site: {site_id})")

        # Skip deletions (we might want to handle these differently in the future)
        if event_type == "deleted":
            logger.debug(f"Skipping deleted file: {file_path}")
            return

        # Create translation job
        job = TranslationJob(
            job_id="",  # Will be generated
            job_type=JobType.FILE,
            site_id=site_id,
            target_langs=target_langs,
            input_paths=[file_path],
            priority=3,  # Auto-mode has higher priority than manual
            mode=JobMode.AUTO,
        )

        try:
            job_id = self.job_enqueue_callback(job)
            logger.info(f"Enqueued translation job {job_id} for {file_path}")
        except Exception as e:
            logger.error(f"Failed to enqueue job for {file_path}: {e}")

    def is_running(self) -> bool:
        """
        Check if watcher is running.

        Returns:
            True if running
        """
        with self._lock:
            return self._running
