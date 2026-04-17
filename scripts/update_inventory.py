#!/usr/bin/env python3
"""Update model inventory database."""
import argparse
import importlib.util
import json
import sys
from pathlib import Path


def load_module_directly(module_name, module_path):
    """Load a module directly from file path."""
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description="Update model inventory")
    parser.add_argument("--models-dir", type=str, default="models", help="Models directory")
    parser.add_argument("--output", type=str, help="Output file (default: models/inventory.json)")
    parser.add_argument("--stats", action="store_true", help="Show statistics")
    parser.add_argument("--list", action="store_true", help="List all models")
    parser.add_argument("--find", type=str, help="Find model by ID")
    parser.add_argument("--backend", type=str, help="Filter by backend")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    # Load inventory module directly
    project_root = Path(__file__).parent.parent
    inventory_path = project_root / "src" / "model_runtime" / "inventory.py"
    inventory_module = load_module_directly("inventory", inventory_path)
    ModelInventory = inventory_module.ModelInventory

    # Create inventory manager
    inventory_file = Path(args.output) if args.output else None
    inventory = ModelInventory(args.models_dir, inventory_file)

    # Execute command
    if args.stats:
        # Show statistics
        stats = inventory.get_stats()

        if args.json:
            print(json.dumps({
                "total_models": stats.total_models,
                "total_size_mb": stats.total_size_mb,
                "total_size_gb": stats.total_size_gb,
                "models_by_backend": stats.models_by_backend,
                "models_by_status": stats.models_by_status,
                "last_updated": stats.last_updated
            }, indent=2))
        else:
            print("Model Inventory Statistics")
            print("=" * 60)
            print(f"Total models: {stats.total_models}")
            print(f"Total size: {stats.total_size_mb:.1f} MB ({stats.total_size_gb:.2f} GB)")
            print(f"Last updated: {stats.last_updated}")
            print()
            print("By backend:")
            for backend, count in sorted(stats.models_by_backend.items()):
                print(f"  {backend}: {count} models")
            print()
            print("By verification status:")
            for status, count in sorted(stats.models_by_status.items()):
                print(f"  {status}: {count} models")

    elif args.list or args.find or args.backend:
        # Find/list models
        entries = inventory.find(
            model_id=args.find,
            backend=args.backend
        )

        if args.json:
            print(json.dumps([e.to_dict() for e in entries], indent=2))
        else:
            print(f"Found {len(entries)} model(s)")
            print("=" * 60)
            for entry in entries:
                print(f"\n{entry.model_id}")
                print(f"  Backend: {entry.backend}")
                print(f"  Path: {entry.local_path}")
                print(f"  Size: {entry.size_mb} MB")
                print(f"  Downloaded: {entry.downloaded_at}")
                if entry.verification_status:
                    print(f"  Verification: {entry.verification_status}")
                if entry.hf_model_id:
                    print(f"  HuggingFace: {entry.hf_model_id}")

    else:
        # Update inventory (default action)
        print("Scanning models directory...")
        entries = inventory.scan()
        print(f"Found {len(entries)} models")

        print("Updating inventory...")
        inventory.update(entries)

        stats = inventory.get_stats()
        print(f"✓ Inventory updated: {stats.total_models} models, {stats.total_size_gb:.2f} GB")
        print(f"  Saved to: {inventory.inventory_file}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
