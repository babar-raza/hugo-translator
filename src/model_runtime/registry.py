"""
Model Registry for translation model catalog and selection.

Manages available translation models with metadata.
"""
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

from .hardware import HardwareInfo


@dataclass
class ModelInfo:
    """Metadata about a translation model."""

    model_id: str
    name: str
    backend: Literal["huggingface", "ctranslate2", "opus", "local_llm"]
    supported_pairs: List[Tuple[str, str]] | Literal["all"]  # (src, tgt) lang pairs
    model_size_mb: int
    min_ram_gb: float
    optimal_device: str
    parameters: Optional[int] = None  # Model param count
    license: str = "unknown"
    local_path: Optional[Path] = None
    hf_model_id: Optional[str] = None  # HuggingFace model ID
    description: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        # Convert supported_pairs tuples to lists for YAML serialization
        supported_pairs = self.supported_pairs
        if isinstance(supported_pairs, list):
            supported_pairs = [list(pair) if isinstance(pair, tuple) else pair
                             for pair in supported_pairs]

        result = {
            "model_id": self.model_id,
            "name": self.name,
            "backend": self.backend,
            "supported_pairs": supported_pairs,
            "model_size_mb": self.model_size_mb,
            "min_ram_gb": self.min_ram_gb,
            "optimal_device": self.optimal_device,
            "parameters": self.parameters,
            "license": self.license,
            "local_path": str(self.local_path) if self.local_path else None,
            "hf_model_id": self.hf_model_id,
            "description": self.description,
        }
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModelInfo":
        """Create from dictionary."""
        # Handle local_path
        local_path = data.get("local_path")
        if local_path:
            local_path = Path(local_path)

        # Handle supported_pairs
        supported_pairs = data.get("supported_pairs", "all")
        if isinstance(supported_pairs, list) and supported_pairs:
            # Convert list of lists to list of tuples
            if isinstance(supported_pairs[0], list):
                supported_pairs = [tuple(pair) for pair in supported_pairs]

        return cls(
            model_id=data["model_id"],
            name=data["name"],
            backend=data["backend"],
            supported_pairs=supported_pairs,
            model_size_mb=data["model_size_mb"],
            min_ram_gb=data["min_ram_gb"],
            optimal_device=data["optimal_device"],
            parameters=data.get("parameters"),
            license=data.get("license", "unknown"),
            local_path=local_path,
            hf_model_id=data.get("hf_model_id"),
            description=data.get("description"),
        )


class ModelRegistry:
    """
    Central registry of available translation models.

    Loads model catalog from YAML and provides selection logic.
    """

    def __init__(self, registry_path: Path | str):
        """
        Initialize model registry.

        Args:
            registry_path: Path to YAML registry file
        """
        self.registry_path = Path(registry_path)
        self.models: Dict[str, ModelInfo] = {}
        self._load_registry()

    def _load_registry(self) -> None:
        """Load model registry from YAML file."""
        if not self.registry_path.exists():
            raise FileNotFoundError(
                f"Registry file not found: {self.registry_path}"
            )

        with open(self.registry_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not data or "models" not in data:
            raise ValueError("Invalid registry format: missing 'models' key")

        for model_data in data["models"]:
            model = ModelInfo.from_dict(model_data)
            self.models[model.model_id] = model

    def list_models(
        self, lang_pair: Optional[Tuple[str, str]] = None
    ) -> List[ModelInfo]:
        """
        List available models, optionally filtered by language pair.

        Args:
            lang_pair: Optional (src, tgt) language pair to filter by

        Returns:
            List of ModelInfo objects
        """
        models = list(self.models.values())

        if lang_pair:
            filtered = []
            for model in models:
                if self._supports_lang_pair(model, lang_pair):
                    filtered.append(model)
            return filtered

        return models

    def _supports_lang_pair(
        self, model: ModelInfo, lang_pair: Tuple[str, str]
    ) -> bool:
        """
        Check if model supports language pair.

        Args:
            model: ModelInfo to check
            lang_pair: (src, tgt) language pair

        Returns:
            True if model supports the pair
        """
        if model.supported_pairs == "all":
            return True

        return lang_pair in model.supported_pairs

    def get_model(self, model_id: str) -> ModelInfo:
        """
        Get specific model info.

        Args:
            model_id: Model identifier

        Returns:
            ModelInfo object

        Raises:
            KeyError: If model not found
        """
        if model_id not in self.models:
            raise KeyError(f"Model not found: {model_id}")

        return self.models[model_id]

    def recommend_model(
        self,
        src_lang: str,
        tgt_lang: str,
        hardware: HardwareInfo,
        prefer_quality: bool = False,
    ) -> ModelInfo:
        """
        Recommend best model for given hardware and language pair.

        Args:
            src_lang: Source language code
            tgt_lang: Target language code
            hardware: HardwareInfo with detected capabilities
            prefer_quality: Prefer quality over speed

        Returns:
            Recommended ModelInfo

        Raises:
            ValueError: If no suitable model found
        """
        lang_pair = (src_lang, tgt_lang)

        # Get models that support the language pair
        candidates = [
            m for m in self.models.values()
            if self._supports_lang_pair(m, lang_pair)
        ]

        if not candidates:
            raise ValueError(
                f"No models found for language pair: {src_lang}->{tgt_lang}"
            )

        # Filter by hardware constraints
        suitable = []
        for model in candidates:
            # Check RAM requirements
            if model.min_ram_gb <= hardware.total_ram_gb:
                # Check device compatibility
                if model.optimal_device == hardware.recommended_device:
                    suitable.append(model)
                elif hardware.recommended_device == "cpu":
                    # CPU can run anything
                    suitable.append(model)

        if not suitable:
            # No exact match, return smallest model
            return min(candidates, key=lambda m: m.model_size_mb)

        # Score models
        scored = []
        for model in suitable:
            score = self._score_model(model, hardware, prefer_quality)
            scored.append((score, model))

        # Return highest scored model
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]

    def _score_model(
        self, model: ModelInfo, hardware: HardwareInfo, prefer_quality: bool
    ) -> float:
        """
        Score model based on hardware and preferences.

        Args:
            model: ModelInfo to score
            hardware: Hardware capabilities
            prefer_quality: Whether to prefer quality

        Returns:
            Score (higher is better)
        """
        score = 0.0

        # Device match bonus
        if model.optimal_device == hardware.recommended_device:
            score += 10.0

        # Parameter count (proxy for quality)
        if model.parameters:
            if prefer_quality:
                # Prefer larger models for quality
                score += (model.parameters / 1_000_000_000) * 5.0
            else:
                # Prefer smaller models for speed
                score -= (model.parameters / 1_000_000_000) * 2.0

        # Backend preference
        if model.backend == "ctranslate2":
            score += 5.0  # CT2 is optimized
        elif model.backend == "huggingface":
            score += 3.0  # HF is well-supported

        # Size penalty (smaller is better for loading)
        score -= (model.model_size_mb / 1000) * 1.0

        return score

    def register_model(self, model_info: ModelInfo) -> None:
        """
        Add new model to registry dynamically.

        Args:
            model_info: ModelInfo to register
        """
        self.models[model_info.model_id] = model_info

    def unregister_model(self, model_id: str) -> None:
        """
        Remove model from registry.

        Args:
            model_id: Model identifier to remove

        Raises:
            KeyError: If model not found
        """
        if model_id not in self.models:
            raise KeyError(f"Model not found: {model_id}")

        del self.models[model_id]

    def save_registry(self, output_path: Optional[Path] = None) -> None:
        """
        Save registry to YAML file.

        Args:
            output_path: Optional path to save to (defaults to original path)
        """
        path = output_path or self.registry_path

        # Convert models to dict format
        models_data = []
        for model in self.models.values():
            model_dict = model.to_dict()
            models_data.append(model_dict)

        data = {"models": models_data}

        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    def __len__(self) -> int:
        """Return number of registered models."""
        return len(self.models)

    def __contains__(self, model_id: str) -> bool:
        """Check if model is registered."""
        return model_id in self.models
