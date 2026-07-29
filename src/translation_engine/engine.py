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

import hashlib
import logging
import os
import re
import time
import unicodedata
from pathlib import Path
from typing import Any, Optional

from ..model_runtime import ModelLoader
from ..observability.progress import get_progress_tracker
from ..observability.telemetry_integration import _safe_duration_ms
from ..tm import TranslationMemory
from ..tm.override_controller import OverrideMode
from ..tm.retranslate_queue import (
    add_to_queue as _rtq_add,
)
from ..utils.atomic_write import (
    AtomicWriteError,
    DiskFullError,
    InvalidPathError,
    ReadOnlyFilesystemError,
    atomic_write,
    atomic_write_binary,
)
from ..utils.config_loader import ConfigService
from ..utils.content_discovery import ALL_LANGUAGE_CODES as _ALL_LANGUAGE_CODES  # noqa: F401
from ..utils.content_discovery import is_translated_filename as _is_translated_filename
from ..utils.content_discovery import resolve_translated_path as _resolve_translated_path
from ..utils.file_lock import FileLock
from ..utils.locale_policy import LocalePolicyViolation, validate_requested_locales
from ..utils.metadata_tracker import MetadataTracker
from ..utils.metrics import calc_stats
from .exceptions import TranslationRejectedError
from .extractor import SegmentExtractor
from .models import (
    DirectoryResult,
    TranslationResult,
    TranslationStats,
)
from .parser import HugoParser  # noqa: F401 — patched by tests
from .reconstructor import MarkdownReconstructor  # noqa: F401 — patched by tests
from .validation import ValidationSuite
from .validation.base import ValidationIssue as _ValIssue
from .validation.base import ValidationSeverity as _ValSeverity
from .validation.decision_engine import ValidationDecisionEngine

logger = logging.getLogger(__name__)


_TARGET_SCRIPT_RANGES: dict[str, tuple[tuple[int, int], ...]] = {
    "ar": ((0x0600, 0x06FF),),
    "fa": ((0x0600, 0x06FF),),
    "el": ((0x0370, 0x03FF),),
    "he": ((0x0590, 0x05FF),),
    "hi": ((0x0900, 0x097F),),
    "ja": ((0x3040, 0x30FF), (0x3400, 0x9FFF)),
    "ko": ((0x1100, 0x11FF), (0xAC00, 0xD7AF)),
    "ru": ((0x0400, 0x052F),),
    "th": ((0x0E00, 0x0E7F),),
    "uk": ((0x0400, 0x052F),),
    "zh": ((0x3400, 0x9FFF),),
}

_FRONTMATTER_TECHNICAL_SIGNAL_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:"
    r"Aspose(?:\.[A-Za-z][A-Za-z0-9]*)+|"
    r"\.NET|C\+\+|C#|"
    r"FOSS|SDK|API|HTTP|REST|JSON|XML|XLSX|PDF|DOCX|"
    r"Rust|Python|Java|JavaScript|Microsoft|Office|"
    r"[A-Za-z][A-Za-z0-9_+#-]*(?:\.[A-Za-z0-9_+#-]+)+|"
    r"[A-Z][A-Z0-9_+#-]{1,}|"
    r"[A-Z][a-z0-9]+(?:[A-Z][A-Za-z0-9]*)+"
    r")(?![A-Za-z0-9_.])"
)


def _frontmatter_script_metrics(text: str, target_lang: str) -> dict[str, int | float]:
    """Return payload-free script ratios for frontmatter diagnostics."""
    letters = [character for character in text if character.isalpha()]
    letter_count = len(letters)
    if not letter_count:
        return {
            "letter_count": 0,
            "latin_letter_ratio": 0.0,
            "target_script_ratio": 0.0,
        }
    latin_count = sum(1 for character in letters if "LATIN" in unicodedata.name(character, ""))
    ranges = _TARGET_SCRIPT_RANGES.get(target_lang, ())
    if ranges:
        target_count = sum(
            1
            for character in letters
            if any(start <= ord(character) <= end for start, end in ranges)
        )
    else:
        target_count = latin_count
    return {
        "letter_count": letter_count,
        "latin_letter_ratio": latin_count / letter_count,
        "target_script_ratio": target_count / letter_count,
    }


def _frontmatter_has_strong_script_evidence(text: str, target_lang: str) -> bool:
    """Attest Chinese prose after removing governed technical tokens.

    Required product, platform, API, and file-format identifiers must not
    outvote translated prose. The remaining signal still needs enough Han
    characters and a high script ratio, so a token Chinese word added to
    untranslated English prose cannot pass.
    """
    target_base = target_lang.lower().split("-")[0]
    if target_base != "zh":
        return False
    signal = _FRONTMATTER_TECHNICAL_SIGNAL_RE.sub(" ", text)
    letters = [character for character in signal if character.isalpha()]
    if not letters:
        return False
    ranges = _TARGET_SCRIPT_RANGES[target_base]
    target_count = sum(
        any(start <= ord(character) <= end for start, end in ranges) for character in letters
    )
    return target_count >= 6 and target_count / len(letters) >= 0.70


def _frontmatter_language_signal_text(text: str) -> str:
    """Return ordinary prose without governed technical classifier noise."""
    stripped = _FRONTMATTER_TECHNICAL_SIGNAL_RE.sub(" ", text)
    return re.sub(r"\s+", " ", stripped).strip()


# _ALL_LANGUAGE_CODES and _is_translated_filename are re-exported (see imports
# above) from src.utils.content_discovery, the canonical, config-driven
# implementation shared with standalone scripts. Kept as module attributes
# here for backward compatibility with existing `from
# src.translation_engine.engine import _is_translated_filename` call sites.


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


def get_site_lock_path(site_id: str) -> Path:
    """
    Get lock file path for a site.

    Args:
        site_id: Site identifier

    Returns:
        Path to lock file for this site
    """
    lock_dir = Path(".translation_progress") / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    return lock_dir / f"{site_id}.lock"


def get_site_lock(site_id: str, timeout: float = 30.0) -> FileLock:
    """
    Get FileLock for a site.

    Args:
        site_id: Site identifier
        timeout: Lock acquisition timeout in seconds

    Returns:
        FileLock instance configured for the site
    """
    lock_file = get_site_lock_path(site_id)
    return FileLock(lock_file, timeout=timeout)


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
        enable_validation: bool = True,  # Always validate in production
        enable_telemetry: bool = True,
        validation_suite: ValidationSuite | None = None,
        decision_engine: ValidationDecisionEngine | None = None,
        validation_mode: str | None = None,
        validation_policy: str = "standard",
        enable_terminology: bool | None = None,
        terminology_mode: str | None = None,
        max_retries: int | None = None,
        dry_run: bool = False,
        save_rejected: bool = False,
        override_mode: str | None = None,
        override_filters: dict | None = None,
        batch_size: int = 16,
        enable_verification: bool = False,
        enable_verification_fix: bool = False,
        output_dir_override: Path | None = None,
        input_root: Path | None = None,
        progress_tracker: Optional["ProgressTracker"] = None,
        production_ingestor: Optional["ProductionMetricsIngestor"] = None,
        sort_segments_by_length: bool = False,
        redis_client: "any | None" = None,
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
            validation_policy: Persistence policy (standard or zero-defect)
            enable_terminology: Enable/disable terminology preservation
            terminology_mode: Terminology mode (protect, validate, both, none)
            max_retries: Override max retry attempts
            dry_run: Preview decisions without writing files
            save_rejected: Save rejected translations for debugging
            override_mode: TM cache override mode (normal, bypass, refresh, validate)
            override_filters: Optional filters for override (source_patterns, target_langs, frontmatter_keys)
            batch_size: Maximum texts to translate per batch (reduces GPU memory usage)
            enable_verification: Enable post-translation verification (VA-03)
            enable_verification_fix: Enable automatic retry on verification failure (VA-03)
            output_dir_override: Override output directory (takes precedence over site profile)
            input_root: Input root directory for computing relative output paths (prevents collisions)
            progress_tracker: Optional ProgressTracker for crash recovery (RES-02)
            production_ingestor: Optional ProductionMetricsIngestor for recording translation runs (BM-06)
            sort_segments_by_length: Sort segments by length (shortest first) for improved batching efficiency
            redis_client: Optional Redis client for distributed locking (multi-worker coordination)
            **kwargs: Additional options (for future extensibility)
        """
        # TC-HT-006: BYPASS_PLACEHOLDER_PROTECTION disables placeholder
        # protection (extractor/segment_extractor.py:417) and directly
        # caused the 2026-07-12 wave-3 corruption. This is the one choke
        # point both cli.py's main() AND .local/unified_translate.py (which
        # never goes through cli.py's argparse) pass through, so it is the
        # only place a fatal check here actually covers both invocation
        # paths.
        if os.environ.get("BYPASS_PLACEHOLDER_PROTECTION"):
            raise RuntimeError(
                "FATAL: BYPASS_PLACEHOLDER_PROTECTION is set. This env var disables "
                "placeholder protection and directly caused the 2026-07-12 wave-3 "
                "corruption. Unset it to proceed."
            )

        # TC-DECOMP-05: All initialization delegated to EngineBuilder
        from .engine_builder import EngineBuilder

        EngineBuilder(
            config_service=config_service,
            tm=tm,
            model_loader=model_loader,
            enable_validation=enable_validation,
            enable_telemetry=enable_telemetry,
            validation_suite=validation_suite,
            decision_engine=decision_engine,
            validation_mode=validation_mode,
            validation_policy=validation_policy,
            enable_terminology=enable_terminology,
            terminology_mode=terminology_mode,
            max_retries=max_retries,
            dry_run=dry_run,
            save_rejected=save_rejected,
            override_mode=override_mode,
            override_filters=override_filters,
            batch_size=batch_size,
            enable_verification=enable_verification,
            enable_verification_fix=enable_verification_fix,
            output_dir_override=output_dir_override,
            input_root=input_root,
            progress_tracker=progress_tracker,
            production_ingestor=production_ingestor,
            sort_segments_by_length=sort_segments_by_length,
            redis_client=redis_client,
            **kwargs,
        ).build_into(self)

    def _load_adaptive_config(self) -> dict:
        """Load adaptive batching configuration from global config."""
        try:
            global_config = self.config.get_config()
            return global_config.get("adaptive_batching", {})
        except Exception as e:
            logger.debug(f"Failed to load adaptive batching config: {e}")
            return {"enabled": False}

    def _load_language_detection_config(self) -> dict:
        """Load language detection configuration from global config."""
        try:
            global_config = self.config.get_config()
            return global_config.get("language_detection", {})
        except Exception as e:
            logger.debug(f"Failed to load language detection config: {e}")
            return {}

    def _load_oom_retry_config(self) -> dict:
        """Load OOM retry configuration from global config."""
        try:
            global_config = self.config.get_config()
            autonomous_recovery = global_config.get("autonomous_recovery", {})
            oom_retry = autonomous_recovery.get("oom_retry", {})

            # Debug logging to help diagnose config loading issues
            if not oom_retry:
                logger.debug(
                    f"OOM retry config not found. "
                    f"Has autonomous_recovery: {bool(autonomous_recovery)}, "
                    f"Keys: {list(autonomous_recovery.keys()) if autonomous_recovery else []}"
                )

            return oom_retry
        except Exception as e:
            logger.warning(f"Failed to load OOM retry config: {e}", exc_info=True)
            return {}

    def _get_language_detector(self):
        """
        Resolve active language detector with backward compatibility.

        Returns:
            Detector object implementing detect(text) -> (lang, confidence), or None.
        """
        detector = getattr(self, "fasttext_detector", None)
        if detector is not None:
            return detector
        return getattr(self, "detector", None)

    def _is_oom_error(self, exception: Exception) -> bool:
        """
        OOM-01: Detect CUDA Out of Memory errors.

        Checks if the exception is a GPU OOM error by examining the error message
        for common OOM patterns. This allows the exception handler in translate_file()
        to distinguish between OOM errors (which should be retried with batch reduction)
        and other exceptions (which should break the retry loop).

        Args:
            exception: Exception to check

        Returns:
            True if this is a CUDA OOM error, False otherwise
        """
        error_str = str(exception).lower()

        oom_patterns = [
            "cuda out of memory",
            "out of memory",
            "gpu out of memory during translation",
            "reduce batch size",
            "cudnn_status_not_enough_memory",
            "cublas error",
        ]

        for pattern in oom_patterns:
            if pattern in error_str:
                logger.debug(f"OOM detected in Engine: pattern='{pattern}' matched in error")
                return True

        # Log non-OOM for troubleshooting
        error_preview = error_str[:150] + "..." if len(error_str) > 150 else error_str
        logger.debug(f"NOT OOM in Engine: {error_preview}")
        return False

    def register_shutdown_callback(self, callback) -> None:
        """
        RES-06: Register callback to be called on shutdown.

        Args:
            callback: Function to call during shutdown
        """
        self._shutdown_callbacks.append(callback)

    def request_shutdown(self) -> None:
        """
        RES-06: Request graceful shutdown.

        Called by signal handler. Sets flag and allows current
        file to complete before shutdown.
        """
        with self._shutdown_lock:
            if self._shutdown_requested:
                return

            self._shutdown_requested = True

            current = self._current_file
            if current:
                logger.info(f"Shutdown requested. Completing current file: {current}")
            else:
                logger.info("Shutdown requested. Finishing up...")

    def _check_shutdown(self) -> bool:
        """
        RES-06: Check if shutdown has been requested.

        Called between file translations to allow clean exit point.

        Returns:
            True if shutdown requested
        """
        return self._shutdown_requested

    def _perform_shutdown(self) -> None:
        """
        RES-06: Perform shutdown sequence.

        Steps:
        1. Save progress tracker state
        2. Save L3 index
        3. Call registered shutdown callbacks
        4. Log shutdown complete
        """
        logger.info("Performing graceful shutdown...")

        try:
            # Save L3 index via TM
            if self.tm:
                try:
                    # Access L3 via the TM hierarchy
                    l3 = getattr(self.tm, "l3", None)
                    if l3 and hasattr(l3, "save_index"):
                        logger.info("Saving L3 semantic index...")
                        l3.save_index()
                        logger.info("L3 index saved successfully")
                except Exception as e:
                    logger.warning(f"L3 index save may be incomplete: {e}")

            # Call shutdown callbacks
            for callback in self._shutdown_callbacks:
                try:
                    callback()
                except Exception as e:
                    logger.error(f"Shutdown callback failed: {e}")

            logger.info("Graceful shutdown complete")

        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
            raise

    def _get_free_space(self, path: Path) -> int:
        """
        RES-09 + D3: Get free disk space for path with parent walking and caching.

        Cross-platform implementation for checking available disk space.
        Features:
        - Parent directory walking: finds nearest existing ancestor if path doesn't exist
        - 60-second cache: avoids repeated stat calls for same path
        - Graceful degradation: returns 0 if all checks fail

        Args:
            path: Directory path to check

        Returns:
            Free space in bytes, or 0 if unable to determine
        """
        import shutil
        import time

        # D3: Check cache first (60-second TTL)
        path_str = str(path)
        if path_str in self._space_check_cache:
            timestamp, cached_free = self._space_check_cache[path_str]
            age = time.time() - timestamp
            if age < 60:  # Cache valid for 60 seconds
                logger.debug(
                    f"Disk space cache hit for {path} (age: {age:.1f}s, free: {cached_free / (1024**3):.2f}GB)"
                )
                return cached_free

        try:
            # D3: Parent directory walking - find nearest existing ancestor
            check_path = path
            walked_steps = 0
            max_steps = 20  # Safety limit to prevent infinite loops

            while not check_path.exists() and walked_steps < max_steps:
                parent = check_path.parent
                if parent == check_path:
                    # Reached filesystem root without finding existing path
                    logger.warning(f"Could not find existing path for {path} (walked to root)")
                    return 0
                check_path = parent
                walked_steps += 1

            if walked_steps >= max_steps:
                logger.warning(f"Exceeded max parent walk steps ({max_steps}) for {path}")
                return 0

            if walked_steps > 0:
                logger.debug(f"Walked {walked_steps} parent directories: {path} -> {check_path}")

            # D3: Get disk usage for existing path
            total, used, free = shutil.disk_usage(check_path)

            # D3: Cache the result with timestamp
            self._space_check_cache[path_str] = (time.time(), free)
            logger.debug(f"Cached disk space for {path}: {free / (1024**3):.2f}GB free")

            return free

        except Exception as e:
            logger.warning(f"Could not determine free space for {path}: {e}")
            return 0

    def _get_model_id(self, site_profile, src_lang: str | None = None, tgt_lang: str | None = None):
        """
        Get model ID with CLI override, dynamic selection, and site profile fallback support.

        CT2-002: Implements language-aware model selection via ModelSelector if available.

        Selection priority:
        1. Per-language routing override from config (highest specificity — WS-COMP-7)
        2. CLI --model override / programmatic model_id (global default)
        3. Dynamic selection via model_selector (CT2 models preferred for language pairs)
        4. Site profile default_model
        5. Global fallback "m2m100_418m"

        Args:
            site_profile: Site profile with default_model attribute
            src_lang: Optional source language code (for dynamic selection)
            tgt_lang: Optional target language code (for dynamic selection)

        Returns:
            Model ID to use for translation
        """
        # Priority 1: WS-COMP-7 — per-language routing override (highest specificity).
        # Must be checked BEFORE model_id_override because the autonomous worker always
        # sets model_id_override to the global fallback model, which would otherwise
        # shadow language-specific routing (e.g. lv/sr → professionalize_llm).
        # Config: translation_engine.language_routing_overrides: {lv: "professionalize_llm"}
        # Only active when tgt_lang is explicitly provided.
        if tgt_lang:
            try:
                _te_cfg_lr = (
                    self.config.get_config().get("translation_engine", {})
                    if hasattr(self.config, "get_config")
                    else {}
                )
                _lang_routing = _te_cfg_lr.get("language_routing_overrides", {})
                if _lang_routing and tgt_lang in _lang_routing:
                    _routed_model = _lang_routing[tgt_lang]
                    logger.info(
                        f"Language routing override: {tgt_lang} \u2192 '{_routed_model}' "
                        f"(from translation_engine.language_routing_overrides)"
                    )
                    return _routed_model
            except Exception:
                pass

        # Priority 2: CLI/programmatic model override (global default for all languages).
        if self.model_id_override:
            if src_lang and tgt_lang:
                _p1_origin = (
                    "discovered" if self.model_id_override.startswith("disc_") else "curated"
                )
                logger.info(
                    f"CT2-002 model_decision: model_id={self.model_id_override} "
                    f"origin={_p1_origin} "
                    f"pair={src_lang}->{tgt_lang} "
                    f"strategy=cli-override "
                    f"fallback_used=False "
                    f"selection_reason=cli_model_flag"
                )
            return self.model_id_override

        # Priority 3: Dynamic selection via model_selector (CT2-002)
        # Only if both languages provided and selector available
        if src_lang and tgt_lang and self.model_selector:
            try:
                selection = self.model_selector.select_for_language_pair(src_lang, tgt_lang)
                _model_id = selection.model_info.model_id
                _origin = "discovered" if _model_id.startswith("disc_") else "curated"
                _local_path = (
                    str(selection.model_info.local_path)
                    if selection.model_info.local_path
                    else None
                )
                _path_exists = bool(
                    selection.model_info.local_path and selection.model_info.local_path.exists()
                )
                logger.info(
                    f"CT2-002 model_decision: model_id={_model_id} "
                    f"backend={selection.model_info.backend} "
                    f"origin={_origin} "
                    f"strategy={selection.selection_strategy} "
                    f"local_path={_local_path} "
                    f"local_path_exists={_path_exists} "
                    f"pair={src_lang}->{tgt_lang} "
                    f"fallback_used=False"
                )
                return _model_id
            except ValueError as e:
                # No suitable model found via selector, fall through to static defaults
                logger.warning(
                    f"CT2-002: Model selector failed for {src_lang}→{tgt_lang}: {e}. "
                    f"Falling back to site profile or global default."
                )

        # Priority 4: Site profile default
        # Priority 5: Global config fallback_model
        # Priority 5: Hardcoded default
        global_fallback = "m2m100_418m"
        if self.config and hasattr(self.config, "global_config"):
            md = getattr(self.config.global_config, "model_defaults", None)
            if md and getattr(md, "fallback_model", None):
                global_fallback = md.fallback_model
        fallback_model = getattr(site_profile, "default_model", None) or global_fallback

        # Log fallback decision (RBTW-004: structured model decision record)
        if src_lang and tgt_lang:
            _fb_origin = "discovered" if fallback_model.startswith("disc_") else "curated"
            logger.info(
                f"CT2-002 model_decision: model_id={fallback_model} "
                f"origin={_fb_origin} "
                f"pair={src_lang}->{tgt_lang} "
                f"fallback_used=True "
                f"fallback_reason=no_selector_or_no_match"
            )
        elif fallback_model:
            logger.debug(f"Using fallback model {fallback_model} (no language pair provided)")

        return fallback_model

    def _should_skip_translation(
        self,
        source_path: Path,
        output_path: Path,
        force_retranslate: bool = False,
        use_mtime_check: bool = True,
        target_lang: str | None = None,
    ) -> tuple:
        """
        RES-05: Determine if translation can be skipped.

        Decision logic:
        1. If force_retranslate: never skip
        2. If output doesn't exist: don't skip
        3. If output exists but is invalid: don't skip
        4. mtime check: skip if output is newer than source
        5. Content hash check (if enabled): skip if content unchanged

        Args:
            source_path: Path to source file
            output_path: Path to output file
            force_retranslate: Force retranslation flag
            use_mtime_check: Use modification time comparison
            target_lang: Target language (for output integrity validation)

        Returns:
            Tuple of (should_skip: bool, reason: str)
        """
        # Never skip if force flag set
        if force_retranslate:
            return (False, "force_retranslate enabled")

        # Don't skip if output doesn't exist
        if not output_path.exists():
            return (False, "output file does not exist")

        # Check if output is valid (not empty, has minimum content)
        if not self._is_valid_output(output_path):
            return (False, "output file invalid or empty")

        # Use mtime comparison first (quick check)
        if use_mtime_check:
            try:
                source_mtime = source_path.stat().st_mtime
                output_mtime = output_path.stat().st_mtime

                if source_mtime > output_mtime:
                    return (False, "source has been modified (mtime)")
                # If output is newer or same age, continue to content hash check

            except OSError as e:
                logger.warning(f"Failed to check mtime: {e}")
                # Fall through to content hash check or default

        # Content hash check (if enabled)
        if self.enable_content_hash and self.metadata_tracker:
            try:
                # Check if source content changed
                fast_path = True  # Default: use fast-path mtime optimization
                changed, reason = self.metadata_tracker.check_source_changed(
                    source_path, fast_path_mtime=fast_path
                )

                if not changed:
                    # Content unchanged, but validate output integrity if needed
                    # (output integrity check disabled by default for performance)
                    return (True, f"content unchanged: {reason}")

                # Content changed → force retranslation regardless of mtime
                return (False, f"content changed: {reason}")

            except Exception as e:
                # Hash check failed → fall back to default
                logger.warning(f"Content hash check failed: {e}")
                # Fall through to default

        # If we got here after mtime check and output was newer, skip translation
        if use_mtime_check:
            try:
                source_mtime = source_path.stat().st_mtime
                output_mtime = output_path.stat().st_mtime
                if output_mtime >= source_mtime:
                    return (True, "output is newer than source (mtime)")
            except OSError:
                pass

        # Default: don't skip
        return (False, "default behavior")

    def _is_valid_output(self, output_path: Path) -> bool:
        """
        RES-05: Check if output file is valid.

        Criteria:
        - File exists
        - File size > 0
        - File is readable
        - Has minimum expected content (basic structure)

        Args:
            output_path: Path to output file

        Returns:
            True if output appears valid
        """
        try:
            # Check size
            size = output_path.stat().st_size
            if size == 0:
                return False

            # Check readability
            with open(output_path, encoding="utf-8") as f:
                content = f.read(1024)  # Read first 1KB

            # Basic validation: has some content
            if len(content.strip()) < 10:
                return False

            return True

        except Exception as e:
            logger.warning(f"Output validation failed for {output_path}: {e}")
            return False

    @staticmethod
    def _compute_quality_score(stats) -> str:
        """Compute the per-file quality signal from validation stats."""
        if stats.validation_errors > 0:
            return "FAIL"
        if stats.ast_missing_nodes > 1 or stats.validation_warnings > 0:
            return "PARTIAL"
        return "PASS"

    def _get_dir_orchestrator(self):
        """Return the directory orchestrator, creating it for lightweight test instances."""
        orchestrator = getattr(self, "_dir_orchestrator", None)
        if orchestrator is None:
            from .directory_orchestrator import DirectoryOrchestrator

            orchestrator = DirectoryOrchestrator(self)
            self._dir_orchestrator = orchestrator

        ft_model = getattr(self, "_quality_filter_ft_model", None)
        if ft_model is not None and getattr(orchestrator, "_quality_filter_ft_model", None) is None:
            orchestrator._quality_filter_ft_model = ft_model

        return orchestrator

    def _quality_check_complete_file(
        self,
        source_path: Path,
        target_langs: list[str],
        site_profile,
        ttl_days: int = 7,
        confidence: float = 0.80,
        max_paragraphs: int = 2,
    ) -> bool:
        """Delegate to DirectoryOrchestrator."""
        return self._get_dir_orchestrator()._quality_check_complete_file(
            source_path=source_path,
            target_langs=target_langs,
            site_profile=site_profile,
            ttl_days=ttl_days,
            confidence=confidence,
            max_paragraphs=max_paragraphs,
        )

    def _get_output_dir(self, site_profile) -> Path:
        """Get output directory for the site profile.

        Args:
            site_profile: Site profile configuration

        Returns:
            Path to output directory
        """
        if self.output_dir_override:
            return self.output_dir_override

        # Get from site profile or use default
        return Path(getattr(site_profile, "output_dir", None) or "output")

    def _discover_all_segments(
        self,
        files: list[Path],
        target_langs: list[str],
        site_id: str,
        source_lang: str = "en",
    ) -> int:
        """
        Pre-parse all files to discover total segment count.

        This provides accurate progress tracking from the start by scanning all files
        upfront to count segments, rather than discovering them progressively during
        translation.

        Args:
            files: List of markdown files to scan
            target_langs: Target languages
            site_id: Site identifier for profile lookup
            source_lang: Source language (default: "en")

        Returns:
            Total number of segments across all files * target languages
        """
        from ..observability.progress import get_progress_tracker

        total_segments = 0
        progress = get_progress_tracker()

        # Get site profile for extractor configuration
        site_profile = self.config.get_site_profile(site_id)

        logger.info("[INIT] Discovering files...")

        for i, file_path in enumerate(files, 1):
            # Show progress every 5 files or on last file
            if i % 5 == 0 or i == len(files):
                logger.info(f"[INIT] Scanning files... ({i}/{len(files)})")

            try:
                # Parse file (quick read + parse, no translation)
                with open(file_path, encoding="utf-8") as f:
                    content = f.read()
                doc = self.parser.parse_string(content)

                # Extract segments (same logic as translate_file)
                extractor = SegmentExtractor(
                    site_profile, terminology_manager=self.terminology_manager
                )
                segments = extractor.extract_all(doc, source_lang)

                # Count segments per file * number of target languages
                segment_count = len(segments) * len(target_langs)
                total_segments += segment_count

            except Exception as e:
                logger.warning(f"Failed to parse {file_path} during discovery: {e}")
                # Continue with other files, don't fail the whole discovery

        logger.info(f"[INIT] Found {len(files)} files with {total_segments:,} total segments")

        return total_segments

    def _filter_source_files(
        self,
        files: list,
        site_profile,
        target_langs: list[str],
    ) -> list:
        """Delegate to DirectoryOrchestrator."""
        return self._dir_orchestrator._filter_source_files(files, site_profile, target_langs)

    def translate_file(
        self,
        site_id: str,
        file_path: Path,
        target_langs: list[str],
        force: bool = False,
        force_overwrite: bool = False,
        validate: bool | None = None,
        trigger_type: str = "cli",
        retry_budget_override: int | None = None,
    ) -> TranslationResult:
        """
        Translate a single Hugo markdown file.

        Args:
            site_id: Site identifier for configuration
            file_path: Path to source markdown file
            target_langs: List of target language codes
            force: If True, bypass TM and force retranslation
            validate: Whether to validate translation quality. If None, uses engine default.
            trigger_type: How translation was triggered ("cli", "scheduled", "web", etc.)

        Returns:
            TranslationResult with outcomes for all target languages
        """
        # TEL-04: Start telemetry tracking
        telemetry_enabled = (
            self.enable_telemetry and self.telemetry and self.telemetry.is_available()
        )
        telemetry_cm = None  # Context manager
        telemetry_run = None  # RunContext
        if telemetry_enabled:
            telemetry_cm = self.telemetry.track_translation_session(
                job_type="translate_file",
                trigger_type=trigger_type,
                file_path=file_path,
                target_langs=target_langs,
                site_id=site_id,
                force=force,
            )
            telemetry_run = telemetry_cm.__enter__()

            # GS-02: Register telemetry context for graceful shutdown
            try:
                from ..observability.graceful_shutdown import register_active_context

                register_active_context(telemetry_run)
            except ImportError:
                pass  # Graceful degradation if module not available

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

            # Locale allowlist policy: for sites with strict_locale_allowlist
            # set, reject any target locale outside target_langs, regardless
            # of caller (CLI, quality scripts, orchestrator jobs) — this is
            # the last-line safety net. No-op for non-strict sites.
            try:
                validate_requested_locales(site_profile, target_langs)
            except LocalePolicyViolation as e:
                result.errors.append(str(e))
                return result

            source_lang = site_profile.default_source_lang

            # Guard: reject translated files in file-based localization layouts
            output_layout = getattr(site_profile, "output_layout", None)
            if output_layout and not getattr(output_layout, "per_language_folders", True):
                is_translated, detected_lang = _is_translated_filename(
                    file_path.name, target_langs, source_lang=source_lang
                )
                if is_translated:
                    msg = (
                        f"Refusing to translate already-translated file: {file_path.name} "
                        f"(detected language: {detected_lang}). "
                        "Pass a source file without a language code in the filename."
                    )
                    logger.warning(msg)
                    result.errors.append(msg)
                    return result

            # Initialize metadata tracker for content hash tracking (if enabled)
            if self.enable_content_hash and not self.metadata_tracker:
                from pathlib import Path

                from ..utils.config_loader import get_global_config

                global_config = get_global_config()

                # Determine metadata storage location
                content_hash_config = global_config.get("content_hash_tracking", {})
                metadata_dir_config = content_hash_config.get("metadata_dir", "")

                if metadata_dir_config:
                    # Use dedicated metadata directory (Docker volume)
                    metadata_dir = Path(metadata_dir_config)
                    metadata_dir.mkdir(parents=True, exist_ok=True)
                else:
                    # Use output directory (default behavior)
                    metadata_dir = self._get_output_dir(site_profile)

                metadata_file = metadata_dir / ".translation_metadata.json"

                # Get hash algorithm and lock timeout from config
                hash_algorithm = content_hash_config.get("hash_algorithm", "md5")
                lock_timeout = content_hash_config.get("redis_lock_timeout", 30)
                auto_cleanup_config = content_hash_config.get(
                    "auto_cleanup", {}
                )  # CHH-05: Cleanup config

                self.metadata_tracker = MetadataTracker(
                    metadata_file=metadata_file,
                    hash_algorithm=hash_algorithm,
                    site_id=site_id,
                    redis_client=self.redis_client,  # CHH-02: Pass Redis client for locking
                    lock_timeout=lock_timeout,
                    auto_cleanup_config=auto_cleanup_config,  # CHH-05: Automatic cleanup
                )
                self.metadata_tracker.load()

            # Safety check: prevent translating already-translated files
            # This prevents creating double-language files like index.es.da.md
            output_layout = getattr(site_profile, "output_layout", None)
            per_language_folders = False
            if output_layout:
                per_language_folders = (
                    getattr(output_layout, "per_language_folders", False)
                    if hasattr(output_layout, "per_language_folders")
                    else output_layout.get("per_language_folders", False)
                )

            if not per_language_folders:
                # For file-based localization, use helper to check if file is already translated
                is_translated, detected_lang = _is_translated_filename(
                    file_path.name, target_langs, source_lang
                )

                if is_translated:
                    error_msg = (
                        f"Refusing to translate already-translated file: {file_path.name}\n"
                        f"File appears to be a {detected_lang} translation. "
                        f"Only source files (without language codes) should be translated.\n"
                        f"To fix: Remove language-tagged files from input or use a directory with only source files."
                    )
                    logger.error(error_msg)
                    result.errors.append(error_msg)
                    return result

            # Parse file
            logger.info(f"Parsing {file_path}")
            try:
                with open(file_path, encoding="utf-8") as f:
                    content = f.read()
                doc = self.parser.parse_string(content)
                doc.source_path = file_path  # Set source path for output routing
            except Exception as e:
                result.errors.append(f"Parse error: {e}")
                return result

            # Extract segments (TRM-05: pass terminology_manager for term protection)
            # HT-QUALITY-GATES-001 RC1/RC3: force_protected_fields must reach THIS
            # extractor, not just the AST-body path's TextUnitExtractor — this is
            # the one that actually decides whether `title` becomes a translatable
            # segment for family/platform index pages (confirmed directly: a
            # canary retranslation after fixing only the AST-path mechanism still
            # produced wrong titles, traced to this exact extractor never having
            # had any is_family_platform_index() awareness at all).
            from .segment_translator import compute_force_protected_fields

            extractor = SegmentExtractor(
                site_profile,
                terminology_manager=self.terminology_manager,
                force_protected_fields=compute_force_protected_fields(doc, site_profile),
            )
            segments = extractor.extract_all(doc, source_lang)
            result.stats.total_segments = len(segments)

            logger.info(f"Extracted {len(segments)} segments from {file_path}")

            # Progress tracking: file started with segment count
            # Multiply by number of target languages since segments_completed is called per language
            progress = get_progress_tracker()
            if progress:
                progress.file_started(
                    str(file_path), segment_count=len(segments) * len(target_langs)
                )

            # INT-01: Translate for each target language with retry loop
            # VA-03: Determine if verification should run
            should_validate = validate if validate is not None else self.enable_validation
            should_verify = self.enable_verification
            should_fix = self.enable_verification_fix and should_verify
            max_retry_attempts = (
                retry_budget_override
                if retry_budget_override is not None
                else (self.decision_engine.max_retry_attempts if self.decision_engine else 2)
            )
            if max_retry_attempts < 0:
                raise ValueError("retry_budget_override must be non-negative")

            # CRITICAL FIX: Cache output paths to prevent path mismatch between skip check and write
            # Bug: If path calculated differently at write time, skip check tests wrong path
            output_paths_cache = {}

            for target_lang in target_langs:
                # RES-05: Check if translation can be skipped
                # Calculate path ONCE and cache it
                output_path = self._get_output_path(file_path, target_lang, site_profile)
                output_paths_cache[target_lang] = output_path
                should_skip, skip_reason = self._should_skip_translation(
                    source_path=file_path,
                    output_path=output_path,
                    force_retranslate=self.force_retranslate or force,
                    use_mtime_check=True,
                    target_lang=target_lang,
                )

                if should_skip:
                    logger.debug(f"Skipping {file_path} -> {target_lang}: {skip_reason}")
                    result.skipped_langs.append(target_lang)
                    result.skip_reasons[target_lang] = skip_reason

                    # Record skip in progress tracker
                    progress = get_progress_tracker()
                    if progress:
                        progress.record_skip(target_lang, skip_reason)

                    # Count as success since output already exists
                    result.outputs[target_lang] = output_path

                    # Progress tracking: count skipped language segments as completed
                    # since the work already exists
                    progress = get_progress_tracker()
                    if progress:
                        progress.segments_completed(len(segments))

                    continue

                # NOTE: Multi-language contamination (where state bleeds between target languages)
                # is prevented by CLI subprocess isolation. See cli.py line 1082 where each target
                # language is processed in a separate subprocess for complete state isolation.

                # WS-COMP-4: LLM escalation — check if this output file is in the LLM escalation
                # set (MT has failed repeatedly). If so AND config enables it, override model to LLM.
                _llm_model_override: str | None = None
                _rtq_llm_paths = getattr(self, "_rtq_llm_output_paths", None)
                if _rtq_llm_paths and str(output_path.resolve()) in _rtq_llm_paths:
                    try:
                        _te_cfg = (
                            self.config.get_config().get("translation_engine", {})
                            if hasattr(self.config, "get_config")
                            else {}
                        )
                        if _te_cfg.get("llm_escalation_enabled", False):
                            _llm_model_override = _te_cfg.get(
                                "llm_escalation_model", "professionalize_llm"
                            )
                            logger.info(
                                f"LLM escalation: overriding model to '{_llm_model_override}' "
                                f"for stuck CASE 4 file {output_path.name} ({target_lang})"
                            )
                    except Exception:
                        pass

                # TC-DECOMP-03: Delegate per-language retry loop to FileTranslationPipeline
                from .file_pipeline import LanguageTranslationContext

                _lang_ctx = LanguageTranslationContext(
                    site_id=site_id,
                    site_profile=site_profile,
                    doc=doc,
                    segments=segments,
                    content=content,
                    source_lang=source_lang,
                    target_lang=target_lang,
                    output_path=output_path,
                    file_path=file_path,
                    force=force,
                    force_overwrite=force_overwrite,
                    should_validate=should_validate,
                    should_verify=should_verify,
                    should_fix=should_fix,
                    max_retry_attempts=max_retry_attempts,
                    output_paths_cache=output_paths_cache,
                    llm_model_override=_llm_model_override,
                )

                self._file_pipeline.translate_language(_lang_ctx, result)

            # Mark success if at least one language succeeded
            result.success = len(result.outputs) > 0

            # RES-05: Log skip summary if any languages were skipped
            if result.skipped_langs:
                logger.info(
                    f"Skipped {len(result.skipped_langs)} language(s) for {file_path}: "
                    f"{', '.join(result.skipped_langs)} (existing outputs)"
                )

            # Progress tracking: file completed
            if progress:
                # Calculate if any new translations occurred
                has_new_translations = len(result.outputs) > len(result.skipped_langs)
                progress.file_completed(
                    success=result.success, has_new_translations=has_new_translations
                )

        except Exception as e:
            # SR-02: Handle shutdown request - re-raise to propagate up
            from .exceptions import ShutdownRequested

            if isinstance(e, ShutdownRequested):
                logger.info(f"Shutdown requested while translating {file_path}")
                # Mark file as incomplete before propagating shutdown
                progress = get_progress_tracker()
                if progress:
                    progress.file_completed(success=False, has_new_translations=False)
                raise  # Re-raise to propagate to caller

            # TC-02: TranslationRejectedError already logged by inner handler (line 1779)
            # and re-raised. Don't double-log it as "Unexpected error".
            if isinstance(e, TranslationRejectedError):
                progress = get_progress_tracker()
                if progress:
                    progress.record_error("translation_error", str(e), str(file_path))
                    progress.file_completed(success=False, has_new_translations=False)
                if telemetry_run:
                    telemetry_run.log_event("validation_rejected", {"reason": str(e)})
                # Queue rejected file for retranslation on the next worker run so it
                # is not silently skipped by the completion filter indefinitely.
                try:
                    _rejected_path = locals().get("output_path") or locals().get(
                        "expected_output_path"
                    )
                    _rejected_lang = locals().get("target_lang")
                    if _rejected_path and _rejected_lang:
                        _rtq_add(_rejected_path, _rejected_lang)
                        logger.info(
                            f"Queued rejected translation for retry: {_rejected_path.name} ({_rejected_lang})"
                        )
                except Exception as _rtq_err:
                    logger.debug(f"Failed to queue rejected file for retry: {_rtq_err}")
                return result

            # OOM-01: Detect OOM errors and allow RetryHandler to engage (outer handler)
            if self._is_oom_error(e):
                if self.retry_handler:
                    # Re-raise to let RetryHandler catch and apply batch reduction
                    logger.debug(
                        f"OOM error detected for {file_path} (outer handler). "
                        f"Re-raising to engage RetryHandler with batch reduction."
                    )
                    # Mark file as incomplete before re-raising
                    progress = get_progress_tracker()
                    if progress:
                        progress.record_error("translation_error", str(e), str(file_path))
                        progress.file_completed(success=False, has_new_translations=False)
                    raise

            logger.error(f"Unexpected error translating {file_path}: {e}")
            result.errors.append(f"Unexpected error: {e}")
            # Progress tracking: record error
            progress = get_progress_tracker()
            if progress:
                progress.record_error("translation_error", str(e), str(file_path))
                progress.file_completed(success=False, has_new_translations=False)
            # TEL-04: Track error in telemetry
            if telemetry_run:
                telemetry_run.log_event("error", {"error": str(e)})
                # Capture full stack trace as error_details (truncate to 10KB)
                import traceback

                error_details = traceback.format_exc()
                # Truncate to 10KB to avoid API payload issues
                max_error_details_size = 10 * 1024  # 10KB
                if len(error_details) > max_error_details_size:
                    error_details = error_details[:max_error_details_size] + "\n... [truncated]"
                telemetry_run.set_metrics(error_details=error_details)

        finally:
            result.stats.files_translated = 1 if result.success else 0
            result.stats.files_generated = len(result.outputs)
            result.stats.duration_seconds = time.time() - start_time

            # RES-05: Calculate language-level skip vs translation counts
            result.stats.langs_skipped = len(result.skipped_langs)
            result.stats.langs_translated = len(result.outputs) - len(result.skipped_langs)

            if result.stats.multiline_segments > 0:
                logger.info(
                    "MSP-02: Multiline batching summary for %s: segments=%d, lines=%d, backend_calls=%d",
                    file_path,
                    result.stats.multiline_segments,
                    result.stats.multiline_lines,
                    result.stats.multiline_backend_calls,
                )

            # TEL-04: Track stats and close telemetry
            if telemetry_run and telemetry_enabled:
                try:
                    # RES-05: Detect if all languages were skipped (no work done)
                    # CRITICAL: If no work done, create NO telemetry entry at all
                    total_langs = len(result.outputs)  # Total languages requested
                    all_skipped = (
                        result.stats.langs_skipped == total_langs
                        and total_langs > 0
                        and result.success
                    )

                    if all_skipped:
                        # NO WORK DONE → NO TELEMETRY ENTRY
                        # Exit telemetry context without recording anything
                        telemetry_cm.__exit__(None, None, None)
                        logger.info(
                            "Skipping telemetry entry: all languages skipped (no work done)",
                            extra={
                                "langs_skipped": result.stats.langs_skipped,
                                "total_langs": total_langs,
                                "skipped_langs": result.skipped_langs,
                            },
                        )
                    else:
                        # Work was done → Record telemetry with skip metrics
                        self.telemetry.track_translation_stats(
                            telemetry_run, result.stats, output_paths=result.outputs
                        )
                        # SR-03: Use helper functions for RunRecord fields (TEL-05-B)
                        from ..observability.telemetry_integration import (
                            build_error_summary,
                            build_output_summary,
                            calculate_items_metrics,
                        )

                        items_metrics = calculate_items_metrics(
                            job_type="translate_file",
                            stats=result.stats,
                            skip_count=len(result.skipped_langs),  # RES-05: Pass skip count
                        )
                        output_summary = build_output_summary(
                            job_type="translate_file",
                            outputs=result.outputs,
                            errors=result.errors,
                            skipped_langs=result.skipped_langs,  # RES-05: Pass skip data
                            skip_reasons=result.skip_reasons,  # RES-05: Pass skip reasons
                        )
                        error_summary = build_error_summary(result.errors, max_errors=5)

                        # TI-01: Use centralized helper with observability
                        duration_ms, used_fallback = _safe_duration_ms(
                            result.stats, context="translate_file"
                        )

                        telemetry_run.set_metrics(
                            duration_ms=duration_ms,  # API requires integer
                            items_discovered=items_metrics["items_discovered"],
                            items_succeeded=items_metrics["items_succeeded"],
                            items_failed=items_metrics["items_failed"],
                            output_summary=output_summary,
                            error_summary=error_summary,
                        )
                        telemetry_cm.__exit__(None, None, None)

                    # GS-02: Unregister telemetry context after normal completion
                    try:
                        from ..observability.graceful_shutdown import unregister_active_context

                        unregister_active_context(telemetry_run)
                    except ImportError:
                        pass
                except Exception as telemetry_error:
                    logger.warning(f"Telemetry tracking failed: {telemetry_error}")

            # Save adaptive batch statistics
            if self.batch_stats_tracker:
                try:
                    self.batch_stats_tracker.save()
                    logger.debug("Saved adaptive batch statistics")
                except Exception as save_error:
                    logger.warning(f"Failed to save batch statistics: {save_error}")

            # TC-GIT-01: Store telemetry context for git commit association
            if telemetry_enabled and telemetry_run:
                result.telemetry_context = telemetry_run

            # D5: Clear GPU cache after file translation (per-file, not per call)
            try:
                if self.model_loader:
                    self.model_loader.clear_cache_after_file()
                    if self.model_loader.check_and_clear_cache():
                        logger.info("Performed aggressive GPU cache clear after file translation")
            except Exception as cache_error:
                logger.warning(f"GPU cache clear after file failed: {cache_error}")

        return result

    def _clear_language_cache(self) -> None:
        """
        Clear L1 TM cache to free memory between language switches.

        T304: Memory management for round-robin mode (federated-splashing-panda).
        In round-robin mode, clearing the cache between languages prevents
        memory buildup when processing many languages.
        """
        with self._tm_lock:
            if hasattr(self.tm, "l1") and hasattr(self.tm.l1, "clear"):
                cache_size_before = len(self.tm.l1.cache) if hasattr(self.tm.l1, "cache") else 0
                self.tm.l1.clear()
                logger.debug(f"Cleared L1 cache ({cache_size_before} entries)")

    def _translate_single_language(
        self,
        site_id: str,
        file_path: Path,
        target_lang: str,
        force: bool = False,
    ) -> TranslationResult:
        """
        Translate file for single target language.

        T304: Helper method for parallel execution (federated-splashing-panda).
        This method translates a file for a single language, used by
        ParallelLanguageExecutor to process languages concurrently.

        Args:
            site_id: Site identifier
            file_path: Path to source file
            target_lang: Target language code
            force: Force retranslation (bypass cache)

        Returns:
            TranslationResult for the single language
        """
        # Call translate_file with single language
        return self.translate_file(
            site_id=site_id,
            file_path=file_path,
            target_langs=[target_lang],
            force=force,
        )

    def _translate_body_ast(
        self,
        doc,
        target_lang: str,
        site_profile,
        stats: TranslationStats,
        segments: list | None = None,
        translations: dict[str, str] | None = None,
    ) -> str:
        """Delegate to SegmentTranslator."""
        return self._segment_translator._translate_body_ast(
            doc,
            target_lang,
            site_profile,
            stats,
            segments=segments,
            translations=translations,
        )

    def _translate_to_language(
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
        """Delegate to SegmentTranslator."""
        return self._segment_translator.translate_to_language(
            site_id=site_id,
            site_profile=site_profile,
            doc=doc,
            segments=segments,
            source_lang=source_lang,
            target_lang=target_lang,
            force=force,
            stats=stats,
            retry_feedback=retry_feedback,
            retry_count=retry_count,
            model_id_override=model_id_override,
            tm_write_buffer=tm_write_buffer,
        )

    def _write_output(
        self, content: str, output_path: Path, source_path: Path, stats: TranslationStats
    ) -> None:
        """
        Write translated content to output file atomically.

        Uses atomic write (temp file + rename) to prevent file corruption
        on unexpected termination (Ctrl+C, kill, power loss).

        RES-09: Enhanced with comprehensive error detection and recovery.

        Args:
            content: Translated markdown content
            output_path: Path to write the output file
            source_path: Original source file path (for logging)
            stats: Stats object to update with file operation metrics

        Raises:
            AtomicWriteError: If atomic write operation fails
            DiskFullError: If disk is full
            PermissionError: If permission denied
            InvalidPathError: If path is invalid
            ReadOnlyFilesystemError: If filesystem is read-only
        """
        # TEL-04: Track file operation (add vs. update)
        file_existed = output_path.exists()

        # RES-09: Check available disk space before write
        content_size = len(content.encode("utf-8"))
        free_space = self._get_free_space(output_path.parent)

        if free_space > 0 and free_space < content_size * 2:  # 2x for temp file
            logger.warning(
                f"Low disk space: {free_space / 1024 / 1024:.1f}MB free, "
                f"~{content_size * 2 / 1024:.1f}KB needed for {output_path.name}"
            )

        # RES-03: Atomic write - prevents file corruption on crash
        # RES-09: Enhanced error handling with specific exception types
        try:
            atomic_write(
                path=output_path, content=content, encoding="utf-8", fsync=True, create_parents=True
            )
        except DiskFullError:
            # RES-09: Provide helpful disk full message
            free_space = self._get_free_space(output_path.parent)
            logger.error(
                f"Disk full when writing {output_path}. "
                f"Free space: {free_space / 1024 / 1024:.1f}MB, "
                f"needed: ~{content_size / 1024:.1f}KB"
            )
            raise
        except PermissionError:
            # RES-09: Clear permission error message
            logger.error(f"Permission denied: {output_path}. Check file permissions and ownership.")
            raise
        except InvalidPathError as e:
            # RES-09: Clear invalid path message
            logger.error(f"Invalid path: {e}")
            raise
        except ReadOnlyFilesystemError:
            # RES-09: Clear read-only filesystem message
            logger.error(f"Read-only filesystem: {output_path}")
            raise
        except AtomicWriteError as e:
            # RES-09: Generic atomic write error
            logger.error(f"Failed to write output atomically: {e}")
            raise

        # TEL-04: Update file operation stats
        if file_existed:
            stats.md_files_updated += 1
        else:
            stats.md_files_added += 1
        stats.bytes_written_md += len(content.encode("utf-8"))

        logger.info(f"Written translated file: {output_path}")

    def _pre_write_validation(
        self,
        *,
        content: str,
        output_path: Path,
        source_path: Path,
        target_lang: str,
        site_id: str,
        site_profile,
    ) -> tuple[bool, list[str]]:
        """Validate serialized candidate bytes and placement without disk I/O."""
        errors: list[str] = []
        try:
            encoded = content.encode("utf-8")
            if not encoded or not content.strip():
                errors.append("candidate is empty")
            if encoded.decode("utf-8") != content:
                errors.append("candidate is not a stable UTF-8 round trip")
            self.parser.parse_string(content)
        except Exception as exc:
            errors.append(f"candidate serialization/parse failed: {exc}")

        try:
            from .validation.file_placement_validator import FilePlacementValidator

            validator = FilePlacementValidator(config_service=self.config)
            placement = validator.validate(
                str(source_path),
                str(output_path),
                {
                    "source_path": source_path,
                    "source_lang": getattr(site_profile, "default_source_lang", "en"),
                    "target_lang": target_lang,
                    "site_id": site_id,
                    "site_profile": site_profile,
                    "output_override_active": bool(self.output_dir_override),
                },
            )
            for issue in placement.issues:
                severity = getattr(getattr(issue, "severity", None), "value", "error")
                if severity in {"error", "warning"}:
                    errors.append(f"placement {severity}: {issue.message}")
            if not placement.success and not errors:
                errors.append("file placement validation failed")
        except Exception as exc:
            errors.append(f"file placement validator unavailable: {exc}")

        return not errors, errors

    def accept_candidate_bytes(
        self,
        *,
        source_bytes: bytes,
        candidate_bytes: bytes,
        source_path: Path,
        output_path: Path,
        target_lang: str,
        site_id: str,
        model_fingerprint: str = "",
    ):
        """Revalidate immutable bytes and return an acceptance capability.

        This is the non-writing counterpart of the production validation path.
        It exists for fail-closed receipt recovery and verification: callers
        receive an ``AcceptedTranslation`` only when the exact supplied bytes
        pass the full validation suite, independent verification, all 44 write
        gates (including the fidelity judge), placement checks, and the
        fixed-point auto-clean rerun.  It never writes output or flushes TM.
        """
        from .models import AcceptedTranslation
        from .reconstructor import ASTRenderer
        from .validation.post_translation_validator import (
            ValidationDecision as PostValidationDecision,
        )

        if self.validation_policy != "zero-defect":
            raise RuntimeError("candidate-byte acceptance requires zero-defect policy")
        if not isinstance(source_bytes, bytes) or not isinstance(candidate_bytes, bytes):
            raise TypeError("candidate-byte acceptance requires immutable bytes")
        if not self.validation_suite or not self.decision_engine:
            raise RuntimeError("candidate-byte acceptance requires all validators")

        try:
            source_content = source_bytes.decode("utf-8", errors="strict")
            translated_content = candidate_bytes.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ValueError("candidate-byte acceptance requires valid UTF-8") from exc
        if translated_content.encode("utf-8") != candidate_bytes:
            raise ValueError("candidate bytes are not a stable UTF-8 round trip")

        site_profile = self.config.get_site_profile(site_id)
        if site_profile is None:
            raise RuntimeError(f"site profile unavailable: {site_id}")
        source_doc = self.parser.parse_string(source_content)
        source_doc.source_path = source_path
        translated_doc = self.parser.parse_string(translated_content)

        source_body = (
            ASTRenderer().render_to_markdown(source_doc.ast)
            if getattr(source_doc, "ast", None)
            else ""
        )
        # Match the production file pipeline exactly: validation operates on
        # the serialized body bytes with only the frontmatter delimiters
        # removed, not on a parser-normalized reconstruction.
        translated_body = translated_content
        if translated_body.startswith("---"):
            frontmatter_end = translated_body.find("---", 3)
            if frontmatter_end != -1:
                translated_body = translated_body[frontmatter_end + 3 :].lstrip("\n")
        validation_result = self.validation_suite.validate_aggregated(
            source_body,
            translated_body,
            context={
                "source_lang": getattr(site_profile, "default_source_lang", "en"),
                "target_lang": target_lang,
                "file_path": str(source_path),
                "validation_policy": "zero-defect",
            },
        )
        validation_result.issues.extend(
            self._check_frontmatter_language(translated_content, target_lang)
        )
        if (
            getattr(validation_result, "error_count", 0) > 0
            or getattr(validation_result, "warning_count", 0) > 0
        ):
            validators = sorted(
                {
                    str(getattr(issue, "validator", "unknown"))
                    for issue in getattr(validation_result, "issues", [])
                }
            )
            raise ValueError(
                "candidate rejected by validation suite "
                f"errors={getattr(validation_result, 'error_count', 0)} "
                f"warnings={getattr(validation_result, 'warning_count', 0)} "
                f"validators={','.join(validators) or 'unknown'}"
            )
        decision = self.decision_engine.make_decision(
            validation_result=validation_result,
            retry_count=0,
            source=source_body,
            site_id=site_id,
            target_lang=target_lang,
        )
        if decision.decision != PostValidationDecision.ACCEPT:
            raise ValueError("candidate rejected by validation decision")

        verification = self._get_verification_agent().verify(
            source_doc={
                "frontmatter": getattr(source_doc, "frontmatter", {}),
                "body": str(getattr(source_doc, "body", "")),
            },
            translated_doc={
                "frontmatter": getattr(translated_doc, "frontmatter", {}),
                "body": str(getattr(translated_doc, "body", "")),
            },
            target_lang=target_lang,
            context={
                "source_lang": getattr(site_profile, "default_source_lang", "en"),
                "file_path": str(source_path),
                "site_id": site_id,
                "validation_policy": "zero-defect",
            },
        )
        if (
            not verification.passed
            or getattr(verification, "error_count", 0) > 0
            or getattr(verification, "warning_count", 0) > 0
        ):
            checks = sorted(
                {
                    str(getattr(issue, "check_name", "unknown"))
                    for issue in getattr(verification, "issues", [])
                }
            )
            locations = sorted(
                {
                    hashlib.sha256(
                        str(getattr(issue, "location", "unknown")).encode("utf-8")
                    ).hexdigest()[:16]
                    for issue in getattr(verification, "issues", [])
                }
            )
            raise ValueError(
                "candidate rejected by independent verification "
                f"errors={getattr(verification, 'error_count', 0)} "
                f"warnings={getattr(verification, 'warning_count', 0)} "
                f"checks={','.join(checks) or 'unknown'} "
                f"location_hashes={','.join(locations) or 'none'}"
            )

        gate_result = self._write_gate.evaluate_zero_defect(
            translated_content=translated_content,
            source_content=source_content,
            target_lang=target_lang,
            output_path=output_path,
            source_doc=source_doc,
            # Receipt recovery validates a byte-identical existing blob.  This
            # bypasses only Gate 3's "path already exists" condition; it does
            # not bypass or weaken any translation-quality gate.
            force_overwrite=True,
            site_profile=site_profile,
            translation_stats=TranslationStats(),
        )
        if not gate_result.passed:
            failed_gates = sorted(
                gate_id
                for gate_id, item in gate_result.gate_results.items()
                if not item.get("passed", False)
            )
            reason_hash = hashlib.sha256(
                str(gate_result.error or "unknown").encode("utf-8")
            ).hexdigest()[:16]
            raise ValueError(
                "candidate rejected by write gate "
                f"failed_gates={','.join(map(str, failed_gates)) or 'unknown'} "
                f"reason_sha256={reason_hash}"
            )
        expected_gate_ids = set(range(2, 45))
        if set(gate_result.gate_results) != expected_gate_ids or any(
            not item.get("passed", False) for item in gate_result.gate_results.values()
        ):
            raise ValueError("candidate lacks an all-pass 43-gate write receipt")
        final_content = (
            gate_result.cleaned_content
            if gate_result.cleaned_content is not None
            else translated_content
        )
        if final_content.encode("utf-8") != candidate_bytes:
            raise ValueError("candidate bytes differ from fixed-point gate output")
        fidelity = getattr(gate_result, "_fidelity_result", None)
        if not isinstance(fidelity, dict) or fidelity.get("verdict") != "pass":
            raise ValueError("candidate lacks an independent fidelity PASS")

        pre_write_passed, pre_write_errors = self._pre_write_validation(
            content=translated_content,
            output_path=output_path,
            source_path=source_path,
            target_lang=target_lang,
            site_id=site_id,
            site_profile=site_profile,
        )
        if not pre_write_passed:
            raise ValueError(
                f"candidate rejected by pre-write validation ({len(pre_write_errors)} finding(s))"
            )

        gate_receipt = {
            1: {"passed": True, "action": "verification", "error": None},
            **gate_result.gate_results,
        }
        campaign_context = getattr(self, "campaign_context", {}) or {}
        fidelity_model = str(fidelity.get("model") or "")
        receipt_model = model_fingerprint or (
            f"receipt-recovery:fidelity={fidelity_model}"
            if fidelity_model
            else "receipt-recovery:fidelity=unknown"
        )
        return AcceptedTranslation(
            content=candidate_bytes,
            source_path=source_path,
            output_path=output_path,
            source_sha256=hashlib.sha256(source_bytes).hexdigest(),
            output_sha256=hashlib.sha256(candidate_bytes).hexdigest(),
            target_lang=target_lang,
            validation_policy="zero-defect",
            gate_results=gate_receipt,
            config_fingerprint=str(campaign_context.get("config_fingerprint") or ""),
            model_fingerprint=receipt_model,
            campaign_id=str(campaign_context.get("campaign_id") or ""),
        )

    def _tm_site_namespace(self, site_id: str, source_path: Path | str | None) -> str:
        """Bind campaign TM entries to campaign, config, and source context."""
        context = getattr(self, "campaign_context", {}) or {}
        campaign_id = str(context.get("campaign_id") or "")
        config_fingerprint = str(context.get("config_fingerprint") or "")
        if not campaign_id:
            return site_id
        source_context = str(Path(source_path).resolve()) if source_path else ""
        source_fingerprint = hashlib.sha256(source_context.encode("utf-8")).hexdigest()[:16]
        return (
            f"{site_id}::campaign={campaign_id}"
            f"::config={config_fingerprint[:16]}"
            f"::source={source_fingerprint}"
        )

    def _write_accepted_output(self, accepted, stats: TranslationStats) -> None:
        """Persist an AcceptedTranslation and verify its bytes immediately."""
        from .models import AcceptedTranslation

        if not isinstance(accepted, AcceptedTranslation):
            raise TypeError("zero-defect writer requires AcceptedTranslation")
        if accepted.validation_policy != "zero-defect":
            raise ValueError("accepted translation has the wrong validation policy")
        expected_gate_ids = set(range(1, 45))
        invalid_gates = [
            gate_id
            for gate_id, item in accepted.gate_results.items()
            if not isinstance(item, dict)
            or not item.get("passed", False)
            or str(item.get("action", "")).lower()
            in {"warn", "warning", "skip", "skipped", "unavailable", "exception"}
            or item.get("error") is not None
        ]
        if set(accepted.gate_results) != expected_gate_ids or invalid_gates:
            raise ValueError("accepted translation contains a non-final gate receipt")

        file_existed = accepted.output_path.exists()
        atomic_write_binary(
            path=accepted.output_path,
            content=accepted.content,
            fsync=True,
            create_parents=True,
        )
        if file_existed:
            stats.md_files_updated += 1
        else:
            stats.md_files_added += 1
        stats.bytes_written_md += len(accepted.content)
        try:
            written = accepted.output_path.read_bytes()
        except Exception:
            accepted.output_path.unlink(missing_ok=True)
            raise
        if hashlib.sha256(written).hexdigest() != accepted.output_sha256:
            accepted.output_path.unlink(missing_ok=True)
            raise RuntimeError(
                f"read-back checksum mismatch for accepted output {accepted.output_path}"
            )
        receipt_sink = getattr(self, "campaign_context", {}).get("receipt_sink")
        if receipt_sink is not None:
            try:
                receipt_sink(accepted.receipt())
            except Exception:
                accepted.output_path.unlink(missing_ok=True)
                raise

    def _flush_accepted_tm(self, accepted, buffered_entries: list[dict[str, Any]]) -> None:
        """Flush deferred TM writes only for an immutable accepted candidate."""
        from .models import AcceptedTranslation

        if not isinstance(accepted, AcceptedTranslation):
            raise TypeError("TM flush requires AcceptedTranslation")
        expected_gate_ids = set(range(1, 45))
        invalid_gates = [
            gate_id
            for gate_id, item in accepted.gate_results.items()
            if not isinstance(item, dict)
            or not item.get("passed", False)
            or str(item.get("action", "")).lower()
            in {"warn", "warning", "skip", "skipped", "unavailable", "exception"}
            or item.get("error") is not None
        ]
        if set(accepted.gate_results) != expected_gate_ids or invalid_gates:
            raise ValueError("TM flush requires an all-44-gates acceptance receipt")
        for entry in buffered_entries:
            self.tm.store(**entry)

    def _load_batch_purity_skip_langs(self) -> list[str]:
        """Load batch_purity_skip_langs list from config.global_config."""
        if not self.config:
            return []
        try:
            gc = getattr(self.config, "global_config", None)
            if gc is None:
                return []
            if isinstance(gc, dict):
                te = gc.get("translation_engine", {}) or {}
                return te.get("batch_purity_skip_langs") or []
            # Pydantic model or similar
            te = getattr(gc, "translation_engine", None)
            if te is None:
                return []
            if isinstance(te, dict):
                return te.get("batch_purity_skip_langs") or []
            return getattr(te, "batch_purity_skip_langs", None) or []
        except Exception:
            return []

    def _check_frontmatter_language(self, translated_content: str, target_lang: str) -> list:
        """Detect mixed-language corruption in translatable frontmatter fields.

        Checks title, description, seoTitle, and summary fields to ensure they
        are written in the target language, not a mix of Arabic, Greek, Catalan, etc.

        Args:
            translated_content: Full translated document including frontmatter
            target_lang: Expected language code (e.g., 'es', 'it', 'cs')

        Returns:
            List of _ValIssue objects (empty if all fields are clean)
        """
        import re as _re

        CHECKED_FIELDS = {"title", "description", "seoTitle", "summary"}
        MIN_CHARS = 20
        # Raised from 0.65 to 0.80: descriptions with C++ API identifiers (::, _xxx)
        # cause langdetect to weakly classify translated text as English.
        # At 0.80, only high-confidence genuine language violations are flagged.
        CONFIDENCE_THRESHOLD = 0.80
        # Regex: C++ scope resolution (mapi_message::from_file) or multiple underscored
        # identifiers — these inflate apparent English ratio in langdetect.
        _API_IDENTIFIER_RE = _re.compile(r"[A-Za-z_]\w*::[A-Za-z_]\w*|(?:\b[a-z]+_[a-z_]+\b.*){2}")

        issues = []
        # Extract frontmatter block
        fm_match = _re.match(r"^---\s*\n(.*?)\n?---\s*\n", translated_content, _re.DOTALL)
        if not fm_match:
            return issues

        try:
            import yaml as _yaml

            fm_data = _yaml.safe_load(fm_match.group(1).strip()) or {}
        except Exception:
            return issues

        try:
            import langdetect as _ld
            from langdetect import DetectorFactory

            DetectorFactory.seed = 0
        except ImportError:
            return issues

        # API reference identifier prefixes — title values starting with these are
        # passthrough (English API class/method names) and must not be language-checked.
        _API_PREFIXES = (
            "Class ",
            "Interface ",
            "Enum ",
            "Struct ",
            "Method ",
            "Property ",
            "Namespace ",
            "Delegate ",
            "Event ",
            "Constructor ",
        )
        _SIMILAR_LANG_MAP = {
            "sr": {"hr", "bs"},  # South Slavic Latin-script
            "hr": {"sr", "bs"},
            "bs": {"sr", "hr"},
            "ms": {"id"},  # Malay ↔ Indonesian
            "id": {"ms"},
            "uk": {"ru", "bg"},  # East Slavic Cyrillic
            "bg": {"ru", "uk"},
            "sk": {"cs"},  # West Slavic
            "cs": {"sk"},
            "zh": {"ja", "zh-cn", "zh-tw"},  # CJK — shared characters
            "ja": {"zh", "zh-cn", "zh-tw"},
            "no": {"da", "nb"},  # North Germanic
            "nb": {"no", "da"},
            "da": {"no", "nb"},
        }

        for field in CHECKED_FIELDS:
            value = fm_data.get(field)
            if not value or not isinstance(value, str) or len(value.strip()) < MIN_CHARS:
                continue
            # Skip API reference identifiers in title/description fields (passthrough content).
            # description values like "Namespace Aspose.Words.Comparing" start with an API
            # prefix and will always contain English namespace names after translation.
            v_stripped = value.strip()
            if field in ("title", "description") and (
                any(v_stripped.startswith(p) for p in _API_PREFIXES)
                or _re.match(r"^[A-Z][A-Za-z0-9.]+$", v_stripped)
                or _API_IDENTIFIER_RE.search(v_stripped)
            ):
                continue
            if _frontmatter_has_strong_script_evidence(v_stripped, target_lang):
                continue
            try:
                # Required product/API/platform identifiers can dominate a
                # short, otherwise-correct Latin-script title. Accept only a
                # strong positive target-language verdict from ordinary prose
                # with governed technical tokens removed. If that positive
                # attestation is absent, retain the stricter raw-text check.
                signal_text = _frontmatter_language_signal_text(v_stripped)
                if sum(character.isalpha() for character in signal_text) >= 6:
                    signal_langs = _ld.detect_langs(signal_text)
                    if signal_langs:
                        signal_top = signal_langs[0]
                        signal_accepted = _SIMILAR_LANG_MAP.get(target_lang, set())
                        if (
                            signal_top.lang == target_lang or signal_top.lang in signal_accepted
                        ) and signal_top.prob > CONFIDENCE_THRESHOLD:
                            continue
                detected_langs = _ld.detect_langs(v_stripped)
                if detected_langs:
                    top = detected_langs[0]
                    # Accept linguistically near-identical languages that share script/vocabulary space.
                    # langdetect frequently confuses these pairs on short technical text.
                    _similar_accepted = _SIMILAR_LANG_MAP.get(target_lang, set())
                    if (
                        top.lang != target_lang
                        and top.lang not in _similar_accepted
                        and top.prob > CONFIDENCE_THRESHOLD
                    ):
                        issues.append(
                            _ValIssue(
                                severity=_ValSeverity.ERROR,
                                validator="FrontmatterLanguageCheck",
                                message=(
                                    f"Frontmatter field '{field}' detected as '{top.lang}' "
                                    f"(confidence {top.prob:.0%}), expected '{target_lang}'. "
                                    f"Preview: '{value[:80]}'"
                                ),
                                location=f"frontmatter.{field}",
                                details={
                                    "field": field,
                                    "detected_lang": top.lang,
                                    "confidence": top.prob,
                                    "expected_lang": target_lang,
                                    **_frontmatter_script_metrics(v_stripped, target_lang),
                                },
                            )
                        )
            except Exception:
                pass  # langdetect is probabilistic; silently skip on any detection error

        return issues

    def _get_purity_threshold(self, lang: str) -> float:
        """Delegate to WriteGateEvaluator."""
        return self._write_gate._get_purity_threshold(lang)

    @staticmethod
    def _should_skip_purity_segment(line: str) -> bool:
        """Delegate to WriteGateEvaluator."""
        from .write_gate import WriteGateEvaluator

        return WriteGateEvaluator._should_skip_purity_segment(line)

    def _verify_final_file_purity(self, content: str, expected_lang: str, detector) -> dict:
        """Delegate to WriteGateEvaluator."""
        return self._write_gate._verify_final_file_purity(content, expected_lang, detector)

    def _get_output_path(self, source_path: Path, target_lang: str, site_profile) -> Path:
        """
        Determine output path for translated file.

        Args:
            source_path: Original file path
            target_lang: Target language code
            site_profile: Site profile

        Returns:
            Output file path
        """
        # SR-02: Priority: CLI override > site profile config
        if self.output_dir_override:
            # Collision fix: Preserve directory structure if input_root is known
            if self.input_root:
                try:
                    # Resolve to absolute paths for reliable relative_to computation
                    abs_source = source_path.resolve()
                    abs_input_root = self.input_root.resolve()
                    # Compute relative path from input root
                    relative_path = abs_source.relative_to(abs_input_root)
                    logger.debug(
                        f"Computed relative path: {relative_path} from {abs_source} relative to {abs_input_root}"
                    )
                except ValueError:
                    # Fallback if source_path is not under input_root
                    logger.warning(
                        f"Source path {source_path} not under input root {self.input_root}, using basename"
                    )
                    relative_path = source_path.name
            else:
                # Fallback: use basename (preserves existing behavior)
                relative_path = source_path.name

            output_path = self.output_dir_override / target_lang / relative_path
            logger.info(f"Using CLI output override: {output_path} (relative: {relative_path})")
            return output_path

        # Delegate the per_language_folders/pattern branch to the shared,
        # config-driven implementation in src/utils/content_discovery.py --
        # the same logic standalone scripts use, so there is exactly one
        # place this substitution logic lives.
        output_layout = getattr(site_profile, "output_layout", None)
        if output_layout:
            output_path = _resolve_translated_path(site_profile, source_path, target_lang)
            # _resolve_translated_path only falls through to its own
            # last-resort (content_root-relative) fallback when neither
            # per_language_folders nor a usable pattern applied -- detect
            # that case so this method's own site-profile output_dir
            # fallback below still runs instead (preserves prior behavior
            # for profiles with output_layout set but no pattern and
            # per_language_folders=False).
            per_language_folders = (
                getattr(output_layout, "per_language_folders", False)
                if hasattr(output_layout, "per_language_folders")
                else output_layout.get("per_language_folders", False)
            )
            pattern = (
                getattr(output_layout, "pattern", None)
                if hasattr(output_layout, "pattern")
                else output_layout.get("pattern", None)
            )
            if per_language_folders or pattern:
                if pattern and not per_language_folders:
                    logger.info(
                        f"File-based localization: {source_path.name} -> {output_path.name}"
                    )
                return output_path

        # Fallback: use output directory from site profile
        output_dir = Path(getattr(site_profile, "output_dir", None) or "output")

        # Construct output path: output/{lang}/{relative_path}
        output_path = output_dir / target_lang / source_path.name
        logger.info(f"Using site profile output: {output_path}")

        return output_path

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
        """Translate all eligible files in a directory (delegates to DirectoryOrchestrator)."""
        return self._get_dir_orchestrator().translate_directory(
            site_id=site_id,
            directory=directory,
            target_langs=target_langs,
            recursive=recursive,
            parallel=parallel,
            max_workers=max_workers,
            skip_site_lock=skip_site_lock,
            trigger_type=trigger_type,
            max_files=max_files,
            skip_first=skip_first,
            run_deadline=run_deadline,
        )

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
        """Delegate to DirectoryOrchestrator."""
        return self._get_dir_orchestrator()._translate_directory_locked(
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

    def _translate_directory_sequential(
        self,
        site_id: str,
        md_files: list[Path],
        target_langs: list[str],
        result: DirectoryResult,
        run_deadline: float | None = None,
    ) -> DirectoryResult:
        """Delegate to DirectoryOrchestrator."""
        return self._get_dir_orchestrator()._translate_directory_sequential(
            site_id, md_files, target_langs, result, run_deadline=run_deadline
        )

    def _translate_directory_parallel(
        self,
        site_id: str,
        md_files: list[Path],
        target_langs: list[str],
        result: DirectoryResult,
        max_workers: int | None = None,
        run_deadline: float | None = None,
    ) -> DirectoryResult:
        """Delegate to DirectoryOrchestrator."""
        return self._get_dir_orchestrator()._translate_directory_parallel(
            site_id, md_files, target_langs, result, max_workers, run_deadline=run_deadline
        )

    def _translate_file_safe(
        self, site_id: str, file_path: Path, target_langs: list[str]
    ) -> TranslationResult:
        """Thread-safe wrapper for translate_file (delegates to DirectoryOrchestrator)."""
        return self._get_dir_orchestrator()._translate_file_safe(site_id, file_path, target_langs)

    def extract_segments(self, site_id: str, file_path: Path) -> list:
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
        with open(file_path, encoding="utf-8") as f:
            content = f.read()
        doc = self.parser.parse_string(content)
        doc.source_path = file_path  # HT-QUALITY-GATES-001: needed for is_family_platform_index()

        # Extract segments (TRM-05: with terminology protection)
        from .segment_translator import compute_force_protected_fields

        extractor = SegmentExtractor(
            site_profile,
            terminology_manager=self.terminology_manager,
            force_protected_fields=compute_force_protected_fields(doc, site_profile),
        )
        source_lang = site_profile.default_source_lang
        segments = extractor.extract_all(doc, source_lang)

        return segments

    def _validate_translation(
        self,
        file_path: Path,
        doc,
        segments: list,
        outputs: dict[str, Path],
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
                with open(output_path, encoding="utf-8") as f:
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

    def get_tm_stats(self, site_id: str) -> dict:
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
        src_lang: str | None = None,
        tgt_lang: str | None = None,
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
            # G-L4-4: When --output override is active, content-root mismatch is expected
            # (evidence/staging dir writes). Downgrade to warning, not error.
            "output_override_active": bool(self.output_dir_override),
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
                log_level = logger.error if issue.severity.value == "error" else logger.warning
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
                f"Post-write validation passed for {output_path} ({result.warning_count} warnings)"
            )
            # Log warnings if any
            if result.warning_count > 0:
                for issue in result.issues:
                    if issue.severity.value == "warning":
                        logger.warning(f"  - [WARNING] {issue.message}")
            return True

    def _get_verification_agent(self):
        """
        Get or create the verification agent lazily.

        VA-03: Creates agent with language detection check on first use.

        Returns:
            VerificationAgent instance
        """
        if self.verification_agent is None:
            from ..verification import VerificationAgent
            from ..verification.checks.language_check import LanguageDetectionCheck

            # Initialize agent with language detection check
            self.verification_agent = VerificationAgent(
                checks=[
                    LanguageDetectionCheck(min_text_length=20),
                ],
                fail_fast=False,  # Run all checks to get complete picture
            )
            logger.debug("Initialized VerificationAgent with LanguageDetectionCheck")

        return self.verification_agent

    def _record_production_metrics(
        self,
        file_path: Path,
        target_lang: str,
        stats: TranslationStats,
        retry_count: int,
        success: bool,
    ) -> None:
        """
        Record production translation metrics to benchmarking database.

        BM-06: Enables learning from real translation runs.

        Args:
            file_path: Source file path
            target_lang: Target language code
            stats: Translation statistics
            retry_count: Number of retries performed
            success: Whether translation succeeded
        """
        if not self.production_ingestor or not self.production_ingestor.enabled:
            return

        try:
            # Extract metrics from stats
            segments_translated = stats.segments_translated
            segments_from_tm = stats.tm_hits
            translation_model_used = self.model_id_override or "default"

            # Calculate average throughput (if duration available)
            # Note: TranslationStats might not have total duration,
            # so we estimate from segments
            # This is a rough estimate - ideally we'd track duration per file
            estimated_duration_seconds = max(
                1.0, segments_translated * 0.1
            )  # ~0.1s per segment estimate

            # Record via ingestor
            self.production_ingestor.record_translation_run(
                file_path=str(file_path),
                target_lang=target_lang,
                segments_translated=segments_translated,
                segments_from_tm=segments_from_tm,
                segments_translated_new=segments_translated - segments_from_tm,
                translation_model=translation_model_used,
                retry_count=retry_count,
                success=success,
                # Additional context
                validation_passed=(
                    stats.validation_passed if hasattr(stats, "validation_passed") else None
                ),
                validation_errors=(
                    stats.validation_errors if hasattr(stats, "validation_errors") else 0
                ),
            )

            logger.debug(
                f"Recorded production metrics: {file_path} -> {target_lang} "
                f"({segments_translated} segments, {retry_count} retries)"
            )

        except Exception as e:
            # Log but don't propagate - production recording is optional
            logger.warning(f"Failed to record production metrics for {file_path}: {e}")

    def set_override_mode(
        self,
        mode: str,
        filters: dict | None = None,
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

    def get_override_stats(self) -> dict:
        """
        Get TM cache override statistics.

        TMO-03: Returns statistics about cache bypass/refresh operations.

        Returns:
            Dict with override stats including mode, bypass counts, and filter info
        """
        return self.tm.get_override_stats()

    def get_retry_timing_metrics(self) -> dict:
        """
        Get retry timing metrics for performance monitoring (BM-08).

        Returns:
            Dictionary with retry statistics including attempt counts, durations, and reasons
        """
        with self._retry_metrics_lock:
            return {
                "retry_attempts": calc_stats(self._retry_metrics["retry_attempts"]),
                "retry_durations_ms": calc_stats(self._retry_metrics["retry_durations_ms"]),
                "retry_reasons": dict(self._retry_metrics["retry_reasons"]),
                "total_retries": sum(self._retry_metrics["retry_attempts"]),
                "files_with_retries": sum(
                    1 for count in self._retry_metrics["retry_attempts"] if count > 0
                ),
            }

    def _restore_placeholders(self, text: str, segment) -> str:
        """Delegate to SegmentTranslator."""
        return self._segment_translator._restore_placeholders(text, segment)

    def _translate_with_multiline_support(
        self,
        backend,
        segments: list,
        texts: list[str],
        source_lang: str,
        target_lang: str,
        stats: TranslationStats,
    ) -> list[str]:
        """Delegate to SegmentTranslator."""
        return self._segment_translator._translate_with_multiline_support(
            backend=backend,
            segments=segments,
            texts=texts,
            source_lang=source_lang,
            target_lang=target_lang,
            stats=stats,
        )
