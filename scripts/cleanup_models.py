#!/usr/bin/env python3
"""Clean up unused models to free disk space."""
import argparse
import json
import shutil
import sys
from pathlib import Path
import importlib.util


def load_module_directly(module_name, module_path):
    """Load a module directly from file path."""
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def confirm_deletion(models, total_size_gb):
    """Prompt user for confirmation.

    Args:
        models: List of ModelDiskInfo to delete
        total_size_gb: Total size to be freed

    Returns:
        True if user confirms
    """
    print()
    print("=" * 70)
    print("DELETION PLAN")
    print("=" * 70)
    print(f"\nWill delete {len(models)} model(s) totaling {total_size_gb:.2f} GB:")
    print()
    for model in models:
        print(f"  - {model.model_id} ({model.size_mb:.1f} MB) from {model.backend}")
    print()
    print(f"Total space to be freed: {total_size_gb:.2f} GB")
    print()

    response = input("Proceed with deletion? [yes/NO]: ").strip().lower()
    return response in ['yes', 'y']


def delete_model(model, inventory_manager=None):
    """Delete a model and update inventory.

    Args:
        model: ModelDiskInfo to delete
        inventory_manager: Optional ModelInventory instance

    Returns:
        True if successful
    """
    try:
        # Delete model directory
        if model.path.exists():
            shutil.rmtree(model.path)
            print(f"✓ Deleted {model.model_id}")

            # Update inventory if available
            if inventory_manager:
                entries = inventory_manager.load()
                entries = [e for e in entries if e.model_id != model.model_id]
                inventory_manager.update(entries)

            return True
        else:
            print(f"✗ Model not found: {model.model_id}")
            return False

    except Exception as e:
        print(f"✗ Error deleting {model.model_id}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Clean up unused models")
    parser.add_argument("--models-dir", type=str, default="models", help="Models directory")
    parser.add_argument("--min-size", type=float, default=100, help="Minimum size to consider (MB)")
    parser.add_argument("--days-unused", type=int, help="Only delete if unused for N days")
    parser.add_argument("--backend", type=str, help="Only delete from specific backend")
    parser.add_argument("--model", type=str, help="Delete specific model by ID")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted")
    parser.add_argument("--force", action="store_true", help="Skip confirmation")
    parser.add_argument("--json", action="store_true", help="Output JSON report")
    args = parser.parse_args()

    # Load disk_manager module directly
    project_root = Path(__file__).parent.parent
    disk_manager_path = project_root / "src" / "model_runtime" / "disk_manager.py"
    disk_manager_module = load_module_directly("disk_manager", disk_manager_path)
    DiskManager = disk_manager_module.DiskManager

    manager = DiskManager(args.models_dir)

    # Load inventory manager if available
    inventory_manager = None
    try:
        inventory_path = project_root / "src" / "model_runtime" / "inventory.py"
        if inventory_path.exists():
            inventory_module = load_module_directly("inventory", inventory_path)
            inventory_manager = inventory_module.ModelInventory(args.models_dir)
    except Exception:
        pass

    # Find cleanup candidates
    if args.model:
        # Delete specific model
        all_models = manager.get_models_usage()
        models_to_delete = [m for m in all_models if m.model_id == args.model]
        if not models_to_delete:
            print(f"Model not found: {args.model}")
            return 1
    else:
        # Find candidates based on criteria
        models_to_delete = manager.find_cleanup_candidates(
            min_size_mb=args.min_size,
            days_since_access=args.days_unused
        )

        # Filter by backend if specified
        if args.backend:
            models_to_delete = [m for m in models_to_delete if m.backend == args.backend]

    if not models_to_delete:
        print("No models found matching cleanup criteria")
        return 0

    total_size_mb = sum(m.size_mb for m in models_to_delete)
    total_size_gb = total_size_mb / 1024

    # Dry run mode
    if args.dry_run:
        if args.json:
            output = {
                "dry_run": True,
                "models_to_delete": [m.to_dict() for m in models_to_delete],
                "total_size_mb": round(total_size_mb, 1),
                "total_size_gb": round(total_size_gb, 2)
            }
            print(json.dumps(output, indent=2))
        else:
            print("DRY RUN - No files will be deleted")
            print("=" * 70)
            print(f"\nFound {len(models_to_delete)} model(s) totaling {total_size_gb:.2f} GB:")
            print()
            for model in models_to_delete:
                backend_info = f"[{model.backend}]" if model.backend else ""
                accessed = f"(last accessed: {model.last_accessed[:10]})" if model.last_accessed else "(never accessed)"
                print(f"  - {model.model_id:<30} {model.size_mb:>8.1f} MB {backend_info} {accessed}")
            print()
            print("Run without --dry-run to actually delete these models")

        return 0

    # Confirmation (unless --force)
    if not args.force:
        if not confirm_deletion(models_to_delete, total_size_gb):
            print("Deletion cancelled")
            return 0

    # Perform deletion
    print()
    print("Deleting models...")
    deleted_count = 0
    deleted_size = 0

    for model in models_to_delete:
        if delete_model(model, inventory_manager):
            deleted_count += 1
            deleted_size += model.size_mb

    # Summary
    print()
    print("=" * 70)
    if args.json:
        output = {
            "deleted_count": deleted_count,
            "deleted_size_mb": round(deleted_size, 1),
            "deleted_size_gb": round(deleted_size / 1024, 2),
            "failed_count": len(models_to_delete) - deleted_count
        }
        print(json.dumps(output, indent=2))
    else:
        print(f"Deleted {deleted_count}/{len(models_to_delete)} model(s)")
        print(f"Freed {deleted_size/1024:.2f} GB of disk space")

        if deleted_count < len(models_to_delete):
            print(f"\n⚠️  {len(models_to_delete) - deleted_count} model(s) failed to delete")

    return 0 if deleted_count == len(models_to_delete) else 1


if __name__ == "__main__":
    sys.exit(main())
