"""
Unit tests for ModelRegistry multi-registry merge behavior.
"""

from pathlib import Path

import yaml

from src.model_runtime.registry import ModelRegistry


def _write_registry(path: Path, models):
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump({"models": models}, f, default_flow_style=False, sort_keys=False)


def test_model_registry_multi_registry_override(tmp_path):
    first = tmp_path / "registry_one.yaml"
    second = tmp_path / "registry_two.yaml"

    _write_registry(
        first,
        [
            {
                "model_id": "dup_model",
                "name": "Old Name",
                "backend": "huggingface",
                "supported_pairs": "all",
                "model_size_mb": 100,
                "min_ram_gb": 1,
                "optimal_device": "cuda",
            }
        ],
    )
    _write_registry(
        second,
        [
            {
                "model_id": "dup_model",
                "name": "New Name",
                "backend": "huggingface",
                "supported_pairs": "all",
                "model_size_mb": 120,
                "min_ram_gb": 1,
                "optimal_device": "cuda",
            },
            {
                "model_id": "extra_model",
                "name": "Extra Model",
                "backend": "huggingface",
                "supported_pairs": "all",
                "model_size_mb": 200,
                "min_ram_gb": 2,
                "optimal_device": "cuda",
            },
        ],
    )

    registry = ModelRegistry(f"{first},{second}")

    assert registry.get_model("dup_model").name == "New Name"
    assert "extra_model" in registry.models
