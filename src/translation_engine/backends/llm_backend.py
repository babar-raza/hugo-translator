"""
Large Language Model backend using Anthropic Claude API.

Provides LLM-based translation via Claude models (Sonnet, Opus, Haiku).
"""

import logging
import os
from typing import List, Dict, Any, Optional

from .interface import ITranslationBackend

logger = logging.getLogger(__name__)

# Optional anthropic import (graceful degradation if not installed)
try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    anthropic = None  # type: ignore
    logger.warning("anthropic SDK not installed. LLMBackend will not be available.")


class LLMBackend(ITranslationBackend):
    """
    LLM translation backend using Anthropic Claude API.

    Translates text using Claude models via API calls. Useful for:
    - High-quality literary translation
    - Context-aware translation
    - Languages not supported by MT models

    Args:
        model_id: Claude model identifier (e.g., "claude-sonnet-4", "claude-opus-4")
        api_key: Anthropic API key (or None to read from ANTHROPIC_API_KEY env var)
        max_tokens: Maximum tokens per translation (default: 4096)
        temperature: Sampling temperature 0-1 (default: 0.0 for deterministic)

    Example:
        backend = LLMBackend(
            model_id="claude-sonnet-4",
            api_key=os.getenv("ANTHROPIC_API_KEY")
        )
        result = backend.translate("Hello", src_lang="en", tgt_lang="es")

    Note:
        Requires ANTHROPIC_API_KEY environment variable or api_key parameter.
        Requires `anthropic` package: pip install anthropic
    """

    # Language code to full name mapping (for prompts)
    LANGUAGE_NAMES = {
        "en": "English",
        "es": "Spanish",
        "fr": "French",
        "de": "German",
        "it": "Italian",
        "pt": "Portuguese",
        "ru": "Russian",
        "zh": "Chinese",
        "ja": "Japanese",
        "ko": "Korean",
        "ar": "Arabic",
        "hi": "Hindi",
        "tr": "Turkish",
        "nl": "Dutch",
        "pl": "Polish",
        "sv": "Swedish",
        "fi": "Finnish",
        "da": "Danish",
        "no": "Norwegian",
        "cs": "Czech",
        "ro": "Romanian",
        "el": "Greek",
        "th": "Thai",
        "vi": "Vietnamese",
        "id": "Indonesian",
        "uk": "Ukrainian",
    }

    def __init__(
        self,
        model_id: str = "claude-sonnet-4",
        api_key: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.0
    ):
        """Initialize LLM backend with API configuration."""
        if not ANTHROPIC_AVAILABLE:
            raise RuntimeError(
                "anthropic SDK not installed. Install with: pip install anthropic"
            )

        self.model_id = model_id
        self.max_tokens = max_tokens
        self.temperature = temperature

        # Get API key from parameter or environment
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Anthropic API key required. Set ANTHROPIC_API_KEY environment variable "
                "or pass api_key parameter."
            )

        # Initialize Anthropic client
        self.client = anthropic.Anthropic(api_key=self.api_key)

        logger.info(
            f"LLMBackend initialized: model={model_id}, "
            f"max_tokens={max_tokens}, temperature={temperature}"
        )

    def translate(
        self,
        text: str,
        src_lang: str,
        tgt_lang: str,
        **kwargs: Any
    ) -> str:
        """
        Translate a single text segment using Claude API.

        Args:
            text: Source text to translate
            src_lang: Source language code (ISO 639-1)
            tgt_lang: Target language code (ISO 639-1)
            **kwargs: Optional LLM-specific parameters:
                - max_tokens: Override max tokens (default: 4096)
                - temperature: Override temperature (default: 0.0)
                - system_prompt: Custom system prompt (optional)

        Returns:
            Translated text string

        Raises:
            anthropic.APIError: If API call fails
            ValueError: If language codes are unsupported
        """
        # Get language names for prompt
        src_lang_name = self.LANGUAGE_NAMES.get(src_lang, src_lang.upper())
        tgt_lang_name = self.LANGUAGE_NAMES.get(tgt_lang, tgt_lang.upper())

        # Extract optional parameters
        max_tokens = kwargs.get("max_tokens", self.max_tokens)
        temperature = kwargs.get("temperature", self.temperature)
        custom_system = kwargs.get("system_prompt", None)

        # Build system prompt
        if custom_system:
            system_prompt = custom_system
        else:
            system_prompt = (
                f"You are an expert translator. Translate the provided text from "
                f"{src_lang_name} to {tgt_lang_name}. "
                f"Preserve formatting, tone, and style. Output only the translation."
            )

        # Build user prompt
        user_prompt = text

        try:
            # Call Claude API
            logger.debug(f"LLM translate: {len(text)} chars, {src_lang} -> {tgt_lang}")
            response = self.client.messages.create(
                model=self.model_id,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_prompt}
                ]
            )

            # Extract translation from response
            translation = response.content[0].text

            logger.debug(
                f"LLM translate complete: {len(translation)} chars, "
                f"usage={response.usage.input_tokens}in/{response.usage.output_tokens}out"
            )

            return translation

        except anthropic.APIError as e:
            logger.error(f"Claude API error: {e}")
            raise
        except Exception as e:
            logger.error(f"LLM translation failed: {e}")
            raise RuntimeError(f"LLM translation failed: {e}") from e

    def translate_batch(
        self,
        texts: List[str],
        src_lang: str,
        tgt_lang: str,
        **kwargs: Any
    ) -> List[str]:
        """
        Translate multiple texts (sequential API calls).

        Note: Claude API doesn't support true batch translation, so this
        makes sequential API calls. Consider using parallel=True with
        asyncio for better performance in production.

        Args:
            texts: List of source texts to translate
            src_lang: Source language code
            tgt_lang: Target language code
            **kwargs: Optional LLM-specific parameters

        Returns:
            List of translated texts (same order as input)
        """
        # Sequential translation (could be optimized with asyncio)
        translations = []
        for text in texts:
            translation = self.translate(text, src_lang, tgt_lang, **kwargs)
            translations.append(translation)

        return translations

    def get_model_info(self) -> Dict[str, Any]:
        """
        Return backend metadata for telemetry.

        Returns:
            Dictionary with:
                - backend_type: "llm"
                - model_id: Claude model identifier
                - device: "api"
                - max_tokens: Max tokens per call
                - temperature: Sampling temperature
        """
        return {
            "backend_type": "llm",
            "model_id": self.model_id,
            "device": "api",
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }

    def supports_language_pair(self, src_lang: str, tgt_lang: str) -> bool:
        """
        Check if backend supports a language pair.

        Claude supports all common languages, so this returns True
        for any pair in LANGUAGE_NAMES. Unknown languages are also
        supported (Claude can handle them).

        Args:
            src_lang: Source language code
            tgt_lang: Target language code

        Returns:
            True (Claude supports virtually all languages)
        """
        return True

    def warmup(self) -> None:
        """
        Pre-warm API connection (optional).

        Makes a minimal API call to verify credentials and warm up connection.
        """
        try:
            logger.info("Warming up LLMBackend: testing API connection")
            # Make minimal API call to test connection
            self.translate("test", src_lang="en", tgt_lang="es")
            logger.info("LLMBackend warmed up successfully")
        except Exception as e:
            logger.warning(f"LLMBackend warmup failed (non-critical): {e}")

    def shutdown(self) -> None:
        """
        Clean up API resources.

        No-op for API backends (no persistent state to clean up).
        """
        logger.info("LLMBackend shutdown (no-op)")
