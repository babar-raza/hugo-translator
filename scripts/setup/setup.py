#!/usr/bin/env python
"""
Setup script for Hugo Translation System.

Initializes directories, downloads models, and verifies installation.
"""

import argparse
import sys
from pathlib import Path


def setup_directories(base_dir: Path) -> bool:
    """Create required directories."""
    print("Creating directories...")

    dirs = [
        base_dir / "data",
        base_dir / "logs",
        base_dir / "artifacts",
        base_dir / "models",
    ]

    for dir_path in dirs:
        try:
            dir_path.mkdir(parents=True, exist_ok=True)
            print(f"✓ Created {dir_path}")
        except Exception as e:
            print(f"✗ Failed to create {dir_path}: {e}")
            return False

    return True


def verify_dependencies() -> bool:
    """Verify required packages are installed."""
    print("\nVerifying dependencies...")

    required = [
        "pydantic",
        "yaml",
        "lmdb",
        "torch",
        "transformers",
        "sentence_transformers",
        "watchdog",
        "structlog",
    ]

    missing = []
    for package in required:
        try:
            __import__(package)
            print(f"✓ {package}")
        except ImportError:
            print(f"✗ {package} (missing)")
            missing.append(package)

    if missing:
        print(f"\nMissing packages: {', '.join(missing)}")
        print("Install with: pip install -r requirements/base.txt")
        return False

    return True


def verify_installation(base_dir: Path) -> bool:
    """Run installation checks."""
    print("\nVerifying installation...")

    # Check config directory
    config_dir = base_dir / "config"
    if not config_dir.exists():
        print(f"✗ Config directory not found: {config_dir}")
        return False
    print(f"✓ Config directory: {config_dir}")

    # Check for site profiles
    profiles_dir = config_dir / "site_profiles"
    if profiles_dir.exists():
        profiles = list(profiles_dir.glob("*.yaml"))
        print(f"✓ Found {len(profiles)} site profile(s)")
    else:
        print("⚠ No site profiles directory found")

    # Check model registry
    model_registry = config_dir / "model_registry.yaml"
    if model_registry.exists():
        print(f"✓ Model registry: {model_registry}")
    else:
        print(f"⚠ Model registry not found: {model_registry}")

    return True


def main():
    parser = argparse.ArgumentParser(description="Setup Hugo Translation System")
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=Path.cwd(),
        help="Base directory (default: current directory)",
    )

    args = parser.parse_args()
    base_dir = args.base_dir.resolve()

    print("Hugo Translation System Setup")
    print(f"Base directory: {base_dir}\n")

    # Run setup steps
    steps = [
        ("Dependencies", verify_dependencies),
        ("Directories", lambda: setup_directories(base_dir)),
        ("Installation", lambda: verify_installation(base_dir)),
    ]

    for step_name, step_func in steps:
        if not step_func():
            print(f"\n✗ Setup failed at: {step_name}")
            return 1

    print("\n✓ Setup completed successfully!")
    print("\nNext steps:")
    print("1. Create site profile in config/site_profiles/")
    print("2. Configure .env file")
    print("3. Run example translation")

    return 0


if __name__ == "__main__":
    sys.exit(main())
