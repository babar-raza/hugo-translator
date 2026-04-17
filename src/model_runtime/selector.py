"""
Language-Aware Model Selector for Translation.

Automatically selects the best translation model for a given language pair,
considering:
- Language-specific Opus models (preferred for quality)
- Multilingual models (fallback for unsupported language pairs)
- Hardware constraints (RAM, VRAM, device compatibility)
- Quality vs speed trade-offs

Priority order:
1. Opus-specific model (e.g., opus_en_fr for EN→FR)
2. Multilingual model with supported_pairs="all" (e.g., m2m100, nllb)
3. Global fallback_model from configuration
4. ValueError if no suitable model found

PROD-004: Language-Aware Model Selection (Agent-E)
"""
import logging
from dataclasses import dataclass

from .hardware import HardwareInfo
from .registry import ModelInfo, ModelRegistry

logger = logging.getLogger(__name__)


@dataclass
class ModelSelection:
    """Result of model selection with rationale."""

    model_info: ModelInfo
    selection_strategy: str  # "opus-specific", "multilingual-fallback", "global-fallback"
    rationale: str  # Human-readable explanation
    hardware_fit: bool  # Whether model fits hardware constraints


class LanguageAwareModelSelector:
    """
    Intelligent model selector for language pairs.

    Automatically selects the best model for a given source-target language pair,
    preferring language-specific Opus models when available, falling back to
    multilingual models otherwise.

    Selection Strategy:
    1. Try language-specific Opus model (e.g., opus_en_fr for EN→FR)
    2. Try multilingual models (m2m100, nllb) with supported_pairs="all"
    3. Use global fallback_model from config (if specified)
    4. Raise ValueError if no suitable model found

    Always respects hardware constraints (RAM, VRAM, device compatibility).

    Example:
        >>> from model_runtime.registry import ModelRegistry
        >>> from model_runtime.hardware import HardwareDetector
        >>>
        >>> registry = ModelRegistry("config/model_registry.yaml")
        >>> hardware = HardwareDetector().detect()
        >>> selector = LanguageAwareModelSelector(registry, hardware)
        >>>
        >>> # Auto-select for French (will use opus_en_fr if available)
        >>> selection = selector.select_for_language_pair("en", "fr")
        >>> print(selection.model_info.model_id)  # "opus_en_fr"
        >>>
        >>> # Auto-select for Croatian (will use multilingual fallback)
        >>> selection = selector.select_for_language_pair("en", "hr")
        >>> print(selection.model_info.model_id)  # "m2m100_418m"
    """

    def __init__(
        self,
        registry: ModelRegistry,
        hardware_info: HardwareInfo,
        fallback_model: str | None = None,
    ):
        """
        Initialize language-aware model selector.

        Args:
            registry: ModelRegistry instance with available models
            hardware_info: HardwareInfo with detected capabilities
            fallback_model: Optional global fallback model ID (used if no Opus/multilingual found)
        """
        self.registry = registry
        self.hardware_info = hardware_info
        self.fallback_model = fallback_model

        logger.info(
            f"LanguageAwareModelSelector initialized "
            f"(device={hardware_info.recommended_device}, "
            f"ram={hardware_info.total_ram_gb:.1f}GB, "
            f"fallback={fallback_model})"
        )

    def select_for_language_pair(
        self,
        src_lang: str,
        tgt_lang: str,
        prefer_quality: bool = False,
    ) -> ModelSelection:
        """
        Select best model for the given language pair.

        Selection priority:
        1. Opus-specific model (highest quality for supported pairs)
        2. Multilingual model (supports all language pairs)
        3. Global fallback model (last resort from config)
        4. Raise ValueError if nothing found

        Args:
            src_lang: Source language code (e.g., 'en')
            tgt_lang: Target language code (e.g., 'fr', 'hr', 'ko')
            prefer_quality: If True, prefer larger/better models when multiple options available

        Returns:
            ModelSelection with selected model and rationale

        Raises:
            ValueError: If no suitable model found for this language pair + hardware combination
        """
        logger.info(f"Selecting model for {src_lang}→{tgt_lang} (prefer_quality={prefer_quality})")

        # Strategy 1: Try Opus-specific model
        opus_selection = self._try_opus_model(src_lang, tgt_lang)
        if opus_selection:
            logger.info(
                f"Selected Opus model: {opus_selection.model_info.model_id} "
                f"({opus_selection.rationale})"
            )
            return opus_selection

        # Strategy 2: Try multilingual fallback
        multilingual_selection = self._try_multilingual_fallback(prefer_quality)
        if multilingual_selection:
            logger.warning(
                f"No Opus model for {src_lang}→{tgt_lang}, using multilingual fallback: "
                f"{multilingual_selection.model_info.model_id} ({multilingual_selection.rationale})"
            )
            return multilingual_selection

        # Strategy 3: Use global fallback model
        if self.fallback_model:
            fallback_selection = self._try_global_fallback()
            if fallback_selection:
                logger.warning(
                    f"Using global fallback model: {fallback_selection.model_info.model_id} "
                    f"({fallback_selection.rationale})"
                )
                return fallback_selection

        # Strategy 4: No suitable model found
        error_msg = (
            f"No suitable model found for language pair: {src_lang}→{tgt_lang}\n"
            f"Attempted strategies:\n"
            f"  1. Opus-specific model: Not found in registry\n"
            f"  2. Multilingual model: Not found or doesn't fit hardware constraints\n"
            f"  3. Global fallback: {'Not configured' if not self.fallback_model else 'Not found in registry'}\n\n"
            f"Suggestions:\n"
            f"  - Install multilingual model (m2m100_418m or nllb_200_600m)\n"
            f"  - Increase hardware resources (current RAM: {self.hardware_info.total_ram_gb:.1f}GB)\n"
            f"  - Manually specify model with --model flag"
        )
        logger.error(error_msg)
        raise ValueError(error_msg)

    def _try_opus_model(self, src_lang: str, tgt_lang: str) -> ModelSelection | None:
        """
        Try to find language-specific Opus model for this language pair.

        Searches registry for models with supported_pairs containing [src_lang, tgt_lang].
        Filters by hardware constraints.

        Args:
            src_lang: Source language code
            tgt_lang: Target language code

        Returns:
            ModelSelection if Opus model found and fits hardware, None otherwise
        """
        lang_pair = (src_lang, tgt_lang)

        # Search for Opus models supporting this language pair
        opus_candidates = []
        for model in self.registry.models.values():
            # Check if model supports this language pair
            if self.registry._supports_lang_pair(model, lang_pair):
                # Prefer Opus models (marked with "opus" in model_id)
                if "opus" in model.model_id.lower():
                    opus_candidates.append(model)

        if not opus_candidates:
            logger.debug(f"No Opus models found for {src_lang}→{tgt_lang}")
            return None

        # Filter by hardware constraints
        suitable = [m for m in opus_candidates if self._fits_hardware_constraints(m)]

        if not suitable:
            logger.debug(
                f"Found {len(opus_candidates)} Opus models but none fit hardware constraints "
                f"(RAM={self.hardware_info.total_ram_gb:.1f}GB, device={self.hardware_info.recommended_device})"
            )
            return None

        # Select best Opus model (prefer smaller for faster loading)
        best_opus = min(suitable, key=lambda m: m.model_size_mb)

        rationale = (
            f"Language-specific Opus model for {src_lang}→{tgt_lang}. "
            f"Size: {best_opus.model_size_mb}MB, "
            f"Device: {best_opus.optimal_device}"
        )

        return ModelSelection(
            model_info=best_opus,
            selection_strategy="opus-specific",
            rationale=rationale,
            hardware_fit=True,
        )

    def _try_multilingual_fallback(self, prefer_quality: bool = False) -> ModelSelection | None:
        """
        Try to find suitable multilingual model as fallback.

        Searches for models with supported_pairs="all" (m2m100, nllb, etc.).
        Filters by hardware constraints.

        Args:
            prefer_quality: If True, prefer larger/better models (e.g., nllb_200_1.3b over m2m100_418m)

        Returns:
            ModelSelection if multilingual model found and fits hardware, None otherwise
        """
        # Search for multilingual models (supported_pairs="all")
        multilingual_candidates = []
        for model in self.registry.models.values():
            if model.supported_pairs == "all":
                multilingual_candidates.append(model)

        if not multilingual_candidates:
            logger.debug("No multilingual models found in registry")
            return None

        # Filter by hardware constraints
        suitable = [m for m in multilingual_candidates if self._fits_hardware_constraints(m)]

        if not suitable:
            logger.debug(
                f"Found {len(multilingual_candidates)} multilingual models but none fit hardware constraints"
            )
            return None

        # Select best multilingual model
        if prefer_quality:
            # Prefer larger models (higher parameter count = better quality)
            best_multilingual = max(suitable, key=lambda m: m.parameters or 0)
            quality_note = "quality-preferred"
        else:
            # Prefer smaller models (faster loading, lower memory)
            # But prioritize CTranslate2 backend if available
            ct2_models = [m for m in suitable if m.backend == "ctranslate2"]
            if ct2_models:
                best_multilingual = min(ct2_models, key=lambda m: m.model_size_mb)
                quality_note = "speed-optimized (CTranslate2)"
            else:
                best_multilingual = min(suitable, key=lambda m: m.model_size_mb)
                quality_note = "speed-preferred"

        rationale = (
            f"Multilingual fallback ({quality_note}). "
            f"Supports all language pairs. "
            f"Size: {best_multilingual.model_size_mb}MB, "
            f"Backend: {best_multilingual.backend}"
        )

        return ModelSelection(
            model_info=best_multilingual,
            selection_strategy="multilingual-fallback",
            rationale=rationale,
            hardware_fit=True,
        )

    def _try_global_fallback(self) -> ModelSelection | None:
        """
        Try to use global fallback model from configuration.

        Returns:
            ModelSelection if fallback model exists in registry and fits hardware, None otherwise
        """
        if not self.fallback_model:
            return None

        try:
            model = self.registry.get_model(self.fallback_model)
        except KeyError:
            logger.warning(
                f"Global fallback model '{self.fallback_model}' not found in registry"
            )
            return None

        if not self._fits_hardware_constraints(model):
            logger.warning(
                f"Global fallback model '{self.fallback_model}' doesn't fit hardware constraints"
            )
            return None

        rationale = (
            f"Global fallback model from configuration. "
            f"Size: {model.model_size_mb}MB, "
            f"Backend: {model.backend}"
        )

        return ModelSelection(
            model_info=model,
            selection_strategy="global-fallback",
            rationale=rationale,
            hardware_fit=True,
        )

    def _fits_hardware_constraints(self, model: ModelInfo) -> bool:
        """
        Check if model fits current hardware constraints.

        Checks:
        - RAM requirement vs available RAM
        - Device compatibility (cpu, cuda, mps)
        - VRAM requirement (if applicable)

        Args:
            model: ModelInfo to check

        Returns:
            True if model fits hardware constraints, False otherwise
        """
        # Check RAM requirement
        if model.min_ram_gb > self.hardware_info.total_ram_gb:
            logger.debug(
                f"Model {model.model_id} requires {model.min_ram_gb}GB RAM, "
                f"but only {self.hardware_info.total_ram_gb:.1f}GB available"
            )
            return False

        # Check device compatibility
        recommended_device = self.hardware_info.recommended_device

        # CPU can run anything
        if recommended_device == "cpu":
            return True

        # GPU models can run on GPU or CPU
        if recommended_device in ["cuda", "mps"]:
            # GPU models preferred, but CPU models also acceptable
            return True

        # Model requires GPU but we only have CPU
        if model.optimal_device in ["cuda", "mps"] and recommended_device == "cpu":
            # Still acceptable - will just run slower on CPU
            return True

        return True

    def get_available_models_for_language_pair(
        self, src_lang: str, tgt_lang: str
    ) -> list[tuple[str, str]]:
        """
        Get list of all available models for a language pair.

        Useful for debugging and reporting what models are available.

        Args:
            src_lang: Source language code
            tgt_lang: Target language code

        Returns:
            List of (model_id, selection_strategy) tuples
        """
        available = []

        # Check Opus models
        opus_selection = self._try_opus_model(src_lang, tgt_lang)
        if opus_selection:
            available.append((opus_selection.model_info.model_id, "opus-specific"))

        # Check multilingual models
        multilingual_selection = self._try_multilingual_fallback()
        if multilingual_selection:
            available.append(
                (multilingual_selection.model_info.model_id, "multilingual-fallback")
            )

        # Check global fallback
        fallback_selection = self._try_global_fallback()
        if fallback_selection:
            available.append((fallback_selection.model_info.model_id, "global-fallback"))

        return available
