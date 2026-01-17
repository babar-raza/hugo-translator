"""
Discover locally cached HuggingFace models and write a local registry.

Scans the HF cache for model folders and emits a lightweight
config/model_registry.local.yaml without overwriting the main registry.

Improvements:
- Correctly identifies Opus pair models (Helsinki-NLP/opus-mt-en-XX)
- Emits proper supported_pairs for bilingual models
- Computes actual model size from cache
- Only marks as organized if in models/ directory
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Dict, List, Optional

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


def _parse_opus_language_pair(hf_id: str) -> Optional[tuple[str, str]]:
    """
    Parse Opus model HF ID to extract language pair.

    Examples:
        Helsinki-NLP/opus-mt-en-fr -> (en, fr)
        Helsinki-NLP/opus-mt-de-en -> (de, en)

    Returns:
        (src_lang, tgt_lang) if Opus model, None otherwise
    """
    # Pattern: Helsinki-NLP/opus-mt-{src}-{tgt}
    match = re.match(r"Helsinki-NLP/opus-mt-([a-z]{2,3})-([a-z]{2,3})$", hf_id, re.IGNORECASE)
    if match:
        return (match.group(1).lower(), match.group(2).lower())
    return None


def _compute_directory_size_mb(directory: Path) -> float:
    """
    Compute total size of directory in MB.

    Args:
        directory: Path to directory

    Returns:
        Size in MB
    """
    if not directory.exists():
        return 0.0

    total_bytes = 0
    for file_path in directory.rglob("*"):
        if file_path.is_file():
            total_bytes += file_path.stat().st_size

    return total_bytes / (1024 ** 2)


def _get_cache_directory(cache_dir: Path, hf_id: str) -> Optional[Path]:
    """
    Get cache directory for HF model.

    Args:
        cache_dir: Base HF cache directory
        hf_id: HuggingFace model ID (e.g., "facebook/m2m100_418M")

    Returns:
        Path to cached model directory if exists, None otherwise
    """
    # HF cache pattern: models--{org}--{model}
    dir_name = "models--" + hf_id.replace("/", "--")
    model_dir = cache_dir / dir_name

    if model_dir.exists():
        # Find snapshots subdirectory (latest snapshot)
        snapshots_dir = model_dir / "snapshots"
        if snapshots_dir.exists():
            # Get latest snapshot (by modification time)
            snapshots = list(snapshots_dir.iterdir())
            if snapshots:
                latest = max(snapshots, key=lambda p: p.stat().st_mtime)
                return latest

    return None


def _check_model_in_organized_layout(hf_id: str, models_dir: Path = Path("models")) -> Optional[Path]:
    """
    Check if model exists in organized models/ layout.

    Args:
        hf_id: HuggingFace model ID
        models_dir: Base models directory

    Returns:
        Path if found, None otherwise
    """
    # Check Opus layout: models/opus/opus-mt-en-XX/
    if "opus-mt-" in hf_id:
        repo_name = hf_id.split("/")[-1]
        opus_path = models_dir / "opus" / repo_name
        if opus_path.exists() and (opus_path / "config.json").exists():
            return opus_path

    # Check direct layout: models/{model_name}/
    # Extract model name from HF ID
    model_name = hf_id.split("/")[-1]
    direct_path = models_dir / model_name
    if direct_path.exists() and (direct_path / "config.json").exists():
        return direct_path

    return None


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

        # Determine supported_pairs based on model type
        opus_pair = _parse_opus_language_pair(hf_id)
        if opus_pair:
            # Bilingual Opus model: emit both directions
            src, tgt = opus_pair
            supported_pairs = [[src, tgt], [tgt, src]]
            backend = "opus"
            description = f"Auto-discovered Opus bilingual model ({src}↔{tgt}) from HF cache."
        else:
            # Multilingual model (M2M100, NLLB, etc.)
            supported_pairs = "all"
            backend = "huggingface"
            description = "Auto-discovered multilingual model from HF cache."

        # Compute model size from cache
        cache_model_dir = _get_cache_directory(cache_dir, hf_id)
        if cache_model_dir:
            model_size_mb = _compute_directory_size_mb(cache_model_dir)
            # Estimate RAM requirement: ~2x model size + 1GB base overhead
            min_ram_gb = (model_size_mb / 1024 * 2) + 1.0
        else:
            model_size_mb = 0
            min_ram_gb = 4.0  # Conservative default

        # Check if model exists in organized layout
        organized_path = _check_model_in_organized_layout(hf_id)
        if organized_path:
            local_path = str(organized_path)
            source_note = f" (found in organized layout: {local_path})"
        else:
            local_path = None
            source_note = " (only in HF cache, not organized)"

        models[model_id] = {
            "model_id": model_id,
            "name": hf_id,
            "backend": backend,
            "supported_pairs": supported_pairs,
            "model_size_mb": int(model_size_mb),
            "min_ram_gb": round(min_ram_gb, 1),
            "optimal_device": "cuda" if model_size_mb > 500 else "cpu",
            "hf_model_id": hf_id,
            "description": description + source_note,
        }
        if local_path:
            models[model_id]["local_path"] = local_path

    output_data = {"models": list(models.values())}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(output_data, f, default_flow_style=False, sort_keys=False)

    print(f"Discovered {len(hf_ids)} HF cache model(s).")
    print(f"Wrote {len(models)} model(s) to {output_path}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
