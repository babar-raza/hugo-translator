"""
LLM Translation Backend for ModelLoader.

Provides LLM-based translation through the ModelBackend interface,
enabling plug-and-play switching between MT models and LLMs via
config/model_registry.yaml entries.

Supports all providers in llm_providers.py: Ollama, OpenAI,
Anthropic, and any OpenAI-compatible endpoint.
"""

import contextvars
import logging
import re
import time
from pathlib import Path
from typing import Any

from .contracts import LLMProviderConfig
from .llm_providers import BaseLLMProvider, create_provider
from .loader import repair_mojibake
from .registry import ModelInfo

logger = logging.getLogger(__name__)

# HT-QUALITY-GATES-001 Part 22 (root cause B, LLM prompt-context race):
# ModelLoader caches ONE LLMModelBackend instance per model, shared across
# every concurrent worker thread (max_parallel_files: 2+ per site config).
# translate_with_context() used to stash context_hint/file_context as plain
# instance attributes (`self._ctx_hint`/`self._ctx_file`) on that shared
# instance, read back later inside prompt-building -- two threads
# translating different files concurrently could interleave, so file A's
# prompt got built with file B's class context. Confirmed as the same shape
# as the reference.aspose.org CfbDocument/StampInfo description
# cross-contamination found this session. contextvars.ContextVar gives each
# thread (and each asyncio task, if this code is ever awaited concurrently)
# its own independent view by default -- no shared mutable state, no lock
# needed, and no call-chain signature changes required in the many
# `translate()`/`translate_with_token_counts()` call sites elsewhere in this
# file that don't care about context at all.
_ctx_hint_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "llm_backend_ctx_hint", default=None
)
_ctx_file_var: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar(
    "llm_backend_ctx_file", default=None
)
_retry_feedback_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "llm_backend_retry_feedback", default=None
)
# Same race, same fix: this used to be a temporary instance-attribute
# override (`self.MAX_SEGMENTS_PER_PROMPT = 30`) on the shared backend.
_max_segments_per_prompt_var: contextvars.ContextVar[int] = contextvars.ContextVar(
    "llm_backend_max_segments_per_prompt", default=8
)

# ISO 639-1 → full language name for translation prompts
LANGUAGE_NAMES = {
    "af": "Afrikaans",
    "ar": "Arabic",
    "az": "Azerbaijani",
    "bg": "Bulgarian",
    "ca": "Catalan",
    "cs": "Czech",
    "da": "Danish",
    "de": "German",
    "el": "Greek",
    "en": "English",
    "es": "Spanish",
    "et": "Estonian",
    "fa": "Persian",
    "fi": "Finnish",
    "fr": "French",
    "ga": "Irish",
    "he": "Hebrew",
    "hi": "Hindi",
    "hr": "Croatian",
    "hu": "Hungarian",
    "id": "Indonesian",
    "it": "Italian",
    "ja": "Japanese",
    "ko": "Korean",
    "lt": "Lithuanian",
    "lv": "Latvian",
    "ms": "Malay",
    "nb": "Norwegian Bokmål",
    "nl": "Dutch",
    "no": "Norwegian",
    "pl": "Polish",
    "pt": "Portuguese",
    "ro": "Romanian",
    "ru": "Russian",
    "sk": "Slovak",
    "sl": "Slovenian",
    "sr": "Serbian",
    "sv": "Swedish",
    "th": "Thai",
    "tr": "Turkish",
    "uk": "Ukrainian",
    "vi": "Vietnamese",
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

# TC-HT-003: prompt-echo / refusal detection patterns.
_REFUSAL_RE = re.compile(
    r"^(i cannot|i can'?t|i'?m sorry|as an ai|i am (an ai|unable))",
    re.IGNORECASE,
)
# Short single-token/phrase line ending in a colon (EN "Rules:" or a
# translated equivalent like "Reglas:"/"Regeln:") — language-agnostic,
# matched structurally rather than against a fixed word list.
_RULE_HEADER_LINE_RE = re.compile(r"^\s*[^\s:：]{1,24}[:：]\s*$")
_LIST_MARKER_RE = re.compile(r"^\s*[-*]\s")
_NUMBERED_MARKER_RE = re.compile(r"^\s*\d+[.)]\s")


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

        # TC-HT-003: prompt-echo/refusal rejects from the most recent
        # translate_with_token_counts() call, keyed by index into `texts`.
        self.last_reject_reasons: dict[int, str] = {}

        # TC-AST-02: Configurable hallucination cap (default 4.0× input length).
        # Read from global config so it survives model reloads without restarts.
        try:
            from src.utils.config_loader import get_global_config

            _te_cfg = get_global_config().get("translation_engine", {})
            self._max_hallucination_ratio: float = float(
                _te_cfg.get("max_llm_output_to_input_ratio", 4.0)
            )
            # TC-H2: Per-language overrides (e.g. hi: 3.0, pl: 5.0, cs: 5.0).
            # Key: ISO 639-1 lang code → float ratio. Falls back to global when absent.
            self._hallucination_ratio_overrides: dict[str, float] = {
                str(k): float(v) for k, v in _te_cfg.get("llm_output_ratio_overrides", {}).items()
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
                logger.warning(
                    "TerminologyManager unavailable: %s — terms sent unprotected to LLM", e
                )
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

    def translate_with_context(
        self,
        texts: list[str],
        src_lang: str,
        tgt_lang: str,
        context_hint: str | None = None,
        file_context: dict[str, str] | None = None,
        retry_feedback: str | None = None,
    ) -> list[str]:
        """Translate with optional content-type context for enriched prompting.

        When ``context_hint == "api_property_description"``, the system prompt
        is enriched with class/product information from ``file_context`` and
        the batch size is increased to 30 (short descriptions are cheap).

        Args:
            texts: Source texts.
            src_lang: Source language code.
            tgt_lang: Target language code.
            context_hint: Content-type hint from ContentTypeRouter
                (e.g. ``"api_property_description"``, ``"frontmatter_description"``).
            file_context: Optional dict with keys ``class_name``, ``product``, etc.
                Derived from the output file path via :meth:`_derive_file_context`.

        Returns:
            List of translated texts in original order.
        """
        if not texts:
            return []

        # HT-QUALITY-GATES-001 Part 22: context lives in thread/task-local
        # ContextVars, not shared instance attributes -- see the module-level
        # comment above for why. reset(token) restores the PREVIOUS value in
        # this same context (normally the default), not just blanking it,
        # which matters if translate_with_context() calls are ever nested.
        hint_token = _ctx_hint_var.set(context_hint)
        file_token = _ctx_file_var.set(file_context)
        feedback_token = _retry_feedback_var.set(retry_feedback)
        try:
            # Use larger batch for short API descriptions (avg ~8 tokens each)
            max_token = _max_segments_per_prompt_var.set(
                30
                if context_hint == "api_property_description"
                else _max_segments_per_prompt_var.get()
            )
            try:
                translations, _, _ = self.translate_with_token_counts(texts, src_lang, tgt_lang)
            finally:
                _max_segments_per_prompt_var.reset(max_token)
        finally:
            _retry_feedback_var.reset(feedback_token)
            _ctx_hint_var.reset(hint_token)
            _ctx_file_var.reset(file_token)
        return translations

    def translate_with_retry_feedback(
        self,
        texts: list[str],
        src_lang: str,
        tgt_lang: str,
        retry_feedback: str,
        **kwargs,
    ) -> list[str]:
        """Translate with candidate-free correction instructions in the system prompt."""
        feedback_token = _retry_feedback_var.set(retry_feedback)
        try:
            return self.translate(texts, src_lang, tgt_lang, **kwargs)
        finally:
            _retry_feedback_var.reset(feedback_token)

    def translate_with_token_counts_and_retry_feedback(
        self,
        texts: list[str],
        src_lang: str,
        tgt_lang: str,
        retry_feedback: str,
        **kwargs,
    ) -> tuple[list[str], int, int]:
        """Translate with token counts and governed system-prompt feedback."""
        feedback_token = _retry_feedback_var.set(retry_feedback)
        try:
            return self.translate_with_token_counts(texts, src_lang, tgt_lang, **kwargs)
        finally:
            _retry_feedback_var.reset(feedback_token)

    @staticmethod
    def _apply_retry_feedback(system_prompt: str) -> str:
        feedback = _retry_feedback_var.get()
        if not feedback:
            return system_prompt
        return (
            f"{system_prompt}\n\nGoverned retry requirements:\n"
            f"- {feedback}\n"
            "- Apply these requirements silently; do not repeat or discuss them."
        )

    @staticmethod
    def _derive_file_context(output_path: str | None) -> dict[str, str]:
        """Extract class name and product from a reference.aspose.org file path.

        Example path:
          ``D:/content/reference.aspose.org/content/zh/cells/python/Alignment.md``
        Extracted: ``{"class_name": "Alignment", "product": "cells/python"}``

        Returns an empty dict for non-reference paths or when path is None.
        """
        if not output_path:
            return {}
        p = Path(output_path)
        if "reference.aspose.org" not in str(p):
            return {}
        # Parts after the locale segment: product/module/ClassName.md
        parts = p.parts
        try:
            # Find locale segment index (2-letter language code)
            content_idx = next(i for i, part in enumerate(parts) if part == "content")
            # locale is content_idx + 1; product parts follow, class name is last
            after_locale = parts[content_idx + 2 :]  # skip content/<locale>/
            if len(after_locale) >= 2:
                class_name = p.stem  # filename without extension
                product = "/".join(after_locale[:-1])
                return {"class_name": class_name, "product": product}
        except (StopIteration, IndexError):
            pass
        return {}

    # LLM-WASTE-FIX-3: max segments packed into a single LLM prompt.
    # Each segment gets a numbered tag; the LLM returns numbered translations.
    # If parsing fails, we fall back to per-segment calls for that sub-batch.
    # HT-QUALITY-GATES-001 Part 22: the effective, possibly-overridden value
    # now lives in _max_segments_per_prompt_var (module-level ContextVar);
    # this class attribute is kept only as the documented default baseline.
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
        self.last_reject_reasons = {}

        # Separate empty/whitespace-only texts (no API call needed)
        non_empty_indices = [i for i, t in enumerate(texts) if t.strip()]
        for i, t in enumerate(texts):
            if not t.strip():
                translations[i] = t  # preserve whitespace-only as-is

        # Process non-empty texts in packed sub-batches
        _max_segments = _max_segments_per_prompt_var.get()
        for sub_start in range(0, len(non_empty_indices), _max_segments):
            sub_indices = non_empty_indices[sub_start : sub_start + _max_segments]

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

    @staticmethod
    def _validate_llm_response(response: str, source_text: str, system_prompt: str) -> str | None:
        """Return a rejection reason if `response` looks like a leaked
        prompt-rule echo or a refusal rather than an actual translation,
        else None.

        TC-HT-003: a response dominated by the system prompt's own rule text
        (in English or translated) or a refusal phrase must never reach
        output — this is the direct fix for the wave-3 TITLE_MISMATCH bug,
        where such text was accepted verbatim into title/linkTitle.
        Checks are independent of response length, so short legitimate
        translations can never trip them.
        """
        stripped = response.strip()
        if not stripped:
            return "refusal"
        if _REFUSAL_RE.match(stripped):
            return "refusal"

        # HT-QUALITY-GATES-001 Part 22 (1.6): _REFUSAL_RE above only matches
        # at the START of the response. A fluent, mid-string, or
        # non-start-anchored conversational reply -- a clarifying question,
        # an apology not beginning with "I'm sorry", "let me know if..." --
        # passed every check here untouched and shipped as translated
        # content in production (confirmed real examples: a `keywords` list
        # entry that reads "Could you please provide the English text you'd
        # like translated into Ukrainian?"; body prose reading "I'm sorry,
        # but I can't access or read any attached files..."). Reuses the
        # same curated patterns as write_gate.py's Gate 29/30 (single source
        # of truth, src/translation_engine/quality/refusal_patterns.py) so
        # generation-time and write-time detection can't drift apart.
        # Lazy import: translation_engine's package __init__ imports
        # TranslationEngine, which imports this package (ModelLoader) at
        # module load time -- a top-level import here would be circular.
        from src.translation_engine.quality.refusal_patterns import (
            CONVERSATIONAL_SHAPE_RE,
            REFUSAL_RE,
        )

        if REFUSAL_RE.search(stripped) or CONVERSATIONAL_SHAPE_RE.search(stripped):
            return "refusal"

        lines = stripped.splitlines()

        # Structural rule-header leak: a short single-token/phrase line
        # ending in a colon, immediately followed by >=2 list/numbered
        # lines — catches "Rules:"/"Reglas:"/"Regeln:" style leaks without
        # needing a fixed word list per language.
        for i, line in enumerate(lines[:-1]):
            if not _RULE_HEADER_LINE_RE.match(line):
                continue
            following = lines[i + 1 : i + 4]
            marker_count = sum(
                1 for ln in following if _LIST_MARKER_RE.match(ln) or _NUMBERED_MARKER_RE.match(ln)
            )
            if marker_count >= 2:
                return "rule_header_leak"

        # List-marker leak: response has >=2 list-marker lines while the
        # source has none at all.
        response_list_lines = sum(1 for ln in lines if _LIST_MARKER_RE.match(ln))
        if response_list_lines >= 2:
            source_has_list = any(_LIST_MARKER_RE.match(ln) for ln in source_text.splitlines())
            if not source_has_list:
                return "list_marker_leak"

        # English rule n-gram overlap: system_prompt is always our own text,
        # so rule-line extraction is exact, not fuzzy.
        rule_lines = [
            ln.strip().lstrip("- ")
            for ln in system_prompt.splitlines()
            if ln.strip().startswith("- ")
        ]
        if rule_lines:

            def _words(s: str) -> set[str]:
                return set(re.findall(r"[a-z0-9]+", s.lower()))

            for resp_line in lines:
                resp_words = _words(resp_line)
                if not resp_words:
                    continue
                for rule_line in rule_lines:
                    rule_words = _words(rule_line)
                    if not rule_words:
                        continue
                    overlap = len(resp_words & rule_words) / len(rule_words)
                    if overlap >= 0.6:
                        return "prompt_echo_en"

        return None

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
        system_prompt = self._apply_retry_feedback(self._build_system_prompt(src_lang, tgt_lang))
        try:
            protected = tm.protect(text) if tm else None
            input_text = protected.protected_text if protected else text

            result, inp_tokens, out_tokens = self._provider.generate(
                system_prompt=system_prompt,
                user_text=input_text,
            )

            # TC-HT-003: reject prompt-echo/refusal responses before any
            # other processing — a rule-echo must never reach output, even
            # truncated (truncating rule-garbage into e.g. `title` still
            # leaves garbage; only reject+passthrough is safe).
            reject_reason = self._validate_llm_response(result, input_text, system_prompt)
            if reject_reason is not None:
                logger.error(
                    "LLM response rejected (%s) for segment %d/%d: prompt-echo/refusal guard fired",
                    reject_reason,
                    idx + 1,
                    total,
                )
                self.last_reject_reasons[idx] = reject_reason
                translations[idx] = text
                return inp_tokens, out_tokens

            # TC-AST-02 / TC-H2: Configurable hallucination cap with per-language overrides.
            # Per-language override takes precedence; falls back to global ratio.
            input_len = len(input_text)
            output_len = len(result)
            _max_ratio = self._hallucination_ratio_overrides.get(
                tgt_lang, self._max_hallucination_ratio
            )
            if input_len > 0 and output_len > _max_ratio * input_len:
                excess_text = result[int(input_len * _max_ratio) :]
                if re.search(r"^\s*[-*]\s", excess_text, re.MULTILINE):
                    # TC-HT-003: the overflow itself looks like leaked
                    # rule/list text rather than a verbose-but-legitimate
                    # translation — reject and passthrough rather than
                    # truncate.
                    logger.error(
                        "LLM hallucination with list-marker overflow rejected for segment %d/%d "
                        "(%d→%d chars, %.1fx input)",
                        idx + 1,
                        total,
                        input_len,
                        output_len,
                        output_len / input_len,
                    )
                    self.last_reject_reasons[idx] = "hallucination_list_marker_reject"
                    translations[idx] = text
                    return inp_tokens, out_tokens
                logger.error(
                    "LLM hallucination detected: segment %d/%d output is %.1fx input "
                    "(%d→%d chars). Truncating to %.1fx source length (max_llm_output_to_input_ratio=%.1f).",
                    idx + 1,
                    total,
                    output_len / input_len,
                    input_len,
                    output_len,
                    _max_ratio,
                    _max_ratio,
                )
                self.last_truncation_detected = True
                self.truncation_count += 1
                # Truncate at word boundary to avoid mid-word cuts that break markdown.
                hard_limit = int(input_len * _max_ratio)
                truncated = result[:hard_limit]
                # Back up to last whitespace or newline so we don't cut mid-word.
                last_ws = max(truncated.rfind(" "), truncated.rfind("\n"))
                if last_ws > hard_limit * 0.8:
                    result = truncated[:last_ws].rstrip()
                else:
                    result = truncated  # No boundary found close enough; use character limit
            elif input_len > 0 and output_len > 3 * input_len:
                logger.warning(
                    "LLM output unusually long: segment %d/%d is %.1fx input (%d→%d chars)",
                    idx + 1,
                    total,
                    output_len / input_len,
                    input_len,
                    output_len,
                )

            if protected:
                protected.protected_text = result
                result = tm.restore(protected)

            translations[idx] = repair_mojibake(result)
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
        system_prompt = self._apply_retry_feedback(
            self._build_batch_system_prompt(src_lang, tgt_lang, len(indices))
        )

        # Protect terms and build packed input
        protected_map = {}  # idx -> ProtectedResult
        lines = []
        for seq, idx in enumerate(indices, 1):
            if tm:
                p = tm.protect(texts[idx])
                if p:
                    protected_map[idx] = p
                    lines.append(f"<<<SEG_{seq}>>> {p.protected_text}")
                else:
                    lines.append(f"<<<SEG_{seq}>>> {texts[idx]}")
            else:
                lines.append(f"<<<SEG_{seq}>>> {texts[idx]}")

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

                    # TC-HT-003: reject prompt-echo/refusal per-item before
                    # term restore, same guard as the single-segment path.
                    reject_reason = self._validate_llm_response(trans, texts[idx], system_prompt)
                    if reject_reason is not None:
                        logger.error(
                            "LLM response rejected (%s) for packed segment idx=%d: "
                            "prompt-echo/refusal guard fired",
                            reject_reason,
                            idx,
                        )
                        self.last_reject_reasons[idx] = reject_reason
                        translations[idx] = texts[idx]
                        continue

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
            <<<SEG_1>>> Translation one
            <<<SEG_2>>> Translation two

        Returns list of translations (0-indexed) or None if parsing fails.
        """
        # Match lines starting with <<<SEG_N>>> (with optional leading whitespace)
        pattern = re.compile(r"^\s*<<<SEG_(\d+)>>>\s*(.*)$", re.MULTILINE)
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

        When a context hint is active (set via :meth:`translate_with_context`),
        injects class context for API property descriptions.

        Args:
            src_lang: Source language code.
            tgt_lang: Target language code.
            segment_count: Number of segments in the batch.

        Returns:
            Formatted system prompt string.
        """
        src_name = LANGUAGE_NAMES.get(src_lang, src_lang.upper())
        tgt_name = LANGUAGE_NAMES.get(tgt_lang, tgt_lang.upper())
        hint: str | None = _ctx_hint_var.get()
        file_ctx: dict[str, str] = _ctx_file_var.get() or {}

        if hint == "api_property_description":
            class_name = file_ctx.get("class_name", "")
            class_clause = f" Class context: `{class_name}`." if class_name else ""
            return (
                f"You are an API documentation translator.{class_clause} "
                f"Translate each numbered property description from {src_name} to {tgt_name}.\n\n"
                f"Input: {segment_count} numbered items, each prefixed with <<<SEG_N>>>.\n"
                f"Output: {segment_count} translated items, each on its own line "
                f"prefixed with the SAME tag <<<SEG_N>>>.\n\n"
                f"Rules:\n"
                f"- Output ONLY the translations with their numbers, nothing else\n"
                f"- Property names, class names, and code identifiers MUST NOT be translated\n"
                f"- Keep the exact tense and voice of each description\n"
                f"- Preserve backtick spans and markdown formatting"
            )

        return (
            f"You are a professional translator. Translate each numbered segment "
            f"from {src_name} to {tgt_name}.\n\n"
            f"Input: {segment_count} numbered segments, each prefixed with <<<SEG_N>>>.\n"
            f"Output: {segment_count} translated segments, each on its own line "
            f"prefixed with the SAME tag <<<SEG_N>>>.\n\n"
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

        When a context hint is active (set via :meth:`translate_with_context`),
        an enriched prompt is returned for known hint types.

        Args:
            src_lang: Source language code.
            tgt_lang: Target language code.

        Returns:
            Formatted system prompt string.
        """
        src_name = LANGUAGE_NAMES.get(src_lang, src_lang.upper())
        tgt_name = LANGUAGE_NAMES.get(tgt_lang, tgt_lang.upper())
        hint: str | None = _ctx_hint_var.get()
        file_ctx: dict[str, str] = _ctx_file_var.get() or {}

        if hint == "api_property_description":
            class_name = file_ctx.get("class_name", "")
            class_clause = f" of the `{class_name}` class" if class_name else ""
            return (
                f"You are an API documentation translator. "
                f"Translate each property description{class_clause} from {src_name} to {tgt_name}.\n\n"
                "Rules:\n"
                "- Property names, class names, and code identifiers MUST NOT be translated\n"
                "- Keep the exact tense and voice of each description\n"
                "- Output ONLY the translation, nothing else\n"
                "- Preserve all formatting: markdown, backtick spans, links"
            )
        if hint == "frontmatter_description":
            return (
                f"You are a technical documentation translator. "
                f"Translate this API class description from {src_name} to {tgt_name}.\n\n"
                "Rules:\n"
                "- Keep class names, method names, and identifiers in English\n"
                "- Output ONLY the translation, nothing else\n"
                "- Keep the same concise register as the source"
            )

        template = (
            self.model_info.system_prompt_template
            if self.model_info.system_prompt_template
            else DEFAULT_SYSTEM_PROMPT
        )
        return template.format(
            src_lang_name=src_name,
            tgt_lang_name=tgt_name,
        )
