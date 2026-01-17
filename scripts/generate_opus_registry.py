"""
Generate Opus model registry for all target languages.

Reads config/target_languages.yaml and generates Opus model entries for
each target language using the Helsinki-NLP/opus-mt-en-{lang} pattern.

Output: config/model_registry.opus_autogen.yaml

Features:
- Generates entries for all 36 target languages
- Optionally checks HuggingFace Hub for model availability (--check-online)
- Marks unavailable models with notes
- Supports offline mode (skip availability checks)
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Dict, List, Optional

import yaml

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def load_target_languages(config_path: Path = Path("config/target_languages.yaml")) -> List[str]:
    """
    Load target language codes from config.

    Args:
        config_path: Path to target languages YAML

    Returns:
        List of ISO language codes (e.g., ['ar', 'bg', 'cs', ...])
    """
    if not config_path.exists():
        raise FileNotFoundError(f"Target languages config not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not data or "languages" not in data:
        raise ValueError(f"Invalid config format: missing 'languages' key")

    languages = data["languages"]
    return [lang["iso_code"] for lang in languages]


def check_opus_model_exists(
    src_lang: str,
    tgt_lang: str,
    timeout: int = 10
) -> tuple[bool, Optional[str]]:
    """
    Check if Opus model exists on HuggingFace Hub.

    Args:
        src_lang: Source language code (e.g., 'en')
        tgt_lang: Target language code (e.g., 'fr')
        timeout: Request timeout in seconds

    Returns:
        (exists, error_message) tuple
    """
    try:
        from huggingface_hub import model_info
    except ImportError:
        return (False, "huggingface_hub not installed")

    model_id = f"Helsinki-NLP/opus-mt-{src_lang}-{tgt_lang}"

    try:
        info = model_info(model_id, timeout=timeout)
        # Model exists if we got info without error
        logger.info(f"✓ {model_id} exists on HuggingFace Hub")
        return (True, None)
    except Exception as e:
        error_msg = str(e)
        if "404" in error_msg or "not found" in error_msg.lower():
            logger.warning(f"✗ {model_id} not found on HuggingFace Hub")
            return (False, "Model not found on HuggingFace Hub")
        else:
            logger.warning(f"? {model_id} check failed: {e}")
            return (False, f"Check failed: {error_msg}")


def generate_opus_model_entry(
    src_lang: str,
    tgt_lang: str,
    check_online: bool = False
) -> Optional[Dict]:
    """
    Generate Opus model registry entry.

    Args:
        src_lang: Source language code
        tgt_lang: Target language code
        check_online: Whether to check HuggingFace Hub

    Returns:
        Model entry dict if model should be included, None if unavailable
    """
    model_id = f"opus_{src_lang}_{tgt_lang}"
    hf_model_id = f"Helsinki-NLP/opus-mt-{src_lang}-{tgt_lang}"
    local_path = f"models/opus/opus-mt-{src_lang}-{tgt_lang}"

    # Check availability if requested
    availability_note = ""
    if check_online:
        exists, error = check_opus_model_exists(src_lang, tgt_lang)
        if not exists:
            # Model doesn't exist - log and skip
            logger.warning(
                f"Skipping {model_id}: {error or 'not available'}"
            )
            # Return entry but mark as unavailable for documentation
            return {
                "model_id": model_id,
                "name": f"Opus-MT {src_lang.upper()}-{tgt_lang.upper()}",
                "backend": "opus",
                "supported_pairs": [[src_lang, tgt_lang], [tgt_lang, src_lang]],
                "model_size_mb": 0,
                "min_ram_gb": 1.0,
                "optimal_device": "cpu",
                "hf_model_id": hf_model_id,
                "local_path": local_path,
                "description": f"Opus bilingual model for {src_lang}↔{tgt_lang}. UNAVAILABLE: {error}",
                "available": False
            }
        else:
            availability_note = " (verified on HuggingFace Hub)"

    # Generate entry
    entry = {
        "model_id": model_id,
        "name": f"Opus-MT {src_lang.upper()}-{tgt_lang.upper()}",
        "backend": "opus",
        "supported_pairs": [[src_lang, tgt_lang], [tgt_lang, src_lang]],
        "model_size_mb": 300,  # Typical Opus model size
        "min_ram_gb": 1.0,  # Opus models are lightweight
        "optimal_device": "cpu",  # Optimized for CPU
        "parameters": 77000000,  # Typical Opus model parameter count
        "license": "CC-BY-4.0",
        "hf_model_id": hf_model_id,
        "local_path": local_path,
        "description": f"Specialized bilingual model for {src_lang}↔{tgt_lang}. "
                      f"Fast and lightweight.{availability_note}",
        "available": True
    }

    return entry


def main() -> int:
    """Generate Opus registry for all target languages."""
    parser = argparse.ArgumentParser(
        description="Generate Opus model registry from target languages"
    )
    parser.add_argument(
        "--target-langs",
        default="config/target_languages.yaml",
        help="Path to target languages YAML (default: config/target_languages.yaml)"
    )
    parser.add_argument(
        "--output",
        default="config/model_registry.opus_autogen.yaml",
        help="Output registry path (default: config/model_registry.opus_autogen.yaml)"
    )
    parser.add_argument(
        "--source-lang",
        default="en",
        help="Source language code (default: en)"
    )
    parser.add_argument(
        "--check-online",
        action="store_true",
        help="Check HuggingFace Hub for model availability (requires internet)"
    )
    parser.add_argument(
        "--include-unavailable",
        action="store_true",
        help="Include unavailable models in output (with available=false flag)"
    )
    args = parser.parse_args()

    # Load target languages
    target_langs_path = Path(args.target_langs)
    logger.info(f"Loading target languages from {target_langs_path}")
    target_langs = load_target_languages(target_langs_path)
    logger.info(f"Found {len(target_langs)} target languages")

    # Generate entries
    models = []
    available_count = 0
    unavailable_count = 0

    for tgt_lang in target_langs:
        entry = generate_opus_model_entry(
            src_lang=args.source_lang,
            tgt_lang=tgt_lang,
            check_online=args.check_online
        )

        if entry:
            is_available = entry.get("available", True)
            if is_available:
                available_count += 1
                models.append(entry)
            else:
                unavailable_count += 1
                if args.include_unavailable:
                    models.append(entry)
                else:
                    logger.debug(f"Excluding unavailable model: {entry['model_id']}")

    # Generate output
    output_data = {
        "# Auto-generated Opus model registry": None,
        "# Generated from": str(target_langs_path),
        "# Source language": args.source_lang,
        "# Target languages": len(target_langs),
        "# Available models": available_count,
        "# Unavailable models": unavailable_count,
        "models": models
    }

    # Remove comment keys before writing
    clean_data = {"models": models}

    # Write output
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        # Write header comments manually
        f.write("# Auto-generated Opus model registry\n")
        f.write(f"# Generated from: {target_langs_path}\n")
        f.write(f"# Source language: {args.source_lang}\n")
        f.write(f"# Target languages: {len(target_langs)}\n")
        f.write(f"# Available models: {available_count}\n")
        if unavailable_count > 0:
            f.write(f"# Unavailable models: {unavailable_count}\n")
        f.write("\n")

        # Write YAML data
        yaml.dump(clean_data, f, default_flow_style=False, sort_keys=False)

    logger.info(f"Generated {len(models)} Opus model entries")
    logger.info(f"Output written to {output_path}")
    logger.info(f"Available: {available_count}, Unavailable: {unavailable_count}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
