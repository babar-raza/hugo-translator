"""
LLM Translation Backend for ModelLoader.

Provides LLM-based translation through the ModelBackend interface,
enabling plug-and-play switching between MT models and LLMs via
config/model_registry.yaml entries.

Supports all providers in llm_providers.py: Ollama, OpenAI,
Anthropic, and any OpenAI-compatible endpoint.
"""

import logging
import re
import time
from pathlib import Path
from typing import Any

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
    "You are a professional technical translator. Translate the following text from "
    "{src_lang_name} to {tgt_lang_name}.\n\n"
    "Rules:\n"
    "- Output ONLY the translation, nothing else\n"
    "- Preserve all formatting: markdown, HTML tags, links\n"
    "- Preserve all Hugo shortcodes ({{{{< ... >}}}}) and template syntax EXACTLY as written\n"
    "- Preserve inline code spans (`code`) EXACTLY — do not translate content inside backticks\n"
    "- Preserve fenced code blocks (```...```) EXACTLY — do not translate code inside them\n"
    "- Preserve all URLs and file paths EXACTLY — do not modify or translate them\n"
    "- Do not add, invent, or fabricate any content not present in the source text\n"
    "- Do not add explanations, notes, commentary, or placeholder text\n"
    "- Keep technical terms, brand names (Aspose, .NET, C#), and API identifiers unchanged\n"
    "- NEVER transliterate or translate archive/compression format names: "
    "TAR, ZIP, RAR, GZ, BZ2, TGZ, XZ, 7Z, BZIP2 — keep them exactly as written\n"
    "- Complete the full translation without truncation — do not stop mid-sentence\n"
    "- Preserve the same number of paragraphs and line breaks as the source\n"
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

        self._provider: BaseLLMProvider | None = None
        self._terminology_manager = None  # lazy-loaded on first translate() call

        # TEL-04 token tracking compatibility
        self.last_input_tokens: int = 0
        self.last_output_tokens: int = 0
        self.last_truncation_detected: bool = False
        self.truncation_count: int = 0

        # TC-AST-02: Configurable hallucination cap (default 4.0× input length).
        # Read from global config so it survives model reloads without restarts.
        try:
            from src.utils.config_loader import get_global_config
            _te_cfg = get_global_config().get('translation_engine', {})
            self._max_hallucination_ratio: float = float(
                _te_cfg.get('max_llm_output_to_input_ratio', 4.0)
            )
            # TC-H2: Per-language overrides (e.g. hi: 3.0, pl: 5.0, cs: 5.0).
            # Key: ISO 639-1 lang code → float ratio. Falls back to global when absent.
            self._hallucination_ratio_overrides: dict[str, float] = {
                str(k): float(v)
                for k, v in _te_cfg.get('llm_output_ratio_overrides', {}).items()
            }
        except Exception:
            self._max_hallucination_ratio = 4.0
            self._hallucination_ratio_overrides = {}

    @property
    def _term_manager(self):
        """Lazy-load TerminologyManager for placeholder-based term protection."""
        if self._terminology_manager is None:
            try:
                from src.translation_engine.terminology.terminology_manager import (
                    TerminologyManager,
                )
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
        texts: list[str],
        src_lang: str,
        tgt_lang: str,
        max_new_tokens: int | None = None,
        generation_params: dict[str, Any] | None = None,
    ) -> list[str]:
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

    # LLM-WASTE-FIX-3: max segments packed into a single LLM prompt.
    # Each segment gets a numbered tag; the LLM returns numbered translations.
    # If parsing fails, we fall back to per-segment calls for that sub-batch.
    MAX_SEGMENTS_PER_PROMPT = 8

    def translate_with_token_counts(
        self,
        texts: list[str],
        src_lang: str,
        tgt_lang: str,
        max_new_tokens: int | None = None,
        generation_params: dict[str, Any] | None = None,
    ) -> tuple[list[str], int, int]:
        """Translate texts and return token counts.

        LLM-WASTE-FIX-3: packs multiple segments into a single prompt using
        numbered delimiters to reduce per-call system-prompt overhead.

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

        translations: list[str] = [""] * len(texts)
        total_input = 0
        total_output = 0
        start_time = time.perf_counter()
        tm = self._term_manager

        # Separate empty/whitespace-only texts (no API call needed)
        non_empty_indices = [i for i, t in enumerate(texts) if t.strip()]
        for i, t in enumerate(texts):
            if not t.strip():
                translations[i] = t  # preserve whitespace-only as-is

        # Process non-empty texts in packed sub-batches
        for sub_start in range(0, len(non_empty_indices), self.MAX_SEGMENTS_PER_PROMPT):
            sub_indices = non_empty_indices[sub_start:sub_start + self.MAX_SEGMENTS_PER_PROMPT]

            if len(sub_indices) == 1:
                # Single segment — use direct prompt (no packing overhead)
                idx = sub_indices[0]
                inp, out = self._translate_single_segment(
                    texts[idx], idx, len(texts), src_lang, tgt_lang, tm, translations
                )
                total_input += inp
                total_output += out
            else:
                # Multi-segment — pack into numbered prompt
                inp, out = self._translate_packed_batch(
                    texts, sub_indices, src_lang, tgt_lang, tm, translations
                )
                total_input += inp
                total_output += out

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

    def _translate_single_segment(
        self,
        text: str,
        idx: int,
        total: int,
        src_lang: str,
        tgt_lang: str,
        tm,
        translations: list[str],
    ) -> tuple[int, int]:
        """Translate a single segment via one LLM call.

        Returns (input_tokens, output_tokens).
        """
        system_prompt = self._build_system_prompt(src_lang, tgt_lang)
        try:
            protected = tm.protect(text) if tm else None
            input_text = protected.protected_text if protected else text

            result, inp_tokens, out_tokens = self._provider.generate(
                system_prompt=system_prompt,
                user_text=input_text,
            )

            # TC-AST-02 / TC-H2: Configurable hallucination cap with per-language overrides.
            # Per-language override takes precedence; falls back to global ratio.
            input_len = len(input_text)
            output_len = len(result)
            _max_ratio = self._hallucination_ratio_overrides.get(
                tgt_lang, self._max_hallucination_ratio
            )
            if input_len > 0 and output_len > _max_ratio * input_len:
                logger.error(
                    "LLM hallucination detected: segment %d/%d output is %.1fx input "
                    "(%d→%d chars). Truncating to %.1fx source length (max_llm_output_to_input_ratio=%.1f).",
                    idx + 1, total, output_len / input_len, input_len, output_len, _max_ratio, _max_ratio,
                )
                self.last_truncation_detected = True
                self.truncation_count += 1
                # Truncate at word boundary to avoid mid-word cuts that break markdown.
                hard_limit = int(input_len * _max_ratio)
                truncated = result[:hard_limit]
                # Back up to last whitespace or newline so we don't cut mid-word.
                last_ws = max(truncated.rfind(' '), truncated.rfind('\n'))
                if last_ws > hard_limit * 0.8:
                    result = truncated[:last_ws].rstrip()
                else:
                    result = truncated  # No boundary found close enough; use character limit
            elif input_len > 0 and output_len > 3 * input_len:
                logger.warning(
                    "LLM output unusually long: segment %d/%d is %.1fx input (%d→%d chars)",
                    idx + 1, total, output_len / input_len, input_len, output_len,
                )

            if protected:
                protected.protected_text = result
                result = tm.restore(protected)

            translations[idx] = result
            return inp_tokens, out_tokens

        except Exception as e:
            logger.error("LLM translation failed for segment %d/%d: %s", idx + 1, total, e)
            translations[idx] = text  # fallback to source
            return 0, 0

    def _translate_packed_batch(
        self,
        texts: list[str],
        indices: list[int],
        src_lang: str,
        tgt_lang: str,
        tm,
        translations: list[str],
    ) -> tuple[int, int]:
        """Pack multiple segments into one numbered prompt, parse results back.

        Falls back to per-segment calls if output parsing fails.
        Returns (total_input_tokens, total_output_tokens).
        """
        system_prompt = self._build_batch_system_prompt(src_lang, tgt_lang, len(indices))

        # Protect terms and build packed input
        protected_map = {}  # idx -> ProtectedResult
        lines = []
        for seq, idx in enumerate(indices, 1):
            if tm:
                p = tm.protect(texts[idx])
                if p:
                    protected_map[idx] = p
                    lines.append(f"[{seq}] {p.protected_text}")
                else:
                    lines.append(f"[{seq}] {texts[idx]}")
            else:
                lines.append(f"[{seq}] {texts[idx]}")

        packed_input = "\n".join(lines)

        try:
            result, inp_tokens, out_tokens = self._provider.generate(
                system_prompt=system_prompt,
                user_text=packed_input,
            )

            # Parse numbered outputs
            parsed = self._parse_packed_output(result, len(indices))

            if parsed is not None:
                # Successfully parsed — assign translations
                for seq, idx in enumerate(indices):
                    trans = parsed[seq]
                    if idx in protected_map:
                        protected_map[idx].protected_text = trans
                        trans = tm.restore(protected_map[idx])
                    translations[idx] = trans
                return inp_tokens, out_tokens
            else:
                # Parsing failed — fall back to per-segment calls
                logger.warning(
                    "Packed batch parsing failed (%d segments). "
                    "Falling back to per-segment translation.",
                    len(indices),
                )
                total_in, total_out = 0, 0
                for idx in indices:
                    i, o = self._translate_single_segment(
                        texts[idx], idx, len(texts), src_lang, tgt_lang, tm, translations
                    )
                    total_in += i
                    total_out += o
                return total_in, total_out

        except Exception as e:
            logger.error("Packed batch LLM call failed: %s. Falling back to per-segment.", e)
            total_in, total_out = 0, 0
            for idx in indices:
                i, o = self._translate_single_segment(
                    texts[idx], idx, len(texts), src_lang, tgt_lang, tm, translations
                )
                total_in += i
                total_out += o
            return total_in, total_out

    @staticmethod
    def _parse_packed_output(raw: str, expected_count: int) -> list[str] | None:
        """Parse numbered LLM output back into individual translations.

        Expected format:
            [1] Translation one
            [2] Translation two

        Returns list of translations (0-indexed) or None if parsing fails.
        """
        # Match lines starting with [N] (with optional leading whitespace)
        pattern = re.compile(r"^\s*\[(\d+)\]\s*(.*)$", re.MULTILINE)
        matches = list(pattern.finditer(raw))

        if len(matches) != expected_count:
            return None

        result = [None] * expected_count
        for match in matches:
            seq = int(match.group(1))
            text = match.group(2).strip()
            if seq < 1 or seq > expected_count:
                return None
            result[seq - 1] = text

        # Check all slots filled
        if any(r is None for r in result):
            return None

        return result

    def _build_batch_system_prompt(self, src_lang: str, tgt_lang: str, segment_count: int) -> str:
        """Build system prompt for packed multi-segment translation.

        Args:
            src_lang: Source language code.
            tgt_lang: Target language code.
            segment_count: Number of segments in the batch.

        Returns:
            Formatted system prompt string.
        """
        src_name = LANGUAGE_NAMES.get(src_lang, src_lang.upper())
        tgt_name = LANGUAGE_NAMES.get(tgt_lang, tgt_lang.upper())

        return (
            f"You are a professional translator. Translate each numbered segment "
            f"from {src_name} to {tgt_name}.\n\n"
            f"Input: {segment_count} numbered segments, each prefixed with [N].\n"
            f"Output: {segment_count} translated segments, each on its own line "
            f"prefixed with the SAME number [N].\n\n"
            f"Rules:\n"
            f"- Output ONLY the translations with their numbers, nothing else\n"
            f"- Preserve all formatting: markdown, HTML tags, code blocks, links\n"
            f"- Preserve all Hugo shortcodes ({{{{< ... >}}}}) and template syntax exactly\n"
            f"- Keep technical terms, brand names, and API identifiers unchanged\n"
            f"- NEVER transliterate or translate archive/compression format names: "
            f"TAR, ZIP, RAR, GZ, BZ2, TGZ, XZ, 7Z, BZIP2 — keep them exactly as written\n"
            f"- Maintain the same tone and register as the source"
        )

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
