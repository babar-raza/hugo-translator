#!/usr/bin/env python3
"""Download translation models from HuggingFace Hub."""
import argparse
import importlib.util
import sys
from pathlib import Path


def load_module_directly(module_name, module_path):
    """Load a module directly from file path without triggering package imports."""
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(
        description="Download translation models"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Download all models from registry"
    )
    parser.add_argument(
        "--model",
        type=str,
        help="Download specific model by ID"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-download if already exists"
    )
    parser.add_argument(
        "--parallel",
        type=int,
        default=1,
        help="Number of concurrent downloads"
    )
    parser.add_argument(
        "--models-dir",
        type=str,
        default="models",
        help="Models base directory"
    )

    args = parser.parse_args()

    # Load downloader module directly
    project_root = Path(__file__).parent.parent
    downloader_path = project_root / "src" / "model_runtime" / "downloader.py"
    downloader_module = load_module_directly("downloader", downloader_path)
    ModelDownloader = downloader_module.ModelDownloader

    # Load model registry
    try:
        import yaml
        with open("config/model_registry.yaml") as f:
            registry = yaml.safe_load(f)
    except ImportError:
        print("Error: PyYAML not installed. Install with: pip install pyyaml")
        return 1
    except FileNotFoundError:
        print("Error: config/model_registry.yaml not found")
        return 1

    downloader = ModelDownloader(args.models_dir)

    # Determine which models to download
    models_to_download = []
    if args.all:
        models_to_download = registry['models']
    elif args.model:
        model = next((m for m in registry['models'] if m['model_id'] == args.model), None)
        if not model:
            print(f"✗ Model {args.model} not found in registry")
            return 1
        models_to_download = [model]
    else:
        print("Error: Specify --all or --model <id>")
        return 1

    # Download models
    print(f"Will download {len(models_to_download)} model(s)")
    success_count = 0

    for model in models_to_download:
        try:
            hf_id = model.get('hf_model_id')
            if not hf_id:
                print(f"⊘ Skipping {model['model_id']} (no HuggingFace ID)")
                continue

            print(f"\nDownloading {model['model_id']}...")
            downloader.download(
                model_id=model['model_id'],
                hf_model_id=hf_id,
                backend=model.get('backend', 'huggingface'),
                force=args.force
            )
            success_count += 1

        except Exception as e:
            print(f"✗ Failed to download {model['model_id']}: {e}")

    print(f"\n✓ Downloaded {success_count}/{len(models_to_download)} models")
    return 0 if success_count == len(models_to_download) else 1


if __name__ == "__main__":
    sys.exit(main())
