"""
Download Opus models directly to models/opus/ organized layout.

Downloads Helsinki-NLP/opus-mt-en-XX models from HuggingFace Hub
directly into the organized models/opus/opus-mt-en-XX/ structure.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from huggingface_hub import snapshot_download
except ImportError:
    print("[FAIL] huggingface_hub not installed. Install with: pip install huggingface_hub")
    sys.exit(1)


def download_opus_model(lang: str, models_dir: Path = Path("models"), force: bool = False) -> bool:
    """
    Download Opus model for language.

    Args:
        lang: Target language code (e.g., 'fr')
        models_dir: Base models directory
        force: Re-download even if exists

    Returns:
        True if successful
    """
    model_name = f"opus-mt-en-{lang}"
    hf_model_id = f"Helsinki-NLP/{model_name}"
    target_dir = models_dir / "opus" / model_name

    if target_dir.exists() and not force:
        print(f"  [SKIP] {lang}: Already exists at {target_dir}")
        return True

    print(f"  [DOWNLOAD] {lang}: {hf_model_id} -> {target_dir}")

    try:
        # Create parent directory
        target_dir.parent.mkdir(parents=True, exist_ok=True)

        # Download entire model
        snapshot_download(
            repo_id=hf_model_id,
            local_dir=target_dir,
            local_dir_use_symlinks=False,  # Copy files, don't symlink
        )

        # Verify config.json exists
        if not (target_dir / "config.json").exists():
            print(f"  [WARN] {lang}: config.json missing after download")
            return False

        print(f"  [DONE] {lang}: Downloaded successfully")
        return True

    except Exception as e:
        print(f"  [FAIL] {lang}: {e}")
        return False


def main() -> int:
    """Download Opus models."""
    parser = argparse.ArgumentParser(description="Download Opus models directly to models/opus/")
    parser.add_argument(
        "--languages", required=True, help="Comma-separated list of language codes (e.g., fr,de,es)"
    )
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=Path("models"),
        help="Base models directory (default: models)",
    )
    parser.add_argument("--force", action="store_true", help="Re-download even if model exists")
    args = parser.parse_args()

    # Parse languages
    languages = [lang.strip() for lang in args.languages.split(",")]
    print(f"Downloading {len(languages)} Opus models...")

    # Download each model
    success_count = 0
    for lang in languages:
        if download_opus_model(lang, args.models_dir, args.force):
            success_count += 1

    print(f"\nDownloaded {success_count}/{len(languages)} models")
    print(f"Models available in: {args.models_dir / 'opus'}")

    return 0 if success_count == len(languages) else 1


if __name__ == "__main__":
    raise SystemExit(main())
