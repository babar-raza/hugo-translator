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

            tm = TranslationMemory(
                l1_cache=l1_cache,
                l2_persistent=l2_persistent,
                l3_semantic=l3_semantic
            )
            logger.info("Initialized TranslationMemory (L1+L2+L3)")
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

    def _start_heartbeat_thread(self):
        """Start a daemon thread that writes heartbeat every 60 seconds."""
        self._heartbeat_stop_event = threading.Event()

        def _heartbeat_loop():
            while not self._heartbeat_stop_event.is_set():
                try:
                    self._write_heartbeat("alive")
                except Exception as e:
                    logger.warning(f"Heartbeat write failed: {e}")
                self._heartbeat_stop_event.wait(timeout=60)

        self._heartbeat_thread = threading.Thread(
            target=_heartbeat_loop,
            name=f"{self._worker_id}-heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()
        logger.info("Background heartbeat thread started (60s interval)")

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

    def _run_oneshot(self) -> None:
        """Execute a single translation run and exit."""
        logger.info("=" * 80)
        logger.info("ONESHOT MODE: Running single translation pass")
        logger.info("=" * 80)

        if not self._preflight_check():
            logger.warning("Preflight check failed, aborting oneshot run")
            return  # Graceful exit, not sys.exit(1)

        try:
            self._execute_translation_run()
            logger.info("Oneshot run completed successfully")
        except Exception as e:
            logger.error(f"Oneshot run failed: {e}", exc_info=True)
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
                    self._execute_translation_run()
                    logger.info(f"Scheduled run #{run_count} completed successfully")
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
                    if consecutive_failures >= max_consecutive_failures:
                        logger.critical(
                            f"Aborting daemon: {max_consecutive_failures} consecutive failures"
                        )
                        self._write_heartbeat("fatal_failure")
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
        content_dir = Path(content_root)

        if not content_dir.exists():
            logger.warning(f"Content root does not exist: {content_root}, skipping")
            return

        logger.info(f"Translating content_root: {content_root}")
        logger.info(f"Target languages: {', '.join(target_langs)}")

        # Run translation with timeout protection
        # Timeout scales with number of target languages
        timeout_seconds = self.config.file_timeout_seconds * len(target_langs)
        operation_name = f"translate_directory({content_dir.name}, {len(target_langs)} langs)"

        try:
            with timeout_guard(timeout_seconds, operation_name):
                # Run translation with trigger_type="scheduled"
                # This ensures telemetry is tagged correctly
                result = self.translation_engine.translate_directory(
                    site_id=site_id,
                    directory=content_dir,
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

        # Commit only modified files using git_commit_helper
        # This reuses existing TC-GIT-01 flow with commit hash association
        if result.successful_files > 0:
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

    # Setup logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
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
