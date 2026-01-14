"""
CompositionRoot - Central factory for creating SharedEngines from configuration.

Instantiates all 8 shared engines in correct dependency order and provides
unified access through a single SharedEngines container.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any

from src.shared_engines.profile_engine import ProfileEngine
from src.shared_engines.logging_engine import LoggingEngine
from src.shared_engines.telemetry_engine import TelemetryEngine
from src.shared_engines.job_engine import JobEngine
from src.shared_engines.commit_engine import CommitEngine
from src.shared_engines.limiting_engine import LimitingEngine, ResourceLimits
from src.shared_engines.healing_engine import HealingEngine
from src.shared_engines.translation_backends import TranslationBackend, MTBackend, LLMBackend

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
    def create_from_config(config: Optional[Dict[str, Any]] = None) -> SharedEngines:
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

        # 1. ProfileEngine - Configuration resolution
        config_root = cfg.get("config_root", "config")
        profile_engine = ProfileEngine(config_root=config_root)
        logger.debug(f"Created ProfileEngine: config_root={config_root}")

        # 2. LoggingEngine - Structured logging
        log_level = cfg.get("log_level", "INFO")
        log_file = cfg.get("log_file")
        console_output = cfg.get("console_output", True)
        logging_engine = LoggingEngine(
            name="translation_system",
            log_level=log_level,
            log_file=log_file,
            console_output=console_output
        )
        logger.debug(f"Created LoggingEngine: level={log_level}, file={log_file}")

        # 3. TelemetryEngine - Event tracking
        telemetry_enabled = cfg.get("telemetry_enabled", True)
        telemetry_config = {"enabled": telemetry_enabled}
        telemetry_engine = TelemetryEngine(config=telemetry_config)
        logger.debug(f"Created TelemetryEngine: enabled={telemetry_enabled}")

        # 4. JobEngine - Job queue management
        job_backend = cfg.get("job_backend", "memory")
        job_config = {}
        if job_backend == "redis":
            job_config["redis_host"] = cfg.get("redis_host", "localhost")
            job_config["redis_port"] = cfg.get("redis_port", 6379)
        job_engine = JobEngine(backend=job_backend, config=job_config)
        logger.debug(f"Created JobEngine: backend={job_backend}")

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
            max_gpu_memory_mb=cfg.get("max_gpu_memory_mb"),
            enable_gpu=cfg.get("enable_gpu", True)
        )
        limiting_engine = LimitingEngine(limits=resource_limits)
        logger.debug(f"Created LimitingEngine: gpu_limit={resource_limits.max_gpu_memory_mb}MB")

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
