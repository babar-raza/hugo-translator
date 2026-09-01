"""
Directory orchestration for translation engine.

Handles directory scanning, file filtering, completion-aware prioritization,
sequential/parallel dispatch, and telemetry for batch translation runs.

Extracted from TranslationEngine to reduce god-class complexity while
preserving identical behavior.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING

from ..tm.retranslate_queue import (
    load_queued_llm_paths as _rtq_load_llm,
)
from ..tm.retranslate_queue import (
    load_queued_paths as _rtq_load,
)
from ..utils.file_filters import filter_source_files
from ..utils.file_lock import FileLock, LockError
from ..utils.locale_policy import validate_requested_locales
from .models import DirectoryResult, TranslationResult

if TYPE_CHECKING:
    from .engine import TranslationEngine

logger = logging.getLogger(__name__)


class DirectoryOrchestrator:
    """Orchestrates directory-level translation: scan, filter, dispatch, telemetry."""

    def __init__(self, engine: TranslationEngine) -> None:
        self._engine = engine

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def translate_directory(
        self,
        site_id: str,
        directory: Path,
        target_langs: list[str],
        recursive: bool = True,
        parallel: bool = True,
        max_workers: int | None = None,
        skip_site_lock: bool = False,
        trigger_type: str = "cli",
        max_files: int = 0,
        skip_first: int = 0,
        run_deadline: float | None = None,
    ) -> DirectoryResult:
        """Translate all eligible files in a directory.

        Args:
            site_id: Site identifier
            directory: Directory to scan
            target_langs: List of target language codes
            recursive: If True, scan subdirectories
            parallel: If True, process files in parallel (default: True)
            max_workers: Maximum number of parallel workers (default: auto)
            skip_site_lock: If True, skip lock acquisition (parent holds lock) - TC1
            trigger_type: How translation was triggered ("cli", "scheduled", "web", etc.)
            max_files: Maximum number of files to process (0=unlimited, default: 0)
            skip_first: Number of files to skip from the start (for chunked pagination, default: 0)
            run_deadline: Optional epoch timestamp; stop processing when reached.

        Returns:
            DirectoryResult with outcomes for all files

        Raises:
            LockError: If another translation is already in progress for this site
            LocalePolicyViolation: If a strict_locale_allowlist site is asked
                to translate a locale outside its target_langs
        """
        # Locale allowlist policy: reject any target locale outside
        # target_langs before doing any work (lock, scan, telemetry), for
        # sites with strict_locale_allowlist set. No-op otherwise.
        site_profile = self._engine.config.get_site_profile(site_id)
        if site_profile:
            validate_requested_locales(site_profile, target_langs)

        # TC2: AUTO-CLEANUP: Remove stale locks older than 24 hours on startup
        lock_dir = Path(".translation_progress") / "locks"
        if lock_dir.exists():
            for lock_file in lock_dir.glob("*.lock"):
                try:
                    age = time.time() - lock_file.stat().st_mtime
                    if age > 86400:  # 24 hours
                        logger.info(f"Auto-removing stale lock (>24h old): {lock_file}")
                        lock_file.unlink()
                except Exception as e:
                    logger.debug(f"Could not check/remove {lock_file}: {e}")

        # TC1: Skip lock acquisition if parent process holds it
        if skip_site_lock:
            logger.info(f"Skipping site lock acquisition (parent holds lock for {site_id})")
            return self._translate_directory_locked(
                site_id,
                directory,
                target_langs,
                recursive,
                parallel,
                max_workers,
                trigger_type,
                max_files,
                skip_first,
                run_deadline,
            )

        # RES-08: Create lock to prevent concurrent translations of same site
        lock_dir = Path(".translation_progress") / "locks"
        lock_file = lock_dir / f"{site_id}.lock"
        lock = FileLock(lock_file, timeout=300.0)  # 5 minute timeout

        try:
            logger.info(f"Acquiring translation lock for site: {site_id}")
            if not lock.acquire(blocking=True):
                raise LockError(
                    f"Another translation is in progress for site '{site_id}'. "
                    f"Wait for it to complete or remove lock file: {lock_file}"
                )
            logger.debug("Lock acquired, starting translation")
        except LockError:
            raise

        try:
            return self._translate_directory_locked(
                site_id,
                directory,
                target_langs,
                recursive,
                parallel,
                max_workers,
                trigger_type,
                max_files,
                skip_first,
                run_deadline,
            )
        finally:
            # RES-08: Always release lock
            lock.release()

    # ------------------------------------------------------------------
    # Internal: locked directory translation
    # ------------------------------------------------------------------

    def _translate_directory_locked(
        self,
        site_id: str,
        directory: Path,
        target_langs: list[str],
        recursive: bool = True,
        parallel: bool = True,
        max_workers: int | None = None,
        trigger_type: str = "cli",
        max_files: int = 0,
        skip_first: int = 0,
        run_deadline: float | None = None,
    ) -> DirectoryResult:
        """Internal implementation of translate_directory (called while holding lock)."""
        engine = self._engine
        from ..observability.telemetry_integration import _safe_duration_ms

        # TEL-04: Start telemetry tracking for batch operation
        telemetry_enabled = (
            engine.enable_telemetry and engine.telemetry and engine.telemetry.is_available()
        )
        telemetry_cm = None
        telemetry_run = None

        # SR-01: Find first markdown file to extract business context
        representative_file = None
        if telemetry_enabled:
            pattern = "**/*.md" if recursive else "*.md"
            md_files_for_context = list(directory.glob(pattern))
            if md_files_for_context:
                representative_file = md_files_for_context[0]

        if telemetry_enabled:
            telemetry_cm = engine.telemetry.track_translation_session(
                job_type="translate_directory",
                trigger_type=trigger_type,
                directory=str(directory),
                file_path=representative_file,
                target_langs=target_langs,
                site_id=site_id,
                recursive=recursive,
                parallel=parallel,
            )
            telemetry_run = telemetry_cm.__enter__()

            # GS-02: Register telemetry context for graceful shutdown
            try:
                from ..observability.graceful_shutdown import register_active_context

                register_active_context(telemetry_run)
            except ImportError:
                pass

        result = DirectoryResult(
            success=False,
            directory=directory,
        )
        start_time = time.time()

        try:
            # Find markdown files
            pattern = "**/*.md" if recursive else "*.md"
            md_files = list(directory.glob(pattern))

            logger.info(f"Found {len(md_files)} markdown files in {directory}")

            # Filter files based on localization strategy
            site_profile = engine.config.get_site_profile(site_id)
            if site_profile:
                md_files = filter_source_files(md_files, site_profile, target_langs)
                logger.info(f"After filtering: {len(md_files)} source files to translate")

            # Git diff change detection
            if engine.changed_since_sha and md_files:
                from ..utils.file_filters import git_changed_files

                _git_changed = git_changed_files(directory, engine.changed_since_sha)
                if _git_changed is not None:
                    _before = len(md_files)
                    md_files = [f for f in md_files if f.resolve() in _git_changed]
                    logger.info(
                        "Git diff filter (--changed-since %s): %d -> %d files",
                        engine.changed_since_sha[:12],
                        _before,
                        len(md_files),
                    )

            # Completion-aware filtering
            if site_profile and md_files and not engine.force_retranslate:
                try:
                    _queued_output_paths = _rtq_load()
                except Exception:
                    _queued_output_paths = set()

                try:
                    engine._rtq_llm_output_paths = _rtq_load_llm()
                except Exception:
                    engine._rtq_llm_output_paths = set()

                # WS-COMP-6: Quality-aware filter settings
                _quality_filter_enabled = False
                _quality_filter_ttl_days = 7
                _quality_filter_confidence = 0.80
                _quality_filter_paragraphs = 2
                try:
                    _feat_cfg = (
                        engine.config.get_config().get("features", {})
                        if hasattr(engine.config, "get_config")
                        else {}
                    )
                    _quality_filter_enabled = _feat_cfg.get(
                        "enable_quality_aware_completion_filter", False
                    )
                    if _quality_filter_enabled:
                        _quality_filter_ttl_days = _feat_cfg.get("quality_aware_filter_ttl_days", 7)
                        _quality_filter_confidence = _feat_cfg.get(
                            "quality_aware_filter_confidence", 0.80
                        )
                        _quality_filter_paragraphs = _feat_cfg.get(
                            "quality_aware_filter_paragraphs", 2
                        )
                except Exception:
                    pass

                _incomplete_with_priority: list[tuple] = []
                skipped_complete = 0
                queued_force_included = 0
                for f in md_files:
                    try:
                        source_mtime = f.stat().st_mtime
                    except OSError:
                        _incomplete_with_priority.append((f, True))
                        continue

                    all_outputs_current = True
                    any_output_queued = False
                    any_output_missing = False
                    for lang in target_langs:
                        output_p = engine._get_output_path(f, lang, site_profile)
                        if _queued_output_paths and str(output_p.resolve()) in _queued_output_paths:
                            any_output_queued = True
                        try:
                            if not output_p.exists():
                                any_output_missing = True
                                all_outputs_current = False
                            elif output_p.stat().st_mtime < source_mtime:
                                all_outputs_current = False
                        except OSError:
                            any_output_missing = True
                            all_outputs_current = False

                    if any_output_queued:
                        _incomplete_with_priority.append((f, True))
                        queued_force_included += 1
                    elif all_outputs_current:
                        _quality_filter_failed = False
                        if _quality_filter_enabled:
                            try:
                                _quality_filter_failed = self._quality_check_complete_file(
                                    source_path=f,
                                    target_langs=target_langs,
                                    site_profile=site_profile,
                                    ttl_days=_quality_filter_ttl_days,
                                    confidence=_quality_filter_confidence,
                                    max_paragraphs=_quality_filter_paragraphs,
                                )
                            except Exception as _qe:
                                logger.debug(f"Quality filter check failed for {f.name}: {_qe}")
                        if _quality_filter_failed:
                            _incomplete_with_priority.append((f, False))
                        else:
                            skipped_complete += 1
                    else:
                        _incomplete_with_priority.append((f, any_output_missing))

                if skipped_complete > 0 or queued_force_included > 0:
                    logger.info(
                        f"Completion check: skipped {skipped_complete} up-to-date files, "
                        f"force-included {queued_force_included} queued files, "
                        f"{len(_incomplete_with_priority)} files need work. "
                        f"Use --force-retranslate to reprocess all completed files."
                    )
                md_files = [f for f, _ in _incomplete_with_priority]
                _priority_flags = {f: has_missing for f, has_missing in _incomplete_with_priority}
                result.completion_filter_skipped = skipped_complete
            else:
                _priority_flags = dict.fromkeys(md_files, True)

            # Sort deterministically for pagination
            _file_priority_strategy = "alphabetical"
            if site_profile:
                try:
                    _te_cfg = (
                        engine.config.get_config().get("translation_engine", {})
                        if hasattr(engine.config, "get_config")
                        else {}
                    )
                    _file_priority_strategy = _te_cfg.get("file_priority_strategy", "missing_first")
                except Exception:
                    _file_priority_strategy = "missing_first"

            if _file_priority_strategy == "missing_first" and _priority_flags:
                md_files = sorted(
                    md_files,
                    key=lambda f: (0 if _priority_flags.get(f, True) else 1, str(f)),
                )
                _missing_count = sum(1 for f in md_files if _priority_flags.get(f, True))
                _stale_count = len(md_files) - _missing_count
                if _missing_count or _stale_count:
                    logger.info(
                        f"Priority sort (missing_first): {_missing_count} files with missing outputs, "
                        f"{_stale_count} files with stale outputs"
                    )
            else:
                md_files = sorted(md_files, key=str)

            # Apply skip_first for chunked pagination
            if skip_first > 0:
                md_files = md_files[skip_first:]
                logger.info(
                    f"Skipped first {skip_first} files for chunked pagination ({len(md_files)} remaining)"
                )

            # Apply max_files limit if specified
            if max_files and max_files > 0 and len(md_files) > max_files:
                md_files = md_files[:max_files]
                logger.info(f"Limited to first {max_files} files (deterministic selection)")

            result.total_files = len(md_files)

            if not md_files:
                all_md_count = len(list(directory.glob(pattern)))
                logger.error(
                    f"No markdown files to translate in {directory}. "
                    f"Discovered {all_md_count} .md file(s) total, "
                    f"but after filtering: 0 source files remain. "
                    f"Check: input path exists, site profile content_roots are correct, "
                    f"working directory is repository root, and files aren't already translated."
                )
                result.success = False
                result.failed_files = 1
                return result

            # Choose processing mode
            if parallel and len(md_files) > 1:
                result = self._translate_directory_parallel(
                    site_id,
                    md_files,
                    target_langs,
                    result,
                    max_workers,
                    run_deadline=run_deadline,
                )
            else:
                result = self._translate_directory_sequential(
                    site_id, md_files, target_langs, result, run_deadline=run_deadline
                )

            result.success = result.successful_files > 0

        except Exception as e:
            logger.error(f"Error translating directory {directory}: {e}")
            result.failed_files = result.total_files
            if telemetry_run:
                telemetry_run.log_event("error", {"error": str(e)})
                import traceback

                error_details = traceback.format_exc()
                max_error_details_size = 10 * 1024
                if len(error_details) > max_error_details_size:
                    error_details = error_details[:max_error_details_size] + "\n... [truncated]"
                telemetry_run.set_metrics(error_details=error_details)

        finally:
            result.duration_seconds = time.time() - start_time
            logger.info(
                f"Directory translation completed: "
                f"{result.successful_files}/{result.total_files} files "
                f"in {result.duration_seconds:.2f}s"
            )

            # TC-05: Persist review cache to disk at end of directory run
            if engine._review_cache is not None:
                try:
                    engine._review_cache.save()
                except Exception as _rc_err:
                    logger.debug("Review cache save failed: %s", _rc_err)

            # TEL-04: Track aggregated stats and close telemetry
            if telemetry_run and telemetry_enabled:
                try:
                    agg_stats = result.aggregate_stats
                    all_outputs = {}
                    for file_result in result.file_results:
                        if file_result.outputs:
                            all_outputs.update(file_result.outputs)

                    engine.telemetry.track_translation_stats(
                        telemetry_run,
                        agg_stats,
                        job_type="translate_directory",
                        output_paths=all_outputs,
                    )

                    from ..observability.telemetry_integration import (
                        build_error_summary,
                        build_output_summary,
                        calculate_items_metrics,
                    )

                    files_generated = sum(len(fr.outputs) for fr in result.file_results)
                    all_errors = []
                    for fr in result.file_results:
                        if fr.errors:
                            all_errors.extend(fr.errors[:2])

                    items_metrics = calculate_items_metrics(
                        job_type="translate_directory",
                        total_files=result.total_files,
                        successful_files=result.successful_files,
                        failed_files=result.failed_files,
                    )
                    output_summary = build_output_summary(
                        job_type="translate_directory",
                        successful_files=result.successful_files,
                        total_files=result.total_files,
                        files_generated=files_generated,
                        errors=all_errors,
                    )
                    error_summary = build_error_summary(all_errors, max_errors=5)

                    duration_ms, used_fallback = _safe_duration_ms(
                        agg_stats, context="translate_directory"
                    )

                    telemetry_run.set_metrics(
                        duration_ms=duration_ms,
                        items_discovered=items_metrics["items_discovered"],
                        items_succeeded=items_metrics["items_succeeded"],
                        items_failed=items_metrics["items_failed"],
                        output_summary=output_summary,
                        error_summary=error_summary,
                    )
                    telemetry_cm.__exit__(None, None, None)

                    try:
                        from ..observability.graceful_shutdown import unregister_active_context

                        unregister_active_context(telemetry_run)
                    except ImportError:
                        pass
                except Exception as telemetry_error:
                    logger.warning(f"Telemetry tracking failed: {telemetry_error}")

            # TC-GIT-01: Store telemetry context for git commit association
            if telemetry_enabled and telemetry_run:
                result.telemetry_context = telemetry_run

        # Asset sync: copy non-markdown assets for per_language_folders sites
        try:
            _asset_cfg = (
                engine.config.get_config().get("asset_sync", {})
                if hasattr(engine.config, "get_config")
                else {}
            )
            if (
                _asset_cfg.get("enabled", False)
                and site_profile
                and getattr(
                    getattr(site_profile, "output_layout", None),
                    "per_language_folders",
                    False,
                )
            ):
                from ..utils.asset_sync import sync_assets

                _exts = _asset_cfg.get("extensions", None)
                _skip = _asset_cfg.get("skip_if_exists", True)
                _src_lang = getattr(site_profile, "default_source_lang", "en")
                _total_synced = 0
                for _tgt_lang in target_langs:
                    _src_dir = directory / _src_lang
                    _tgt_dir = directory / _tgt_lang
                    if _src_dir.is_dir():
                        _total_synced += sync_assets(
                            _src_dir,
                            _tgt_dir,
                            extensions=frozenset(_exts) if _exts else None,
                            skip_if_exists=_skip,
                        )
                if _total_synced:
                    logger.info(
                        "Asset sync total: %d files across %d languages",
                        _total_synced,
                        len(target_langs),
                    )
        except Exception as _asset_err:
            logger.warning("Asset sync failed (non-fatal): %s", _asset_err)

        return result

    # ------------------------------------------------------------------
    # Sequential dispatch
    # ------------------------------------------------------------------

    def _translate_directory_sequential(
        self,
        site_id: str,
        md_files: list[Path],
        target_langs: list[str],
        result: DirectoryResult,
        run_deadline: float | None = None,
    ) -> DirectoryResult:
        """Translate files sequentially."""
        engine = self._engine

        for md_file in md_files:
            # RES-06: Check for shutdown before starting new file
            if engine._check_shutdown():
                logger.info("Shutdown detected, stopping translation")
                engine._perform_shutdown()
                break

            # Check run deadline
            if run_deadline is not None and time.time() >= run_deadline:
                logger.warning(
                    f"Run deadline reached, stopping sequential translation after "
                    f"{result.successful_files} files (deadline={run_deadline:.0f})"
                )
                break

            # RES-06: Track current file for shutdown coordination
            engine._current_file = md_file

            try:
                # WS-A: Use RetryHandler for OOM recovery if available
                if engine.retry_handler:

                    def translate_with_batch_size(file_path: Path, batch_size: int, **kwargs):
                        original_batch_size = engine.batch_size
                        engine.batch_size = batch_size
                        try:
                            return engine.translate_file(
                                site_id=kwargs.get("site_id"),
                                file_path=file_path,
                                target_langs=kwargs.get("target_langs"),
                            )
                        finally:
                            engine.batch_size = original_batch_size

                    def handle_oom_recovery(
                        failed_batch_size: int, success_batch_size: int, _file=md_file
                    ):
                        logger.info(
                            f"OOM RECOVERY: {failed_batch_size}→{success_batch_size}, "
                            f"teaching adaptive tracker for file {_file.name}"
                        )
                        if not engine.batch_stats_tracker:
                            logger.debug("No batch_stats_tracker available, skipping OOM learning")
                            return
                        try:
                            for lang in target_langs:
                                engine.batch_stats_tracker.record_batch_result(
                                    language=lang,
                                    batch_size=failed_batch_size,
                                    success=False,
                                    fallback_reason="oom_retry",
                                )
                                if lang in engine.batch_stats_tracker.languages:
                                    lang_data = engine.batch_stats_tracker.languages[lang]
                                    current = lang_data.get(
                                        "current_batch_size", success_batch_size
                                    )
                                    new_size = min(current, success_batch_size)
                                    lang_data["current_batch_size"] = new_size
                                    logger.debug(f"Capped {lang} batch_size: {current}→{new_size}")
                            engine.batch_stats_tracker.save()
                            logger.info(f"OOM learning persisted for {len(target_langs)} languages")
                        except Exception as e:
                            logger.warning(f"Failed to record OOM learning: {e}")

                    logger.info(
                        f"Translating {md_file.name} | OOM Protection: ACTIVE "
                        f"(max_retries={engine.retry_handler.max_retries}) | Batch size: {engine.batch_size}"
                    )

                    file_result = engine.retry_handler.translate_file_with_retry(
                        translate_func=translate_with_batch_size,
                        file_path=md_file,
                        initial_batch_size=engine.batch_size,
                        on_oom_recovery=handle_oom_recovery,
                        site_id=site_id,
                        target_langs=target_langs,
                    )
                else:
                    logger.info(
                        f"Translating {md_file.name} | OOM Protection: DISABLED | Batch size: {engine.batch_size}"
                    )
                    file_result = engine.translate_file(
                        site_id=site_id,
                        file_path=md_file,
                        target_langs=target_langs,
                    )
                result.file_results.append(file_result)

                if file_result.success:
                    result.successful_files += 1
                    if engine.progress_tracker:
                        try:
                            for lang in target_langs:
                                engine.progress_tracker.mark_completed(md_file, lang)
                            logger.debug(f"Progress saved for {md_file.name}")
                        except Exception as e:
                            logger.warning(f"Failed to save progress for {md_file}: {e}")
                else:
                    if file_result.overwrite_blocked:
                        logger.info(
                            f"Protected skip {md_file.name}: overwrite blocked (existing translation preserved)"
                        )
                    else:
                        result.failed_files += 1

                    if engine.progress_tracker:
                        try:
                            for lang in target_langs:
                                error_msg = (
                                    "; ".join(file_result.errors[:2])
                                    if file_result.errors
                                    else "Unknown error"
                                )
                                engine.progress_tracker.mark_failed(md_file, lang, error_msg)
                            logger.debug(f"Failure progress saved for {md_file.name}")
                        except Exception as e:
                            logger.warning(f"Failed to save failure progress for {md_file}: {e}")

            except Exception as e:
                from .exceptions import ShutdownRequested

                if isinstance(e, ShutdownRequested):
                    logger.info(
                        f"Shutdown requested during {md_file}, stopping directory translation"
                    )
                    engine._perform_shutdown()
                    break

                logger.error(f"Error translating {md_file}: {e}")
                result.failed_files += 1

                if engine.progress_tracker:
                    try:
                        for lang in target_langs:
                            engine.progress_tracker.mark_failed(md_file, lang, str(e))
                    except Exception as mark_error:
                        logger.warning(f"Failed to save error progress: {mark_error}")

            finally:
                engine._current_file = None

        return result

    # ------------------------------------------------------------------
    # Parallel dispatch
    # ------------------------------------------------------------------

    def _translate_directory_parallel(
        self,
        site_id: str,
        md_files: list[Path],
        target_langs: list[str],
        result: DirectoryResult,
        max_workers: int | None = None,
        run_deadline: float | None = None,
    ) -> DirectoryResult:
        """Translate files in parallel using ThreadPoolExecutor."""
        engine = self._engine

        if max_workers is None:
            max_workers = 1

        logger.info(f"Translating {len(md_files)} files with {max_workers} workers")

        # Pre-load the translation model BEFORE starting parallel workers
        site_profile = engine.config.get_site_profile(site_id)
        if site_profile:
            model_id = engine._get_model_id(site_profile)
            logger.info(f"Pre-loading model {model_id} before parallel processing...")
            try:
                engine.model_loader.load_model(model_id)
                logger.info(f"Model {model_id} pre-loaded successfully")
            except Exception as e:
                logger.error(f"Failed to pre-load model {model_id}: {e}")

        # TC-CW-02: Per-file timeout
        import concurrent.futures as _cf

        _te_cfg_cw02 = (
            engine.config.get_config().get("translation_engine", {})
            if hasattr(engine.config, "get_config")
            else {}
        )
        _per_file_timeout_s = float(_te_cfg_cw02.get("per_file_timeout_s", 600))

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_file = {
                executor.submit(self._translate_file_safe, site_id, md_file, target_langs): md_file
                for md_file in md_files
            }

            for future in as_completed(future_to_file):
                if engine._check_shutdown():
                    logger.info("Shutdown detected, cancelling remaining jobs")
                    for f in future_to_file:
                        f.cancel()
                    engine._perform_shutdown()
                    break

                if run_deadline is not None and time.time() >= run_deadline:
                    logger.warning(
                        f"Run deadline reached, stopping parallel translation after "
                        f"{result.successful_files} files (deadline={run_deadline:.0f})"
                    )
                    for f in future_to_file:
                        f.cancel()
                    break

                md_file = future_to_file[future]
                try:
                    file_result = future.result(timeout=_per_file_timeout_s)
                    result.file_results.append(file_result)

                    if file_result.success:
                        result.successful_files += 1
                        logger.debug(f"✓ Translated {md_file.name}")
                    elif file_result.overwrite_blocked:
                        logger.info(
                            f"Protected skip {md_file.name}: overwrite blocked (existing translation preserved)"
                        )
                    else:
                        result.failed_files += 1
                        logger.warning(f"✗ Failed {md_file.name}: {file_result.errors}")

                except _cf.TimeoutError:
                    logger.warning(
                        f"WARNING: per-file timeout for {md_file.name} after {_per_file_timeout_s:.0f}s "
                        f"— cancelling and continuing with remaining files"
                    )
                    future.cancel()
                    result.failed_files += 1

                except Exception as e:
                    from .exceptions import ShutdownRequested

                    if isinstance(e, ShutdownRequested):
                        logger.info(
                            f"Shutdown requested during {md_file}, cancelling parallel jobs"
                        )
                        for f in future_to_file:
                            f.cancel()
                        engine._perform_shutdown()
                        break

                    logger.error(f"Error processing {md_file}: {e}")
                    result.failed_files += 1

        return result

    # ------------------------------------------------------------------
    # Thread-safe file translation wrapper
    # ------------------------------------------------------------------

    def _translate_file_safe(
        self, site_id: str, file_path: Path, target_langs: list[str]
    ) -> TranslationResult:
        """Thread-safe wrapper for translate_file."""
        engine = self._engine
        try:
            if engine.retry_handler:

                def translate_with_batch_size(file_path: Path, batch_size: int, **kwargs):
                    original_batch_size = engine.batch_size
                    engine.batch_size = batch_size
                    try:
                        return engine.translate_file(
                            site_id=kwargs.get("site_id"),
                            file_path=file_path,
                            target_langs=kwargs.get("target_langs"),
                        )
                    finally:
                        engine.batch_size = original_batch_size

                def handle_oom_recovery(failed_batch_size: int, success_batch_size: int):
                    logger.info(
                        f"OOM RECOVERY: {failed_batch_size}→{success_batch_size}, "
                        f"teaching adaptive tracker for file {file_path.name}"
                    )
                    if not engine.batch_stats_tracker:
                        logger.debug("No batch_stats_tracker available, skipping OOM learning")
                        return
                    try:
                        for lang in target_langs:
                            engine.batch_stats_tracker.record_batch_result(
                                language=lang,
                                batch_size=failed_batch_size,
                                success=False,
                                fallback_reason="oom_retry",
                            )
                            if lang in engine.batch_stats_tracker.languages:
                                lang_data = engine.batch_stats_tracker.languages[lang]
                                current = lang_data.get("current_batch_size", success_batch_size)
                                new_size = min(current, success_batch_size)
                                lang_data["current_batch_size"] = new_size
                                logger.debug(f"Capped {lang} batch_size: {current}→{new_size}")
                        engine.batch_stats_tracker.save()
                        logger.info(f"OOM learning persisted for {len(target_langs)} languages")
                    except Exception as e:
                        logger.warning(f"Failed to record OOM learning: {e}")

                logger.info(
                    f"Translating {file_path.name} | OOM Protection: ACTIVE "
                    f"(max_retries={engine.retry_handler.max_retries}) | Batch size: {engine.batch_size}"
                )

                return engine.retry_handler.translate_file_with_retry(
                    translate_func=translate_with_batch_size,
                    file_path=file_path,
                    initial_batch_size=engine.batch_size,
                    on_oom_recovery=handle_oom_recovery,
                    site_id=site_id,
                    target_langs=target_langs,
                )
            else:
                logger.info(
                    f"Translating {file_path.name} | OOM Protection: DISABLED | Batch size: {engine.batch_size}"
                )
                return engine.translate_file(
                    site_id=site_id, file_path=file_path, target_langs=target_langs
                )
        except Exception as e:
            logger.error(f"Error in _translate_file_safe for {file_path}: {e}")
            return TranslationResult(
                success=False,
                file_path=file_path,
                errors=[str(e)],
            )

    # ------------------------------------------------------------------
    # Quality-aware completion filter
    # ------------------------------------------------------------------

    def _quality_check_complete_file(
        self,
        source_path: Path,
        target_langs: list[str],
        site_profile,
        ttl_days: int = 7,
        confidence: float = 0.80,
        max_paragraphs: int = 2,
    ) -> bool:
        """WS-COMP-6: Quality-aware completion filter check.

        For a file the mtime check would skip, sample a few paragraphs from each
        target-language output and check if the body is in the correct language.

        Returns:
            True if ANY output fails the language check (file should be retranslated).
            False if all outputs pass or cannot be checked.
        """
        import datetime

        engine = self._engine

        marker_dir = Path("data/quality_scan_markers")
        try:
            marker_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            return False

        file_key = hashlib.sha256(str(source_path.resolve()).encode()).hexdigest()[:24]
        marker_path = marker_dir / f"{file_key}.json"

        marker: dict = {}
        if marker_path.exists():
            try:
                marker = json.loads(marker_path.read_text(encoding="utf-8"))
            except Exception:
                marker = {}

        now_ts = datetime.datetime.utcnow().timestamp()
        ttl_seconds = ttl_days * 86400

        all_cached_pass = all(
            marker.get(f"lang_{lang}", {}).get("result") == "pass"
            and now_ts - marker.get(f"lang_{lang}", {}).get("validated_at", 0) < ttl_seconds
            for lang in target_langs
        )
        if all_cached_pass:
            return False

        ft_model = getattr(self, "_quality_filter_ft_model", None)
        if ft_model is None:
            try:
                import fasttext as _ft  # type: ignore

                _ft_path = Path("data/models/fasttext/lid.176.bin")
                if _ft_path.exists():
                    ft_model = _ft.load_model(str(_ft_path))
                    self._quality_filter_ft_model = ft_model
            except Exception:
                return False

        if ft_model is None:
            return False

        _similar_pairs: set[frozenset] = {
            frozenset({"hr", "sr"}),
            frozenset({"hr", "bs"}),
            frozenset({"sr", "bs"}),
            frozenset({"ms", "id"}),
            frozenset({"cs", "sk"}),
            frozenset({"nb", "no"}),
        }

        any_failed = False
        updated_marker = dict(marker)

        for lang in target_langs:
            lang_key = f"lang_{lang}"
            cached = updated_marker.get(lang_key, {})
            if (
                cached.get("result") == "pass"
                and now_ts - cached.get("validated_at", 0) < ttl_seconds
            ):
                continue

            output_path = engine._get_output_path(source_path, lang, site_profile)
            if not output_path.exists():
                continue

            try:
                content = output_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            body = content
            if body.startswith("---"):
                end = body.find("\n---", 3)
                if end != -1:
                    body = body[end + 4 :]
            body = re.sub(r"```[\s\S]*?```", "", body)
            body = re.sub(r"\{\{[<%][^}]*[>%]\}\}", "", body)
            paragraphs = []
            for para in re.split(r"\n\n+", body):
                para = para.strip()
                if para.startswith("#"):
                    para = re.sub(r"^#+\s*", "", para)
                if len(para) < 30:
                    continue
                letter_ratio = sum(1 for c in para if c.isalpha()) / max(len(para), 1)
                if letter_ratio < 0.5:
                    continue
                paragraphs.append(para)
                if len(paragraphs) >= max_paragraphs:
                    break

            if not paragraphs:
                continue

            sample_text = " ".join(paragraphs).replace("\n", " ")[:500]
            try:
                preds = ft_model.predict(sample_text, k=1)
                detected_lang = preds[0][0].replace("__label__", "")
                det_confidence = float(preds[1][0])
            except Exception:
                continue

            if (
                detected_lang != lang
                and det_confidence >= confidence
                and frozenset({detected_lang, lang}) not in _similar_pairs
            ):
                logger.info(
                    f"Quality filter: {output_path.name} detected as '{detected_lang}' "
                    f"(expected '{lang}', conf={det_confidence:.2f}) — flagging for retranslation"
                )
                updated_marker[lang_key] = {
                    "result": "fail",
                    "validated_at": now_ts,
                    "detected": detected_lang,
                    "confidence": round(det_confidence, 3),
                }
                any_failed = True
            else:
                updated_marker[lang_key] = {"result": "pass", "validated_at": now_ts}

        try:
            marker_path.write_text(json.dumps(updated_marker), encoding="utf-8")
        except Exception:
            pass

        return any_failed

    # ------------------------------------------------------------------
    # Source file filtering
    # ------------------------------------------------------------------

    def _filter_source_files(
        self,
        files: list,
        site_profile,
        target_langs: list[str],
    ) -> list:
        """Filter a list of files to exclude already-translated files.

        For file-based localization (per_language_folders=False), translated
        files follow the pattern ``{name}.{lang}.md``.

        For directory-based localization (per_language_folders=True), all
        files are returned unchanged.
        """
        from .engine import _is_translated_filename

        if getattr(getattr(site_profile, "output_layout", None), "per_language_folders", True):
            return list(files)

        source_lang = getattr(site_profile, "default_source_lang", "en")
        source_files = []
        excluded_count = 0

        for f in files:
            is_translated, detected_lang = _is_translated_filename(
                f.name, target_langs, source_lang=source_lang
            )
            if is_translated:
                logger.info(
                    "Skipping already-translated file: %s (detected lang: %s)",
                    f.name,
                    detected_lang,
                )
                excluded_count += 1
            else:
                source_files.append(f)

        total = len(files)
        if excluded_count > 0 and total > 0:
            pct = excluded_count / total * 100
            logger.info(
                "Filtering: excluded %d/%d files (%.0f%%) as existing translations",
                excluded_count,
                total,
                pct,
            )
            if pct > 50:
                logger.warning(
                    "High filter rate: %.0f%% of %d files filtered as translations. "
                    "Verify the source directory is correct.",
                    pct,
                    total,
                )

        return source_files
