"""
TC-DECOMP-03: Per-language retry/validation/correction pipeline.

Extracted from TranslationEngine.translate_file() to isolate the retry loop,
validation cycle, correction pass, VA-03 verification gate, write gate
evaluation, and TM buffer management into a cohesive unit.

The pipeline receives an engine reference for accessing shared state
(validation suite, decision engine, write gate, TM, config, etc.)
and mutates the TranslationResult directly.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..tm.retranslate_queue import (
    add_to_queue as _rtq_add,
)
from ..tm.retranslate_queue import (
    increment_retry as _rtq_increment,
)
from ..tm.retranslate_queue import (
    remove_from_queue as _rtq_remove,
)

if TYPE_CHECKING:
    from .engine import TranslationEngine

logger = logging.getLogger(__name__)


@dataclass
class LanguageTranslationContext:
    """All inputs needed for translating one file into one target language."""

    site_id: str
    site_profile: Any
    doc: Any  # HugoDocument
    segments: list
    content: str  # raw source file content
    source_lang: str
    target_lang: str
    output_path: Path
    file_path: Path
    force: bool
    should_validate: bool
    should_verify: bool
    should_fix: bool
    max_retry_attempts: int
    output_paths_cache: dict[str, Path]
    llm_model_override: str | None = None


@dataclass
class LanguageResult:
    """Outcome of translating one file into one target language."""

    success: bool
    error: str | None = None
    output_path: Path | None = None
    retry_count: int = 0
    overwrite_blocked: bool = False


class FileTranslationPipeline:
    """Owns the per-language retry/validation/write loop.

    Receives an engine reference for shared state access.
    Mutates TranslationResult directly (passed by reference).
    """

    def __init__(self, engine: TranslationEngine) -> None:
        self._engine = engine

    def translate_language(
        self,
        ctx: LanguageTranslationContext,
        result: Any,  # TranslationResult — mutated in place
    ) -> LanguageResult:
        """Run the retry loop for a single target language.

        This method encapsulates:
        - LLM escalation override detection
        - TM write buffer lifecycle
        - The while retry_count <= max_retry_attempts loop
        - Validation -> decision -> correction cycle
        - VA-03 verification gate (with retry-on-failure)
        - Write gate evaluation (gates 2-8)
        - TM buffer flush on success
        - Post-write bookkeeping
        - Exception handling (Rejected, Retryable, Shutdown, OOM, generic)
        - Post-loop retry metrics
        """
        engine = self._engine

        # Retry loop state
        retry_count = 0
        retry_feedback = None
        translated_content = None
        final_decision = None
        final_validation_result = None
        final_verification_result = None

        # BM-08: Track retry timing
        retry_start_time = time.perf_counter()

        # TC-11: Per-file TM write buffer. Segments are collected here during
        # _translate_to_language() and flushed to self.tm only after the file
        # passes all purity and validation gates and is successfully written to disk.
        _tm_write_buffer: list = []

        # TC-06: Correction pass guard -- only attempt once per file+lang
        _correction_attempted = False
        # Repeated feedback guard: tracks error validator names from previous retry.
        _prev_retry_validators: frozenset | None = None

        # Unpack context for readability
        site_id = ctx.site_id
        site_profile = ctx.site_profile
        doc = ctx.doc
        segments = ctx.segments
        content = ctx.content
        source_lang = ctx.source_lang
        target_lang = ctx.target_lang
        output_path = ctx.output_path
        file_path = ctx.file_path
        force = ctx.force
        should_validate = ctx.should_validate
        should_verify = ctx.should_verify
        should_fix = ctx.should_fix
        max_retry_attempts = ctx.max_retry_attempts
        output_paths_cache = ctx.output_paths_cache
        _llm_model_override = ctx.llm_model_override

        lang_result = LanguageResult(success=False, retry_count=0)

        while retry_count <= max_retry_attempts:
            try:
                # Clear buffer at each attempt start (discard any entries from
                # a failed previous attempt that triggered RETRY).
                _tm_write_buffer.clear()

                # Translate (returns content, doesn't write yet)
                translated_content = engine._translate_to_language(
                    site_id=site_id,
                    site_profile=site_profile,
                    doc=doc,
                    segments=segments,
                    source_lang=source_lang,
                    target_lang=target_lang,
                    force=force,
                    stats=result.stats,
                    retry_feedback=retry_feedback,
                    retry_count=retry_count,
                    model_id_override=_llm_model_override,
                    tm_write_buffer=_tm_write_buffer,
                )

                # Pre-write validation (if enabled)
                if should_validate and engine.validation_suite and engine.decision_engine:
                    # Extract source body for validation
                    if doc.ast:
                        from .reconstructor import ASTRenderer

                        _val_renderer = ASTRenderer()
                        source_body = _val_renderer.render_to_markdown(doc.ast)
                    else:
                        source_body = ""

                    # Extract translated body by stripping frontmatter
                    def _strip_frontmatter(text: str) -> str:
                        if text.startswith("---"):
                            end = text.find("---", 3)
                            if end != -1:
                                return text[end + 3 :].lstrip("\n")
                        return text

                    translated_body = _strip_frontmatter(translated_content)

                    # TC-05: Review cache -- skip full validation if this exact
                    # source+translation pair was already validated and ACCEPTED.
                    _rc_hit = False
                    _rc_key = None
                    if engine._review_cache is not None and retry_count == 0:
                        from .validation.review_cache import ReviewCache

                        _rc_key = ReviewCache.make_key(
                            source_body,
                            translated_body,
                            target_lang,
                            getattr(engine, "_review_cache_config_fingerprint", ""),
                        )
                        _rc_entry = engine._review_cache.get(_rc_key)
                        if _rc_entry and _rc_entry.get("decision") == "ACCEPT":
                            _rc_hit = True
                            logger.debug(
                                "Review cache HIT for %s -> %s (skipping validation)",
                                file_path.name,
                                target_lang,
                            )

                    if not _rc_hit:
                        # Run validation suite
                        validation_result = engine.validation_suite.validate_aggregated(
                            source_body,
                            translated_body,
                            context={
                                "source_lang": source_lang,
                                "target_lang": target_lang,
                                "file_path": str(file_path),
                            },
                        )

                        # Check frontmatter language
                        _fm_issues = engine._check_frontmatter_language(
                            translated_content, target_lang
                        )
                        validation_result.issues.extend(_fm_issues)

                        # Make decision
                        decision_result = engine.decision_engine.make_decision(
                            validation_result=validation_result,
                            retry_count=retry_count,
                            source=source_body,
                            site_id=site_id,
                            target_lang=target_lang,
                        )

                        final_decision = decision_result
                        final_validation_result = validation_result

                        # TC-05: Store ACCEPT results in review cache
                        if (
                            engine._review_cache is not None
                            and _rc_key
                            and decision_result.decision == PostValidationDecision.ACCEPT
                        ):
                            engine._review_cache.put(
                                _rc_key,
                                decision="ACCEPT",
                                error_count=validation_result.error_count,
                                warning_count=validation_result.warning_count,
                                decision_reason=decision_result.decision_reason or "",
                            )
                    else:
                        # Cache hit -- treat as ACCEPT, skip full validation
                        final_decision = None
                        final_validation_result = None

                    # T3-D: Append to local validation metrics log
                    if not _rc_hit:
                        try:
                            from .validation.decision_engine import append_validation_metric

                            _vr = {
                                i.validator: (i.severity.value != "error")
                                for i in validation_result.issues
                            }
                            append_validation_metric(
                                file_path=str(file_path),
                                lang=target_lang,
                                decision=decision_result.decision.value,
                                validator_results=_vr,
                                retry_count=retry_count,
                                error_count=sum(
                                    1
                                    for i in validation_result.issues
                                    if i.severity.value == "error"
                                ),
                                warning_count=sum(
                                    1
                                    for i in validation_result.issues
                                    if i.severity.value == "warning"
                                ),
                            )
                        except Exception:
                            pass

                    # Handle decision (skip on review cache hit -- already ACCEPTED)
                    if _rc_hit:
                        pass  # Fall through to ACCEPT / write phase
                    elif decision_result.decision == PostValidationDecision.REJECT:
                        # TC-06: Correction pass
                        if not _correction_attempted:
                            _correction_attempted = True
                            try:
                                _corr_cfg = (
                                    engine.config.get_config().get("correction_pass", {})
                                    if hasattr(engine.config, "get_config")
                                    else {}
                                )
                                if _corr_cfg.get("enabled", False):
                                    from .correction import attempt_correction

                                    _corr_model = _corr_cfg.get("model", "professionalize_llm")
                                    _corrected_body = attempt_correction(
                                        source_body=source_body,
                                        translated_body=translated_body,
                                        src_lang=source_lang,
                                        tgt_lang=target_lang,
                                        issues=validation_result.issues,
                                        model_id=_corr_model,
                                    )
                                    if _corrected_body:
                                        # Re-assemble full content
                                        if translated_content.startswith("---"):
                                            _fm_end = translated_content.find("---", 3)
                                            if _fm_end != -1:
                                                translated_content = (
                                                    translated_content[: _fm_end + 3]
                                                    + "\n"
                                                    + _corrected_body
                                                )
                                            else:
                                                translated_content = _corrected_body
                                        else:
                                            translated_content = _corrected_body

                                        # Re-validate the corrected content
                                        translated_body = _corrected_body
                                        validation_result = (
                                            engine.validation_suite.validate_aggregated(
                                                source_body,
                                                translated_body,
                                                context={
                                                    "source_lang": source_lang,
                                                    "target_lang": target_lang,
                                                    "file_path": str(file_path),
                                                },
                                            )
                                        )
                                        _fm_issues = engine._check_frontmatter_language(
                                            translated_content, target_lang
                                        )
                                        validation_result.issues.extend(_fm_issues)
                                        decision_result = engine.decision_engine.make_decision(
                                            validation_result=validation_result,
                                            retry_count=retry_count,
                                            source=source_body,
                                            site_id=site_id,
                                            target_lang=target_lang,
                                        )
                                        final_decision = decision_result
                                        final_validation_result = validation_result

                                        if (
                                            decision_result.decision
                                            != PostValidationDecision.REJECT
                                        ):
                                            logger.info(
                                                "Correction pass SAVED %s -> %s (decision: %s)",
                                                file_path.name,
                                                target_lang,
                                                decision_result.decision.value,
                                            )
                                        else:
                                            logger.warning(
                                                "Correction pass did NOT fix %s -> %s",
                                                file_path.name,
                                                target_lang,
                                            )
                            except Exception as _corr_err:
                                logger.debug("Correction pass error: %s", _corr_err)

                        # After correction attempt, re-check decision
                        if decision_result.decision == PostValidationDecision.REJECT:
                            raise TranslationRejectedError(
                                message=f"Translation rejected: {decision_result.decision_reason}",
                                file_path=str(file_path),
                                validation_result=validation_result,
                                rejection_reason=decision_result.decision_reason,
                            )

                    elif decision_result.decision == PostValidationDecision.RETRY:
                        # TC-BUGFIX-B: MT backends cannot act on retry feedback —
                        # they produce identical output. Skip directly to REJECT.
                        _model_used = getattr(result.stats, "model_used", "") or ""
                        _is_llm_backend = "llm" in _model_used.lower()
                        if _model_used and not _is_llm_backend:
                            logger.warning(
                                f"MT backend ({_model_used}) cannot act on feedback — "
                                f"escalating to reject + retranslate queue for {file_path} to {target_lang}"
                            )
                            raise TranslationRejectedError(
                                message=f"MT backend cannot retry with feedback: {decision_result.decision_reason}",
                                file_path=str(file_path),
                                validation_result=validation_result,
                                rejection_reason="MT backend cannot use feedback — retries are futile",
                            )

                        # Repeated feedback guard
                        try:
                            _current_validators = frozenset(
                                (
                                    getattr(iss, "validator", ""),
                                    getattr(iss, "severity", ""),
                                )
                                for iss in (validation_result.issues if validation_result else [])
                                if getattr(getattr(iss, "severity", None), "value", "") == "error"
                            )
                        except Exception:
                            _current_validators = frozenset()
                        if (
                            _prev_retry_validators is not None
                            and _current_validators
                            and _current_validators == _prev_retry_validators
                        ):
                            logger.warning(
                                f"Repeated feedback for {file_path} to {target_lang}: "
                                f"same validators on retry {retry_count}. Failing early. "
                                f"Validators: {_current_validators}"
                            )
                            raise TranslationRejectedError(
                                message=f"Repeated identical feedback: {decision_result.decision_reason}",
                                file_path=str(file_path),
                                validation_result=validation_result,
                                rejection_reason="Repeated feedback -- LLM cannot resolve this issue",
                            )
                        _prev_retry_validators = _current_validators

                        # Retry with feedback
                        retry_count += 1

                        if retry_count > max_retry_attempts:
                            logger.error(
                                f"Max retry attempts ({max_retry_attempts}) exceeded for {file_path} "
                                f"to {target_lang}. Validation kept returning RETRY. "
                                f"Reason: {decision_result.decision_reason}"
                            )
                            raise TranslationRejectedError(
                                message=f"Max retry attempts exceeded: {decision_result.decision_reason}",
                                file_path=str(file_path),
                                validation_result=validation_result,
                                rejection_reason=decision_result.decision_reason,
                            )

                        retry_feedback = decision_result.retry_feedback
                        result.stats.validation_retried += 1
                        # Progress tracking
                        progress = get_progress_tracker()
                        if progress:
                            progress.file_translation_retry(segments_to_undo=len(segments))
                        logger.info(
                            f"Retrying translation for {file_path} to {target_lang} "
                            f"(attempt {retry_count}/{max_retry_attempts}): "
                            f"{decision_result.decision_reason}"
                        )

                        result.retry_history.append(
                            {
                                "attempt": retry_count,
                                "reason": decision_result.decision_reason,
                                "feedback": retry_feedback,
                            }
                        )

                        # BM-08: Track retry reason
                        with engine._retry_metrics_lock:
                            reason_key = "validation_retry"
                            engine._retry_metrics["retry_reasons"][reason_key] = (
                                engine._retry_metrics["retry_reasons"].get(reason_key, 0) + 1
                            )

                        continue  # Loop again with feedback

                    # ACCEPT - fall through to write file

                # ================================================================
                # AGENT B-7.6: RESTRUCTURED WRITE FLOW
                # validate -> decide -> write
                # ================================================================

                # PHASE 1: ALL VALIDATION (before write decision)
                validation_passed = True
                validation_error = None

                # VA-03: Post-translation verification
                if should_verify:
                    logger.debug(f"Running post-translation verification for {target_lang}")

                    source_doc_dict = {
                        "frontmatter": doc.frontmatter if hasattr(doc, "frontmatter") else {},
                        "body": str(doc.body) if hasattr(doc, "body") else "",
                    }
                    translated_doc_parsed = engine.parser.parse_string(translated_content)
                    translated_doc_dict = {
                        "frontmatter": translated_doc_parsed.frontmatter
                        if hasattr(translated_doc_parsed, "frontmatter")
                        else {},
                        "body": str(translated_doc_parsed.body)
                        if hasattr(translated_doc_parsed, "body")
                        else "",
                    }

                    verification_agent = engine._get_verification_agent()
                    verification_result = verification_agent.verify(
                        source_doc=source_doc_dict,
                        translated_doc=translated_doc_dict,
                        target_lang=target_lang,
                        context={
                            "source_lang": source_lang,
                            "file_path": str(file_path),
                            "site_id": site_id,
                        },
                    )

                    final_verification_result = verification_result

                    if not verification_result.passed:
                        logger.warning(
                            f"Verification failed for {file_path} to {target_lang}: "
                            f"{verification_result.error_count} errors, "
                            f"{verification_result.warning_count} warnings"
                        )

                        if should_fix and retry_count < max_retry_attempts:
                            retry_count += 1
                            error_messages = [
                                f"- {issue.location}: {issue.message}"
                                for issue in verification_result.issues
                                if issue.severity == "error"
                            ]
                            retry_feedback = (
                                "Previous translation had verification errors:\n"
                                + "\n".join(error_messages[:5])
                                + "\n\nPlease fix these issues in the translation."
                            )
                            result.stats.validation_retried += 1

                            progress = get_progress_tracker()
                            if progress:
                                progress.file_translation_retry(segments_to_undo=len(segments))

                            logger.info(
                                f"Retrying translation due to verification failure "
                                f"(attempt {retry_count}/{max_retry_attempts})"
                            )

                            result.retry_history.append(
                                {
                                    "attempt": retry_count,
                                    "reason": "verification_failed",
                                    "feedback": retry_feedback,
                                    "error_count": verification_result.error_count,
                                }
                            )

                            # BM-08: Track retry reason
                            with engine._retry_metrics_lock:
                                reason_key = "verification_retry"
                                engine._retry_metrics["retry_reasons"][reason_key] = (
                                    engine._retry_metrics["retry_reasons"].get(reason_key, 0) + 1
                                )

                            continue  # Loop again with feedback
                        else:
                            validation_passed = False
                            validation_error = f"Verification failed: {verification_result.error_count} errors (fix={'disabled' if not should_fix else 'max retries reached'})"
                            logger.error(
                                f"WRITE BLOCKED: Verification failed for {output_path.name} "
                                f"(fix mode {'disabled' if not should_fix else 'max retries reached'}). "
                                f"Refusing to write file with {verification_result.error_count} verification errors."
                            )
                    else:
                        logger.debug(
                            f"Verification passed for {target_lang} "
                            f"({verification_result.warning_count} warnings)"
                        )

                # Prepare output path for validation checks
                source_path = (
                    doc.source_path
                    if hasattr(doc, "source_path") and doc.source_path
                    else Path("output.md")
                )

                # CRITICAL FIX: Use cached output_path to prevent path mismatch
                expected_output_path = output_paths_cache.get(target_lang)
                recalculated_output_path = engine._get_output_path(
                    source_path,
                    target_lang,
                    site_profile,
                )

                if expected_output_path != recalculated_output_path:
                    logger.error(
                        f"PATH MISMATCH DETECTED! Refusing to write to prevent corruption. "
                        f"Skip check used: {expected_output_path}, "
                        f"Write would use: {recalculated_output_path}. "
                        f"This indicates doc.source_path ({source_path}) differs from original file_path ({file_path})."
                    )
                    result.success = False
                    result.error = f"Output path mismatch: {expected_output_path} != {recalculated_output_path}"
                    lang_result.error = result.error
                    break  # Stop processing this file

                # Use the cached path for write
                output_path = expected_output_path

                # TC-DECOMP-02: Write gate evaluation (gates 2-8)
                if validation_passed:
                    _gate_result = engine._write_gate.evaluate(
                        translated_content=translated_content,
                        source_content=content,
                        target_lang=target_lang,
                        output_path=output_path,
                        source_doc=doc,
                    )
                    if not _gate_result.passed:
                        validation_passed = False
                        validation_error = _gate_result.error
                        if _gate_result.overwrite_blocked:
                            result.overwrite_blocked = True
                            lang_result.overwrite_blocked = True
                        if _gate_result.clear_tm_buffer:
                            _tm_write_buffer.clear()
                        for _rtq_path, _rtq_lang in _gate_result.retranslate_paths:
                            try:
                                _rtq_add(_rtq_path, _rtq_lang)
                            except Exception:
                                pass
                        if _gate_result.quarantine_content:
                            try:
                                from pathlib import Path as _QPath

                                _qdir = _QPath("workspace/quarantine") / (output_path.parent.name)
                                _qdir.mkdir(parents=True, exist_ok=True)
                                _qfile = _qdir / (output_path.name + ".quarantine.md")
                                _qfile.write_text(_gate_result.quarantine_content, encoding="utf-8")
                                import json as _qjson

                                (_qdir / (output_path.name + ".error.json")).write_text(
                                    _qjson.dumps(
                                        {
                                            "file": str(output_path),
                                            "error": _gate_result.quarantine_error,
                                            "target_lang": target_lang,
                                        },
                                        ensure_ascii=False,
                                        indent=2,
                                    ),
                                    encoding="utf-8",
                                )
                                logger.info("Quarantined invalid candidate to %s", _qfile)
                            except Exception as _qe:
                                logger.warning("Quarantine write failed: %s", _qe)
                    else:
                        # Soft contamination queuing (does NOT block write)
                        for _rtq_path, _rtq_lang in _gate_result.retranslate_paths:
                            try:
                                _rtq_add(_rtq_path, _rtq_lang)
                            except Exception as _rtq_err:
                                logger.debug(f"soft contamination queue failed: {_rtq_err}")

                # Apply auto-cleaned content from gates 9-12/16 (if any gate cleaned it)
                if validation_passed and "_gate_result" in locals() and _gate_result.cleaned_content is not None:
                    translated_content = _gate_result.cleaned_content

                # PHASE 2: WRITE (only if ALL validation passed)
                if validation_passed:
                    try:
                        engine._write_output(
                            translated_content, output_path, source_path, result.stats
                        )
                        logger.info(
                            f"Successfully wrote {output_path.name} after passing all validation checks"
                        )
                        # TC-11: Flush deferred TM entries now
                        for _entry in _tm_write_buffer:
                            try:
                                engine.tm.store(**_entry)
                            except Exception as _tm_err:
                                logger.warning(
                                    f"TM deferred store failed for {output_path.name}: {_tm_err}"
                                )
                        _tm_write_buffer.clear()
                    except Exception as write_error:
                        logger.error(
                            f"Write operation failed for {output_path.name}: {write_error}"
                        )
                        result.success = False
                        result.error = f"Write error: {write_error}"
                        lang_result.error = str(write_error)
                        break  # Exit retry loop
                else:
                    logger.error(f"WRITE BLOCKED for {output_path.name}: {validation_error}")
                    result.success = False
                    result.error = validation_error
                    if "Blocked overwrite:" in validation_error:
                        result.overwrite_blocked = True
                        lang_result.overwrite_blocked = True
                    if "both translations wrong" in validation_error:
                        try:
                            _rtq_increment(output_path)
                        except Exception:
                            pass
                    lang_result.error = validation_error
                    break  # Validation failure is deterministic

                # File successfully written
                result.outputs[target_lang] = output_path
                lang_result.success = True
                lang_result.output_path = output_path

                # Clear from retranslate queue (CASE 4 recovery)
                try:
                    _rtq_remove(output_path)
                except Exception:
                    pass

                # Update content hash metadata
                if engine.enable_content_hash and engine.metadata_tracker:
                    try:
                        source_hash = engine.metadata_tracker.update_source(source_path)
                        engine.metadata_tracker.update_output(
                            source_path=source_path,
                            output_path=output_path,
                            target_lang=target_lang,
                            source_hash=source_hash,
                            status="success",
                        )
                        engine.metadata_tracker.save()
                    except Exception as e:
                        logger.warning(f"Failed to update content hash metadata: {e}")

                # INT-05: Post-write validation
                post_write_passed = engine._post_write_validation(
                    output_path=output_path,
                    source_path=source_path,
                    target_lang=target_lang,
                    site_id=site_id,
                    site_profile=site_profile,
                )

                if not post_write_passed:
                    logger.warning(
                        f"Post-write validation failed for {output_path}, but file was written"
                    )

                # Mark language as completed in progress tracker
                progress = get_progress_tracker()
                if progress:
                    progress.language_completed(target_lang)

                # Track validation decision in result
                if final_decision:
                    result.validation_decision = (
                        ValidationDecision.ACCEPT
                        if final_decision.decision == PostValidationDecision.ACCEPT
                        else None
                    )
                    result.decision_reason = final_decision.decision_reason
                    result.retry_attempts = retry_count

                    result.stats.validation_passed = True
                    result.stats.validation_decision = "ACCEPT"
                    if final_validation_result:
                        result.stats.validation_errors = final_validation_result.error_count
                        result.stats.validation_warnings = final_validation_result.warning_count
                        result.stats.validation_info = final_validation_result.info_count
                    # TC-H5: Compute per-file quality signal
                    _s = result.stats
                    if _s.validation_errors > 0:
                        _s.quality_score = "FAIL"
                    elif _s.ast_missing_nodes > 1 or _s.validation_warnings > 0:
                        _s.quality_score = "PARTIAL"
                    else:
                        _s.quality_score = "PASS"

                # VA-03: Store verification result
                if final_verification_result:
                    result.verification_result = final_verification_result
                    if not final_verification_result.passed:
                        result.warnings.append(
                            f"Verification found {final_verification_result.error_count} errors "
                            f"in {target_lang} translation"
                        )

                logger.info(
                    f"Successfully translated {file_path} to {target_lang} after {retry_count} retries"
                )

                # BM-06: Record production metrics
                if engine.production_ingestor and engine.production_ingestor.enabled:
                    try:
                        engine._record_production_metrics(
                            file_path=file_path,
                            target_lang=target_lang,
                            stats=result.stats,
                            retry_count=retry_count,
                            success=True,
                        )
                    except Exception as e:
                        logger.warning(f"Failed to record production metrics: {e}")

                break  # Success, exit retry loop

            except TranslationRejectedError:
                # Per-locale rejection: record failure, queue for retry, continue
                # to next locale. Do NOT re-raise.
                result.errors.append(
                    f"Translation to {target_lang} rejected after {retry_count} attempts"
                )
                result.stats.validation_failed = True
                result.stats.validation_decision = "REJECT"
                result.stats.quality_score = "FAIL"  # TC-H5
                try:
                    _rtq_add(output_path, target_lang)
                    logger.info(
                        f"Queued rejected translation for retry: {output_path.name} ({target_lang})"
                    )
                except Exception:
                    pass
                break  # exit retry loop only

            except TranslationRetryableError as e:
                retry_count += 1
                retry_feedback = e.retry_feedback

                progress = get_progress_tracker()
                if progress:
                    progress.file_translation_retry(segments_to_undo=len(segments))

                # BM-08: Track retry reason
                with engine._retry_metrics_lock:
                    reason_key = "retryable_error"
                    engine._retry_metrics["retry_reasons"][reason_key] = (
                        engine._retry_metrics["retry_reasons"].get(reason_key, 0) + 1
                    )

                if retry_count > max_retry_attempts:
                    # Per-locale rejection: max retries exceeded. Handle in-place;
                    # do NOT raise.
                    result.errors.append(
                        f"Translation to {target_lang} rejected after {retry_count} retries"
                    )
                    result.stats.validation_failed = True
                    result.stats.validation_decision = "REJECT"
                    result.stats.quality_score = "FAIL"
                    try:
                        _rtq_add(output_paths_cache.get(target_lang, output_path), target_lang)
                        logger.info(
                            f"Queued rejected translation for retry: "
                            f"{output_paths_cache.get(target_lang, output_path).name} ({target_lang})"
                        )
                    except Exception:
                        pass
                    break  # exit retry loop only
                continue

            except Exception as e:
                # SR-02: Handle shutdown request by re-raising
                from .exceptions import ShutdownRequested

                if isinstance(e, ShutdownRequested):
                    logger.info(
                        f"Shutdown requested during translation of {file_path} to {target_lang} "
                        f"(completed {e.segments_completed} segments)"
                    )
                    progress = get_progress_tracker()
                    if progress:
                        progress.file_completed(success=False, has_new_translations=False)
                    raise

                # OOM-01: Detect OOM errors
                if engine._is_oom_error(e):
                    if engine.retry_handler:
                        logger.debug(
                            f"OOM error detected for {file_path} to {target_lang}. "
                            f"Re-raising to engage RetryHandler with batch reduction."
                        )
                        raise
                    else:
                        logger.error(
                            f"OOM error detected for {file_path} to {target_lang}, "
                            f"but RetryHandler is disabled. Consider enabling autonomous_recovery.oom_retry "
                            f"in config to automatically reduce batch size. Error: {e}"
                        )
                        result.errors.append(f"Translation to {target_lang} failed (OOM): {e}")
                        break

                # Unexpected error - don't retry
                logger.error(f"Error translating {file_path} to {target_lang}: {e}")
                result.errors.append(f"Translation to {target_lang} failed: {e}")
                break

        # BM-08: Record retry metrics after retry loop completes
        lang_result.retry_count = retry_count
        retry_duration_ms = (time.perf_counter() - retry_start_time) * 1000
        with engine._retry_metrics_lock:
            engine._retry_metrics["retry_attempts"].append(retry_count)
            engine._retry_metrics["retry_durations_ms"].append(retry_duration_ms)

        if retry_count > 0 and retry_duration_ms > 1000:
            logger.warning(
                f"High retry overhead for {file_path} to {target_lang}: "
                f"{retry_count} retries in {retry_duration_ms:.1f}ms"
            )

        return lang_result


# ---------------------------------------------------------------------------
# Lazy imports used inside the pipeline (referenced by name in the loop body)
# ---------------------------------------------------------------------------
from ..observability.progress import get_progress_tracker
from .exceptions import TranslationRejectedError, TranslationRetryableError
from .models import ValidationDecision
from .validation.post_translation_validator import ValidationDecision as PostValidationDecision
