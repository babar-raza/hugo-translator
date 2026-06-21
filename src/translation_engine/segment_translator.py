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
import time
from pathlib import Path
from typing import TYPE_CHECKING

from ..observability.progress import get_progress_tracker
from .engine import estimate_token_count
from .exceptions import TranslationRetryableError
from .extractor import SegmentExtractor
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

                # RC-4 FIX: Disable L3 semantic search for frontmatter segments.
                _is_frontmatter_segment = bool(
                    segment.context
                    and hasattr(segment.context, "context_type")
                    and str(segment.context.context_type) == "SegmentContextType.FRONTMATTER"
                )

                tm_result = engine.tm.lookup(
                    site_id=site_id,
                    src_lang=source_lang,
                    tgt_lang=target_lang,
                    text=segment.source_text,
                    context=str(segment.context) if segment.context else None,
                    lookup_context=lookup_context,
                    use_semantic=not _is_frontmatter_segment,
                )

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
            try:
                translated_body = self._translate_body_ast(
                    doc,
                    target_lang,
                    site_profile,
                    stats,
                    segments=segments,
                    translations=translations,
                )

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
                import yaml as _yaml_check

                _source_keys = set(doc.frontmatter.keys())
                try:
                    _out_data = _yaml_check.safe_load(frontmatter_yaml.split("---", 2)[1])
                    _out_keys = set(_out_data.keys()) if isinstance(_out_data, dict) else set()
                    if _source_keys != _out_keys:
                        _diff = _source_keys ^ _out_keys
                        raise ValueError(
                            f"Frontmatter key integrity check failed after translation. "
                            f"Mismatched keys: {_diff}"
                        )
                except _yaml_check.YAMLError as _e:
                    raise ValueError(f"Frontmatter key integrity: YAML parse failed: {_e}") from _e

                translated_content = f"{frontmatter_yaml}\n{translated_body}"
                logger.info("AST Translation: Successfully reconstructed document")

            except TranslationRetryableError:
                raise
            except Exception as e:
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

            reconstructor = MarkdownReconstructor(site_profile)
            translated_doc = reconstructor.reconstruct_document(
                doc, translations, target_lang, segment_map=segment_map
            )

            translated_content = str(translated_doc)

        stats.tokens_total = stats.tokens_cached + stats.tokens_input + stats.tokens_output

        return translated_content

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

            # Step 2: Translate units with batching + fallback
            batch_size = site_profile.body.ast_batch_size
            units_needing_translation = [
                u for u in plan.units if not u.do_not_translate and not u.translated_text
            ]
            logger.info(
                f"AST Translation: Translating {len(units_needing_translation)} new units (batch_size: {batch_size}, reused: {reused_count})"
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

            # AGENT B-7.3: Check batch-level purity failures
            batch_stats = extractor.batch_stats
            if batch_stats.get("language_purity_failures", 0) > 0 and target_lang not in (
                _batch_purity_skip_langs or []
            ):
                total_batches = batch_stats.get("total_batches", 0)
                if total_batches > 0:
                    purity_failure_rate = batch_stats["language_purity_failures"] / total_batches

                    if purity_failure_rate > 0.10:
                        logger.error(
                            f"HIGH PURITY FAILURE RATE: {purity_failure_rate:.1%} of batches failed "
                            f"language validation. Blocking write to prevent corruption. "
                            f"Stats: {batch_stats['language_purity_failures']}/{total_batches} batches failed."
                        )

                        issues = [
                            ValidationIssue(
                                severity="error",
                                rule="BatchLanguagePurity",
                                message=f"High batch purity failure rate: {purity_failure_rate:.1%} ({batch_stats['language_purity_failures']}/{total_batches} batches)",
                                location=str(doc.file_path) if hasattr(doc, "file_path") else None,
                            )
                        ]
                        validation_result = ValidationResult(valid=False, issues=issues)
                        raise TranslationRetryableError(
                            message=f"Batch purity failure rate too high: {purity_failure_rate:.1%}",
                            file_path=str(doc.file_path) if hasattr(doc, "file_path") else "",
                            validation_result=validation_result,
                            retry_feedback=f"Batch language purity check failed for {purity_failure_rate:.1%} of batches. Ensure all translated units are in the target language {target_lang}.",
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
                translated_texts[original_idx] = unsorted_translations[list_idx]

        # Translate multiline texts with structure preservation
        if multiline_indices:
            logger.info(
                f"MSP-02: Processing {len(multiline_indices)} multiline segments "
                f"with structure preservation"
            )
            multiline_line_items = []
            multiline_line_info = {}

            for original_idx in multiline_indices:
                text = texts[original_idx]
                lines_info = engine.multiline_handler.parse_lines(text)
                multiline_line_info[original_idx] = lines_info
                for line_info in lines_info:
                    if line_info.is_empty:
                        continue
                    if not line_info.content.strip():
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

                for chunk_start in range(0, total_lines, batch_size):
                    chunk_end = min(chunk_start + batch_size, total_lines)
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

                    if total_lines > batch_size:
                        logger.debug(
                            f"MSP-02: Translated multiline batch {chunk_start // batch_size + 1}/"
                            f"{(total_lines + batch_size - 1) // batch_size} "
                            f"({len(chunk_texts)} lines)"
                        )

                unsorted_translations = [None] * total_lines
                for sorted_idx, original_list_idx in enumerate(sorted_indices):
                    unsorted_translations[original_list_idx] = batch_translations[sorted_idx]

                for list_idx, (segment_idx, line_idx, _) in enumerate(multiline_line_items):
                    translated_line_map[(segment_idx, line_idx)] = unsorted_translations[list_idx]

            stats.multiline_backend_calls += multiline_backend_calls

            for original_idx in multiline_indices:
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
                    translated_lines.append(
                        f"{line_info.indent}{line_info.prefix}{translated_content}"
                    )

                translated_text = "\n".join(translated_lines)
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
