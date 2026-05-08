"""
Command-line interface for Hugo Translation System.

Provides CLI flags for:
- Validation control (mode, enable/disable, config paths)
- Terminology control (enable/disable, modes, config paths)
- Retry behavior (max retries)
- Output control (dry-run, save-rejected)

CLI flags override configuration file settings.

Note: Heavy ML dependencies (torch, transformers) are lazily imported to allow
--help to work without the full ML stack installed. See _import_heavy_deps().
"""
import argparse
import atexit
import importlib.metadata
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

# TYPE_CHECKING guard: These imports are only used for type hints
# and won't be executed at runtime, allowing --help to work without torch
if TYPE_CHECKING:
    from .translation_engine import TranslationEngine
    from .utils.config_loader import ConfigService

logger = logging.getLogger(__name__)

# Module-level cache for lazy-loaded heavy dependencies
_heavy_deps_loaded = False
_heavy_deps_cache = {}


def _import_heavy_deps():
    """
    Lazily import heavy ML dependencies when actually needed.

    This allows --help to work without torch/transformers installed.
    Imports are cached after first successful load.

    Returns:
        dict: Dictionary containing all heavy dependency modules/classes

    Raises:
        ImportError: If required dependencies are not installed
    """
    global _heavy_deps_loaded, _heavy_deps_cache

    if _heavy_deps_loaded:
        return _heavy_deps_cache

    try:
        # Try relative imports first (when used as package)
        from .model_runtime import ModelLoader
        from .model_runtime.cpu_optimizer import CPUOptimizer
        from .model_runtime.gpu_optimizer import GPUOptimizer
        from .model_runtime.registry import ModelRegistry
        from .tm import TranslationMemory
        from .tm.l1_cache import L1Cache
        from .tm.l2_persistent import L2PersistentTM
        from .tm.l3_semantic import L3SemanticTM
        from .translation_engine import TranslationEngine
        from .translation_engine.models import DirectoryResult, TranslationResult
        from .translation_engine.progress import ProgressTracker
        from .utils.config_loader import ConfigService
        from .utils.file_filters import filter_source_files
        from .utils.models import TerminologySettings, ValidationSettings
        from .verification.report import write_report
    except ImportError:
        # Try absolute imports (when run directly)
        try:
            from model_runtime import ModelLoader
            from model_runtime.cpu_optimizer import CPUOptimizer
            from model_runtime.gpu_optimizer import GPUOptimizer
            from model_runtime.registry import ModelRegistry
            from tm import TranslationMemory
            from tm.l1_cache import L1Cache
            from tm.l2_persistent import L2PersistentTM
            from tm.l3_semantic import L3SemanticTM
            from translation_engine import TranslationEngine
            from translation_engine.models import DirectoryResult, TranslationResult
            from translation_engine.progress import ProgressTracker
            from utils.config_loader import ConfigService
            from utils.file_filters import filter_source_files
            from utils.models import TerminologySettings, ValidationSettings
            from verification.report import write_report
        except ImportError as e:
            # Provide helpful error message about missing dependencies
            error_msg = str(e)
            if 'torch' in error_msg.lower() or "No module named 'torch'" in error_msg:
                raise ImportError(
                    "PyTorch is required for translation but not installed. "
                    "Install with: pip install torch or "
                    "install all ML dependencies: pip install -r requirements.txt"
                ) from e
            elif 'transformers' in error_msg.lower():
                raise ImportError(
                    "HuggingFace Transformers is required for translation but not installed. "
                    "Install with: pip install transformers or "
                    "install all ML dependencies: pip install -r requirements.txt"
                ) from e
            else:
                raise

    # Cache all imports
    _heavy_deps_cache = {
        'TranslationEngine': TranslationEngine,
        'TranslationResult': TranslationResult,
        'DirectoryResult': DirectoryResult,
        'ProgressTracker': ProgressTracker,
        'TranslationMemory': TranslationMemory,
        'L1Cache': L1Cache,
        'L2PersistentTM': L2PersistentTM,
        'L3SemanticTM': L3SemanticTM,
        'ModelLoader': ModelLoader,
        'ModelRegistry': ModelRegistry,
        'CPUOptimizer': CPUOptimizer,
        'GPUOptimizer': GPUOptimizer,
        'ConfigService': ConfigService,
        'filter_source_files': filter_source_files,
        'ValidationSettings': ValidationSettings,
        'TerminologySettings': TerminologySettings,
        'write_report': write_report,
    }
    _heavy_deps_loaded = True
    return _heavy_deps_cache



logger = logging.getLogger(__name__)

# TC1: Global lock tracker for signal handlers (Lock Contention Fix)
_parent_lock = None


def _signal_handler(signum, frame):
    """Release lock on SIGINT/SIGTERM."""
    global _parent_lock
    if _parent_lock:
        logger.info(f"Received signal {signum}, releasing lock...")
        _parent_lock.release()
        _parent_lock = None
    sys.exit(1)


class CLIConfigOverrides:
    """Container for CLI-provided configuration overrides."""

    def __init__(self, args: argparse.Namespace):
        """Initialize from parsed CLI arguments."""
        self.validation_mode: str | None = args.validation_mode
        self.disable_validation: bool = args.disable_validation
        self.force_accept: bool = args.force_accept
        self.strict_reject: bool = args.strict_reject
        self.enable_terminology: bool | None = (
            True if args.enable_terminology else (False if args.disable_terminology else None)
        )
        self.terminology_mode: str | None = args.terminology_mode
        self.max_retries: int | None = args.max_retries
        self.validation_config_path: str | None = args.validation_config
        self.terminology_config_path: str | None = args.terminology_config
        self.dry_run: bool = args.dry_run
        self.save_rejected: bool = args.save_rejected
        # VA-03: Post-translation verification flags
        self.verify: bool = args.verify
        self.fix: bool = args.fix
        # VA-04: Verification report output
        self.verification_report: str | None = args.verification_report
        # TR-01: Token limit configurability
        self.max_tokens: int | None = args.max_tokens
        # Model override
        self.model: str | None = args.model
        # TC-CPU-02: Batch size override
        self.batch_size: int | None = args.batch_size
        # SR-02: Segment sorting control
        self.sort_segments_by_length: bool | None = args.sort_segments_by_length
        # Device and load mode overrides (federated-splashing-panda: T101)
        self.device: str | None = None if args.device == "auto" else args.device
        self.load_mode: str | None = None if args.load_mode == "auto" else args.load_mode
        # Cache behavior control (federated-splashing-panda: Phase 2 redesign)
        self.force_retranslate: bool = args.force_retranslate
        self.cache_write_mode: str = args.cache_write_mode
        # Multi-language processing (T301: federated-splashing-panda)
        self.parallel_languages: int = args.parallel_languages
        self.global_lang_rounds: int = args.global_lang_rounds
        self.global_lang_sort: str = args.global_lang_sort
        # Progress and metrics control
        self.metrics_file: str | None = args.metrics_file
        self.metrics_interval: float = args.metrics_interval
        self.metrics_only: bool = args.metrics_only
        self.no_progress: bool = args.no_progress
        # RES-02: Resume/restart control
        self.resume: bool = args.resume
        self.force_restart: bool = args.force_restart
        self.progress_dir: str = args.progress_dir
        # Git diff change detection
        self.changed_since: str | None = getattr(args, 'changed_since', None)
        # Content hash tracking
        self.disable_content_hash: bool = args.disable_content_hash
        self.rebuild_content_hashes: bool = args.rebuild_content_hashes
        self.validate_output_integrity: bool = args.validate_output_integrity

    def apply_to_config_service(self, config_service: "ConfigService") -> None:
        """
        Apply CLI overrides to configuration service.

        Args:
            config_service: Configuration service to modify
        """
        # Override validation config path if specified
        if self.validation_config_path:
            config_service.validation_config_path = Path(self.validation_config_path)

        # Override terminology config path if specified
        if self.terminology_config_path:
            config_service.terminology_config_path = Path(self.terminology_config_path)

    def get_engine_overrides(self) -> dict[str, any]:
        """
        Get dictionary of overrides for TranslationEngine initialization.

        Returns:
            Dictionary of keyword arguments to pass to TranslationEngine
        """
        overrides = {}

        # Validation control
        # force-accept disables validation completely
        if self.force_accept:
            overrides["enable_validation"] = False
        elif self.disable_validation:
            overrides["enable_validation"] = False
        elif self.validation_mode == "off":
            overrides["enable_validation"] = False
        else:
            overrides["enable_validation"] = True

        # Validation mode
        if self.validation_mode and self.validation_mode != "off":
            overrides["validation_mode"] = self.validation_mode

        # strict-reject sets validation mode to strict and max retries to 0
        if self.strict_reject:
            overrides["validation_mode"] = "strict"
            overrides["max_retries"] = 0

        # Terminology control
        if self.enable_terminology is not None:
            overrides["enable_terminology"] = self.enable_terminology

        if self.terminology_mode:
            overrides["terminology_mode"] = self.terminology_mode

        # Retry control (unless overridden by strict-reject)
        if self.max_retries is not None and not self.strict_reject:
            overrides["max_retries"] = self.max_retries

        # Dry run and save rejected
        overrides["dry_run"] = self.dry_run
        overrides["save_rejected"] = self.save_rejected

        # VA-03: Post-translation verification
        overrides["enable_verification"] = self.verify
        overrides["enable_verification_fix"] = self.fix

        # TR-01: Token limit configurability
        if self.max_tokens is not None:
            overrides["max_tokens"] = self.max_tokens

        # Model override
        if self.model is not None:
            overrides["model_id"] = self.model

        # TC-CPU-02: Batch size override
        if self.batch_size is not None:
            overrides["batch_size"] = self.batch_size

        # SR-02: Segment sorting control
        if self.sort_segments_by_length is not None:
            overrides["sort_segments_by_length"] = self.sort_segments_by_length

        # Cache behavior control (federated-splashing-panda: Phase 2 redesign)
        overrides["force_retranslate"] = self.force_retranslate
        if self.cache_write_mode != "auto":
            overrides["cache_write_mode"] = self.cache_write_mode

        # Multi-language processing (T301: federated-splashing-panda)
        # Mutual exclusion validation: cannot use both parallel and round-robin
        if self.parallel_languages > 0 and self.global_lang_rounds > 0:
            raise ValueError(
                "Cannot use both --parallel-languages and --global-lang-rounds simultaneously. "
                "Choose either parallel processing or round-robin, not both."
            )

        if self.parallel_languages > 0:
            overrides["parallel_languages"] = self.parallel_languages

        if self.global_lang_rounds > 0:
            overrides["global_lang_rounds"] = self.global_lang_rounds
            overrides["global_lang_sort"] = self.global_lang_sort

        # Content hash tracking control (CHT-04)
        overrides["enable_content_hash_tracking"] = not self.disable_content_hash

        # Git diff change detection (--changed-since)
        if self.changed_since:
            overrides["changed_since_sha"] = self.changed_since

        # Note: rebuild_content_hashes is handled in main() before engine creation
        # Note: validate_output_integrity would be passed to engine if implemented

        return overrides


# CLI-TC-03: Custom action for mutually exclusive multi-language mode flags
class _MultiLangModeAction(argparse.Action):
    """
    Custom argparse action for --parallel-languages and --global-lang-rounds.

    Enforces mutual exclusion at parse time: if one flag is provided with a
    non-zero value, the other cannot be provided with a non-zero value.

    This is superior to runtime validation because:
    1. Error appears immediately when parsing command
    2. argparse provides consistent error formatting
    3. User gets feedback before any processing begins
    """

    def __call__(self, parser, namespace, values, option_string=None):
        # Convert to int (argparse type=int already handles this, but be safe)
        value = int(values) if values is not None else 0

        # Determine which flag this is and which is the conflicting one
        if option_string in ('--parallel-languages',):
            this_flag = '--parallel-languages'
            other_flag = '--global-lang-rounds'
            other_attr = 'global_lang_rounds'
        else:
            this_flag = '--global-lang-rounds'
            other_flag = '--parallel-languages'
            other_attr = 'parallel_languages'

        # Check if conflicting flag was already set to non-zero
        other_value = getattr(namespace, other_attr, 0)
        if value > 0 and other_value > 0:
            parser.error(
                f"argument {this_flag}: not allowed with argument {other_flag}: "
                f"cannot use both {this_flag} and {other_flag} simultaneously. "
                f"Choose either parallel processing or round-robin, not both."
            )

        # Store the value
        setattr(namespace, self.dest, value)


def get_version() -> str:
    """
    Get the package version from installed metadata.

    Returns:
        Version string from pyproject.toml if installed, otherwise "0.1.0-dev"
    """
    try:
        return importlib.metadata.version("hugo-translation-system")
    except importlib.metadata.PackageNotFoundError:
        return "0.1.0-dev"


def create_parser() -> argparse.ArgumentParser:
    """
    Create CLI argument parser with all flags.

    Returns:
        Configured ArgumentParser instance
    """
    parser = argparse.ArgumentParser(
        prog="translate-hugo",
        description="Hugo Translation System - Multi-site translation with semantic TM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Translate with strict validation
  translate-hugo --site products.aspose.net --validation-mode strict

  # Disable validation for quick testing
  translate-hugo --site products.aspose.net --disable-validation

  # Accept all translations without validation
  translate-hugo --site products.aspose.net --force-accept

  # Reject on any validation issue (fail fast)
  translate-hugo --site products.aspose.net --strict-reject

  # Use custom validation config
  translate-hugo --site products.aspose.net --validation-config ./custom-validation.yaml

  # Enable terminology with validation mode
  translate-hugo --site products.aspose.net --enable-terminology --terminology-mode both

  # Preview decisions without writing files
  translate-hugo --site products.aspose.net --dry-run

  # Save rejected translations for debugging
  translate-hugo --site products.aspose.net --save-rejected

  # Increase retry attempts
  translate-hugo --site products.aspose.net --max-retries 5

  # Override token limit for longer translations
  translate-hugo --site products.aspose.net --max-tokens 1024
        """,
    )

    # Version flag
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {get_version()}",
        help="Show program version and exit",
    )

    # Required arguments
    parser.add_argument(
        "--site",
        required=True,
        help="Site ID to translate (e.g., products.aspose.net)",
    )

    parser.add_argument(
        "--input",
        required=False,
        help="Input file or directory to translate (defaults to site content_roots)",
    )

    parser.add_argument(
        "--target-langs",
        nargs="+",
        help="Target languages (overrides site profile)",
    )

    # Hidden flag to prevent infinite recursion in multi-language subprocess mode
    parser.add_argument(
        "--_single-lang-mode",
        dest="_single_lang_mode",
        action="store_true",
        help=argparse.SUPPRESS,  # Hidden from help text
    )

    # Hidden flag for parent-held lock pattern (TC1: Lock Contention Fix)
    parser.add_argument(
        "--_skip-site-lock",
        dest="_skip_site_lock",
        action="store_true",
        help=argparse.SUPPRESS,  # Hidden from help text
    )

    # Validation mode control
    validation_group = parser.add_argument_group("Validation Control")

    validation_group.add_argument(
        "--validation-mode",
        choices=["strict", "normal", "lenient", "off"],
        help="Validation strictness level (overrides config)",
    )

    validation_group.add_argument(
        "--disable-validation",
        action="store_true",
        help="Quick disable of all validation (same as --validation-mode off)",
    )

    validation_group.add_argument(
        "--force-accept",
        action="store_true",
        help="Accept all translations without validation (ignore all validation errors)",
    )

    validation_group.add_argument(
        "--strict-reject",
        action="store_true",
        help="Reject translations on any validation issue (no retries, fail fast)",
    )

    validation_group.add_argument(
        "--validation-config",
        metavar="PATH",
        help="Path to custom validation.yaml config file",
    )

    validation_group.add_argument(
        "--max-retries",
        type=int,
        metavar="N",
        help="Override maximum retry attempts (0-5)",
    )

    # Model control (TR-01: Token limit configurability)
    model_group = parser.add_argument_group("Model Control")

    model_group.add_argument(
        "--model",
        type=str,
        metavar="MODEL_ID",
        help="Override translation model (e.g., m2m100_1.2b, nllb_200_600m)",
    )

    model_group.add_argument(
        "--max-tokens",
        type=int,
        metavar="N",
        help="Override maximum new tokens for translation model (default: 512)",
    )

    model_group.add_argument(
        "--batch-size",
        type=int,
        metavar="N",
        help="Override batch size for translation (default: auto-detected based on RAM)",
    )

    model_group.add_argument(
        "--sort-segments-by-length",
        action="store_true",
        default=None,
        dest="sort_segments_by_length",
        help="Sort segments by length (shortest first) before translation for improved GPU batching efficiency",
    )

    model_group.add_argument(
        "--no-sort-segments-by-length",
        action="store_false",
        dest="sort_segments_by_length",
        help="Disable segment sorting (process in document order)",
    )

    model_group.add_argument(
        "--auto-select-model",
        action="store_true",
        help="Automatically select best model for each target language (uses Opus when available, falls back to multilingual). Mutually exclusive with --model.",
    )

    model_group.add_argument(
        "--device",
        type=str,
        choices=["auto", "cpu", "cuda"],
        default="auto",
        metavar="DEVICE",
        help="Device for model inference: auto (default), cpu, or cuda",
    )

    model_group.add_argument(
        "--load-mode",
        type=str,
        choices=["auto", "fp16", "fp32", "int8"],
        default="auto",
        metavar="MODE",
        help="Model precision/quantization mode: auto (default), fp16, fp32, or int8",
    )

    # Post-translation verification control (VA-03)
    verification_group = parser.add_argument_group("Post-Translation Verification (VA-03)")

    verification_group.add_argument(
        "--verify",
        action="store_true",
        help="Enable post-translation verification (detects mixed-language, untranslated segments)",
    )

    verification_group.add_argument(
        "--fix",
        action="store_true",
        help="Automatically retry failed verification (requires --verify)",
    )

    verification_group.add_argument(
        "--verification-report",
        metavar="PATH",
        help="Output verification report to file (JSON or Markdown based on extension: .json or .md)",
    )

    # Terminology control
    terminology_group = parser.add_argument_group("Terminology Control")

    terminology_group.add_argument(
        "--enable-terminology",
        action="store_true",
        help="Enable terminology preservation/validation",
    )

    terminology_group.add_argument(
        "--disable-terminology",
        action="store_true",
        help="Disable terminology preservation/validation",
    )

    terminology_group.add_argument(
        "--terminology-mode",
        choices=["protect", "validate", "both", "none"],
        help="Terminology preservation mode (overrides config)",
    )

    terminology_group.add_argument(
        "--terminology-config",
        metavar="PATH",
        help="Path to custom terminology.yaml config file",
    )

    # Output control
    output_group = parser.add_argument_group("Output Control")

    output_group.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview validation decisions without writing files",
    )

    output_group.add_argument(
        "--save-rejected",
        action="store_true",
        help="Save rejected translations to disk for debugging",
    )

    output_group.add_argument(
        "--output",
        help=(
            "Output directory (overrides site profile). "
            "Files written to {output}/{lang}/{filename}. "
            "Example: --output /tmp/translations"
        ),
    )

    output_group.add_argument(
        "--max-files",
        type=int,
        default=0,
        metavar="N",
        help=(
            "Maximum number of files to process (0=unlimited, default: 0). "
            "Useful for testing/sampling. Files are selected deterministically "
            "(sorted by path) for reproducibility."
        ),
    )

    # Logging control
    logging_group = parser.add_argument_group("Logging")

    logging_group.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level (default: INFO)",
    )

    logging_group.add_argument(
        "--log-file",
        help="Write logs to file instead of console",
    )

    # Progress and metrics control
    metrics_group = parser.add_argument_group("Progress & Metrics")

    metrics_group.add_argument(
        "--metrics-file",
        metavar="PATH",
        help="Write metrics to file (creates PATH_current.json snapshot + PATH.ndjson stream)",
    )

    metrics_group.add_argument(
        "--metrics-interval",
        type=float,
        default=2.0,
        metavar="SECS",
        help="Metrics update interval in seconds (default: 2.0)",
    )

    metrics_group.add_argument(
        "--metrics-only",
        action="store_true",
        help="Suppress normal logs, emit only compact metrics line (for second terminal)",
    )

    metrics_group.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable progress tracking and ETA display",
    )

    # RES-02: Resume control
    resume_group = parser.add_argument_group("Resume Control (Crash Recovery)")

    resume_group.add_argument(
        "--resume",
        action="store_true",
        default=True,
        dest="resume",
        help="Resume from previous progress if available (default: enabled)",
    )

    resume_group.add_argument(
        "--no-resume",
        action="store_false",
        dest="resume",
        help="Ignore previous progress and start fresh",
    )

    resume_group.add_argument(
        "--force-restart",
        action="store_true",
        default=False,
        help="Clear all progress for site and start fresh (overrides --resume)",
    )

    resume_group.add_argument(
        "--progress-dir",
        default=".translation_progress",
        metavar="DIR",
        help="Directory to store progress files (default: .translation_progress)",
    )

    resume_group.add_argument(
        "--changed-since",
        type=str,
        default=None,
        metavar="SHA",
        help=(
            "Only translate files changed since this Git commit SHA. "
            "Runs git diff in the content repo; falls back to no filter on failure. "
            "Useful in CI: --changed-since $GITHUB_EVENT_BEFORE"
        ),
    )

    # Cache behavior control (federated-splashing-panda: Phase 2 redesign)
    cache_group = parser.add_argument_group("Translation Cache Control")

    cache_group.add_argument(
        "--force-retranslate",
        action="store_true",
        help="Bypass cache lookup and force fresh translation from model (updates cache with new results)",
    )

    cache_group.add_argument(
        "--cache-write-mode",
        choices=["auto", "always", "never"],
        default="auto",
        metavar="MODE",
        help="Cache write behavior: auto (write if missing, default), always (overwrite existing), never (read-only)",
    )

    cache_group.add_argument(
        "--disable-content-hash",
        action="store_true",
        help="Disable content hash tracking (use mtime-only change detection)",
    )

    cache_group.add_argument(
        "--rebuild-content-hashes",
        action="store_true",
        help="Ignore stored content hashes and recompute all (forces metadata rebuild)",
    )

    cache_group.add_argument(
        "--validate-output-integrity",
        action="store_true",
        help="Validate translated output file integrity (detect manual edits)",
    )

    # Multi-language processing (T301: federated-splashing-panda)
    multilang_group = parser.add_argument_group("Multi-Language Processing")

    multilang_group.add_argument(
        "--parallel-languages",
        type=int,
        default=0,
        metavar="N",
        action=_MultiLangModeAction,  # CLI-TC-03: Parse-time mutual exclusion
        help="Process up to N languages in parallel (0=disabled, default)",
    )

    multilang_group.add_argument(
        "--global-lang-rounds",
        type=int,
        default=0,
        metavar="N",
        action=_MultiLangModeAction,  # CLI-TC-03: Parse-time mutual exclusion
        help="Process N texts per language in round-robin fashion (0=disabled, default)",
    )

    multilang_group.add_argument(
        "--global-lang-sort",
        choices=["asc", "desc"],
        default="desc",
        metavar="ORDER",
        help="Sort languages by missing translation count: desc (most first, default) or asc (least first)",
    )

    multilang_group.add_argument(
        "--fail-fast",
        action="store_true",
        default=True,
        dest="fail_fast",
        help="Stop multi-language processing on first language failure (default: True)",
    )

    multilang_group.add_argument(
        "--no-fail-fast",
        action="store_false",
        dest="fail_fast",
        help="Continue processing remaining languages even if one fails",
    )

    # Benchmarking (production metrics collection - OPT-IN)
    benchmark_group = parser.add_argument_group("Benchmarking & Production Metrics")

    benchmark_group.add_argument(
        "--enable-production-metrics",
        action="store_true",
        help="Enable production metrics recording to benchmark database (OPT-IN, overrides config)",
    )

    # Configuration
    config_group = parser.add_argument_group("Configuration")

    config_group.add_argument(
        "--config-root",
        default="./config",
        help="Configuration root directory (default: ./config)",
    )

    # Git commit control
    commit_group = parser.add_argument_group("Git Commit Control")

    commit_group.add_argument(
        "--auto-commit",
        action="store_true",
        default=None,
        dest="auto_commit",
        help="Enable automatic git commits after successful translation (config default)",
    )

    commit_group.add_argument(
        "--no-commit",
        action="store_false",
        dest="auto_commit",
        help="Disable automatic git commits (override config)",
    )

    commit_group.add_argument(
        "--commit-message",
        type=str,
        default=None,
        dest="commit_message_override",
        help="Override commit message template",
    )

    return parser


def _load_benchmarking_yaml() -> dict:
    """
    Load and parse benchmarking.yaml, return empty dict if not found.

    Returns:
        Parsed YAML config dict, or empty dict if file doesn't exist or parse fails.

    Note:
        This is a low-level loader. Use load_benchmarking_config() for full config with defaults.
    """
    config_path = Path("config/benchmarking.yaml")
    logger_inst = logging.getLogger(__name__)

    if not config_path.exists():
        logger_inst.info("No benchmarking config file found, using defaults")
        return {}

    try:
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
            logger_inst.info(f"Loaded benchmarking config: path={config_path}")
            return config
    except Exception as e:
        logger_inst.warning(f"Failed to load benchmarking config: {e}, using defaults")
        return {}


def load_benchmarking_config() -> dict:
    """
    Load benchmarking configuration from config/benchmarking.yaml.

    Returns:
        Config dict with 'production', 'scheduler', 'database' sections.
        Returns safe defaults if config file doesn't exist or is invalid.
    """
    # Load raw YAML (uses shared loader)
    config = _load_benchmarking_yaml()

    # If config is empty (file doesn't exist or failed to load), return defaults
    if not config:
        return {
            "production": {"record_enabled": False},
            "database": {
                "path": "data/benchmarks/benchmarks.db",
                "production_path": "data/benchmarks/production.db",
            },
        }

    # Ensure defaults for missing sections
    if "production" not in config:
        config["production"] = {"record_enabled": False}
    if "database" not in config:
        config["database"] = {
            "path": "data/benchmarks/benchmarks.db",
            "production_path": "data/benchmarks/production.db",
        }

    # Validate and return
    return validate_benchmarking_config(config)


def validate_benchmarking_config(config: dict) -> dict:
    """
    Validate benchmarking config types and ranges, return sanitized config.

    Args:
        config: Raw config dict from YAML

    Returns:
        Sanitized config with validated types and safe defaults
    """
    logger = logging.getLogger(__name__)
    validated = config.copy()

    # Validate production section
    if "production" in validated:
        prod = validated["production"]

        # Validate record_enabled (bool)
        if "record_enabled" in prod:
            if not isinstance(prod["record_enabled"], bool):
                logger.warning(
                    f"Invalid type for production.record_enabled: {type(prod['record_enabled']).__name__}, "
                    "expected bool. Using default: False"
                )
                prod["record_enabled"] = False

        # Validate min_segments_to_record (int > 0)
        if "min_segments_to_record" in prod:
            val = prod["min_segments_to_record"]
            if not isinstance(val, int):
                logger.warning(
                    f"Invalid type for production.min_segments_to_record: {type(val).__name__}, "
                    "expected int. Using default: 1"
                )
                prod["min_segments_to_record"] = 1
            elif val < 1:
                logger.warning(
                    f"Invalid value for production.min_segments_to_record: {val}, "
                    "must be >= 1. Using default: 1"
                )
                prod["min_segments_to_record"] = 1
        else:
            # Add default if missing
            prod["min_segments_to_record"] = 1

    # Validate database section
    if "database" in validated:
        db = validated["database"]

        # Validate path (str)
        if "path" in db:
            if not isinstance(db["path"], str):
                logger.warning(
                    f"Invalid type for database.path: {type(db['path']).__name__}, "
                    "expected str. Using default"
                )
                db["path"] = "data/benchmarks/benchmarks.db"

        # Validate production_path (str)
        if "production_path" in db:
            if not isinstance(db["production_path"], str):
                logger.warning(
                    f"Invalid type for database.production_path: {type(db['production_path']).__name__}, "
                    "expected str. Using default"
                )
                db["production_path"] = "data/benchmarks/production.db"

    return validated


def validate_output_path(output_path: Path) -> None:
    """
    Validate output directory is writable before translation starts.

    Args:
        output_path: Path to validate

    Raises:
        SystemExit: If path is invalid (exits with code 1)
    """
    # SR-02c: Fail fast if output path is a file
    if output_path.exists() and output_path.is_file():
        print(f"ERROR: Output path is a file, not directory: {output_path}", file=sys.stderr)
        sys.exit(1)

    # SR-02c: Check parent directory exists
    parent = output_path.parent if not output_path.exists() else output_path
    if not parent.exists():
        print(f"ERROR: Output path parent does not exist: {parent}", file=sys.stderr)
        sys.exit(1)

    # SR-02c: Check write permissions
    if not os.access(parent, os.W_OK):
        print(f"ERROR: Output path not writable: {parent}", file=sys.stderr)
        sys.exit(1)


def _generate_verification_report(
    report_path: Path,
    results: any,  # Can be List[Tuple[Path, TranslationResult]] or DirectoryResult
) -> None:
    """
    Generate verification report from translation results.

    Args:
        report_path: Path to write report to
        results: Either a list of (file_path, TranslationResult) tuples for single file,
                 or a DirectoryResult for batch operations
    """
    # Import dependencies
    try:
        from .translation_engine.models import DirectoryResult
        from .verification.report import write_report
    except ImportError:
        from translation_engine.models import DirectoryResult
        from verification.report import write_report

    # VA-04: Extract verification results
    verification_results = []

    if isinstance(results, DirectoryResult):
        # Batch operation - collect from all file results
        for file_result in results.file_results:
            if hasattr(file_result, "verification_result") and file_result.verification_result:
                # Get the actual file path from outputs
                if file_result.outputs:
                    # Use first output path as the file identifier
                    file_path = Path(file_result.outputs[0])
                else:
                    # Fallback to a generic identifier
                    file_path = Path(f"file_{len(verification_results)}")
                verification_results.append((file_path, file_result.verification_result))
    elif isinstance(results, list):
        # Single file operation
        for file_path, translation_result in results:
            if hasattr(translation_result, "verification_result") and translation_result.verification_result:
                verification_results.append((file_path, translation_result.verification_result))

    if not verification_results:
        logger.warning("No verification results available to generate report")
        return

    try:
        write_report(
            report_path=report_path,
            results=verification_results,
            format_type="auto",
            include_issues=True,
        )
        logger.info(f"Verification report written to: {report_path}")
    except Exception as e:
        logger.error(f"Failed to write verification report: {e}")


def _cleanup_progress(progress_dir: Path, site_id: str) -> int:
    """
    Remove all progress files for a site.

    Args:
        progress_dir: Directory containing progress files
        site_id: Site identifier to clean up

    Returns:
        Number of progress files removed
    """
    if not progress_dir.exists():
        return 0

    removed = 0
    for pf in progress_dir.glob("progress_*.json"):
        try:
            with open(pf, encoding='utf-8') as f:
                data = json.load(f)
            if data.get('site_id') == site_id:
                pf.unlink()
                removed += 1
                logger.info(f"Removed progress file: {pf}")
        except (json.JSONDecodeError, KeyError, OSError) as e:
            logger.warning(f"Failed to check/remove progress file {pf}: {e}")
            continue

    return removed


def setup_logging(log_level: str, log_file: str | None = None, config_root: str | None = None) -> None:
    """
    Configure structured logging for CLI.

    Reads configuration from global.yaml and merges with CLI args.
    Sets up dual output: NDJSON file + colored console.

    Args:
        log_level: Logging level from CLI (DEBUG, INFO, WARNING, ERROR)
        log_file: Optional file path from CLI (overrides config)
        config_root: Configuration root directory (defaults to ./config)
    """
    from pathlib import Path

    import yaml

    from src.observability.logger import setup_structured_logging

    # Use provided config_root or default
    if config_root:
        config_path = Path(config_root) / "global.yaml"
    else:
        config_path = Path("config/global.yaml")

    logging_config = None

    if config_path.exists():
        try:
            with open(config_path, encoding="utf-8") as f:
                global_config = yaml.safe_load(f)
                logging_config = global_config.get("observability", {}).get("logging", {})
        except Exception as e:
            # Fallback to defaults if config read fails
            print(f"Warning: Failed to load logging config: {e}")
            logging_config = None

    # Determine effective logging configuration
    if logging_config and logging_config.get("enabled", True):
        # Use config from global.yaml, allowing CLI overrides
        effective_log_level = log_level or logging_config.get("log_level", "INFO")
        console_output = logging_config.get("console_output", True)
        file_output = logging_config.get("file_output", True)

        # CLI log_file takes precedence over config
        if log_file:
            log_file_path = Path(log_file)
        elif file_output:
            log_file_path = Path(logging_config.get("log_file", "data/logs/hugo-translator.ndjson"))
        else:
            log_file_path = None

        max_mb = logging_config.get("max_file_size_mb", 100)
        backup_count = logging_config.get("backup_count", 10)

        # Set up structured logging with dual output
        setup_structured_logging(
            log_level=effective_log_level,
            log_file=log_file_path if file_output or log_file else None,
            console_output=console_output,
            max_bytes=max_mb * 1024 * 1024,  # Convert MB to bytes
            backup_count=backup_count,
        )

        # WS4: Validate log file after setup
        if log_file_path and (file_output or log_file):
            # Import structlog to use the configured logger
            import structlog
            logger = structlog.get_logger(__name__)

            # Log startup message to test file write
            logger.info("Hugo Translator starting", version="0.1.0")

            # Check if log file exists and has content
            import time
            time.sleep(0.1)  # Brief delay to allow file write to complete
            if log_file_path.exists():
                file_size = log_file_path.stat().st_size
                if file_size == 0:
                    print(f"WARNING: Log file is empty: {log_file_path}", file=sys.stderr)
                    print(f"WARNING: Log file is empty: {log_file_path}", file=sys.stdout, flush=True)
            else:
                print(f"WARNING: Log file does not exist: {log_file_path}", file=sys.stderr)
                print(f"WARNING: Log file does not exist: {log_file_path}", file=sys.stdout, flush=True)
    else:
        # Fallback to basic logging if structured logging is disabled
        level = getattr(logging, log_level.upper())

        # Create formatter
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # Configure root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(level)

        # Remove existing handlers
        root_logger.handlers.clear()

        # Add appropriate handler
        if log_file:
            handler = logging.FileHandler(log_file, encoding="utf-8")
        else:
            handler = logging.StreamHandler(sys.stdout)

        handler.setLevel(level)
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)


def setup_unified_signal_handler(engine: "TranslationEngine") -> None:
    """
    SR-01, SR-05: Set up unified signal handler for graceful shutdown.

    This handler combines telemetry cleanup (from graceful_shutdown module)
    with engine shutdown coordination, fixing the issue where two separate
    handlers would conflict and cause the first to be overwritten.

    Platform-aware signal handling:
    - Windows: Handles SIGINT, SIGTERM, and SIGBREAK
    - Unix/Linux/macOS: Handles SIGINT and SIGTERM

    Supports multi-stage shutdown:
    - First Ctrl+C: Graceful shutdown (cleanup telemetry, finish current file)
    - Second Ctrl+C: Force quit immediately (exit code 130)

    Args:
        engine: The TranslationEngine instance to coordinate shutdown with
    """
    import platform as platform_mod

    from .observability.graceful_shutdown import cleanup_telemetry_contexts

    # Track number of interrupt signals received
    interrupt_count = {'count': 0}
    is_windows = platform_mod.system() == 'Windows'

    def unified_signal_handler(signum, frame):
        sig_name = signal.Signals(signum).name if hasattr(signal, 'Signals') else str(signum)
        interrupt_count['count'] += 1

        if interrupt_count['count'] == 1:
            # First interrupt: graceful shutdown sequence
            logger.warning(
                f"Received {sig_name}, initiating graceful shutdown...\n"
                "Finishing current file and saving progress. Press Ctrl+C again to force quit."
            )

            # Step 1: Clean up telemetry contexts (preserves partial metrics)
            try:
                cleanup_telemetry_contexts(sig_name)
            except Exception as e:
                logger.error(f"Error during telemetry cleanup: {e}")

            # Step 2: Request engine shutdown (saves L3 index, completes current file)
            engine.request_shutdown()
        else:
            # Second or subsequent interrupt: force quit immediately
            logger.error(
                f"Received {sig_name} again, forcing immediate exit...\n"
                "Warning: Translation state may not be fully saved!"
            )
            # Force immediate exit with standard interrupt exit code
            sys.exit(130)

    # Register handlers for all relevant signals (platform-aware)
    signals_to_register = [signal.SIGINT, signal.SIGTERM]

    # SR-05: Add SIGBREAK on Windows (CTRL+C may send SIGBREAK in some terminals)
    if is_windows and hasattr(signal, 'SIGBREAK'):
        signals_to_register.append(signal.SIGBREAK)

    for sig in signals_to_register:
        signal.signal(sig, unified_signal_handler)

    sig_names = [s.name if hasattr(s, 'name') else str(s) for s in signals_to_register]
    logger.debug(f"Unified signal handlers registered for graceful shutdown: {', '.join(sig_names)}")


def setup_signal_handlers(engine: "TranslationEngine") -> None:
    """
    DEPRECATED: Legacy function kept for backward compatibility.

    Use setup_unified_signal_handler() instead, which properly coordinates
    telemetry cleanup AND engine shutdown without conflicts.

    Args:
        engine: The TranslationEngine instance to coordinate shutdown with
    """
    logger.warning(
        "setup_signal_handlers() is deprecated. "
        "Calling setup_unified_signal_handler() instead."
    )
    setup_unified_signal_handler(engine)


def _log_startup_configuration(args: argparse.Namespace, site_profile, global_config, target_langs: list[str]) -> None:
    """
    Log comprehensive startup configuration at INFO level (WS3, Requirement 10).

    Displays all CLI settings, model configuration, validation mode, cache settings,
    and processing options so users understand exactly what configuration is active.
    """
    logger.info("=" * 80)
    logger.info("TRANSLATION CONFIGURATION")
    logger.info("=" * 80)

    # Basic settings
    logger.info(f"Site: {args.site}")
    if args.input:
        logger.info(f"Input: {args.input}")
    if args.output:
        logger.info(f"Output: {args.output}")
    else:
        logger.info("Output: (default from site profile)")

    logger.info(f"Target Languages: {', '.join(target_langs)} ({len(target_langs)} total)")

    # Model settings
    model_id = args.model or getattr(global_config, 'model_id', 'default')
    logger.info(f"Model: {model_id}")
    logger.info(f"Device: {args.device or 'auto'}")

    if hasattr(args, 'load_mode') and args.load_mode:
        logger.info(f"Load Mode: {args.load_mode}")

    if args.batch_size:
        logger.info(f"Batch Size: {args.batch_size}")
    else:
        logger.info("Batch Size: auto-optimized")

    if args.max_tokens:
        logger.info(f"Max Tokens: {args.max_tokens}")

    # Cache settings
    if args.force_retranslate:
        logger.info("Force Retranslate: ENABLED (cache reads disabled)")
    else:
        logger.info("Force Retranslate: DISABLED (cache enabled)")

    if hasattr(args, 'cache_write_mode') and args.cache_write_mode:
        logger.info(f"Cache Write Mode: {args.cache_write_mode}")

    # Validation settings
    if args.force_accept:
        logger.info("Validation: FORCE ACCEPT (all translations accepted)")
    elif args.strict_reject:
        logger.info("Validation: STRICT REJECT (strict validation enabled)")
    elif args.disable_validation:
        logger.info("Validation: DISABLED")
    else:
        max_retries = getattr(args, 'max_retries', 3)
        logger.info(f"Validation: ENABLED (max retries: {max_retries})")

    # Terminology settings
    if args.enable_terminology:
        terminology_mode = getattr(args, 'terminology_mode', 'both')
        logger.info(f"Terminology: ENABLED (mode: {terminology_mode})")
    else:
        logger.info("Terminology: DISABLED")

    # Processing settings
    if hasattr(args, 'sort_segments_by_length') and args.sort_segments_by_length:
        logger.info("Sort Segments: ENABLED (by length)")

    if args.dry_run:
        logger.info("Dry Run: ENABLED (no files will be written)")

    if hasattr(args, 'auto_commit') and args.auto_commit:
        logger.info("Auto Commit: ENABLED (translations will be committed)")

    # Multi-language mode
    if len(target_langs) > 1:
        logger.info("Multi-Language Mode: Sequential subprocesses (state isolation)")
        logger.info(f"Total Jobs: {len(target_langs)} languages")

    # Benchmarking (if available)
    if hasattr(global_config, 'benchmarking') and global_config.benchmarking:
        if global_config.benchmarking.enabled:
            output_dir = getattr(global_config.benchmarking, 'output_dir', 'data/benchmarks')
            logger.info(f"Benchmarking: ENABLED (recording to {output_dir})")
        else:
            logger.info("Benchmarking: DISABLED")

    logger.info("=" * 80)


def _write_dry_run_manifest(
    *,
    site_id: str,
    site_profile,
    input_path: Path,
    target_langs: list[str],
    model: str,
    engine: "TranslationEngine",
    filter_source_files_func,
    max_files: int = 0,
    force_retranslate: bool = False,
) -> Path:
    """Write a reviewable dry-run manifest without translating or writing output files."""
    timestamp = datetime.now(timezone.utc)
    timestamp_text = timestamp.isoformat().replace("+00:00", "Z")
    filename_ts = timestamp.strftime("%Y%m%dT%H%M%SZ")
    report_dir = Path("reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = report_dir / f"dry-run-{filename_ts}.json"

    would_translate: list[dict[str, str]] = []
    would_skip: list[dict[str, str]] = []
    would_fail: list[dict[str, str]] = []

    if input_path.is_file():
        all_files = [input_path]
        source_files = [input_path]
    elif input_path.is_dir():
        all_files = sorted(input_path.glob("**/*.md"), key=lambda p: str(p))
        try:
            source_files = filter_source_files_func(all_files, site_profile, target_langs)
            source_files = sorted(source_files, key=lambda p: str(p))
        except (ValueError, TypeError, AttributeError) as exc:
            source_files = all_files
            would_fail.append({
                "source_path": str(input_path),
                "target_lang": "",
                "reason": f"source filtering failed: {exc}",
            })
    else:
        all_files = []
        source_files = []
        would_fail.append({
            "source_path": str(input_path),
            "target_lang": "",
            "reason": "input path not found",
        })

    source_set = {Path(p) for p in source_files}
    for skipped in (p for p in all_files if p not in source_set):
        would_skip.append({
            "source_path": str(skipped),
            "reason": "filtered_or_translated",
        })

    if max_files and max_files > 0:
        limited_files = source_files[:max_files]
        for skipped in source_files[max_files:]:
            would_skip.append({
                "source_path": str(skipped),
                "reason": "outside_max_files_limit",
            })
        source_files = limited_files

    for source_file in source_files:
        try:
            source_mtime = source_file.stat().st_mtime
        except OSError as exc:
            for lang in target_langs:
                would_fail.append({
                    "source_path": str(source_file),
                    "target_lang": lang,
                    "reason": f"source stat failed: {exc}",
                })
            continue

        for lang in target_langs:
            output_path = engine._get_output_path(source_file, lang, site_profile)
            if not force_retranslate and output_path.exists():
                try:
                    if output_path.stat().st_mtime >= source_mtime:
                        would_skip.append({
                            "source_path": str(source_file),
                            "target_lang": lang,
                            "output_path": str(output_path),
                            "reason": "up_to_date",
                        })
                        continue
                except OSError as exc:
                    would_fail.append({
                        "source_path": str(source_file),
                        "target_lang": lang,
                        "reason": f"output stat failed: {exc}",
                    })
                    continue

            would_translate.append({
                "source_path": str(source_file),
                "target_lang": lang,
                "output_path": str(output_path),
            })

    manifest = {
        "site": site_id,
        "would_translate": would_translate,
        "would_skip": would_skip,
        "would_fail": would_fail,
        "model": model,
        "dry_run_timestamp": timestamp_text,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


def translate_site(args: argparse.Namespace) -> int:
    """
    Execute translation for a site with CLI overrides.

    Args:
        args: Parsed CLI arguments

    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    # Start CI heartbeat early — prevents timeout kills on long translations
    from .utils.ci_heartbeat import start_ci_heartbeat
    start_ci_heartbeat()

    # Import all dependencies needed for translation
    try:
        from .model_runtime import ModelLoader
        from .model_runtime.cpu_optimizer import CPUOptimizer
        from .model_runtime.gpu_optimizer import GPUOptimizer
        from .model_runtime.registry import ModelRegistry
        from .observability.graceful_shutdown import setup_graceful_shutdown
        from .observability.progress import (
            get_progress_tracker,
            init_progress_tracker,
            stop_progress_tracker,
        )
        from .observability.telemetry_cleanup import cleanup_stale_runs
        from .tm import TranslationMemory
        from .tm.l1_cache import L1Cache
        from .tm.l2_persistent import L2PersistentTM
        from .tm.l3_semantic import L3SemanticTM
        from .translation_engine import TranslationEngine
        from .translation_engine.progress import ProgressTracker
        from .utils.config_loader import ConfigService
        from .utils.file_filters import filter_source_files
        from .verification.report import write_report
    except ImportError:
        from model_runtime import ModelLoader
        from model_runtime.cpu_optimizer import CPUOptimizer
        from model_runtime.gpu_optimizer import GPUOptimizer
        from model_runtime.registry import ModelRegistry
        from observability.progress import (
            init_progress_tracker,
            stop_progress_tracker,
        )
        from observability.telemetry_cleanup import cleanup_stale_runs
        from tm import TranslationMemory
        from tm.l1_cache import L1Cache
        from tm.l2_persistent import L2PersistentTM
        from tm.l3_semantic import L3SemanticTM
        from translation_engine import TranslationEngine
        from translation_engine.progress import ProgressTracker
        from utils.config_loader import ConfigService
        from utils.file_filters import filter_source_files

    progress_tracker = None

    try:
        # Setup logging
        setup_logging(args.log_level, args.log_file, args.config_root)

        # Create CLI overrides early (needed for metrics_only flag)
        overrides = CLIConfigOverrides(args)

        # SR-01: Graceful shutdown setup moved after engine creation
        # (unified handler requires engine instance to coordinate shutdown)

        # TC-01: Clean up stale telemetry runs from previous interrupted sessions
        # Uses API-based cleanup to respect single-writer pattern
        try:
            cleanup_stats = cleanup_stale_runs(
                api_url=os.getenv("METRICS_API_URL", "http://localhost:8765"),
                max_age_hours=1,
                dry_run=False,
                quiet=overrides.metrics_only  # Suppress verbose logging in metrics-only mode
            )
            if cleanup_stats["stale_runs_found"] > 0 and not overrides.metrics_only:
                logger.info(
                    f"Telemetry cleanup: {cleanup_stats['updated']}/{cleanup_stats['stale_runs_found']} "
                    f"stale run(s) marked as cancelled"
                )
            elif cleanup_stats["errors"]:
                logger.debug(
                    f"Telemetry cleanup completed with errors: {cleanup_stats['errors']}"
                )
        except Exception as cleanup_error:
            # Non-critical - just log and continue
            logger.debug(f"Telemetry cleanup skipped: {cleanup_error}")

        if not overrides.metrics_only:
            logger.info(f"Starting translation for site: {args.site}")

        # RES-02: Handle resume/restart flags
        resume_enabled = overrides.resume
        if overrides.force_restart and overrides.resume:
            logger.info("Note: --force-restart overrides --resume")
            resume_enabled = False

        progress_dir_path = Path(overrides.progress_dir)
        translation_progress_tracker = None  # Distinct from observability progress_tracker

        if overrides.force_restart:
            logger.info("Force restart requested, clearing previous progress...")
            removed = _cleanup_progress(progress_dir_path, args.site)
            if removed > 0:
                logger.info(f"Removed {removed} progress file(s) for site {args.site}")
            else:
                logger.info("No previous progress found to clear")

        elif resume_enabled:
            # Try to find existing progress for this site
            translation_progress_tracker = ProgressTracker.find_latest(
                progress_dir=progress_dir_path,
                site_id=args.site
            )

            if translation_progress_tracker:
                # RES-07: Validate progress file before using
                is_valid, error_msg, recoverable = ProgressTracker.validate_progress_file(
                    translation_progress_tracker.progress_file
                )

                if not is_valid:
                    logger.warning(f"Progress file validation failed: {error_msg}")

                    if recoverable:
                        logger.info("Attempting recovery...")
                        recovered_tracker = ProgressTracker.recover_progress_file(
                            translation_progress_tracker.progress_file
                        )

                        if recovered_tracker:
                            translation_progress_tracker = recovered_tracker
                            logger.info("Progress recovered successfully")
                        else:
                            logger.warning("Recovery failed. Starting fresh.")
                            translation_progress_tracker = None
                    else:
                        logger.warning("Progress file is unrecoverable. Starting fresh.")
                        # Backup corrupted file
                        backup_path = translation_progress_tracker.progress_file.with_suffix('.json.corrupt')
                        try:
                            shutil.copy(translation_progress_tracker.progress_file, backup_path)
                            logger.info(f"Corrupted file backed up to: {backup_path}")
                        except Exception as e:
                            logger.warning(f"Could not backup corrupted file: {e}")
                        translation_progress_tracker = None

            if translation_progress_tracker:
                stats = translation_progress_tracker.get_statistics()
                logger.info(f"Found previous progress (run {stats['run_id'][:8]}...)")
                logger.info(f"Progress: {stats['files_processed']}/{stats['total_files']} files")
                logger.info(f"Completed: {stats['translations_completed']} translations")
                logger.info(f"Failed: {stats['translations_failed']} translations")
                logger.info(f"Pending: {stats['translations_pending']} translations ({stats['progress_percent']:.1f}%)")
                logger.info("Resuming translation...")
            else:
                logger.info("No previous progress found, starting fresh...")

        # Load configuration
        config_service = ConfigService(args.config_root)

        # Apply CLI config path overrides
        overrides.apply_to_config_service(config_service)

        # Load site profile
        site_profile = config_service.get_site_profile(args.site)

        # Override target languages if specified
        target_langs = args.target_langs if args.target_langs else site_profile.target_langs

        # P1-12: Initialize SharedEngines early for unified engine access
        shared_engines = None
        try:
            from .shared_engines.composition_root import CompositionRoot
        except ImportError:
            try:
                from shared_engines.composition_root import CompositionRoot
            except ImportError:
                CompositionRoot = None  # Graceful degradation if not available

        if CompositionRoot:
            try:
                # Create engines from CLI arguments and configuration
                engines_config = {
                    "config_root": args.config_root,
                    "log_level": args.log_level,
                    "log_file": Path(args.log_file) if args.log_file else None,
                    "console_output": True,
                    "telemetry_enabled": True,
                    "job_backend": "memory",  # Use memory backend for CLI
                    "commit_enabled": not overrides.dry_run,  # Disable commits in dry-run
                    "max_retries": overrides.max_retries or 3,
                    "translation_backend": "mt"  # CLI uses MT backend
                }
                shared_engines = CompositionRoot.create_from_config(engines_config)
                logger.debug("SharedEngines initialized successfully")
            except Exception as e:
                logger.debug(f"SharedEngines initialization failed: {e}")
                shared_engines = None  # Graceful degradation
        else:
            logger.debug("SharedEngines not available (composition_root not imported)")

        # WS3: Log comprehensive startup configuration (Requirement 10)
        _log_startup_configuration(args, site_profile, config_service.global_config, target_langs)

        # P1-12: Track translation session start via engines (if available)
        if shared_engines:
            try:
                shared_engines.logging.info(
                    "Translation session started",
                    site_id=args.site,
                    target_langs=target_langs,
                    source_lang=site_profile.source_lang if hasattr(site_profile, 'source_lang') else 'en'
                )
                shared_engines.telemetry.track_event(
                    event_type="translation_session_start",
                    site_id=args.site,
                    target_langs=target_langs,
                    model_id=args.model or "default"
                )
            except Exception as e:
                logger.debug(f"SharedEngines telemetry tracking failed (non-fatal): {e}")

        # CRITICAL FIX: Process each language in separate subprocess to prevent state contamination
        # Root cause: M2M100 model retains internal state between sequential translations to different
        # target languages, causing text from one language (e.g., Turkish) to bleed into others
        # (e.g., Ukrainian). This occurs even with model reload, use_cache=False, and TM bypass.
        # Solution: Complete process isolation ensures each language starts with pristine state.
        if len(target_langs) > 1 and not getattr(args, '_single_lang_mode', False):
            logger.info(
                f"Multi-language translation detected ({len(target_langs)} languages). "
                f"Processing each language in separate subprocess to prevent state contamination..."
            )

            # Import per-language commit and failure tracking functions
            try:
                from src.observability.language_commit import (
                    commit_language_translations,
                    save_failure_report,
                )
            except ImportError:
                from observability.language_commit import (
                    commit_language_translations,
                    save_failure_report,
                )

            # TC1: Acquire site lock in PARENT before spawning subprocesses
            from src.translation_engine.engine import get_site_lock

            # CRITICAL: Timeout set on construction, not on acquire()
            site_lock = get_site_lock(args.site, timeout=30.0)  # 30s parent timeout

            # Register cleanup handlers for unexpected exit
            def cleanup_lock():
                global _parent_lock
                if _parent_lock and _parent_lock._locked:
                    logger.info("Cleaning up parent lock on exit")
                    _parent_lock.release()
                    _parent_lock = None

            atexit.register(cleanup_lock)

            # Register signal handlers
            signal.signal(signal.SIGINT, _signal_handler)
            signal.signal(signal.SIGTERM, _signal_handler)

            try:
                logger.info(f"Acquiring site lock for {args.site}...")
                # NO timeout parameter here - it's set in FileLock constructor above
                if not site_lock.acquire(blocking=True):
                    logger.error("Failed to acquire site lock. Another translation may be running.")
                    logger.info(f"Run 'python -m src.cli diagnose-lock --site {args.site}' for details")
                    return 1

                global _parent_lock
                _parent_lock = site_lock  # For signal handler
                logger.info("Site lock acquired by parent process")

            except Exception as e:
                logger.error(f"Error acquiring lock: {e}")
                logger.info(f"Run 'python -m src.cli diagnose-lock --site {args.site}' for details")
                return 1

            exit_codes = []
            language_results = {}  # Track per-language results
            failure_dir = Path("data/failures")  # Directory for failure reports

            # Determine input path for git repo detection
            if args.input:
                input_path = Path(os.path.expandvars(args.input))
            else:
                # Use first content root from site profile
                input_path = Path(os.path.expandvars(site_profile.content_roots[0]))

            # Load global config for commit settings
            global_config = config_service.global_config

            # Determine effective auto-commit flag:
            # Explicit --auto-commit / --no-commit overrides global config;
            # when neither is provided (args.auto_commit is None), fall back to
            # global_config.git_commit.enabled so the workers always commit when
            # the config says so (e.g. global.yaml git_commit.enabled: true).
            effective_auto_commit = args.auto_commit
            if effective_auto_commit is None:
                try:
                    effective_auto_commit = bool(global_config.git_commit.enabled)
                except Exception:
                    effective_auto_commit = False

            # Determine git repository root once for all languages
            git_repo_root = None
            if effective_auto_commit:
                try:
                    # Find git root by walking up from input path
                    search_path = input_path if input_path.is_dir() else input_path.parent
                    while search_path != search_path.parent:
                        if (search_path / ".git").exists():
                            git_repo_root = search_path
                            logger.info(f"Auto-commit enabled (config: git_commit.enabled=true). Git repository: {git_repo_root}")
                            break
                        search_path = search_path.parent

                    if git_repo_root is None:
                        logger.warning(f"Could not find git repository root for {input_path}. Auto-commit will be disabled.")
                except Exception as e:
                    logger.warning(f"Failed to determine git repository root: {e}. Auto-commit will be disabled.")
                    git_repo_root = None

            try:
                import threading as _thr
                from concurrent.futures import ThreadPoolExecutor as _TPE
                from concurrent.futures import as_completed as _ac
                _parallel_n = max(1, getattr(args, 'parallel_languages', 0) or 1)
                _commit_lock = _thr.Lock()
                logger.info(f"Parallel dispatch: {_parallel_n} workers for {len(target_langs)} languages")

                def _run_one_language(lang_idx):
                    """Translate one language in a thread; returns (exit_code, result_dict)."""
                    i, lang = lang_idx
                    _ec = -1
                    _res = {}
                    logger.info(f"\n{'='*60}")
                    logger.info(f"Processing language {i}/{len(target_langs)}: {lang}")
                    logger.info(f"{'='*60}\n")

                    # Track start time for this language
                    lang_start_time = time.time()

                    # Build subprocess command with same args but single target language
                    cmd = [sys.executable, "-m", "src.cli"]

                    # Copy all original arguments
                    cmd.extend(["--site", args.site])

                    if args.input:
                        cmd.extend(["--input", str(args.input)])
                    if args.output:
                        cmd.extend(["--output", str(args.output)])

                    # Single target language for this subprocess
                    cmd.extend(["--target-langs", lang])

                    # Copy other flags
                    if args.model:
                        cmd.extend(["--model", args.model])
                    # CT2-002: Pass model selection flag to subprocess
                    if args.auto_select_model:
                        cmd.append("--auto-select-model")
                    if args.device:
                        cmd.extend(["--device", args.device])
                    if args.batch_size:
                        cmd.extend(["--batch-size", str(args.batch_size)])
                    if args.max_tokens:
                        cmd.extend(["--max-tokens", str(args.max_tokens)])
                    if args.log_level:
                        cmd.extend(["--log-level", args.log_level])
                    if args.log_file:
                        cmd.extend(["--log-file", args.log_file])
                    if args.force_retranslate:
                        cmd.append("--force-retranslate")
                    if args.dry_run:
                        cmd.append("--dry-run")
                    if args.no_progress:
                        cmd.append("--no-progress")
                    if args.disable_validation:
                        cmd.append("--disable-validation")
                    if args.force_accept:
                        cmd.append("--force-accept")
                    if args.strict_reject:
                        cmd.append("--strict-reject")
                    if args.validation_mode:
                        cmd.extend(["--validation-mode", args.validation_mode])
                    if args.enable_terminology is not None:
                        if args.enable_terminology:
                            cmd.append("--enable-terminology")
                        else:
                            cmd.append("--disable-terminology")
                    if args.config_root:
                        cmd.extend(["--config-root", args.config_root])

                    # Mark as single-language mode to prevent infinite recursion
                    cmd.append("--_single-lang-mode")

                    # TC1: Tell subprocess to skip lock acquisition (parent holds it)
                    cmd.append("--_skip-site-lock")

                    # Run subprocess with error handling
                    logger.debug(f"Subprocess command: {' '.join(cmd)}")

                    # --- Batch-commit loop: translate up to files_per_commit files, commit, repeat ---
                    try:
                        _fpc = int(global_config.git_commit.files_per_commit)
                        if _fpc <= 0:
                            _fpc = 25
                    except Exception:
                        _fpc = 25
                    _batch_cmd = list(cmd) + ["--max-files", str(_fpc)]
                    _batch_num = 0
                    while True:
                        _batch_num += 1
                        logger.info(f"[{lang}] Batch {_batch_num}: launching subprocess (max {_fpc} files)")
                        try:
                            # Stream subprocess output in real-time with [lang] prefix
                            import threading
                            from io import StringIO

                            # Buffers to capture full output for failure reporting
                            stdout_buffer = StringIO()
                            stderr_buffer = StringIO()

                            def stream_output(pipe, prefix, log_func, buffer):
                                """Stream subprocess output line-by-line with prefix"""
                                try:
                                    for line in iter(pipe.readline, ''):
                                        if line:
                                            stripped = line.rstrip()
                                            if stripped:  # Only log non-empty lines
                                                log_func(f"[{prefix}] {stripped}")
                                            buffer.write(line)
                                    pipe.close()
                                except Exception as e:
                                    logger.debug(f"Error streaming {prefix} output: {e}")

                            # Start subprocess with pipes
                            # IMPORTANT: Use UTF-8 encoding to match subprocess output encoding
                            # (subprocess uses UTF-8 stdout wrapper for Unicode support on Windows)
                            process = subprocess.Popen(
                                _batch_cmd,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                text=True,
                                encoding='utf-8',  # Match subprocess UTF-8 encoding
                                errors='replace',  # Handle any encoding errors gracefully
                                bufsize=1,  # Line-buffered
                            )

                            # Create threads to stream stdout and stderr
                            stdout_thread = threading.Thread(
                                target=stream_output,
                                args=(process.stdout, lang, logger.info, stdout_buffer),
                                daemon=True
                            )
                            stderr_thread = threading.Thread(
                                target=stream_output,
                                args=(process.stderr, lang, logger.warning, stderr_buffer),
                                daemon=True
                            )

                            stdout_thread.start()
                            stderr_thread.start()

                            # Wait for process completion with timeout
                            try:
                                exit_code = process.wait(timeout=None)  # No per-language timeout
                            except subprocess.TimeoutExpired:
                                process.kill()
                                process.wait()  # Clean up zombie process
                                raise  # Re-raise to be caught below

                            # Wait for output threads to finish
                            stdout_thread.join(timeout=5)
                            stderr_thread.join(timeout=5)

                            # Get captured output
                            stdout_output = stdout_buffer.getvalue()
                            stderr_output = stderr_buffer.getvalue()

                            duration = time.time() - lang_start_time
                            _ec = exit_code

                            # Track result for this language
                            _res = {
                                "exit_code": exit_code,
                                "success": exit_code == 0,
                                "duration": duration,
                                "stderr_preview": stderr_output[-500:] if stderr_output else "",
                            }

                            if exit_code != 0:
                                logger.error(
                                    f"Translation had failures for language {lang} (exit_code={exit_code}, "
                                    f"duration: {duration:.1f}s) — checking for partial progress"
                                )

                                # Save failure report with captured output
                                mock_result = subprocess.CompletedProcess(
                                    args=cmd,
                                    returncode=exit_code,
                                    stdout=stdout_output,
                                    stderr=stderr_output,
                                )
                                save_failure_report(
                                    target_lang=lang,
                                    subprocess_result=mock_result,
                                    failure_dir=failure_dir,
                                    duration_seconds=duration,
                                )
                            else:
                                logger.info(f"Successfully completed translation for {lang} (duration: {duration:.1f}s)")

                            # Always check git status — even partial-success batches (exit_code=1)
                            # should commit what succeeded and continue to remaining untranslated files.
                            # Only break if there is literally zero new progress (no staged files).
                            stats = {
                                "model_used": args.model or "default",
                                "duration_seconds": duration,
                                "tm_hit_rate": 0.0,
                                "segments_total": 0,
                            }
                            validation_passed = exit_code == 0

                            if git_repo_root is None:
                                logger.debug(f"Skipping auto-commit for {lang} (git repository not found)")
                                translated_files = []
                            else:
                                try:
                                    git_status_result = subprocess.run(
                                        ["git", "status", "--porcelain"],
                                        cwd=git_repo_root,
                                        capture_output=True,
                                        text=True,
                                        encoding='utf-8',
                                        errors='replace',
                                        timeout=30,
                                        check=True,
                                    )
                                    try:
                                        _site_prefix = str(input_path.relative_to(git_repo_root)).replace('\\', '/').rstrip('/') + '/'
                                    except Exception:
                                        _site_prefix = None

                                    translated_files = []
                                    for line in git_status_result.stdout.splitlines():
                                        if line.strip():
                                            status_code = line[:2]
                                            file_path = line[3:].strip()
                                            if 'R' in status_code or 'D' in status_code:
                                                continue
                                            if 'M' not in status_code and 'A' not in status_code and '?' not in status_code:
                                                continue
                                            file_path_normalized = file_path.replace('\\', '/')
                                            if _site_prefix and not file_path_normalized.startswith(_site_prefix):
                                                continue
                                            is_translated = (
                                                f'/{lang}/' in file_path_normalized
                                                or file_path_normalized.startswith(f'{lang}/')
                                                or f'.{lang}.' in file_path_normalized
                                            )
                                            if is_translated:
                                                translated_files.append(git_repo_root / file_path)

                                    if translated_files:
                                        logger.debug(f"Detected {len(translated_files)} modified files for {lang}")
                                    else:
                                        logger.warning(f"No modified files detected for {lang}, skipping commit")

                                except Exception as e:
                                    logger.warning(f"Failed to detect modified files for {lang}: {e}")
                                    translated_files = []

                            if translated_files:
                                with _commit_lock:
                                    # P1-12: Commit translations using CommitEngine (if available) or fallback
                                    if shared_engines and shared_engines.commit:
                                        try:
                                            commit_result = shared_engines.commit.commit_if_enabled(
                                                output_files=translated_files,
                                                site_id=args.site,
                                                target_langs=[lang],
                                                run_id=f"cli-multilang-{lang}",
                                                model_id=args.model or "default",
                                                tm_stats=stats
                                            )
                                            if commit_result.success and commit_result.files_committed > 0:
                                                logger.info(f"Committed {commit_result.files_committed} files for {lang}")
                                            elif not commit_result.success:
                                                logger.warning(f"Failed to commit translations for {lang}: {commit_result.error} (non-fatal)")
                                            else:
                                                logger.debug(f"No files to commit for {lang} (already committed or no changes)")
                                        except Exception as e:
                                            logger.warning(f"CommitEngine error for {lang} (non-fatal): {e}")
                                    else:
                                        _auto_push = getattr(global_config.git_commit, 'auto_push', False)
                                        commit_success = commit_language_translations(
                                            target_lang=lang,
                                            translated_files=translated_files,
                                            stats=stats,
                                            config=config_service.get_config(),
                                            auto_push=_auto_push,
                                            git_repo_root=git_repo_root,
                                            validation_passed=validation_passed,
                                        )
                                        if commit_success:
                                            logger.info(f"Committed {len(translated_files)} files for {lang}")
                                        else:
                                            logger.warning(f"Failed to commit translations for {lang} (non-fatal)")
                                # Partial-failure batch: log and continue to next batch
                                if exit_code != 0:
                                    logger.info(f"[{lang}] Batch {_batch_num} had partial failures but committed {len(translated_files)} files — continuing")
                            else:
                                # No new files written this batch
                                if exit_code != 0:
                                    logger.info(f"[{lang}] Batch {_batch_num} failed (exit_code={exit_code}) with no new files — stopping")
                                else:
                                    logger.info(f"[{lang}] No new files in batch {_batch_num} — language complete")
                                break  # No progress made — stop loop

                        except subprocess.TimeoutExpired:
                            duration = time.time() - lang_start_time
                            logger.error(
                                f"Translation timed out for language {lang} after {duration:.1f}s "
                                f"(timeout: 3600s)"
                            )

                            # Create a mock result for failure reporting
                            mock_result = subprocess.CompletedProcess(
                                args=cmd,
                                returncode=-1,
                                stdout="",
                                stderr="Process timed out after 3600 seconds",
                            )

                            _ec = -1
                            _res = {
                                "exit_code": -1,
                                "success": False,
                                "duration": duration,
                                "stderr_preview": "TimeoutExpired",
                            }

                            save_failure_report(
                                target_lang=lang,
                                subprocess_result=mock_result,
                                failure_dir=failure_dir,
                                duration_seconds=duration,
                            )

                            # Stop batch loop for this language after timeout
                            logger.info(f"[{lang}] Stopping batch loop after timeout in batch {_batch_num}")
                            break

                        except subprocess.CalledProcessError as e:
                            duration = time.time() - lang_start_time
                            logger.error(
                                f"Subprocess error for language {lang}: {e} "
                                f"(duration: {duration:.1f}s)"
                            )

                            _ec = e.returncode
                            _res = {
                                "exit_code": e.returncode,
                                "success": False,
                                "duration": duration,
                                "stderr_preview": str(e)[-500:],
                            }

                            # Create result object for failure reporting
                            result = subprocess.CompletedProcess(
                                args=cmd,
                                returncode=e.returncode,
                                stdout=getattr(e, 'stdout', ''),
                                stderr=getattr(e, 'stderr', str(e)),
                            )

                            save_failure_report(
                                target_lang=lang,
                                subprocess_result=result,
                                failure_dir=failure_dir,
                                duration_seconds=duration,
                            )

                            # Stop batch loop for this language after error
                            logger.info(f"[{lang}] Stopping batch loop after error in batch {_batch_num}")
                            break

                        except Exception as e:
                            duration = time.time() - lang_start_time
                            logger.error(
                                f"Unexpected error for language {lang}: {e} "
                                f"(duration: {duration:.1f}s)"
                            )

                            _ec = -1
                            _res = {
                                "exit_code": -1,
                                "success": False,
                                "duration": duration,
                                "stderr_preview": str(e)[-500:],
                            }

                            # Create mock result for failure reporting
                            mock_result = subprocess.CompletedProcess(
                                args=cmd,
                                returncode=-1,
                                stdout="",
                                stderr=str(e),
                            )

                            save_failure_report(
                                target_lang=lang,
                                subprocess_result=mock_result,
                                failure_dir=failure_dir,
                                duration_seconds=duration,
                            )

                            # Stop batch loop for this language after unexpected error
                            logger.info(f"[{lang}] Stopping batch loop after unexpected error in batch {_batch_num}")
                            break

                    return _ec, _res

                with _TPE(max_workers=_parallel_n) as _pool:
                    _futures = {
                        _pool.submit(_run_one_language, (i, lang)): lang
                        for i, lang in enumerate(target_langs, 1)
                    }
                    for _fut in _ac(_futures):
                        _flang = _futures[_fut]
                        try:
                            _fec, _fres = _fut.result()
                            exit_codes.append(_fec)
                            language_results[_flang] = _fres
                        except Exception as _ferr:
                            logger.error(f"Thread error for {_flang}: {_ferr}")
                            exit_codes.append(-1)
                            language_results[_flang] = {"exit_code": -1, "success": False, "duration": 0, "stderr_preview": str(_ferr)}
                # Summary report with per-language results
                successful_langs = [lang for lang, res in language_results.items() if res["success"]]
                failed_langs = [lang for lang, res in language_results.items() if not res["success"]]

                logger.info(f"\n{'='*60}")
                logger.info("Multi-Language Translation Summary")
                logger.info(f"{'='*60}")
                logger.info(f"Total languages: {len(target_langs)}")
                logger.info(f"Successful: {len(successful_langs)}/{len(target_langs)}")
                if successful_langs:
                    logger.info(f"  Languages: {', '.join(successful_langs)}")
                    # Show durations for successful languages
                    for lang in successful_langs:
                        duration = language_results[lang].get("duration", 0)
                        logger.info(f"    - {lang}: {duration:.1f}s")

                logger.info(f"Failed: {len(failed_langs)}/{len(target_langs)}")
                if failed_langs:
                    logger.warning(f"  Languages: {', '.join(failed_langs)}")
                    # Show exit codes and durations for failed languages
                    for lang in failed_langs:
                        exit_code = language_results[lang].get("exit_code", -1)
                        duration = language_results[lang].get("duration", 0)
                        logger.warning(f"    - {lang}: exit_code={exit_code}, duration={duration:.1f}s")

                    # Show where failure reports are saved
                    if failure_dir.exists():
                        logger.info(f"\nFailure reports saved to: {failure_dir.absolute()}")
                        logger.info("Review reports for detailed error information and retry commands")

                logger.info(f"{'='*60}\n")

                # P1-12: Track multi-language processing summary via telemetry
                if shared_engines:
                    try:
                        shared_engines.telemetry.track_event(
                            event_type="multilang_processing_complete",
                            site_id=args.site,
                            total_languages=len(target_langs),
                            successful_languages=len(successful_langs),
                            failed_languages=len(failed_langs),
                            success_rate=len(successful_langs) / len(target_langs) if target_langs else 0
                        )
                    except Exception as e:
                        logger.debug(f"Telemetry tracking failed (non-fatal): {e}")

                # Return overall status - exit with 1 if ANY failures occurred
                if failed_langs:
                    logger.error(f"Translation completed with {len(failed_langs)} failure(s). Exiting with code 1.")
                    return 1
                else:
                    logger.info("All translations completed successfully!")
                    return 0

            finally:
                # TC1: Always release lock
                if site_lock and site_lock._locked:
                    logger.info("Releasing site lock")
                    site_lock.release()
                    _parent_lock = None

        # Log validation settings
        if overrides.force_accept:
            logger.info("Validation: FORCE ACCEPT - all translations accepted without validation")
        elif overrides.strict_reject:
            logger.info("Validation: STRICT REJECT - fail fast on any validation issue (max retries: 0)")
        elif overrides.disable_validation:
            logger.info("Validation: DISABLED via CLI")
        elif overrides.validation_mode:
            logger.info(f"Validation mode: {overrides.validation_mode} (CLI override)")
        else:
            logger.info("Validation: Using config defaults")

        if overrides.enable_terminology is not None:
            status = "ENABLED" if overrides.enable_terminology else "DISABLED"
            logger.info(f"Terminology: {status} via CLI")

        if overrides.terminology_mode:
            logger.info(f"Terminology mode: {overrides.terminology_mode} (CLI override)")

        if overrides.max_retries is not None:
            logger.info(f"Max retries: {overrides.max_retries} (CLI override)")

        if overrides.dry_run:
            logger.info("DRY RUN MODE: No files will be written")

        # Initialize core components
        logger.info("Initializing Translation Memory...")
        global_config = config_service.global_config

        # Get TM data paths from global config
        tm_data_dir = Path(global_config.tm_data_dir)
        tm_data_dir.mkdir(parents=True, exist_ok=True)

        # Initialize TM layers (use reasonable defaults)
        l1_cache = L1Cache(max_size=10000)  # Default L1 cache size

        from .tm.l2_persistent import L2_DB_NAME
        _raw = config_service.get_config() if hasattr(config_service, "get_config") else {}
        _l2_max_mb = _raw.get("tm_defaults", {}).get("l2_max_size_mb", 1536)
        l2_path = tm_data_dir / L2_DB_NAME
        l2_path.mkdir(parents=True, exist_ok=True)
        l2_persistent = L2PersistentTM(str(l2_path), max_size_mb=_l2_max_mb)

        l3_semantic = None
        if site_profile.tm_prefs.use_semantic_tm:
            try:
                l3_path = tm_data_dir / "l3_faiss"
                l3_path.mkdir(parents=True, exist_ok=True)
                l3_semantic = L3SemanticTM(index_path=str(l3_path))
                logger.info("L3 Semantic TM initialized")
            except Exception as e:
                logger.warning(f"L3 Semantic TM unavailable: {e}")

        tm = TranslationMemory(
            l1_cache=l1_cache,
            l2_persistent=l2_persistent,
            l3_semantic=l3_semantic,
        )

        logger.info("Initializing Model Loader...")
        # CT2-002: Support multiple registries (base + custom CT2 + discovered local models)
        registry_paths = [
            Path(args.config_root) / "model_registry.yaml",
            Path(args.config_root) / "custom_ct2_registry.yaml",
            Path(args.config_root) / "model_registry.discovered.yaml",
        ]
        # Filter to only existing registry files
        existing_registries = [p for p in registry_paths if p.exists()]
        if not existing_registries:
            raise FileNotFoundError(f"No model registry files found in {args.config_root}")

        logger.info(f"Loading model registries: {[str(p) for p in existing_registries]}")
        model_registry = ModelRegistry(existing_registries)
        logger.info(f"Combined registry: {len(model_registry)} models total")

        # Device selection with CLI override support (T102: federated-splashing-panda)
        try:
            import torch

            if overrides.device:
                # Device explicitly specified via CLI
                device = overrides.device

                if device == "cuda":
                    # Validate CUDA availability when explicitly requested
                    if not torch.cuda.is_available():
                        logger.error("CUDA device requested but not available. Check GPU drivers and PyTorch CUDA installation.")
                        return 1
                    logger.info(f"Device: {device} (CLI override)")
                else:
                    # CPU explicitly requested
                    logger.info(f"Device: {device} (CLI override)")
            else:
                # Auto-detect device: use CUDA if available, otherwise CPU
                device = "cuda" if torch.cuda.is_available() else "cpu"
                logger.info(f"Auto-detected device: {device}")

            # Load mode compatibility warnings
            if overrides.load_mode:
                if overrides.load_mode == "fp16" and device == "cpu":
                    logger.warning("FP16 (half precision) is not optimally supported on CPU. Performance may be degraded. Consider using --load-mode fp32 or --load-mode int8 for CPU.")
                elif overrides.load_mode == "int8" and device == "cuda":
                    logger.warning("INT8 quantization is primarily for CPU inference. On CUDA, consider using --load-mode fp16 for better performance.")

        except ImportError:
            if overrides.device == "cuda":
                logger.error("CUDA device requested but PyTorch is not installed.")
                return 1
            device = "cpu"
            logger.info("PyTorch not available, using CPU")

        # Load raw config once for dict-based lookups
        raw_config = config_service.get_config()

        # Get max GPU memory from global config (use raw config since hardware not in GlobalConfig model)
        max_gpu_memory_mb = None
        print(f"DEBUG CLI: device={device}", flush=True)
        if device.startswith("cuda"):
            hardware_config = raw_config.get("hardware", {})
            max_gpu_memory_mb = hardware_config.get("max_gpu_memory_mb")
            print(f"DEBUG CLI: max_gpu_memory_mb from hardware_config={max_gpu_memory_mb}", flush=True)

            # If not set in hardware config, compute from execution mode percent
            if max_gpu_memory_mb is None:
                exec_mode = os.getenv("EXECUTION_MODE", "windows_cuda")
                exec_mode_config = raw_config.get("execution", {}).get("modes", {}).get(exec_mode, {})
                max_gpu_memory_percent = exec_mode_config.get("max_gpu_memory_percent")
                print(f"DEBUG CLI: exec_mode={exec_mode}, max_gpu_memory_percent={max_gpu_memory_percent}", flush=True)
                if max_gpu_memory_percent is not None:
                    try:
                        import torch
                        if torch.cuda.is_available():
                            total_vram_mb = torch.cuda.get_device_properties(0).total_memory / (1024**2)
                            max_gpu_memory_mb = int(total_vram_mb * (max_gpu_memory_percent / 100.0))
                            logger.info(
                                f"Computed GPU memory limit from {max_gpu_memory_percent}%: "
                                f"{max_gpu_memory_mb}MB ({max_gpu_memory_percent}% of {total_vram_mb:.0f}MB)"
                            )
                            print(f"DEBUG CLI: Computed max_gpu_memory_mb={max_gpu_memory_mb}", flush=True)
                    except Exception as e:
                        logger.warning(f"Failed to compute GPU memory limit from percent: {e}")
                        print(f"DEBUG CLI: Failed to compute: {e}", flush=True)
            elif max_gpu_memory_mb:
                logger.info(f"GPU memory limit from config: {max_gpu_memory_mb}MB")

        # Enforce VRAM limit if configured for CUDA device
        if device.startswith("cuda") and max_gpu_memory_mb:
            from src.hardware.gpu_manager import GPUManager
            gpu_mgr = GPUManager(config={"max_gpu_memory_mb": max_gpu_memory_mb})
            gpu_mgr.enforce_memory_limit(device)
            logger.info(f"VRAM enforcement applied: {max_gpu_memory_mb}MB")

        model_loader = ModelLoader(
            registry=model_registry,
            device=device,
            max_memory_mb=max_gpu_memory_mb,
            load_mode=overrides.load_mode,  # T103: federated-splashing-panda
            config=raw_config
        )

        # Get engine overrides from CLI
        engine_kwargs = overrides.get_engine_overrides()

        # TC-CPU-02: Apply CPU optimization if on CPU and batch_size not explicitly set
        if device == "cpu" and "batch_size" not in engine_kwargs:
            logger.info("Optimizing for CPU runtime...")
            cpu_optimizer = CPUOptimizer()
            cpu_config = cpu_optimizer.optimize()
            engine_kwargs["batch_size"] = cpu_config.batch_size
            logger.info(
                f"CPU optimization enabled: batch_size={cpu_config.batch_size}, "
                f"threads={cpu_config.num_threads}"
            )
        # GPU optimization: Apply GPU-aware batch sizing if on GPU and batch_size not explicitly set
        elif device.startswith("cuda") and "batch_size" not in engine_kwargs:
            logger.info("Optimizing for GPU runtime...")
            try:
                # Determine precision from load_mode (default to fp16 for GPU)
                precision = overrides.load_mode or "fp16"

                # Extract device ID if specified (e.g., "cuda:0" -> 0)
                device_id = 0
                if ":" in device:
                    try:
                        device_id = int(device.split(":")[1])
                    except (IndexError, ValueError):
                        device_id = 0

                # Determine model name: CLI override > site profile default > global config fallback
                model_name = overrides.model
                if model_name is None:
                    model_name = site_profile.default_model
                if model_name is None:
                    model_name = global_config.model_defaults.fallback_model

                print(f"DEBUG CLI: Creating GPUOptimizer with max_vram_mb={max_gpu_memory_mb}", flush=True)
                gpu_optimizer = GPUOptimizer(
                    model_name=model_name,
                    precision=precision,
                    # target_utilization uses GPUOptimizer default (0.40) to account for generation peak memory
                    device_id=device_id,
                    max_vram_mb=max_gpu_memory_mb,  # Use configured VRAM limit
                )
                gpu_config = gpu_optimizer.optimize()
                engine_kwargs["batch_size"] = gpu_config.batch_size

                # WS3: Pass hardware baseline to BatchStatsTracker for new language initialization
                # This allows new languages to start with GPU-calculated batch sizes instead of hardcoded values
                hardware_baseline = gpu_config.batch_size
                engine_kwargs["hardware_baseline"] = hardware_baseline

                logger.info(
                    f"GPU optimization enabled: batch_size={gpu_config.batch_size}, "
                    f"estimated_vram={gpu_config.estimated_vram_mb:.0f}MB "
                    f"({gpu_config.estimated_vram_mb/gpu_config.total_vram_mb*100:.1f}% of {gpu_config.total_vram_mb:.0f}MB)"
                )
                logger.info(f"GPU optimizer suggests hardware_baseline={hardware_baseline} for adaptive batch sizing")
            except Exception as e:
                logger.warning(
                    f"GPU optimization failed: {e}. Using default batch size."
                )
                # Don't set batch_size, will use engine default

        logger.info("Initializing Translation Engine...")

        # SR-02: Pass --output argument to engine if specified
        if args.output:
            output_path = Path(args.output)
            # SR-02c: Validate output path before engine creation (fail fast)
            validate_output_path(output_path)
            engine_kwargs["output_dir_override"] = output_path

            # Collision fix: Pass input_root to preserve directory structure
            if args.input:
                engine_kwargs["input_root"] = Path(args.input)

        # SR-03: Read sort_segments_by_length from config if CLI didn't override
        if "sort_segments_by_length" not in engine_kwargs:
            body_rules = site_profile.body
            if hasattr(body_rules, 'sort_segments_by_length'):
                engine_kwargs["sort_segments_by_length"] = body_rules.sort_segments_by_length

        # TC-BM-01: Initialize production metrics ingestor (OPT-IN)
        production_ingestor = None
        benchmark_config = load_benchmarking_config()

        # Check if enabled via CLI flag or config
        metrics_enabled = (
            args.enable_production_metrics
            or benchmark_config.get("production", {}).get("record_enabled", False)
        )

        logger.info(f"Production metrics recording: enabled={metrics_enabled}")

        if metrics_enabled:
            try:
                # Import only when needed (try relative first, fallback to absolute)
                try:
                    from .benchmarking.cli import get_benchmark_db_path
                    from .benchmarking.production_ingestor import ProductionMetricsIngestor
                    from .benchmarking.storage import BenchmarkDatabase
                except ImportError:
                    from benchmarking.cli import get_benchmark_db_path
                    from benchmarking.production_ingestor import ProductionMetricsIngestor
                    from benchmarking.storage import BenchmarkDatabase

                # Get database path from config
                db_path = get_benchmark_db_path(purpose="production")
                db_path.parent.mkdir(parents=True, exist_ok=True)

                # Get min_segments threshold from config
                min_segments = benchmark_config.get("production", {}).get("min_segments_to_record", 1)

                # Initialize database and ingestor
                db = BenchmarkDatabase(db_path)
                production_ingestor = ProductionMetricsIngestor(db, enabled=True, min_segments=min_segments)

                logger.info(f"Production metrics enabled, recording to {db_path} (min_segments={min_segments})")
            except Exception as e:
                logger.warning(
                    f"Failed to initialize production metrics: {e}. "
                    "Translation will continue without metrics recording."
                )
                production_ingestor = None

        # CHT-04: Handle --rebuild-content-hashes flag
        if overrides.rebuild_content_hashes:
            # Determine output directory (same logic as later in this function)
            output_dir = Path(args.output) if args.output else Path(
                site_profile.output_dir if hasattr(site_profile, 'output_dir') else "output"
            )
            metadata_file = output_dir / ".translation_metadata.json"

            if metadata_file.exists():
                logger.info(f"Rebuild content hashes requested, removing {metadata_file}")
                try:
                    metadata_file.unlink()
                    logger.info("Metadata file deleted, will rebuild hashes from scratch")
                except Exception as e:
                    logger.warning(f"Failed to delete metadata file: {e}")

        # PROD-004: Language-aware model selection (Agent-E)
        # If --auto-select-model flag is enabled, select best model per language pair
        # This happens AFTER model_loader is created but BEFORE engine initialization
        if args.auto_select_model and overrides.model:
            logger.error("Cannot use both --auto-select-model and --model flags. Please choose one.")
            return 1

        if args.auto_select_model:
            logger.info("Auto-selection enabled - will select best model for target language(s)")
            # Import selector module
            try:
                from .model_runtime.hardware import HardwareDetector
                from .model_runtime.selector import LanguageAwareModelSelector
            except ImportError:
                from model_runtime.hardware import HardwareDetector
                from model_runtime.selector import LanguageAwareModelSelector

            # Detect hardware for selector
            hardware_detector = HardwareDetector()
            hardware_info = hardware_detector.detect()

            # Get fallback model from config
            fallback_model = global_config.model_defaults.fallback_model if hasattr(global_config, 'model_defaults') else None

            # Create selector
            selector = LanguageAwareModelSelector(
                registry=model_registry,
                hardware_info=hardware_info,
                fallback_model=fallback_model
            )

            # Note: Actual model selection happens per-language in the engine
            # We pass the selector to engine_kwargs so engine can use it
            engine_kwargs["model_selector"] = selector
            logger.info("Model selector initialized and passed to engine")

        engine = TranslationEngine(
            config_service=config_service,
            tm=tm,
            model_loader=model_loader,
            progress_tracker=translation_progress_tracker,
            production_ingestor=production_ingestor,
            **engine_kwargs,
        )

        # SR-01, SR-05: Set up unified signal handler for graceful shutdown
        # Coordinates telemetry cleanup AND engine shutdown without conflicts
        setup_unified_signal_handler(engine)

        # Determine input path
        if args.input:
            input_path = Path(os.path.expandvars(args.input))
        else:
            # Use first content root from site profile
            input_path = Path(os.path.expandvars(site_profile.content_roots[0]))

        logger.info(f"Input path: {input_path}")

        # Determine output directory
        output_dir = Path(args.output) if args.output else Path(site_profile.output_dir if hasattr(site_profile, 'output_dir') else "output")

        if overrides.dry_run:
            resolved_model = overrides.model or getattr(site_profile, 'default_model', None) or "m2m100_418m"
            manifest_path = _write_dry_run_manifest(
                site_id=args.site,
                site_profile=site_profile,
                input_path=input_path,
                target_langs=target_langs,
                model=resolved_model,
                engine=engine,
                filter_source_files_func=filter_source_files,
                max_files=getattr(args, 'max_files', 0),
                force_retranslate=overrides.force_retranslate,
            )
            logger.info(f"Dry-run manifest written: {manifest_path}")
            return 0

        # RES-02: Initialize translation progress tracker for crash recovery
        if translation_progress_tracker is None and resume_enabled:
            # Create new tracker for this run
            translation_progress_tracker = ProgressTracker(
                progress_dir=progress_dir_path,
                site_id=args.site,
                source_dir=input_path,
                output_dir=output_dir,
                target_langs=target_langs
            )

            # Initialize with file count (filter out already-translated files)
            if input_path.is_dir():
                all_files = list(input_path.glob("**/*.md"))
                # Filter to only source files, excluding translated files
                try:
                    source_files = filter_source_files(all_files, site_profile, target_langs)
                    logger.info(f"Translation progress tracker initialized: {len(source_files)} source files (filtered {len(all_files) - len(source_files)} translated files)")
                except (ValueError, TypeError, AttributeError) as e:
                    logger.warning(f"File filtering failed: {e}. Using all markdown files for progress tracking.")
                    source_files = all_files
                translation_progress_tracker.initialize(source_files)
            else:
                translation_progress_tracker.initialize([input_path])

        # Initialize progress tracker if enabled
        if not overrides.no_progress:
            metrics_file_path = Path(overrides.metrics_file) if overrides.metrics_file else None
            progress_tracker = init_progress_tracker(
                update_interval=overrides.metrics_interval,
                metrics_file=metrics_file_path,
                metrics_only=overrides.metrics_only,
                show_progress=True,
            )

            # Resolve model name with priority: CLI > profile > system default
            resolved_model = overrides.model or getattr(site_profile, 'default_model', None) or "m2m100_418m"
            if overrides.model:
                logger.debug(f"Using CLI-specified model: {resolved_model}")
            elif getattr(site_profile, 'default_model', None):
                logger.debug(f"Using profile default_model: {resolved_model}")
            else:
                logger.debug(f"Using system default model: {resolved_model}")

            # Count files for progress tracking (filter out already-translated files)
            if input_path.is_dir():
                all_md_files = list(input_path.glob("**/*.md"))
                # Filter to only source files, excluding translated files
                try:
                    md_files = filter_source_files(all_md_files, site_profile, target_langs)
                    logger.info(f"Progress tracking enabled: {len(md_files)} source files to process (filtered {len(all_md_files) - len(md_files)} translated files)")
                except (ValueError, TypeError, AttributeError) as e:
                    logger.warning(f"File filtering failed: {e}. Using all markdown files for progress count.")
                    md_files = all_md_files

                # Pre-parse all files to discover accurate segment totals
                source_lang = getattr(site_profile, 'default_source_lang', 'en')
                total_segments = engine._discover_all_segments(
                    files=md_files,
                    target_langs=target_langs,
                    site_id=args.site,
                    source_lang=source_lang,
                )

                progress_tracker.start(files_total=len(md_files), target_langs=target_langs)
                # Set accurate segment total from pre-parsing
                progress_tracker.set_totals(segments=total_segments)
                progress_tracker.set_model(
                    model_name=resolved_model,
                    device=device,
                )
            else:
                progress_tracker.start(files_total=1, target_langs=target_langs)
                progress_tracker.set_model(
                    model_name=resolved_model,
                    device=device,
                )

        # Translate files
        if input_path.is_file():
            logger.info(f"Translating single file: {input_path}")
            result = engine.translate_file(
                site_id=args.site,
                file_path=input_path,
                target_langs=target_langs,
                force=overrides.force_retranslate,  # T202: federated-splashing-panda
            )

            # VA-04: Generate verification report if requested
            if overrides.verification_report and overrides.verify:
                _generate_verification_report(
                    report_path=Path(overrides.verification_report),
                    results=[(input_path, result)],
                )

            if result.success:
                logger.info("Translation completed successfully")
                # P1-12: Track translation success via telemetry
                if shared_engines:
                    try:
                        shared_engines.telemetry.track_event(
                            event_type="translation_success",
                            site_id=args.site,
                            file_path=str(input_path),
                            target_langs=target_langs
                        )
                    except Exception as e:
                        logger.debug(f"Telemetry tracking failed (non-fatal): {e}")
                # RES-02: Clear progress on successful completion
                if translation_progress_tracker:
                    translation_progress_tracker.clear()
                    logger.info("Progress cleared - translation complete")
                return 0
            else:
                logger.error(f"Translation failed: {'; '.join(result.errors)}")
                # P1-12: Track translation failure via telemetry
                if shared_engines:
                    try:
                        shared_engines.telemetry.track_event(
                            event_type="translation_failure",
                            site_id=args.site,
                            file_path=str(input_path),
                            errors=result.errors
                        )
                    except Exception as e:
                        logger.debug(f"Telemetry tracking failed (non-fatal): {e}")
                logger.info("Progress saved. Fix the issue and resume with the same command.")
                return 1

        elif input_path.is_dir():
            logger.info(f"Translating directory: {input_path}")
            result = engine.translate_directory(
                site_id=args.site,
                directory=input_path,
                target_langs=target_langs,
                skip_site_lock=getattr(args, '_skip_site_lock', False),  # TC1
                max_files=getattr(args, 'max_files', 0),
            )

            logger.info(f"Translation completed: {result.total_files} files processed")
            logger.info(f"Success: {result.successful_files}, Failed: {result.failed_files}")

            # P1-12: Track directory translation completion via telemetry
            if shared_engines:
                try:
                    shared_engines.telemetry.track_event(
                        event_type="directory_translation_complete",
                        site_id=args.site,
                        total_files=result.total_files,
                        successful_files=result.successful_files,
                        failed_files=result.failed_files,
                        target_langs=target_langs
                    )
                except Exception as e:
                    logger.debug(f"Telemetry tracking failed (non-fatal): {e}")

            # VA-04: Generate verification report if requested
            if overrides.verification_report and overrides.verify:
                _generate_verification_report(
                    report_path=Path(overrides.verification_report),
                    results=result,
                )

            # RES-02: Clear progress on successful completion
            if result.failed_files == 0:
                if translation_progress_tracker:
                    translation_progress_tracker.clear()
                    logger.info("Progress cleared - all translations complete")
            else:
                logger.info("Progress saved. Some translations failed - resume to retry.")

            # P1-12: Auto-commit translations using CommitEngine (if available) or fallback
            if result.successful_files > 0:
                # Check if commit should happen based on CLI flags
                should_commit = True
                if hasattr(args, 'auto_commit') and args.auto_commit is False:
                    should_commit = False
                elif overrides.dry_run:
                    should_commit = False

                if should_commit:
                    # Try to use CommitEngine from shared_engines (preferred)
                    if shared_engines and shared_engines.commit:
                        try:
                            # Collect output files from result
                            output_files = []
                            for file_result in result.file_results:
                                if file_result.success and file_result.outputs:
                                    # file_result.outputs is a dict: {target_lang: output_path}
                                    # Extract the path values, not the language keys
                                    output_files.extend([Path(f) for f in file_result.outputs.values()])

                            if output_files:
                                # Calculate TM stats from result
                                tm_stats = {}
                                if hasattr(result, 'tm_hit_rate'):
                                    tm_stats['hit_rate'] = result.tm_hit_rate
                                if hasattr(result, 'cache_hits'):
                                    tm_stats['cache_hits'] = result.cache_hits
                                if hasattr(result, 'cache_misses'):
                                    tm_stats['cache_misses'] = result.cache_misses

                                commit_result = shared_engines.commit.commit_if_enabled(
                                    output_files=output_files,
                                    site_id=args.site,
                                    target_langs=target_langs,
                                    run_id="cli-run",
                                    translation_result=result,
                                    model_id=args.model or "default",
                                    tm_stats=tm_stats
                                )

                                if commit_result.success:
                                    if commit_result.files_committed > 0:
                                        logger.info(f"Committed {commit_result.files_committed} files")
                                    else:
                                        logger.debug("No files to commit (already committed or no changes)")
                                else:
                                    logger.warning(f"Commit failed (non-fatal): {commit_result.error}")
                            else:
                                logger.debug("No output files to commit")

                        except Exception as e:
                            logger.warning(f"CommitEngine error (non-fatal): {e}")

                    # Fallback to direct auto_commit_translations if engines not available
                    else:
                        try:
                            from src.observability.git_commit_helper import auto_commit_translations

                            commit_success = auto_commit_translations(
                                result=result,
                                site_id=args.site,
                                target_langs=target_langs,
                                run_id="cli-run",
                                config_service=config_service,
                                commit_message_override=getattr(args, 'commit_message_override', None),
                                no_commit=False,
                            )

                            if not commit_success:
                                logger.debug("Git commit failed (non-fatal)")

                        except Exception as e:
                            logger.warning(f"Auto-commit error (non-fatal): {e}")

            # Check for no-op (0 files processed)
            if result.total_files == 0:
                logger.error(
                    "No files were processed. Translation cannot proceed. "
                    "Possible causes: input path doesn't exist, no .md files found, "
                    "all files filtered out, or incorrect working directory."
                )
                return 1

            return 0 if result.failed_files == 0 else 1

        else:
            logger.error(f"Input path not found: {input_path}")
            return 1

    except KeyboardInterrupt:
        # RES-06: Handle second Ctrl+C during graceful shutdown
        logger.warning("Translation interrupted by user")
        try:
            # Ensure engine shutdown is performed if engine was created
            engine._perform_shutdown()
        except NameError:
            # Engine wasn't created yet, nothing to shut down
            pass
        except Exception as shutdown_err:
            logger.warning(f"Shutdown may be incomplete: {shutdown_err}")
        logger.info("Progress saved. Resume with the same command.")
        if progress_tracker:
            stop_progress_tracker()
        return 130  # Standard Unix exit code for Ctrl+C

    except Exception as e:
        logger.exception(f"Translation failed with error: {e}")
        logger.info("Progress saved. Fix the issue and resume with the same command.")
        if progress_tracker:
            stop_progress_tracker()
        return 1

    finally:
        # Stop progress tracking and show final summary
        if progress_tracker:
            stop_progress_tracker()


def cmd_unlock() -> int:
    """
    Force unlock a site (TC2).

    Usage: python -m src.cli unlock --site <site> [--force] [--yes]

    Returns:
        Exit code (0 = success, 1 = failure, 2 = invalid usage)
    """
    import argparse
    parser = argparse.ArgumentParser(
        prog="translate-hugo unlock",
        description="Force unlock a site (use with caution)"
    )
    parser.add_argument('unlock', help=argparse.SUPPRESS)  # Positional arg (already consumed)
    parser.add_argument('--site', required=True, help='Site identifier')
    parser.add_argument(
        '--force',
        action='store_true',
        help='Force unlock even if holder process appears alive (DANGEROUS)'
    )
    parser.add_argument(
        '--yes',
        action='store_true',
        help='Skip confirmation prompt (for automation)'
    )

    args = parser.parse_args()

    from src.translation_engine.engine import get_site_lock
    from src.utils.file_lock import diagnose_lock

    # Show diagnostics first
    print("Running diagnostics before unlock...\n")
    diagnose_lock(args.site)

    # Confirm with user (unless --yes or --force)
    if not args.yes and not args.force:
        # CRITICAL: Non-interactive mode must use --yes flag
        if not sys.stdin.isatty():
            print("\nERROR: Running in non-interactive mode without --yes flag")
            print("Use --yes to skip confirmation in automation")
            return 2  # Exit code 2 = invalid usage

        response = input("\nProceed with unlock? [y/N]: ")
        if response.lower() != 'y':
            print("Unlock cancelled")
            return 0

    # Attempt force unlock
    lock = get_site_lock(args.site)
    check_pid = not args.force

    try:
        if lock.force_unlock(check_pid=check_pid):
            print(f"\nSuccessfully unlocked site: {args.site}")
            try:
                from src.observability.worker_telemetry import emit_worker_event
                emit_worker_event(
                    agent_name="hugo-translator", job_type="cli_unlock", trigger_type="cli",
                    status="success", metrics={"site": args.site, "force": args.force},
                )
            except Exception:
                pass
            return 0  # Success
        else:
            print(f"\nFailed to unlock site: {args.site}")
            print("Holder process is still running. Use --force to override (DANGEROUS).")
            try:
                from src.observability.worker_telemetry import emit_worker_event
                emit_worker_event(
                    agent_name="hugo-translator", job_type="cli_unlock", trigger_type="cli",
                    status="failure", metrics={"site": args.site, "force": args.force, "reason": "holder_alive"},
                )
            except Exception:
                pass
            return 1  # Failure
    except Exception as e:
        print(f"\nError during unlock: {e}")
        try:
            from src.observability.worker_telemetry import emit_worker_event
            emit_worker_event(
                agent_name="hugo-translator", job_type="cli_unlock", trigger_type="cli",
                status="failure", error_summary=str(e)[:500], metrics={"site": args.site},
            )
        except Exception:
            pass
        return 1


def cmd_diagnose_lock() -> int:
    """
    Diagnose lock file issues for a site (TC2).

    Usage: python -m src.cli diagnose-lock --site <site>

    Returns:
        Exit code (0 = success)
    """
    import argparse
    parser = argparse.ArgumentParser(
        prog="translate-hugo diagnose-lock",
        description="Diagnose lock file issues for a site"
    )
    parser.add_argument('diagnose_lock', nargs='?', help=argparse.SUPPRESS)  # Positional (already consumed)
    parser.add_argument('--site', required=True, help='Site identifier')

    args = parser.parse_args()

    from src.utils.file_lock import diagnose_lock

    diagnose_lock(args.site)
    try:
        from src.observability.worker_telemetry import emit_worker_event
        emit_worker_event(
            agent_name="hugo-translator", job_type="cli_diagnose_lock", trigger_type="cli",
            status="success", metrics={"site": args.site},
        )
    except Exception:
        pass
    return 0


def main() -> int:
    """
    Main CLI entry point.

    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    # TC2: Handle special lock management commands
    if len(sys.argv) > 1:
        if sys.argv[1] == "diagnose-lock":
            return cmd_diagnose_lock()
        elif sys.argv[1] == "unlock":
            return cmd_unlock()

    parser = create_parser()
    args = parser.parse_args()

    return translate_site(args)


if __name__ == "__main__":
    sys.exit(main())
