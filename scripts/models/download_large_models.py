#!/usr/bin/env python3
"""
Download larger translation models for improved quality.

Downloads M2M100-1.2B and NLLB-200 models to models/ directory.
"""

import logging
import sys
from pathlib import Path

from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def download_model(model_id: str, save_dir: Path) -> None:
    """
    Download model and tokenizer from HuggingFace.

    Args:
        model_id: HuggingFace model ID
        save_dir: Directory to save model to
    """
    logger.info(f"Downloading {model_id}...")
    logger.info(f"Save directory: {save_dir}")

    try:
        # Create save directory
        save_dir.mkdir(parents=True, exist_ok=True)

        # Download tokenizer
        logger.info(f"Downloading tokenizer for {model_id}...")
        tokenizer = AutoTokenizer.from_pretrained(model_id)
        tokenizer.save_pretrained(save_dir)
        logger.info(f"✓ Tokenizer saved to {save_dir}")

        # Download model
        logger.info(f"Downloading model {model_id}... (this may take several minutes)")
        model = AutoModelForSeq2SeqLM.from_pretrained(model_id)
        model.save_pretrained(save_dir)
        logger.info(f"✓ Model saved to {save_dir}")

        # Calculate size
        total_size = sum(f.stat().st_size for f in save_dir.rglob("*") if f.is_file())
        size_mb = total_size / (1024 * 1024)
        logger.info(f"✓ Total size: {size_mb:.1f} MB")

    except Exception as e:
        logger.error(f"Failed to download {model_id}: {e}")
        raise


def main():
    """Download all large models."""
    # Base models directory
    models_dir = Path(__file__).parent.parent / "models"

    logger.info("=" * 80)
    logger.info("LARGE MODEL DOWNLOAD SCRIPT")
    logger.info("=" * 80)
    logger.info("")

    # Models to download
    models = [
        ("facebook/m2m100_1.2B", "m2m100_1.2b"),
        ("facebook/nllb-200-distilled-600M", "nllb_200_600m"),
        ("facebook/nllb-200-1.3B", "nllb_200_1.3b"),
    ]

    logger.info(f"Will download {len(models)} models:")
    for hf_id, local_name in models:
        logger.info(f"  - {hf_id} → models/{local_name}/")
    logger.info("")

    # Download each model
    for idx, (hf_id, local_name) in enumerate(models, 1):
        logger.info("")
        logger.info(f"[{idx}/{len(models)}] Processing {hf_id}")
        logger.info("-" * 80)

        save_dir = models_dir / local_name

        # Check if already downloaded
        if save_dir.exists() and list(save_dir.rglob("*.bin")):
            logger.info(f"Model already exists at {save_dir}")
            logger.info("Skipping download. Delete directory to re-download.")
            continue

        try:
            download_model(hf_id, save_dir)
            logger.info(f"✓ Successfully downloaded {hf_id}")
        except Exception as e:
            logger.error(f"✗ Failed to download {hf_id}: {e}")
            logger.error("Continuing with next model...")
            continue

    logger.info("")
    logger.info("=" * 80)
    logger.info("DOWNLOAD COMPLETE")
    logger.info("=" * 80)
    logger.info("")
    logger.info("Downloaded models:")
    for hf_id, local_name in models:
        save_dir = models_dir / local_name
        if save_dir.exists():
            total_size = sum(f.stat().st_size for f in save_dir.rglob("*") if f.is_file())
            size_mb = total_size / (1024 * 1024)
            logger.info(f"  ✓ {local_name}: {size_mb:.1f} MB")
        else:
            logger.info(f"  ✗ {local_name}: Not downloaded")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\nDownload interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
