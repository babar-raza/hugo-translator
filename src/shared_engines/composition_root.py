"""
CompositionRoot - Central factory for creating SharedEngines from configuration.

Instantiates all 8 shared engines in correct dependency order and provides
unified access through a single SharedEngines container.
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.shared_engines.commit_engine import CommitEngine
from src.shared_engines.healing_engine import HealingEngine
from src.shared_engines.job_engine import JobEngine
from src.shared_engines.limiting_engine import LimitingEngine, ResourceLimits
from src.shared_engines.logging_engine import LoggingEngine
from src.shared_engines.profile_engine import ProfileEngine
from src.shared_engines.telemetry_engine import TelemetryEngine
from src.shared_engines.translation_backends import LLMBackend, MTBackend, TranslationBackend

logger = logging.getLogger(__name__)


@dataclass
class SharedEngines:
    """
    Container for all shared engines.

    Provides unified access to all 8 engines created by CompositionRoot.
    """

    profile: ProfileEngine
    logging: LoggingEngine
    telemetry: TelemetryEngine
    job: JobEngine
    commit: CommitEngine
    limiting: LimitingEngine
    healing: HealingEngine
    translation: TranslationBackend

    def __repr__(self) -> str:
        """String representation of SharedEngines."""
        return (
            f"SharedEngines("
            f"profile={self.profile.__class__.__name__}, "
            f"logging={self.logging.__class__.__name__}, "
            f"telemetry={self.telemetry.__class__.__name__}, "
            f"job={self.job.__class__.__name__}, "
            f"commit={self.commit.__class__.__name__}, "
            f"limiting={self.limiting.__class__.__name__}, "
            f"healing={self.healing.__class__.__name__}, "
            f"translation={self.translation.__class__.__name__}"
            f")"
        )


class CompositionRoot:
    """
    Central factory for creating SharedEngines from configuration.

    Instantiates all 8 engines in correct dependency order:
    1. ProfileEngine (config resolution)
    2. LoggingEngine (structured logging)
    3. TelemetryEngine (event tracking)
    4. JobEngine (job queue management)
    5. CommitEngine (git automation)
    6. LimitingEngine (resource constraints)
    7. HealingEngine (retry logic)
    8. TranslationBackend (translation execution)

    Example:
        # Create engines from config
        config = {
            "config_root": "config/",
            "log_level": "INFO",
            "log_file": Path("logs/translation.ndjson"),
            "job_backend": "memory",
            "translation_backend": "mt",
            "max_retries": 3
        }

        engines = CompositionRoot.create_from_config(config)

        # Use engines
        profile = engines.profile.get_profile("products.aspose.com")
        engines.logging.info("Translation started", site_id="products.aspose.com")
        engines.telemetry.track_translation_session("run_123", "products.aspose.com")
    """

    @staticmethod
    def _load_execution_mode_config(config_root: str) -> dict[str, Any]:
        """
        Load execution mode configuration from global.yaml.

        Implements 3-tier precedence:
        1. EXECUTION_MODE environment variable (highest)
        2. execution.modes.{mode} section from global.yaml (middle)
        3. Caller-provided config defaults (lowest)

        Args:
            config_root: Path to configuration directory

        Returns:
            Dictionary with execution mode defaults

        Example:
            mode_config = CompositionRoot._load_execution_mode_config("config/")
            # Returns: {"device": "cpu", "max_retries": 5, ...}
        """
        import yaml

        # Determine execution mode from environment (default: windows_cuda)
        execution_mode = os.getenv("EXECUTION_MODE", "windows_cuda")

        # Load global.yaml to get mode-specific defaults
        global_yaml_path = Path(config_root) / "global.yaml"
        mode_config = {}

        if global_yaml_path.exists():
            try:
                with open(global_yaml_path, encoding="utf-8") as f:
                    global_config = yaml.safe_load(f)

                # Extract execution mode defaults
                execution_section = global_config.get("execution", {})
                modes_section = execution_section.get("modes", {})
                mode_defaults = modes_section.get(execution_mode, {})

                if mode_defaults:
                    logger.info(
                        f"Loaded execution mode config for '{execution_mode}' from global.yaml: "
                        f"{mode_defaults}"
                    )
                    mode_config = mode_defaults
                else:
                    logger.warning(
                        f"No execution mode config found for '{execution_mode}' in global.yaml. "
                        f"Using defaults."
                    )

            except Exception as e:
                logger.warning(f"Failed to load execution mode config from global.yaml: {e}")

        return mode_config

    @staticmethod
    def _load_queue_config(config_root: str, caller_config: dict[str, Any]) -> dict[str, Any]:
        """
        Load queue configuration from global.yaml with 4-tier precedence.

        Precedence (highest to lowest):
        1. Environment variable QUEUE_BACKEND
        2. Execution mode default (queue_backend from mode config)
        3. Global queue.backend (from global.yaml)
        4. Caller-provided config
        5. Fallback backend (queue.fallback_backend)

        Args:
            config_root: Path to configuration directory
            caller_config: Configuration provided by caller

        Returns:
            Queue configuration dictionary

        Example:
            queue_config = CompositionRoot._load_queue_config("config/", {})
            # Returns: {
            #     "backend": "redis",
            #     "fallback_backend": "memory",
            #     "redis": {...},
            #     "memory": {...}
            # }
        """
        import yaml

        # Load global.yaml
        global_yaml_path = Path(config_root) / "global.yaml"
        queue_config = {
            "backend": "redis",  # Default
            "fallback_backend": "memory",  # Default
            "redis": {
                "host": "localhost",
                "port": 6379,
                "db": 0,
                "max_retries": 3,
                "retry_delay": 1.0,
                "health_check_interval": 60
            },
            "memory": {
                "max_queue_size": 1000
            }
        }

        if global_yaml_path.exists():
            try:
                with open(global_yaml_path, encoding="utf-8") as f:
                    global_config = yaml.safe_load(f)

                # Extract queue section
                queue_section = global_config.get("queue", {})

                if queue_section:
                    # Update defaults with global.yaml values
                    if "backend" in queue_section:
                        queue_config["backend"] = queue_section["backend"]

                    if "fallback_backend" in queue_section:
                        queue_config["fallback_backend"] = queue_section["fallback_backend"]

                    if "redis" in queue_section:
                        queue_config["redis"].update(queue_section["redis"])

                    if "memory" in queue_section:
                        queue_config["memory"].update(queue_section["memory"])

                    logger.info(
                        f"Loaded queue config from global.yaml: "
                        f"backend={queue_config['backend']}, "
                        f"fallback={queue_config['fallback_backend']}"
                    )

            except Exception as e:
                logger.warning(f"Failed to load queue config from global.yaml: {e}")

        # Tier 2: Execution mode default
        execution_mode = os.getenv("EXECUTION_MODE", "windows_cuda")
        mode_config = CompositionRoot._load_execution_mode_config(config_root)
        if "queue_backend" in mode_config:
            queue_config["primary_backend_from_mode"] = mode_config["queue_backend"]
            logger.info(
                f"Queue backend from execution mode '{execution_mode}': "
                f"{mode_config['queue_backend']}"
            )

        # Tier 1: Environment variable (highest priority)
        env_backend = os.getenv("QUEUE_BACKEND")
        if env_backend:
            queue_config["backend"] = env_backend
            logger.info(f"Queue backend from QUEUE_BACKEND env var: {env_backend}")

        # Merge with caller config (caller config takes precedence)
        if caller_config:
            # Legacy support: job_backend -> backend
            if "job_backend" in caller_config and "backend" not in caller_config:
                queue_config["backend"] = caller_config["job_backend"]

            # Legacy support: redis_host, redis_port -> redis dict
            if "redis_host" in caller_config or "redis_port" in caller_config:
                if "redis_host" in caller_config:
                    queue_config["redis"]["host"] = caller_config["redis_host"]
                if "redis_port" in caller_config:
                    queue_config["redis"]["port"] = caller_config["redis_port"]

            # Direct config overrides
            for key in ["backend", "fallback_backend", "redis", "memory"]:
                if key in caller_config:
                    if isinstance(caller_config[key], dict) and isinstance(queue_config.get(key), dict):
                        queue_config[key].update(caller_config[key])
                    else:
                        queue_config[key] = caller_config[key]

        return queue_config

    @staticmethod
    def create_from_config(config: dict[str, Any] | None = None) -> SharedEngines:
        """
        Create all shared engines from configuration.

        Args:
            config: Optional configuration dictionary with keys:
                - config_root: Path to config directory (default: "config")
                - log_level: Logging level (default: "INFO")
                - log_file: Optional log file path
                - console_output: Console logging (default: True)
                - telemetry_enabled: Enable telemetry (default: True)
                - job_backend: "memory" or "redis" (default: "memory")
                - redis_host: Redis host if using redis backend
                - redis_port: Redis port if using redis backend
                - commit_enabled: Enable git commits (default: True)
                - max_retries: Maximum retry attempts (default: 3)
                - max_gpu_memory_mb: GPU memory limit
                - translation_backend: "mt" or "llm" (default: "mt")
                - execution_mode: "windows_cuda", "docker_cpu", or "docker_gpu"
                  (default: from EXECUTION_MODE env var or "windows_cuda")

        Returns:
            SharedEngines with all 8 engines initialized

        Example:
            config = {
                "config_root": "config/",
                "log_level": "DEBUG",
                "job_backend": "redis",
                "redis_host": "localhost",
                "max_retries": 5
            }
            engines = CompositionRoot.create_from_config(config)
        """
        cfg = config or {}

        logger.info("Creating SharedEngines from configuration")

        # PHASE 2: Load execution mode configuration from global.yaml
        # This implements 3-tier precedence:
        # 1. Environment variables (highest - handled by caller)
        # 2. Execution mode defaults from global.yaml (middle)
        # 3. Provided config dictionary (lowest)
        config_root = cfg.get("config_root", "config")
        mode_config = CompositionRoot._load_execution_mode_config(config_root)

        # Merge mode config with provided config (provided config takes precedence)
        merged_cfg = {**mode_config, **cfg}
        cfg = merged_cfg

        # Log execution mode if present
        execution_mode = os.getenv("EXECUTION_MODE")
        if execution_mode:
            logger.info(f"Execution mode: {execution_mode}")

        # 1. ProfileEngine - Configuration resolution
        config_root = cfg.get("config_root", "config")
        profile_engine = ProfileEngine(config_root=config_root)
        logger.debug(f"Created ProfileEngine: config_root={config_root}")

        # 2. LoggingEngine - Structured logging
        print("DEBUG: About to create LoggingEngine", flush=True)
        log_level = cfg.get("log_level", "INFO")
        log_file = cfg.get("log_file")
        console_output = cfg.get("console_output", True)
        print(f"DEBUG: LoggingEngine config - level={log_level}, file={log_file}, console={console_output}", flush=True)
        logging_engine = LoggingEngine(
            name="translation_system",
            log_level=log_level,
            log_file=log_file,
            console_output=console_output
        )
        print("DEBUG: LoggingEngine created successfully", flush=True)
        logger.debug(f"Created LoggingEngine: level={log_level}, file={log_file}")

        # 3. TelemetryEngine - Event tracking
        telemetry_enabled = cfg.get("telemetry_enabled", True)
        telemetry_config = {"enabled": telemetry_enabled}
        telemetry_engine = TelemetryEngine(config=telemetry_config)
        logger.debug(f"Created TelemetryEngine: enabled={telemetry_enabled}")

        # 4. JobEngine - Job queue management (V2 with backend switching)
        # Load queue configuration from global.yaml
        job_config = CompositionRoot._load_queue_config(config_root, cfg)
        # Add telemetry to queue config for event emission
        job_config["telemetry"] = telemetry_engine
        job_engine = JobEngine(config=job_config)
        logger.debug(
            f"Created JobEngine: backend={job_config.get('backend', 'memory')}, "
            f"failover_enabled={job_config.get('fallback_backend') is not None}"
        )

        # 5. CommitEngine - Git automation
        commit_enabled = cfg.get("commit_enabled", True)
        commit_auto_push = cfg.get("commit_auto_push", True)
        from src.observability.git_commit import GitCommitConfig
        commit_config = GitCommitConfig(
            enabled=commit_enabled,
            auto_push=commit_auto_push
        )
        commit_engine = CommitEngine(config=commit_config)
        logger.debug(f"Created CommitEngine: enabled={commit_enabled}")

        # 6. LimitingEngine - Resource constraints
        resource_limits = ResourceLimits(
            max_cpu_percent=cfg.get("max_cpu_percent"),
            min_memory_mb=cfg.get("min_memory_mb"),
            max_gpu_memory_percent=cfg.get("max_gpu_memory_percent"),
            max_gpu_memory_mb=cfg.get("max_gpu_memory_mb"),
            enable_gpu=cfg.get("enable_gpu", True)
        )
        limiting_engine = LimitingEngine(limits=resource_limits)
        logger.debug(
            f"Created LimitingEngine: gpu_percent={resource_limits.max_gpu_memory_percent}%, "
            f"gpu_limit={resource_limits.max_gpu_memory_mb}MB"
        )

        # 7. HealingEngine - Retry and recovery
        max_retries = cfg.get("max_retries", 3)
        batch_reduction_factor = cfg.get("batch_reduction_factor", 0.5)
        min_batch_size = cfg.get("min_batch_size", 1)
        healing_engine = HealingEngine(
            max_retries=max_retries,
            batch_reduction_factor=batch_reduction_factor,
            min_batch_size=min_batch_size
        )
        logger.debug(f"Created HealingEngine: max_retries={max_retries}")

        # 8. TranslationBackend - Translation execution
        translation_backend = cfg.get("translation_backend", "mt")
        if translation_backend == "mt":
            backend = MTBackend(
                model_id=cfg.get("model_id", "m2m100_418m"),
                device=cfg.get("device", "auto")
            )
        elif translation_backend == "llm":
            backend = LLMBackend(
                model_id=cfg.get("model_id", "gpt-4"),
                api_key=cfg.get("api_key")
            )
        else:
            raise ValueError(
                f"Invalid translation_backend: {translation_backend}. "
                f"Expected 'mt' or 'llm'"
            )
        logger.debug(f"Created TranslationBackend: type={translation_backend}")

        engines = SharedEngines(
            profile=profile_engine,
            logging=logging_engine,
            telemetry=telemetry_engine,
            job=job_engine,
            commit=commit_engine,
            limiting=limiting_engine,
            healing=healing_engine,
            translation=backend
        )

        logger.info("SharedEngines created successfully")
        return engines

    @staticmethod
    def create_default() -> SharedEngines:
        """
        Create SharedEngines with default configuration.

        Returns:
            SharedEngines with all defaults

        Example:
            engines = CompositionRoot.create_default()
        """
        return CompositionRoot.create_from_config({})

    @staticmethod
    def create_for_testing(
        mock_translation: bool = True,
        memory_job_backend: bool = True
    ) -> SharedEngines:
        """
        Create SharedEngines optimized for testing.

        Args:
            mock_translation: Use mock translation backend (default: True)
            memory_job_backend: Use memory job backend (default: True)

        Returns:
            SharedEngines configured for testing

        Example:
            engines = CompositionRoot.create_for_testing()
        """
        config = {
            "log_level": "DEBUG",
            "console_output": False,  # Quiet during tests
            "telemetry_enabled": False,  # Disable telemetry in tests
            "job_backend": "memory" if memory_job_backend else "redis",
            "commit_enabled": False,  # Don't commit during tests
            "translation_backend": "mt"  # Use MT for tests
        }
        return CompositionRoot.create_from_config(config)
