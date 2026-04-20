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
import json
import logging
import os
import platform
import re
import signal
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import torch

from src.hardware.gpu_manager import GPUManager
from src.hardware.vram_enforcer import VRAMEnforcer
from src.intelligence.llm_client import LLMClient, LLMConfig
from src.observability.worker_telemetry import (
    complete_worker_run,
    emit_worker_event,
    start_worker_run,
)
from src.tm import TranslationMemory
from src.tm.improvement_queue import ImprovementCandidate, ImprovementQueue
from src.tm.l1_cache import L1Cache
from src.tm.l2_persistent import L2PersistentTM
from src.utils.config_loader import ConfigService
from src.workers.window_scheduler import ScheduleConfig, WindowScheduler
from src.workers.worker_state import record_worker_state

try:
    from src.tm.l3_semantic import L3SemanticTM
except ImportError:
    L3SemanticTM = None

try:
    from src.observability.telemetry_integration import TranslationTelemetry
except ImportError:
    TranslationTelemetry = None

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
        llm_model: str = "qwen3:14b",
        llm_base_url: str | None = "http://localhost:11434",
        llm_api_key: str | None = None,
        llm_api_key_env: str | None = None,
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
        self.llm_api_key_env = llm_api_key_env
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
        config = config_service.get_config()

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
            llm_model=llm.get("model", "qwen3:14b"),
            llm_base_url=llm.get("base_url", "http://localhost:11434"),
            llm_api_key=llm.get("api_key"),
            llm_api_key_env=llm.get("api_key_env"),
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

    _worker_id = "tm_worker"
    _worker_log_path = "data/logs/tm_worker.log"

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
        self._llm_unavailable = False  # Track LLM availability state

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
            from src.tm.l2_persistent import L2_DB_NAME
            _raw_cfg = self.config_service.get_config() if self.config_service else {}
            _l2_max_mb = _raw_cfg.get("tm_defaults", {}).get("l2_max_size_mb", 1536)
            l2_store = L2PersistentTM(db_path=self.config.tm_path / L2_DB_NAME, max_size_mb=_l2_max_mb)

            # Create L3 semantic store (optional)
            l3_store = None
            if L3SemanticTM is not None:
                try:
                    l3_store = L3SemanticTM(
                        index_path=self.config.tm_path / "l3_faiss",
                        use_gpu=(self.config.device == "cuda"),
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

        # Initialize LLM client (with auto-discovery fallback)
        try:
            llm_config = LLMConfig(
                provider=self.config.llm_provider,
                model=self.config.llm_model,
                base_url=self.config.llm_base_url,
                api_key=self.config.llm_api_key,
                api_key_env=self.config.llm_api_key_env,
                timeout_seconds=self.config.llm_timeout_seconds,
                temperature=self.config.llm_temperature,
            )

            self.llm_client = LLMClient(llm_config)

            if not self.llm_client.is_available():
                if self.config.llm_provider == "ollama":
                    # Auto-discover an available model from Ollama
                    logger.warning(
                        f"Configured model '{self.config.llm_model}' not available. "
                        f"Attempting auto-discovery of available Ollama models..."
                    )
                    fallback_model = self._discover_available_model()
                    if fallback_model:
                        logger.info(f"Using discovered model: {fallback_model}")
                        llm_config = LLMConfig(
                            provider=self.config.llm_provider,
                            model=fallback_model,
                            base_url=self.config.llm_base_url,
                            api_key=self.config.llm_api_key,
                            api_key_env=self.config.llm_api_key_env,
                            timeout_seconds=self.config.llm_timeout_seconds,
                            temperature=self.config.llm_temperature,
                        )
                        self.llm_client = LLMClient(llm_config)
                else:
                    logger.warning(
                        f"Configured LLM provider '{self.config.llm_provider}' not available. "
                        "Skipping auto-discovery (only supported for Ollama)."
                    )

            if self.llm_client.is_available():
                logger.info(
                    f"Initialized LLM client: {self.config.llm_provider}/{self.llm_client.config.model}"
                )
                self._llm_unavailable = False
            else:
                logger.warning(
                    "LLM client is not available - TM worker will skip improvement runs. "
                    "Worker will remain alive and retry on next scheduled run."
                )
                self._llm_unavailable = True

        except Exception as e:
            logger.warning(
                f"Failed to initialize LLM client: {e}. "
                "Worker will continue and retry on next scheduled run."
            )
            self._llm_unavailable = True

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

        # Initialize telemetry (graceful degradation — never blocks worker)
        self.telemetry = None
        if TranslationTelemetry is not None:
            try:
                self.telemetry = TranslationTelemetry(
                    agent_name="tm_improvement_worker",
                    enabled=True,
                )
                logger.info(f"Telemetry initialized: available={self.telemetry.is_available()}")
            except Exception as e:
                logger.warning(f"Telemetry initialization failed (non-critical): {e}")
                self.telemetry = None
        else:
            logger.info("Telemetry not available (TranslationTelemetry not importable)")

        logger.info("Setup complete")

    def _discover_available_model(self) -> str | None:
        """Query Ollama for available models and return the first suitable one."""
        try:
            import requests
            base_url = self.config.llm_base_url or "http://localhost:11434"
            response = requests.get(f"{base_url}/api/tags", timeout=5)
            response.raise_for_status()
            models = response.json().get("models", [])
            model_names = [m.get("name", "") for m in models]
            logger.info(f"Available Ollama models: {model_names}")

            # Prefer models in this order
            preferred_prefixes = ["qwen", "llama", "mistral", "codellama"]
            for prefix in preferred_prefixes:
                for name in model_names:
                    if name.startswith(prefix):
                        return name

            # Return first available model if no preferred match
            if model_names:
                return model_names[0]

            return None
        except Exception as e:
            logger.warning(f"Model auto-discovery failed: {e}")
            return None

    def _write_pid_file(self):
        """Write PID file for watchdog monitoring."""
        pid_path = Path("data/logs") / f"{self._worker_id}.pid"
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text(str(os.getpid()))

    def _offload_resources(self) -> None:
        """Unload LLM from Ollama VRAM and offload L3 FAISS + encoder before sleeping.

        Python objects stay alive — only GPU weights are released.
        Everything reloads automatically on the next run.
        """
        # 1. Signal LLM provider to release the model (~8-10 GB freed for local providers)
        if self.llm_client is not None:
            try:
                self.llm_client.unload_from_server()
                logger.info(
                    "[VRAM] Signalled LLM provider (%s) to release model '%s'",
                    self.config.llm_provider,
                    self.config.llm_model,
                )
            except Exception as e:
                logger.warning("[VRAM] LLM provider unload signal failed: %s", e)

        # 2. Move L3 FAISS index + embedding encoder to CPU RAM
        try:
            l3 = getattr(self.tm, 'l3', None)
            if l3 is not None and hasattr(l3, 'offload_to_cpu'):
                l3.offload_to_cpu()
                logger.info("[VRAM] L3 FAISS index and encoder offloaded to CPU")
        except Exception as e:
            logger.warning("[VRAM] L3 offload failed: %s", e)

        # 3. Force CUDA cache flush
        try:
            import gc

            import torch
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

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

        # 1. GPU available (if device=cuda)
        if self.config.device == "cuda":
            try:
                import torch
                if not torch.cuda.is_available():
                    logger.warning("PREFLIGHT FAIL: CUDA requested but not available, skipping run")
                    checks_passed = False
            except ImportError:
                logger.warning("PREFLIGHT FAIL: torch not installed, cannot use CUDA")
                checks_passed = False

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

        # 4. Ollama reachable (TM worker specific)
        ollama_ok = True
        if hasattr(self.config, 'llm_provider') and self.config.llm_provider == "ollama":
            try:
                import urllib.request
                urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5)
            except Exception:
                logger.warning("PREFLIGHT FAIL: Ollama not reachable at localhost:11434")
                checks_passed = False
                ollama_ok = False

        # Emit preflight telemetry
        try:
            emit_worker_event(
                agent_name="tm_improvement_worker",
                job_type="worker_preflight",
                status="success" if checks_passed else "failure",
                metrics={
                    "gpu_check": self.config.device != "cuda" or checks_passed,
                    "config_root_exists": config_root.exists(),
                    "ollama_check": ollama_ok,
                    "device": self.config.device,
                },
            )
        except Exception:
            pass

        return checks_passed

    def run(self) -> None:
        """
        Run TM improvement worker.

        In oneshot mode: Executes one improvement run and exits
        In daemon mode: Continuously schedules and executes runs
        """
        self._write_pid_file()
        self._write_heartbeat("starting")
        self._record_state("starting")
        self._start_heartbeat_thread()
        self._lifecycle_event_id = start_worker_run(
            "tm_improvement_worker", "worker_lifecycle",
            context={
                "mode": self.config.mode,
                "llm_provider": getattr(self.config, "llm_provider", None),
                "llm_model": getattr(self.config, "llm_model", None),
                "runs_per_day": getattr(self.config, "runs_per_day", None),
            },
        )
        self._daemon_start_time = time.time()
        try:
            if self.config.mode == "oneshot":
                self._run_oneshot()
            elif self.config.mode == "daemon":
                self._run_daemon()
            else:
                raise ValueError(
                    f"Invalid mode: {self.config.mode}. Expected 'oneshot' or 'daemon'"
                )
        finally:
            self._stop_heartbeat_thread()
            self._write_heartbeat("stopped")
            self._record_state("stopped")

    def _run_oneshot(self) -> None:
        """Execute a single improvement run and exit."""
        logger.info("=" * 80)
        logger.info("ONESHOT MODE: Running single improvement pass")
        logger.info("=" * 80)

        if not self._preflight_check():
            logger.warning("Preflight check failed, aborting oneshot run")
            self._record_state("preflight_failed", error="Preflight checks failed")
            return  # Graceful exit, not sys.exit(1)

        try:
            result = self._execute_improvement_run_with_telemetry()

            if result["status"] == "success":
                logger.info(
                    f"Oneshot run completed: {result['improved_count']} improved, "
                    f"{result['skipped_count']} skipped, {result['failed_count']} failed"
                )
                self._record_state("run_completed", success=True)
            else:
                logger.warning(f"Oneshot run completed with status: {result['status']}")
                self._record_state("run_completed_non_success")

        except Exception as e:
            logger.error(f"Oneshot run failed: {e}", exc_info=True)
            self._record_state("run_failed", error=str(e))
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
        consecutive_failures = 0
        max_consecutive_failures = 10

        try:
            while True:
                # Release VRAM, then sleep until next run time
                self._offload_resources()
                self._write_heartbeat("sleeping")
                self._record_state("sleeping")
                next_run = self.scheduler.sleep_until_next_run()
                run_count += 1

                logger.info("=" * 80)
                logger.info(
                    f"SCHEDULED RUN #{run_count} at {next_run.strftime('%Y-%m-%d %H:%M:%S %Z')}"
                )
                logger.info("=" * 80)

                if not self._preflight_check():
                    logger.warning(f"Skipping run #{run_count} due to preflight failure")
                    self._write_heartbeat("skipped_preflight")
                    self._record_state("preflight_failed", error="Preflight checks failed")
                    continue

                try:
                    result = self._execute_improvement_run_with_telemetry()

                    if result["status"] == "success":
                        logger.info(
                            f"Run #{run_count} completed: {result['improved_count']} improved, "
                            f"{result['skipped_count']} skipped, {result['failed_count']} failed"
                        )
                        self._record_state("run_completed", success=True)
                    else:
                        logger.warning(f"Run #{run_count} status: {result['status']}")
                        self._record_state("run_completed_non_success")

                    consecutive_failures = 0

                except Exception as e:
                    consecutive_failures += 1
                    logger.error(
                        f"Run #{run_count} failed "
                        f"({consecutive_failures} consecutive): {e}",
                        exc_info=True,
                    )
                    emit_worker_event(
                        agent_name="tm_improvement_worker",
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

    def _check_gpu_usage(self) -> float | None:
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

    def _execute_improvement_run_with_telemetry(self) -> dict[str, Any]:
        """Execute improvement run wrapped in telemetry tracking."""
        if not (self.telemetry and self.telemetry.is_available()):
            return self._execute_improvement_run()

        with self.telemetry.client.track_run(
            agent_name="tm_improvement_worker",
            job_type="tm_improvement",
            trigger_type="scheduled",
        ) as ctx:
            result = self._execute_improvement_run()
            ctx.set_metrics(
                items_discovered=result.get("candidates_pulled", 0),
                items_succeeded=result.get("improved_count", 0),
                items_failed=result.get("failed_count", 0),
                metrics_json={
                    "llm_calls": result.get("llm_calls", 0),
                    "skipped_count": result.get("skipped_count", 0),
                    "elapsed_seconds": result.get("elapsed_seconds", 0),
                    "llm_provider": self.config.llm_provider,
                    "llm_model": self.config.llm_model,
                },
            )
            return result

    def _execute_improvement_run(self) -> dict[str, Any]:
        """
        Execute a single improvement run.

        Returns:
            Dictionary with run results
        """
        start_time = time.time()

        # Reload L3 FAISS index + encoder back to GPU after a sleep offload
        try:
            l3 = getattr(self.tm, 'l3', None)
            if l3 is not None and hasattr(l3, 'reload_to_gpu'):
                l3.reload_to_gpu()
        except Exception as e:
            logger.warning("[VRAM] L3 GPU reload failed (continuing on CPU): %s", e)

        # Check LLM availability before attempting work
        if self._llm_unavailable or not self.llm_client or not self.llm_client.is_available():
            logger.info("LLM unavailable - attempting to reconnect...")

            # Try to reconnect (maybe Ollama came back online)
            try:
                if self.llm_client:
                    # Re-initialize the client
                    if self.llm_client.reconnect():
                        logger.info("✓ LLM reconnected successfully!")
                        self._llm_unavailable = False
                    else:
                        raise RuntimeError("Still unavailable after reconnection attempt")
                else:
                    raise RuntimeError("LLM client not initialized")
            except Exception as e:
                logger.info(f"LLM still unavailable: {e}. Skipping improvement run.")
                return {
                    "status": "skipped",
                    "reason": "llm_unavailable",
                    "candidates_pulled": 0,
                    "improved_count": 0,
                    "skipped_count": 0,
                    "failed_count": 0,
                    "elapsed_seconds": time.time() - start_time,
                }

        # VRAM preflight check
        if self.config.preflight_check and self.config.abort_on_high_usage:
            gpu_usage = self._check_gpu_usage()
            if gpu_usage is not None and gpu_usage >= self.config.max_gpu_memory_percent:
                logger.warning(
                    f"PREFLIGHT CHECK FAILED: GPU usage ({gpu_usage:.1f}%) already at or above "
                    f"threshold ({self.config.max_gpu_memory_percent}%). Aborting run."
                )
                emit_worker_event(
                    agent_name="tm_improvement_worker",
                    job_type="worker_gpu_check",
                    status="failure",
                    metrics={"gpu_usage_percent": gpu_usage, "threshold": self.config.max_gpu_memory_percent, "phase": "pre_run"},
                    error_summary=f"GPU usage {gpu_usage:.1f}% exceeds threshold",
                )
                return {
                    "status": "aborted",
                    "reason": "gpu_usage_high",
                    "gpu_usage_percent": gpu_usage,
                }

        # Pop candidates from queue
        logger.info(f"Popping up to {self.config.candidates_per_run} candidates from queue...")
        candidates = self.improvement_queue.pop_candidates(limit=self.config.candidates_per_run)

        # Emit queue pull telemetry
        emit_worker_event(
            agent_name="tm_improvement_worker",
            job_type="worker_queue_pull",
            items_discovered=len(candidates),
            metrics={"requested": self.config.candidates_per_run},
        )

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
                        emit_worker_event(
                            agent_name="tm_improvement_worker",
                            job_type="worker_gpu_check",
                            status="failure",
                            metrics={"gpu_usage_percent": gpu_usage, "threshold": self.config.max_gpu_memory_percent, "phase": "post_call", "candidate_index": i},
                            error_summary=f"Post-call GPU usage {gpu_usage:.1f}% exceeds threshold",
                        )
                        break

            except Exception as e:
                logger.error(
                    f"Failed to process candidate {i + 1}/{len(candidates)}: {e}",
                    exc_info=True,
                )
                emit_worker_event(
                    agent_name="tm_improvement_worker",
                    job_type="worker_llm_failure",
                    status="failure",
                    error_summary=str(e)[:500],
                    metrics={"candidate_index": i, "site_id": getattr(candidate, "site_id", None)},
                )
                failed_count += 1

        elapsed = time.time() - start_time

        logger.info(
            f"Improvement run completed in {elapsed:.1f}s: "
            f"{improved_count} improved, {skipped_count} skipped, {failed_count} failed, "
            f"{llm_calls} LLM calls"
        )

        # Flush L3 FAISS index to disk before returning.
        # L2 LMDB persists on every store() call; L3 only persists on save_index().
        if self.tm is not None and self.tm.l3 is not None:
            logger.info("Flushing L3 semantic index to disk...")
            try:
                self.tm.l3.save_index()
                logger.info("L3 index flushed successfully")
            except Exception as e:
                logger.warning(f"L3 index flush failed (non-fatal): {e}")

        # WS-COMP-5: Nightly TM language validity scan — detect and optionally remove
        # L2 entries where the cached translation is in the wrong language.
        # Guarded: only runs if l2 is available and fasttext model exists.
        _lang_validity_results: dict = {}
        try:
            _l2 = getattr(self.tm, 'l2', None) if self.tm else None
            _ft_model_path = Path("data/models/fasttext/lid.176.bin")
            if _l2 is not None and _ft_model_path.exists():
                from ..tm.integrity import CacheIntegrityChecker
                _checker = CacheIntegrityChecker(_l2)
                # Get target languages from config (if available)
                _tm_langs: list[str] = []
                try:
                    _cfg_raw = self.config.get_config() if hasattr(self.config, 'get_config') else {}
                    _site_profiles_dir = Path(_cfg_raw.get('paths', {}).get('config_dir', 'config')) / 'site_profiles'
                    if _site_profiles_dir.exists():
                        import yaml as _yaml
                        for _p in _site_profiles_dir.glob("*.aspose.net.yaml"):
                            _sp = _yaml.safe_load(_p.read_text(encoding="utf-8"))
                            _tm_langs.extend(_sp.get("target_langs", []))
                        _tm_langs = list(set(_tm_langs))  # dedup
                except Exception:
                    pass
                if not _tm_langs:
                    _tm_langs = ["de", "fr", "es", "it", "pt", "nl", "ru", "ja", "zh", "ar"]
                # Scan each lang; repair=True with max 100 deletions/run (prevents mass deletion)
                for _lang in _tm_langs:
                    try:
                        _report = _checker.scan_language_validity(
                            tgt_lang=_lang,
                            fasttext_model_path=_ft_model_path,
                            sample_rate=0.05,
                            confidence_threshold=0.85,
                            repair=True,
                            max_deletions_per_run=100,
                            dry_run=False,
                        )
                        if _report.stale_found > 0:
                            logger.warning(
                                f"TM integrity scan [{_lang}]: "
                                f"{_report.stale_found}/{_report.total_sampled} sampled entries "
                                f"were wrong-language; deleted {_report.repaired_count}"
                            )
                            _lang_validity_results[_lang] = _report.to_dict()
                    except Exception as _e:
                        logger.debug(f"TM language validity scan failed for {_lang}: {_e}")
            else:
                logger.debug("TM language validity scan skipped: l2 unavailable or fasttext model missing")
        except Exception as _e:
            logger.warning(f"TM language validity scan error (non-fatal): {_e}")

        # T3-A: TM consistency check — gate-checked, non-blocking.
        # Scans L2 for phrases translated differently across sites and logs divergences.
        _consistency_result: dict = {}
        try:
            _l2_for_consistency = getattr(self.tm, 'l2', None) if self.tm else None
            if _l2_for_consistency is not None:
                from ..tm.consistency_warner import run_consistency_check
                _consistency_result = run_consistency_check(
                    _l2_for_consistency,
                    run_id=f"tm_improvement:{int(start_time)}",
                )
        except Exception as _cw_err:
            logger.debug("ConsistencyWarner wiring error (non-fatal): %s", _cw_err)

        return {
            "status": "success",
            "candidates_pulled": len(candidates),
            "improved_count": improved_count,
            "skipped_count": skipped_count,
            "failed_count": failed_count,
            "llm_calls": llm_calls,
            "elapsed_seconds": elapsed,
            "lang_validity_scan": _lang_validity_results,
            "consistency_check": _consistency_result,
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

            # Attempt in-place L3 metadata update first (avoids duplicate vectors).
            # The entry_id format matches translation_memory.py:218.
            l3_updated = False
            if self.tm is not None and self.tm.l3 is not None:
                entry_id = (
                    f"{candidate.site_id}:{candidate.src_lang}:"
                    f"{candidate.tgt_lang}:{hash(candidate.text)}"
                )
                l3_updated = self.tm.l3.update_entry(
                    entry_id=entry_id,
                    new_translation=improved_translation,
                    new_metadata=metadata,
                )
                if l3_updated:
                    logger.debug(
                        f"L3 in-place update: entry_id={entry_id[:60]}"
                    )

            # Always store to L2 (LMDB). If L3 was updated in-place, pass
            # skip_l3=True so tm.store() does not append a duplicate vector.
            stored = self.tm.store(
                site_id=candidate.site_id,
                src_lang=candidate.src_lang,
                tgt_lang=candidate.tgt_lang,
                text=candidate.text,
                translation=improved_translation,
                context=candidate.context,
                metadata=metadata,
                force_update=True,
                skip_l3=l3_updated,
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

    # LLM configuration — all default to None so main() can detect explicit CLI overrides
    parser.add_argument(
        "--llm-provider",
        type=str,
        default=None,
        help="LLM provider: ollama, openai, anthropic, openai_compatible (overrides config)",
    )

    parser.add_argument(
        "--llm-model",
        type=str,
        default=None,
        help="LLM model name (overrides config)",
    )

    parser.add_argument(
        "--llm-base-url",
        type=str,
        default=None,
        help="LLM base URL (overrides config)",
    )

    parser.add_argument(
        "--llm-api-key",
        type=str,
        default=None,
        help="LLM API key for cloud providers (overrides config)",
    )

    parser.add_argument(
        "--llm-api-key-env",
        type=str,
        default=None,
        help="Env var name holding the LLM API key (overrides config)",
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

    log_dir = Path("data/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "tm_worker.log"

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

    logger.info("=" * 80)
    logger.info("TM IMPROVEMENT WORKER")
    logger.info("=" * 80)
    logger.info(f"Mode: {args.mode}")
    logger.info(f"Config root: {args.config_root}")
    logger.info(f"TM path: {args.tm_path}")
    logger.info(f"LLM: {args.llm_provider or '(from config)'}/{args.llm_model or '(from config)'}")
    logger.info(f"Device: {args.device}")

    if args.mode == "daemon":
        logger.info(f"Runs per day: {args.runs_per_day}")
        logger.info(f"Window: {args.window_start}-{args.window_end} {args.timezone}")

    logger.info("=" * 80)

    # Load base config from global.yaml via ConfigService
    config_service = ConfigService(args.config_root)
    config = TMImprovementWorkerConfig.from_config_service(config_service, mode=args.mode)

    # Apply CLI arg overrides — only when explicitly provided (non-None)
    if args.tm_path != "data/tm":  # non-default value
        config.tm_path = Path(args.tm_path)
    if args.candidates_per_run != 50:
        config.candidates_per_run = args.candidates_per_run
    if args.max_llm_calls_per_run != 200:
        config.max_llm_calls_per_run = args.max_llm_calls_per_run
    if args.max_seconds_per_run != 900:
        config.max_seconds_per_run = args.max_seconds_per_run
    if args.llm_provider is not None:
        config.llm_provider = args.llm_provider
    if args.llm_model is not None:
        config.llm_model = args.llm_model
    if args.llm_base_url is not None:
        config.llm_base_url = args.llm_base_url
    if args.llm_api_key is not None:
        config.llm_api_key = args.llm_api_key
    if args.llm_api_key_env is not None:
        config.llm_api_key_env = args.llm_api_key_env
    if args.max_gpu_memory_percent != 60:
        config.max_gpu_memory_percent = args.max_gpu_memory_percent
    config.preflight_check = not args.no_preflight_check
    config.abort_on_high_usage = not args.no_abort_on_high_usage
    if args.device != "auto":
        config.device = args.device

    # Create and run worker
    worker = TMImprovementWorker(config)

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
