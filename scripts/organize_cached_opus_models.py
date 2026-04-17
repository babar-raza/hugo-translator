"""
Organize Opus models from HF cache into models/opus/ layout.

Copies cached Helsinki-NLP/opus-mt-en-XX models from HuggingFace cache
to the organized models/opus/opus-mt-en-XX/ directory structure.

This avoids re-downloading ~8.3 GB of models that are already cached.
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def find_hf_cache_dir() -> Path | None:
    """Find HuggingFace cache directory."""
    cache_dir = Path.home() / ".cache" / "huggingface" / "hub"
    if cache_dir.exists():
        return cache_dir
    return None

def find_opus_models_in_cache(cache_dir: Path) -> list[tuple[str, Path]]:
    """
    Find Opus models in HF cache.

    Returns:
        List of (language_code, snapshot_path) tuples
    """
    models = []

    for model_dir in cache_dir.iterdir():
        if not model_dir.is_dir():
            continue

        # Match: models--Helsinki-NLP--opus-mt-en-{lang}
        if not model_dir.name.startswith("models--Helsinki-NLP--opus-mt-en-"):
            continue

        # Extract language code
        parts = model_dir.name.split("--")
        if len(parts) < 3:
            continue

        model_name = parts[2]  # e.g., "opus-mt-en-fr"
        if not model_name.startswith("opus-mt-en-"):
            continue

        lang = model_name.replace("opus-mt-en-", "")

        # Skip multilingual models (e.g., ROMANCE)
        if lang.isupper():
            print(f"Skipping multilingual model: {model_name}")
            continue

        # Find latest snapshot
        snapshots_dir = model_dir / "snapshots"
        if not snapshots_dir.exists():
            print(f"Warning: No snapshots found for {model_name}")
            continue

        snapshots = list(snapshots_dir.iterdir())
        if not snapshots:
            print(f"Warning: Empty snapshots directory for {model_name}")
            continue

        # Get latest snapshot (by modification time)
        latest_snapshot = max(snapshots, key=lambda p: p.stat().st_mtime)

        models.append((lang, latest_snapshot))

    return sorted(models, key=lambda x: x[0])

def copy_model_to_organized_layout(
    lang: str,
    source_path: Path,
    models_dir: Path,
    dry_run: bool = False
) -> bool:
    """
    Copy model from HF cache to organized layout.

    Args:
        lang: Language code (e.g., 'fr')
        source_path: Source snapshot directory
        models_dir: Base models directory
        dry_run: If True, only print what would be done

    Returns:
        True if successful, False otherwise
    """
    target_dir = models_dir / "opus" / f"opus-mt-en-{lang}"

    if target_dir.exists():
        print(f"  [OK] {lang}: Already exists at {target_dir}")
        return True

    if dry_run:
        print(f"  [DRY RUN] Would copy {lang}: {source_path} -> {target_dir}")
        return True

    try:
        # Create parent directory
        target_dir.parent.mkdir(parents=True, exist_ok=True)

        # Copy entire snapshot directory
        print(f"  Copying {lang}: {source_path} -> {target_dir}")
        shutil.copytree(source_path, target_dir)

        # Verify essential files exist
        if not (target_dir / "config.json").exists():
            print(f"  [WARN] Warning: config.json missing for {lang}")
            return False

        print(f"  [DONE] {lang}: Copied successfully")
        return True

    except Exception as e:
        print(f"  [FAIL] {lang}: Failed to copy: {e}")
        return False

def main() -> int:
    """Organize cached Opus models."""
    parser = argparse.ArgumentParser(
        description="Organize Opus models from HF cache to models/opus/"
    )
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=Path("models"),
        help="Base models directory (default: models)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without copying"
    )
    parser.add_argument(
        "--languages",
        help="Comma-separated list of languages to organize (default: all)"
    )
    args = parser.parse_args()

    # Find HF cache
    cache_dir = find_hf_cache_dir()
    if not cache_dir:
        print("[FAIL] HuggingFace cache directory not found")
        return 1

    print(f"Found HF cache: {cache_dir}")

    # Find Opus models
    print("\nScanning for Opus models in cache...")
    cached_models = find_opus_models_in_cache(cache_dir)

    if not cached_models:
        print("No Opus models found in cache")
        return 0

    print(f"Found {len(cached_models)} Opus models in cache")

    # Filter by language if specified
    if args.languages:
        requested_langs = set(lang.strip() for lang in args.languages.split(","))
        cached_models = [(lang, path) for lang, path in cached_models if lang in requested_langs]
        print(f"Filtered to {len(cached_models)} requested languages")

    if not cached_models:
        print("No models to organize after filtering")
        return 0

    # Organize models
    print(f"\n{'DRY RUN: ' if args.dry_run else ''}Organizing {len(cached_models)} models...")

    success_count = 0
    for lang, source_path in cached_models:
        if copy_model_to_organized_layout(lang, source_path, args.models_dir, args.dry_run):
            success_count += 1

    print(f"\n{'Would organize' if args.dry_run else 'Organized'} {success_count}/{len(cached_models)} models")

    if not args.dry_run:
        print(f"\n[DONE] Models available in: {args.models_dir / 'opus'}")
        print("\nNext steps:")
        print("1. Update manifest: python -m src.model_runtime.model_cli sync-registry")
        print("2. Verify models: python -m src.model_runtime.model_cli verify --all")

    return 0 if success_count == len(cached_models) else 1

if __name__ == "__main__":
    raise SystemExit(main())
