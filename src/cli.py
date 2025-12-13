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
import sys
from pathlib import Path
from typing import Dict, List, Optional

try:
    # Relative imports (when used as package)
    from .translation_engine import TranslationEngine
    from .translation_engine.models import TranslationResult
    from .tm import TranslationMemory
    from .model_runtime import ModelLoader
    from .utils.config_loader import ConfigService
    from .utils.models import ValidationSettings, TerminologySettings
except ImportError:
    # Absolute imports (when run directly)
    from translation_engine import TranslationEngine
    from translation_engine.models import TranslationResult
    from tm import TranslationMemory
    from model_runtime import ModelLoader
    from utils.config_loader import ConfigService
    from utils.models import ValidationSettings, TerminologySettings

logger = logging.getLogger(__name__)


class CLIConfigOverrides:
    """Container for CLI-provided configuration overrides."""

    def __init__(self, args: argparse.Namespace):
        """Initialize from parsed CLI arguments."""
        self.validation_mode: Optional[str] = args.validation_mode
        self.disable_validation: bool = args.disable_validation
        self.enable_terminology: Optional[bool] = (
            True if args.enable_terminology else (False if args.disable_terminology else None)
        )
        self.terminology_mode: Optional[str] = args.terminology_mode
        self.max_retries: Optional[int] = args.max_retries
        self.validation_config_path: Optional[str] = args.validation_config
        self.terminology_config_path: Optional[str] = args.terminology_config
        self.dry_run: bool = args.dry_run
        self.save_rejected: bool = args.save_rejected

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
        if self.disable_validation:
            overrides["enable_validation"] = False
        elif self.validation_mode == "off":
            overrides["enable_validation"] = False
        else:
            overrides["enable_validation"] = True

        # Validation mode
        if self.validation_mode and self.validation_mode != "off":
            overrides["validation_mode"] = self.validation_mode

        # Terminology control
        if self.enable_terminology is not None:
            overrides["enable_terminology"] = self.enable_terminology

        if self.terminology_mode:
            overrides["terminology_mode"] = self.terminology_mode

        # Retry control
        if self.max_retries is not None:
            overrides["max_retries"] = self.max_retries

        # Dry run and save rejected
        overrides["dry_run"] = self.dry_run
        overrides["save_rejected"] = self.save_rejected

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

  # Use custom validation config
  translate-hugo --site products.aspose.net --validation-config ./custom-validation.yaml

  # Enable terminology with validation mode
  translate-hugo --site products.aspose.net --enable-terminology --terminology-mode both

  # Preview decisions without writing files
  translate-hugo --site products.aspose.net --dry-run

  # Increase retry attempts
  translate-hugo --site products.aspose.net --max-retries 5
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
        help="Output directory (overrides site profile)",
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

    # Configuration
    config_group = parser.add_argument_group("Configuration")

    config_group.add_argument(
        "--config-root",
        default="./config",
        help="Configuration root directory (default: ./config)",
    )

    return parser


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
        if overrides.disable_validation:
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
        tm = TranslationMemory(
            data_dir=global_config.tm_data_dir,
            enable_semantic=site_profile.tm_prefs.use_semantic_tm,
        )

        logger.info("Initializing Model Loader...")
        model_loader = ModelLoader(cache_dir=global_config.model_cache_dir)

        # Get engine overrides from CLI
        engine_kwargs = overrides.get_engine_overrides()

        logger.info("Initializing Translation Engine...")
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
            )

            if result.success:
                logger.info("Translation completed successfully")
                return 0
            else:
                logger.error(f"Translation failed: {result.error}")
                return 1

        elif input_path.is_dir():
            logger.info(f"Translating directory: {input_path}")
            result = engine.translate_directory(
                site_id=args.site,
                directory=input_path,
                target_langs=target_langs,
            )

            logger.info(f"Translation completed: {result.total_files} files processed")
            logger.info(f"Success: {result.success_count}, Failed: {result.failed_count}")

            return 0 if result.failed_count == 0 else 1

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
