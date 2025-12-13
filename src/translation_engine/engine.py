"""
Main Translation Engine.

Orchestrates the complete translation workflow:
1. Parse Hugo markdown files
2. Extract translatable segments
3. Lookup translations in Translation Memory
4. Translate new segments using models
5. Reconstruct translated documents
6. Write output files
"""
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional

from ..model_runtime import ModelLoader
from ..observability.telemetry_integration import get_telemetry
from ..tm import TranslationMemory
from .extractor.placeholder_manager import PlaceholderManager
from ..tm.override_controller import OverrideController, OverrideConfig, OverrideMode
from ..utils.config_loader import ConfigService
from .exceptions import TranslationRejectedError, TranslationRetryableError
from .extractor import SegmentExtractor
from .models import DirectoryResult, TranslationResult, TranslationStats, ValidationDecision
from .parser import HugoParser
from .reconstructor import MarkdownReconstructor
from .validation import ValidationSuite
from .validation.decision_engine import ValidationDecisionEngine
from .validation.post_translation_validator import ValidationDecision as PostValidationDecision
from .handlers.multiline_handler import MultilineHandler

logger = logging.getLogger(__name__)


def estimate_token_count(text: str) -> int:
    """
    Estimate token count for text (rough approximation).

    Uses a simple heuristic: ~1.3 tokens per word.
    This is a rough estimate for when actual tokenization isn't available.

    Args:
        text: Text to estimate tokens for

    Returns:
        Estimated token count
    """
    # Rough approximation: split on whitespace and multiply by 1.3
    # This accounts for subword tokenization
    word_count = len(text.split())
    return int(word_count * 1.3)


class TranslationEngine:
    """
    Main translation engine orchestrating all components.

    Integrates parser, extractor, TM, model loader, and reconstructor
    into a cohesive translation workflow.
    """

    def __init__(
        self,
        config_service: ConfigService,
        tm: TranslationMemory,
        model_loader: ModelLoader,
        enable_validation: bool = False,
        enable_telemetry: bool = True,
        validation_suite: Optional[ValidationSuite] = None,
        decision_engine: Optional[ValidationDecisionEngine] = None,
        validation_mode: Optional[str] = None,
        enable_terminology: Optional[bool] = None,
        terminology_mode: Optional[str] = None,
        max_retries: Optional[int] = None,
        dry_run: bool = False,
        save_rejected: bool = False,
        override_mode: Optional[str] = None,
        override_filters: Optional[Dict] = None,
        **kwargs,
    ):
        """
        Initialize translation engine.

        Args:
            config_service: Configuration service with site profiles
            tm: Translation Memory instance
            model_loader: Model loader for translation models
            enable_validation: Whether to enable validation by default
            enable_telemetry: Whether to enable TEL-04 telemetry tracking
            validation_suite: Optional custom ValidationSuite instance
            decision_engine: Optional custom ValidationDecisionEngine instance
            validation_mode: Validation mode override (strict, normal, lenient)
            enable_terminology: Enable/disable terminology preservation
            terminology_mode: Terminology mode (protect, validate, both, none)
            max_retries: Override max retry attempts
            dry_run: Preview decisions without writing files
            save_rejected: Save rejected translations for debugging
            override_mode: TM cache override mode (normal, bypass, refresh, validate)
            override_filters: Optional filters for override (source_patterns, target_langs, frontmatter_keys)
            **kwargs: Additional options (for future extensibility)
        """
        self.config = config_service
        self.tm = tm
        self.model_loader = model_loader
        self.enable_validation = enable_validation
        self.enable_telemetry = enable_telemetry

        # CFG-03: Store CLI overrides
        self.validation_mode = validation_mode
        self.enable_terminology = enable_terminology
        self.terminology_mode = terminology_mode
        self.max_retries_override = max_retries
        self.dry_run = dry_run
        self.save_rejected = save_rejected

        # TMO-03: Configure TM override mode if specified
        if override_mode:
            mode_map = {
                "normal": OverrideMode.NORMAL,
                "bypass": OverrideMode.BYPASS,
                "refresh": OverrideMode.REFRESH,
                "validate": OverrideMode.VALIDATE,
            }
            mode = mode_map.get(override_mode.lower(), OverrideMode.NORMAL)
            self.tm.set_override_mode(mode, override_filters)

        # Initialize components (will be created per-site)
        self.parser = HugoParser()
        self.validation_suite = validation_suite or (ValidationSuite() if enable_validation else None)
        self.placeholder_manager = PlaceholderManager()
        self.multiline_handler = MultilineHandler()  # MSP-02: Structure-preserving multiline translation

        # INT-01: Initialize decision engine with default config
        # CFG-03: Apply max_retries override if specified
        decision_config = {
            "decision_rules": {
                "max_retry_attempts": max_retries if max_retries is not None else 2,
                "reject_on_error_count": 3,
                "accept_warnings": True,
                "accept_after_max_retries": True,
                "reject_on_placeholder_error": True,
                "reject_on_code_block_error": True,
                "reject_on_link_error": True,
                "retry_on_structure_error": True,
                "retry_on_terminology_warning": True,
            }
        }

        # CFG-03: Apply validation mode overrides to decision config
        if validation_mode == "strict":
            decision_config["decision_rules"]["reject_on_error_count"] = 1
            decision_config["decision_rules"]["accept_warnings"] = False
        elif validation_mode == "lenient":
            decision_config["decision_rules"]["reject_on_error_count"] = 5
            decision_config["decision_rules"]["accept_warnings"] = True
            decision_config["decision_rules"]["accept_after_max_retries"] = True

        self.decision_engine = decision_engine or (ValidationDecisionEngine(decision_config) if enable_validation else None)

        # TEL-04: Initialize telemetry integration
        self.telemetry = get_telemetry() if enable_telemetry else None

        # Thread safety locks for parallel processing
        self._tm_lock = Lock()
        self._model_lock = Lock()
        self._file_write_lock = Lock()

    def translate_file(
        self,
        site_id: str,
        file_path: Path,
        target_langs: List[str],
        force: bool = False,
        validate: Optional[bool] = None,
    ) -> TranslationResult:
        """
        Translate a single Hugo markdown file.

        Args:
            site_id: Site identifier for configuration
            file_path: Path to source markdown file
            target_langs: List of target language codes
            force: If True, bypass TM and force retranslation
            validate: Whether to validate translation quality. If None, uses engine default.

        Returns:
            TranslationResult with outcomes for all target languages
        """
        # TEL-04: Start telemetry tracking
        telemetry_enabled = self.enable_telemetry and self.telemetry and self.telemetry.is_available()
        telemetry_cm = None  # Context manager
        telemetry_run = None  # RunContext
        if telemetry_enabled:
            telemetry_cm = self.telemetry.track_translation_session(
                job_type="translate_file",
                trigger_type="cli",
                file_path=file_path,
                target_langs=target_langs,
                site_id=site_id,
                force=force,
            )
            telemetry_run = telemetry_cm.__enter__()

        result = TranslationResult(
            success=False,
            file_path=file_path,
        )
        start_time = time.time()

        try:
            # Get site profile
            site_profile = self.config.get_site_profile(site_id)
            if not site_profile:
                result.errors.append(f"Site profile not found: {site_id}")
                return result

            source_lang = site_profile.default_source_lang

            # Parse file
            logger.info(f"Parsing {file_path}")
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                doc = self.parser.parse_string(content)
                doc.source_path = file_path  # Set source path for output routing
            except Exception as e:
                result.errors.append(f"Parse error: {e}")
                return result

            # Extract segments
            extractor = SegmentExtractor(site_profile)
            segments = extractor.extract_all(doc, source_lang)
            result.stats.total_segments = len(segments)

            logger.info(
                f"Extracted {len(segments)} segments from {file_path}"
            )

            # INT-01: Translate for each target language with retry loop
            should_validate = validate if validate is not None else self.enable_validation
            max_retry_attempts = self.decision_engine.max_retry_attempts if self.decision_engine else 2

            for target_lang in target_langs:
                # Retry loop for this target language
                retry_count = 0
                retry_feedback = None
                translated_content = None
                final_decision = None
                final_validation_result = None

                while retry_count <= max_retry_attempts:
                    try:
                        # Translate (returns content, doesn't write yet)
                        translated_content = self._translate_to_language(
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
                        )

                        # Pre-write validation (if enabled)
                        if should_validate and self.validation_suite and self.decision_engine:
                            # Extract source body for validation
                            source_body = str(doc.body) if hasattr(doc, "body") else ""

                            # Parse translated content to get body
                            translated_doc = self.parser.parse_string(translated_content)
                            translated_body = str(translated_doc.body) if hasattr(translated_doc, "body") else ""

                            # Run validation suite
                            validation_result = self.validation_suite.validate(
                                source_body,
                                translated_body,
                                context={
                                    "source_lang": source_lang,
                                    "target_lang": target_lang,
                                    "file_path": str(file_path),
                                },
                            )

                            # Make decision
                            decision_result = self.decision_engine.make_decision(
                                validation_result=validation_result,
                                retry_count=retry_count,
                                source=source_body,
                            )

                            final_decision = decision_result
                            final_validation_result = validation_result

                            # Handle decision
                            if decision_result.decision == PostValidationDecision.REJECT:
                                # Don't write file, raise exception
                                raise TranslationRejectedError(
                                    message=f"Translation rejected: {decision_result.decision_reason}",
                                    file_path=str(file_path),
                                    validation_result=validation_result,
                                    rejection_reason=decision_result.decision_reason,
                                )

                            elif decision_result.decision == PostValidationDecision.RETRY:
                                # Retry with feedback
                                retry_count += 1
                                retry_feedback = decision_result.retry_feedback
                                result.stats.validation_retried += 1
                                logger.info(
                                    f"Retrying translation for {file_path} to {target_lang} "
                                    f"(attempt {retry_count}/{max_retry_attempts}): "
                                    f"{decision_result.decision_reason}"
                                )

                                # Track retry in result history
                                result.retry_history.append({
                                    "attempt": retry_count,
                                    "reason": decision_result.decision_reason,
                                    "feedback": retry_feedback,
                                })

                                continue  # Loop again with feedback

                            # ACCEPT - fall through to write file

                        # Write output file (only on ACCEPT or if validation disabled)
                        source_path = doc.source_path if hasattr(doc, "source_path") and doc.source_path else Path("output.md")
                        output_path = self._get_output_path(
                            source_path,
                            target_lang,
                            site_profile,
                        )
                        self._write_output(translated_content, output_path, source_path, result.stats)

                        # INT-05: Run post-write validation
                        post_write_passed = self._post_write_validation(
                            output_path=output_path,
                            source_path=source_path,
                            target_lang=target_lang,
                            site_id=site_id,
                            site_profile=site_profile,
                        )

                        if not post_write_passed:
                            logger.warning(f"Post-write validation failed for {output_path}, but file was written")

                        result.outputs[target_lang] = output_path

                        # Track validation decision in result
                        if final_decision:
                            result.validation_decision = ValidationDecision.ACCEPT if final_decision.decision == PostValidationDecision.ACCEPT else None
                            result.decision_reason = final_decision.decision_reason
                            result.retry_attempts = retry_count

                            # Update stats
                            result.stats.validation_passed = True
                            result.stats.validation_decision = "ACCEPT"
                            if final_validation_result:
                                result.stats.validation_errors = final_validation_result.error_count
                                result.stats.validation_warnings = final_validation_result.warning_count
                                result.stats.validation_info = final_validation_result.info_count

                        logger.info(f"Successfully translated {file_path} to {target_lang} after {retry_count} retries")
                        break  # Success, exit retry loop

                    except TranslationRejectedError:
                        # Re-raise rejection errors
                        result.errors.append(f"Translation to {target_lang} rejected after {retry_count} attempts")
                        result.stats.validation_failed = True
                        result.stats.validation_decision = "REJECT"
                        raise

                    except TranslationRetryableError as e:
                        # Handle retryable errors (from nested logic if needed)
                        retry_count += 1
                        retry_feedback = e.retry_feedback
                        if retry_count > max_retry_attempts:
                            raise TranslationRejectedError(
                                message=f"Failed after {retry_count} retries",
                                file_path=str(file_path),
                                validation_result=e.validation_result,
                                rejection_reason="Max retries exceeded",
                            )
                        continue

                    except Exception as e:
                        # Unexpected error - don't retry
                        logger.error(
                            f"Error translating {file_path} to {target_lang}: {e}"
                        )
                        result.errors.append(
                            f"Translation to {target_lang} failed: {e}"
                        )
                        break  # Exit retry loop on unexpected error

            # Mark success if at least one language succeeded
            result.success = len(result.outputs) > 0

        except Exception as e:
            logger.error(f"Unexpected error translating {file_path}: {e}")
            result.errors.append(f"Unexpected error: {e}")
            # TEL-04: Track error in telemetry
            if telemetry_run:
                telemetry_run.log_event("error", {"error": str(e)})

        finally:
            result.stats.files_translated = 1 if result.success else 0
            result.stats.files_generated = len(result.outputs)
            result.stats.duration_seconds = time.time() - start_time

            # TEL-04: Track stats and close telemetry
            if telemetry_run and telemetry_enabled:
                try:
                    self.telemetry.track_translation_stats(telemetry_run, result.stats)
                    # Track additional result metrics (TEL-05-A/B)
                    error_summary = "; ".join(result.errors[:3]) if result.errors else ""  # TEL-05-B
                    telemetry_run.set_metrics(
                        items_discovered=result.stats.total_segments,
                        items_succeeded=result.stats.translated_segments + result.stats.tm_hits,
                        items_failed=result.stats.skipped_segments,
                        output_summary=f"{len(result.outputs)} translations, {len(result.errors)} errors",
                        error_summary=error_summary,  # TEL-05-B
                    )
                    telemetry_cm.__exit__(None, None, None)
                except Exception as telemetry_error:
                    logger.warning(f"Telemetry tracking failed: {telemetry_error}")

        return result

    def _translate_to_language(
        self,
        site_id: str,
        site_profile,
        doc,
        segments: List,
        source_lang: str,
        target_lang: str,
        force: bool,
        stats: TranslationStats,
        retry_feedback: Optional[str] = None,
        retry_count: int = 0,
    ) -> str:
        """
        Translate document to a specific target language.

        INT-01: Modified to return translated content without writing.
        INT-02: Added retry feedback integration and temperature variation.

        This method performs translation and returns the translated content
        WITHOUT writing to disk. The caller is responsible for writing the
        file after validation.

        Retry feedback is prepended to source texts to guide the model toward
        fixing validation issues. Temperature increases with retry count to
        encourage more creative solutions (when model backends support it).

        Args:
            site_id: Site identifier
            site_profile: Site profile configuration
            doc: Parsed HugoDocument
            segments: Extracted segments
            source_lang: Source language code
            target_lang: Target language code
            force: Bypass TM if True
            stats: Stats object to update
            retry_feedback: Optional feedback from previous validation failure.
                          If provided, prepended to all source texts.
            retry_count: Current retry attempt number (0 for first attempt).
                        Used to calculate temperature variation.

        Returns:
            Translated document content as string (not yet written to disk)
        """
        # Create translation map: segment text -> translation
        translations = {}
        segments_to_translate = []

        # Step 1: TM lookup (unless force=True)
        if not force:
            for segment in segments:
                # TMO-03: Build lookup context for override filtering
                lookup_context = {
                    "target_lang": target_lang,
                }
                if segment.context:
                    if hasattr(segment.context, "frontmatter_key") and segment.context.frontmatter_key:
                        lookup_context["frontmatter_key"] = segment.context.frontmatter_key
                    if hasattr(segment.context, "context_type"):
                        lookup_context["context_type"] = str(segment.context.context_type)

                # Try TM lookup
                tm_result = self.tm.lookup(
                    site_id=site_id,
                    src_lang=source_lang,
                    tgt_lang=target_lang,
                    text=segment.source_text,
                    context=str(segment.context) if segment.context else None,
                    lookup_context=lookup_context,
                )

                if tm_result.hit:
                    restored = self._restore_placeholders(
                        tm_result.translation or "", segment
                    )
                    # TM hit! Use segment.id as key (must match reconstructor lookup)
                    translations[segment.id] = restored
                    stats.tm_hits += 1

                    # Track which layer hit
                    if tm_result.source == "l1_cache":
                        stats.l1_hits += 1
                    elif tm_result.source == "l2_exact":
                        stats.l2_hits += 1
                    elif tm_result.source == "l3_semantic":
                        stats.l3_hits += 1

                    # Track cached tokens (estimate input + output)
                    # TEL-04: Count tokens saved by cache hit
                    cached_input_tokens = estimate_token_count(segment.source_text)
                    cached_output_tokens = estimate_token_count(tm_result.translation)
                    stats.tokens_cached += cached_input_tokens + cached_output_tokens
                else:
                    # Need to translate
                    segments_to_translate.append(segment)

        else:
            # Force mode: translate everything
            segments_to_translate = segments

        # Step 2: Translate new segments via model
        if segments_to_translate:
            logger.info(
                f"Translating {len(segments_to_translate)} new segments "
                f"from {source_lang} to {target_lang}"
                + (f" (retry {retry_count} with feedback)" if retry_count > 0 else "")
            )

            # Get model
            model_id = getattr(site_profile, 'default_model', None) or "m2m100_418m"
            backend = self.model_loader.load_model(model_id)
            stats.model_used = model_id

            # INT-02: Prepare translation texts
            texts = [seg.source_text for seg in segments_to_translate]

            # INT-02: If retry_feedback provided, prepend to translation texts
            if retry_feedback:
                texts_with_feedback = [
                    f"{retry_feedback}\n\nSOURCE TEXT:\n{text}"
                    for text in texts
                ]
                texts = texts_with_feedback
                logger.debug(f"Applied retry feedback to {len(texts)} segments")

            # INT-02: Calculate temperature variation on retry
            # Note: Current model backends don't support temperature parameter yet,
            # but we calculate it here for future use when backends are updated
            base_temperature = 0.7  # Default
            if retry_count > 0:
                temperature_increment = 0.1  # Could be config from site_profile in future
                max_temperature = 1.0
                temperature = min(
                    base_temperature + (retry_count * temperature_increment),
                    max_temperature
                )
                logger.debug(f"Retry {retry_count}: temperature adjusted to {temperature}")
            else:
                temperature = base_temperature
            try:
                # MSP-02: Translate with multiline structure preservation
                translated_texts = self._translate_with_multiline_support(
                    backend=backend,
                    segments=segments_to_translate,
                    texts=texts,
                    source_lang=source_lang,
                    target_lang=target_lang,
                    stats=stats,
                )

                # Store results in translations map and TM
                for segment, translation in zip(
                    segments_to_translate, translated_texts
                ):
                    translation = self._restore_placeholders(translation, segment)
                    # Use segment.id as key (must match reconstructor lookup)
                    translations[segment.id] = translation
                    stats.translated_segments += 1
                    stats.words_translated += len(segment.source_text.split())

                    # TMO-03: Build store context for override filtering
                    store_context = {
                        "target_lang": target_lang,
                    }
                    if segment.context:
                        if hasattr(segment.context, "frontmatter_key") and segment.context.frontmatter_key:
                            store_context["frontmatter_key"] = segment.context.frontmatter_key
                        if hasattr(segment.context, "context_type"):
                            store_context["context_type"] = str(segment.context.context_type)

                    # Store in TM for future use (respects override mode)
                    self.tm.store(
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
                        force_update=force,  # Force mode updates cache with new translations
                    )
                    # TEL-04: Track TM entry storage
                    stats.tm_entries_stored += 1

            except Exception as e:
                logger.error(f"Model translation failed: {e}")
                raise RuntimeError(f"Translation failed: {e}")

        # Step 3: Reconstruct document
        reconstructor = MarkdownReconstructor(site_profile)
        translated_doc = reconstructor.reconstruct_document(
            doc, translations, target_lang
        )

        # INT-01: Return translated content without writing (writing moved to retry loop)
        translated_content = str(translated_doc)

        # TEL-04: Calculate total tokens (cached + translated)
        stats.tokens_total = stats.tokens_cached + stats.tokens_input + stats.tokens_output

        return translated_content

    def _write_output(
        self, content: str, output_path: Path, source_path: Path, stats: TranslationStats
    ) -> None:
        """
        Write translated content to output file.

        Args:
            content: Translated markdown content
            output_path: Path to write the output file
            source_path: Original source file path (for logging)
            stats: Stats object to update with file operation metrics

        Raises:
            IOError: If file writing fails
        """
        # Create output directories if needed
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # TEL-04: Track file operation (add vs. update)
        file_existed = output_path.exists()

        # Write translated content
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)

        # TEL-04: Update file operation stats
        if file_existed:
            stats.md_files_updated += 1
        else:
            stats.md_files_added += 1
        stats.bytes_written_md += len(content.encode('utf-8'))

        logger.info(f"Written translated file: {output_path}")

    def _get_output_path(
        self, source_path: Path, target_lang: str, site_profile
    ) -> Path:
        """
        Determine output path for translated file.

        Args:
            source_path: Original file path
            target_lang: Target language code
            site_profile: Site profile

        Returns:
            Output file path
        """
        # Check if site profile uses Hugo sibling folder pattern
        output_layout = getattr(site_profile, 'output_layout', None)
        per_language_folders = False
        if output_layout:
            per_language_folders = getattr(output_layout, 'per_language_folders', False) if hasattr(output_layout, 'per_language_folders') else output_layout.get('per_language_folders', False)

        source_lang = getattr(site_profile, 'default_source_lang', 'en')

        if per_language_folders:
            # Hugo sibling folder pattern: replace /en/ with /{target_lang}/
            source_str = str(source_path)
            # Try to find and replace the source language folder
            # Handle both forward and back slashes
            for sep in ['/', '\\']:
                source_folder = f"{sep}{source_lang}{sep}"
                target_folder = f"{sep}{target_lang}{sep}"
                if source_folder in source_str:
                    output_path = Path(source_str.replace(source_folder, target_folder, 1))
                    return output_path

            # Also check if path ends with /en (folder name without trailing separator)
            for sep in ['/', '\\']:
                if source_str.endswith(f"{sep}{source_lang}"):
                    output_path = Path(source_str[:-len(source_lang)] + target_lang)
                    return output_path

        # Fallback: use output directory from site profile
        output_dir = Path(getattr(site_profile, 'output_dir', None) or "output")

        # Construct output path: output/{lang}/{relative_path}
        output_path = output_dir / target_lang / source_path.name

        return output_path

    def translate_directory(
        self,
        site_id: str,
        directory: Path,
        target_langs: List[str],
        recursive: bool = True,
        parallel: bool = True,
        max_workers: Optional[int] = None,
    ) -> DirectoryResult:
        """
        Translate all eligible files in a directory.

        Args:
            site_id: Site identifier
            directory: Directory to scan
            target_langs: List of target language codes
            recursive: If True, scan subdirectories
            parallel: If True, process files in parallel (default: True)
            max_workers: Maximum number of parallel workers (default: auto)

        Returns:
            DirectoryResult with outcomes for all files
        """
        # TEL-04: Start telemetry tracking for batch operation
        telemetry_enabled = self.enable_telemetry and self.telemetry and self.telemetry.is_available()
        telemetry_cm = None  # Context manager
        telemetry_run = None  # RunContext
        if telemetry_enabled:
            telemetry_cm = self.telemetry.track_translation_session(
                job_type="translate_directory",
                trigger_type="cli",
                directory=str(directory),
                target_langs=target_langs,
                site_id=site_id,
                recursive=recursive,
                parallel=parallel,
            )
            telemetry_run = telemetry_cm.__enter__()

        result = DirectoryResult(
            success=False,
            directory=directory,
        )
        start_time = time.time()

        try:
            # Find markdown files
            pattern = "**/*.md" if recursive else "*.md"
            md_files = list(directory.glob(pattern))

            logger.info(
                f"Found {len(md_files)} markdown files in {directory}"
            )
            result.total_files = len(md_files)

            if not md_files:
                logger.warning(f"No markdown files found in {directory}")
                result.success = True
                return result

            # Choose processing mode
            if parallel and len(md_files) > 1:
                # Parallel processing for better performance
                result = self._translate_directory_parallel(
                    site_id, md_files, target_langs, result, max_workers
                )
            else:
                # Sequential processing
                result = self._translate_directory_sequential(
                    site_id, md_files, target_langs, result
                )

            result.success = result.successful_files > 0

        except Exception as e:
            logger.error(f"Error translating directory {directory}: {e}")
            result.failed_files = result.total_files
            # TEL-04: Track error in telemetry
            if telemetry_run:
                telemetry_run.log_event("error", {"error": str(e)})

        finally:
            result.duration_seconds = time.time() - start_time
            logger.info(
                f"Directory translation completed: "
                f"{result.successful_files}/{result.total_files} files "
                f"in {result.duration_seconds:.2f}s"
            )

            # TEL-04: Track aggregated stats and close telemetry
            if telemetry_run and telemetry_enabled:
                try:
                    # Get aggregated stats across all files
                    agg_stats = result.aggregate_stats
                    self.telemetry.track_translation_stats(telemetry_run, agg_stats)
                    # Track additional directory-level metrics (TEL-05-A/B)
                    # Calculate files_generated from all output files across results
                    files_generated = sum(
                        len(fr.outputs) for fr in result.file_results
                    )
                    # Collect errors from failed files (TEL-05-B)
                    all_errors = []
                    for fr in result.file_results:
                        if fr.errors:
                            all_errors.extend(fr.errors[:2])  # Max 2 per file
                    error_summary = "; ".join(all_errors[:5]) if all_errors else ""  # Max 5 total
                    telemetry_run.set_metrics(
                        total_files=result.total_files,
                        items_discovered=result.total_files,
                        items_succeeded=result.successful_files,
                        items_failed=result.failed_files,
                        output_summary=f"{result.successful_files}/{result.total_files} files translated, {files_generated} outputs",
                        error_summary=error_summary,  # TEL-05-B
                    )
                    telemetry_cm.__exit__(None, None, None)
                except Exception as telemetry_error:
                    logger.warning(f"Telemetry tracking failed: {telemetry_error}")

        return result

    def _translate_directory_sequential(
        self,
        site_id: str,
        md_files: List[Path],
        target_langs: List[str],
        result: DirectoryResult,
    ) -> DirectoryResult:
        """
        Translate files sequentially.

        Args:
            site_id: Site identifier
            md_files: List of markdown files to translate
            target_langs: Target languages
            result: DirectoryResult to update

        Returns:
            Updated DirectoryResult
        """
        for md_file in md_files:
            try:
                file_result = self.translate_file(
                    site_id=site_id,
                    file_path=md_file,
                    target_langs=target_langs,
                )
                result.file_results.append(file_result)

                if file_result.success:
                    result.successful_files += 1
                else:
                    result.failed_files += 1

            except Exception as e:
                logger.error(f"Error translating {md_file}: {e}")
                result.failed_files += 1

        return result

    def _translate_directory_parallel(
        self,
        site_id: str,
        md_files: List[Path],
        target_langs: List[str],
        result: DirectoryResult,
        max_workers: Optional[int] = None,
    ) -> DirectoryResult:
        """
        Translate files in parallel using ThreadPoolExecutor.

        Args:
            site_id: Site identifier
            md_files: List of markdown files to translate
            target_langs: Target languages
            result: DirectoryResult to update
            max_workers: Maximum number of workers

        Returns:
            Updated DirectoryResult
        """
        # Determine optimal number of workers
        if max_workers is None:
            # Use min(32, CPU count + 4) as recommended by Python docs
            max_workers = min(32, (os.cpu_count() or 1) + 4)

        logger.info(f"Translating {len(md_files)} files with {max_workers} workers")

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all translation jobs
            future_to_file = {
                executor.submit(
                    self._translate_file_safe, site_id, md_file, target_langs
                ): md_file
                for md_file in md_files
            }

            # Collect results as they complete
            for future in as_completed(future_to_file):
                md_file = future_to_file[future]
                try:
                    file_result = future.result()
                    result.file_results.append(file_result)

                    if file_result.success:
                        result.successful_files += 1
                        logger.debug(f"✓ Translated {md_file.name}")
                    else:
                        result.failed_files += 1
                        logger.warning(f"✗ Failed {md_file.name}: {file_result.errors}")

                except Exception as e:
                    logger.error(f"Error processing {md_file}: {e}")
                    result.failed_files += 1

        return result

    def _translate_file_safe(
        self, site_id: str, file_path: Path, target_langs: List[str]
    ) -> TranslationResult:
        """
        Thread-safe wrapper for translate_file.

        Ensures proper synchronization for shared resources (TM, models).

        Args:
            site_id: Site identifier
            file_path: Path to file
            target_langs: Target languages

        Returns:
            TranslationResult
        """
        try:
            # The translate_file method will use locks internally where needed
            return self.translate_file(
                site_id=site_id, file_path=file_path, target_langs=target_langs
            )
        except Exception as e:
            logger.error(f"Error in _translate_file_safe for {file_path}: {e}")
            return TranslationResult(
                success=False,
                file_path=file_path,
                errors=[str(e)],
            )

    def extract_segments(
        self, site_id: str, file_path: Path
    ) -> List:
        """
        Extract segments from a file without translating.

        Useful for previewing what will be translated.

        Args:
            site_id: Site identifier
            file_path: Path to markdown file

        Returns:
            List of Segment objects
        """
        site_profile = self.config.get_site_profile(site_id)
        if not site_profile:
            raise ValueError(f"Site profile not found: {site_id}")

        # Parse file
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        doc = self.parser.parse_string(content)

        # Extract segments
        extractor = SegmentExtractor(site_profile)
        source_lang = site_profile.default_source_lang
        segments = extractor.extract_all(doc, source_lang)

        return segments

    def _validate_translation(
        self,
        file_path: Path,
        doc,
        segments: List,
        outputs: Dict[str, Path],
        source_lang: str,
    ):
        """
        Validate translation quality.

        Args:
            file_path: Source file path
            doc: Source HugoDocument
            segments: Extracted segments
            outputs: Dictionary of target_lang -> output_path
            source_lang: Source language code

        Returns:
            ValidationResult with any issues found
        """
        if not self.validation_suite:
            return None

        from .validation import ValidationResult as VResult

        aggregate_result = VResult(success=True)

        try:
            # Read source body (excluding frontmatter)
            source_body = str(doc.body) if hasattr(doc, "body") else ""

            # Validate each target language output
            for target_lang, output_path in outputs.items():
                if not output_path.exists():
                    continue

                # Read translated file
                with open(output_path, "r", encoding="utf-8") as f:
                    translated_content = f.read()

                # Parse translated document
                translated_doc = self.parser.parse_string(translated_content)
                translated_body = (
                    str(translated_doc.body) if hasattr(translated_doc, "body") else ""
                )

                # Validate body
                validation_result = self.validation_suite.validate(
                    source_body,
                    translated_body,
                    context={
                        "source_lang": source_lang,
                        "target_lang": target_lang,
                        "file_path": str(file_path),
                    },
                )

                aggregate_result.merge(validation_result)

        except Exception as e:
            logger.warning(f"Validation failed for {file_path}: {e}")

        return aggregate_result

    def get_tm_stats(self, site_id: str) -> Dict:
        """
        Get Translation Memory statistics for a site.

        Args:
            site_id: Site identifier

        Returns:
            Dictionary with TM statistics
        """
        return self.tm.get_stats(site_id)

    def clear_tm(
        self,
        site_id: str,
        src_lang: Optional[str] = None,
        tgt_lang: Optional[str] = None,
    ) -> None:
        """
        Clear Translation Memory entries.

        Args:
            site_id: Site identifier
            src_lang: Optional source language filter
            tgt_lang: Optional target language filter
        """
        self.tm.clear(site_id, src_lang, tgt_lang)
        logger.info(f"Cleared TM for site={site_id}, src={src_lang}, tgt={tgt_lang}")

    def _post_write_validation(
        self,
        output_path: Path,
        source_path: Path,
        target_lang: str,
        site_id: str,
        site_profile,
    ) -> bool:
        """
        Perform post-write validation on a written file.

        Validates that:
        - File exists at expected path
        - File is readable
        - File has content (not empty)
        - File is in correct language folder structure

        Args:
            output_path: Path to the written file
            source_path: Original source file path
            target_lang: Target language code
            site_id: Site identifier
            site_profile: Site profile configuration

        Returns:
            True if validation passes, False if validation fails

        Raises:
            RuntimeError: If validation fails and halt_on_failure is enabled
        """
        # Skip post-write validation when validation is disabled
        if not self.enable_validation:
            return True

        # Check if post-write validation is enabled
        validation_config = self.config.get_config()
        if not validation_config:
            return True

        # Get validation defaults
        validation_defaults = validation_config.get("validation_defaults", {})
        post_write_config = validation_defaults.get("post_write", {})

        # Check if post-write validation is enabled (default: True)
        if not post_write_config.get("enabled", True):
            logger.debug("Post-write validation disabled, skipping")
            return True

        # Import FilePlacementValidator
        from .validation.file_placement_validator import FilePlacementValidator

        # Create validator instance
        validator = FilePlacementValidator(config_service=self.config)

        # Prepare validation context
        source_lang = getattr(site_profile, "default_source_lang", "en")
        context = {
            "source_path": source_path,
            "source_lang": source_lang,
            "target_lang": target_lang,
            "site_id": site_id,
            "site_profile": site_profile,
        }

        # Validate written file
        logger.debug(f"Running post-write validation on {output_path}")
        result = validator.validate_written_file(output_path, context)

        # Handle validation result
        if not result.success:
            logger.error(
                f"Post-write validation failed for {output_path}: "
                f"{result.error_count} errors, {result.warning_count} warnings"
            )

            # Log all issues
            for issue in result.issues:
                log_level = (
                    logger.error
                    if issue.severity.value == "error"
                    else logger.warning
                )
                log_level(f"  - [{issue.severity.value.upper()}] {issue.message}")

            # Delete file if configured
            delete_on_failure = post_write_config.get("delete_on_failure", False)
            if delete_on_failure:
                try:
                    logger.warning(f"Deleting invalid file: {output_path}")
                    output_path.unlink()
                except Exception as e:
                    logger.error(f"Failed to delete invalid file {output_path}: {e}")

            # Halt if configured
            halt_on_failure = post_write_config.get("halt_on_failure", False)
            if halt_on_failure:
                raise RuntimeError(
                    f"Post-write validation failed for {output_path}. "
                    f"Errors: {result.error_count}, Warnings: {result.warning_count}"
                )

            return False
        else:
            logger.debug(
                f"Post-write validation passed for {output_path} "
                f"({result.warning_count} warnings)"
            )
            # Log warnings if any
            if result.warning_count > 0:
                for issue in result.issues:
                    if issue.severity.value == "warning":
                        logger.warning(f"  - [WARNING] {issue.message}")
            return True

    def set_override_mode(
        self,
        mode: str,
        filters: Optional[Dict] = None,
    ) -> None:
        """
        Set the TM cache override mode at runtime.

        TMO-03: Allows changing override behavior without recreating engine.

        Args:
            mode: Override mode string (normal, bypass, refresh, validate)
            filters: Optional filter configuration dict with keys:
                - source_patterns: List of regex patterns to match source text
                - target_langs: List of target language codes to match
                - frontmatter_keys: List of frontmatter keys to match
        """
        mode_map = {
            "normal": OverrideMode.NORMAL,
            "bypass": OverrideMode.BYPASS,
            "refresh": OverrideMode.REFRESH,
            "validate": OverrideMode.VALIDATE,
        }
        override_mode = mode_map.get(mode.lower(), OverrideMode.NORMAL)
        self.tm.set_override_mode(override_mode, filters)
        logger.info(f"TM override mode set to: {mode}")

    def get_override_stats(self) -> Dict:
        """
        Get TM cache override statistics.

        TMO-03: Returns statistics about cache bypass/refresh operations.

        Returns:
            Dict with override stats including mode, bypass counts, and filter info
        """
        return self.tm.get_override_stats()

    def _restore_placeholders(self, text: str, segment) -> str:
        """
        Restore placeholder content (links, shortcodes, etc.) in translated text.
        """
        if not text or not getattr(segment, "placeholder_map", None):
            return text
        try:
            return self.placeholder_manager.restore(text, segment.placeholder_map)
        except Exception as e:
            logger.warning(f"Placeholder restore failed: {e}")
            return text

    def _translate_with_multiline_support(
        self,
        backend,
        segments: List,
        texts: List[str],
        source_lang: str,
        target_lang: str,
        stats: TranslationStats,
    ) -> List[str]:
        """
        Translate texts with multiline structure preservation.

        MSP-02: For segments containing newlines, uses the MultilineHandler to:
        1. Split text into individual lines
        2. Translate each line separately
        3. Reassemble with preserved structure (indentation, bullets, etc.)

        Single-line texts are translated normally in batch for efficiency.

        Args:
            backend: Translation model backend
            segments: List of segments being translated
            texts: List of source texts (may include retry feedback prefix)
            source_lang: Source language code
            target_lang: Target language code
            stats: Stats object to update with token counts

        Returns:
            List of translated texts with structure preserved
        """
        translated_texts = []

        # Separate multiline and single-line segments for efficient processing
        multiline_indices = []
        singleline_indices = []
        singleline_texts = []

        for idx, (segment, text) in enumerate(zip(segments, texts)):
            # Check the original segment source_text for multiline content
            # (not the possibly-modified text which may have feedback prefix)
            if self.multiline_handler.is_multiline(segment.source_text):
                multiline_indices.append(idx)
            else:
                singleline_indices.append(idx)
                singleline_texts.append(text)

        # Initialize result list with placeholders
        translated_texts = [None] * len(texts)

        # Translate single-line texts in batch (efficient)
        if singleline_texts:
            if hasattr(backend, 'translate_with_token_counts'):
                batch_translations, input_tokens, output_tokens = backend.translate_with_token_counts(
                    singleline_texts, source_lang, target_lang
                )
                stats.tokens_input += input_tokens
                stats.tokens_output += output_tokens
            else:
                batch_translations = backend.translate(
                    singleline_texts, source_lang, target_lang
                )
                stats.tokens_input += sum(estimate_token_count(t) for t in singleline_texts)
                stats.tokens_output += sum(estimate_token_count(t) for t in batch_translations)

            # Place results in correct positions
            for list_idx, original_idx in enumerate(singleline_indices):
                translated_texts[original_idx] = batch_translations[list_idx]

        # Translate multiline texts with structure preservation
        if multiline_indices:
            logger.info(
                f"MSP-02: Processing {len(multiline_indices)} multiline segments "
                f"with structure preservation"
            )

            for original_idx in multiline_indices:
                segment = segments[original_idx]
                text = texts[original_idx]

                # Create a translation function that calls the backend for single lines
                def translate_line(line_text: str) -> str:
                    """Translate a single line via backend."""
                    if not line_text.strip():
                        return line_text

                    if hasattr(backend, 'translate_with_token_counts'):
                        translations, in_tok, out_tok = backend.translate_with_token_counts(
                            [line_text], source_lang, target_lang
                        )
                        stats.tokens_input += in_tok
                        stats.tokens_output += out_tok
                        return translations[0]
                    else:
                        translations = backend.translate(
                            [line_text], source_lang, target_lang
                        )
                        stats.tokens_input += estimate_token_count(line_text)
                        stats.tokens_output += estimate_token_count(translations[0])
                        return translations[0]

                # Use multiline handler for structure-preserving translation
                result = self.multiline_handler.translate(text, translate_line)

                if not result.structure_preserved:
                    logger.warning(
                        f"MSP-02: Structure drift in segment {segment.id}: "
                        f"{result.line_count_source} -> {result.line_count_translated} lines"
                    )

                translated_texts[original_idx] = result.translated_text

                logger.debug(
                    f"MSP-02: Multiline segment {segment.id} translated with "
                    f"{result.line_count_source} lines preserved"
                )

        return translated_texts
