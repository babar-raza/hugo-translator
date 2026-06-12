#!/usr/bin/env python3
"""Safely remove a specific model."""

import argparse
import importlib.util
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path


def load_module_directly(module_name, module_path):
    """Load a module directly from file path."""
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def find_model_path(models_dir: Path, model_id: str):
    """Find the path to a model by ID.

    Args:
        models_dir: Base models directory
        model_id: Model ID to find

    Returns:
        Tuple of (path: Path, backend: str) or (None, None) if not found
    """
    for backend_dir in models_dir.iterdir():
        if not backend_dir.is_dir():
            continue

        model_path = backend_dir / model_id
        if model_path.exists() and model_path.is_dir():
            return model_path, backend_dir.name

    return None, None


def confirm_deletion(model_id: str, model_path: Path, size_mb: float):
    """Prompt user for confirmation.

    Args:
        model_id: Model ID
        model_path: Path to model
        size_mb: Model size in MB

    Returns:
        True if user confirms
    """
    print()
    print("=" * 70)
    print("DELETION CONFIRMATION")
    print("=" * 70)
    print(f"\nModel ID:   {model_id}")
    print(f"Path:       {model_path}")
    print(f"Size:       {size_mb:.1f} MB ({size_mb / 1024:.2f} GB)")
    print()
    print("⚠️  This action cannot be undone!")
    print()

    response = input("Type the model ID to confirm deletion: ").strip()
    return response == model_id


def calculate_dir_size(path: Path) -> float:
    """Calculate directory size in MB."""
    total = 0
    try:
        for item in path.rglob("*"):
            if item.is_file():
                total += item.stat().st_size
    except (PermissionError, OSError):
        pass

    return total / (1024 * 1024)


def create_backup(model_path: Path, backup_dir: Path) -> Path:
    """Create a backup of the model before deletion.

    Args:
        model_path: Path to model
        backup_dir: Directory for backups

    Returns:
        Path to backup
    """
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"{model_path.name}_{timestamp}"
    backup_path = backup_dir / backup_name

    print(f"Creating backup at {backup_path}...")
    shutil.copytree(model_path, backup_path)
    print("✓ Backup created")

    return backup_path


def remove_model(
    model_id: str,
    models_dir: Path,
    inventory_manager=None,
    create_backup_flag: bool = False,
    backup_dir: Path = None,
):
    """Remove a model and update inventory.

    Args:
        model_id: Model ID to remove
        models_dir: Base models directory
        inventory_manager: Optional ModelInventory instance
        create_backup_flag: Whether to create backup before deletion
        backup_dir: Directory for backups

    Returns:
        True if successful
    """
    # Find model
    model_path, backend = find_model_path(models_dir, model_id)

    if not model_path:
        print(f"✗ Model not found: {model_id}")
        return False

    # Calculate size
    size_mb = calculate_dir_size(model_path)

    # Create backup if requested
    if create_backup_flag:
        try:
            backup_path = create_backup(model_path, backup_dir or models_dir / ".backups")
            print(f"Backup location: {backup_path}")
        except Exception as e:
            print(f"✗ Failed to create backup: {e}")
            print("Deletion aborted for safety")
            return False

    # Delete model directory
    try:
        shutil.rmtree(model_path)
        print(f"✓ Deleted model directory: {model_path}")
    except Exception as e:
        print(f"✗ Error deleting model: {e}")
        return False

    # Update inventory
    if inventory_manager:
        try:
            entries = inventory_manager.load()
            original_count = len(entries)
            entries = [e for e in entries if e.model_id != model_id]

            if len(entries) < original_count:
                inventory_manager.update(entries)
                print(f"✓ Updated inventory (removed {original_count - len(entries)} entry)")
        except Exception as e:
            print(f"⚠️  Warning: Failed to update inventory: {e}")
            # Don't fail the whole operation for inventory issues

    print(f"\n✓ Successfully removed {model_id} (freed {size_mb / 1024:.2f} GB)")
    return True


def main():
    parser = argparse.ArgumentParser(description="Remove a specific model")
    parser.add_argument("model_id", help="Model ID to remove")
    parser.add_argument("--models-dir", type=str, default="models", help="Models directory")
    parser.add_argument("--force", action="store_true", help="Skip confirmation")
    parser.add_argument("--backup", action="store_true", help="Create backup before deletion")
    parser.add_argument("--backup-dir", type=str, help="Custom backup directory")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    project_root = Path(__file__).parent.parent
    models_dir = Path(args.models_dir)

    # Load inventory manager if available
    inventory_manager = None
    try:
        inventory_path = project_root / "src" / "model_runtime" / "inventory.py"
        if inventory_path.exists():
            inventory_module = load_module_directly("inventory", inventory_path)
            inventory_manager = inventory_module.ModelInventory(str(models_dir))
    except Exception:
        pass

    # Find model
    model_path, backend = find_model_path(models_dir, args.model_id)

    if not model_path:
        if args.json:
            print(json.dumps({"success": False, "error": f"Model not found: {args.model_id}"}))
        else:
            print(f"✗ Model not found: {args.model_id}")
        return 1

    # Get model size
    size_mb = calculate_dir_size(model_path)

    # Confirmation (unless --force)
    if not args.force:
        if not confirm_deletion(args.model_id, model_path, size_mb):
            if args.json:
                print(json.dumps({"success": False, "error": "Deletion cancelled by user"}))
            else:
                print("\nDeletion cancelled")
            return 0

    # Remove model
    backup_dir = Path(args.backup_dir) if args.backup_dir else None
    success = remove_model(args.model_id, models_dir, inventory_manager, args.backup, backup_dir)

    # Output
    if args.json:
        output = {
            "success": success,
            "model_id": args.model_id,
            "size_mb": round(size_mb, 1),
            "size_gb": round(size_mb / 1024, 2),
        }
        print(json.dumps(output, indent=2))

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
