"""
Model Management CLI Commands.

Provides CLI interface for model acquisition, organization, and verification:
- models sync-registry: Generate Opus registry and discover cache models
- models download: Download models with various filters
- models verify: Validate downloaded models against manifest
"""
import argparse
import logging
import sys
from pathlib import Path
from typing import List, Optional

from .model_store import ModelStore, ModelManifest
from .registry import ModelRegistry
from .ct2_manager import CT2ConversionManager

logger = logging.getLogger(__name__)


def cmd_sync_registry(args: argparse.Namespace) -> int:
    """
    Synchronize model registry by generating Opus entries and discovering cache models.

    Steps:
    1. Generate Opus registry from target languages
    2. Discover models from HuggingFace cache
    3. Merge registries (main + opus + cache)

    Args:
        args: Parsed arguments

    Returns:
        Exit code (0 for success)
    """
    import subprocess

    logger.info("=== Synchronizing Model Registry ===")

    # Step 1: Generate Opus registry
    logger.info("\n[1/2] Generating Opus model registry...")
    opus_cmd = [
        sys.executable,
        "-m",
        "scripts.generate_opus_registry",
        "--output",
        args.opus_output
    ]
    if args.check_online:
        opus_cmd.append("--check-online")

    try:
        subprocess.run(opus_cmd, check=True)
        logger.info(f"✓ Opus registry generated: {args.opus_output}")
    except subprocess.CalledProcessError as e:
        logger.error(f"✗ Opus registry generation failed: {e}")
        return 1

    # Step 2: Discover cache models
    logger.info("\n[2/2] Discovering models from HuggingFace cache...")
    cache_cmd = [
        sys.executable,
        "-m",
        "scripts.discover_hf_cache_models",
        "--output",
        args.cache_output
    ]

    try:
        subprocess.run(cache_cmd, check=True)
        logger.info(f"✓ Cache discovery complete: {args.cache_output}")
    except subprocess.CalledProcessError as e:
        logger.error(f"✗ Cache discovery failed: {e}")
        return 1

    # Step 3: Display registry summary
    logger.info("\n=== Registry Summary ===")
    logger.info(f"Main registry: config/model_registry.yaml")
    logger.info(f"Opus registry: {args.opus_output}")
    logger.info(f"Cache registry: {args.cache_output}")
    logger.info("\nTo use all registries, update your config to load:")
    logger.info("  registry_path: config/model_registry.yaml,{},{}"
                .format(args.opus_output, args.cache_output))

    return 0


def cmd_download(args: argparse.Namespace) -> int:
    """
    Download models with various filters.

    Args:
        args: Parsed arguments

    Returns:
        Exit code (0 for success)
    """
    logger.info("=== Model Download ===")

    # Load registry (support multiple paths)
    registry_paths = args.registry.split(",") if "," in args.registry else [args.registry]
    logger.info(f"Loading registry from: {registry_paths}")

    try:
        registry = ModelRegistry(registry_paths)
        logger.info(f"Loaded {len(registry.models)} models from registry")
    except Exception as e:
        logger.error(f"Failed to load registry: {e}")
        return 1

    # Create model store with download permission
    store = ModelStore(
        registry=registry,
        models_dir=Path(args.models_dir),
        allow_downloads=True  # Explicitly enabled for download command
    )

    # Determine what to download
    if args.all:
        # Download all models
        logger.info("Downloading ALL models...")
        language_filter = None
    elif args.languages:
        # Download models for specific languages
        language_filter = args.languages.split(",")
        logger.info(f"Downloading models for languages: {language_filter}")
    elif args.model_id:
        # Download specific model
        logger.info(f"Downloading model: {args.model_id}")
        try:
            path = store.ensure_model_downloaded(args.model_id)
            logger.info(f"✓ Model downloaded successfully: {path}")
            return 0
        except Exception as e:
            logger.error(f"✗ Download failed: {e}")
            return 1
    else:
        logger.error("Must specify --all, --model-id, or --languages")
        return 1

    # Download multiple models
    results = store.download_all_models(
        language_filter=language_filter,
        max_workers=args.parallel
    )

    # Report results
    success_count = sum(1 for success in results.values() if success)
    failure_count = len(results) - success_count

    logger.info(f"\n=== Download Summary ===")
    logger.info(f"Total: {len(results)}")
    logger.info(f"Success: {success_count}")
    logger.info(f"Failed: {failure_count}")

    if failure_count > 0:
        logger.warning("Some downloads failed. Check logs above for details.")

    return 0 if failure_count == 0 else 1


def cmd_verify(args: argparse.Namespace) -> int:
    """
    Verify downloaded models against manifest.

    Args:
        args: Parsed arguments

    Returns:
        Exit code (0 for success)
    """
    logger.info("=== Model Verification ===")

    # Load registry
    try:
        registry = ModelRegistry(args.registry)
    except Exception as e:
        logger.error(f"Failed to load registry: {e}")
        return 1

    # Create model store
    store = ModelStore(
        registry=registry,
        models_dir=Path(args.models_dir),
        allow_downloads=False
    )

    # Get models to verify
    if args.all:
        models_to_verify = store.manifest.list_models()
        logger.info(f"Verifying {len(models_to_verify)} models from manifest...")
    elif args.model_id:
        models_to_verify = [args.model_id]
        logger.info(f"Verifying model: {args.model_id}")
    else:
        logger.error("Must specify --all or --model-id")
        return 1

    # Verify each model
    results = {}
    for model_id in models_to_verify:
        try:
            if model_id not in registry:
                logger.warning(f"? {model_id}: not in registry")
                results[model_id] = False
                continue

            verified = store.verify_model(model_id)
            results[model_id] = verified

            if verified:
                logger.info(f"✓ {model_id}: verified")
            else:
                logger.error(f"✗ {model_id}: verification failed")

        except Exception as e:
            logger.error(f"✗ {model_id}: {e}")
            results[model_id] = False

    # Summary
    verified_count = sum(1 for v in results.values() if v)
    failed_count = len(results) - verified_count

    logger.info(f"\n=== Verification Summary ===")
    logger.info(f"Total: {len(results)}")
    logger.info(f"Verified: {verified_count}")
    logger.info(f"Failed: {failed_count}")

    return 0 if failed_count == 0 else 1


def cmd_list(args: argparse.Namespace) -> int:
    """
    List models and their status.

    Args:
        args: Parsed arguments

    Returns:
        Exit code (0 for success)
    """
    logger.info("=== Model List ===")

    # Load registry
    try:
        registry = ModelRegistry(args.registry)
    except Exception as e:
        logger.error(f"Failed to load registry: {e}")
        return 1

    # Create model store
    store = ModelStore(
        registry=registry,
        models_dir=Path(args.models_dir),
        allow_downloads=False
    )

    # Get download plan
    plan = store.get_download_plan()

    # Display status
    print(f"\n{'Model ID':<30} {'Status':<15} {'Size (MB)':<12} {'Backend':<12}")
    print("-" * 75)

    for model_info in sorted(registry.models.values(), key=lambda m: m.model_id):
        status = "✓ Downloaded" if model_info.model_id in plan["already_present"] else "⬇ Need Download"
        size = model_info.model_size_mb
        backend = model_info.backend

        print(f"{model_info.model_id:<30} {status:<15} {size:<12} {backend:<12}")

    # Summary
    print("\n" + "=" * 75)
    print(f"Total Models: {plan['total_models']}")
    print(f"Downloaded: {plan['already_present_count']}")
    print(f"Need Download: {plan['needs_download_count']} ({plan['total_size_mb']:.1f} MB)")

    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    """
    Show download plan for models.

    Args:
        args: Parsed arguments

    Returns:
        Exit code (0 for success)
    """
    logger.info("=== Download Plan ===")

    # Load registry
    try:
        registry = ModelRegistry(args.registry)
    except Exception as e:
        logger.error(f"Failed to load registry: {e}")
        return 1

    # Create model store
    store = ModelStore(
        registry=registry,
        models_dir=Path(args.models_dir),
        allow_downloads=False
    )

    # Get download plan
    plan = store.get_download_plan()

    # Display plan
    print("\nAlready Downloaded:")
    for model_id in sorted(plan["already_present"]):
        print(f"  ✓ {model_id}")

    print("\nNeed to Download:")
    for model_id in sorted(plan["needs_download"]):
        model_info = registry.get_model(model_id)
        print(f"  ⬇ {model_id} ({model_info.model_size_mb} MB)")

    print(f"\nTotal download size: {plan['total_size_mb']:.1f} MB")
    print(f"\nTo download all: python -m src.model_runtime.model_cli download --all")

    return 0


def cmd_convert_ct2(args: argparse.Namespace) -> int:
    """
    Convert models to CTranslate2 format.

    Args:
        args: Parsed arguments

    Returns:
        Exit code (0 for success)
    """
    logger.info("=== CT2 Conversion ===")

    # Load registry
    try:
        registry = ModelRegistry(args.registry)
    except Exception as e:
        logger.error(f"Failed to load registry: {e}")
        return 1

    # Create CT2 manager
    manager = CT2ConversionManager(
        registry=registry,
        models_dir=Path(args.models_dir),
    )

    # Determine models to convert
    model_ids = []

    if args.model:
        model_ids = [args.model]
    elif args.all_multilingual:
        # Convert core multilingual models
        model_ids = ["m2m100_418m", "m2m100_1.2b", "nllb_distilled_600m", "small100"]
        logger.info(f"Converting multilingual models: {', '.join(model_ids)}")
    elif args.all_opus:
        # Convert Opus models
        opus_models = [m.model_id for m in registry.list_models() if m.backend == "opus"]
        model_ids = opus_models
        logger.info(f"Converting {len(opus_models)} Opus models")
    else:
        logger.error("Must specify --model, --all-multilingual, or --all-opus")
        return 1

    # Convert each model
    results = []
    for model_id in model_ids:
        logger.info(f"\nConverting {model_id}...")

        result = manager.ensure_ct2(
            model_id=model_id,
            quantization=args.quant,
            device_target="cpu" if args.quant == "int8" else "cuda",
            force=args.force,
        )

        results.append(result)

        if result.success:
            logger.info(f"✓ {model_id} -> {result.model_id} ({result.size_mb:.1f}MB)")
        else:
            logger.error(f"✗ {model_id}: {result.error}")

    # Summary
    success_count = sum(1 for r in results if r.success)
    failure_count = len(results) - success_count
    total_size_mb = sum(r.size_mb for r in results if r.success)

    logger.info(f"\n=== Conversion Summary ===")
    logger.info(f"Total: {len(results)}")
    logger.info(f"Success: {success_count}")
    logger.info(f"Failed: {failure_count}")
    logger.info(f"Total size: {total_size_mb:.1f} MB")

    if failure_count > 0:
        logger.warning("Some conversions failed. Check logs above for details.")

    return 0 if failure_count == 0 else 1


def cmd_list_ct2(args: argparse.Namespace) -> int:
    """
    List CT2 models (existing and potential).

    Args:
        args: Parsed arguments

    Returns:
        Exit code (0 for success)
    """
    logger.info("=== CT2 Models ===")

    # Load registry
    try:
        registry = ModelRegistry(args.registry)
    except Exception as e:
        logger.error(f"Failed to load registry: {e}")
        return 1

    # Create CT2 manager
    manager = CT2ConversionManager(
        registry=registry,
        models_dir=Path(args.models_dir),
    )

    # Get CT2 models
    ct2_models = manager.list_ct2_models()

    # Group by status
    existing = [(m, p) for m, exists, p in ct2_models if exists]
    potential = [(m, p) for m, exists, p in ct2_models if not exists]

    # Display existing
    print(f"\n{'CT2 Model ID':<40} {'Status':<15} {'Path':<50}")
    print("-" * 110)

    if existing:
        print("\nExisting CT2 Models:")
        for model_id, path in sorted(existing):
            print(f"  ✓ {model_id:<38} {'Ready':<15} {path}")

    if args.show_potential and potential:
        print("\nPotential CT2 Conversions:")
        for model_id, path in sorted(potential):
            print(f"  ⬇ {model_id:<38} {'Not converted':<15} {path}")

    # Summary
    print("\n" + "=" * 110)
    print(f"Existing CT2 models: {len(existing)}")
    if args.show_potential:
        print(f"Potential conversions: {len(potential)}")

    if not existing and not potential:
        print("\nNo CT2 models found. Run 'convert-ct2' to create them.")
    elif not existing:
        print("\nNo CT2 models exist yet. Run 'convert-ct2 --all-multilingual' to get started.")

    return 0


def main() -> int:
    """Main entry point for model CLI."""
    parser = argparse.ArgumentParser(
        description="Model Management CLI",
        prog="python -m src.model_runtime.model_cli"
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # sync-registry command
    sync_parser = subparsers.add_parser(
        "sync-registry",
        help="Synchronize model registry (generate Opus + discover cache)"
    )
    sync_parser.add_argument(
        "--opus-output",
        default="config/model_registry.opus_autogen.yaml",
        help="Output path for Opus registry"
    )
    sync_parser.add_argument(
        "--cache-output",
        default="config/model_registry.local.yaml",
        help="Output path for cache discovery registry"
    )
    sync_parser.add_argument(
        "--check-online",
        action="store_true",
        help="Check HuggingFace Hub for Opus model availability"
    )

    # download command
    download_parser = subparsers.add_parser(
        "download",
        help="Download models"
    )
    download_parser.add_argument(
        "--all",
        action="store_true",
        help="Download all models in registry"
    )
    download_parser.add_argument(
        "--model-id",
        help="Download specific model by ID"
    )
    download_parser.add_argument(
        "--languages",
        help="Download models for specific languages (comma-separated)"
    )
    download_parser.add_argument(
        "--registry",
        default="config/model_registry.yaml",
        help="Registry path (supports comma-separated list)"
    )
    download_parser.add_argument(
        "--models-dir",
        default="models",
        help="Base directory for model storage"
    )
    download_parser.add_argument(
        "--parallel",
        type=int,
        default=3,
        help="Maximum parallel downloads"
    )

    # verify command
    verify_parser = subparsers.add_parser(
        "verify",
        help="Verify downloaded models against manifest"
    )
    verify_parser.add_argument(
        "--all",
        action="store_true",
        help="Verify all downloaded models"
    )
    verify_parser.add_argument(
        "--model-id",
        help="Verify specific model by ID"
    )
    verify_parser.add_argument(
        "--registry",
        default="config/model_registry.yaml",
        help="Registry path"
    )
    verify_parser.add_argument(
        "--models-dir",
        default="models",
        help="Base directory for model storage"
    )

    # list command
    list_parser = subparsers.add_parser(
        "list",
        help="List all models and their download status"
    )
    list_parser.add_argument(
        "--registry",
        default="config/model_registry.yaml",
        help="Registry path"
    )
    list_parser.add_argument(
        "--models-dir",
        default="models",
        help="Base directory for model storage"
    )

    # plan command
    plan_parser = subparsers.add_parser(
        "plan",
        help="Show download plan"
    )
    plan_parser.add_argument(
        "--registry",
        default="config/model_registry.yaml",
        help="Registry path"
    )
    plan_parser.add_argument(
        "--models-dir",
        default="models",
        help="Base directory for model storage"
    )

    # convert-ct2 command
    convert_ct2_parser = subparsers.add_parser(
        "convert-ct2",
        help="Convert models to CTranslate2 format"
    )
    convert_ct2_parser.add_argument(
        "--model",
        help="Model ID to convert (e.g., m2m100_418m)"
    )
    convert_ct2_parser.add_argument(
        "--all-multilingual",
        action="store_true",
        help="Convert all multilingual models (m2m100, nllb, small100)"
    )
    convert_ct2_parser.add_argument(
        "--all-opus",
        action="store_true",
        help="Convert all Opus models"
    )
    convert_ct2_parser.add_argument(
        "--quant",
        choices=["int8", "int16", "float16", "float32"],
        default="int8",
        help="Quantization type (default: int8 for CPU)"
    )
    convert_ct2_parser.add_argument(
        "--force",
        action="store_true",
        help="Force reconversion even if CT2 model exists"
    )
    convert_ct2_parser.add_argument(
        "--registry",
        default="config/model_registry.yaml",
        help="Registry path"
    )
    convert_ct2_parser.add_argument(
        "--models-dir",
        default="models",
        help="Base directory for model storage"
    )

    # list-ct2 command
    list_ct2_parser = subparsers.add_parser(
        "list-ct2",
        help="List CT2 models (existing and potential)"
    )
    list_ct2_parser.add_argument(
        "--show-potential",
        action="store_true",
        help="Show potential CT2 conversions (not yet converted)"
    )
    list_ct2_parser.add_argument(
        "--registry",
        default="config/model_registry.yaml",
        help="Registry path"
    )
    list_ct2_parser.add_argument(
        "--models-dir",
        default="models",
        help="Base directory for model storage"
    )

    # Parse arguments
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s"
    )

    # Execute command
    if args.command == "sync-registry":
        return cmd_sync_registry(args)
    elif args.command == "download":
        return cmd_download(args)
    elif args.command == "verify":
        return cmd_verify(args)
    elif args.command == "list":
        return cmd_list(args)
    elif args.command == "plan":
        return cmd_plan(args)
    elif args.command == "convert-ct2":
        return cmd_convert_ct2(args)
    elif args.command == "list-ct2":
        return cmd_list_ct2(args)
    else:
        logger.error(f"Unknown command: {args.command}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
