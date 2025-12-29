#!/usr/bin/env python3
"""Comprehensive cleanup: remove all unused models and caches."""
import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import List, Dict
import importlib.util


def load_module_directly(module_name, module_path):
    """Load a module directly from file path."""
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def find_cache_directories(project_root: Path) -> List[Path]:
    """Find cache directories to clean.

    Args:
        project_root: Project root directory

    Returns:
        List of cache directory paths
    """
    cache_dirs = []

    # Python cache
    for cache in project_root.rglob("__pycache__"):
        cache_dirs.append(cache)

    for cache in project_root.rglob("*.pyc"):
        cache_dirs.append(cache)

    # HuggingFace cache (if inside project)
    hf_cache = project_root / ".cache" / "huggingface"
    if hf_cache.exists():
        cache_dirs.append(hf_cache)

    # Temp directories
    temp_dirs = [
        project_root / "tmp",
        project_root / "temp",
        project_root / ".tmp"
    ]
    for temp_dir in temp_dirs:
        if temp_dir.exists():
            cache_dirs.append(temp_dir)

    # Model download markers
    models_dir = project_root / "models"
    if models_dir.exists():
        for marker in models_dir.rglob(".*.downloading"):
            cache_dirs.append(marker)

    return cache_dirs


def calculate_total_size(paths: List[Path]) -> float:
    """Calculate total size of paths in MB.

    Args:
        paths: List of paths

    Returns:
        Total size in MB
    """
    total = 0
    for path in paths:
        try:
            if path.is_file():
                total += path.stat().st_size
            elif path.is_dir():
                for item in path.rglob('*'):
                    if item.is_file():
                        total += item.stat().st_size
        except (PermissionError, OSError):
            pass

    return total / (1024 * 1024)


def confirm_cleanup(plan: Dict):
    """Prompt user for confirmation.

    Args:
        plan: Cleanup plan dictionary

    Returns:
        True if user confirms
    """
    print()
    print("=" * 70)
    print("CLEANUP PLAN")
    print("=" * 70)
    print()

    if plan["models"]:
        print(f"Models to remove: {len(plan['models'])} ({plan['models_size_gb']:.2f} GB)")
        for model in plan["models"][:5]:
            print(f"  - {model['model_id']} ({model['size_mb']:.1f} MB)")
        if len(plan["models"]) > 5:
            print(f"  ... and {len(plan['models']) - 5} more")
        print()

    if plan["caches"]:
        print(f"Cache directories to remove: {len(plan['caches'])} ({plan['caches_size_mb']:.1f} MB)")
        for cache in plan["caches"][:5]:
            print(f"  - {cache}")
        if len(plan["caches"]) > 5:
            print(f"  ... and {len(plan['caches']) - 5} more")
        print()

    total_gb = plan['models_size_gb'] + (plan['caches_size_mb'] / 1024)
    print(f"Total space to be freed: {total_gb:.2f} GB")
    print()
    print("⚠️  This action cannot be undone!")
    print()

    response = input("Proceed with cleanup? [yes/NO]: ").strip().lower()
    return response in ['yes', 'y']


def cleanup_caches(cache_paths: List[Path]) -> Dict:
    """Remove cache directories.

    Args:
        cache_paths: List of cache paths to remove

    Returns:
        Dictionary with cleanup results
    """
    removed = 0
    failed = 0
    size_freed = 0

    for cache_path in cache_paths:
        try:
            if cache_path.is_file():
                size = cache_path.stat().st_size
                cache_path.unlink()
                size_freed += size
                removed += 1
            elif cache_path.is_dir():
                # Calculate size before removal
                size = sum(f.stat().st_size for f in cache_path.rglob('*') if f.is_file())
                shutil.rmtree(cache_path)
                size_freed += size
                removed += 1
        except Exception as e:
            print(f"⚠️  Failed to remove {cache_path}: {e}")
            failed += 1

    return {
        "removed": removed,
        "failed": failed,
        "size_freed_mb": size_freed / (1024 * 1024)
    }


def cleanup_models(models, disk_manager, inventory_manager=None) -> Dict:
    """Remove models.

    Args:
        models: List of ModelDiskInfo to remove
        disk_manager: DiskManager instance
        inventory_manager: Optional ModelInventory instance

    Returns:
        Dictionary with cleanup results
    """
    removed = 0
    failed = 0
    size_freed = 0

    for model in models:
        try:
            if model.path.exists():
                shutil.rmtree(model.path)
                size_freed += model.size_mb
                removed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"⚠️  Failed to remove {model.model_id}: {e}")
            failed += 1

    # Update inventory
    if inventory_manager and removed > 0:
        try:
            entries = inventory_manager.load()
            removed_ids = {m.model_id for m in models}
            entries = [e for e in entries if e.model_id not in removed_ids]
            inventory_manager.update(entries)
        except Exception as e:
            print(f"⚠️  Warning: Failed to update inventory: {e}")

    return {
        "removed": removed,
        "failed": failed,
        "size_freed_mb": size_freed
    }


def main():
    parser = argparse.ArgumentParser(description="Comprehensive cleanup of models and caches")
    parser.add_argument("--models-dir", type=str, default="models", help="Models directory")
    parser.add_argument("--keep-models", action="store_true", help="Keep models, only clean caches")
    parser.add_argument("--keep-caches", action="store_true", help="Keep caches, only clean models")
    parser.add_argument("--min-size", type=float, default=100, help="Minimum model size to remove (MB)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be cleaned")
    parser.add_argument("--force", action="store_true", help="Skip confirmation")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    project_root = Path(__file__).parent.parent

    # Load disk manager
    disk_manager_path = project_root / "src" / "model_runtime" / "disk_manager.py"
    disk_manager_module = load_module_directly("disk_manager", disk_manager_path)
    DiskManager = disk_manager_module.DiskManager

    disk_manager = DiskManager(args.models_dir)

    # Load inventory manager
    inventory_manager = None
    try:
        inventory_path = project_root / "src" / "model_runtime" / "inventory.py"
        if inventory_path.exists():
            inventory_module = load_module_directly("inventory", inventory_path)
            inventory_manager = inventory_module.ModelInventory(args.models_dir)
    except Exception:
        pass

    # Find cleanup candidates
    models_to_remove = []
    if not args.keep_models:
        models_to_remove = disk_manager.find_cleanup_candidates(min_size_mb=args.min_size)

    cache_paths = []
    if not args.keep_caches:
        cache_paths = find_cache_directories(project_root)

    # Calculate sizes
    models_size_mb = sum(m.size_mb for m in models_to_remove)
    caches_size_mb = calculate_total_size(cache_paths)

    # Build cleanup plan
    plan = {
        "models": [m.to_dict() for m in models_to_remove],
        "models_size_gb": models_size_mb / 1024,
        "caches": [str(p) for p in cache_paths],
        "caches_size_mb": caches_size_mb
    }

    # Dry run
    if args.dry_run:
        if args.json:
            plan["dry_run"] = True
            print(json.dumps(plan, indent=2))
        else:
            print("DRY RUN - No files will be deleted")
            print("=" * 70)
            print()
            if plan["models"]:
                print(f"Would remove {len(plan['models'])} model(s): {plan['models_size_gb']:.2f} GB")
            if plan["caches"]:
                print(f"Would remove {len(plan['caches'])} cache(s): {plan['caches_size_mb']:.1f} MB")
            print()
            total_gb = plan['models_size_gb'] + (plan['caches_size_mb'] / 1024)
            print(f"Total space to be freed: {total_gb:.2f} GB")
            print()
            print("Run without --dry-run to actually perform cleanup")
        return 0

    # Check if anything to clean
    if not models_to_remove and not cache_paths:
        if args.json:
            print(json.dumps({"message": "Nothing to clean up"}))
        else:
            print("Nothing to clean up")
        return 0

    # Confirmation (unless --force)
    if not args.force:
        if not confirm_cleanup(plan):
            print("Cleanup cancelled")
            return 0

    # Perform cleanup
    print()
    print("Performing cleanup...")
    print()

    results = {
        "models": {"removed": 0, "failed": 0, "size_freed_mb": 0},
        "caches": {"removed": 0, "failed": 0, "size_freed_mb": 0}
    }

    # Clean caches
    if cache_paths:
        print(f"Cleaning {len(cache_paths)} cache location(s)...")
        results["caches"] = cleanup_caches(cache_paths)
        print(f"✓ Removed {results['caches']['removed']} cache(s), "
              f"freed {results['caches']['size_freed_mb']:.1f} MB")

    # Clean models
    if models_to_remove:
        print(f"\nCleaning {len(models_to_remove)} model(s)...")
        results["models"] = cleanup_models(models_to_remove, disk_manager, inventory_manager)
        print(f"✓ Removed {results['models']['removed']} model(s), "
              f"freed {results['models']['size_freed_mb']/1024:.2f} GB")

    # Summary
    print()
    print("=" * 70)
    total_freed_gb = (
        results['models']['size_freed_mb'] + results['caches']['size_freed_mb']
    ) / 1024

    if args.json:
        results["total_freed_gb"] = round(total_freed_gb, 2)
        print(json.dumps(results, indent=2))
    else:
        print(f"Total space freed: {total_freed_gb:.2f} GB")

        total_failed = results['models']['failed'] + results['caches']['failed']
        if total_failed > 0:
            print(f"\n⚠️  {total_failed} item(s) failed to delete")

        print("\n✓ Cleanup complete")

    return 0


if __name__ == "__main__":
    sys.exit(main())
