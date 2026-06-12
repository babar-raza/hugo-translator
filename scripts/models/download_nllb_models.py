#!/usr/bin/env python3
"""
Download NLLB-200 models for improved translation quality.
"""

import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def download_nllb_600m():
    """Download NLLB-200-distilled-600M model."""
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

    model_id = "facebook/nllb-200-distilled-600M"
    save_dir = Path("models/nllb_200_600m")

    logger.info(f"Downloading {model_id}...")
    logger.info(f"Save directory: {save_dir}")

    # Remove existing directory to force re-download
    if save_dir.exists():
        import shutil

        logger.info(f"Removing existing directory: {save_dir}")
        shutil.rmtree(save_dir)

    save_dir.mkdir(parents=True, exist_ok=True)

    # Download tokenizer
    logger.info("Downloading tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    tokenizer.save_pretrained(save_dir)
    logger.info("✓ Tokenizer saved")

    # Download model
    logger.info("Downloading model weights... (this will take several minutes)")
    model = AutoModelForSeq2SeqLM.from_pretrained(model_id)
    model.save_pretrained(save_dir)
    logger.info("✓ Model saved")

    # Calculate size
    total_size = sum(f.stat().st_size for f in save_dir.rglob("*") if f.is_file())
    size_gb = total_size / (1024 * 1024 * 1024)
    logger.info(f"✓ Total size: {size_gb:.2f} GB")

    return save_dir


def download_nllb_1_3b():
    """Download NLLB-200-1.3B model."""
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

    model_id = "facebook/nllb-200-1.3B"
    save_dir = Path("models/nllb_200_1.3b")

    logger.info(f"Downloading {model_id}...")
    logger.info(f"Save directory: {save_dir}")

    # Remove existing directory to force re-download
    if save_dir.exists():
        import shutil

        logger.info(f"Removing existing directory: {save_dir}")
        shutil.rmtree(save_dir)

    save_dir.mkdir(parents=True, exist_ok=True)

    # Download tokenizer
    logger.info("Downloading tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    tokenizer.save_pretrained(save_dir)
    logger.info("✓ Tokenizer saved")

    # Download model
    logger.info("Downloading model weights... (this will take several minutes)")
    model = AutoModelForSeq2SeqLM.from_pretrained(model_id)
    model.save_pretrained(save_dir)
    logger.info("✓ Model saved")

    # Calculate size
    total_size = sum(f.stat().st_size for f in save_dir.rglob("*") if f.is_file())
    size_gb = total_size / (1024 * 1024 * 1024)
    logger.info(f"✓ Total size: {size_gb:.2f} GB")

    return save_dir


def main():
    """Download NLLB models."""
    logger.info("=" * 80)
    logger.info("NLLB MODEL DOWNLOAD")
    logger.info("=" * 80)
    logger.info("")

    try:
        # Download NLLB-200-distilled-600M
        logger.info("[1/2] Downloading NLLB-200-distilled-600M")
        logger.info("-" * 80)
        download_nllb_600m()
        logger.info("")

        # Download NLLB-200-1.3B
        logger.info("[2/2] Downloading NLLB-200-1.3B")
        logger.info("-" * 80)
        download_nllb_1_3b()
        logger.info("")

        logger.info("=" * 80)
        logger.info("✓ ALL DOWNLOADS COMPLETE")
        logger.info("=" * 80)

    except Exception as e:
        logger.error(f"Download failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\nDownload interrupted by user")
        sys.exit(1)
