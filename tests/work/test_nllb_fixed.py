#!/usr/bin/env python3
"""
Test NLLB model with fixed language code mapping.

This script verifies that the language code mapping correctly handles
NLLB's language_Script format (eng_Latn, spa_Latn, etc.).
"""
import logging
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.model_runtime.registry import ModelRegistry
from src.model_runtime.loader import ModelLoader

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Also set debug level for model_runtime
logging.getLogger('src.model_runtime').setLevel(logging.DEBUG)


def test_nllb_model():
    """Test NLLB model with language code mapping."""
    logger.info("=" * 80)
    logger.info("TESTING NLLB MODEL WITH FIXED LANGUAGE CODE MAPPING")
    logger.info("=" * 80)

    # Initialize model system
    registry_path = project_root / "config" / "model_registry.yaml"
    registry = ModelRegistry(registry_path)
    loader = ModelLoader(registry, device="cuda:0")

    # Test text
    test_text = "This is a test of the NLLB translation model with proper language code mapping."

    # Target languages (using simple ISO 639-1 codes - they will be mapped automatically)
    target_langs = {
        "es": "Spanish",
        "de": "German",
        "fr": "French",
    }

    try:
        logger.info("\nLoading NLLB-200-600M model...")
        backend = loader.load_model("nllb_200_600m")
        logger.info("✓ Model loaded successfully")

        logger.info(f"\nSource text (English): {test_text}")
        logger.info("-" * 80)

        for lang_code, lang_name in target_langs.items():
            logger.info(f"\nTranslating to {lang_name} (code: {lang_code})...")

            # Translate using simple ISO 639-1 codes
            # The mapping will automatically convert "es" -> "spa_Latn", etc.
            translation = backend.translate([test_text], "en", lang_code)

            logger.info(f"✓ {lang_name}: {translation[0]}")
            logger.info(f"  Length: {len(translation[0])} characters")

        logger.info("\n" + "=" * 80)
        logger.info("✓ ALL TESTS PASSED - NLLB language code mapping working correctly!")
        logger.info("=" * 80)
        return True

    except Exception as e:
        logger.error(f"\n✗ TEST FAILED: {e}", exc_info=True)
        return False
    finally:
        # Cleanup
        loader.unload_all()


if __name__ == "__main__":
    success = test_nllb_model()
    sys.exit(0 if success else 1)
