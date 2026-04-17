"""
Translation Backend Abstractions - Enable MT ↔ LLM backend switching.

Provides abstract interface for translation backends with concrete implementations:
- MTBackend: Machine Translation (M2M100, NLLB, etc.)
- LLMBackend: Large Language Model APIs (Claude, GPT-4, etc.)

This abstraction allows per-site or per-job backend selection while maintaining
unified TM caching and validation workflows.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class TranslationBackend(ABC):
    """
    Abstract base class for translation backends.

    All translation backends must implement the translate() method which
    takes source text and returns translated text.
    """

    def __init__(self, model_id: str, **kwargs):
        """
        Initialize translation backend.

        Args:
            model_id: Identifier for the model (e.g., "m2m100_418m", "claude-sonnet-4")
            **kwargs: Backend-specific configuration
        """
        self.model_id = model_id
        self.config = kwargs

    @abstractmethod
    def translate(
        self,
        text: str,
        src_lang: str,
        tgt_lang: str,
        **kwargs
    ) -> str:
        """
        Translate text from source language to target language.

        Args:
            text: Source text to translate
            src_lang: Source language code (ISO 639-1 or locale)
            tgt_lang: Target language code (ISO 639-1 or locale)
            **kwargs: Backend-specific options

        Returns:
            Translated text

        Raises:
            TranslationError: If translation fails
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if backend is available and ready to translate.

        Returns:
            True if backend can be used, False otherwise
        """
        pass

    def get_model_info(self) -> dict[str, Any]:
        """
        Get information about the model/backend.

        Returns:
            Dictionary with model metadata
        """
        return {
            "model_id": self.model_id,
            "backend_type": self.__class__.__name__,
            "config": self.config
        }


class MTBackend(TranslationBackend):
    """
    Machine Translation backend using local transformer models.

    Supports models like M2M100, NLLB-200, etc. via HuggingFace transformers.
    Uses ModelLoader for model management and device optimization.
    """

    def __init__(
        self,
        model_id: str = "m2m100_418m",
        device: str = "auto",
        **kwargs
    ):
        """
        Initialize MT backend.

        Args:
            model_id: Model identifier (e.g., "m2m100_418m", "nllb_200_1.3B")
            device: Device to use ("cpu", "cuda", "cuda:0", "auto")
            **kwargs: Additional configuration
        """
        super().__init__(model_id, device=device, **kwargs)
        self.device = device
        self._model = None
        self._model_loader = None

    def translate(
        self,
        text: str,
        src_lang: str,
        tgt_lang: str,
        **kwargs
    ) -> str:
        """
        Translate using MT model.

        Note: This is a DEPRECATED stub implementation that returns English unchanged!
        DO NOT USE THIS CLASS. Use src.translation_engine.backends.mt_backend.MTBackend instead.

        Args:
            text: Source text
            src_lang: Source language
            tgt_lang: Target language
            **kwargs: Additional options (batch_size, etc.)

        Returns:
            Translated text

        Raises:
            NotImplementedError: This is a stub - use the real MTBackend
        """
        raise NotImplementedError(
            "This MTBackend is a deprecated stub that returns English unchanged. "
            "Use src.translation_engine.backends.mt_backend.MTBackend instead. "
            "This stub was accidentally returning source text without translation, "
            "causing English to appear in translated output."
        )

    def is_available(self) -> bool:
        """Check if MT backend is available."""
        try:
            import torch
            if self.device.startswith("cuda"):
                return torch.cuda.is_available()
            return True
        except ImportError:
            return False


class LLMBackend(TranslationBackend):
    """
    Large Language Model backend using API services.

    Supports:
    - Anthropic Claude (claude-sonnet-4, claude-opus-4, etc.)
    - OpenAI GPT (gpt-4, gpt-4-turbo, etc.)
    - Other LLM APIs
    """

    def __init__(
        self,
        model_id: str = "claude-sonnet-4",
        api_key: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        **kwargs
    ):
        """
        Initialize LLM backend.

        Args:
            model_id: Model identifier (e.g., "claude-sonnet-4", "gpt-4")
            api_key: API key for authentication (or set via environment)
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature (0.0 = deterministic)
            **kwargs: Additional API-specific configuration
        """
        super().__init__(
            model_id,
            api_key=api_key,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs
        )
        self.api_key = api_key
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._client = None

    def translate(
        self,
        text: str,
        src_lang: str,
        tgt_lang: str,
        **kwargs
    ) -> str:
        """
        Translate using LLM API.

        Note: This is a stub implementation. In practice, this should:
        1. Initialize API client if not initialized
        2. Construct translation prompt
        3. Call API
        4. Extract and return translation

        Args:
            text: Source text
            src_lang: Source language
            tgt_lang: Target language
            **kwargs: Additional options (prompt template, etc.)

        Returns:
            Translated text
        """
        # Stub implementation - actual API calls would go here
        logger.warning(
            "LLMBackend.translate() is a stub. "
            "Full implementation requires API integration."
        )
        return text  # Pass-through for now

    def is_available(self) -> bool:
        """Check if LLM backend is available."""
        if not self.api_key:
            logger.warning("LLMBackend: No API key provided")
            return False

        # Check if API client library is available
        if "claude" in self.model_id.lower():
            try:
                import anthropic
                return True
            except ImportError:
                logger.warning("LLMBackend: anthropic library not installed")
                return False
        elif "gpt" in self.model_id.lower():
            try:
                import openai
                return True
            except ImportError:
                logger.warning("LLMBackend: openai library not installed")
                return False

        return False


class MockBackend(TranslationBackend):
    """
    Mock backend for testing purposes.

    Returns predictable translations useful for unit tests.
    """

    def __init__(self, model_id: str = "mock", **kwargs):
        """Initialize mock backend."""
        super().__init__(model_id, **kwargs)

    def translate(
        self,
        text: str,
        src_lang: str,
        tgt_lang: str,
        **kwargs
    ) -> str:
        """
        Return mock translation.

        Returns source text with language tag for verification.
        """
        return f"[{tgt_lang}] {text}"

    def is_available(self) -> bool:
        """Mock backend is always available."""
        return True


# Backend registry for discovery and creation
_BACKEND_REGISTRY: dict[str, type] = {
    "mt": MTBackend,
    "llm": LLMBackend,
    "mock": MockBackend,
}


def register_backend(name: str, backend_class: type):
    """
    Register a custom translation backend.

    Args:
        name: Backend identifier
        backend_class: Backend class (must inherit from TranslationBackend)
    """
    if not issubclass(backend_class, TranslationBackend):
        raise TypeError(f"{backend_class} must inherit from TranslationBackend")
    _BACKEND_REGISTRY[name] = backend_class
    logger.info(f"Registered translation backend: {name}")


def get_backend(name: str) -> type | None:
    """
    Get backend class by name.

    Args:
        name: Backend identifier

    Returns:
        Backend class or None if not found
    """
    return _BACKEND_REGISTRY.get(name)


def list_backends() -> list:
    """
    List all registered backends.

    Returns:
        List of backend names
    """
    return list(_BACKEND_REGISTRY.keys())
