"""
LLM Translation Backend for ModelLoader.

Provides LLM-based translation through the ModelBackend interface,
enabling plug-and-play switching between MT models and LLMs via
config/model_registry.yaml entries.

Supports all providers in llm_providers.py: Ollama, OpenAI,
Anthropic, and any OpenAI-compatible endpoint.
"""

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .contracts import LLMProviderConfig
from .llm_providers import BaseLLMProvider, create_provider
from .registry import ModelInfo

logger = logging.getLogger(__name__)

# ISO 639-1 → full language name for translation prompts
LANGUAGE_NAMES = {
    "af": "Afrikaans", "ar": "Arabic", "az": "Azerbaijani",
    "bg": "Bulgarian", "ca": "Catalan", "cs": "Czech",
    "da": "Danish", "de": "German", "el": "Greek",
    "en": "English", "es": "Spanish", "et": "Estonian",
    "fa": "Persian", "fi": "Finnish", "fr": "French",
    "ga": "Irish", "he": "Hebrew", "hi": "Hindi",
    "hr": "Croatian", "hu": "Hungarian", "id": "Indonesian",
    "it": "Italian", "ja": "Japanese", "ko": "Korean",
    "lt": "Lithuanian", "lv": "Latvian", "ms": "Malay",
    "nb": "Norwegian Bokmål", "nl": "Dutch", "no": "Norwegian",
    "pl": "Polish", "pt": "Portuguese", "ro": "Romanian",
    "ru": "Russian", "sk": "Slovak", "sl": "Slovenian",
    "sr": "Serbian", "sv": "Swedish", "th": "Thai",
    "tr": "Turkish", "uk": "Ukrainian", "vi": "Vietnamese",
    "zh": "Chinese",
    # BCP-47 regional variants used by Aspose sites
    "zh-CN": "Simplified Chinese",
    "zh-TW": "Traditional Chinese",
    "zh-HK": "Traditional Chinese",
    "pt-BR": "Brazilian Portuguese",
    "pt-PT": "European Portuguese",
    "sr-Latn": "Serbian (Latin)",
}

DEFAULT_SYSTEM_PROMPT = (
    "You are a professional translator. Translate the following text from "
    "{src_lang_name} to {tgt_lang_name}.\n\n"
    "Rules:\n"
    "- Output ONLY the translation, nothing else\n"
    "- Preserve all formatting: markdown, HTML tags, code blocks, links\n"
    "- Preserve all Hugo shortcodes ({{{{< ... >}}}}) and template syntax exactly\n"
    "- Do not add explanations, notes, or commentary\n"
    "- Keep technical terms, brand names, and API identifiers unchanged\n"
    "- NEVER transliterate or translate archive/compression format names: "
    "TAR, ZIP, RAR, GZ, BZ2, TGZ, XZ, 7Z, BZIP2 — keep them exactly as written\n"
    "- Maintain the same tone and register as the source"
)


class LLMModelBackend:
    """LLM-based translation backend conforming to the ModelBackend interface.

    Plugs into ModelLoader alongside HuggingFaceBackend and CTranslate2Backend.
    The engine calls backend.translate(texts, src, tgt) and gets translations
    back — identical contract regardless of whether MT or LLM is used.

    Args:
        model_info: ModelInfo with backend="llm" and LLM-specific fields.
        device: Ignored for LLM backends (always "api").
    """

    def __init__(self, model_info: ModelInfo, device: str) -> None:
        self.model_info = model_info
        self.device = "api"
        self.loaded = False

        self._provider: Optional[BaseLLMProvider] = None
        self._terminology_manager = None  # lazy-loaded on first translate() call

        # TEL-04 token tracking compatibility
        self.last_input_tokens: int = 0
        self.last_output_tokens: int = 0
        self.last_truncation_detected: bool = False
        self.truncation_count: int = 0

    @property
    def _term_manager(self):
        """Lazy-load TerminologyManager for placeholder-based term protection."""
        if self._terminology_manager is None:
            try:
                from src.translation_engine.terminology.terminology_manager import TerminologyManager
                _cfg = Path("config/terminology.yaml")
                if not _cfg.exists():
                    # Fallback: resolve relative to this source file
                    _cfg = Path(__file__).parent.parent.parent / "config" / "terminology.yaml"
                self._terminology_manager = TerminologyManager(str(_cfg))
                logger.debug("TerminologyManager loaded for LLM backend term protection")
            except Exception as e:
                logger.warning("TerminologyManager unavailable: %s — terms sent unprotected to LLM", e)
                self._terminology_manager = False  # sentinel: don't retry
        return self._terminology_manager if self._terminology_manager else None

    def load(self) -> None:
        """Initialize the LLM provider client."""
        if self.loaded:
            return

        config = LLMProviderConfig.from_model_info(self.model_info)
        self._provider = create_provider(config)
        self.loaded = True

        logger.info(
            "LLMModelBackend loaded: provider=%s model=%s",
            config.provider,
            config.model_name,
        )

    def translate(
        self,
        texts: List[str],
        src_lang: str,
        tgt_lang: str,
        max_new_tokens: Optional[int] = None,
        generation_params: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """Translate a batch of texts.

        Args:
            texts: Source texts.
            src_lang: Source language code (ISO 639-1).
            tgt_lang: Target language code (ISO 639-1).
            max_new_tokens: Ignored for LLM backends (uses max_tokens from config).
            generation_params: Ignored for LLM backends.

        Returns:
            List of translated texts (same order and length as input).
        """
        translations, _, _ = self.translate_with_token_counts(
            texts, src_lang, tgt_lang, max_new_tokens, generation_params
        )
        return translations

    def translate_with_token_counts(
        self,
        texts: List[str],
        src_lang: str,
        tgt_lang: str,
        max_new_tokens: Optional[int] = None,
        generation_params: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[str], int, int]:
        """Translate texts and return token counts.

        Args:
            texts: Source texts.
            src_lang: Source language code.
            tgt_lang: Target language code.
            max_new_tokens: Unused (LLM config controls this).
            generation_params: Unused.

        Returns:
            Tuple of (translations, total_input_tokens, total_output_tokens).
        """
        if not self.loaded:
            raise RuntimeError("Model not loaded. Call load() first.")

        if not texts:
            return [], 0, 0

        system_prompt = self._build_system_prompt(src_lang, tgt_lang)

        translations: List[str] = []
        total_input = 0
        total_output = 0
        start_time = time.perf_counter()

        tm = self._term_manager

        for idx, text in enumerate(texts):
            if not text.strip():
                translations.append(text)
                continue

            try:
                # Protect technical terms with placeholders before LLM call
                # (prevents transliteration of TAR→Тар, ZIP→Жип, etc.)
                protected = tm.protect(text) if tm else None
                input_text = protected.protected_text if protected else text

                result, inp_tokens, out_tokens = self._provider.generate(
                    system_prompt=system_prompt,
                    user_text=input_text,
                )

                # Restore protected terms (handles Cyrillic/case corruption of placeholders)
                if protected:
                    protected.protected_text = result
                    result = tm.restore(protected)

                translations.append(result)
                total_input += inp_tokens
                total_output += out_tokens

            except Exception as e:
                logger.error(
                    "LLM translation failed for segment %d/%d: %s",
                    idx + 1,
                    len(texts),
                    e,
                )
                # Fallback to source text — matches engine's empty-translation pattern
                translations.append(text)

        elapsed = time.perf_counter() - start_time

        self.last_input_tokens = total_input
        self.last_output_tokens = total_output

        logger.info(
            "LLM translation: batch=%d tokens_in=%d tokens_out=%d elapsed=%.1fs",
            len(texts),
            total_input,
            total_output,
            elapsed,
        )

        return translations, total_input, total_output

    def unload(self) -> None:
        """Release provider resources."""
        if self._provider:
            self._provider.shutdown()
            self._provider = None
        self.loaded = False
        logger.info("LLMModelBackend unloaded")

    def is_loaded(self) -> bool:
        """Check if backend is loaded."""
        return self.loaded

    def get_token_count(self, text: str) -> int:
        """Estimate token count (no local tokenizer for LLM backends).

        Uses a heuristic of ~1.3 tokens per word.

        Args:
            text: Text to estimate.

        Returns:
            Estimated token count.
        """
        return int(len(text.split()) * 1.3)

    def _build_system_prompt(self, src_lang: str, tgt_lang: str) -> str:
        """Build the translation system prompt.

        Args:
            src_lang: Source language code.
            tgt_lang: Target language code.

        Returns:
            Formatted system prompt string.
        """
        template = (
            self.model_info.system_prompt_template
            if self.model_info.system_prompt_template
            else DEFAULT_SYSTEM_PROMPT
        )
        src_name = LANGUAGE_NAMES.get(src_lang, src_lang.upper())
        tgt_name = LANGUAGE_NAMES.get(tgt_lang, tgt_lang.upper())

        return template.format(
            src_lang_name=src_name,
            tgt_lang_name=tgt_name,
        )
