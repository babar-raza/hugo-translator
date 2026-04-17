"""
Model Registry for translation model catalog and selection.

Manages available translation models with metadata.
"""
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

from .hardware import HardwareInfo

logger = logging.getLogger(__name__)


@dataclass
class ModelInfo:
    """Metadata about a translation model."""

    model_id: str
    name: str
    backend: Literal["huggingface", "ctranslate2", "opus", "llm", "local_llm"]
    supported_pairs: list[tuple[str, str]] | Literal["all"]  # (src, tgt) lang pairs
    model_size_mb: int
    min_ram_gb: float
    optimal_device: str
    parameters: int | None = None  # Model param count
    license: str = "unknown"
    local_path: Path | None = None
    hf_model_id: str | None = None  # HuggingFace model ID
    description: str | None = None
    max_new_tokens: int = 256  # TR-01: Reduced from 512 to 256 for memory efficiency

    # LLM-specific fields (only used when backend="llm" or "local_llm")
    provider: str | None = None          # "ollama" | "openai" | "anthropic" | "openai_compatible"
    model_name: str | None = None        # Provider model name (e.g., "qwen3:14b", "gpt-4o")
    base_url: str | None = None          # API endpoint URL
    api_key_env: str | None = None       # Env var name for API key (e.g., "OPENAI_API_KEY")
    temperature: float | None = None     # Sampling temperature (default: 0.1 for translation)
    max_tokens: int | None = None        # Max response tokens (default: 4096)
    timeout_seconds: int | None = None   # Request timeout (default: 120)
    system_prompt_template: str | None = None  # Custom system prompt

    def to_dict(self) -> dict[str, Any]:
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
            "max_new_tokens": self.max_new_tokens,
        }

        # Include LLM-specific fields only when set (keeps MT entries clean)
        for llm_field in (
            "provider", "model_name", "base_url", "api_key_env",
            "temperature", "max_tokens", "timeout_seconds",
            "system_prompt_template",
        ):
            value = getattr(self, llm_field, None)
            if value is not None:
                result[llm_field] = value

        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModelInfo":
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
            model_size_mb=data.get("model_size_mb", 0),  # Default 0 for auto-discovered models
            min_ram_gb=data.get("min_ram_gb", 4),  # Default 4GB minimum
            optimal_device=data.get("optimal_device", "cpu"),  # Default to CPU
            parameters=data.get("parameters"),
            license=data.get("license", "unknown"),
            local_path=local_path,
            hf_model_id=data.get("hf_model_id"),
            description=data.get("description"),
            max_new_tokens=data.get("max_new_tokens", 512),
            # LLM-specific fields
            provider=data.get("provider"),
            model_name=data.get("model_name"),
            base_url=data.get("base_url"),
            api_key_env=data.get("api_key_env"),
            temperature=data.get("temperature"),
            max_tokens=data.get("max_tokens"),
            timeout_seconds=data.get("timeout_seconds"),
            system_prompt_template=data.get("system_prompt_template"),
        )


class ModelRegistry:
    """
    Central registry of available translation models.

    Loads model catalog from YAML and provides selection logic.
    """

    def __init__(self, registry_path: Path | str = "config/model_registry.yaml"):
        """
        Initialize model registry.

        Args:
            registry_path: Path to YAML registry file or comma-separated list of paths
        """
        if isinstance(registry_path, (list, tuple)):
            registry_paths = [Path(p) for p in registry_path]
        elif isinstance(registry_path, str) and "," in registry_path:
            registry_paths = [Path(p.strip()) for p in registry_path.split(",") if p.strip()]
        else:
            registry_paths = [Path(registry_path)]

        if not registry_paths:
            raise ValueError("No registry paths provided")

        self.registry_paths = registry_paths
        self.registry_path = registry_paths[0]
        self.models: dict[str, ModelInfo] = {}
        self._load_registry()

    def _load_registry(self) -> None:
        """Load model registry from YAML file."""
        for registry_path in self.registry_paths:
            if not registry_path.exists():
                raise FileNotFoundError(
                    f"Registry file not found: {registry_path}"
                )

            with open(registry_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)

            if not data or "models" not in data:
                raise ValueError(
                    f"Invalid registry format in {registry_path}: missing 'models' key"
                )

            for model_data in data["models"]:
                model = ModelInfo.from_dict(model_data)
                # Later registries override earlier ones
                self.models[model.model_id] = model

    def list_models(
        self, lang_pair: tuple[str, str] | None = None
    ) -> list[ModelInfo]:
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
        self, model: ModelInfo, lang_pair: tuple[str, str]
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

        Implements a 2-tier fallback chain:
        1. Opus-specific models (fast, specialized for language pair)
        2. Multilingual models (m2m100, nllb - support all language pairs)
        3. ValueError if no models available

        Args:
            src_lang: Source language code
            tgt_lang: Target language code
            hardware: HardwareInfo with detected capabilities
            prefer_quality: Prefer quality over speed

        Returns:
            Recommended ModelInfo

        Raises:
            ValueError: If no suitable model found (including multilingual fallback)
        """
        lang_pair = (src_lang, tgt_lang)

        # Tier 1: Try Opus-specific models first (fast, specialized)
        # Exclude multilingual models (supported_pairs="all") from this tier
        candidates = [
            m for m in self.models.values()
            if self._supports_lang_pair(m, lang_pair) and m.supported_pairs != "all"
        ]

        if candidates:
            logger.debug(f"Found {len(candidates)} Opus models for {src_lang}→{tgt_lang}")
            return self._select_best(candidates, hardware, prefer_quality)

        # Tier 2: Fallback to multilingual models (covers all language pairs)
        multilingual = [
            m for m in self.models.values()
            if m.supported_pairs == "all"
        ]

        if multilingual:
            logger.info(
                f"No Opus model for {src_lang}→{tgt_lang}, using multilingual fallback "
                f"({len(multilingual)} models available)"
            )
            return self._select_best(multilingual, hardware, prefer_quality)

        # Tier 3: No models available at all
        logger.warning(
            f"No models available for {src_lang}→{tgt_lang}. "
            f"Registry contains {len(self.models)} models total."
        )
        raise ValueError(
            f"No models available for {src_lang}→{tgt_lang}. "
            "Registry contains no models supporting this pair or multilingual models."
        )

    def _select_best(
        self,
        candidates: list[ModelInfo],
        hardware: HardwareInfo,
        prefer_quality: bool,
    ) -> ModelInfo:
        """
        Select best model from candidates based on hardware and preferences.

        Device-aware selection (CT2 automation):
        - optimal_device is a preference, not an exclusion
        - User-chosen device can run any model as long as backend supports it
        - Models are filtered only by RAM requirements
        - Device match affects scoring (bonus points for optimal_device match)

        Args:
            candidates: List of candidate models to choose from
            hardware: Hardware capabilities
            prefer_quality: Whether to prefer quality over speed

        Returns:
            Best ModelInfo from candidates

        Raises:
            ValueError: If candidates list is empty
        """
        if not candidates:
            raise ValueError("Cannot select from empty candidate list")

        # Filter by hardware constraints (RAM only)
        # Device compatibility is handled in scoring, not filtering
        suitable = []
        for model in candidates:
            # Check RAM requirements
            if model.min_ram_gb <= hardware.total_ram_gb:
                suitable.append(model)

        if not suitable:
            # No models meet RAM requirements, return smallest model
            logger.debug(
                f"No models meet RAM requirements ({hardware.total_ram_gb}GB), "
                f"selecting smallest from {len(candidates)} candidates"
            )
            return min(candidates, key=lambda m: m.model_size_mb)

        # Score models (optimal_device affects score, not eligibility)
        scored = []
        for model in suitable:
            score = self._score_model(model, hardware, prefer_quality)
            scored.append((score, model))

        # Return highest scored model
        scored.sort(key=lambda x: x[0], reverse=True)
        best_model = scored[0][1]
        logger.debug(
            f"Selected {best_model.model_id} from {len(suitable)} suitable models "
            f"(score: {scored[0][0]:.2f}, optimal_device: {best_model.optimal_device})"
        )
        return best_model

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

    def save_registry(self, output_path: Path | None = None) -> None:
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
