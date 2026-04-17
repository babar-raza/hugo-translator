#!/usr/bin/env python3
"""
Download and cache M2M100 model for corpus validation.

This script downloads the facebook/m2m100_418M model and caches it locally
to avoid re-downloading on subsequent runs.
"""

import sys
from pathlib import Path

from transformers import M2M100ForConditionalGeneration, M2M100Tokenizer


def download_and_cache_model(model_name: str = "facebook/m2m100_418M", cache_dir: Path = None):
    """
    Download and cache M2M100 model.

    Args:
        model_name: HuggingFace model identifier
        cache_dir: Local cache directory (defaults to ~/.cache/huggingface)
    """
    print(f"Downloading M2M100 model: {model_name}")
    print("=" * 60)

    if cache_dir:
        cache_dir = Path(cache_dir).resolve()
        cache_dir.mkdir(parents=True, exist_ok=True)
        print(f"Cache directory: {cache_dir}")
    else:
        print("Using default HuggingFace cache directory")

    # Download tokenizer
    print("\n1. Downloading tokenizer...")
    tokenizer = M2M100Tokenizer.from_pretrained(
        model_name,
        cache_dir=cache_dir
    )
    print("   [OK] Tokenizer downloaded successfully")
    print(f"   Vocab size: {tokenizer.vocab_size}")

    # Download model
    print("\n2. Downloading model (this may take several minutes)...")
    model = M2M100ForConditionalGeneration.from_pretrained(
        model_name,
        cache_dir=cache_dir
    )
    print("   [OK] Model downloaded successfully")
    print(f"   Parameters: {model.num_parameters():,}")

    # Test the model with a simple translation
    print("\n3. Testing model with sample translation...")
    tokenizer.src_lang = "en"
    inputs = tokenizer("Hello, world!", return_tensors="pt")

    generated_tokens = model.generate(
        **inputs,
        forced_bos_token_id=tokenizer.get_lang_id("de")
    )
    translation = tokenizer.batch_decode(generated_tokens, skip_special_tokens=True)[0]
    print(f"   Test translation (EN->DE): 'Hello, world!' -> '{translation}'")
    print("   [OK] Model is working correctly")

    print("\n" + "=" * 60)
    print("Model download and cache complete!")
    print(f"Model location: {cache_dir or 'Default HuggingFace cache'}")
    print("\nThe model will not need to be downloaded again on subsequent runs.")

    return tokenizer, model


def main():
    """Main entry point."""
    # Store models in project models/ directory with size-specific subdirectory
    project_root = Path(__file__).parent.parent
    cache_dir = project_root / "models" / "m2m100_418M"

    print("M2M100 Model Download Script")
    print("=" * 60)
    print(f"Project root: {project_root}")
    print(f"Model directory: {cache_dir}")
    print()

    try:
        tokenizer, model = download_and_cache_model(
            model_name="facebook/m2m100_418M",
            cache_dir=cache_dir
        )

        print("\n[SUCCESS] Model ready for corpus validation")
        return 0

    except Exception as e:
        print("\n[ERROR] Failed to download model", file=sys.stderr)
        print(f"  {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
