"""
Discover locally cached HuggingFace models and write a local registry.

Scans the HF cache for model folders and emits a lightweight
config/model_registry.local.yaml without overwriting the main registry.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List

import yaml


def _parse_hf_id(dir_name: str) -> str | None:
    if not dir_name.startswith("models--"):
        return None
    parts = dir_name.split("--")[1:]
    if len(parts) < 2:
        return None
    org = parts[0]
    model = "--".join(parts[1:])
    return f"{org}/{model}"


def _is_candidate_model(hf_id: str, patterns: List[str]) -> bool:
    lower = hf_id.lower()
    return any(pattern in lower for pattern in patterns)


def _load_existing_registry(path: Path) -> Dict[str, Dict]:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    models = data.get("models", [])
    return {model.get("model_id"): model for model in models if model.get("model_id")}


def _load_main_registry_ids(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    models = data.get("models", [])
    return {
        model.get("model_id"): model.get("hf_model_id", "")
        for model in models
        if model.get("model_id")
    }


def _model_id_from_hf_id(hf_id: str) -> str:
    return hf_id.replace("/", "_").replace("-", "_")


def discover_models(cache_dir: Path, patterns: List[str]) -> List[str]:
    if not cache_dir.exists():
        return []
    hf_ids = []
    for child in cache_dir.iterdir():
        if not child.is_dir():
            continue
        hf_id = _parse_hf_id(child.name)
        if not hf_id:
            continue
        if not _is_candidate_model(hf_id, patterns):
            continue
        hf_ids.append(hf_id)
    return sorted(set(hf_ids))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Discover local HF cache models and write model_registry.local.yaml"
    )
    parser.add_argument(
        "--cache-dir",
        default=str(Path.home() / ".cache" / "huggingface" / "hub"),
        help="Path to HuggingFace cache hub directory",
    )
    parser.add_argument(
        "--output",
        default="config/model_registry.local.yaml",
        help="Output registry path",
    )
    parser.add_argument(
        "--patterns",
        default="m2m100,nllb,mbart,opus-mt",
        help="Comma-separated model name filters",
    )
    args = parser.parse_args()

    cache_dir = Path(args.cache_dir)
    output_path = Path(args.output)
    patterns = [p.strip() for p in args.patterns.split(",") if p.strip()]

    hf_ids = discover_models(cache_dir, patterns)
    main_registry_ids = _load_main_registry_ids(Path("config/model_registry.yaml"))
    existing_local = _load_existing_registry(output_path)

    models: Dict[str, Dict] = dict(existing_local)

    for hf_id in hf_ids:
        model_id = _model_id_from_hf_id(hf_id)
        if model_id in main_registry_ids:
            continue
        if model_id in models:
            continue

        models[model_id] = {
            "model_id": model_id,
            "name": hf_id,
            "backend": "huggingface",
            "supported_pairs": "all",
            "model_size_mb": 0,
            "min_ram_gb": 0,
            "optimal_device": "cuda",
            "hf_model_id": hf_id,
            "description": "Auto-discovered from local HuggingFace cache.",
        }

    output_data = {"models": list(models.values())}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(output_data, f, default_flow_style=False, sort_keys=False)

    print(f"Discovered {len(hf_ids)} HF cache model(s).")
    print(f"Wrote {len(models)} model(s) to {output_path}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
