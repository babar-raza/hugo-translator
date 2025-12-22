#!/usr/bin/env python3
"""
Test translation models on real blog content.

Translates the same blog post with different models for quality comparison.
"""
import logging
import subprocess
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def translate_with_model(model_id: str, input_file: str, target_lang: str, output_suffix: str):
    """Translate a file with a specific model."""
    logger.info(f"\n{'=' * 80}")
    logger.info(f"Translating with model: {model_id} to {target_lang}")
    logger.info(f"Input: {input_file}")
    logger.info(f"{'=' * 80}\n")

    # Build command
    cmd = [
        r"C:\Users\prora\anaconda3\envs\hugo-translator\python.exe",
        "-m", "src.cli",
        "--site", "blog.aspose.net",
        "--input", input_file,
        "--target-langs", target_lang,
        "--model", model_id,
        "--log-level", "INFO"
    ]

    try:
        # Run translation
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

        if result.returncode == 0:
            logger.info(f"✓ Translation with {model_id} completed successfully")

            # Rename output file to include model name
            input_path = Path(input_file)
            output_file = input_path.parent / f"{input_path.stem}.{target_lang}.md"
            renamed_file = input_path.parent / f"{input_path.stem}.{target_lang}.{output_suffix}.md"

            if output_file.exists():
                output_file.rename(renamed_file)
                logger.info(f"✓ Saved as: {renamed_file}")
                return True
            else:
                logger.error(f"✗ Output file not found: {output_file}")
                return False
        else:
            logger.error(f"✗ Translation failed with {model_id}")
            logger.error(f"Error: {result.stderr}")
            return False

    except subprocess.TimeoutExpired:
        logger.error(f"✗ Translation with {model_id} timed out")
        return False
    except Exception as e:
        logger.error(f"✗ Error: {e}")
        return False

def main():
    # Test file
    input_file = r"D:\onedrive\Documents\GitHub\aspose.net\content\blog.aspose.net\slides\accessibility-automation-extracting-alt-text-and-creating-transcripts\index.md"
    target_lang = "es"

    # Models to test
    models = [
        ("m2m100_418m", "418m"),        # Baseline
        ("m2m100_1.2b", "1.2b"),        # Larger M2M100
    ]

    logger.info("=" * 80)
    logger.info("TESTING TRANSLATION MODELS ON REAL BLOG POST")
    logger.info("=" * 80)

    results = {}
    for model_id, suffix in models:
        success = translate_with_model(model_id, input_file, target_lang, suffix)
        results[model_id] = success

    # Summary
    logger.info(f"\n{'=' * 80}")
    logger.info("SUMMARY")
    logger.info(f"{'=' * 80}")

    for model_id, success in results.items():
        status = "✓ SUCCESS" if success else "✗ FAILED"
        logger.info(f"{model_id}: {status}")

    logger.info(f"\n{'=' * 80}")
    logger.info("TEST COMPLETE")
    logger.info(f"{'=' * 80}")

if __name__ == "__main__":
    main()
