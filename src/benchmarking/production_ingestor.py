"""Production metrics integration for benchmarking.

Bridges production translation runs to the benchmark database, enabling
continuous learning from real workloads.

OPT-IN feature - disabled by default to prevent unintended data collection.
"""

import logging
import threading
import time
import uuid
from typing import Optional

from src.benchmarking.storage import BenchmarkDatabase, BenchmarkRun
from src.benchmarking.system_info import SystemInfo, SystemInfoCollector

logger = logging.getLogger(__name__)


class ProductionMetricsIngestor:
    """Records production translation runs as benchmark data (OPT-IN)."""

    def __init__(self, db: BenchmarkDatabase, enabled: bool = False, min_segments: int = 1):
        """Initialize production metrics ingestor.

        Args:
            db: Benchmark database instance
            enabled: Whether to record metrics (default: False - OPT-IN)
            min_segments: Minimum segments required to record (default: 1)
        """
        self.db = db
        self.enabled = enabled
        self.min_segments = max(1, min_segments)  # Ensure at least 1
        self._lock = threading.Lock()
        self._collector = SystemInfoCollector() if enabled else None
        logger.info(f"ProductionMetricsIngestor initialized (enabled={enabled}, min_segments={self.min_segments})")

    def record_translation_run(
        self,
        file_path: str,
        target_lang: str,
        segments_translated: int,
        segments_from_tm: int,
        segments_translated_new: int,
        translation_model: str,
        retry_count: int,
        success: bool,
        duration_seconds: float = 0.0,
    ) -> None:
        """Record a production translation run as benchmark data.

        Args:
            file_path: Path to file being translated
            target_lang: Target language code
            segments_translated: Total segments translated
            segments_from_tm: Segments retrieved from TM
            segments_translated_new: Segments newly translated
            translation_model: Model ID used for translation
            retry_count: Number of retries during translation
            success: Whether translation succeeded
            duration_seconds: Total duration in seconds

        Note:
            When enabled=False, this is a no-op and returns immediately.
            When enabled=True, records to database but NEVER crashes on error.
        """
        if not self.enabled:
            return  # No-op when disabled

        # Skip recording if below threshold
        if segments_translated < self.min_segments:
            logger.debug(
                f"Skipping metrics recording: segments={segments_translated} < threshold={self.min_segments}"
            )
            return

        try:
            with self._lock:
                # Collect system info at record time (not constructor time)
                system_info = self._collector.collect()

                # Create unique run ID
                run_id = f"prod_{uuid.uuid4().hex[:8]}_{int(time.time())}"

                # Create benchmark run
                run = BenchmarkRun(
                    run_id=run_id,
                    model_id=translation_model,
                    device="unknown",  # Not tracked in production
                    batch_sizes=[],  # Not applicable to production runs
                    iterations=segments_translated,
                    corpus_category="production",
                    purpose="production",
                    tags=["production", target_lang, "auto-recorded"],
                    system_info=system_info,
                    results=[],  # No detailed results in production
                    total_duration_seconds=duration_seconds,
                )

                # Save to database
                self.db.save_run(run)
                logger.info(
                    f"Recorded translation metrics: file={file_path} lang={target_lang} "
                    f"segments={segments_translated} duration={duration_seconds:.2f}s run_id={run_id}"
                )

        except Exception as e:
            # CRITICAL: MUST NOT crash translation pipeline
            logger.error(f"Failed to record production metrics: {e}", exc_info=True)
