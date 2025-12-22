#!/usr/bin/env python3
"""Test all translation models with a short sample."""

import logging
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from src.model_runtime import ModelLoader
from src.model_runtime.registry import ModelRegistry

def test_model(model_id: str, text: str, src_lang: str, tgt_lang: str):
    """Test a single model."""
    logger.info(f"\n{'=' * 80}")
    logger.info(f"Testing model: {model_id}")
    logger.info(f"{'=' * 80}")

    try:
        # Initialize model registry and loader
        registry = ModelRegistry("config/model_registry.yaml")
        loader = ModelLoader(registry, device="cuda")

        # Load model
        logger.info(f"Loading model: {model_id}...")
        backend = loader.load_model(model_id)
        logger.info(f"✓ Model loaded successfully")

        # Translate
        logger.info(f"Translating from {src_lang} to {tgt_lang}...")
        logger.info(f"Source text: {text[:100]}...")

        translations = backend.translate([text], src_lang, tgt_lang)
        translation = translations[0]

        logger.info(f"✓ Translation: {translation[:200]}...")
        logger.info(f"✓ Translation complete (length: {len(translation)} chars)")

        # Unload model to free memory
        loader.unload_model(model_id)
        logger.info(f"✓ Model unloaded")

        return translation

    except Exception as e:
        logger.error(f"✗ Error testing {model_id}: {e}")
        import traceback
        traceback.print_exc()
        return None

def main():
    # Test text
    test_text = """
# Accessibility Excellence: Creating Screen Reader-Friendly SVG Slides

When it comes to digital presentations, accessibility is paramount. SVG (Scalable Vector Graphics)
presentations offer unique advantages for screen reader compatibility, making your content accessible
to users with visual impairments. This guide shows you how to create SVG slides with proper ARIA
labels and semantic structure using C# and Aspose.Slides for .NET Framework.
    """.strip()

    # Languages to test
    src_lang = "en"
    target_langs = ["es", "de"]

    # Models to test
    models = [
        "m2m100_418m",      # Baseline (418M parameters)
        "m2m100_1.2b",      # Larger M2M100 (1.2B parameters)
        "nllb_200_600m",    # NLLB-200 (600M parameters)
    ]

    results = {}

    for model_id in models:
        for tgt_lang in target_langs:
            key = f"{model_id}_{tgt_lang}"
            translation = test_model(model_id, test_text, src_lang, tgt_lang)
            results[key] = translation

    # Print summary
    logger.info(f"\n{'=' * 80}")
    logger.info("SUMMARY")
    logger.info(f"{'=' * 80}")

    for key, translation in results.items():
        if translation:
            logger.info(f"✓ {key}: {len(translation)} chars")
        else:
            logger.info(f"✗ {key}: FAILED")

    logger.info(f"\n{'=' * 80}")
    logger.info("TEST COMPLETE")
    logger.info(f"{'=' * 80}")

if __name__ == "__main__":
    main()
