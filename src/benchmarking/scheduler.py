"""Benchmark scheduler for resource-aware execution.

Provides job queue management and resource-aware scheduling to prevent
system choking from concurrent or resource-heavy benchmarks.
"""

import os
import uuid
import warnings
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, TYPE_CHECKING
import logging
import yaml

from src.benchmarking.storage import BenchmarkDatabase, BenchmarkRun
from src.benchmarking.resource_monitor import ResourceMonitor, ResourceEstimate, ResourceSnapshot
from src.benchmarking.system_info import SystemInfo, SystemInfoCollector

if TYPE_CHECKING:
    from src.shared_engines.composition_root import SharedEngines

logger = logging.getLogger(__name__)


@dataclass
class ScheduledBenchmark:
    """A benchmark job in the scheduler queue."""

    job_id: str
    config: Dict[str, Any]  # Benchmark configuration
    priority: int  # Lower = higher priority (0 is highest)
    estimated_resources: ResourceEstimate
    status: str  # "pending", "running", "completed", "failed", "cancelled"
    queued_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]


class ResourceEstimator:
    """Estimates resource requirements for benchmark configurations."""

    def estimate(
        self, config: Dict[str, Any], system_info: SystemInfo
    ) -> ResourceEstimate:
        """Estimate resource requirements for a benchmark configuration.

        Uses heuristics based on model size, batch size, and device.

        Args:
            config: Benchmark configuration dictionary
            system_info: System information for context

        Returns:
            ResourceEstimate with predicted requirements
        """
        # Extract config parameters
        model_id = config.get("model_id", "unknown")
        device = config.get("device", "cpu")
        batch_size = config.get("batch_size", 1)

        # Estimate based on model size (heuristic)
        # Small models: ~500MB, Medium: ~1.5GB, Large: ~5GB
        base_memory_mb = 500.0

        if "1.2B" in model_id or "1.3B" in model_id:
            base_memory_mb = 1500.0
        elif "3B" in model_id or "7B" in model_id:
            base_memory_mb = 5000.0
        elif "13B" in model_id:
            base_memory_mb = 10000.0

        # Scale by batch size
        estimated_memory_mb = base_memory_mb * (1 + (batch_size - 1) * 0.3)

        # GPU memory estimate (if using GPU)
        estimated_gpu_memory_mb = None
        if device in ["cuda", "gpu"]:
            # GPU typically needs more for model + inference
            estimated_gpu_memory_mb = estimated_memory_mb * 1.5

        # Duration estimate (rough heuristic)
        # Assume ~1 minute baseline, scale by corpus size
        corpus_size = config.get("corpus_size", 100)
        estimated_duration_seconds = 60.0 * (corpus_size / 100.0)

        # Confidence based on how much info we have
        confidence = 0.5  # Default medium confidence
        if "batch_size" in config and "model_id" in config:
            confidence = 0.7

        return ResourceEstimate(
            estimated_memory_mb=estimated_memory_mb,
            estimated_gpu_memory_mb=estimated_gpu_memory_mb,
            estimated_duration_seconds=estimated_duration_seconds,
            device_required=device,
            confidence=confidence,
        )


class BenchmarkScheduler:
    """Resource-aware benchmark scheduler with job queue.

    Manages a queue of benchmark jobs and executes them when
    resources are available, preventing system overload.

    Phase 5.3 Migration:
        Supports optional SharedEngines for unified telemetry, logging,
        and configuration. Falls back to legacy mode if engines not provided.
    """

    def __init__(
        self,
        db: BenchmarkDatabase,
        config_path: Optional[Path] = None,
        engines: Optional["SharedEngines"] = None,
    ):
        """Initialize benchmark scheduler.

        Args:
            db: Benchmark database instance (ignored if engines provided)
            config_path: Optional path to scheduler config YAML (ignored if engines provided)
            engines: SharedEngines container (NEW - Phase 5.3 migration)
                    If provided, uses shared engines instead of direct instantiation.
                    Enables unified telemetry, logging, and configuration.
        """
        # PHASE 5.3: Detect if using SharedEngines or legacy mode
        self._using_shared_engines = engines is not None
        self.engines = engines

        if not self._using_shared_engines:
            # Legacy mode: Direct instantiation (DEPRECATED)
            warnings.warn(
                "Instantiating BenchmarkScheduler without SharedEngines is deprecated. "
                "Use CompositionRoot.create_from_config() and pass engines parameter. "
                "Legacy mode will be removed in a future release.",
                DeprecationWarning,
                stacklevel=2
            )
            logger.warning(
                "BenchmarkScheduler running in LEGACY mode (direct instantiation). "
                "Consider migrating to SharedEngines for unified telemetry and configuration."
            )

        # PHASE 5.3: Use SharedEngines if available, otherwise legacy instantiation
        if self._using_shared_engines:
            logger.info("Using SharedEngines (Phase 5.3 migration)")

            # Use logging from SharedEngines
            # Note: Logger is already configured by SharedEngines
            logger.info(f"Using shared logging from SharedEngines")

            # Emit telemetry event for scheduler startup
            try:
                self.engines.telemetry.track_event(
                    event_type="benchmark_scheduler_started",
                    mode="shared_engines"
                )
            except Exception as e:
                logger.debug(f"Telemetry event failed (non-fatal): {e}")

            # For now, still use passed db (future: could use engines.job for storage)
            self.db = db

        else:
            # LEGACY MODE: Direct instantiation
            self.db = db

        self.monitor = ResourceMonitor()
        self.estimator = ResourceEstimator()

        # Load config
        self.config = self._load_config(config_path)

        # Initialize queue table
        self._ensure_queue_table()

    def _load_config(self, config_path: Optional[Path]) -> Dict[str, Any]:
        """Load scheduler configuration."""
        default_config = {
            "max_cpu_percent": 80,
            "max_memory_percent": 85,
            "max_gpu_memory_percent": 90,
            "min_available_memory_mb": 1024,
            "default_timeout_seconds": 3600,
            "poll_interval_seconds": 5,
        }

        if config_path and config_path.exists():
            try:
                with open(config_path, "r") as f:
                    loaded = yaml.safe_load(f)
                    scheduler_config = loaded.get("scheduler", {})
                    default_config.update(scheduler_config)
                    logger.info(f"Loaded scheduler config from {config_path}")
            except Exception as e:
                logger.warning(f"Failed to load scheduler config: {e}, using defaults")

        return default_config

    def _ensure_queue_table(self) -> None:
        """Ensure job queue table exists in database."""
        try:
            with self.db._get_connection() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS benchmark_queue (
                        job_id TEXT PRIMARY KEY,
                        config_json TEXT NOT NULL,
                        priority INTEGER NOT NULL DEFAULT 5,
                        estimated_memory_mb REAL NOT NULL,
                        estimated_gpu_memory_mb REAL,
                        estimated_duration_seconds REAL NOT NULL,
                        device_required TEXT NOT NULL,
                        status TEXT NOT NULL,
                        queued_at TEXT NOT NULL,
                        started_at TEXT,
                        completed_at TEXT
                    )
                    """
                )

                # Create indices
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_queue_status_priority "
                    "ON benchmark_queue(status, priority)"
                )

                conn.commit()

        except Exception as e:
            logger.error(f"Failed to create queue table: {e}")

    def schedule(
        self, config: Dict[str, Any], priority: int = 5
    ) -> str:
        """Schedule a benchmark job.

        Args:
            config: Benchmark configuration
            priority: Priority (0=highest, default=5)

        Returns:
            Job ID
        """
        try:
            job_id = str(uuid.uuid4())[:8]
            queued_at = datetime.utcnow()

            # Estimate resources
            system_info = SystemInfoCollector().collect()
            estimate = self.estimator.estimate(config, system_info)

            # Store in queue
            import json

            with self.db._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO benchmark_queue (
                        job_id, config_json, priority,
                        estimated_memory_mb, estimated_gpu_memory_mb,
                        estimated_duration_seconds, device_required,
                        status, queued_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job_id,
                        json.dumps(config),
                        priority,
                        estimate.estimated_memory_mb,
                        estimate.estimated_gpu_memory_mb,
                        estimate.estimated_duration_seconds,
                        estimate.device_required,
                        "pending",
                        queued_at.isoformat() + "Z",
                    ),
                )
                conn.commit()

            logger.info(
                f"Scheduled benchmark job {job_id} with priority {priority} "
                f"(est. {estimate.estimated_memory_mb:.0f}MB, {estimate.estimated_duration_seconds:.0f}s)"
            )

            # PHASE 5.3: Emit telemetry event if using SharedEngines
            if self._using_shared_engines:
                try:
                    self.engines.telemetry.track_event(
                        event_type="benchmark_job_scheduled",
                        job_id=job_id,
                        priority=priority,
                        estimated_memory_mb=estimate.estimated_memory_mb,
                        device_required=estimate.device_required
                    )
                except Exception as e:
                    logger.debug(f"Telemetry event failed (non-fatal): {e}")

            return job_id

        except Exception as e:
            logger.error(f"Failed to schedule benchmark: {e}")

            # PHASE 5.3: Emit failure event if using SharedEngines
            if self._using_shared_engines:
                try:
                    self.engines.telemetry.track_event(
                        event_type="benchmark_job_schedule_failed",
                        error=str(e)
                    )
                except Exception as tel_err:
                    logger.debug(f"Telemetry event failed (non-fatal): {tel_err}")

            raise

    def can_run_now(self, job_id: str) -> bool:
        """Check if a job can run given current resources.

        Args:
            job_id: Job ID to check

        Returns:
            True if job can run now, False otherwise
        """
        try:
            job = self._get_job(job_id)
            if not job:
                return False

            # Check resource availability
            return self.monitor.is_safe_to_run(
                job.estimated_resources,
                safety_margin=0.2,
            )

        except Exception as e:
            logger.error(f"Failed to check if job can run: {e}")
            return False

    def get_queue_status(self) -> List[ScheduledBenchmark]:
        """Get current queue status.

        Returns:
            List of ScheduledBenchmark jobs ordered by priority
        """
        try:
            import json

            with self.db._get_connection() as conn:
                cursor = conn.execute(
                    """
                    SELECT job_id, config_json, priority,
                           estimated_memory_mb, estimated_gpu_memory_mb,
                           estimated_duration_seconds, device_required,
                           status, queued_at, started_at, completed_at
                    FROM benchmark_queue
                    ORDER BY status, priority, queued_at
                    """
                )

                jobs = []
                for row in cursor.fetchall():
                    estimate = ResourceEstimate(
                        estimated_memory_mb=row[3],
                        estimated_gpu_memory_mb=row[4],
                        estimated_duration_seconds=row[5],
                        device_required=row[6],
                        confidence=0.5,
                    )

                    jobs.append(
                        ScheduledBenchmark(
                            job_id=row[0],
                            config=json.loads(row[1]),
                            priority=row[2],
                            estimated_resources=estimate,
                            status=row[7],
                            queued_at=datetime.fromisoformat(row[8].rstrip("Z")),
                            started_at=datetime.fromisoformat(row[9].rstrip("Z"))
                            if row[9]
                            else None,
                            completed_at=datetime.fromisoformat(row[10].rstrip("Z"))
                            if row[10]
                            else None,
                        )
                    )

                return jobs

        except Exception as e:
            logger.error(f"Failed to get queue status: {e}")
            return []

    def cancel(self, job_id: str) -> bool:
        """Cancel a pending job.

        Args:
            job_id: Job ID to cancel

        Returns:
            True if cancelled, False otherwise
        """
        try:
            with self.db._get_connection() as conn:
                cursor = conn.execute(
                    """
                    UPDATE benchmark_queue
                    SET status = 'cancelled', completed_at = ?
                    WHERE job_id = ? AND status = 'pending'
                    """,
                    (datetime.utcnow().isoformat() + "Z", job_id),
                )
                conn.commit()

                if cursor.rowcount > 0:
                    logger.info(f"Cancelled job {job_id}")
                    return True
                else:
                    logger.warning(f"Could not cancel job {job_id} (not found or not pending)")
                    return False

        except Exception as e:
            logger.error(f"Failed to cancel job: {e}")
            return False

    def run_next(self) -> Optional[BenchmarkRun]:
        """Run the next pending job if resources allow.

        Returns:
            BenchmarkRun if job was executed, None otherwise

        Note:
            This is a blocking operation that waits for resources
            up to the configured timeout.
        """
        try:
            # Get next pending job
            jobs = self.get_queue_status()
            pending = [j for j in jobs if j.status == "pending"]

            if not pending:
                logger.debug("No pending jobs in queue")
                return None

            job = pending[0]  # Highest priority pending job
            logger.info(f"Attempting to run job {job.job_id}")

            # Wait for resources
            timeout = self.config.get("default_timeout_seconds", 3600)
            if not self.monitor.wait_for_resources(job.estimated_resources, timeout):
                logger.warning(f"Timeout waiting for resources for job {job.job_id}")

                # PHASE 5.3: Emit timeout event if using SharedEngines
                if self._using_shared_engines:
                    try:
                        self.engines.telemetry.track_event(
                            event_type="benchmark_job_timeout",
                            job_id=job.job_id,
                            timeout_seconds=timeout
                        )
                    except Exception as e:
                        logger.debug(f"Telemetry event failed (non-fatal): {e}")

                return None

            # Mark as running
            self._update_job_status(job.job_id, "running", started_at=datetime.utcnow())

            # PHASE 5.3: Emit job started event if using SharedEngines
            if self._using_shared_engines:
                try:
                    self.engines.telemetry.track_event(
                        event_type="benchmark_job_started",
                        job_id=job.job_id
                    )
                except Exception as e:
                    logger.debug(f"Telemetry event failed (non-fatal): {e}")

            # Execute benchmark (stub - actual execution would go here)
            # For now, just mark as completed
            logger.info(f"Would execute job {job.job_id} here")

            # Mark as completed
            self._update_job_status(job.job_id, "completed", completed_at=datetime.utcnow())

            # PHASE 5.3: Emit job completed event if using SharedEngines
            if self._using_shared_engines:
                try:
                    self.engines.telemetry.track_event(
                        event_type="benchmark_job_completed",
                        job_id=job.job_id
                    )
                except Exception as e:
                    logger.debug(f"Telemetry event failed (non-fatal): {e}")

            # Return None for now (would return BenchmarkRun in real implementation)
            return None

        except Exception as e:
            logger.error(f"Failed to run next job: {e}")

            # PHASE 5.3: Emit failure event if using SharedEngines
            if self._using_shared_engines:
                try:
                    self.engines.telemetry.track_event(
                        event_type="benchmark_job_failed",
                        error=str(e)
                    )
                except Exception as tel_err:
                    logger.debug(f"Telemetry event failed (non-fatal): {tel_err}")

            return None

    def run_all(self, max_concurrent: int = 1) -> List[BenchmarkRun]:
        """Run all pending jobs (respecting max concurrency).

        Args:
            max_concurrent: Maximum concurrent jobs (default 1 for safety)

        Returns:
            List of completed BenchmarkRuns
        """
        completed = []

        while True:
            pending = [j for j in self.get_queue_status() if j.status == "pending"]
            if not pending:
                break

            # For now, just run one at a time (max_concurrent=1 enforced)
            result = self.run_next()
            if result:
                completed.append(result)
            else:
                break  # Stop if can't run

        return completed

    def _get_job(self, job_id: str) -> Optional[ScheduledBenchmark]:
        """Get job by ID."""
        jobs = self.get_queue_status()
        for job in jobs:
            if job.job_id == job_id:
                return job
        return None

    def _update_job_status(
        self,
        job_id: str,
        status: str,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
    ) -> None:
        """Update job status in queue."""
        try:
            updates = ["status = ?"]
            params = [status]

            if started_at:
                updates.append("started_at = ?")
                params.append(started_at.isoformat() + "Z")

            if completed_at:
                updates.append("completed_at = ?")
                params.append(completed_at.isoformat() + "Z")

            params.append(job_id)

            with self.db._get_connection() as conn:
                conn.execute(
                    f"""
                    UPDATE benchmark_queue
                    SET {', '.join(updates)}
                    WHERE job_id = ?
                    """,
                    params,
                )
                conn.commit()

        except Exception as e:
            logger.error(f"Failed to update job status: {e}")
