"""
Abstract interface for translation backends.

Defines the contract that all translation backends must implement,
enabling pluggable translation engines (MT models, LLM APIs, etc.).
"""

from abc import ABC, abstractmethod
from typing import Any


class ITranslationBackend(ABC):
    """
    Abstract base class for translation backends.

    All translation backends (MT, LLM, etc.) must implement this interface
    to be compatible with the TranslationEngine.

    Methods:
        translate: Translate a single text segment
        translate_batch: Translate multiple segments in one call (optional optimization)
        get_model_info: Return backend metadata for telemetry
    """

    @abstractmethod
    def translate(
        self,
        text: str,
        src_lang: str,
        tgt_lang: str,
        **kwargs: Any
    ) -> str:
        """
        Translate a single text segment.

        Args:
            text: Source text to translate
            src_lang: Source language code (ISO 639-1, e.g., 'en')
            tgt_lang: Target language code (ISO 639-1, e.g., 'es')
            **kwargs: Backend-specific options (max_length, temperature, etc.)

        Returns:
            Translated text string

        Raises:
            TranslationError: If translation fails
            ValueError: If language codes are invalid
        """
        pass

    def translate_batch(
        self,
        texts: list[str],
        src_lang: str,
        tgt_lang: str,
        **kwargs: Any
    ) -> list[str]:
        """
        Translate multiple text segments in one call.

        Default implementation calls translate() for each text sequentially.
        Backends can override for optimized batch processing.

        Args:
            texts: List of source texts to translate
            src_lang: Source language code
            tgt_lang: Target language code
            **kwargs: Backend-specific options

        Returns:
            List of translated text strings (same order as input)

        Raises:
            TranslationError: If any translation fails
        """
        return [self.translate(text, src_lang, tgt_lang, **kwargs) for text in texts]

    @abstractmethod
    def get_model_info(self) -> dict[str, Any]:
        """
        Return backend metadata for telemetry and logging.

        Returns:
            Dictionary with backend information:
                - backend_type: "mt" or "llm"
                - model_id: Model identifier (e.g., "m2m100_418m", "claude-sonnet-4")
                - device: Execution device ("cuda", "cpu", "api")
                - version: Backend version string (optional)

        Example:
            {
                "backend_type": "mt",
                "model_id": "m2m100_418m",
                "device": "cuda",
                "version": "1.0.0"
            }
        """
        pass

    def supports_language_pair(self, src_lang: str, tgt_lang: str) -> bool:
        """
        Check if backend supports a language pair.

        Default implementation returns True (assumes all pairs supported).
        Backends can override to provide language-specific validation.

        Args:
            src_lang: Source language code
            tgt_lang: Target language code

        Returns:
            True if language pair is supported, False otherwise
        """
        return True

    def warmup(self) -> None:
        """
        Pre-load model/resources for faster first translation.

        Default implementation does nothing.
        Backends can override to implement model preloading.
        """
        pass

    def shutdown(self) -> None:
        """
        Clean up resources (GPU memory, API connections, etc.).

        Default implementation does nothing.
        Backends can override to implement cleanup logic.
        """
        pass
