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

from src.hardware.vram_enforcer import VRAMEnforcer
from src.observability.git_commit_helper import auto_commit_translations
from src.observability.worker_telemetry import (
    complete_worker_run,
    emit_worker_event,
    start_worker_run,
)
from src.translation_engine.engine import TranslationEngine
from src.utils.config_loader import ConfigService
from src.utils.timeout_guard import TimeoutError, timeout_guard
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
        site: str | None = None,
        mode: str = "oneshot",
        runs_per_day: int = 5,
        window_start: str = "10:00",
        window_end: str = "22:00",
        timezone: str = "America/Los_Angeles",
        jitter_minutes: int = 10,
        max_sites_per_run: int | None = None,
        max_seconds_per_run: int | None = None,
        max_gpu_memory_percent: int | None = 60,
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
        self.max_seconds_per_run = max_seconds_per_run
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
        self._site_profile_cache = {}
        self._site_profile_errors = {}

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
            from src.tm.l2_persistent import L2_DB_NAME, L2PersistentTM
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
            l2_max_size_mb = raw_config.get("tm_defaults", {}).get("l2_max_size_mb", 1536)
            l2_persistent = L2PersistentTM(db_path=tm_data_dir / L2_DB_NAME, max_size_mb=l2_max_size_mb)
            _l2s = l2_persistent.get_stats()
            logger.info(
                "[L2] map used: %.0f / %.0f MiB (%.1f%%) — %d entries",
                _l2s["used_mb"], _l2s["map_size_mb"], _l2s["used_pct"], _l2s["entries"],
            )

            # Try to initialize L3 semantic TM (optional)
            l3_semantic = None
            if L3SemanticTM is not None:
                try:
                    l3_semantic = L3SemanticTM(
                        index_path=tm_data_dir / "l3_faiss",
                        use_gpu=True  # TC-L3-002: ~80MB encoder, safe on RTX 4090; CPU fallback built-in
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
            import os

            from src.model_runtime import ModelLoader
            from src.model_runtime.registry import ModelRegistry

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
            global_config = self.config_service.get_config()
            content_hash_enabled = global_config.get('features', {}).get('enable_content_hash_tracking', False)
            self.translation_engine = TranslationEngine(
                config_service=self.config_service,
                tm=tm,
                model_loader=model_loader,
                enable_telemetry=True,  # Always enable telemetry for autonomous workers
                model_id=global_config.get('model_defaults', {}).get('fallback_model', 'm2m100_1.2b'),
                enable_content_hash_tracking=content_hash_enabled,
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
        """Write PID file for watchdog monitoring (with single-instance guard)."""
        from src.workers.worker_state import acquire_pid_file

        if not acquire_pid_file(self._worker_id):
            logger.critical(
                "Another instance of %s is already running. Exiting.",
                self._worker_id,
            )
            sys.exit(1)

    def _write_heartbeat(self, status="alive"):
        """Write heartbeat file for watchdog monitoring."""
        heartbeat_path = Path("data/logs") / f"{self._worker_id}.heartbeat"
        heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
        heartbeat_path.write_text(json.dumps({
            "timestamp": datetime.now().isoformat(),
            "pid": os.getpid(),
            "status": status,
        }))

    def _record_state(self, state: str, *, success: bool = False, error: str | None = None) -> None:
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

        # 3. Disk space > 5% (check output drive, not CWD)
        try:
            # Check the content root drive (where translations are written)
            disk_check_path = "."
            if self.config_service and self.config.site:
                try:
                    profile = self.config_service.get_site_profile(self.config.site)
                    if profile and profile.content_roots:
                        resolved = self.config_service.resolve_content_root(profile.content_roots[0])
                        disk_check_path = str(resolved)
                except Exception:
                    pass  # Fall back to CWD
            total, used, free = shutil.disk_usage(disk_check_path)
            if (free / total) < 0.05:
                logger.warning(f"PREFLIGHT FAIL: Disk space critical ({free / total * 100:.1f}% free on {disk_check_path})")
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
            # TC-REEXEC-06: Campaign config gate — daemon mode must not run
            # unless scheduler.campaign_mode_enabled=true in global.yaml.
            # This prevents accidental daemon spawning while scheduler safety
            # gates (TC-SCHED-01..06) are incomplete. Oneshot is not gated.
            if self.config.mode == "daemon":
                _raw_cfg = getattr(self.config_service, '_raw_global_config', {})
                _sched_cfg = _raw_cfg.get('scheduler', {})
                if not _sched_cfg.get('campaign_mode_enabled', False):
                    logger.info(
                        "[SCHED] campaign_mode_enabled=false in config. "
                        "Daemon exiting safely. Set scheduler.campaign_mode_enabled=true "
                        "in global.yaml after TC-SCHED-01..06 pass all gates."
                    )
                    return

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
                # BUG-1 FIX: Release VRAM before sleeping so TM worker can load its LLM.
                # M2M100 (4.7 GB) stayed resident across all sleep periods without this call.
                # Mirrors the pattern in tm_improvement_worker.py:_offload_resources().
                self._offload_models()
                # Sleep until next run time
                self._write_heartbeat("sleeping")
                next_run = self.scheduler.sleep_until_next_run()
                run_count += 1

                # TC-L3-007: Reload L3 encoder to GPU on wake
                try:
                    l3 = getattr(getattr(self.translation_engine, "tm", None), "l3", None)
                    if l3 is not None and hasattr(l3, "reload_to_gpu"):
                        l3.reload_to_gpu()
                except Exception as e:
                    logger.debug("[VRAM] L3 reload skipped: %s", e)

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
        # BUG-2 FIX: Initialize per-run tracking so health monitoring works correctly.
        # Without this, _run_new_files is always {} → success=False on every run →
        # last_success_ts is never written → health checks show "never succeeded".
        # Also initializes _run_start so per-site time limits are enforced.
        self._run_new_files = {}
        self._run_start = time.time()

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
            site_profile = self._get_site_profile(site_id)
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
            except (TypeError, AttributeError) as e:
                logger.critical(
                    "Code error in content_root %s for site %s (will recur on retry): %s",
                    content_root, site_id, e, exc_info=True,
                )
            except Exception as e:
                logger.error(
                    f"Failed to translate content_root {content_root} for site {site_id}: {e}",
                    exc_info=True,
                )
                # Continue with next content_root

    def _get_site_profile(self, site_id: str):
        """Load and cache a site profile for the current worker invocation."""
        if not hasattr(self, "_site_profile_cache") or self._site_profile_cache is None:
            self._site_profile_cache = {}
        if not hasattr(self, "_site_profile_errors") or self._site_profile_errors is None:
            self._site_profile_errors = {}
        if site_id in self._site_profile_errors:
            raise self._site_profile_errors[site_id]
        if site_id not in self._site_profile_cache:
            try:
                self._site_profile_cache[site_id] = self.config_service.get_site_profile(site_id)
            except Exception as exc:
                self._site_profile_errors[site_id] = exc
                raise
        return self._site_profile_cache[site_id]

    def _iter_recovery_git_roots(self) -> list[Path]:
        """Discover git roots relevant to this worker run without reloading profiles."""
        from src.observability.git_context import find_git_root

        git_roots: set[Path] = set()
        sites = [self.config.site] if self.config.site else self.config_service.list_sites()
        if (
            not self.config.site
            and self.config.max_sites_per_run
            and len(sites) > self.config.max_sites_per_run
        ):
            sites = sites[: self.config.max_sites_per_run]
        for site_id in sites:
            try:
                profile = self._get_site_profile(site_id)
            except Exception:
                continue

            for content_root_str in (profile.content_roots or []):
                try:
                    content_root = self.config_service.resolve_content_root(content_root_str)
                    git_root = find_git_root(content_root)
                    if git_root:
                        git_roots.add(git_root)
                except Exception:
                    continue

        return sorted(git_roots)

    def _site_ids_for_git_root(self, git_root: Path) -> list[str]:
        """Return configured sites whose content roots live under this git root."""
        from src.observability.git_context import find_git_root

        site_ids: list[str] = []
        sites = [self.config.site] if self.config.site else self.config_service.list_sites()
        if (
            not self.config.site
            and self.config.max_sites_per_run
            and len(sites) > self.config.max_sites_per_run
        ):
            sites = sites[: self.config.max_sites_per_run]

        for site_id in sites:
            try:
                profile = self._get_site_profile(site_id)
            except Exception:
                continue

            for content_root_str in (profile.content_roots or []):
                try:
                    content_root = self.config_service.resolve_content_root(content_root_str)
                    if find_git_root(content_root) == git_root:
                        site_ids.append(site_id)
                        break
                except Exception:
                    continue

        return site_ids

    def _translate_content_root(
        self, site_id: str, content_root: str, target_langs: list[str],
        batch_idx: int = 1,
    ) -> None:
        """
        Translate a single content_root directory.

        Supports chunked commit mode (files_per_commit > 0) where translation
        runs in fixed-size slices with a commit after each chunk.  Legacy mode
        (files_per_commit == 0) is a single-pass translate + commit.

        Args:
            site_id: Site identifier
            content_root: Content root directory path
            target_langs: Target language codes
            batch_idx: Daemon-run batch number (used to build unique run_ids)
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

        # Read chunked commit config
        raw_config = self.config_service.get_config() if self.config_service is not None else {}
        files_per_commit = raw_config.get("git_commit", {}).get("files_per_commit", 0) or 0

        # Compute run_deadline (per-site override > global config)
        per_site_limits = (
            raw_config
            .get("autonomous_content_translation", {})
            .get("execution", {})
            .get("per_site_limits", {})
        )
        site_max_seconds = (
            per_site_limits.get(site_id, {}).get("max_seconds_per_run")
            if isinstance(per_site_limits, dict)
            else None
        )
        effective_max_seconds = site_max_seconds or getattr(self.config, "max_seconds_per_run", None)
        _PRE_RUN_BUFFER = 300  # seconds reserved for clean shutdown
        run_deadline = (
            self._run_start + effective_max_seconds - _PRE_RUN_BUFFER
            if effective_max_seconds is not None and getattr(self, "_run_start", None) is not None
            else None
        )
        self._run_deadline = run_deadline  # TC-06: expose for _run_post_contamination_scan

        logger.info(f"Translating content_root: {resolved_content_dir}")
        logger.info(f"Target languages: {', '.join(target_langs)}")

        # WS-COMP-8: Accumulators for coverage telemetry emitted at end of this method.
        _cov_total_needing_work = 0
        _cov_successful = 0
        _cov_skipped = 0

        timeout_seconds = self.config.file_timeout_seconds * len(target_langs)
        operation_name = f"translate_directory({resolved_content_dir.name}, {len(target_langs)} langs)"

        # Safe default — overwritten by both the chunked loop and single-pass branch below.
        # Prevents UnboundLocalError if the chunked-mode deadline check fires before chunk 0.
        run_id = f"{self.invocation_id}:{site_id}:{Path(content_root).name}"

        # Pre-loop remaining time check
        if run_deadline is not None:
            remaining = run_deadline - time.time()
            if remaining <= 0:
                logger.warning("Run deadline already exceeded before translation, skipping")
                return
            logger.info(f"Time budget for this content root: {remaining:.0f}s")

        if files_per_commit > 0:
            # Chunked commit mode: translate in fixed-size slices
            chunk_idx = 0
            skip_first = 0
            while True:
                # Pre-chunk deadline check
                if run_deadline is not None and time.time() >= run_deadline:
                    logger.info("Run deadline reached, stopping chunked translation")
                    break

                run_id = f"{self.invocation_id}:{site_id}:batch-{batch_idx}-chunk-{chunk_idx}"
                try:
                    with timeout_guard(timeout_seconds, operation_name):
                        result = self.translation_engine.translate_directory(
                            site_id=site_id,
                            directory=resolved_content_dir,
                            target_langs=target_langs,
                            recursive=True,
                            parallel=True,
                            trigger_type="scheduled",
                            max_files=files_per_commit,
                            skip_first=skip_first,
                            run_deadline=run_deadline,
                        )
                except TimeoutError as e:
                    logger.error(f"⏱️  TIMEOUT: Translation exceeded {timeout_seconds}s limit: {e}")
                    self._write_heartbeat("timeout_detected")
                    emit_worker_event(
                        agent_name="content_worker",
                        job_type="worker_timeout",
                        status="failure",
                        error_summary=str(e)[:500],
                        metrics={"timeout_seconds": timeout_seconds,
                                 "content_root": str(content_root),
                                 "target_langs": target_langs},
                    )
                    raise

                logger.info(
                    "Chunk %d: %d/%d files succeeded, %d failed",
                    chunk_idx, result.successful_files, result.total_files, result.failed_files,
                )

                # WS-COMP-8: Accumulate coverage counters across chunks
                _cov_total_needing_work += result.total_files
                _cov_successful += result.successful_files
                _cov_skipped += getattr(result, "completion_filter_skipped", 0)

                # Log rejection rate for validation monitoring
                try:
                    agg = result.aggregate_stats
                    rejected = getattr(agg, 'rejected_count', 0) or 0
                    if rejected > 0 and result.total_files > 0:
                        rej_rate = rejected / result.total_files * 100
                        logger.info("Chunk %d rejection rate: %d/%d (%.1f%%)",
                                    chunk_idx, rejected, result.total_files, rej_rate)
                        if rej_rate > 10:
                            logger.warning("High rejection rate %.1f%% in chunk %d — check validation config",
                                           rej_rate, chunk_idx)
                except (AttributeError, TypeError):
                    pass  # Gracefully handle incomplete result objects

                # BUG-2 FIX: Accumulate successful file count for run-level health tracking
                _site_files = getattr(self, "_run_new_files", {})
                _site_files[site_id] = _site_files.get(site_id, 0) + result.successful_files
                self._run_new_files = _site_files

                if result.successful_files > 0:
                    success = auto_commit_translations(
                        result=result,
                        site_id=site_id,
                        target_langs=target_langs,
                        run_id=run_id,
                        config_service=self.config_service,
                    )
                    if success:
                        logger.info("Chunk %d committed", chunk_idx)
                    else:
                        logger.error("Chunk %d commit failed", chunk_idx)

                chunk_idx += 1
                skip_first += result.total_files

                # Zero-progress guard: break if chunk produced nothing useful
                if result.successful_files == 0 and result.failed_files == 0:
                    logger.warning("Chunk %d: zero progress (0 successful, 0 failed) — breaking loop", chunk_idx)
                    break

                # Exit when the slice was smaller than the chunk size (last slice)
                if result.total_files < files_per_commit:
                    break

        else:
            # Legacy single-pass mode
            run_id = f"{self.invocation_id}:{site_id}:{Path(content_root).name}"
            try:
                with timeout_guard(timeout_seconds, operation_name):
                    result = self.translation_engine.translate_directory(
                        site_id=site_id,
                        directory=resolved_content_dir,
                        target_langs=target_langs,
                        recursive=True,
                        parallel=True,
                        trigger_type="scheduled",
                        max_files=0,
                        run_deadline=run_deadline,
                    )
            except TimeoutError as e:
                logger.error(f"⏱️  TIMEOUT: Translation exceeded {timeout_seconds}s limit: {e}")
                self._write_heartbeat("timeout_detected")
                emit_worker_event(
                    agent_name="content_worker",
                    job_type="worker_timeout",
                    status="failure",
                    error_summary=str(e)[:500],
                    metrics={"timeout_seconds": timeout_seconds,
                             "content_root": str(content_root),
                             "target_langs": target_langs},
                )
                raise

            logger.info(
                f"Translation completed: "
                f"{result.successful_files}/{result.total_files} files succeeded, "
                f"{result.failed_files} failed"
            )

            # WS-COMP-8: Accumulate coverage counters (single-pass mode)
            _cov_total_needing_work += result.total_files
            _cov_successful += result.successful_files
            _cov_skipped += getattr(result, "completion_filter_skipped", 0)

            # Log rejection rate for validation monitoring
            try:
                agg = result.aggregate_stats
                rejected = getattr(agg, 'rejected_count', 0) or 0
                if rejected > 0 and result.total_files > 0:
                    rej_rate = rejected / result.total_files * 100
                    logger.info("Rejection rate: %d/%d (%.1f%%)",
                                rejected, result.total_files, rej_rate)
                    if rej_rate > 10:
                        logger.warning("High rejection rate %.1f%% — check validation config", rej_rate)
            except (AttributeError, TypeError):
                pass  # Gracefully handle incomplete result objects

            # BUG-2 FIX: Accumulate successful file count for run-level health tracking
            _site_files = getattr(self, "_run_new_files", {})
            _site_files[site_id] = _site_files.get(site_id, 0) + result.successful_files
            self._run_new_files = _site_files

            # LLM-WASTE-FIX-1: Skip commit when ALL file results have every language skipped
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

            if result.successful_files > 0 and _has_new_translations:
                success = auto_commit_translations(
                    result=result,
                    site_id=site_id,
                    target_langs=target_langs,
                    run_id=run_id,
                    config_service=self.config_service,
                )
                if success:
                    logger.info("Git commit successful")
                else:
                    logger.error("Git commit FAILED or was SKIPPED - check logs above for details")
            else:
                logger.info("No successful translations, skipping git commit")

        # TC-14: Post-run contamination scan — catches files that slipped through validation.
        self._run_post_contamination_scan(site_id=site_id, content_root=resolved_content_dir)

        # TC-16: Write per-run quality metrics summary to data/metrics/.
        self._write_run_metrics(site_id=site_id, run_id=run_id)

        # WS-COMP-8: Emit structured coverage telemetry for this content root.
        # Runs after both chunked and single-pass modes so the snapshot always fires.
        try:
            from src.observability.metrics import record_coverage_snapshot
            record_coverage_snapshot(
                site_id=site_id,
                target_langs=target_langs,
                total_files=_cov_total_needing_work,
                successful_files=_cov_successful,
                completion_filter_skipped=_cov_skipped,
            )
        except Exception as _cov_exc:
            logger.debug("Coverage snapshot skipped: %s", _cov_exc)

        try:
            emit_worker_event(
                agent_name="content_worker",
                job_type="worker_coverage_metrics",
                items_discovered=_cov_total_needing_work + _cov_skipped,
                items_succeeded=_cov_successful,
                metrics={
                    "site_id": site_id,
                    "content_root": str(content_root),
                    "target_langs": target_langs,
                    "total_needing_work": _cov_total_needing_work,
                    "successful": _cov_successful,
                    "completion_filter_skipped": _cov_skipped,
                },
            )
        except Exception as _ev_exc:
            logger.debug("Coverage event skipped: %s", _ev_exc)

    def _write_run_metrics(self, site_id: str, run_id: str) -> None:
        """
        TC-16: Write a per-run quality metrics summary to data/metrics/run_<timestamp>.json.

        Collects MetricsCollector stats, retranslate queue size, files translated,
        and per-language breakdown.  Wrapped in try/except — must never block the worker.
        """
        try:
            raw_config = self.config_service.get_config() if self.config_service is not None else {}
            metrics_cfg = raw_config.get("metrics", {})
            if not metrics_cfg.get("enabled", True):
                return
            if not metrics_cfg.get("write_per_run_summary", True):
                return

            import json as _json

            from src.observability.metrics import get_metrics
            from src.tm.retranslate_queue import load_queued_paths

            mc = get_metrics()
            stats = mc.get_stats_summary()

            # Retranslate queue size
            try:
                retranslate_queue_size = len(load_queued_paths())
            except Exception:
                retranslate_queue_size = -1

            # Per-language files translated (from _run_new_files dict)
            per_language_stats = dict(getattr(self, "_run_new_files", {}))

            from datetime import timezone as _tz
            _now = datetime.now(_tz.utc)
            run_summary = {
                "run_id": run_id,
                "site_id": site_id,
                "timestamp": _now.isoformat(),
                "files_translated": sum(per_language_stats.values()),
                "per_language_stats": per_language_stats,
                "validation_failures": int(
                    stats.get("translations", {}).get("failed", 0)
                ),
                "tm_hit_rates": stats.get("tm", {}),
                "retranslate_queue_size": retranslate_queue_size,
                "translations": stats.get("translations", {}),
                "performance": stats.get("performance", {}),
            }

            output_dir = Path(metrics_cfg.get("output_dir", "data/metrics"))
            output_dir.mkdir(parents=True, exist_ok=True)
            ts = _now.strftime("%Y%m%dT%H%M%SZ")
            run_file = output_dir / f"run_{ts}_{site_id}.json"
            # Use a thread with timeout to guard against OneDrive-sync file write hangs
            # (Windows OneDrive can block write_text() indefinitely on synced paths).
            import concurrent.futures as _cf
            _content = _json.dumps(run_summary, indent=2, ensure_ascii=False)
            with _cf.ThreadPoolExecutor(max_workers=1) as _ex:
                _fut = _ex.submit(run_file.write_text, _content, "utf-8")
                try:
                    _fut.result(timeout=10)
                    logger.info("TC-16: Run metrics written to %s", run_file)
                except _cf.TimeoutError:
                    logger.warning("TC-16: Run metrics write timed out (OneDrive sync?) — skipping")
        except Exception as _e:
            logger.warning("TC-16: Failed to write run metrics (non-fatal): %s", _e)

    def _run_post_contamination_scan(self, site_id: str, content_root: Path) -> None:
        """
        TC-14: Run full (non-fast) contamination scan on the just-translated content root.

        Invokes scripts/scan_language_contamination.py WITHOUT --fast so langdetect
        sentence analysis detects same-script contamination (e.g. English in Spanish/French).
        Scoped to --repo <content_root> (not all profiles) to keep runtime bounded.
        Parses the JSON output and adds contaminated files to the retranslate queue.

        Wrapped in try/except — must never block the worker on failure.
        TC-MLD-05: Removed --fast flag (was blind to same-script contamination, RC-2).
        Timeout raised to 600 s (full langdetect scan needs more than 180 s for large sites).
        """
        import subprocess
        import sys
        import tempfile
        import time as _time

        # TC-06: Skip scan if run deadline has already passed
        run_deadline = getattr(self, "_run_deadline", None)
        if run_deadline is not None and _time.time() >= run_deadline:
            logger.info("TC-06: run deadline exceeded — skipping contamination scan")
            return

        raw_config = self.config_service.get_config() if self.config_service is not None else {}
        if not raw_config.get("auto_scan_contamination", True):
            return

        if not content_root.exists():
            logger.debug("TC-14: content_root %s not found — skipping post-run scan", content_root)
            return

        script = Path(__file__).parents[2] / "scripts" / "scan_language_contamination.py"
        if not script.exists():
            logger.warning("TC-14: scan_language_contamination.py not found — skipping post-run scan")
            return

        try:
            with tempfile.NamedTemporaryFile(
                prefix=f"scan_{site_id}_",
                suffix=".json",
                delete=False,
            ) as tmp:
                json_output_path = tmp.name

            cmd = [
                sys.executable,
                str(script),
                # TC-MLD-05: --fast removed — full langdetect scan detects same-script
                # contamination (English in Spanish/French/German, etc.) that --fast misses.
                "--all-languages",
                "--repo", str(content_root),
                "--workers", "16",
                "--json-output", json_output_path,
            ]

            logger.info("TC-14: Running post-run contamination scan for site %s ...", site_id)
            # TC-06: Use CREATE_NEW_PROCESS_GROUP on Windows so the subprocess tree
            # can be killed cleanly on timeout instead of leaving orphan python processes.
            creation_flags = 0
            if sys.platform == "win32":
                creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,  # TC-MLD-05: raised from 180 — full langdetect scan needs more time
                creationflags=creation_flags,
            )

            # Parse JSON output and queue contaminated files
            try:
                json_path = Path(json_output_path)
                if json_path.exists() and json_path.stat().st_size > 0:
                    import json as _json
                    data = _json.loads(json_path.read_text(encoding="utf-8"))
                    contaminated_files = data.get("files", [])
                    queued = 0
                    from src.tm.retranslate_queue import add_to_queue
                    for entry in contaminated_files:
                        file_path = entry.get("file_path")
                        target_lang = entry.get("target_lang")
                        if file_path and target_lang:
                            try:
                                add_to_queue(Path(file_path), target_lang)
                                queued += 1
                            except Exception as _qe:
                                logger.debug("TC-14: failed to queue %s: %s", file_path, _qe)
                    contaminated_count = data.get("contaminated_count", 0)
                    logger.info(
                        "TC-14: Post-run contamination scan complete — %d contaminated, %d queued for retranslation",
                        contaminated_count,
                        queued,
                    )
                else:
                    logger.info("TC-14: Post-run contamination scan complete — no JSON output (no issues found)")
            except Exception as _parse_err:
                logger.warning("TC-14: Failed to parse scan JSON output: %s", _parse_err)
            finally:
                try:
                    Path(json_output_path).unlink(missing_ok=True)
                except Exception:
                    pass

            if result.returncode not in (0, 1):
                # exit code 1 = quality issues found (normal); other codes = errors
                logger.warning("TC-14: Contamination scan exited with code %d: %s", result.returncode, result.stderr.strip()[:200])

        except subprocess.TimeoutExpired:
            logger.warning("TC-14: Post-run contamination scan timed out after 180s — skipping")
        except Exception as _e:
            logger.warning("TC-14: Post-run contamination scan failed (non-fatal): %s", _e)

    def _offload_models(self) -> None:
        """Unload translation model weights and free VRAM between daemon runs."""
        if self.translation_engine is None:
            return
        model_loader = getattr(self.translation_engine, "model_loader", None)
        if model_loader is None:
            return
        loaded_models = getattr(model_loader, "loaded_models", {})
        if not loaded_models:
            return
        model_loader.unload_all()
        import gc
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            logger.debug("[VRAM] torch not available — skipping CUDA cache clear")

        # TC-L3-007: Offload L3 encoder to CPU (mirrors TM worker pattern)
        try:
            l3 = getattr(getattr(self.translation_engine, "tm", None), "l3", None)
            if l3 is not None and hasattr(l3, "offload_to_cpu"):
                l3.offload_to_cpu()
                logger.debug("[VRAM] L3 encoder offloaded to CPU")
        except Exception as e:
            logger.debug("[VRAM] L3 offload skipped: %s", e)

    @staticmethod
    def _build_orphan_commit_message(
        files: list[Path],
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
            logger.error(
                "[orphan_gate] git show FAILED for %s: %s — REJECTING (fail-safe; "
                "fix git access before re-enabling orphan recovery)",
                source_rel_posix, e,
            )
            return False  # fail-safe: unknown state is treated as corrupted

        # --- Read orphan from disk ---
        try:
            orphan_text = orphan_path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            logger.error(
                "[orphan_gate] Cannot read orphan %s: %s — REJECTING (fail-safe)",
                orphan_path.name, e,
            )
            return False  # fail-safe

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
        from src.observability.git_commit_helper import recover_orphaned_commit_manifests
        from src.observability.legacy_backlog_recovery import recover_legacy_translation_backlog

        # Respect global git_commit.enabled flag — if disabled, skip all orphan recovery.
        try:
            gc_cfg = self.config_service.global_config.git_commit
            if isinstance(gc_cfg, dict):
                enabled = gc_cfg.get("enabled", True)
            else:
                enabled = getattr(gc_cfg, "enabled", True)
            if not enabled:
                logger.debug("[orphan_sweep] git_commit disabled — skipping orphan recovery")
                return 0
        except Exception:
            pass  # If config is unavailable, proceed with recovery

        try:
            git_roots = self._iter_recovery_git_roots()
        except Exception as exc:
            logger.warning(f"[orphan_sweep] Could not discover git roots: {exc}")
            return 0

        total_recovered = 0
        for git_root in git_roots:
            try:
                recovered = recover_orphaned_commit_manifests(git_root)
                if recovered:
                    logger.info(
                        f"[orphan_sweep] Recovered {recovered} manifest-backed commit(s) in {git_root}"
                    )
                total_recovered += recovered

                legacy_report = recover_legacy_translation_backlog(
                    repo=git_root,
                    config_service=self.config_service,
                    validate_fn=self._validate_orphan_structural_integrity,
                    build_message_fn=self._build_orphan_commit_message,
                    site_ids=self._site_ids_for_git_root(git_root),
                    apply=True,
                )
                legacy_commits = sum(1 for item in legacy_report.commits if item.commit_hash)
                if legacy_commits:
                    logger.info(
                        f"[orphan_sweep] Recovered {legacy_commits} legacy backlog commit(s) in {git_root}"
                    )
                total_recovered += legacy_commits
            except Exception as exc:
                logger.warning(f"[orphan_sweep] {git_root}: {exc}")

        return total_recovered

    def _recover_pending_commits(self) -> None:
        """Retry any .pending_commit.json / .pending_commit.json.stale_* files left
        behind by a previous failed commit attempt (e.g. git commit timeout).

        Discovers the git root for every configured content root, then delegates to
        recover_pending_commits() which handles staging and committing.
        """
        from src.observability.git_commit_helper import (
            recover_orphaned_commit_manifests,
            recover_pending_commits,
        )
        try:
            git_roots = self._iter_recovery_git_roots()
        except Exception as exc:
            logger.warning(f"[pending_commit_recovery] Could not discover git roots: {exc}")
            return

        for git_root in git_roots:
            try:
                manifest_recovered = recover_orphaned_commit_manifests(
                    git_root,
                    stale_ready_seconds=0,
                )
                if manifest_recovered > 0:
                    logger.info(
                        f"[pending_commit_recovery] Recovered {manifest_recovered} manifest commit(s) in {git_root}"
                    )
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

    # TC-SYS-02: Use RotatingFileHandler to prevent log files from growing unbounded.
    try:
        from src.utils.config_loader import get_global_config as _gcfg
        _log_cfg = _gcfg().get('logging', {})
    except Exception:
        _log_cfg = {}
    _max_bytes = int(_log_cfg.get('max_log_size_mb', 50)) * 1024 * 1024
    _backup_count = int(_log_cfg.get('max_log_backups', 3))
    from logging.handlers import RotatingFileHandler as _RFH
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(),
            _RFH(log_path, maxBytes=_max_bytes, backupCount=_backup_count, delay=True, encoding="utf-8"),
        ],
        force=True,
    )

    # Ensure logs are flushed on any exit path (normal, exception, signal)
    import atexit
    atexit.register(logging.shutdown)

    # TC-REEXEC-09 / RISK-09: Route structlog through stdlib logging so Windows
    # pipe errors (OSError [Errno 22]) are swallowed by stdlib Handler.emit()
    # instead of aborting translation. Without this, structlog's default
    # PrintLoggerFactory calls print(msg, file=sys.stdout) directly, which
    # crashes on restricted pipes (Task Scheduler, redirected stdout).
    import structlog as _structlog
    _structlog.configure(
        processors=[
            _structlog.stdlib.filter_by_level,
            _structlog.stdlib.add_logger_name,
            _structlog.stdlib.add_log_level,
            _structlog.stdlib.PositionalArgumentsFormatter(),
            _structlog.processors.TimeStamper(fmt="iso"),
            _structlog.processors.StackInfoRenderer(),
            _structlog.processors.format_exc_info,
            _structlog.processors.UnicodeDecoder(),
            _structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=_structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=_structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
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
        logging.shutdown()
        sys.exit(0)

    for sig in [signal.SIGINT, signal.SIGTERM]:
        signal.signal(sig, _shutdown_handler)
    if platform.system() == "Windows" and hasattr(signal, 'SIGBREAK'):
        signal.signal(signal.SIGBREAK, _shutdown_handler)

    try:
        worker.run()
    except SystemExit:
        raise  # Let sys.exit() propagate normally
    except Exception:
        logger.exception("Worker crashed with unhandled exception")
        sys.exit(1)
    finally:
        logging.shutdown()


if __name__ == "__main__":
    main()
