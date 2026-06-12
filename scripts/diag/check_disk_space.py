#!/usr/bin/env python3
"""Check disk space usage for model storage."""

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
    parser = argparse.ArgumentParser(description="Check disk space for models")
    parser.add_argument("--models-dir", type=str, default="models", help="Models directory")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--by-backend", action="store_true", help="Show usage by backend")
    parser.add_argument("--by-model", action="store_true", help="Show usage by model")
    parser.add_argument("--cleanup-candidates", action="store_true", help="Show cleanup candidates")
    parser.add_argument("--min-size", type=float, default=100, help="Minimum size for cleanup (MB)")
    args = parser.parse_args()

    # Load disk_manager module directly
    project_root = Path(__file__).parent.parent
    disk_manager_path = project_root / "src" / "model_runtime" / "disk_manager.py"
    disk_manager_module = load_module_directly("disk_manager", disk_manager_path)
    DiskManager = disk_manager_module.DiskManager

    manager = DiskManager(args.models_dir)

    # Get disk usage
    usage = manager.get_disk_usage()

    if args.json:
        output = {
            "disk_usage": usage.to_dict(),
            "total_models_size_gb": round(manager.get_total_models_size(), 2),
        }

        if args.by_backend:
            output["usage_by_backend"] = {
                backend: round(size, 2) for backend, size in manager.get_usage_by_backend().items()
            }

        if args.by_model:
            output["models"] = [m.to_dict() for m in manager.get_models_usage()]

        if args.cleanup_candidates:
            output["cleanup_candidates"] = [
                m.to_dict() for m in manager.find_cleanup_candidates(min_size_mb=args.min_size)
            ]

        print(json.dumps(output, indent=2))

    else:
        # Text output
        print("Disk Space Report")
        print("=" * 70)
        print()
        print(f"Models Directory: {manager.models_dir}")
        print()
        print("Partition Usage:")
        print(f"  Total:     {usage.total_gb:>8.2f} GB")
        print(f"  Used:      {usage.used_gb:>8.2f} GB ({usage.percent_used:.1f}%)")
        print(f"  Free:      {usage.free_gb:>8.2f} GB")
        print()

        # Warning if approaching threshold
        if usage.percent_used >= manager.CRITICAL_THRESHOLD * 100:
            print("🔴 CRITICAL: Disk usage above 95%!")
            print("   Consider cleaning up models immediately.")
            print()
        elif usage.percent_used >= manager.WARN_THRESHOLD * 100:
            print("⚠️  WARNING: Disk usage above 90%")
            print("   Consider cleaning up models soon.")
            print()

        # Total models size
        total_models_gb = manager.get_total_models_size()
        print(f"Models Total: {total_models_gb:>8.2f} GB")
        print()

        # Usage by backend
        if args.by_backend:
            print("Usage by Backend:")
            for backend, size in sorted(manager.get_usage_by_backend().items()):
                print(f"  {backend:15s}: {size:>8.2f} GB")
            print()

        # Usage by model
        if args.by_model:
            models = manager.get_models_usage()
            print(f"Models ({len(models)} total):")
            print(f"  {'Model ID':<30} {'Backend':<15} {'Size':>10}")
            print("  " + "-" * 58)
            for model in models[:20]:  # Show top 20
                print(f"  {model.model_id:<30} {model.backend:<15} {model.size_mb:>8.1f} MB")

            if len(models) > 20:
                remaining = len(models) - 20
                remaining_size = sum(m.size_mb for m in models[20:]) / 1024
                print(f"\n  ... and {remaining} more models ({remaining_size:.2f} GB)")
            print()

        # Cleanup candidates
        if args.cleanup_candidates:
            candidates = manager.find_cleanup_candidates(min_size_mb=args.min_size)
            if candidates:
                print(f"Cleanup Candidates (>{args.min_size} MB):")
                total_cleanup_gb = sum(m.size_mb for m in candidates) / 1024
                print(f"  Found {len(candidates)} models totaling {total_cleanup_gb:.2f} GB")
                print()
                print(f"  {'Model ID':<30} {'Size':>10} {'Last Accessed'}")
                print("  " + "-" * 60)
                for model in candidates[:10]:  # Show top 10
                    last_access = model.last_accessed or "unknown"
                    if len(last_access) > 20:
                        last_access = last_access[:20]
                    print(f"  {model.model_id:<30} {model.size_mb:>8.1f} MB {last_access}")

                if len(candidates) > 10:
                    print(f"\n  ... and {len(candidates) - 10} more candidates")
                print()
                print("  Run scripts/models/cleanup_models.py to remove unused models")
            else:
                print(f"No cleanup candidates found (threshold: {args.min_size} MB)")
                print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
