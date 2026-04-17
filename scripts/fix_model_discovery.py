#!/usr/bin/env python3
"""
Fix Model Discovery - Systematic Cleanup and Registry Update.

This script:
1. Identifies complete vs incomplete model directories
2. Removes incomplete copies
3. Updates model registry to point to valid paths
4. Validates all registry entries
"""

import json
import logging
import shutil
import yaml
from pathlib import Path
from typing import Dict, List, Tuple

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def is_complete_hf_model(model_path: Path) -> bool:
    """Check if a directory contains a complete HuggingFace model."""
    if not model_path.exists() or not model_path.is_dir():
        return False

    # Must have config.json
    if not (model_path / "config.json").exists():
        return False

    # Must have model weights (any of these)
    weight_files = [
        "pytorch_model.bin",
        "model.safetensors",
        "tf_model.h5",
    ]
    has_weights = any((model_path / f).exists() for f in weight_files)

    return has_weights


def is_complete_ct2_model(model_path: Path) -> bool:
    """Check if a directory contains a complete CTranslate2 model."""
    if not model_path.exists() or not model_path.is_dir():
        return False

    # CT2 models have model.bin and config.json
    required_files = ["model.bin", "config.json"]
    return all((model_path / f).exists() for f in required_files)


def scan_models_directory(models_dir: Path) -> Dict[str, Dict]:
    """
    Scan models directory and categorize all model directories.

    Returns:
        Dict mapping relative path to model info
    """
    results = {}

    for path in models_dir.rglob("*"):
        if not path.is_dir():
            continue

        # Skip cache/lock directories
        if any(p in path.parts for p in [".locks", "cache", "blobs", "snapshots"]):
            continue

        rel_path = path.relative_to(models_dir)

        # Check if complete model
        is_hf = is_complete_hf_model(path)
        is_ct2 = is_complete_ct2_model(path)

        if is_hf or is_ct2:
            # Count files
            file_count = len(list(path.iterdir()))
            size_mb = sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / (1024 * 1024)

            results[str(rel_path)] = {
                "path": path,
                "rel_path": str(rel_path),
                "type": "ctranslate2" if is_ct2 else "huggingface",
                "complete": True,
                "file_count": file_count,
                "size_mb": round(size_mb, 1)
            }
        elif len(list(path.iterdir())) > 0:  # Has files but incomplete
            file_count = len(list(path.iterdir()))
            results[str(rel_path)] = {
                "path": path,
                "rel_path": str(rel_path),
                "type": "unknown",
                "complete": False,
                "file_count": file_count,
                "size_mb": 0
            }

    return results


def create_updated_registry(
    scan_results: Dict,
    old_registry_path: Path,
    output_path: Path
) -> None:
    """
    Create updated registry with corrected paths.

    Strategy:
    1. Load existing registry
    2. For each model, find best matching path from scan results
    3. Update local_path to point to complete model
    4. Add new OPUS models
    """
    # Load existing registry
    with open(old_registry_path, 'r') as f:
        registry = yaml.safe_load(f)

    models = registry.get('models', [])
    updated_models = []

    for model in models:
        model_id = model['model_id']
        old_local_path = model.get('local_path', '')
        hf_model_id = model.get('hf_model_id', '')

        logger.info(f"\nProcessing: {model_id}")
        logger.info(f"  Old path: {old_local_path}")
        logger.info(f"  HF ID: {hf_model_id}")

        # Find best matching complete model
        new_path = None

        # Check if old path is still valid
        if old_local_path:
            for scan_path, info in scan_results.items():
                if info['complete'] and str(old_local_path).replace('\\', '/') in scan_path:
                    new_path = info['rel_path']
                    logger.info(f"  ✓ Found at old path: {new_path}")
                    break

        # If not found, search by model ID or HF model ID
        if not new_path and hf_model_id:
            model_name = hf_model_id.split('/')[-1]  # e.g., "m2m100_418M"
            for scan_path, info in scan_results.items():
                if info['complete'] and model_name.lower() in scan_path.lower():
                    new_path = info['rel_path']
                    logger.info(f"  ✓ Found by name: {new_path}")
                    break

        # Update model entry
        if new_path:
            model['local_path'] = f"models/{new_path}"
            logger.info(f"  → Updated to: models/{new_path}")
        elif hf_model_id:
            # No local copy, rely on HuggingFace auto-download
            model['local_path'] = None
            logger.info(f"  → Will download from HuggingFace: {hf_model_id}")
        else:
            logger.warning(f"  ⚠ No path found and no HF ID!")

        updated_models.append(model)

    # Add new OPUS models found in scan that aren't in registry
    existing_hf_ids = {m.get('hf_model_id', '').lower() for m in updated_models}

    for scan_path, info in scan_results.items():
        if not info['complete']:
            continue
        if 'opus' not in scan_path.lower():
            continue

        # Extract model name (e.g., opus-mt-en-de)
        model_name = Path(scan_path).name
        hf_id = f"Helsinki-NLP/{model_name}"

        if hf_id.lower() not in existing_hf_ids:
            # Extract language pair
            parts = model_name.split('-')
            if len(parts) >= 4:
                src_lang = parts[-2]
                tgt_lang = parts[-1]

                new_model = {
                    'model_id': f"opus_mt_{src_lang}_{tgt_lang}",
                    'name': f"OPUS-MT {src_lang.upper()}-{tgt_lang.upper()}",
                    'backend': 'huggingface',
                    'local_path': f"models/{scan_path}",
                    'hf_model_id': hf_id,
                    'supported_pairs': [[src_lang, tgt_lang]],
                    'model_size_mb': int(info['size_mb']),
                    'min_ram_gb': 1,
                    'optimal_device': 'cpu',
                    'parameters': 77000000,
                    'license': 'CC-BY-4.0',
                    'description': f"Specialized {src_lang}-{tgt_lang} translation model"
                }
                updated_models.append(new_model)
                logger.info(f"\n  + Added new OPUS model: {hf_id}")

    # Write updated registry
    registry['models'] = updated_models
    with open(output_path, 'w') as f:
        yaml.dump(registry, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    logger.info(f"\n✓ Updated registry written to: {output_path}")
    logger.info(f"  Total models: {len(updated_models)}")


def cleanup_incomplete_models(
    scan_results: Dict,
    models_dir: Path,
    dry_run: bool = True
) -> None:
    """Remove incomplete model directories to save space."""
    incomplete = [info for info in scan_results.values() if not info['complete']]

    if not incomplete:
        logger.info("\n✓ No incomplete models to clean up")
        return

    logger.info(f"\n{'DRY RUN: Would remove' if dry_run else 'Removing'} {len(incomplete)} incomplete model directories:")

    total_size = 0
    for info in incomplete:
        size_mb = sum(f.stat().st_size for f in info['path'].rglob("*") if f.is_file()) / (1024 * 1024)
        total_size += size_mb
        logger.info(f"  - {info['rel_path']} ({info['file_count']} files, {size_mb:.1f} MB)")

        if not dry_run:
            shutil.rmtree(info['path'])
            logger.info(f"    ✓ Removed")

    logger.info(f"\n{'Would free' if dry_run else 'Freed'}: {total_size:.1f} MB")


def generate_report(scan_results: Dict, output_file: Path) -> None:
    """Generate model discovery report."""
    complete = [info for info in scan_results.values() if info['complete']]
    incomplete = [info for info in scan_results.values() if not info['complete']]

    report = []
    report.append("# Model Discovery Report\n")
    report.append(f"**Total Directories Scanned:** {len(scan_results)}\n")
    report.append(f"**Complete Models:** {len(complete)}\n")
    report.append(f"**Incomplete Models:** {len(incomplete)}\n\n")

    report.append("## Complete Models\n")
    report.append("| Path | Type | Files | Size (MB) |\n")
    report.append("|------|------|-------|----------|\n")
    for info in sorted(complete, key=lambda x: x['rel_path']):
        report.append(f"| {info['rel_path']} | {info['type']} | {info['file_count']} | {info['size_mb']} |\n")

    report.append("\n## Incomplete Models (to remove)\n")
    report.append("| Path | Files | Issue |\n")
    report.append("|------|-------|-------|\n")
    for info in sorted(incomplete, key=lambda x: x['rel_path']):
        report.append(f"| {info['rel_path']} | {info['file_count']} | Missing config.json or weights |\n")

    with open(output_file, 'w') as f:
        f.writelines(report)

    logger.info(f"\n✓ Report written to: {output_file}")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Fix model discovery")
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=Path(__file__).parent.parent / "models",
        help="Models directory"
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path(__file__).parent.parent / "config" / "model_registry.yaml",
        help="Current model registry"
    )
    parser.add_argument(
        "--output-registry",
        type=Path,
        default=Path(__file__).parent.parent / "config" / "model_registry_fixed.yaml",
        help="Output registry path"
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Actually remove incomplete models (default: dry run)"
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path(__file__).parent.parent / "MODEL_DISCOVERY_REPORT.md",
        help="Output report path"
    )

    args = parser.parse_args()

    logger.info("="*80)
    logger.info("MODEL DISCOVERY FIX")
    logger.info("="*80)

    # Scan models directory
    logger.info(f"\nScanning: {args.models_dir}")
    scan_results = scan_models_directory(args.models_dir)

    # Generate report
    generate_report(scan_results, args.report)

    # Create updated registry
    create_updated_registry(scan_results, args.registry, args.output_registry)

    # Cleanup incomplete models
    cleanup_incomplete_models(scan_results, args.models_dir, dry_run=not args.cleanup)

    logger.info("\n" + "="*80)
    logger.info("NEXT STEPS:")
    logger.info("="*80)
    logger.info(f"1. Review: {args.report}")
    logger.info(f"2. Review: {args.output_registry}")
    logger.info(f"3. If satisfied, run with --cleanup to remove incomplete models")
    logger.info(f"4. Replace config/model_registry.yaml with the fixed version")
    logger.info(f"5. Run E2E tests to verify")

    return 0


if __name__ == "__main__":
    exit(main())
