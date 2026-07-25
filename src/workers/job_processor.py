"""
Job Processor for Translation Worker.

Polls Redis queue for translation jobs and processes them.
"""

import logging
import os
import signal
import sys
import time
import warnings
from pathlib import Path
from typing import Optional

from src.model_runtime import HardwareDetector, ModelLoader, ModelRegistry
from src.orchestrator.models import JobStatus, TranslationJob
from src.orchestrator.redis_backend import RedisJobQueue
from src.tm import TranslationMemory
from src.tm.l1_cache import L1Cache
from src.tm.l2_persistent import L2PersistentTM
from src.tm.l3_semantic import L3SemanticTM
from src.translation_engine.engine import TranslationEngine
from src.utils.config_loader import ConfigService

logger = logging.getLogger(__name__)


class JobProcessor:
    """
    Job processor that polls Redis queue and processes translation jobs.

    Runs in a loop, dequeuing jobs from Redis, processing them,
    and updating their status.
    """

    def __init__(
        self,
        redis_host: str = "localhost",
        redis_port: int = 6379,
        redis_db: int = 0,
        redis_password: str | None = None,
        poll_interval: float = 5.0,
        max_retries: int = 3,
        config_path: str = "./config",
        tm_path: str = "./data/tm",
        engines: Optional["SharedEngines"] = None,  # NEW: SharedEngines support
    ):
        """
        Initialize job processor.

        Args:
            redis_host: Redis host (ignored if engines provided)
            redis_port: Redis port (ignored if engines provided)
            redis_db: Redis database number (ignored if engines provided)
            redis_password: Optional Redis password (ignored if engines provided)
            poll_interval: Seconds between queue polls
            max_retries: Maximum job retry attempts (overridden by engines.healing if provided)
            config_path: Configuration directory path (ignored if engines provided)
            tm_path: Translation memory storage path
            engines: SharedEngines container (NEW - Phase 5.1 migration)
                    If provided, uses shared engines instead of direct instantiation.
                    Enables unified telemetry, logging, and configuration.
        """
        # PHASE 5.1: Detect if using SharedEngines or legacy mode
        self._using_shared_engines = engines is not None
        self.engines = engines

        if not self._using_shared_engines:
            # Legacy mode: Direct instantiation (DEPRECATED)
            warnings.warn(
                "Instantiating JobProcessor without SharedEngines is deprecated. "
                "Use CompositionRoot.create_from_config() and pass engines parameter. "
                "Legacy mode will be removed in a future release.",
                DeprecationWarning,
                stacklevel=2
            )
            logger.warning(
                "JobProcessor running in LEGACY mode (direct instantiation). "
                "Consider migrating to SharedEngines for unified telemetry and configuration."
            )

        self.redis_host = redis_host
        self.redis_port = redis_port
        self.redis_db = redis_db
        self.redis_password = redis_password
        self.poll_interval = poll_interval
        self.max_retries = max_retries
        self.config_path = config_path
        self.tm_path = tm_path

        # Initialize components (will be set in setup())
        self.queue: RedisJobQueue | None = None
        self.tm: TranslationMemory | None = None
        self.model_loader: ModelLoader | None = None
        self.engine: TranslationEngine | None = None
        self.config_service: ConfigService | None = None

        # Control flags
        self._running = False
        self._shutdown_requested = False

        # Statistics
        self.jobs_processed = 0
        self.jobs_succeeded = 0
        self.jobs_failed = 0

    def setup(self) -> None:
        """Setup processor components."""
        logger.info("Setting up job processor...")

        # PHASE 5.1: Use SharedEngines if available, otherwise legacy instantiation
        if self._using_shared_engines:
            logger.info("Using SharedEngines (Phase 5.1 migration)")

            # Use job queue from SharedEngines
            self.queue = self.engines.job.queue
            logger.info(f"Using shared job queue: {self.queue.__class__.__name__}")

            # Use configuration from SharedEngines
            self.config_service = self.engines.profile.config_service
            logger.info(f"Using shared configuration from {self.engines.profile.config_root}")

            # Emit telemetry event for worker startup
            try:
                self.engines.telemetry.track_event(
                    event_type="worker_started",
                    worker_id=os.getenv("WORKER_ID", "worker-unknown"),
                    mode="shared_engines"
                )
            except Exception as e:
                logger.debug(f"Telemetry event failed (non-fatal): {e}")

        else:
            # LEGACY MODE: Direct instantiation
            # Initialize Redis queue
            self.queue = RedisJobQueue(
                host=self.redis_host,
                port=self.redis_port,
                db=self.redis_db,
                password=self.redis_password if self.redis_password else None,
            )
            logger.info(f"Connected to Redis queue at {self.redis_host}:{self.redis_port}")

            # Initialize configuration service
            self.config_service = ConfigService(config_root=self.config_path)
            logger.info(f"Loaded configuration from {self.config_path}")

        # Initialize translation memory layers
        l1_cache = L1Cache(max_size=10000)  # Per-worker cache

        # Setup L2 persistent TM path
        from src.tm.l2_persistent import L2_DB_NAME
        _l2_cfg = self.config_service.get_config() if self.config_service else {}
        _l2_max_mb = _l2_cfg.get("tm_defaults", {}).get("l2_max_size_mb", 1536)
        l2_path = Path(self.tm_path) / L2_DB_NAME
        l2_path.mkdir(parents=True, exist_ok=True)
        l2_persistent = L2PersistentTM(str(l2_path), max_size_mb=_l2_max_mb)

        # Setup L3 semantic TM (optional)
        l3_path = Path(self.tm_path) / "l3_faiss"
        l3_path.mkdir(parents=True, exist_ok=True)
        l3_semantic = L3SemanticTM(
            index_path=str(l3_path),
            embedding_model="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
            use_gpu=True,  # TC-L3-002: GPU encode; CPU fallback built-in
        )

        self.tm = TranslationMemory(
            l1_cache=l1_cache,
            l2_persistent=l2_persistent,
            l3_semantic=l3_semantic,
        )
        logger.info("Translation memory initialized")

        # Detect hardware and initialize model runtime
        detector = HardwareDetector()
        hardware = detector.detect()
        logger.info(
            f"Hardware detected: {len(hardware.cuda_devices)} GPUs, {hardware.cpu_count} CPUs"
        )

        # Get max_gpu_memory_mb from config (computed by LimitingEngine if using SharedEngines)
        # For legacy mode, compute it from hardware config
        max_memory_mb = None
        if self._using_shared_engines:
            # SharedEngines: Get from LimitingEngine (already computed from percent if needed)
            max_memory_mb = self.engines.limiting.limits.max_gpu_memory_mb
            logger.info(
                f"Using max_memory_mb from SharedEngines LimitingEngine: {max_memory_mb}MB"
            )
        else:
            # Legacy mode: Compute from global config
            try:
                global_config = self.config_service.get_global_config()
                hardware_config = global_config.get("hardware", {})

                # Use VRAM budget resolution logic
                import torch

                from src.hardware.vram_budget import resolve_vram_budget_mb

                if hardware.recommended_device.startswith("cuda") and torch.cuda.is_available():
                    device_id = 0
                    if ":" in hardware.recommended_device:
                        device_id = int(hardware.recommended_device.split(":")[1])

                    props = torch.cuda.get_device_properties(device_id)
                    total_mb = props.total_memory / (1024**2)

                    max_gpu_memory_percent = hardware_config.get("max_gpu_memory_percent")
                    max_gpu_memory_mb_config = hardware_config.get("max_gpu_memory_mb")

                    budget_mb, budget = resolve_vram_budget_mb(
                        total_mb=total_mb,
                        max_gpu_memory_percent=max_gpu_memory_percent,
                        max_gpu_memory_mb=max_gpu_memory_mb_config,
                    )

                    max_memory_mb = budget_mb
                    logger.info(
                        f"Computed max_memory_mb from hardware config: {max_memory_mb}MB "
                        f"({budget.percent:.1f}% of {total_mb:.0f}MB, source: {budget.source})"
                    )
            except Exception as e:
                logger.warning(f"Failed to compute max_memory_mb from config: {e}")

        registry = ModelRegistry(registry_path="config/model_registry.yaml")
        raw_config = self.config_service.get_config()
        self.model_loader = ModelLoader(
            registry=registry,
            device=hardware.recommended_device,
            max_memory_mb=max_memory_mb,  # Pass computed budget to ModelLoader
            config=raw_config,
        )
        logger.info(f"Model runtime initialized (max_memory_mb: {max_memory_mb}MB)")

        # Get Redis client for distributed locking (CHH-02)
        redis_client = None
        try:
            redis_client = self.queue.backend._get_redis()
            logger.info("Redis client configured for metadata locking")
        except Exception as e:
            logger.warning(f"Redis client unavailable for metadata locking: {e}")

        # Initialize translation engine
        self.engine = TranslationEngine(
            config_service=self.config_service,
            tm=self.tm,
            model_loader=self.model_loader,
            redis_client=redis_client,  # CHH-02: Pass Redis client for metadata coordination
        )
        logger.info("Translation engine initialized")

        logger.info("Job processor setup complete")

    def shutdown(self) -> None:
        """Graceful shutdown."""
        logger.info("Shutting down job processor...")
        self._shutdown_requested = True

        # Close queue connection
        if self.queue:
            try:
                self.queue.close()
                logger.info("Redis connection closed")
            except Exception as e:
                logger.error(f"Error closing Redis connection: {e}")

        # Cleanup engine
        if self.engine:
            try:
                # Engine cleanup if needed
                pass
            except Exception as e:
                logger.error(f"Error cleaning up engine: {e}")

        logger.info(
            f"Job processor shutdown complete. "
            f"Stats: processed={self.jobs_processed}, "
            f"succeeded={self.jobs_succeeded}, "
            f"failed={self.jobs_failed}"
        )

    def _setup_signal_handlers(self) -> None:
        """Setup signal handlers for graceful shutdown."""

        def signal_handler(signum, frame):
            sig_name = signal.Signals(signum).name
            logger.info(f"Received signal {sig_name}, initiating shutdown...")
            self.shutdown()
            sys.exit(0)

        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
        logger.info("Signal handlers registered (SIGTERM, SIGINT)")

    def process_job(self, job: TranslationJob) -> bool:
        """
        Process a single translation job.

        Args:
            job: TranslationJob to process

        Returns:
            True if successful, False if failed
        """
        logger.info(
            f"Processing job {job.job_id} "
            f"(type={job.job_type.value}, site={job.site_id})"
        )

        try:
            # Get job parameters
            site_id = job.site_id
            input_paths = job.input_paths
            target_langs = job.target_langs

            # Get site profile
            site_profile = self.config_service.get_site_profile(site_id)

            # Re-validate the job's (potentially stale) target_langs snapshot
            # against the live site profile before executing. A job created
            # before a locale was retired from a site's profile must not
            # resurrect it just because it was already queued.
            if site_profile:
                stale_langs = [
                    lang for lang in target_langs if lang not in site_profile.target_langs
                ]
                if stale_langs:
                    logger.warning(
                        f"Job {job.job_id}: dropping locale(s) {stale_langs} — no "
                        f"longer present in the live '{site_id}' site profile"
                    )
                target_langs = [
                    lang for lang in target_langs if lang in site_profile.target_langs
                ]

            # Process all input files
            files_processed = 0
            files_failed = 0

            for source_file in input_paths:
                try:
                    # Translate file
                    result = self.engine.translate_file(
                        site_profile=site_profile,
                        source_file=source_file,
                        target_langs=target_langs,
                    )

                    # Check result
                    if result.get("status") == "success":
                        files_processed += 1
                        logger.info(
                            f"Translated {source_file} to {len(target_langs)} languages"
                        )
                    else:
                        files_failed += 1
                        error_msg = result.get("error", "Unknown error")
                        logger.error(f"Translation failed for {source_file}: {error_msg}")
                except Exception as file_error:
                    files_failed += 1
                    logger.error(
                        f"Error translating {source_file}: {file_error}",
                        exc_info=True,
                    )

            # Determine overall job status
            if files_failed == 0:
                logger.info(
                    f"Job {job.job_id} completed successfully. "
                    f"Processed {files_processed} files, translated to {len(target_langs)} languages"
                )

                # Update job status
                self.queue.update_job_status(
                    job_id=job.job_id,
                    status=JobStatus.COMPLETED,
                    result_summary={
                        "target_langs": target_langs,
                        "files_processed": files_processed,
                        "files_failed": files_failed,
                    },
                )

                self.jobs_succeeded += 1
                return True
            else:
                error_msg = f"{files_failed}/{len(input_paths)} files failed"
                logger.error(f"Job {job.job_id} partially failed: {error_msg}")

                # Update job status
                self.queue.update_job_status(
                    job_id=job.job_id,
                    status=JobStatus.FAILED if files_processed == 0 else JobStatus.COMPLETED,
                    error_message=error_msg,
                    result_summary={
                        "target_langs": target_langs,
                        "files_processed": files_processed,
                        "files_failed": files_failed,
                    },
                )

                self.jobs_failed += 1
                return False

        except Exception as e:
            logger.error(f"Error processing job {job.job_id}: {e}", exc_info=True)

            # Update job status
            try:
                self.queue.update_job_status(
                    job_id=job.job_id,
                    status=JobStatus.FAILED,
                    error_message=str(e),
                )
            except Exception as update_error:
                logger.error(
                    f"Failed to update job status for {job.job_id}: {update_error}"
                )

            self.jobs_failed += 1
            return False

    def run(self) -> None:
        """
        Main processing loop.

        Polls Redis queue, dequeues jobs, and processes them.
        """
        # Setup
        self.setup()
        self._setup_signal_handlers()

        logger.info("=" * 70)
        logger.info("Job Processor Starting")
        logger.info("=" * 70)
        logger.info(f"Redis: {self.redis_host}:{self.redis_port}")
        logger.info(f"Poll interval: {self.poll_interval}s")
        logger.info(f"Max retries: {self.max_retries}")
        logger.info(f"Config path: {self.config_path}")
        logger.info("=" * 70)

        self._running = True

        # Main processing loop
        while self._running and not self._shutdown_requested:
            try:
                # Dequeue job from Redis
                job = self.queue.dequeue()

                if job:
                    # Process job
                    self.jobs_processed += 1
                    self.process_job(job)
                else:
                    # No jobs available, wait before polling again
                    time.sleep(self.poll_interval)

            except KeyboardInterrupt:
                logger.info("Keyboard interrupt received, shutting down...")
                break
            except Exception as e:
                logger.error(f"Error in processing loop: {e}", exc_info=True)
                time.sleep(self.poll_interval)

        # Shutdown
        if not self._shutdown_requested:
            self.shutdown()


def main() -> int:
    """Main entry point for job processor."""
    # Configure logging
    log_level = os.getenv("LOG_LEVEL", "INFO")
    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stdout,
    )

    # PHASE 2 (AW-03): Check for execution mode (dual-run support)
    execution_mode_env = os.getenv("EXECUTION_MODE")
    use_worker_runner = execution_mode_env is not None

    if use_worker_runner:
        logger.info(f"Using WorkerRunner with execution mode: {execution_mode_env}")
        from src.workers.runner import WorkerConfig

        # Load configuration with execution mode support
        config_path = os.getenv("CONFIG_PATH", "./config")

        # PHASE 2: Load mode defaults from global.yaml
        from src.shared_engines.composition_root import CompositionRoot
        mode_defaults = CompositionRoot._load_execution_mode_config(config_path)

        # Create WorkerConfig with 3-tier precedence
        worker_config = WorkerConfig.from_env(mode_defaults)

        # PHASE 5.1 + PHASE 2: Always use SharedEngines when using WorkerRunner
        logger.info("Creating SharedEngines for WorkerRunner")
        try:
            # Build engines config from worker config
            engines_config = {
                "config_root": worker_config.config_path,
                "log_level": worker_config.log_level,
                "telemetry_enabled": True,
                "job_backend": "redis",
                "redis_host": worker_config.redis_host,
                "redis_port": worker_config.redis_port,
                "commit_enabled": os.getenv("COMMIT_ENABLED", "true").lower() in ("true", "1", "yes"),
                "max_retries": worker_config.max_retries,
                "device": worker_config.device,  # PHASE 2: Device from execution mode
            }

            shared_engines = CompositionRoot.create_from_config(engines_config)
            logger.info("SharedEngines created successfully")

            # Emit telemetry event for worker startup with execution mode
            try:
                shared_engines.telemetry.track_event(
                    event_type="worker_started_with_execution_mode",
                    worker_id=worker_config.worker_id,
                    execution_mode=worker_config.execution_mode.value,
                    device=worker_config.device,
                    mode="worker_runner"
                )
            except Exception as e:
                logger.debug(f"Telemetry event failed (non-fatal): {e}")

            # Create and run processor with SharedEngines
            processor = JobProcessor(
                redis_host=worker_config.redis_host,
                redis_port=worker_config.redis_port,
                redis_db=worker_config.redis_db,
                redis_password=worker_config.redis_password,
                poll_interval=worker_config.poll_interval,
                max_retries=worker_config.max_retries,
                config_path=worker_config.config_path,
                tm_path=worker_config.tm_path,
                engines=shared_engines,
            )

            try:
                processor.run()
                return 0
            except Exception as e:
                logger.error(f"Job processor failed: {e}", exc_info=True)
                return 1

        except Exception as e:
            logger.error(f"Failed to create WorkerRunner components: {e}", exc_info=True)
            return 1

    else:
        # LEGACY MODE: No EXECUTION_MODE env var
        from src.workers.runner import warn_legacy_mode
        warn_legacy_mode()

        # Get configuration from environment (legacy)
        redis_host = os.getenv("REDIS_HOST", "localhost")
        redis_port = int(os.getenv("REDIS_PORT", "6379"))
        redis_db = int(os.getenv("REDIS_DB", "0"))
        redis_password = os.getenv("REDIS_PASSWORD")
        poll_interval = float(os.getenv("POLL_INTERVAL", "5.0"))
        max_retries = int(os.getenv("MAX_RETRIES", "3"))
        config_path = os.getenv("CONFIG_PATH", "./config")
        tm_path = os.getenv("TM_DATA_PATH", "./data/tm")

        # PHASE 5.1: Optionally use SharedEngines
        use_shared_engines = os.getenv("USE_SHARED_ENGINES", "false").lower() in ("true", "1", "yes")
        shared_engines = None

        if use_shared_engines:
            logger.info("SharedEngines enabled via USE_SHARED_ENGINES environment variable")
            try:
                from src.shared_engines.composition_root import CompositionRoot

                # Create engines configuration from environment
                engines_config = {
                    "config_root": config_path,
                    "log_level": log_level,
                    "telemetry_enabled": True,
                    "job_backend": "redis",
                    "redis_host": redis_host,
                    "redis_port": redis_port,
                    "commit_enabled": os.getenv("COMMIT_ENABLED", "true").lower() in ("true", "1", "yes"),
                    "max_retries": max_retries,
                }

                shared_engines = CompositionRoot.create_from_config(engines_config)
                logger.info("SharedEngines created successfully")

            except Exception as e:
                logger.error(f"Failed to create SharedEngines: {e}", exc_info=True)
                logger.info("Falling back to legacy mode")
                shared_engines = None

        # Create and run processor (legacy mode)
        processor = JobProcessor(
            redis_host=redis_host,
            redis_port=redis_port,
            redis_db=redis_db,
            redis_password=redis_password if redis_password else None,
            poll_interval=poll_interval,
            max_retries=max_retries,
            config_path=config_path,
            tm_path=tm_path,
            engines=shared_engines,  # NEW: Pass SharedEngines if created
        )

        try:
            processor.run()
            return 0
        except Exception as e:
            logger.error(f"Job processor failed: {e}", exc_info=True)
            return 1


if __name__ == "__main__":
    sys.exit(main())
