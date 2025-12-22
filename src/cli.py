"""
Command-line interface for Hugo Translation System.

Provides CLI flags for:
- Validation control (mode, enable/disable, config paths)
- Terminology control (enable/disable, modes, config paths)
- Retry behavior (max retries)
- Output control (dry-run, save-rejected)

CLI flags override configuration file settings.
"""
import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

try:
    # Relative imports (when used as package)
    from .translation_engine import TranslationEngine
    from .translation_engine.models import TranslationResult, DirectoryResult
    from .tm import TranslationMemory
    from .tm.l1_cache import L1Cache
    from .tm.l2_persistent import L2PersistentTM
    from .tm.l3_semantic import L3SemanticTM
    from .model_runtime import ModelLoader
    from .model_runtime.registry import ModelRegistry
    from .model_runtime.cpu_optimizer import CPUOptimizer
    from .utils.config_loader import ConfigService
    from .utils.models import ValidationSettings, TerminologySettings
    from .verification.report import write_report
except ImportError:
    # Absolute imports (when run directly)
    from translation_engine import TranslationEngine
    from translation_engine.models import TranslationResult, DirectoryResult
    from tm import TranslationMemory
    from tm.l1_cache import L1Cache
    from tm.l2_persistent import L2PersistentTM
    from tm.l3_semantic import L3SemanticTM
    from model_runtime import ModelLoader
    from model_runtime.registry import ModelRegistry
    from model_runtime.cpu_optimizer import CPUOptimizer
    from utils.config_loader import ConfigService
    from utils.models import ValidationSettings, TerminologySettings
    from verification.report import write_report

logger = logging.getLogger(__name__)


class CLIConfigOverrides:
    """Container for CLI-provided configuration overrides."""

    def __init__(self, args: argparse.Namespace):
        """Initialize from parsed CLI arguments."""
        self.validation_mode: Optional[str] = args.validation_mode
        self.disable_validation: bool = args.disable_validation
        self.force_accept: bool = args.force_accept
        self.strict_reject: bool = args.strict_reject
        self.enable_terminology: Optional[bool] = (
            True if args.enable_terminology else (False if args.disable_terminology else None)
        )
        self.terminology_mode: Optional[str] = args.terminology_mode
        self.max_retries: Optional[int] = args.max_retries
        self.validation_config_path: Optional[str] = args.validation_config
        self.terminology_config_path: Optional[str] = args.terminology_config
        self.dry_run: bool = args.dry_run
        self.save_rejected: bool = args.save_rejected
        # VA-03: Post-translation verification flags
        self.verify: bool = args.verify
        self.fix: bool = args.fix
        # VA-04: Verification report output
        self.verification_report: Optional[str] = args.verification_report
        # TR-01: Token limit configurability
        self.max_tokens: Optional[int] = args.max_tokens
        # Model override
        self.model: Optional[str] = args.model
        # TC-CPU-02: Batch size override
        self.batch_size: Optional[int] = args.batch_size
        # Device and load mode overrides (federated-splashing-panda: T101)
        self.device: Optional[str] = None if args.device == "auto" else args.device
        self.load_mode: Optional[str] = None if args.load_mode == "auto" else args.load_mode
        # Cache behavior control (federated-splashing-panda: Phase 2 redesign)
        self.force_retranslate: bool = args.force_retranslate
        self.cache_write_mode: str = args.cache_write_mode
        # Multi-language processing (T301: federated-splashing-panda)
        self.parallel_languages: int = args.parallel_languages
        self.global_lang_rounds: int = args.global_lang_rounds
        self.global_lang_sort: str = args.global_lang_sort

    def apply_to_config_service(self, config_service: ConfigService) -> None:
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

    def get_engine_overrides(self) -> Dict[str, any]:
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

        return overrides


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

    # Multi-language processing (T301: federated-splashing-panda)
    multilang_group = parser.add_argument_group("Multi-Language Processing")

    multilang_group.add_argument(
        "--parallel-languages",
        type=int,
        default=0,
        metavar="N",
        help="Process up to N languages in parallel (0=disabled, default)",
    )

    multilang_group.add_argument(
        "--global-lang-rounds",
        type=int,
        default=0,
        metavar="N",
        help="Process N texts per language in round-robin fashion (0=disabled, default)",
    )

    multilang_group.add_argument(
        "--global-lang-sort",
        choices=["asc", "desc"],
        default="desc",
        metavar="ORDER",
        help="Sort languages by missing translation count: desc (most first, default) or asc (least first)",
    )

    # Configuration
    config_group = parser.add_argument_group("Configuration")

    config_group.add_argument(
        "--config-root",
        default="./config",
        help="Configuration root directory (default: ./config)",
    )

    return parser


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


def setup_logging(log_level: str, log_file: Optional[str] = None) -> None:
    """
    Configure logging for CLI.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        log_file: Optional file path to write logs to
    """
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


def translate_site(args: argparse.Namespace) -> int:
    """
    Execute translation for a site with CLI overrides.

    Args:
        args: Parsed CLI arguments

    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    try:
        # Setup logging
        setup_logging(args.log_level, args.log_file)

        logger.info(f"Starting translation for site: {args.site}")

        # Create CLI overrides
        overrides = CLIConfigOverrides(args)

        # Load configuration
        config_service = ConfigService(args.config_root)

        # Apply CLI config path overrides
        overrides.apply_to_config_service(config_service)

        # Load site profile
        site_profile = config_service.get_site_profile(args.site)

        # Override target languages if specified
        target_langs = args.target_langs if args.target_langs else site_profile.target_langs

        logger.info(f"Target languages: {', '.join(target_langs)}")

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

        l2_path = tm_data_dir / "l2_lmdb"
        l2_path.mkdir(parents=True, exist_ok=True)
        l2_persistent = L2PersistentTM(str(l2_path))

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
        registry_path = Path(args.config_root) / "model_registry.yaml"
        model_registry = ModelRegistry(registry_path)

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

        model_loader = ModelLoader(
            registry=model_registry,
            device=device,
            load_mode=overrides.load_mode  # T103: federated-splashing-panda
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

        logger.info("Initializing Translation Engine...")

        # SR-02: Pass --output argument to engine if specified
        if args.output:
            output_path = Path(args.output)
            # SR-02c: Validate output path before engine creation (fail fast)
            validate_output_path(output_path)
            engine_kwargs["output_dir_override"] = output_path

        engine = TranslationEngine(
            config_service=config_service,
            tm=tm,
            model_loader=model_loader,
            **engine_kwargs,
        )

        # Determine input path
        if args.input:
            input_path = Path(args.input)
        else:
            # Use first content root from site profile
            input_path = Path(site_profile.content_roots[0])

        logger.info(f"Input path: {input_path}")

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
                return 0
            else:
                logger.error(f"Translation failed: {'; '.join(result.errors)}")
                return 1

        elif input_path.is_dir():
            logger.info(f"Translating directory: {input_path}")
            result = engine.translate_directory(
                site_id=args.site,
                directory=input_path,
                target_langs=target_langs,
            )

            logger.info(f"Translation completed: {result.total_files} files processed")
            logger.info(f"Success: {result.successful_files}, Failed: {result.failed_files}")

            # VA-04: Generate verification report if requested
            if overrides.verification_report and overrides.verify:
                _generate_verification_report(
                    report_path=Path(overrides.verification_report),
                    results=result,
                )

            return 0 if result.failed_files == 0 else 1

        else:
            logger.error(f"Input path not found: {input_path}")
            return 1

    except KeyboardInterrupt:
        logger.warning("Translation interrupted by user")
        return 130  # Standard Unix exit code for Ctrl+C

    except Exception as e:
        logger.exception(f"Translation failed with error: {e}")
        return 1


def main() -> int:
    """
    Main CLI entry point.

    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    parser = create_parser()
    args = parser.parse_args()

    return translate_site(args)


if __name__ == "__main__":
    sys.exit(main())
