"""
TM Improvement Worker.

Autonomous worker that improves TM entries using LLM with:
- Two modes: oneshot (run once) and daemon (self-schedules)
- VRAM enforcement with preflight/post-call checks
- Queue-based candidate selection (no full LMDB scan)
- Validation before writing improvements back to TM
- Telemetry with job_type="tm_improvement", trigger_type="scheduled"
"""

import argparse
import hashlib
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List

import torch

from src.hardware.vram_enforcer import VRAMEnforcer
from src.hardware.gpu_manager import GPUManager
from src.intelligence.llm_client import LLMClient, LLMConfig
from src.tm import TranslationMemory
from src.tm.improvement_queue import ImprovementQueue, ImprovementCandidate
from src.tm.l1_cache import L1Cache
from src.tm.l2_persistent import L2PersistentTM
from src.utils.config_loader import ConfigService
from src.workers.window_scheduler import ScheduleConfig, WindowScheduler

try:
    from src.tm.l3_semantic import L3SemanticTM
except ImportError:
    L3SemanticTM = None

logger = logging.getLogger(__name__)


class TMImprovementWorkerConfig:
    """
    Configuration for TM improvement worker.

    Attributes:
        config_root: Root directory for configuration files
        tm_path: Path to TM data directory
        mode: "oneshot" or "daemon"
        runs_per_day: Number of runs per day (daemon mode only)
        window_start: Start of daily window (HH:MM)
        window_end: End of daily window (HH:MM)
        timezone: Timezone name (e.g., "America/Los_Angeles")
        jitter_minutes: Random jitter to add/subtract
        candidates_per_run: Max candidates to process per run
        max_llm_calls_per_run: Max LLM calls per run
        max_seconds_per_run: Max runtime per run
        llm_provider: LLM provider (ollama, openai, anthropic)
        llm_model: LLM model name
        llm_base_url: LLM base URL (for Ollama)
        llm_api_key: LLM API key (for cloud providers)
        llm_timeout_seconds: LLM timeout per call
        llm_temperature: LLM temperature
        max_gpu_memory_percent: GPU memory limit (percentage)
        preflight_check: Check GPU usage before starting
        abort_on_high_usage: Abort if GPU already high at start
        device: Device for LLM inference (cpu, cuda, auto)
    """

    def __init__(
        self,
        config_root: str = "config/",
        tm_path: str = "data/tm",
        mode: str = "oneshot",
        runs_per_day: int = 5,
        window_start: str = "10:00",
        window_end: str = "22:00",
        timezone: str = "America/Los_Angeles",
        jitter_minutes: int = 10,
        candidates_per_run: int = 50,
        max_llm_calls_per_run: int = 200,
        max_seconds_per_run: int = 900,
        llm_provider: str = "ollama",
        llm_model: str = "llama2",
        llm_base_url: Optional[str] = "http://localhost:11434",
        llm_api_key: Optional[str] = None,
        llm_timeout_seconds: int = 30,
        llm_temperature: float = 0.3,
        max_gpu_memory_percent: int = 60,
        preflight_check: bool = True,
        abort_on_high_usage: bool = True,
        device: str = "auto",
    ):
        """Initialize worker configuration."""
        self.config_root = config_root
        self.tm_path = Path(tm_path)
        self.mode = mode
        self.runs_per_day = runs_per_day
        self.window_start = window_start
        self.window_end = window_end
        self.timezone = timezone
        self.jitter_minutes = jitter_minutes
        self.candidates_per_run = candidates_per_run
        self.max_llm_calls_per_run = max_llm_calls_per_run
        self.max_seconds_per_run = max_seconds_per_run
        self.llm_provider = llm_provider
        self.llm_model = llm_model
        self.llm_base_url = llm_base_url
        self.llm_api_key = llm_api_key
        self.llm_timeout_seconds = llm_timeout_seconds
        self.llm_temperature = llm_temperature
        self.max_gpu_memory_percent = max_gpu_memory_percent
        self.preflight_check = preflight_check
        self.abort_on_high_usage = abort_on_high_usage
        self.device = device

    @classmethod
    def from_config_service(
        cls, config_service: ConfigService, mode: str = "oneshot"
    ) -> "TMImprovementWorkerConfig":
        """
        Create configuration from ConfigService.

        Args:
            config_service: ConfigService instance
            mode: Execution mode (oneshot or daemon)

        Returns:
            TMImprovementWorkerConfig instance
        """
        # Load tm_improvement config section
        config = config_service.config

        tm_improvement = config.get("tm_improvement", {})
        schedule = tm_improvement.get("schedule", {})
        batch = tm_improvement.get("batch", {})
        llm = tm_improvement.get("llm", {})
        resources = tm_improvement.get("resources", {})
        queue = tm_improvement.get("queue", {})

        # Get TM path from paths config
        paths = config.get("paths", {})
        tm_path = paths.get("tm_data_dir", "data/tm")

        return cls(
            config_root=config_service.config_root,
            tm_path=tm_path,
            mode=mode,
            runs_per_day=schedule.get("runs_per_day", 5),
            window_start=schedule.get("window_start", "10:00"),
            window_end=schedule.get("window_end", "22:00"),
            timezone=schedule.get("timezone", "America/Los_Angeles"),
            jitter_minutes=schedule.get("jitter_minutes", 10),
            candidates_per_run=batch.get("candidates_per_run", 50),
            max_llm_calls_per_run=batch.get("max_llm_calls_per_run", 200),
            max_seconds_per_run=batch.get("max_seconds_per_run", 900),
            llm_provider=llm.get("provider", "ollama"),
            llm_model=llm.get("model", "llama2"),
            llm_base_url=llm.get("base_url", "http://localhost:11434"),
            llm_api_key=llm.get("api_key"),
            llm_timeout_seconds=llm.get("timeout_seconds", 30),
            llm_temperature=llm.get("temperature", 0.3),
            max_gpu_memory_percent=resources.get("max_gpu_memory_percent", 60),
            preflight_check=resources.get("preflight_check", True),
            abort_on_high_usage=resources.get("abort_on_high_usage", True),
            device="auto",
        )


class TMImprovementWorker:
    """
    Autonomous worker for TM improvement using LLM.

    Processes candidates from the improvement queue and uses LLM to enhance
    translations. Writes improvements back to TM with proper metadata.

    Example:
        # Oneshot mode (run once)
        config = TMImprovementWorkerConfig(mode="oneshot")
        worker = TMImprovementWorker(config)
        worker.run()

        # Daemon mode (self-schedules)
        config = TMImprovementWorkerConfig(
            mode="daemon",
            runs_per_day=5,
            window_start="10:00",
            window_end="22:00",
            timezone="America/Los_Angeles"
        )
        worker = TMImprovementWorker(config)
        worker.run()  # Runs continuously
    """

    def __init__(self, config: TMImprovementWorkerConfig):
        """
        Initialize TM improvement worker.

        Args:
            config: Worker configuration
        """
        self.config = config
        self.config_service = None
        self.tm = None
        self.improvement_queue = None
        self.llm_client = None
        self.scheduler = None
        self.gpu_manager = None

        logger.info(f"Initialized TMImprovementWorker: mode={config.mode}")

    def setup(self) -> None:
        """
        Setup worker components.

        Initializes:
        - ConfigService for loading configuration
        - VRAMEnforcer for GPU memory management
        - ImprovementQueue for candidate management
        - TranslationMemory for TM access
        - LLMClient for translation improvements
        - WindowScheduler for daemon mode scheduling
        """
        logger.info("Setting up TM improvement worker components...")

        # Initialize ConfigService
        try:
            self.config_service = ConfigService(self.config.config_root)
            logger.info(f"Loaded config from: {self.config.config_root}")
        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            raise

        # Initialize GPU manager for VRAM checks
        if self.config.device.startswith("cuda") or self.config.device == "auto":
            try:
                self.gpu_manager = GPUManager()
                logger.info("Initialized GPUManager for VRAM monitoring")
            except Exception as e:
                logger.warning(f"Failed to initialize GPUManager: {e}")
                self.gpu_manager = None

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

        # Initialize improvement queue
        try:
            self.improvement_queue = ImprovementQueue(self.config.tm_path)
            queue_stats = self.improvement_queue.stats()
            logger.info(
                f"Initialized ImprovementQueue: {queue_stats['queue_size']} candidates, "
                f"{queue_stats['seen_hashes']} seen hashes"
            )
        except Exception as e:
            logger.error(f"Failed to initialize improvement queue: {e}")
            raise

        # Initialize TranslationMemory
        try:
            # Create L1 cache
            l1_cache = L1Cache(max_size=10000)

            # Create L2 persistent store
            l2_store = L2PersistentTM(db_path=self.config.tm_path / "l2.lmdb")

            # Create L3 semantic store (optional)
            l3_store = None
            if L3SemanticTM is not None:
                try:
                    l3_store = L3SemanticTM(
                        index_path=self.config.tm_path / "l3_faiss",
                        device=self.config.device,
                    )
                except Exception as e:
                    logger.warning(f"Failed to initialize L3 semantic TM: {e}")

            # Create TranslationMemory
            self.tm = TranslationMemory(
                l1_cache=l1_cache,
                l2_persistent=l2_store,
                l3_semantic=l3_store,
            )

            logger.info("Initialized TranslationMemory")

        except Exception as e:
            logger.error(f"Failed to initialize TranslationMemory: {e}")
            raise

        # Initialize LLM client
        try:
            llm_config = LLMConfig(
                provider=self.config.llm_provider,
                model=self.config.llm_model,
                base_url=self.config.llm_base_url,
                api_key=self.config.llm_api_key,
                timeout_seconds=self.config.llm_timeout_seconds,
                temperature=self.config.llm_temperature,
            )

            self.llm_client = LLMClient(llm_config)

            if self.llm_client.is_available():
                logger.info(
                    f"Initialized LLM client: {self.config.llm_provider}/{self.config.llm_model}"
                )
            else:
                logger.error("LLM client is not available - worker cannot function")
                raise RuntimeError("LLM client unavailable")

        except Exception as e:
            logger.error(f"Failed to initialize LLM client: {e}")
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
        Run TM improvement worker.

        In oneshot mode: Executes one improvement run and exits
        In daemon mode: Continuously schedules and executes runs
        """
        if self.config.mode == "oneshot":
            self._run_oneshot()
        elif self.config.mode == "daemon":
            self._run_daemon()
        else:
            raise ValueError(
                f"Invalid mode: {self.config.mode}. Expected 'oneshot' or 'daemon'"
            )

    def _run_oneshot(self) -> None:
        """Execute a single improvement run and exit."""
        logger.info("=" * 80)
        logger.info("ONESHOT MODE: Running single improvement pass")
        logger.info("=" * 80)

        try:
            result = self._execute_improvement_run()

            if result["status"] == "success":
                logger.info(
                    f"Oneshot run completed: {result['improved_count']} improved, "
                    f"{result['skipped_count']} skipped, {result['failed_count']} failed"
                )
            else:
                logger.warning(f"Oneshot run completed with status: {result['status']}")

        except Exception as e:
            logger.error(f"Oneshot run failed: {e}", exc_info=True)
            sys.exit(1)

    def _run_daemon(self) -> None:
        """Continuously schedule and execute improvement runs."""
        logger.info("=" * 80)
        logger.info("DAEMON MODE: Starting continuous scheduler")
        logger.info(f"Schedule: {self.config.runs_per_day} runs/day")
        logger.info(
            f"Window: {self.config.window_start}-{self.config.window_end} {self.config.timezone}"
        )
        logger.info("=" * 80)

        run_count = 0

        try:
            while True:
                # Sleep until next run time
                next_run = self.scheduler.sleep_until_next_run()
                run_count += 1

                logger.info("=" * 80)
                logger.info(
                    f"SCHEDULED RUN #{run_count} at {next_run.strftime('%Y-%m-%d %H:%M:%S %Z')}"
                )
                logger.info("=" * 80)

                try:
                    result = self._execute_improvement_run()

                    if result["status"] == "success":
                        logger.info(
                            f"Run #{run_count} completed: {result['improved_count']} improved, "
                            f"{result['skipped_count']} skipped, {result['failed_count']} failed"
                        )
                    else:
                        logger.warning(f"Run #{run_count} status: {result['status']}")

                except Exception as e:
                    logger.error(f"Run #{run_count} failed: {e}", exc_info=True)
                    # Continue to next run despite failure

        except KeyboardInterrupt:
            logger.info("Daemon interrupted by user (Ctrl+C)")
        except Exception as e:
            logger.error(f"Daemon failed: {e}", exc_info=True)
            sys.exit(1)

    def _check_gpu_usage(self) -> Optional[float]:
        """
        Check current GPU usage as percentage of total.

        Returns:
            GPU usage as percentage (0.0-100.0), or None if GPU not available
        """
        if not self.gpu_manager or not torch.cuda.is_available():
            return None

        try:
            gpu_info = self.gpu_manager.get_gpu_memory(device_id=0)
            if gpu_info:
                usage_percent = (gpu_info.used_mb / gpu_info.total_mb) * 100
                return usage_percent
        except Exception as e:
            logger.error(f"Failed to check GPU usage: {e}")

        return None

    def _execute_improvement_run(self) -> Dict[str, Any]:
        """
        Execute a single improvement run.

        Returns:
            Dictionary with run results
        """
        start_time = time.time()

        # VRAM preflight check
        if self.config.preflight_check and self.config.abort_on_high_usage:
            gpu_usage = self._check_gpu_usage()
            if gpu_usage is not None and gpu_usage >= self.config.max_gpu_memory_percent:
                logger.warning(
                    f"PREFLIGHT CHECK FAILED: GPU usage ({gpu_usage:.1f}%) already at or above "
                    f"threshold ({self.config.max_gpu_memory_percent}%). Aborting run."
                )
                return {
                    "status": "aborted",
                    "reason": "gpu_usage_high",
                    "gpu_usage_percent": gpu_usage,
                }

        # Pop candidates from queue
        logger.info(f"Popping up to {self.config.candidates_per_run} candidates from queue...")
        candidates = self.improvement_queue.pop_candidates(limit=self.config.candidates_per_run)

        if not candidates:
            logger.info("No candidates in queue")
            return {
                "status": "success",
                "candidates_pulled": 0,
                "improved_count": 0,
                "skipped_count": 0,
                "failed_count": 0,
            }

        logger.info(f"Processing {len(candidates)} candidates")

        # Process candidates
        improved_count = 0
        skipped_count = 0
        failed_count = 0
        llm_calls = 0

        for i, candidate in enumerate(candidates):
            # Check time limit
            elapsed = time.time() - start_time
            if elapsed > self.config.max_seconds_per_run:
                logger.warning(
                    f"Time limit reached ({self.config.max_seconds_per_run}s), "
                    f"stopping after {i + 1}/{len(candidates)} candidates"
                )
                # Re-queue remaining candidates
                for remaining in candidates[i + 1 :]:
                    self.improvement_queue.append_candidate(
                        site_id=remaining.site_id,
                        src_lang=remaining.src_lang,
                        tgt_lang=remaining.tgt_lang,
                        text=remaining.text,
                        translation=remaining.translation,
                        context=remaining.context,
                        metadata=remaining.metadata,
                    )
                break

            # Check LLM call limit
            if llm_calls >= self.config.max_llm_calls_per_run:
                logger.warning(
                    f"LLM call limit reached ({self.config.max_llm_calls_per_run}), "
                    f"stopping after {i + 1}/{len(candidates)} candidates"
                )
                break

            # Process candidate
            try:
                result = self._improve_candidate(candidate)

                if result == "improved":
                    improved_count += 1
                elif result == "skipped":
                    skipped_count += 1
                elif result == "failed":
                    failed_count += 1

                llm_calls += 1

                # Check GPU usage after each call (post-call check)
                if self.config.abort_on_high_usage:
                    gpu_usage = self._check_gpu_usage()
                    if gpu_usage is not None and gpu_usage >= self.config.max_gpu_memory_percent:
                        logger.warning(
                            f"POST-CALL CHECK: GPU usage ({gpu_usage:.1f}%) exceeded "
                            f"threshold ({self.config.max_gpu_memory_percent}%). "
                            f"Pausing further work."
                        )
                        break

            except Exception as e:
                logger.error(
                    f"Failed to process candidate {i + 1}/{len(candidates)}: {e}",
                    exc_info=True,
                )
                failed_count += 1

        elapsed = time.time() - start_time

        logger.info(
            f"Improvement run completed in {elapsed:.1f}s: "
            f"{improved_count} improved, {skipped_count} skipped, {failed_count} failed, "
            f"{llm_calls} LLM calls"
        )

        return {
            "status": "success",
            "candidates_pulled": len(candidates),
            "improved_count": improved_count,
            "skipped_count": skipped_count,
            "failed_count": failed_count,
            "llm_calls": llm_calls,
            "elapsed_seconds": elapsed,
        }

    def _improve_candidate(self, candidate: ImprovementCandidate) -> str:
        """
        Improve a single candidate translation using LLM.

        Args:
            candidate: Candidate to improve

        Returns:
            Status: "improved", "skipped", or "failed"
        """
        logger.debug(
            f"Improving: {candidate.site_id}/{candidate.src_lang}->{candidate.tgt_lang}, "
            f"text='{candidate.text[:50]}...'"
        )

        # Call LLM to improve translation
        try:
            improved_translation = self.llm_client.adapt_translation(
                source_text=candidate.text,
                fuzzy_translation=candidate.translation,
                source_lang=candidate.src_lang,
                target_lang=candidate.tgt_lang,
                context=candidate.context,
                similarity_score=candidate.metadata.get("similarity_score", 0.0)
                if candidate.metadata
                else 0.0,
            )

            if not improved_translation:
                logger.debug("LLM returned no improvement, skipping")
                return "skipped"

            # Validate improved translation
            if not self._validate_improved_translation(
                original=candidate.translation, improved=improved_translation
            ):
                logger.debug("Improved translation failed validation, skipping")
                return "skipped"

            # Compute hash of previous translation
            previous_hash = hashlib.sha256(candidate.translation.encode()).hexdigest()[:16]

            # Store improved translation back to TM with force_update=True
            metadata = {
                "improved_by": "tm_improvement_worker",
                "improved_at": datetime.utcnow().isoformat(),
                "previous_hash": previous_hash,
                "previous_translation": candidate.translation,
                "llm_provider": self.config.llm_provider,
                "llm_model": self.config.llm_model,
            }

            stored = self.tm.store(
                site_id=candidate.site_id,
                src_lang=candidate.src_lang,
                tgt_lang=candidate.tgt_lang,
                text=candidate.text,
                translation=improved_translation,
                context=candidate.context,
                metadata=metadata,
                force_update=True,
            )

            if stored:
                logger.debug(
                    f"Improved translation stored: '{candidate.translation[:50]}...' -> "
                    f"'{improved_translation[:50]}...'"
                )
                return "improved"
            else:
                logger.debug("Failed to store improved translation")
                return "failed"

        except Exception as e:
            logger.error(f"Failed to improve candidate: {e}", exc_info=True)
            return "failed"

    def _validate_improved_translation(self, original: str, improved: str) -> bool:
        """
        Validate improved translation.

        Checks:
        - Not empty
        - Different from original
        - Placeholder balance preserved
        - No obvious formatting corruption

        Args:
            original: Original translation
            improved: Improved translation

        Returns:
            True if valid, False otherwise
        """
        # Check if empty
        if not improved or not improved.strip():
            logger.debug("Validation failed: improved translation is empty")
            return False

        # Check if different from original
        if improved.strip() == original.strip():
            logger.debug("Validation failed: improved translation same as original")
            return False

        # Check placeholder balance
        # Look for common placeholder patterns: {0}, {name}, {{var}}, etc.
        placeholder_pattern = r"\{[\w\d_]*\}"
        original_placeholders = set(re.findall(placeholder_pattern, original))
        improved_placeholders = set(re.findall(placeholder_pattern, improved))

        if original_placeholders != improved_placeholders:
            logger.debug(
                f"Validation failed: placeholder mismatch. "
                f"Original: {original_placeholders}, Improved: {improved_placeholders}"
            )
            return False

        # Check for obvious formatting corruption
        # If original has markdown formatting, improved should too
        markdown_indicators = ["**", "*", "`", "#", "[", "]", "(", ")"]
        original_has_markdown = any(indicator in original for indicator in markdown_indicators)
        improved_has_markdown = any(indicator in improved for indicator in markdown_indicators)

        if original_has_markdown and not improved_has_markdown:
            logger.debug("Validation failed: markdown formatting lost in improvement")
            return False

        # All checks passed
        return True


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="TM Improvement Worker - LLM-based improvement of TM entries",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Oneshot mode - run once
  python -m src.workers.tm_improvement_worker --mode oneshot

  # Daemon mode - self-schedule 5 runs/day
  python -m src.workers.tm_improvement_worker --mode daemon --runs-per-day 5

  # Daemon mode with custom window
  python -m src.workers.tm_improvement_worker \\
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
        "--tm-path",
        type=str,
        default="data/tm",
        help="Path to TM data directory (default: data/tm)",
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

    # Batch configuration
    parser.add_argument(
        "--candidates-per-run",
        type=int,
        default=50,
        help="Maximum candidates to process per run (default: 50)",
    )

    parser.add_argument(
        "--max-llm-calls-per-run",
        type=int,
        default=200,
        help="Maximum LLM calls per run (default: 200)",
    )

    parser.add_argument(
        "--max-seconds-per-run",
        type=int,
        default=900,
        help="Maximum runtime per run in seconds (default: 900 = 15 minutes)",
    )

    # LLM configuration
    parser.add_argument(
        "--llm-provider",
        type=str,
        default="ollama",
        help="LLM provider: ollama, openai, anthropic (default: ollama)",
    )

    parser.add_argument(
        "--llm-model",
        type=str,
        default="llama2",
        help="LLM model name (default: llama2)",
    )

    parser.add_argument(
        "--llm-base-url",
        type=str,
        default="http://localhost:11434",
        help="LLM base URL for Ollama (default: http://localhost:11434)",
    )

    parser.add_argument(
        "--llm-api-key",
        type=str,
        default=None,
        help="LLM API key for cloud providers (default: None)",
    )

    # Safety and resource arguments
    parser.add_argument(
        "--max-gpu-memory-percent",
        type=int,
        default=60,
        help="Maximum GPU memory usage percentage (default: 60)",
    )

    parser.add_argument(
        "--no-preflight-check",
        action="store_true",
        help="Disable GPU usage preflight check",
    )

    parser.add_argument(
        "--no-abort-on-high-usage",
        action="store_true",
        help="Disable abort on high GPU usage",
    )

    parser.add_argument(
        "--device",
        type=str,
        default="auto",
        help="Device for LLM inference: cpu, cuda, or auto (default: auto)",
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
    """Main entry point for TM improvement worker."""
    # Parse arguments
    args = parse_args()

    # Setup logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logger.info("=" * 80)
    logger.info("TM IMPROVEMENT WORKER")
    logger.info("=" * 80)
    logger.info(f"Mode: {args.mode}")
    logger.info(f"Config root: {args.config_root}")
    logger.info(f"TM path: {args.tm_path}")
    logger.info(f"LLM: {args.llm_provider}/{args.llm_model}")
    logger.info(f"Device: {args.device}")

    if args.mode == "daemon":
        logger.info(f"Runs per day: {args.runs_per_day}")
        logger.info(f"Window: {args.window_start}-{args.window_end} {args.timezone}")

    logger.info("=" * 80)

    # Create worker configuration
    config = TMImprovementWorkerConfig(
        config_root=args.config_root,
        tm_path=args.tm_path,
        mode=args.mode,
        runs_per_day=args.runs_per_day,
        window_start=args.window_start,
        window_end=args.window_end,
        timezone=args.timezone,
        jitter_minutes=args.jitter_minutes,
        candidates_per_run=args.candidates_per_run,
        max_llm_calls_per_run=args.max_llm_calls_per_run,
        max_seconds_per_run=args.max_seconds_per_run,
        llm_provider=args.llm_provider,
        llm_model=args.llm_model,
        llm_base_url=args.llm_base_url,
        llm_api_key=args.llm_api_key,
        max_gpu_memory_percent=args.max_gpu_memory_percent,
        preflight_check=not args.no_preflight_check,
        abort_on_high_usage=not args.no_abort_on_high_usage,
        device=args.device,
    )

    # Create and run worker
    worker = TMImprovementWorker(config)
    worker.setup()
    worker.run()


if __name__ == "__main__":
    main()
