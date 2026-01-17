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
import logging
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from src.hardware.vram_enforcer import VRAMEnforcer
from src.observability.git_commit_helper import auto_commit_translations
from src.translation_engine.engine import TranslationEngine
from src.utils.config_loader import ConfigService
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
            global_config = self.config_service.global_config
            tm = TranslationMemory(global_config.translation_memory)
            logger.info("Initialized TranslationMemory")
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

    def run(self) -> None:
        """
        Run autonomous worker.

        In oneshot mode: Executes one translation run and exits
        In daemon mode: Continuously schedules and executes runs
        """
        if self.config.mode == "oneshot":
            self._run_oneshot()
        elif self.config.mode == "daemon":
            self._run_daemon()
        else:
            raise ValueError(f"Invalid mode: {self.config.mode}. Expected 'oneshot' or 'daemon'")

    def _run_oneshot(self) -> None:
        """Execute a single translation run and exit."""
        logger.info("=" * 80)
        logger.info("ONESHOT MODE: Running single translation pass")
        logger.info("=" * 80)

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

        try:
            while True:
                # Sleep until next run time
                next_run = self.scheduler.sleep_until_next_run()
                run_count += 1

                logger.info("=" * 80)
                logger.info(f"SCHEDULED RUN #{run_count} at {next_run.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                logger.info("=" * 80)

                try:
                    self._execute_translation_run()
                    logger.info(f"Scheduled run #{run_count} completed successfully")
                except Exception as e:
                    logger.error(f"Scheduled run #{run_count} failed: {e}", exc_info=True)
                    # Continue to next run despite failure

        except KeyboardInterrupt:
            logger.info("Daemon interrupted by user (Ctrl+C)")
        except Exception as e:
            logger.error(f"Daemon failed: {e}", exc_info=True)
            sys.exit(1)

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

            # Generate run_id for this specific translation (includes invocation_id + site + content_root)
            run_id = f"{self.invocation_id}:{site_id}:{Path(content_root).name}"

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
                logger.warning("Git commit failed or was skipped")
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
    worker.setup()
    worker.run()


if __name__ == "__main__":
    main()
