"""
TC-DECOMP-04: Segment-level translation logic.

Extracted from TranslationEngine: TM lookup, model call, batching,
placeholder/terminology restoration, multiline structure preservation,
and AST-based body translation.

The translator receives an engine reference for accessing shared state
(TM, model_loader, config, locks, etc.).
"""

from __future__ import annotations

import logging
import math
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

from ..observability.progress import get_progress_tracker
from .engine import estimate_token_count
from .exceptions import TranslationRetryableError
from .extractor import SegmentExtractor, TextUnitKind
from .models import TranslationStats, ValidationIssue, ValidationResult
from .reconstructor import MarkdownReconstructor

if TYPE_CHECKING:
    from .engine import TranslationEngine

logger = logging.getLogger(__name__)


class SegmentTranslator:
    """Owns TM lookup, model translation, batching, and reconstruction.

    Receives an engine reference for shared state access.
    """

    def __init__(self, engine: TranslationEngine) -> None:
        self._engine = engine

    @staticmethod
    def _should_preserve_multiline_line(text: str) -> bool:
        placeholders = re.findall(r"\{PLACEHOLDER_\d+\}", text)
        if len(placeholders) >= 3:
            return True
        if placeholders and len("".join(placeholders)) / max(len(text), 1) > 0.45:
            return True
        return False

    @staticmethod
    def _has_fenced_code(text: str) -> bool:
        return bool(re.search(r"```.*?```", text, flags=re.DOTALL))

    @staticmethod
    def _placeholder_is_fenced_code(token: str, placeholder_map: dict[str, str] | None) -> bool:
        if not placeholder_map:
            return False
        return SegmentTranslator._has_fenced_code(placeholder_map.get(token, ""))

    @staticmethod
    def _has_fenced_code_or_placeholder(text: str, placeholder_map: dict[str, str] | None) -> bool:
        if SegmentTranslator._has_fenced_code(text):
            return True
        return any(
            SegmentTranslator._placeholder_is_fenced_code(token, placeholder_map)
            for token in re.findall(r"\{PLACEHOLDER_\d+\}", text)
        )

    @staticmethod
    def _split_fenced_code(
        text: str, placeholder_map: dict[str, str] | None = None
    ) -> list[tuple[str, str]]:
        parts: list[tuple[str, str]] = []
        pos = 0
        pattern = r"```.*?```|\{PLACEHOLDER_\d+\}"
        for match in re.finditer(pattern, text, flags=re.DOTALL):
            token = match.group(0)
            is_code = token.startswith("```") or SegmentTranslator._placeholder_is_fenced_code(
                token, placeholder_map
            )
            if not is_code:
                continue
            if match.start() > pos:
                parts.append(("text", text[pos:match.start()]))
            parts.append(("code", token))
            pos = match.end()
        if pos < len(text):
            parts.append(("text", text[pos:]))
        return parts

    @staticmethod
    def _split_preserved_code(
        text: str, placeholder_map: dict[str, str] | None = None
    ) -> list[tuple[str, str]]:
        parts: list[tuple[str, str]] = []
        pos = 0
        pattern = r"```.*?```|`[^`\n]+`|\{PLACEHOLDER_\d+\}"
        for match in re.finditer(pattern, text, flags=re.DOTALL):
            token = match.group(0)
            is_code = (
                token.startswith("```")
                or token.startswith("`")
                or SegmentTranslator._placeholder_is_fenced_code(token, placeholder_map)
            )
            if not is_code:
                continue
            if match.start() > pos:
                parts.append(("text", text[pos:match.start()]))
            parts.append(("code", token))
            pos = match.end()
        if pos < len(text):
            parts.append(("text", text[pos:]))
        return parts

    @staticmethod
    def _is_effectively_untranslated(source: str, translated: str) -> bool:
        return source.strip() == translated.strip()

    @staticmethod
    def _product_title_suffix_parts(text: str) -> tuple[str, str, str] | None:
        match = re.match(
            r"^(Aspose\.[A-Za-z0-9.+#-]+(?:\s+FOSS)?)(\s+(?:[\u2013\u2014-])\s+)(.+)$",
            text.strip(),
        )
        if not match:
            return None
        suffix = match.group(3).strip()
        if not suffix or not re.search(r"[A-Za-z]{3,}", suffix):
            return None
        return match.group(1), match.group(2), suffix

    def _repair_untranslated_product_title(
        self,
        backend,
        source_text: str,
        translated_text: str,
        source_lang: str,
        target_lang: str,
        stats: TranslationStats,
    ) -> str:
        if not self._is_effectively_untranslated(source_text, translated_text):
            return translated_text

        parts = self._product_title_suffix_parts(source_text)
        if not parts:
            return translated_text

        prefix, separator, suffix = parts
        logger.info("Retrying untranslated product title suffix while preserving identity prefix")
        if hasattr(backend, "translate_with_token_counts"):
            translations, input_tokens, output_tokens = backend.translate_with_token_counts(
                [suffix], source_lang, target_lang
            )
            stats.tokens_input += input_tokens
            stats.tokens_output += output_tokens
        else:
            translations = backend.translate([suffix], source_lang, target_lang)
            stats.tokens_input += estimate_token_count(suffix)
            stats.tokens_output += sum(estimate_token_count(t) for t in translations)

        candidate = translations[0].strip() if translations else ""
        if not candidate or self._is_effectively_untranslated(suffix, candidate):
            return translated_text
        return f"{prefix}{separator}{candidate}"

    def _retry_untranslated_text_by_sentence(
        self,
        backend,
        source_text: str,
        translated_text: str,
        source_lang: str,
        target_lang: str,
        stats: TranslationStats,
    ) -> str:
        if not self._is_effectively_untranslated(source_text, translated_text):
            return translated_text
        if len(source_text.strip()) >= 20 and not self._has_fenced_code(source_text):
            candidate = self._translate_core_with_residue_variants(
                backend,
                source_text.strip(),
                source_lang,
                target_lang,
                stats,
            )
            if candidate.strip() and not self._is_effectively_untranslated(source_text, candidate):
                return candidate
        if len(source_text.strip()) < 80:
            return translated_text
        if self._has_fenced_code(source_text):
            return translated_text

        pieces = re.findall(r"(.+?(?:[.!?]+|$))(\s*)", source_text, flags=re.DOTALL)
        sentence_items = []
        rendered = []
        for sentence, spacing in pieces:
            if not sentence.strip():
                rendered.append(sentence + spacing)
                continue
            rendered.append("")
            sentence_items.append((len(rendered) - 1, sentence, spacing))

        if len(sentence_items) < 2:
            return translated_text

        logger.info(
            "Retrying effectively untranslated text as sentence chunks "
            f"({len(sentence_items)} chunks, target={target_lang})"
        )
        cores = [sentence.strip() for _, sentence, _ in sentence_items]
        if hasattr(backend, "translate_with_token_counts"):
            translations, input_tokens, output_tokens = backend.translate_with_token_counts(
                cores, source_lang, target_lang
            )
            stats.tokens_input += input_tokens
            stats.tokens_output += output_tokens
        else:
            translations = backend.translate(cores, source_lang, target_lang)
            stats.tokens_input += sum(estimate_token_count(t) for t in cores)
            stats.tokens_output += sum(estimate_token_count(t) for t in translations)

        for (rendered_idx, sentence, spacing), translation in zip(
            sentence_items, translations, strict=False
        ):
            rendered[rendered_idx] = f"{translation.strip() if translation.strip() else sentence.strip()}{spacing}"

        candidate = "".join(rendered)
        if not candidate.strip() or self._is_effectively_untranslated(source_text, candidate):
            return translated_text
        return candidate

    @staticmethod
    def _english_source_residue_count(source_text: str, translated_text: str) -> int:
        if not source_text or not translated_text:
            return 0
        if source_text.strip() == translated_text.strip():
            return 0

        def _strip_technical(text: str) -> str:
            text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
            return re.sub(
                r"Aspose\.[A-Za-z0-9.+#-]+|Aspose|FOSS|API|SDK|\.NET|Java|Python|TypeScript|"
                r"Node\.js|C\+\+|C#|HTML|PDF|CSV|JSON|TSV|XLSX|Excel|Markdown|NuGet|Maven|pip|GitHub|"
                r"Microsoft|Office|Outlook|Visio|AutoCAD|DWG|DXF|DGN|MSG|EML|CFB|GDI|"
                r"Workbook|Worksheet|Cell|Style|Font|Color|PageSetup",
                " ",
                text,
            )

        source_normalized = re.sub(r"\s+", " ", _strip_technical(source_text)).lower()
        target_text = _strip_technical(translated_text)
        english_function_words = {
            "the",
            "and",
            "for",
            "with",
            "without",
            "that",
            "which",
            "from",
            "into",
            "your",
            "you",
            "can",
            "are",
            "this",
            "these",
            "using",
            "support",
            "supports",
            "provides",
            "allows",
            "enables",
            "library",
            "developers",
            "operations",
            "options",
            "fully",
            "functional",
        }
        count = 0
        for match in re.finditer(r"\b(?:[A-Z]?[a-z]{3,}\s+){4,}[A-Z]?[a-z]{3,}\b", target_text):
            phrase = re.sub(r"\s+", " ", match.group(0).strip()).lower()
            words = set(re.findall(r"[a-z]{3,}", phrase))
            if len(words & english_function_words) < 2:
                continue
            if phrase in source_normalized:
                count += 1
        return count

    def _retry_english_residue_by_sentence(
        self,
        backend,
        source_text: str,
        translated_text: str,
        source_lang: str,
        target_lang: str,
        stats: TranslationStats,
    ) -> str:
        residue_before = self._english_source_residue_count(source_text, translated_text)
        if residue_before == 0:
            return translated_text
        if len(source_text.strip()) < 40 or self._has_fenced_code(source_text):
            return translated_text

        pieces = re.findall(r"(.+?(?:[.!?]+|$))(\s*)", source_text, flags=re.DOTALL)
        sentence_items = []
        rendered = []
        for sentence, spacing in pieces:
            if not sentence.strip():
                rendered.append(sentence + spacing)
                continue
            rendered.append("")
            sentence_items.append((len(rendered) - 1, sentence, spacing))

        if not sentence_items:
            return translated_text

        logger.info(
            "Retrying text with English source residue as sentence chunks "
            f"(residue={residue_before}, chunks={len(sentence_items)}, target={target_lang})"
        )
        cores = [sentence.strip() for _, sentence, _ in sentence_items]
        if hasattr(backend, "translate_with_token_counts"):
            translations, input_tokens, output_tokens = backend.translate_with_token_counts(
                cores, source_lang, target_lang
            )
            stats.tokens_input += input_tokens
            stats.tokens_output += output_tokens
        else:
            translations = backend.translate(cores, source_lang, target_lang)
            stats.tokens_input += sum(estimate_token_count(t) for t in cores)
            stats.tokens_output += sum(estimate_token_count(t) for t in translations)

        for (rendered_idx, sentence, spacing), translation in zip(
            sentence_items, translations, strict=False
        ):
            rendered[rendered_idx] = f"{translation.strip() if translation.strip() else sentence.strip()}{spacing}"

        candidate = "".join(rendered)
        if not candidate.strip():
            return translated_text
        if self._english_source_residue_count(source_text, candidate) < residue_before:
            return candidate
        if "`" in source_text or re.search(r"\{PLACEHOLDER_\d+\}", source_text):
            chunk_candidate = self._translate_fenced_code_prose_chunks(
                backend,
                source_text,
                source_lang,
                target_lang,
                stats,
            )
            if self._english_source_residue_count(source_text, chunk_candidate) < residue_before:
                return chunk_candidate
        return translated_text

    def _translate_fenced_code_prose_chunks(
        self,
        backend,
        source_text: str,
        source_lang: str,
        target_lang: str,
        stats: TranslationStats,
        placeholder_map: dict[str, str] | None = None,
    ) -> str:
        """Translate prose around fenced code blocks while preserving code exactly."""
        chunks = self._split_preserved_code(source_text, placeholder_map)
        prose_items: list[tuple[int, str]] = []
        rendered: list[str] = []

        for kind, value in chunks:
            if kind == "code" or not value.strip():
                rendered.append(value)
                continue
            rendered.append("")
            prose_items.append((len(rendered) - 1, value))

        for rendered_idx, prose in prose_items:
            leading_match = re.match(r"^\s*", prose)
            trailing_match = re.search(r"\s*$", prose)
            leading = leading_match.group(0) if leading_match else ""
            trailing = trailing_match.group(0) if trailing_match else ""
            core = prose[len(leading): len(prose) - len(trailing) if trailing else len(prose)]
            if not core:
                rendered[rendered_idx] = prose
                continue
            candidate = self._translate_core_with_residue_variants(
                backend,
                core,
                source_lang,
                target_lang,
                stats,
            )
            rendered[rendered_idx] = f"{leading}{candidate if candidate.strip() else core}{trailing}"

        return "".join(rendered)

    @staticmethod
    def _residue_retry_variants(text: str) -> list[str]:
        variants = []
        normalized = text.replace("fit-to-page", "fit to page")
        normalized = normalized.replace("per-format", "per format")
        normalized = normalized.replace("Open-Source", "Open Source")
        normalized = normalized.replace("open-source", "open source")
        normalized = normalized.replace("Cross-Platform", "Cross Platform")
        normalized = normalized.replace("cross-platform", "cross platform")
        normalized = normalized.replace("CMake-based", "CMake based")
        normalized = normalized.replace("header-and-source", "header and source")
        normalized = normalized.replace("control formula visibility", "hide formulas")
        normalized = normalized.replace("Control formula visibility", "Hide formulas")
        normalized = normalized.replace("Lock individual cells", "Protect cells by locking individual cells")
        normalized = normalized.replace("lock individual cells", "protect cells by locking individual cells")
        normalized = normalized.replace("export styled workbooks", "export formatted workbooks")
        normalized = normalized.replace(
            "Library for Word Document Conversion",
            "Software library for converting Word documents",
        )
        normalized = normalized.replace(
            "library for Word Document Conversion",
            "software library for converting Word documents",
        )
        if normalized != text:
            variants.append(normalized)
        if re.match(r"^\s*Set\b", normalized):
            variants.append(re.sub(r"^\s*Set\b", "Configure", normalized, count=1))
        if re.match(r"^\s*set\b", normalized):
            variants.append(re.sub(r"^\s*set\b", "configure", normalized, count=1))
        return [variant for idx, variant in enumerate(variants) if variant and variant not in variants[:idx]]

    def _translate_core_with_residue_variants(
        self,
        backend,
        core: str,
        source_lang: str,
        target_lang: str,
        stats: TranslationStats,
    ) -> str:
        if hasattr(backend, "translate_with_token_counts"):
            translations, input_tokens, output_tokens = backend.translate_with_token_counts(
                [core], source_lang, target_lang
            )
            stats.tokens_input += input_tokens
            stats.tokens_output += output_tokens
        else:
            translations = backend.translate([core], source_lang, target_lang)
            stats.tokens_input += estimate_token_count(core)
            stats.tokens_output += sum(estimate_token_count(t) for t in translations)

        candidate = translations[0] if translations else core
        if (
            not self._is_effectively_untranslated(core, candidate)
            and self._english_source_residue_count(core, candidate) == 0
        ):
            return candidate

        for variant in self._residue_retry_variants(core):
            logger.info(
                "Retrying residue-prone short phrase with normalized source variant "
                f"(target={target_lang})"
            )
            if hasattr(backend, "translate_with_token_counts"):
                retry_translations, input_tokens, output_tokens = backend.translate_with_token_counts(
                    [variant], source_lang, target_lang
                )
                stats.tokens_input += input_tokens
                stats.tokens_output += output_tokens
            else:
                retry_translations = backend.translate([variant], source_lang, target_lang)
                stats.tokens_input += estimate_token_count(variant)
                stats.tokens_output += sum(estimate_token_count(t) for t in retry_translations)
            retry_candidate = retry_translations[0] if retry_translations else ""
            if retry_candidate and self._english_source_residue_count(variant, retry_candidate) == 0:
                return retry_candidate
        return candidate

    def translate_to_language(
        self,
        site_id: str,
        site_profile,
        doc,
        segments: list,
        source_lang: str,
        target_lang: str,
        force: bool,
        stats: TranslationStats,
        retry_feedback: str | None = None,
        retry_count: int = 0,
        model_id_override: str | None = None,
        tm_write_buffer: list | None = None,
    ) -> str:
        """
        Translate document to a specific target language.

        INT-01: Returns translated content without writing.
        INT-02: Retry feedback integration and temperature variation.
        """
        engine = self._engine

        # Create translation map: segment text -> translation
        translations = {}
        segments_to_translate = []

        # Create extractor instance for inline formatting restoration
        extractor = SegmentExtractor(site_profile, terminology_manager=engine.terminology_manager)

        # CT2-002: Get model_id with language-aware selection
        model_id = model_id_override or engine._get_model_id(
            site_profile, src_lang=source_lang, tgt_lang=target_lang
        )

        # Step 1: TM lookup (unless force=True)
        if not force:
            # Batch TM lookup: L1+L2 per-request, then L3 for all misses in one GPU forward pass.
            # RC-4 FIX preserved: frontmatter segments use use_semantic=False (no L3).
            from ..tm.models import LookupRequest as _TMLookupRequest  # noqa: PLC0415

            def _is_fm_seg(seg):
                return bool(
                    seg.context
                    and hasattr(seg.context, "context_type")
                    and str(seg.context.context_type) == "SegmentContextType.FRONTMATTER"
                )

            def _make_tm_req(seg):
                return _TMLookupRequest(
                    site_id=site_id,
                    src_lang=source_lang,
                    tgt_lang=target_lang,
                    text=seg.source_text,
                    context=str(seg.context) if seg.context else None,
                )

            _fm_idx = [i for i, s in enumerate(segments) if _is_fm_seg(s)]
            _body_idx = [i for i, s in enumerate(segments) if not _is_fm_seg(s)]
            _tm_batch_results: list = [None] * len(segments)
            if _fm_idx:
                _fm_res = engine.tm.batch_lookup(
                    [_make_tm_req(segments[i]) for i in _fm_idx], use_semantic=False
                )
                for _bi, _br in zip(_fm_idx, _fm_res):
                    _tm_batch_results[_bi] = _br
            if _body_idx:
                _body_res = engine.tm.batch_lookup(
                    [_make_tm_req(segments[i]) for i in _body_idx], use_semantic=True
                )
                for _bi, _br in zip(_body_idx, _body_res):
                    _tm_batch_results[_bi] = _br

            for idx, segment in enumerate(segments, 1):
                # TMO-03: Build lookup context for override filtering
                lookup_context = {
                    "target_lang": target_lang,
                }
                if segment.context:
                    if (
                        hasattr(segment.context, "frontmatter_key")
                        and segment.context.frontmatter_key
                    ):
                        lookup_context["frontmatter_key"] = segment.context.frontmatter_key
                    if hasattr(segment.context, "context_type"):
                        lookup_context["context_type"] = str(segment.context.context_type)

                stats.total_lookups += 1

                # RC-4 FIX applied in pre-batch split above (frontmatter → use_semantic=False).
                tm_result = _tm_batch_results[idx - 1]

                if tm_result.hit:
                    restored = self._restore_placeholders(tm_result.translation or "", segment)
                    translations[segment.id] = restored
                    stats.tm_hits += 1

                    if tm_result.source == "l1_cache":
                        stats.l1_hits += 1
                    elif tm_result.source == "l2_exact":
                        stats.l2_hits += 1
                    elif tm_result.source == "l3_semantic":
                        _ctx_gate_rejected = False
                        try:
                            _tm_cfg = engine.config.get_config().get("tm_defaults", {})
                            if _tm_cfg.get("l3_context_gate_enabled", False):
                                _ctx_threshold = float(
                                    _tm_cfg.get("l3_context_similarity_threshold", 0.50)
                                )
                                _hit_ctx = (
                                    tm_result.candidates[0].context
                                    if tm_result.candidates and tm_result.candidates[0].context
                                    else ""
                                )
                                _seg_ctx = str(segment.context) if segment.context else ""
                                if _hit_ctx and _seg_ctx and engine._l3 is not None:
                                    _ctx_sim = engine._l3.context_similarity(_hit_ctx, _seg_ctx)
                                    if _ctx_sim < _ctx_threshold:
                                        logger.debug(
                                            "L3 context_mismatch: sim=%.2f < %.2f, rejecting hit for %s",
                                            _ctx_sim,
                                            _ctx_threshold,
                                            segment.id,
                                        )
                                        _ctx_gate_rejected = True
                                        del translations[segment.id]
                                        stats.tm_hits -= 1
                        except Exception:
                            pass
                        if not _ctx_gate_rejected:
                            stats.l3_hits += 1

                    # Track cached tokens
                    backend = engine.model_loader.get_tokenizer_for_counting(model_id)
                    if backend and hasattr(backend, "get_token_count"):
                        cached_input_tokens = backend.get_token_count(segment.source_text)
                        cached_output_tokens = backend.get_token_count(tm_result.translation)
                        stats.token_count_method = "actual"
                    else:
                        cached_input_tokens = estimate_token_count(segment.source_text)
                        cached_output_tokens = estimate_token_count(tm_result.translation)
                        stats.token_count_method = "estimated"

                    stats.tokens_cached += cached_input_tokens + cached_output_tokens

                    progress = get_progress_tracker()
                    if progress:
                        progress.cache_hit(
                            layer=tm_result.source.split("_")[0] if tm_result.source else "l1"
                        )
                        progress.segments_completed(1)
                else:
                    segments_to_translate.append(segment)
                    progress = get_progress_tracker()
                    if progress:
                        progress.cache_miss()

                # SR-02: Check for shutdown every 10 segments
                if idx % 10 == 0 and engine._check_shutdown():
                    from .exceptions import ShutdownRequested

                    raise ShutdownRequested(
                        file_path=str(doc.file_path) if hasattr(doc, "file_path") else "",
                        segments_completed=idx,
                    )

        else:
            # Force mode: translate everything
            logger.info(
                f"Force retranslate enabled: bypassing cache lookup for {len(segments)} segments "
                f"({source_lang} -> {target_lang})"
            )
            segments_to_translate = segments

            progress = get_progress_tracker()
            if progress:
                for _ in segments:
                    progress.cache_miss()

        # Step 2: Translate new segments via model
        if segments_to_translate:
            logger.info(
                f"Translating {len(segments_to_translate)} new segments "
                f"from {source_lang} to {target_lang}"
                + (f" (retry {retry_count} with feedback)" if retry_count > 0 else "")
            )

            with engine._model_lock:
                backend = engine.model_loader.load_model(model_id)
            stats.model_used = model_id

            texts = [seg.source_text for seg in segments_to_translate]

            # INT-02: Retry feedback — only for LLM backends
            if retry_feedback:
                from ..model_runtime.llm_backend import LLMModelBackend

                if isinstance(backend, LLMModelBackend):
                    texts_with_feedback = [
                        f"{retry_feedback}\n\nSOURCE TEXT:\n{text}" for text in texts
                    ]
                    texts = texts_with_feedback
                    logger.debug(f"Applied retry feedback to {len(texts)} segments")
                else:
                    logger.debug(
                        f"Skipping retry feedback injection for non-LLM backend "
                        f"{type(backend).__name__} -- MT models cannot follow instructions"
                    )

            # INT-02: Retry temperature variation — increase sampling diversity on retries
            base_temperature = 0.7
            if retry_count > 0:
                temperature_increment = 0.1
                max_temperature = 1.0
                temperature = min(
                    base_temperature + (retry_count * temperature_increment), max_temperature
                )
                # TC-BUGFIX-A: Apply temperature to LLM backend for retry diversity
                _provider = getattr(getattr(backend, "_provider", None), "_config", None)
                if _provider is not None and hasattr(_provider, "temperature"):
                    _provider.temperature = temperature
                    logger.debug(
                        f"Retry {retry_count}: applied temperature={temperature} to LLM backend"
                    )
                else:
                    logger.debug(
                        f"Retry {retry_count}: temperature={temperature} (backend does not support temperature)"
                    )
            else:
                temperature = base_temperature
            try:
                progress = get_progress_tracker()
                batch_start_time = time.time()
                if progress:
                    batches_for_lang = math.ceil(len(segments_to_translate) / engine.batch_size)
                    progress.add_batches(batches_for_lang)
                    progress.batch_started(len(segments_to_translate))

                # MSP-02: Translate with multiline structure preservation
                translated_texts = self._translate_with_multiline_support(
                    backend=backend,
                    segments=segments_to_translate,
                    texts=texts,
                    source_lang=source_lang,
                    target_lang=target_lang,
                    stats=stats,
                )

                # SR-02: Check for shutdown after batch translation
                if engine._check_shutdown():
                    from .exceptions import ShutdownRequested

                    raise ShutdownRequested(
                        file_path=str(doc.file_path) if hasattr(doc, "file_path") else "",
                        segments_completed=len(translations),
                    )

                # Store results in translations map and TM
                for seg_idx, (segment, translation) in enumerate(
                    zip(segments_to_translate, translated_texts, strict=False), 1
                ):
                    translation = self._restore_placeholders(translation, segment)
                    translations[segment.id] = translation
                    stats.translated_segments += 1
                    stats.words_translated += len(segment.source_text.split())

                    store_context = {
                        "target_lang": target_lang,
                    }
                    if segment.context:
                        if (
                            hasattr(segment.context, "frontmatter_key")
                            and segment.context.frontmatter_key
                        ):
                            store_context["frontmatter_key"] = segment.context.frontmatter_key
                        if hasattr(segment.context, "context_type"):
                            store_context["context_type"] = str(segment.context.context_type)

                    if engine.cache_write_mode != "never":
                        if engine.cache_write_mode == "always":
                            force_update = True
                        else:
                            force_update = force

                        _tm_entry = dict(
                            site_id=site_id,
                            src_lang=source_lang,
                            tgt_lang=target_lang,
                            text=segment.source_text,
                            translation=translation,
                            context=str(segment.context) if segment.context else None,
                            metadata={
                                "model": model_id,
                                "source_file": str(doc.file_path)
                                if hasattr(doc, "file_path")
                                else None,
                            },
                            store_context=store_context,
                            force_update=force_update,
                        )
                        if tm_write_buffer is not None:
                            tm_write_buffer.append(_tm_entry)
                        else:
                            engine.tm.store(**_tm_entry)
                        stats.tm_entries_stored += 1

                    if seg_idx % 10 == 0 and engine._check_shutdown():
                        from .exceptions import ShutdownRequested

                        raise ShutdownRequested(
                            file_path=str(doc.file_path) if hasattr(doc, "file_path") else "",
                            segments_completed=len(translations),
                        )

                batch_duration = time.time() - batch_start_time
                if progress:
                    progress.batch_completed(len(segments_to_translate))
                    progress.segments_completed(
                        len(segments_to_translate), duration_s=batch_duration
                    )
                    progress.add_tokens(
                        tokens_in=stats.tokens_input,
                        tokens_out=stats.tokens_output,
                        method=getattr(stats, "token_count_method", "actual"),
                    )

            except Exception as e:
                logger.error(f"Model translation failed: {e}")
                progress = get_progress_tracker()
                if progress:
                    for _ in range(len(segments_to_translate)):
                        progress.segment_failed()
                raise RuntimeError(f"Translation failed: {e}")

        # Step 3: Reconstruct document (AST-based or legacy)
        use_ast = getattr(site_profile.body, "use_ast_body_reconstruction", False)

        if use_ast:
            logger.info("Using AST-based body reconstruction for translation")
            ast_body_rendered = False
            try:
                translated_body = self._translate_body_ast(
                    doc,
                    target_lang,
                    site_profile,
                    stats,
                    segments=segments,
                    translations=translations,
                )
                ast_body_rendered = True

                _fm_reconstructor = MarkdownReconstructor(site_profile)
                translated_frontmatter = _fm_reconstructor.reconstruct_frontmatter(
                    doc.frontmatter, translations, target_lang
                )

                from .reconstructor import YAMLFormatter

                yaml_formatter = YAMLFormatter()
                frontmatter_yaml = yaml_formatter.format_frontmatter(translated_frontmatter)

                # Structural invariant: verify every frontmatter segment was applied
                _fm_not_applied = []
                for _seg in segments:
                    if (
                        _seg.context
                        and hasattr(_seg.context, "context_type")
                        and str(_seg.context.context_type) == "SegmentContextType.FRONTMATTER"
                        and _seg.id in translations
                    ):
                        _fm_key = _seg.context.frontmatter_key
                        _expected = translations[_seg.id]
                        _actual = yaml_formatter.get_nested_value(translated_frontmatter, _fm_key)
                        if _actual != _expected:
                            _fm_not_applied.append((_fm_key, _expected[:40], str(_actual)[:40]))
                if _fm_not_applied:
                    logger.warning(
                        "frontmatter_segment_not_applied: keys=%s",
                        [k for k, _, _ in _fm_not_applied],
                    )

                # RC-3 FIX: Verify frontmatter keys were not translated
                _source_keys = set(doc.frontmatter.keys())
                _out_data = self._parse_formatted_frontmatter(frontmatter_yaml)
                _out_keys = set(_out_data.keys()) if isinstance(_out_data, dict) else set()
                if _source_keys != _out_keys:
                    _diff = _source_keys ^ _out_keys
                    raise ValueError(
                        f"Frontmatter key integrity check failed after translation. "
                        f"Mismatched keys: {_diff}"
                    )

                translated_content = f"{frontmatter_yaml}\n{translated_body}"
                logger.info("AST Translation: Successfully reconstructed document")

            except TranslationRetryableError:
                raise
            except Exception as e:
                if ast_body_rendered:
                    logger.error(
                        "AST reconstruction failed after body rendering; refusing legacy fallback "
                        "because the document may already be partially mutated",
                        exc_info=True,
                    )
                    raise
                logger.error(f"AST reconstruction failed: {e}", exc_info=True)
                logger.warning("AST translation failed, falling back to legacy reconstruction")
                use_ast = False

        if not use_ast:
            import re as _re_legacy_diag

            _src_ast_text = str(doc.ast) if doc.ast else ""
            _legacy_src_cb = (
                len(_re_legacy_diag.findall(r"^```", _src_ast_text, _re_legacy_diag.MULTILINE)) // 2
            )
            logger.info(
                f"LEGACY DIAG: Source has ~{_legacy_src_cb} code blocks, using legacy MarkdownReconstructor"
            )
            segment_map = {}
            for segment in segments:
                if segment.context and segment.context.node_id:
                    segment_map[segment.context.node_id] = segment.id

            # TC-TBL-012 / Layer 3: Protect markdown tables before passing to legacy
            # MarkdownReconstructor. The legacy path sends raw markdown to the model;
            # if the model sees pipe characters it generates tables with 3×+ extra rows.
            # Solution: replace each table block with a placeholder, reconstruct without
            # table content, then restore original tables from placeholders.
            _TABLE_BLOCK_RE = _re_legacy_diag.compile(
                r"((?:^[ \t]*\|[^\n]+\n)+)",
                _re_legacy_diag.MULTILINE,
            )
            _table_placeholder_map: dict[str, str] = {}
            _table_counter = [0]

            def _replace_table(m: "_re_legacy_diag.Match") -> str:  # type: ignore[name-defined]
                key = f"\x00TABLE_{_table_counter[0]}\x00"
                _table_placeholder_map[key] = m.group(0)
                _table_counter[0] += 1
                return key

            # Protect Hugo shortcodes first — before code blocks so that shortcodes
            # inside prose paragraphs are hidden from the model.  Pattern covers both
            # {{< ... >}} (regular) and {{% ... %}} (markdown) shortcodes.  Each tag is
            # protected individually; multi-line block shortcodes (open + close) are
            # captured as two separate tokens, which restores cleanly.
            _SHORTCODE_LEGACY_RE = _re_legacy_diag.compile(
                r"(\{\{[<%][^\n]*?[>%]\}\})"
            )
            _shortcode_placeholder_map: dict[str, str] = {}
            _shortcode_counter = [0]

            def _replace_shortcode(m: "_re_legacy_diag.Match") -> str:  # type: ignore[name-defined]
                key = f"\x00SHORTCODE_{_shortcode_counter[0]}\x00"
                _shortcode_placeholder_map[key] = m.group(0)
                _shortcode_counter[0] += 1
                return key

            # Protect fenced code blocks after shortcodes. Models in the legacy
            # path drop opening ``` fences, leaving code as plain text. Code blocks must
            # be protected so that pipe characters inside code blocks are not
            # mistakenly matched by the table regex above.
            _CODE_BLOCK_RE = _re_legacy_diag.compile(
                r"(```[^\n]*\n(?:(?!```)[\s\S])*?```[ \t]*)",
                _re_legacy_diag.MULTILINE,
            )
            _code_placeholder_map: dict[str, str] = {}
            _code_counter = [0]

            def _replace_code(m: "_re_legacy_diag.Match") -> str:  # type: ignore[name-defined]
                key = f"\x00CODE_{_code_counter[0]}\x00"
                _code_placeholder_map[key] = m.group(0)
                _code_counter[0] += 1
                return key

            _raw_for_legacy = ""
            if getattr(doc, "source_path", None):
                try:
                    from pathlib import Path as _Path
                    _raw_for_legacy = _Path(doc.source_path).read_text(
                        encoding=getattr(doc, "encoding", None) or "utf-8",
                        errors="replace",
                    )
                except OSError:
                    pass

            # Protect link URLs so relative paths like ../../path/ are not
            # corrupted by the model.  Only the URL portion is replaced; the
            # link text [text] is still translated.  Applied AFTER code block
            # protection so that URLs inside code blocks are already hidden.
            _LINK_URL_RE = _re_legacy_diag.compile(
                r"(\[(?:[^\[\]]*)\])\(([^)]+)\)"
            )
            _link_url_map: dict[str, str] = {}
            _link_counter = [0]

            def _replace_link_url(m: "_re_legacy_diag.Match") -> str:  # type: ignore[name-defined]
                key = f"\x00LINK_{_link_counter[0]}\x00"
                _link_url_map[key] = m.group(2)
                _link_counter[0] += 1
                # Keep [text] intact; only the URL inside (...) is replaced
                return m.group(1) + f"({key})"

            # Apply shortcode protection first, then code blocks, link URLs, then tables
            _protected_raw = _SHORTCODE_LEGACY_RE.sub(_replace_shortcode, _raw_for_legacy)
            if _shortcode_placeholder_map:
                logger.info(
                    f"SHORTCODE-PROTECT: shielded {len(_shortcode_placeholder_map)} shortcode(s) "
                    f"from legacy reconstruction to prevent shortcode corruption"
                )

            _protected_raw = _CODE_BLOCK_RE.sub(_replace_code, _protected_raw)
            if _code_placeholder_map:
                logger.info(
                    f"CODE-PROTECT: shielded {len(_code_placeholder_map)} code block(s) "
                    f"from legacy reconstruction to prevent fence dropping"
                )

            _protected_raw = _LINK_URL_RE.sub(_replace_link_url, _protected_raw)
            if _link_url_map:
                logger.info(
                    f"LINK-PROTECT: shielded {len(_link_url_map)} link URL(s) "
                    f"from legacy reconstruction to prevent path corruption"
                )

            if _TABLE_BLOCK_RE.search(_protected_raw):
                _protected_content = _TABLE_BLOCK_RE.sub(_replace_table, _protected_raw)
            else:
                _protected_content = _protected_raw

            if _table_placeholder_map:
                logger.info(
                    f"TABLE-PROTECT: shielded {len(_table_placeholder_map)} table(s) "
                    f"from legacy reconstruction to prevent row-count corruption"
                )

            # Temporarily swap doc.content for the protected version
            _original_doc_content = getattr(doc, "content", None)
            if (_shortcode_placeholder_map or _code_placeholder_map or _table_placeholder_map) and hasattr(doc, "content"):
                doc.content = _protected_content

            reconstructor = MarkdownReconstructor(site_profile)
            translated_doc = reconstructor.reconstruct_document(
                doc, translations, target_lang, segment_map=segment_map
            )

            translated_content = str(translated_doc)

            # Restore protected tables, link URLs, code blocks, then shortcodes
            if _table_placeholder_map:
                for _key, _original_table in _table_placeholder_map.items():
                    translated_content = translated_content.replace(_key, _original_table)
            if _link_url_map:
                for _key, _original_url in _link_url_map.items():
                    translated_content = translated_content.replace(_key, _original_url)
            if _code_placeholder_map:
                for _key, _original_code in _code_placeholder_map.items():
                    translated_content = translated_content.replace(_key, _original_code)
            if _shortcode_placeholder_map:
                for _key, _original_sc in _shortcode_placeholder_map.items():
                    translated_content = translated_content.replace(_key, _original_sc)
            # Restore doc.content
            if (_shortcode_placeholder_map or _code_placeholder_map or _table_placeholder_map) and hasattr(doc, "content") and _original_doc_content is not None:
                doc.content = _original_doc_content

        stats.tokens_total = stats.tokens_cached + stats.tokens_input + stats.tokens_output

        return translated_content

    @staticmethod
    def _parse_formatted_frontmatter(frontmatter_yaml: str) -> dict:
        """Parse YAMLFormatter output and require Hugo frontmatter delimiters."""
        import re

        import yaml

        match = re.match(r"^---\s*\n(.*?)\n?---\s*(?:\n)?$", frontmatter_yaml, re.DOTALL)
        if not match:
            raise ValueError("Frontmatter key integrity: missing YAML frontmatter delimiters")

        try:
            data = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError as exc:
            raise ValueError(f"Frontmatter key integrity: YAML parse failed: {exc}") from exc

        if not isinstance(data, dict):
            raise ValueError(
                f"Frontmatter key integrity: parsed frontmatter is not a mapping "
                f"(got {type(data).__name__})"
            )
        return data

    def _translate_body_ast(
        self,
        doc,
        target_lang: str,
        site_profile,
        stats: TranslationStats,
        segments: list | None = None,
        translations: dict[str, str] | None = None,
    ) -> str:
        """Translate document body using AST-based node-addressed translation."""
        engine = self._engine

        from .extractor import TextUnitExtractor
        from .reconstructor import ASTRenderer

        try:
            model_id = engine._get_model_id(site_profile, tgt_lang=target_lang)
            with engine._model_lock:
                mt_model = engine.model_loader.load_model(model_id)

            terminology_file = Path("config/terminology/aspose_terms.txt")

            lang_detection_config = engine._load_language_detection_config()
            script_validation_config = lang_detection_config.get("script_validation", {})
            script_validation_thresholds = (
                script_validation_config.get("thresholds", {})
                if script_validation_config.get("enabled", True)
                else None
            )

            _batch_purity_skip_langs = None
            if engine.config:
                try:
                    if hasattr(engine.config, "get_config"):
                        _te_cfg = engine.config.get_config().get("translation_engine", {})
                        _batch_purity_skip_langs = (
                            _te_cfg.get("batch_purity_skip_langs") if _te_cfg else None
                        )
                    elif hasattr(engine.config, "global_config"):
                        _te_cfg = getattr(engine.config.global_config, "translation_engine", None)
                        if _te_cfg:
                            _batch_purity_skip_langs = (
                                _te_cfg.get("batch_purity_skip_langs")
                                if isinstance(_te_cfg, dict)
                                else getattr(_te_cfg, "batch_purity_skip_langs", None)
                            )
                except Exception:
                    pass

            extractor = TextUnitExtractor(
                segmentation_strategy=site_profile.body.ast_segmentation_strategy,
                terminology_file=terminology_file if terminology_file.exists() else None,
                mt_model=mt_model,
                preserve_patterns=site_profile.body.preserve_patterns,
                site_profile=site_profile,
                batch_stats_tracker=engine.batch_stats_tracker,
                fasttext_detector=engine.fasttext_detector,
                similarity_tracker=engine.similarity_tracker,
                script_validation_thresholds=script_validation_thresholds,
                batch_purity_skip_langs=_batch_purity_skip_langs,
            )

            logger.info(
                f"AST Translation: Extracting TextUnits from AST (strategy: {site_profile.body.ast_segmentation_strategy})"
            )
            plan = extractor.extract_from_ast(doc.ast, frontmatter=doc.frontmatter)

            total_units = len(plan.units)
            translatable_units = len([u for u in plan.units if not u.do_not_translate])
            protected_units = len([u for u in plan.units if u.do_not_translate])
            logger.info(
                f"AST Translation: Extracted {total_units} units ({translatable_units} translatable, {protected_units} protected)"
            )

            _code_block_units = [u for u in plan.units if u.kind == "block_code"]
            logger.info(
                f"AST DIAG: {len(_code_block_units)} code block TextUnits extracted (do_not_translate={sum(1 for u in _code_block_units if u.do_not_translate)})"
            )

            stats.ast_translation_enabled = True
            stats.ast_units_extracted = total_units
            stats.ast_units_translatable = translatable_units
            stats.ast_units_protected = protected_units

            # E2E FIX: Reuse existing translations if available
            reused_count = 0
            not_matched_count = 0
            if segments and translations:
                import re

                def strip_markdown(text: str) -> str:
                    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
                    text = re.sub(r"\*(.+?)\*", r"\1", text)
                    text = re.sub(r"`(.+?)`", r"\1", text)
                    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
                    return text

                from .extractor.placeholder_manager import PlaceholderManager

                pm = PlaceholderManager()
                preserve_patterns = site_profile.body.preserve_patterns or []

                source_to_translation = {}
                for segment in segments:
                    if segment.id in translations and translations[segment.id]:
                        normalized_source = strip_markdown(segment.source_text)
                        protected_source, _ = pm.protect(normalized_source, preserve_patterns)
                        source_to_translation[protected_source] = translations[segment.id]

                logger.debug(
                    f"E2E DEBUG: Built mapping with {len(source_to_translation)} segment translations"
                )
                logger.debug(
                    f"E2E DEBUG: First 3 normalized segment source_texts: {list(source_to_translation.keys())[:3]}"
                )

                unmatched_units = []
                for unit in plan.units:
                    if not unit.do_not_translate and unit.source_text:
                        normalized_unit_source = strip_markdown(unit.source_text)
                        protected_unit_source, _ = pm.protect(
                            normalized_unit_source, preserve_patterns
                        )

                        if protected_unit_source in source_to_translation:
                            unit.translated_text = source_to_translation[protected_unit_source]
                            reused_count += 1
                        else:
                            not_matched_count += 1
                            unmatched_units.append(unit)
                            if not_matched_count <= 5:
                                logger.debug(
                                    f"E2E DEBUG: Unmatched unit [{unit.kind}]: normalized={normalized_unit_source[:80]}"
                                )

                logger.info(
                    f"AST Translation: Reused {reused_count} existing translations, {not_matched_count} units not matched"
                )

                if unmatched_units:
                    kind_counts = {}
                    for u in unmatched_units:
                        kind_counts[u.kind] = kind_counts.get(u.kind, 0) + 1
                    logger.debug(f"E2E DEBUG: Unmatched unit kinds: {kind_counts}")

            # Step 2a: ContentTypeRouter — pre-translate LLM-routed units
            # before the MT batch so batch_translate_units() skips them.
            try:
                from .content_type_router import ContentTypeRouter as _CTR
                from ..model_runtime.llm_backend import LLMModelBackend as _LLMBackend

                _te_cfg_ctr = (
                    engine.config.get_config().get("translation_engine", {})
                    if hasattr(engine.config, "get_config")
                    else {}
                )
                _ctr_config = _te_cfg_ctr.get("content_type_routing", {})
                if _ctr_config:
                    _router = _CTR(_ctr_config)
                    _llm_units = []
                    _llm_hints = []
                    _llm_model_id = None
                    for _u in plan.units:
                        if _u.do_not_translate or _u.translated_text:
                            continue
                        _decision = _router.route(
                            _u,
                            field_name=_u.metadata.get("frontmatter_key", "") if _u.metadata else "",
                        )
                        if _decision.model_id:
                            _llm_units.append(_u)
                            _llm_hints.append(_decision.context_hint)
                            if _llm_model_id is None:
                                _llm_model_id = _decision.model_id

                    if _llm_units and _llm_model_id:
                        logger.info(
                            f"ContentTypeRouter: {len(_llm_units)}/{len(plan.units)} units "
                            f"routed to LLM backend before MT batch"
                        )
                        try:
                            _llm_backend = engine.model_loader.load_model(_llm_model_id)
                            _file_ctx = (
                                _LLMBackend._derive_file_context(str(doc.output_path))
                                if hasattr(doc, "output_path") and doc.output_path
                                else {}
                            )
                            for _llm_unit, _hint in zip(_llm_units, _llm_hints):
                                _llm_result = _llm_backend.translate_with_context(
                                    [_llm_unit.source_text],
                                    site_profile.default_source_lang,
                                    target_lang,
                                    context_hint=_hint,
                                    file_context=_file_ctx,
                                )
                                if _llm_result and _llm_result[0]:
                                    _llm_unit.translated_text = _llm_result[0]
                                    # TC-HT-003: tag units the LLM backend
                                    # rejected as prompt-echo/refusal and
                                    # passed through as source text.
                                    if 0 in getattr(_llm_backend, "last_reject_reasons", {}):
                                        if _llm_unit.metadata is None:
                                            _llm_unit.metadata = {}
                                        _llm_unit.metadata[
                                            "llm_passthrough_reason"
                                        ] = "llm_echo_reject"
                        except Exception as _llm_err:
                            logger.warning(
                                f"ContentTypeRouter LLM pre-translate failed "
                                f"({type(_llm_err).__name__}): {_llm_err}; "
                                f"{len(_llm_units)} units marked as English passthrough "
                                f"(NOT routed to MT — MT output for short API descriptions "
                                f"is worse than keeping English)"
                            )
                            for _u in _llm_units:
                                if not _u.translated_text:
                                    _u.translated_text = _u.source_text
                                    if _u.metadata is None:
                                        _u.metadata = {}
                                    _u.metadata[
                                        "llm_passthrough_reason"
                                    ] = "professionalize_llm_unavailable"
            except Exception as _ctr_err:
                logger.debug(f"ContentTypeRouter init skipped: {_ctr_err}")

            # Step 2b: Translate remaining units (MT) with batching + fallback.
            # Units that were pre-translated by the LLM step already have
            # translated_text set and are skipped by batch_translate_units().
            batch_size = site_profile.body.ast_batch_size
            units_needing_translation = [
                u for u in plan.units if not u.do_not_translate and not u.translated_text
            ]
            logger.info(
                f"AST Translation: Translating {len(units_needing_translation)} new units via MT (batch_size: {batch_size}, reused: {reused_count})"
            )

            batch_calls_before = getattr(extractor, "_batch_calls", 0)
            fallbacks_before = getattr(extractor, "_individual_fallbacks", 0)

            translated_units = extractor.batch_translate_units(
                plan.units,
                mt_model,
                site_profile.default_source_lang,
                target_lang,
                batch_size=batch_size,
            )

            _cb_after_batch = [u for u in translated_units if u.kind == "block_code"]
            _cb_with_content = [
                u for u in _cb_after_batch if u.translated_text and u.translated_text.strip()
            ]
            logger.info(
                f"AST DIAG: After batch translate: {len(_cb_after_batch)} code block units, {len(_cb_with_content)} with content"
            )

            # TC-SAS-01: Detect translatable units the model returned unchanged (source-lang leakage).
            # do_not_translate=True units are intentionally excluded — they are preserved YAML
            # passthrough fields, code blocks, and shortcodes that must not be translated.
            # TC-SAS-FIX-016: Merge global + site-specific config; site wins.
            # SiteProfile.translation_engine was previously silently dropped by Pydantic
            # (no field declared) so site overrides were never applied.
            _te_cfg_sas_global = (
                engine.config.get_config().get("translation_engine", {})
                if hasattr(engine.config, "get_config")
                else {}
            )
            _te_cfg_sas_site = getattr(site_profile, "translation_engine", None) or {}
            _te_cfg_sas = {**_te_cfg_sas_global, **_te_cfg_sas_site}
            _sas_min_len = int(_te_cfg_sas.get("same_as_source_min_length", 10))
            _sas_tolerance = float(_te_cfg_sas.get("same_as_source_tolerance", 0.0))
            _translatable_count = sum(1 for u in translated_units if not u.do_not_translate)
            _sas_units = [
                u for u in translated_units
                if not u.do_not_translate
                and u.source_text
                and u.translated_text is not None
                and u.translated_text.strip() == u.source_text.strip()
                and len(u.source_text.strip()) > _sas_min_len
                # TC-TBL-012 / Layer 2: Exclude table cells from SAS ratio.
                # A table cell the model fails to translate stays as English text —
                # bad for quality but handled by Gate 15 / purity check. Counting
                # them toward SAS ratio triggers legacy fallback which corrupts table
                # structure far more severely (3×+ row count expansion).
                and u.kind != TextUnitKind.TABLE_CELL_TEXT
            ]
            if _sas_units:
                _sas_ratio = len(_sas_units) / _translatable_count if _translatable_count > 0 else 0.0
                logger.warning(
                    f"TC-SAS-01: {len(_sas_units)}/{_translatable_count} translatable units returned "
                    f"same-as-source (ratio={_sas_ratio:.1%}, tolerance={_sas_tolerance:.1%}) "
                    f"-- source text will appear in output."
                )
                if _sas_ratio > _sas_tolerance:
                    # TC-TBL-012 / Layer 2: Suppress legacy fallback for table-containing
                    # documents. MarkdownReconstructor corrupts tables (3×+ row expansion)
                    # when raw markdown pipe chars are sent to the model. A partial AST
                    # result (some cells in source language) is far better than structurally
                    # corrupted tables. Only suppress if the document actually has tables.
                    _ast_has_tables = False
                    if doc.ast:
                        from .parser.ast_nodes import NodeType as _NT_SAS

                        def _check_ast_tables(nodes: list) -> bool:
                            for _n in nodes:
                                if getattr(_n, "type", None) == _NT_SAS.TABLE:
                                    return True
                                if getattr(_n, "children", None) and _check_ast_tables(_n.children):
                                    return True
                            return False

                        _ast_nodes = doc.ast if isinstance(doc.ast, list) else [doc.ast]
                        _ast_has_tables = _check_ast_tables(_ast_nodes)

                    if _ast_has_tables:
                        logger.warning(
                            f"TC-SAS-01: ratio {_sas_ratio:.1%} > {_sas_tolerance:.1%} but "
                            f"document contains tables — suppressing legacy fallback to preserve "
                            f"table structure. Proceeding with partial AST result "
                            f"({len(_sas_units)} untranslated units, "
                            f"{len(_sas_units)}/{_translatable_count})."
                        )
                    else:
                        from .exceptions import TranslationIncomplete
                        raise TranslationIncomplete(
                            f"TC-SAS-01: same-as-source ratio {_sas_ratio:.1%} exceeds tolerance "
                            f"{_sas_tolerance:.1%} ({len(_sas_units)}/{_translatable_count} units unchanged)",
                            missing_count=len(_sas_units),
                            total_count=_translatable_count,
                            ratio=_sas_ratio,
                            tolerance=_sas_tolerance,
                        )

            # AGENT B-7.3: Check batch-level purity failures
            batch_stats = extractor.batch_stats
            if batch_stats.get("language_purity_failures", 0) > 0 and target_lang not in (
                _batch_purity_skip_langs or []
            ) and not getattr(engine, '_force_accept', False):
                # Use outer-batch counters so reactive sub-batch splitting doesn't
                # artificially inflate the failure rate.
                total_outer_batches = batch_stats.get("total_outer_batches", 0)
                failed_outer_batches = batch_stats.get("failed_outer_batches", 0)
                if total_outer_batches > 0 and failed_outer_batches > 0:
                    purity_failure_rate = failed_outer_batches / total_outer_batches

                    if purity_failure_rate > 0.10:
                        logger.error(
                            f"HIGH PURITY FAILURE RATE: {purity_failure_rate:.1%} of outer batches failed "
                            f"language validation. Blocking write to prevent corruption. "
                            f"Stats: {failed_outer_batches}/{total_outer_batches} outer batches failed."
                        )

                        issues = [
                            ValidationIssue(
                                severity="error",
                                rule="BatchLanguagePurity",
                                message=f"High batch purity failure rate: {purity_failure_rate:.1%} ({failed_outer_batches}/{total_outer_batches} outer batches)",
                                location=str(doc.file_path) if hasattr(doc, "file_path") else None,
                            )
                        ]
                        validation_result = ValidationResult(valid=False, issues=issues)
                        raise TranslationRetryableError(
                            message=f"Batch purity failure rate too high: {purity_failure_rate:.1%}",
                            file_path=str(doc.file_path) if hasattr(doc, "file_path") else "",
                            validation_result=validation_result,
                            retry_feedback=f"Batch language purity check failed for {purity_failure_rate:.1%} of outer batches. Ensure all translated units are in the target language {target_lang}.",
                        )

            empty_units = [
                u
                for u in translated_units
                if not u.do_not_translate
                and (u.translated_text is None or u.translated_text.strip() == "")
                and u.source_text
                and u.source_text.strip() != ""
                and len(u.source_text.strip()) > 2
            ]
            if empty_units:
                all_empty = [
                    u
                    for u in translated_units
                    if not u.do_not_translate
                    and (u.translated_text is None or u.translated_text.strip() == "")
                ]
                if len(all_empty) > len(empty_units):
                    logger.debug(
                        f"Skipped {len(all_empty) - len(empty_units)} empty translations "
                        f"for whitespace/short source text"
                    )

                issues = [
                    ValidationIssue(
                        severity="error",
                        rule="ASTTranslation",
                        message=f"{len(empty_units)} units with substantial source text returned empty translations",
                        location=str(doc.file_path) if hasattr(doc, "file_path") else None,
                    )
                ]
                validation_result = ValidationResult(valid=False, issues=issues)
                raise TranslationRetryableError(
                    message="AST translation produced empty outputs for substantial text",
                    file_path=str(doc.file_path) if hasattr(doc, "file_path") else "",
                    validation_result=validation_result,
                    retry_feedback="All translated segments with substantial source text must return non-empty output.",
                )

            stats.ast_batch_calls = batch_calls_before - batch_calls_before  # intentional reset
            stats.ast_batch_calls = getattr(extractor, "_batch_calls", 0) - batch_calls_before
            stats.ast_individual_fallbacks = (
                getattr(extractor, "_individual_fallbacks", 0) - fallbacks_before
            )

            # Step 3: Apply translations to AST and frontmatter
            logger.info("AST Translation: Applying translations to AST and frontmatter")
            renderer = ASTRenderer()
            renderer.apply_translations(doc.ast, translated_units, frontmatter=doc.frontmatter)

            # P0-D: Placeholder leak = blocking failure
            if renderer.placeholder_leak_count > 0:
                from .exceptions import TranslationIncomplete

                raise TranslationIncomplete(
                    f"PLACEHOLDER_LEAK: {renderer.placeholder_leak_count} unreplaced placeholder token(s) "
                    f"detected after AST reconstruction. File write blocked to prevent stray tokens in output.",
                    missing_count=renderer.placeholder_leak_count,
                    total_count=renderer.placeholder_leak_count,
                    ratio=1.0,
                    tolerance=0.0,
                )

            # TC-MLD-01: Expose missing node count
            stats.ast_missing_nodes = renderer._missing_node_count
            if renderer._missing_node_count > 0:
                total_checked = len(renderer.applied_units) + renderer._missing_node_count
                fallback_ratio = (
                    renderer._missing_node_count / total_checked if total_checked > 0 else 0.0
                )
                _te_cfg_ast01 = (
                    engine.config.get_config().get("translation_engine", {})
                    if hasattr(engine.config, "get_config")
                    else {}
                )
                _tolerance = float(_te_cfg_ast01.get("ast_fallback_node_tolerance", 0.0))
                logger.warning(
                    f"AST Translation: {renderer._missing_node_count}/{total_checked} nodes had no "
                    f"translation unit (ratio={fallback_ratio:.1%}, tolerance={_tolerance:.1%}) "
                    f"-- source text may appear in output."
                )
                if fallback_ratio > _tolerance:
                    from .exceptions import TranslationIncomplete

                    raise TranslationIncomplete(
                        f"AST fallback ratio {fallback_ratio:.1%} exceeds tolerance {_tolerance:.1%} "
                        f"({renderer._missing_node_count}/{total_checked} nodes missing translation unit)",
                        missing_count=renderer._missing_node_count,
                        total_count=total_checked,
                        ratio=fallback_ratio,
                        tolerance=_tolerance,
                    )

            # Step 4: Render to Markdown
            logger.info("AST Translation: Rendering AST to Markdown")
            translated_body = renderer.render_to_markdown(doc.ast)

            import re as _re_diag

            _rendered_cb = len(_re_diag.findall(r"^```", translated_body, _re_diag.MULTILINE)) // 2
            logger.info(f"AST DIAG: Rendered markdown contains {_rendered_cb} code blocks")

            logger.info(
                f"AST Translation: Successfully translated {translatable_units} units "
                f"({stats.ast_batch_calls} batches, {stats.ast_individual_fallbacks} fallbacks)"
            )

            return translated_body

        except TranslationRetryableError:
            raise
        except Exception as e:
            from .exceptions import TranslationIncomplete

            if isinstance(e, TranslationIncomplete):
                raise
            logger.error(f"AST-based translation failed: {e}", exc_info=True)
            raise RuntimeError(f"AST-based translation failed: {e}")

    def _restore_placeholders(self, text: str, segment) -> str:
        """Restore placeholder content (links, shortcodes, etc.) in translated text."""
        engine = self._engine
        if not text:
            return text

        result = text

        # TRM-05: Restore terminology placeholders first
        if engine.terminology_manager and getattr(segment, "protected_terms", None):
            try:
                for protected_segment in segment.protected_terms:
                    if protected_segment.term_mapping:
                        from .terminology.models import ProtectedSegment

                        translated_protected = ProtectedSegment(
                            original_text=protected_segment.original_text,
                            protected_text=result,
                            term_mapping=protected_segment.term_mapping,
                        )
                        result = engine.terminology_manager.restore(translated_protected)
                        logger.debug(
                            f"Restored {len(protected_segment.term_mapping)} terminology terms"
                        )
            except Exception as e:
                logger.warning(f"Terminology restore failed: {e}")

        # Restore shortcode/pattern placeholders
        if getattr(segment, "placeholder_map", None):
            try:
                result = engine.placeholder_manager.restore(result, segment.placeholder_map)
            except Exception as e:
                logger.warning(f"Placeholder restore failed: {e}")

        return result

    def _translate_with_multiline_support(
        self,
        backend,
        segments: list,
        texts: list[str],
        source_lang: str,
        target_lang: str,
        stats: TranslationStats,
    ) -> list[str]:
        """Translate texts with multiline structure preservation (MSP-02)."""
        engine = self._engine
        batch_size = getattr(engine, "batch_size", 1)
        sort_by_length = getattr(engine, "sort_segments_by_length", False)

        multiline_indices = []
        singleline_indices = []
        singleline_texts = []

        for idx, (segment, text) in enumerate(zip(segments, texts, strict=False)):
            if engine.multiline_handler.is_multiline(segment.source_text):
                multiline_indices.append(idx)
            else:
                singleline_indices.append(idx)
                singleline_texts.append(text)

        translated_texts = [None] * len(texts)

        # Translate single-line texts in batches
        if singleline_texts:
            batch_translations = []
            total_texts = len(singleline_texts)

            if sort_by_length and total_texts > 1:
                sorted_indices = sorted(range(total_texts), key=lambda i: len(singleline_texts[i]))
                sorted_texts = [singleline_texts[i] for i in sorted_indices]
                logger.debug(
                    f"SR-01: Sorting {total_texts} segments by length "
                    f"(range: {len(sorted_texts[0])}-{len(sorted_texts[-1])} chars)"
                )
            else:
                sorted_indices = list(range(total_texts))
                sorted_texts = singleline_texts

            for chunk_start in range(0, total_texts, batch_size):
                chunk_end = min(chunk_start + batch_size, total_texts)
                chunk_texts = sorted_texts[chunk_start:chunk_end]

                if hasattr(backend, "translate_with_token_counts"):
                    chunk_translations, input_tokens, output_tokens = (
                        backend.translate_with_token_counts(chunk_texts, source_lang, target_lang)
                    )
                    stats.tokens_input += input_tokens
                    stats.tokens_output += output_tokens
                else:
                    chunk_translations = backend.translate(chunk_texts, source_lang, target_lang)
                    stats.tokens_input += sum(estimate_token_count(t) for t in chunk_texts)
                    stats.tokens_output += sum(estimate_token_count(t) for t in chunk_translations)

                batch_translations.extend(chunk_translations)

                if total_texts > batch_size:
                    logger.debug(
                        f"Translated batch {chunk_start // batch_size + 1}/"
                        f"{(total_texts + batch_size - 1) // batch_size} "
                        f"({len(chunk_texts)} texts)"
                    )

            unsorted_translations = [None] * total_texts
            for sorted_idx, original_list_idx in enumerate(sorted_indices):
                unsorted_translations[original_list_idx] = batch_translations[sorted_idx]

            for list_idx, original_idx in enumerate(singleline_indices):
                candidate = self._retry_untranslated_text_by_sentence(
                    backend,
                    texts[original_idx],
                    unsorted_translations[list_idx],
                    source_lang,
                    target_lang,
                    stats,
                )
                candidate = self._retry_english_residue_by_sentence(
                    backend,
                    texts[original_idx],
                    candidate,
                    source_lang,
                    target_lang,
                    stats,
                )
                translated_texts[original_idx] = self._repair_untranslated_product_title(
                    backend,
                    texts[original_idx],
                    candidate,
                    source_lang,
                    target_lang,
                    stats,
                )

        # Translate multiline texts with structure preservation
        if multiline_indices:
            logger.info(
                f"MSP-02: Processing {len(multiline_indices)} multiline segments "
                f"with structure preservation"
            )
            multiline_batch_size = 1
            logger.info("MSP-02: Using batch_size=1 for multiline lines")
            multiline_line_items = []
            multiline_line_info = {}
            fenced_code_indices = set()

            for original_idx in multiline_indices:
                text = texts[original_idx]
                segment = segments[original_idx]
                if self._has_fenced_code_or_placeholder(
                    segment.source_text, getattr(segment, "placeholder_map", None)
                ):
                    fenced_code_indices.add(original_idx)
                    translated_texts[original_idx] = self._translate_fenced_code_prose_chunks(
                        backend,
                        segment.source_text,
                        source_lang,
                        target_lang,
                        stats,
                        getattr(segment, "placeholder_map", None),
                    )
                    continue
                lines_info = engine.multiline_handler.parse_lines(text)
                multiline_line_info[original_idx] = lines_info
                for line_info in lines_info:
                    if line_info.is_empty:
                        continue
                    if not line_info.content.strip():
                        continue
                    if self._should_preserve_multiline_line(line_info.content):
                        logger.debug(
                            "MSP-02: Preserving placeholder-dense multiline line without MT"
                        )
                        continue
                    multiline_line_items.append(
                        (original_idx, line_info.line_index, line_info.content)
                    )

            stats.multiline_segments += len(multiline_indices)
            stats.multiline_lines += len(multiline_line_items)

            translated_line_map = {}
            multiline_backend_calls = 0

            if multiline_line_items:
                line_texts = [item[2] for item in multiline_line_items]

                if sort_by_length and len(line_texts) > 1:
                    sorted_indices = sorted(
                        range(len(line_texts)), key=lambda i: len(line_texts[i])
                    )
                    sorted_texts = [line_texts[i] for i in sorted_indices]
                    logger.debug(
                        f"MSP-02: Sorting {len(line_texts)} multiline lines by length "
                        f"(range: {len(sorted_texts[0])}-{len(sorted_texts[-1])} chars)"
                    )
                else:
                    sorted_indices = list(range(len(line_texts)))
                    sorted_texts = line_texts

                batch_translations = []
                total_lines = len(sorted_texts)

                for chunk_start in range(0, total_lines, multiline_batch_size):
                    chunk_end = min(chunk_start + multiline_batch_size, total_lines)
                    chunk_texts = sorted_texts[chunk_start:chunk_end]
                    multiline_backend_calls += 1

                    if hasattr(backend, "translate_with_token_counts"):
                        chunk_translations, input_tokens, output_tokens = (
                            backend.translate_with_token_counts(
                                chunk_texts, source_lang, target_lang
                            )
                        )
                        stats.tokens_input += input_tokens
                        stats.tokens_output += output_tokens
                    else:
                        chunk_translations = backend.translate(
                            chunk_texts, source_lang, target_lang
                        )
                        stats.tokens_input += sum(estimate_token_count(t) for t in chunk_texts)
                        stats.tokens_output += sum(
                            estimate_token_count(t) for t in chunk_translations
                        )

                    batch_translations.extend(chunk_translations)

                    if total_lines > multiline_batch_size:
                        logger.debug(
                            f"MSP-02: Translated multiline batch {chunk_start // multiline_batch_size + 1}/"
                            f"{(total_lines + multiline_batch_size - 1) // multiline_batch_size} "
                            f"({len(chunk_texts)} lines)"
                        )

                unsorted_translations = [None] * total_lines
                for sorted_idx, original_list_idx in enumerate(sorted_indices):
                    unsorted_translations[original_list_idx] = batch_translations[sorted_idx]

                for list_idx, (segment_idx, line_idx, _) in enumerate(multiline_line_items):
                    translated_line_map[(segment_idx, line_idx)] = unsorted_translations[list_idx]

            stats.multiline_backend_calls += multiline_backend_calls

            for original_idx in multiline_indices:
                if original_idx in fenced_code_indices:
                    continue
                segment = segments[original_idx]
                lines_info = multiline_line_info.get(original_idx, [])
                translated_lines = []

                for line_info in lines_info:
                    if line_info.is_empty:
                        translated_lines.append(line_info.original)
                        continue
                    if not line_info.content.strip():
                        translated_lines.append(
                            f"{line_info.indent}{line_info.prefix}{line_info.content}"
                        )
                        continue

                    translated_content = translated_line_map.get(
                        (original_idx, line_info.line_index), line_info.content
                    )
                    translated_content = self._retry_untranslated_text_by_sentence(
                        backend,
                        line_info.content,
                        translated_content,
                        source_lang,
                        target_lang,
                        stats,
                    )
                    translated_content = self._retry_english_residue_by_sentence(
                        backend,
                        line_info.content,
                        translated_content,
                        source_lang,
                        target_lang,
                        stats,
                    )
                    translated_lines.append(
                        f"{line_info.indent}{line_info.prefix}{translated_content}"
                    )

                translated_text = "\n".join(translated_lines)
                if (
                    self._has_fenced_code_or_placeholder(
                        segment.source_text, getattr(segment, "placeholder_map", None)
                    )
                    and self._is_effectively_untranslated(segment.source_text, translated_text)
                ):
                    logger.info(
                        "MSP-02: Retrying fenced-code multiline segment as prose/code chunks"
                    )
                    translated_text = self._translate_fenced_code_prose_chunks(
                        backend,
                        segment.source_text,
                        source_lang,
                        target_lang,
                        stats,
                        getattr(segment, "placeholder_map", None),
                    )
                structure_preserved = len(translated_lines) == len(lines_info)

                if not structure_preserved:
                    logger.warning(
                        f"MSP-02: Structure drift in segment {segment.id}: "
                        f"{len(lines_info)} -> {len(translated_lines)} lines"
                    )

                translated_texts[original_idx] = translated_text

                logger.debug(
                    f"MSP-02: Multiline segment {segment.id} translated with "
                    f"{len(lines_info)} lines preserved"
                )

        return translated_texts
