"""
Autonomous Content Translation Worker.

Runs scheduled translation tasks on Hugo content directories with:
- Two modes: oneshot (run once) and daemon (self-schedules)
- Timezone-aware scheduling within daily window
- VRAM enforcement for CUDA devices
- Git commit for only modified files
- Telemetry with trigger_type="scheduled"
"""

import argparse
import json
import logging
import os
import platform
import signal
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from src.hardware.vram_enforcer import VRAMEnforcer
from src.observability.git_commit_helper import auto_commit_translations
from src.observability.worker_telemetry import emit_worker_event, start_worker_run, complete_worker_run
from src.translation_engine.engine import TranslationEngine
from src.utils.config_loader import ConfigService
from src.utils.timeout_guard import timeout_guard, TimeoutError
from src.workers.window_scheduler import ScheduleConfig, WindowScheduler
from src.workers.worker_state import record_worker_state

logger = logging.getLogger(__name__)


class AutonomousWorkerConfig:
    """
    Configuration for autonomous content translation worker.

    Attributes:
        config_root: Root directory for configuration files
        site: Optional site ID to process (if None, process all sites)
        mode: "oneshot" or "daemon"
        runs_per_day: Number of runs per day (daemon mode only)
        window_start: Start of daily window (HH:MM)
        window_end: End of daily window (HH:MM)
        timezone: Timezone name (e.g., "America/Los_Angeles")
        jitter_minutes: Random jitter to add/subtract
        max_sites_per_run: Optional limit on sites to process per run
        max_gpu_memory_percent: GPU memory limit (percentage)
        device: Device for model inference (cpu, cuda, mps)
        file_timeout_seconds: Timeout for translation operations (seconds)
    """

    def __init__(
        self,
        config_root: str = "config/",
        site: Optional[str] = None,
        mode: str = "oneshot",
        runs_per_day: int = 5,
        window_start: str = "10:00",
        window_end: str = "22:00",
        timezone: str = "America/Los_Angeles",
        jitter_minutes: int = 10,
        max_sites_per_run: Optional[int] = None,
        max_gpu_memory_percent: Optional[int] = 60,
        device: str = "auto",
        file_timeout_seconds: int = 600,
    ):
        """Initialize worker configuration."""
        self.config_root = config_root
        self.site = site
        self.mode = mode
        self.runs_per_day = runs_per_day
        self.window_start = window_start
        self.window_end = window_end
        self.timezone = timezone
        self.jitter_minutes = jitter_minutes
        self.max_sites_per_run = max_sites_per_run
        self.max_gpu_memory_percent = max_gpu_memory_percent
        self.device = device
        self.file_timeout_seconds = file_timeout_seconds

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> "AutonomousWorkerConfig":
        """Create configuration from command-line arguments."""
        return cls(
            config_root=args.config_root,
            site=args.site,
            mode=args.mode,
            runs_per_day=args.runs_per_day,
            window_start=args.window_start,
            window_end=args.window_end,
            timezone=args.timezone,
            jitter_minutes=args.jitter_minutes,
            max_sites_per_run=args.max_sites_per_run,
            max_gpu_memory_percent=args.max_gpu_memory_percent,
            device=args.device,
            file_timeout_seconds=args.file_timeout_seconds,
        )


class AutonomousContentTranslationWorker:
    """
    Autonomous worker for scheduled content translation.

    Runs translation tasks on Hugo content directories with automatic scheduling,
    VRAM enforcement, and git commit integration.

    Example:
        # Oneshot mode (run once)
        config = AutonomousWorkerConfig(mode="oneshot", site="docs.aspose.net")
        worker = AutonomousContentTranslationWorker(config)
        worker.run()

        # Daemon mode (self-schedules)
        config = AutonomousWorkerConfig(
            mode="daemon",
            runs_per_day=5,
            window_start="10:00",
            window_end="22:00",
            timezone="America/Los_Angeles"
        )
        worker = AutonomousContentTranslationWorker(config)
        worker.run()  # Runs continuously
    """

    _worker_id = "content_worker"
    _worker_log_path = "data/logs/content_worker.log"

    def __init__(self, config: AutonomousWorkerConfig):
        """
        Initialize autonomous worker.

        Args:
            config: Worker configuration
        """
        self.config = config
        self.config_service = None
        self.translation_engine = None
        self.scheduler = None

        # Generate stable run ID for this invocation (used across all sites in this run)
        self.invocation_id = str(uuid.uuid4())

        logger.info(f"Initialized AutonomousContentTranslationWorker: mode={config.mode}")
        logger.info(f"Invocation ID: {self.invocation_id}")

    def setup(self) -> None:
        """
        Setup worker components.

        Initializes:
        - ConfigService for loading site profiles
        - VRAMEnforcer for GPU memory management
        - TranslationEngine for translation execution
        - WindowScheduler for daemon mode scheduling
        """
        logger.info("Setting up autonomous worker components...")

        # Initialize ConfigService
        try:
            self.config_service = ConfigService(self.config.config_root)
            logger.info(f"Loaded config from: {self.config.config_root}")
        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            raise

        # Apply VRAM enforcement if using CUDA
        if self.config.device.startswith("cuda"):
            try:
                hardware_config = {
                    "enable_gpu": True,
                    "max_gpu_memory_percent": self.config.max_gpu_memory_percent,
                }

                enforcer = VRAMEnforcer()
                max_memory_mb, budget = enforcer.enforce_from_config(
                    hardware_config, device=self.config.device
                )

                if budget:
                    logger.info(
                        f"VRAM budget enforced: {max_memory_mb}MB "
                        f"({budget.percent:.1f}% of total)"
                    )
                else:
                    logger.warning("VRAM enforcement skipped (GPU disabled or unavailable)")

            except Exception as e:
                logger.error(f"Failed to enforce VRAM budget: {e}", exc_info=True)

        # Initialize TranslationMemory
        try:
            from src.tm import TranslationMemory
            from src.tm.l1_cache import L1Cache
            from src.tm.l2_persistent import L2PersistentTM
            try:
                from src.tm.l3_semantic import L3SemanticTM
            except ImportError:
                L3SemanticTM = None
            try:
                from src.tm.improvement_queue import ImprovementQueue
            except ImportError:
                ImprovementQueue = None
            from pathlib import Path

            # Get TM paths from global config
            raw_config = self.config_service.get_config()
            paths_config = raw_config.get("paths", {})
            tm_data_dir = Path(paths_config.get("tm_data_dir", "data/tm"))

            # Create TM components
            l1_cache = L1Cache(max_size=10000)
            l2_persistent = L2PersistentTM(db_path=tm_data_dir / "l2.lmdb")

            # Try to initialize L3 semantic TM (optional)
            l3_semantic = None
            if L3SemanticTM is not None:
                try:
                    l3_semantic = L3SemanticTM(
                        index_path=tm_data_dir / "l3_faiss",
                        use_gpu=False  # Use CPU for L3 to save GPU memory
                    )
                except Exception as e:
                    logger.warning(f"L3 semantic TM not available: {e}")

            # Initialize improvement queue if enabled in config
            improvement_queue = None
            if ImprovementQueue is not None:
                tm_improve_cfg = raw_config.get("tm_improvement", {}).get("queue", {})
                if tm_improve_cfg.get("enabled", False):
                    improvement_queue = ImprovementQueue(tm_path=tm_data_dir)
                    logger.info("Initialized ImprovementQueue for TM candidate tracking")

            tm = TranslationMemory(
                l1_cache=l1_cache,
                l2_persistent=l2_persistent,
                l3_semantic=l3_semantic,
                improvement_queue=improvement_queue,
            )
            queue_status = "with ImprovementQueue" if improvement_queue else "no ImprovementQueue"
            logger.info(f"Initialized TranslationMemory (L1+L2+L3, {queue_status})")
        except Exception as e:
            logger.error(f"Failed to initialize TranslationMemory: {e}")
            raise

        # Initialize ModelLoader
        try:
            from src.model_runtime import ModelLoader
            from src.model_runtime.registry import ModelRegistry
            import os

            registry_path = os.path.join(self.config.config_root, "model_registry.yaml")
            model_registry = ModelRegistry(registry_path)
            raw_config = self.config_service.get_config()
            model_loader = ModelLoader(
                registry=model_registry,
                device=self.config.device,
                config=raw_config,
            )
            logger.info(f"Initialized ModelLoader: device={self.config.device}")
        except Exception as e:
            logger.error(f"Failed to initialize ModelLoader: {e}")
            raise

        # Initialize TranslationEngine
        try:
            self.translation_engine = TranslationEngine(
                config_service=self.config_service,
                tm=tm,
                model_loader=model_loader,
                enable_telemetry=True,  # Always enable telemetry for autonomous workers
                model_id="professionalize_llm",
            )
            logger.info("Initialized TranslationEngine")
        except Exception as e:
            logger.error(f"Failed to initialize TranslationEngine: {e}")
            raise

        # Initialize WindowScheduler for daemon mode
        if self.config.mode == "daemon":
            try:
                schedule_config = ScheduleConfig(
                    runs_per_day=self.config.runs_per_day,
                    window_start=self.config.window_start,
                    window_end=self.config.window_end,
                    timezone=self.config.timezone,
                    jitter_minutes=self.config.jitter_minutes,
                )
                self.scheduler = WindowScheduler(schedule_config)
                logger.info(
                    f"Initialized WindowScheduler: {self.config.runs_per_day} runs/day, "
                    f"window {self.config.window_start}-{self.config.window_end} {self.config.timezone}"
                )
            except Exception as e:
                logger.error(f"Failed to initialize scheduler: {e}")
                raise

        logger.info("Setup complete")

    def _write_pid_file(self):
        """Write PID file for watchdog monitoring."""
        pid_path = Path("data/logs") / f"{self._worker_id}.pid"
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text(str(os.getpid()))

    def _write_heartbeat(self, status="alive"):
        """Write heartbeat file for watchdog monitoring."""
        heartbeat_path = Path("data/logs") / f"{self._worker_id}.heartbeat"
        heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
        heartbeat_path.write_text(json.dumps({
            "timestamp": datetime.now().isoformat(),
            "pid": os.getpid(),
            "status": status,
        }))

    def _record_state(self, state: str, *, success: bool = False, error: Optional[str] = None) -> None:
        """Persist durable worker state for health audit tooling."""
        try:
            record_worker_state(
                self._worker_id,
                state,
                success=success,
                error=error,
                log_path=self._worker_log_path,
            )
        except Exception as exc:
            logger.debug(f"Worker state write failed (non-fatal): {exc}")

    def _start_heartbeat_thread(self):
        """Start a daemon thread that writes heartbeat every 3600 seconds (60 minutes)."""
        self._heartbeat_stop_event = threading.Event()

        def _heartbeat_loop():
            while not self._heartbeat_stop_event.is_set():
                try:
                    self._write_heartbeat("alive")
                except Exception as e:
                    logger.warning(f"Heartbeat write failed: {e}")
                self._heartbeat_stop_event.wait(timeout=3600)

        self._heartbeat_thread = threading.Thread(
            target=_heartbeat_loop,
            name=f"{self._worker_id}-heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()
        logger.info("Background heartbeat thread started (3600s interval)")

    def _stop_heartbeat_thread(self):
        """Signal the heartbeat thread to stop."""
        if hasattr(self, '_heartbeat_stop_event'):
            self._heartbeat_stop_event.set()
            if hasattr(self, '_heartbeat_thread'):
                self._heartbeat_thread.join(timeout=5)

    def _preflight_check(self) -> bool:
        """Validate dependencies before run. Returns True if safe to proceed."""
        import shutil
        checks_passed = True

        # 1. GPU available (if device=cuda) - Fall back to CPU if unavailable
        original_device = self.config.device
        if self.config.device == "cuda":
            try:
                import torch
                if not torch.cuda.is_available():
                    logger.warning(
                        "PREFLIGHT WARNING: CUDA requested but not available, falling back to CPU"
                    )
                    self.config.device = "cpu"  # Graceful fallback
            except ImportError:
                logger.warning(
                    "PREFLIGHT WARNING: torch not installed, falling back to CPU"
                )
                self.config.device = "cpu"  # Graceful fallback

        # 2. Config root exists
        config_root = Path(self.config.config_root) if hasattr(self.config, 'config_root') else Path("config")
        if not config_root.exists():
            logger.warning(f"PREFLIGHT FAIL: Config root missing: {config_root}")
            checks_passed = False

        # 3. Disk space > 5%
        try:
            total, used, free = shutil.disk_usage(".")
            if (free / total) < 0.05:
                logger.warning(f"PREFLIGHT FAIL: Disk space critical ({free / total * 100:.1f}% free)")
                checks_passed = False
        except Exception as e:
            logger.warning(f"PREFLIGHT WARNING: Could not check disk space: {e}")

        # Emit preflight telemetry
        try:
            emit_worker_event(
                agent_name="content_worker",
                job_type="worker_preflight",
                status="success" if checks_passed else "failure",
                metrics={
                    "gpu_check": self.config.device != "cuda" or checks_passed,
                    "config_root_exists": config_root.exists(),
                    "device": self.config.device,
                    "device_fallback": original_device != self.config.device,
                    "original_device": original_device,
                },
            )
        except Exception:
            pass

        # Log device fallback info
        if original_device != self.config.device:
            logger.info(
                f"Device fallback applied: {original_device} → {self.config.device}"
            )

        return checks_passed

    def run(self) -> None:
        """
        Run autonomous worker.

        In oneshot mode: Executes one translation run and exits
        In daemon mode: Continuously schedules and executes runs
        """
        self._write_pid_file()
        self._write_heartbeat("starting")
        self._record_state("starting")
        self._start_heartbeat_thread()
        self._lifecycle_event_id = start_worker_run(
            "content_worker", "worker_lifecycle",
            context={
                "mode": self.config.mode,
                "runs_per_day": getattr(self.config, "runs_per_day", None),
                "window": f"{getattr(self.config, 'window_start', '?')}-{getattr(self.config, 'window_end', '?')}",
            },
        )
        self._daemon_start_time = time.time()
        try:
            if self.config.mode == "oneshot":
                self._run_oneshot()
            elif self.config.mode == "daemon":
                self._run_daemon()
            else:
                raise ValueError(f"Invalid mode: {self.config.mode}. Expected 'oneshot' or 'daemon'")
        finally:
            self._stop_heartbeat_thread()
            self._write_heartbeat("stopped")
            self._record_state("stopped")

    def _run_oneshot(self) -> None:
        """Execute a single translation run and exit."""
        logger.info("=" * 80)
        logger.info("ONESHOT MODE: Running single translation pass")
        logger.info("=" * 80)

        if not self._preflight_check():
            logger.warning("Preflight check failed, aborting oneshot run")
            self._record_state("preflight_failed", error="Preflight checks failed")
            return  # Graceful exit, not sys.exit(1)

        try:
            self._commit_orphaned_translations()
            self._execute_translation_run()
            self._recover_pending_commits()
            _run_total_new = sum(getattr(self, "_run_new_files", {}).values())
            logger.info(f"Oneshot run completed: {_run_total_new} new translations")
            self._record_state("run_completed", success=(_run_total_new > 0))
        except Exception as e:
            logger.error(f"Oneshot run failed: {e}", exc_info=True)
            self._record_state("run_failed", error=str(e))
            sys.exit(1)

    def _run_daemon(self) -> None:
        """Continuously schedule and execute translation runs."""
        logger.info("=" * 80)
        logger.info("DAEMON MODE: Starting continuous scheduler")
        logger.info(f"Schedule: {self.config.runs_per_day} runs/day")
        logger.info(f"Window: {self.config.window_start}-{self.config.window_end} {self.config.timezone}")
        logger.info("=" * 80)

        run_count = 0
        consecutive_failures = 0
        max_consecutive_failures = 10

        try:
            while True:
                # Sleep until next run time
                self._write_heartbeat("sleeping")
                next_run = self.scheduler.sleep_until_next_run()
                run_count += 1

                logger.info("=" * 80)
                logger.info(f"SCHEDULED RUN #{run_count} at {next_run.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                logger.info("=" * 80)

                if not self._preflight_check():
                    consecutive_failures += 1
                    logger.error(
                        f"CRITICAL: Run #{run_count} FAILED preflight check "
                        f"({consecutive_failures} consecutive failures)"
                    )
                    self._write_heartbeat("preflight_failed")
                    self._record_state("preflight_failed", error="Preflight checks failed")
                    emit_worker_event(
                        agent_name="content_worker",
                        job_type="worker_preflight_failure",
                        status="failure",
                        error_summary="Preflight checks failed",
                        metrics={"run_number": run_count, "consecutive_failures": consecutive_failures},
                    )

                    # Circuit breaker: exit after too many consecutive failures
                    if consecutive_failures >= max_consecutive_failures:
                        logger.critical(
                            f"Aborting daemon: {max_consecutive_failures} consecutive preflight failures"
                        )
                        self._write_heartbeat("fatal_preflight_failure")
                        self._record_state(
                            "fatal_preflight_failure",
                            error=f"{max_consecutive_failures} consecutive preflight failures",
                        )
                        if getattr(self, "_lifecycle_event_id", None):
                            complete_worker_run(
                                self._lifecycle_event_id,
                                status="failure",
                                duration_ms=int((time.time() - self._daemon_start_time) * 1000),
                                error_summary=f"{max_consecutive_failures} consecutive preflight failures",
                            )
                        sys.exit(1)
                    continue

                try:
                    self._commit_orphaned_translations()
                    self._execute_translation_run()
                    self._recover_pending_commits()
                    _run_total_new = sum(getattr(self, "_run_new_files", {}).values())
                    logger.info(
                        f"Scheduled run #{run_count} completed: {_run_total_new} new translations"
                    )
                    # Only set success=True (which advances last_success_ts) when files
                    # were actually translated. Zero-output runs still record run_completed
                    # but do not advance last_success_ts so health checks remain accurate.
                    self._record_state("run_completed", success=(_run_total_new > 0))
                    consecutive_failures = 0
                except Exception as e:
                    consecutive_failures += 1
                    logger.error(
                        f"Scheduled run #{run_count} failed "
                        f"({consecutive_failures} consecutive): {e}",
                        exc_info=True,
                    )
                    emit_worker_event(
                        agent_name="content_worker",
                        job_type="worker_run_failure",
                        status="failure",
                        error_summary=str(e)[:500],
                        metrics={"run_number": run_count, "consecutive_failures": consecutive_failures},
                    )
                    self._record_state("run_failed", error=str(e))
                    if consecutive_failures >= max_consecutive_failures:
                        logger.critical(
                            f"Aborting daemon: {max_consecutive_failures} consecutive failures"
                        )
                        self._write_heartbeat("fatal_failure")
                        self._record_state(
                            "fatal_failure",
                            error=f"{max_consecutive_failures} consecutive failures",
                        )
                        if getattr(self, "_lifecycle_event_id", None):
                            complete_worker_run(
                                self._lifecycle_event_id,
                                status="failure",
                                duration_ms=int((time.time() - self._daemon_start_time) * 1000),
                                error_summary=f"{max_consecutive_failures} consecutive failures",
                            )
                        sys.exit(1)

                self._write_heartbeat("run_completed")
                self.scheduler.mark_run_complete()

        except KeyboardInterrupt:
            logger.info("Daemon interrupted by user (Ctrl+C)")
            self._record_state("cancelled")
            if getattr(self, "_lifecycle_event_id", None):
                complete_worker_run(
                    self._lifecycle_event_id,
                    status="cancelled",
                    duration_ms=int((time.time() - self._daemon_start_time) * 1000),
                    output_summary=f"Interrupted after {run_count} runs",
                )

    def _execute_translation_run(self) -> None:
        """
        Execute a single translation run.

        For each site:
        1. Load site profile
        2. Translate each content_root directory
        3. Commit only modified files with git_commit_helper
        """
        # Determine sites to process
        if self.config.site:
            # Single site specified
            sites = [self.config.site]
            logger.info(f"Processing single site: {self.config.site}")
        else:
            # Process all sites
            sites = self.config_service.list_sites()
            logger.info(f"Processing all sites: {len(sites)} total")

            # Apply max_sites_per_run limit if configured
            if self.config.max_sites_per_run and len(sites) > self.config.max_sites_per_run:
                sites = sites[: self.config.max_sites_per_run]
                logger.info(f"Limited to {self.config.max_sites_per_run} sites per run")

        # Emit site discovery telemetry
        emit_worker_event(
            agent_name="content_worker",
            job_type="worker_site_discovery",
            items_discovered=len(sites),
            metrics={"sites": sites[:10], "max_sites_per_run": self.config.max_sites_per_run},
        )

        # Process each site
        for site_id in sites:
            try:
                self._process_site(site_id)
            except Exception as e:
                logger.error(f"Failed to process site {site_id}: {e}", exc_info=True)
                # Continue with next site

    def _process_site(self, site_id: str) -> None:
        """
        Process a single site.

        For each content_root:
        1. Run translate_directory with trigger_type="scheduled"
        2. Commit modified files using git_commit_helper

        Args:
            site_id: Site identifier
        """
        logger.info(f"Processing site: {site_id}")

        # Load site profile
        try:
            site_profile = self.config_service.get_site_profile(site_id)
        except Exception as e:
            logger.error(f"Failed to load site profile {site_id}: {e}")
            return

        # Validate required fields
        if not site_profile.content_roots:
            logger.warning(f"Site {site_id} has no content_roots, skipping")
            return

        if not site_profile.target_langs:
            logger.warning(f"Site {site_id} has no target_langs, skipping")
            return

        # Process each content_root
        for content_root in site_profile.content_roots:
            try:
                self._translate_content_root(site_id, content_root, site_profile.target_langs)
            except Exception as e:
                logger.error(
                    f"Failed to translate content_root {content_root} for site {site_id}: {e}",
                    exc_info=True,
                )
                # Continue with next content_root

    def _translate_content_root(
        self, site_id: str, content_root: str, target_langs: List[str]
    ) -> None:
        """
        Translate a single content_root directory.

        Args:
            site_id: Site identifier
            content_root: Content root directory path
            target_langs: Target language codes
        """
        resolved_content_dir = (
            self.config_service.resolve_content_root(content_root)
            if self.config_service is not None
            else Path(content_root)
        )

        if not resolved_content_dir.exists():
            logger.warning(
                "Content root does not exist for site %s: configured='%s' resolved='%s', skipping",
                site_id,
                content_root,
                resolved_content_dir,
            )
            return

        logger.info(f"Translating content_root: {resolved_content_dir}")
        logger.info(f"Target languages: {', '.join(target_langs)}")

        # Run translation with timeout protection
        # Timeout scales with number of target languages
        timeout_seconds = self.config.file_timeout_seconds * len(target_langs)
        operation_name = f"translate_directory({resolved_content_dir.name}, {len(target_langs)} langs)"

        try:
            with timeout_guard(timeout_seconds, operation_name):
                # Run translation with trigger_type="scheduled"
                # This ensures telemetry is tagged correctly
                result = self.translation_engine.translate_directory(
                    site_id=site_id,
                    directory=resolved_content_dir,
                    target_langs=target_langs,
                    recursive=True,
                    parallel=True,
                    trigger_type="scheduled",  # CRITICAL: Use "scheduled" trigger type
                )
        except TimeoutError as e:
            logger.error(
                f"⏱️  TIMEOUT: Translation exceeded {timeout_seconds}s limit: {e}"
            )
            self._write_heartbeat("timeout_detected")
            emit_worker_event(
                agent_name="content_worker",
                job_type="worker_timeout",
                status="failure",
                error_summary=str(e)[:500],
                metrics={
                    "timeout_seconds": timeout_seconds,
                    "content_root": str(content_root),
                    "target_langs": target_langs,
                },
            )
            # Re-raise to trigger consecutive failure tracking
            raise

        # Log summary
        logger.info(
            f"Translation completed: "
            f"{result.successful_files}/{result.total_files} files succeeded, "
            f"{result.failed_files} failed"
        )

        # LLM-WASTE-FIX-1: Skip commit when ALL file results have every language
        # in skipped_langs (no new translations produced).  This avoids the
        # costly collect_output_files() → empty list → fallback git-status cycle
        # that was burning wall-clock time on sites with all outputs present.
        _has_new_translations = True
        if hasattr(result, 'file_results') and result.file_results:
            _has_new_translations = any(
                set(fr.outputs.keys()) - set(fr.skipped_langs)
                for fr in result.file_results
                if fr.success and fr.outputs
            )
            if not _has_new_translations:
                logger.info(
                    "All %d files had every language skipped (outputs already exist). "
                    "Skipping commit attempt.",
                    result.successful_files,
                )

        # Commit only modified files using git_commit_helper
        # This reuses existing TC-GIT-01 flow with commit hash association
        if result.successful_files > 0 and _has_new_translations:
            logger.info("Auto-committing translation outputs...")

            # Pre-commit diagnostic logging
            logger.info(f"[COMMIT-DIAG] Pre-commit state:")
            logger.info(f"  - successful_files: {result.successful_files}")
            logger.info(f"  - total_files: {result.total_files}")
            logger.info(f"  - failed_files: {result.failed_files}")

            if hasattr(result, 'file_results') and result.file_results:
                logger.info(f"  - file_results count: {len(result.file_results)}")
                # Sample first result for diagnostics
                first = result.file_results[0]
                logger.info(f"  - first result success: {first.success}")
                logger.info(f"  - first result outputs: {list(first.outputs.keys())}")
                logger.info(f"  - first result skipped_langs: {first.skipped_langs}")
                logger.info(f"  - first output path: {list(first.outputs.values())[0] if first.outputs else 'None'}")

            # Generate run_id for this specific translation (includes invocation_id + site + content_root)
            run_id = f"{self.invocation_id}:{site_id}:{Path(content_root).name}"

            success = auto_commit_translations(
                result=result,
                site_id=site_id,
                target_langs=target_langs,
                run_id=run_id,
                config_service=self.config_service,
            )

            # Post-commit diagnostic logging
            logger.info(f"[COMMIT-DIAG] Post-commit result: {success}")

            if success:
                logger.info("Git commit successful")
            else:
                # Elevate from WARNING to ERROR for visibility
                logger.error("Git commit FAILED or was SKIPPED - check logs above for details")
        else:
            logger.info("No successful translations, skipping git commit")

    @staticmethod
    def _build_orphan_commit_message(
        files: List[Path],
        site_id: str,
        config: "GitCommitConfig",
    ) -> str:
        """Build a commit message for orphaned translation files.

        Args:
            files: List of orphaned translation file paths
            site_id: Site identifier (e.g. "blog.aspose.net")
            config: Git commit configuration for co-author info

        Returns:
            Formatted commit message string
        """
        # Detect languages from file stems: index.de.md → "de"
        lang_counts: dict = {}
        for f in files:
            stem = Path(f).stem  # e.g. "index.de"
            parts = stem.rsplit(".", 1)
            if len(parts) == 2:
                lang = parts[1]
                lang_counts[lang] = lang_counts.get(lang, 0) + 1

        # Detect distinct products: content/<site>/<product>/...
        products: set = set()
        for f in files:
            path_parts = Path(f).parts
            for i, part in enumerate(path_parts):
                if ".aspose." in part or ".aspose.net" in part or ".aspose.com" in part:
                    if i + 1 < len(path_parts):
                        products.add(path_parts[i + 1])
                    break

        site_label = site_id.split(".")[0]  # "reference", "blog", "docs"
        # Blog uses site-level scope always; reference/docs use product scope when unambiguous
        if "blog" in site_id:
            scope = site_label
        elif len(products) == 1:
            scope = list(products)[0]
        else:
            scope = site_label

        if "reference" in site_id:
            content_type = "API references"
        elif "blog" in site_id:
            content_type = "blog posts"
        else:
            content_type = "pages"

        n = len(files)
        subject = f"chore({scope}): translate {n} {content_type} (orphan recovery)"

        lang_lines = "\n".join(
            f"- {lang} ({count})" for lang, count in sorted(lang_counts.items())
        )
        body = (
            f"{n} translation file(s) recovered across {site_id}.\n"
            f"- Model: orphan recovery\n"
            f"- Languages:\n{lang_lines}\n\n"
            f"Run ID: orphan-sweep:{site_id}\n"
            f"Site: {site_id}\n\n"
            f"Co-authored-by: {config.co_author_name} <{config.co_author_email}>"
        )
        return f"{subject}\n\n{body}"

    @staticmethod
    def _validate_orphan_structural_integrity(
        orphan_path: Path,
        git_root: Path,
        source_lang: str,
        per_language_folders: bool,
    ) -> bool:
        """Check that an orphaned translation file preserves the structural
        integrity of its source file (code blocks, heading count, no TITLE: prefix).

        CRITICAL: Reads source from git HEAD (not disk) to avoid comparing
        against a corrupted working-tree copy of the source file.

        Returns True if the file passes validation, False if it should be rejected.
        """
        import re
        import subprocess

        # --- Derive source file path (relative to git root) ---
        try:
            orphan_rel = orphan_path.resolve().relative_to(git_root.resolve())
        except ValueError:
            logger.warning("[orphan_gate] Cannot derive relative path for %s", orphan_path)
            return True  # can't validate — let it through

        if per_language_folders:
            # Folder-based: e.g. content/fr/blog/post/index.md → content/en/blog/post/index.md
            parts = list(orphan_rel.parts)
            if len(parts) >= 2:
                parts[0] = source_lang
                source_rel = Path(*parts)
            else:
                return True
        else:
            # File-based: e.g. content/blog/post/index.pl.md → content/blog/post/index.md
            name = orphan_path.name
            # Strip language suffix: index.pl.md → index.md
            stem_parts = name.rsplit(".", 2)
            if len(stem_parts) >= 3:
                source_name = stem_parts[0] + "." + stem_parts[-1]
            else:
                return True  # can't determine source name
            source_rel = orphan_rel.parent / source_name

        # --- Read source from git HEAD (not disk!) ---
        source_rel_posix = source_rel.as_posix()
        try:
            result = subprocess.run(
                ["git", "show", f"HEAD:{source_rel_posix}"],
                cwd=str(git_root),
                capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                timeout=10,
            )
            if result.returncode != 0:
                logger.debug("[orphan_gate] Source not in git HEAD: %s", source_rel_posix)
                return True  # source missing from git — can't compare
            source_text = result.stdout
        except Exception as e:
            logger.warning("[orphan_gate] git show failed for %s: %s", source_rel_posix, e)
            return True

        # --- Read orphan from disk ---
        try:
            orphan_text = orphan_path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            logger.warning("[orphan_gate] Cannot read orphan %s: %s", orphan_path.name, e)
            return True

        # --- Strip frontmatter for body comparison ---
        def strip_frontmatter(text: str) -> str:
            if text.startswith("---"):
                end = text.find("---", 3)
                if end != -1:
                    return text[end + 3:].lstrip("\n")
            return text

        source_body = strip_frontmatter(source_text)
        orphan_body = strip_frontmatter(orphan_text)

        # --- Check 1: TITLE: prefix (hallucination marker) ---
        if orphan_body.lstrip().startswith("TITLE:"):
            logger.error(
                "[orphan_gate] REJECTED %s — body starts with 'TITLE:' (hallucination marker)",
                orphan_path.name,
            )
            return False

        # --- Check 2: Code block preservation ---
        source_code_blocks = len(re.findall(r"^```", source_body, re.MULTILINE)) // 2
        orphan_code_blocks = len(re.findall(r"^```", orphan_body, re.MULTILINE)) // 2

        if source_code_blocks > 0 and orphan_code_blocks < source_code_blocks:
            logger.error(
                "[orphan_gate] REJECTED %s — code blocks decreased: source=%d orphan=%d",
                orphan_path.name, source_code_blocks, orphan_code_blocks,
            )
            return False

        # --- Check 3: Heading surplus (hallucinated sections) ---
        source_headings = len(re.findall(r"^#{1,6}\s", source_body, re.MULTILINE))
        orphan_headings = len(re.findall(r"^#{1,6}\s", orphan_body, re.MULTILINE))

        if orphan_headings >= source_headings + 3:
            logger.error(
                "[orphan_gate] REJECTED %s — heading surplus: source=%d orphan=%d (+%d)",
                orphan_path.name, source_headings, orphan_headings,
                orphan_headings - source_headings,
            )
            return False

        return True

    def _commit_orphaned_translations(self) -> int:
        """Scan all configured content roots for .md files written but not committed
        in previous runs, and commit them per-site.

        This handles cases where a translation run wrote files to disk but the git
        commit step failed or was interrupted (timeout, index.lock contention, etc.).

        Returns:
            Total number of files committed across all sites.
        """
        # DISABLED: orphan recovery is committing corrupted files (code blocks
        # stripped, hallucinated content, even overwriting English source files).
        # Root cause investigation in progress. See commit 3f90f922.
        logger.warning("[orphan_sweep] DISABLED — orphan recovery is suspended pending root cause fix")
        return 0
        import subprocess
        from src.observability.git_commit import GitCommitter, GitCommitConfig
        from src.observability.git_context import find_git_root

        total_committed = 0

        try:
            sites = self.config_service.list_sites()
        except Exception as exc:
            logger.warning(f"[orphan_sweep] Could not list sites: {exc}")
            return 0

        for site_id in sites:
            try:
                profile = self.config_service.get_site_profile(site_id)
                content_roots = profile.content_roots or []
            except Exception:
                continue

            for content_root_str in content_roots:
                try:
                    content_root = self.config_service.resolve_content_root(content_root_str)
                    if not content_root.exists():
                        continue

                    git_root = find_git_root(content_root)
                    if not git_root:
                        continue

                    # Check if git commit is enabled
                    try:
                        gc_cfg = self.config_service.global_config.git_commit
                        if isinstance(gc_cfg, dict):
                            enabled = gc_cfg.get("enabled", True)
                            co_author = gc_cfg.get("co_author_name", "Hugo Translator")
                            co_email = gc_cfg.get("co_author_email", "hugo-translator@aspose.net")
                            timeout = gc_cfg.get("timeout_seconds", 60)
                            auto_push = gc_cfg.get("auto_push", True)
                        else:
                            enabled = getattr(gc_cfg, "enabled", True)
                            co_author = getattr(gc_cfg, "co_author_name", "Hugo Translator")
                            co_email = getattr(gc_cfg, "co_author_email", "hugo-translator@aspose.net")
                            timeout = getattr(gc_cfg, "timeout_seconds", 60)
                            auto_push = getattr(gc_cfg, "auto_push", True)
                    except Exception:
                        enabled, co_author, co_email, timeout, auto_push = (
                            True, "Hugo Translator", "hugo-translator@aspose.net", 60, True
                        )

                    if not enabled:
                        logger.info(f"[orphan_sweep] Git commit disabled — skipping {site_id}")
                        continue

                    # Find orphaned .md files via git status
                    try:
                        rel_root = content_root.resolve().relative_to(git_root.resolve())
                    except ValueError:
                        rel_root = Path(".")

                    status_result = subprocess.run(
                        ["git", "status", "--porcelain", str(rel_root)],
                        cwd=str(git_root),
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    if status_result.returncode != 0:
                        logger.warning(
                            f"[orphan_sweep] git status failed for {site_id}: "
                            f"{status_result.stderr.strip()}"
                        )
                        continue

                    # Determine localization strategy to filter translation outputs
                    output_layout = getattr(profile, 'output_layout', None)
                    per_language_folders = False
                    if output_layout:
                        per_language_folders = getattr(output_layout, 'per_language_folders', False)
                    source_lang = getattr(profile, 'default_source_lang', 'en')
                    target_langs = getattr(profile, 'target_langs', None) or []

                    orphaned: List[Path] = []
                    for line in status_result.stdout.splitlines():
                        status_code = line[:2]
                        file_rel = line[3:].strip()
                        if "M" in status_code or "A" in status_code or status_code == "??":
                            abs_path = git_root / file_rel
                            if abs_path.is_dir():
                                # Untracked directory — git shows "?? dir/" for whole tree
                                orphaned.extend(abs_path.rglob("*.md"))
                            elif abs_path.suffix == ".md" and abs_path.exists():
                                orphaned.append(abs_path)

                    # Filter to translation outputs only — exclude source-language
                    # files and files changed by other processes (e.g. example reviewer)
                    if per_language_folders:
                        # Folder-based: keep only files NOT in the source lang folder
                        source_markers = [f'/{source_lang}/', f'\\{source_lang}\\']
                        orphaned = [
                            f for f in orphaned
                            if not any(m in str(f) for m in source_markers)
                        ]
                    elif target_langs:
                        # File-based: keep only files with a target-lang suffix
                        from src.translation_engine.engine import _is_translated_filename
                        orphaned = [
                            f for f in orphaned
                            if _is_translated_filename(f.name, target_langs, source_lang)[0]
                        ]

                    if not orphaned:
                        continue

                    # Structural integrity gate — reject orphans with code block
                    # loss, hallucinated sections, or TITLE: prefix corruption
                    pre_gate = len(orphaned)
                    orphaned = [
                        f for f in orphaned
                        if self._validate_orphan_structural_integrity(
                            f, git_root, source_lang, per_language_folders,
                        )
                    ]
                    rejected = pre_gate - len(orphaned)
                    if rejected:
                        logger.warning(
                            "[orphan_sweep] %s: structural gate rejected %d/%d file(s)",
                            site_id, rejected, pre_gate,
                        )

                    if not orphaned:
                        continue

                    logger.info(
                        f"[orphan_sweep] {site_id}: found {len(orphaned)} orphaned file(s)"
                    )

                    # Build config object for committer
                    git_config = GitCommitConfig(
                        enabled=True,
                        auto_push=auto_push,
                        co_author_name=co_author,
                        co_author_email=co_email,
                        timeout_seconds=timeout,
                    )

                    commit_msg = self._build_orphan_commit_message(orphaned, site_id, git_config)

                    committer = GitCommitter(git_config)
                    committer._recover_stale_index_lock(git_root)
                    staged = committer._stage_files(orphaned, git_root)
                    if staged == 0:
                        logger.warning(f"[orphan_sweep] {site_id}: nothing staged — skipping commit")
                        continue

                    commit_hash = committer._create_commit(commit_msg, git_root)
                    if commit_hash:
                        logger.info(
                            f"[orphan_sweep] ✓ {site_id}: committed {staged} orphaned file(s) "
                            f"({commit_hash[:7]})"
                        )
                        total_committed += staged
                    else:
                        logger.warning(
                            f"[orphan_sweep] {site_id}: commit failed — {committer._last_error}"
                        )

                except subprocess.TimeoutExpired:
                    logger.warning(f"[orphan_sweep] {site_id}/{content_root_str}: git status timed out")
                except Exception as exc:
                    logger.warning(f"[orphan_sweep] {site_id}/{content_root_str}: {exc}")

        return total_committed

    def _recover_pending_commits(self) -> None:
        """Retry any .pending_commit.json / .pending_commit.json.stale_* files left
        behind by a previous failed commit attempt (e.g. git commit timeout).

        Discovers the git root for every configured content root, then delegates to
        recover_pending_commits() which handles staging and committing.
        """
        from src.observability.git_commit_helper import recover_pending_commits
        from src.observability.git_context import find_git_root

        git_roots: set = set()
        try:
            sites = self.config_service.list_sites()
        except Exception as exc:
            logger.warning(f"[pending_commit_recovery] Could not list sites: {exc}")
            return

        for site_id in sites:
            try:
                profile = self.config_service.get_site_profile(site_id)
                for content_root in (profile.content_roots or []):
                    try:
                        resolved = self.config_service.resolve_content_root(content_root)
                        gr = find_git_root(resolved)
                        if gr:
                            git_roots.add(gr)
                    except Exception:
                        pass
            except Exception:
                pass

        for git_root in git_roots:
            try:
                n = recover_pending_commits(git_root)
                if n > 0:
                    logger.info(
                        f"[pending_commit_recovery] Recovered {n} commit(s) in {git_root}"
                    )
            except Exception as exc:
                logger.warning(
                    f"[pending_commit_recovery] Error processing {git_root}: {exc}"
                )


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Autonomous Content Translation Worker - Scheduled translation of Hugo content",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Oneshot mode - run once on single site
  python -m src.workers.autonomous_content_translation_worker --mode oneshot --site docs.aspose.net

  # Oneshot mode - run once on all sites
  python -m src.workers.autonomous_content_translation_worker --mode oneshot

  # Daemon mode - self-schedule 5 runs/day
  python -m src.workers.autonomous_content_translation_worker --mode daemon --runs-per-day 5

  # Daemon mode with custom window
  python -m src.workers.autonomous_content_translation_worker \\
    --mode daemon \\
    --runs-per-day 4 \\
    --window-start 09:00 \\
    --window-end 21:00 \\
    --timezone America/New_York
        """,
    )

    # Core arguments
    parser.add_argument(
        "--config-root",
        type=str,
        default="config/",
        help="Root directory for configuration files (default: config/)",
    )

    parser.add_argument(
        "--site",
        type=str,
        default=None,
        help="Site ID to process (if omitted, process all sites)",
    )

    parser.add_argument(
        "--mode",
        type=str,
        choices=["oneshot", "daemon"],
        default="oneshot",
        help="Execution mode: oneshot (run once) or daemon (self-schedule) (default: oneshot)",
    )

    # Scheduling arguments (daemon mode only)
    parser.add_argument(
        "--runs-per-day",
        type=int,
        default=5,
        help="Number of runs per day in daemon mode (default: 5)",
    )

    parser.add_argument(
        "--window-start",
        type=str,
        default="10:00",
        help="Start of daily window in HH:MM format (default: 10:00)",
    )

    parser.add_argument(
        "--window-end",
        type=str,
        default="22:00",
        help="End of daily window in HH:MM format (default: 22:00)",
    )

    parser.add_argument(
        "--timezone",
        type=str,
        default="America/Los_Angeles",
        help="Timezone name (default: America/Los_Angeles)",
    )

    parser.add_argument(
        "--jitter-minutes",
        type=int,
        default=10,
        help="Random jitter to add/subtract in minutes (default: 10)",
    )

    # Safety and resource arguments
    parser.add_argument(
        "--max-sites-per-run",
        type=int,
        default=None,
        help="Maximum number of sites to process per run (default: no limit)",
    )

    parser.add_argument(
        "--max-gpu-memory-percent",
        type=int,
        default=60,
        help="Maximum GPU memory usage percentage (default: 60)",
    )

    parser.add_argument(
        "--device",
        type=str,
        default="auto",
        help="Device for model inference: cpu, cuda, mps, or auto (default: auto)",
    )

    parser.add_argument(
        "--file-timeout-seconds",
        type=int,
        default=600,
        help="Timeout for translation operations in seconds (default: 600 = 10 minutes)",
    )

    # Logging
    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level (default: INFO)",
    )

    return parser.parse_args()


def main():
    """Main entry point for autonomous worker."""
    # Parse arguments
    args = parse_args()

    log_dir = Path("data/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "content_worker.log"

    # Setup logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_path, encoding="utf-8"),
        ],
        force=True,
    )

    logger.info("=" * 80)
    logger.info("AUTONOMOUS CONTENT TRANSLATION WORKER")
    logger.info("=" * 80)
    logger.info(f"Mode: {args.mode}")
    logger.info(f"Config root: {args.config_root}")
    logger.info(f"Site: {args.site or 'ALL'}")
    logger.info(f"Device: {args.device}")

    if args.mode == "daemon":
        logger.info(f"Runs per day: {args.runs_per_day}")
        logger.info(f"Window: {args.window_start}-{args.window_end} {args.timezone}")

    logger.info("=" * 80)

    # Create worker configuration
    config = AutonomousWorkerConfig.from_args(args)

    # Create and run worker
    worker = AutonomousContentTranslationWorker(config)

    # Setup with retry and exponential backoff for transient failures
    max_setup_retries = 5
    for attempt in range(1, max_setup_retries + 1):
        try:
            worker.setup()
            break
        except Exception as e:
            if attempt == max_setup_retries:
                logger.error(f"Setup failed after {max_setup_retries} attempts: {e}")
                sys.exit(1)
            backoff = min(30 * (2 ** (attempt - 1)), 300)
            logger.warning(
                f"Setup attempt {attempt}/{max_setup_retries} failed: {e}. "
                f"Retrying in {backoff}s..."
            )
            time.sleep(backoff)

    # Register signal handlers for graceful shutdown
    def _shutdown_handler(signum, frame):
        sig_name = signal.Signals(signum).name if hasattr(signal, 'Signals') else str(signum)
        logger.warning(f"Received {sig_name}, initiating graceful shutdown...")
        worker._stop_heartbeat_thread()
        worker._write_heartbeat("shutting_down")
        try:
            from src.observability.graceful_shutdown import cleanup_telemetry_contexts
            cleanup_telemetry_contexts(sig_name)
        except Exception:
            pass
        sys.exit(0)

    for sig in [signal.SIGINT, signal.SIGTERM]:
        signal.signal(sig, _shutdown_handler)
    if platform.system() == "Windows" and hasattr(signal, 'SIGBREAK'):
        signal.signal(signal.SIGBREAK, _shutdown_handler)

    worker.run()


if __name__ == "__main__":
    main()
