"""
CTranslate2 Model Conversion Pipeline.

Offline conversion of HuggingFace models to CT2 format with INT8 quantization.
"""
import argparse
import logging
import shutil
import sys
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)


class CT2ConversionPipeline:
    """
    Pipeline for converting HuggingFace models to CTranslate2 format.

    Supports INT8/INT16/FLOAT16 quantization for CPU optimization.
    """

    def __init__(self) -> None:
        """Initialize conversion pipeline."""
        # Verify ctranslate2 is installed
        try:
            import ctranslate2  # noqa: F401
            self._ct2_available = True
        except ImportError:
            raise ImportError(
                "ctranslate2 is not installed. Install with: pip install .[gpu]"
            )

    def convert_model(
        self,
        model_path: Path | str,
        output_path: Path | str,
        quantization: Literal["int8", "int16", "float16", "float32"] = "int8",
        force: bool = False,
    ) -> bool:
        """
        Convert HuggingFace model to CTranslate2 format.

        Args:
            model_path: Path to HuggingFace model directory or model ID
            output_path: Path to output CT2 model directory
            quantization: Quantization type (int8 recommended for CPU)
            force: Overwrite existing output directory

        Returns:
            True if conversion succeeded, False otherwise
        """
        model_path = Path(model_path) if isinstance(model_path, str) else model_path
        output_path = Path(output_path) if isinstance(output_path, str) else output_path

        # Check if output already exists
        if output_path.exists():
            if not force:
                logger.error(
                    f"Output path {output_path} already exists. Use --force to overwrite."
                )
                return False
            logger.info(f"Removing existing output directory: {output_path}")
            shutil.rmtree(output_path)

        # Create output directory
        output_path.mkdir(parents=True, exist_ok=True)

        try:
            from ctranslate2.converters import TransformersConverter

            logger.info(f"Converting {model_path} to CTranslate2 format...")
            logger.info(f"Quantization: {quantization}")
            logger.info(f"Output path: {output_path}")

            # Convert model
            converter = TransformersConverter(str(model_path))
            converter.convert(
                output_dir=str(output_path),
                quantization=quantization,
                force=force,
            )

            logger.info("Conversion completed successfully")
            return True

        except Exception as e:
            logger.error(f"Conversion failed: {e}")
            # Cleanup on failure
            if output_path.exists():
                logger.info(f"Cleaning up failed conversion: {output_path}")
                shutil.rmtree(output_path)
            return False

    def validate_ct2_model(self, model_path: Path | str) -> bool:
        """
        Validate that a CT2 model directory is valid.

        Args:
            model_path: Path to CT2 model directory

        Returns:
            True if model is valid, False otherwise
        """
        model_path = Path(model_path) if isinstance(model_path, str) else model_path

        if not model_path.exists():
            logger.error(f"Model path does not exist: {model_path}")
            return False

        if not model_path.is_dir():
            logger.error(f"Model path is not a directory: {model_path}")
            return False

        # Check for required files
        required_files = ["model.bin"]
        optional_files = ["config.json", "shared_vocabulary.txt", "shared_vocabulary.json"]

        missing_required = []
        for file in required_files:
            if not (model_path / file).exists():
                missing_required.append(file)

        if missing_required:
            logger.error(f"Missing required files: {missing_required}")
            return False

        # Try to load model
        try:
            import ctranslate2

            translator = ctranslate2.Translator(str(model_path), device="cpu")
            logger.info(f"Model validation successful: {model_path}")
            logger.info(f"Model files: {list(model_path.iterdir())}")
            del translator
            return True

        except Exception as e:
            logger.error(f"Model validation failed: {e}")
            return False

    def get_model_info(self, model_path: Path | str) -> dict | None:
        """
        Get information about a CT2 model.

        Args:
            model_path: Path to CT2 model directory

        Returns:
            Dictionary with model info, or None if model is invalid
        """
        model_path = Path(model_path) if isinstance(model_path, str) else model_path

        if not self.validate_ct2_model(model_path):
            return None

        try:
            import json

            info = {
                "model_path": str(model_path),
                "size_mb": sum(f.stat().st_size for f in model_path.rglob("*") if f.is_file())
                / (1024 * 1024),
                "files": [f.name for f in model_path.iterdir() if f.is_file()],
            }

            # Try to read config
            config_path = model_path / "config.json"
            if config_path.exists():
                with open(config_path, encoding="utf-8") as f:
                    config = json.load(f)
                    info["config"] = config

            return info

        except Exception as e:
            logger.error(f"Failed to get model info: {e}")
            return None

    def check_disk_space(self, output_path: Path | str, required_mb: int = 500) -> bool:
        """
        Check if there is enough disk space for conversion.

        Args:
            output_path: Path to output directory
            required_mb: Required disk space in MB (default 500MB)

        Returns:
            True if enough space available, False otherwise
        """
        output_path = Path(output_path) if isinstance(output_path, str) else output_path

        try:
            import shutil

            # Get disk usage
            stat = shutil.disk_usage(output_path.parent if output_path.parent.exists() else "/")
            available_mb = stat.free / (1024 * 1024)

            if available_mb < required_mb:
                logger.error(
                    f"Insufficient disk space. Required: {required_mb}MB, "
                    f"Available: {available_mb:.0f}MB"
                )
                return False

            logger.info(f"Disk space check passed. Available: {available_mb:.0f}MB")
            return True

        except Exception as e:
            logger.error(f"Failed to check disk space: {e}")
            return False


def main() -> int:
    """CLI entry point for model conversion."""
    parser = argparse.ArgumentParser(
        description="Convert HuggingFace models to CTranslate2 format"
    )
    parser.add_argument(
        "--model",
        required=True,
        help="Path to HuggingFace model or model ID (e.g., m2m100_418m)",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output path for CT2 model (e.g., models/ct2/m2m100_418m)",
    )
    parser.add_argument(
        "--quantization",
        choices=["int8", "int16", "float16", "float32"],
        default="int8",
        help="Quantization type (default: int8)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing output directory",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate model after conversion",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Create pipeline
    try:
        pipeline = CT2ConversionPipeline()
    except ImportError as e:
        logger.error(str(e))
        return 1

    # Check disk space
    if not pipeline.check_disk_space(args.output, required_mb=500):
        return 1

    # Convert model
    success = pipeline.convert_model(
        model_path=args.model,
        output_path=args.output,
        quantization=args.quantization,
        force=args.force,
    )

    if not success:
        return 1

    # Validate if requested
    if args.validate:
        logger.info("Validating converted model...")
        if not pipeline.validate_ct2_model(args.output):
            return 1

        # Print model info
        info = pipeline.get_model_info(args.output)
        if info:
            logger.info(f"Model size: {info['size_mb']:.1f}MB")
            logger.info(f"Model files: {', '.join(info['files'])}")

    logger.info("Conversion completed successfully!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
