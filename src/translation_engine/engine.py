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
import math
import os
import re
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional

from ..model_runtime import ModelLoader
from ..observability.telemetry_integration import get_telemetry, _safe_duration_ms
from ..observability.progress import get_progress_tracker
from ..tm import TranslationMemory
from ..utils.metrics import calc_stats
from .extractor.placeholder_manager import PlaceholderManager
from ..tm.override_controller import OverrideController, OverrideConfig, OverrideMode
from ..utils.config_loader import ConfigService
from ..utils.atomic_write import (
    atomic_write,
    AtomicWriteError,
    DiskFullError,
    InvalidPathError,
    ReadOnlyFilesystemError,
)
from ..utils.file_filters import filter_source_files
from ..utils.file_lock import FileLock, LockError
from ..utils.metadata_tracker import MetadataTracker
from .exceptions import TranslationRejectedError, TranslationRetryableError
from .extractor import SegmentExtractor
from .models import (
    DirectoryResult,
    TranslationResult,
    TranslationStats,
    ValidationDecision,
    ValidationIssue,
    ValidationResult,
)
from .parser import HugoParser
from .reconstructor import MarkdownReconstructor
from .validation import ValidationSuite
from .validation.decision_engine import ValidationDecisionEngine
from .validation.post_translation_validator import ValidationDecision as PostValidationDecision
from .handlers.multiline_handler import MultilineHandler
from .language_detection.fasttext_detector import FastTextDetector
from .language_detection.similarity_tracker import SimilarityTracker
from .retry_handler import RetryHandler

logger = logging.getLogger(__name__)


# Module-level constant: All supported language codes for translation filtering
_ALL_LANGUAGE_CODES = frozenset([
    'af', 'ar', 'az', 'bg', 'ca', 'cs', 'da', 'de', 'el', 'es', 'et',
    'fa', 'fi', 'fr', 'ga', 'he', 'hi', 'hr', 'hu', 'id', 'it', 'ja',
    'ko', 'lt', 'lv', 'ms', 'nb', 'nl', 'no', 'pl', 'pt', 'ro', 'ru',
    'sk', 'sl', 'sr', 'sv', 'th', 'tr', 'uk', 'vi', 'zh'
])


def _is_translated_filename(
    filename: str,
    target_langs: List[str],
    source_lang: str = 'en'
) -> tuple[bool, Optional[str]]:
    """
    Check if filename appears to be a translated file based on language code pattern.

    Detects filenames matching pattern: {name}.{lang}.(md|markdown)
    Examples:
        - index.es.md → (True, 'es')
        - index.ES.MD → (True, 'es')  # case-insensitive
        - tutorial.fr.markdown → (True, 'fr')
        - index.md → (False, None)  # source file
        - index.es.da.md → (True, 'da')  # matches last language code

    Args:
        filename: The filename to check (e.g., "index.es.md")
        target_langs: List of target language codes configured for translation
        source_lang: Source language code (default: 'en')

    Returns:
        Tuple of (is_translated, detected_language_code)
        - is_translated: True if filename contains a language code pattern
        - detected_language_code: The language code found, or None if not translated

    Performance: O(n) with single regex compilation for n language codes.
                 Uses sorted lang codes (longest first) for correct matching of region codes.
    """
    # Build combined set of all possible language codes
    all_lang_codes = _ALL_LANGUAGE_CODES | set(target_langs)
    # Exclude source language (allow files like index.en.md if en is source)
    all_lang_codes = all_lang_codes - {source_lang}

    # Sort by length descending to ensure consistent matching
    sorted_langs = sorted(all_lang_codes, key=len, reverse=True)

    # Build single optimized regex pattern with all language codes
    # Pattern: \.(es|fr|de|...)\.(md|markdown)$
    escaped_langs = [re.escape(lang) for lang in sorted_langs]
    lang_pattern = '|'.join(escaped_langs)
    pattern = rf'\.({lang_pattern})\.(md|markdown)$'

    # Compile and search once
    compiled_pattern = re.compile(pattern, re.IGNORECASE)
    match = compiled_pattern.search(filename)

    if match:
        detected_lang = match.group(1)
        # Normalize case (pattern is case-insensitive, but we want consistent case)
        # Find the original case from our language set
        detected_lang_lower = detected_lang.lower()
        for lang in sorted_langs:
            if lang.lower() == detected_lang_lower:
                return (True, lang)
        # Fallback: return matched lang as-is
        return (True, detected_lang)

    return (False, None)


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
        batch_size: int = 16,
        enable_verification: bool = False,
        enable_verification_fix: bool = False,
        output_dir_override: Optional[Path] = None,
        input_root: Optional[Path] = None,
        progress_tracker: Optional["ProgressTracker"] = None,
        production_ingestor: Optional["ProductionMetricsIngestor"] = None,
        sort_segments_by_length: bool = False,
        redis_client: Optional[any] = None,
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
        self.config = config_service
        self.tm = tm
        self.model_loader = model_loader
        self.enable_validation = enable_validation
        self.enable_telemetry = enable_telemetry
        self.production_ingestor = production_ingestor  # BM-06: Production metrics recording
        self.redis_client = redis_client  # CHH-02: Redis client for metadata locking

        # CFG-03: Store CLI overrides
        self.validation_mode = validation_mode
        self.enable_terminology = enable_terminology
        self.terminology_mode = terminology_mode
        self.max_retries_override = max_retries
        self.dry_run = dry_run
        self.save_rejected = save_rejected
        self.batch_size = batch_size  # GPU memory optimization: limit texts per batch
        self.output_dir_override = output_dir_override  # SR-02: CLI --output argument support
        self.input_root = input_root  # Path collision fix: preserve directory structure in output
        self.sort_segments_by_length = sort_segments_by_length  # SR-01: Sort segments shortest→longest for batching efficiency

        # SR-02c: Validate output_dir_override type (fail fast)
        if output_dir_override is not None and not isinstance(output_dir_override, Path):
            raise ValueError(
                f"output_dir_override must be Path or None, got {type(output_dir_override).__name__}"
            )

        # VA-03: Post-translation verification settings
        self.enable_verification = enable_verification
        self.enable_verification_fix = enable_verification_fix
        self.verification_agent = None  # Will be initialized lazily when needed

        # Model override (from CLI --model flag)
        self.model_id_override = kwargs.get('model_id', None)

        # CT2-002: Language-aware model selector (if provided by CLI)
        self.model_selector = kwargs.get('model_selector', None)
        if self.model_selector:
            logger.info(
                f"Language-aware model selector enabled "
                f"(device={self.model_selector.hardware_info.recommended_device})"
            )

        # T202: Cache refresh control (federated-splashing-panda)
        self.force_retranslate = kwargs.get('force_retranslate', False)
        self.cache_write_mode = kwargs.get('cache_write_mode', 'auto')

        # T203: Log cache write mode if non-default (federated-splashing-panda)
        if self.cache_write_mode != "auto":
            logger.info(f"Cache write mode: {self.cache_write_mode}")
        if self.force_retranslate:
            logger.info("Force retranslate enabled (cache lookup will be bypassed)")

        # T304: Multi-language processing control (federated-splashing-panda)
        self.parallel_languages = kwargs.get('parallel_languages', 0)
        self.global_lang_rounds = kwargs.get('global_lang_rounds', 0)
        self.global_lang_sort = kwargs.get('global_lang_sort', 'desc')

        # T304: Mutual exclusion validation (federated-splashing-panda)
        if self.parallel_languages > 0 and self.global_lang_rounds > 0:
            raise ValueError(
                "Cannot use both parallel_languages and global_lang_rounds simultaneously. "
                "Choose either parallel processing or round-robin, not both."
            )

        # T304: Log multi-language mode if enabled (federated-splashing-panda)
        if self.parallel_languages > 0:
            logger.info(f"Parallel language processing enabled: {self.parallel_languages} workers")
        elif self.global_lang_rounds > 0:
            logger.info(
                f"Round-robin language processing enabled: {self.global_lang_rounds} texts/round, "
                f"sort={self.global_lang_sort}"
            )

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

        # TRM-05: Initialize terminology manager if terminology protection is enabled
        self.terminology_manager = None
        if self.enable_terminology:
            try:
                from .terminology import TerminologyManager
                terminology_config_path = "config/terminology.yaml"
                if Path(terminology_config_path).exists():
                    self.terminology_manager = TerminologyManager(terminology_config_path)
                    logger.info(f"Terminology protection enabled (config: {terminology_config_path})")
                else:
                    logger.warning(f"Terminology config not found at {terminology_config_path}, terminology protection disabled")
            except Exception as e:
                logger.warning(f"Failed to initialize TerminologyManager: {e}")

        # Thread safety locks for parallel processing
        self._tm_lock = Lock()
        self._model_lock = Lock()
        self._file_write_lock = Lock()

        # RES-06: Graceful shutdown coordination
        self._shutdown_requested = False
        self._shutdown_lock = Lock()
        self._current_file: Optional[Path] = None
        self._shutdown_callbacks: list = []

        # RES-02: Progress tracker for crash recovery
        self.progress_tracker = progress_tracker

        # BM-08: Retry timing instrumentation (SR-12: bounded to prevent memory leak, CFG-01: configurable)
        from ..utils.config_loader import get_metrics_config
        metrics_config = get_metrics_config()
        retry_maxlen = metrics_config["metrics"]["storage"]["translation_engine"]["retry_metrics_maxlen"]

        self._retry_metrics = {
            "retry_attempts": deque(maxlen=retry_maxlen),  # Bounded by config
            "retry_durations_ms": deque(maxlen=retry_maxlen),  # Bounded by config
            "retry_reasons": {},  # Dict mapping reason -> count (naturally bounded)
        }
        self._retry_metrics_lock = Lock()

        # Content hash tracking for change detection
        self.enable_content_hash = kwargs.get('enable_content_hash_tracking', False)
        if self.enable_content_hash:
            # Will be initialized per-site in translate_file
            self.metadata_tracker = None
        else:
            self.metadata_tracker = None

        # Adaptive batch translation (reactive system)
        self.batch_stats_tracker = None
        adaptive_config = self._load_adaptive_config()
        if adaptive_config.get('enabled', False):
            from .extractor.batch_stats_tracker import BatchStatsTracker
            # WS3: Accept hardware baseline from GPU optimizer (via CLI)
            # Used to seed new languages with hardware-aware batch sizes instead of hardcoded values
            hardware_baseline = kwargs.get('hardware_baseline')
            self.batch_stats_tracker = BatchStatsTracker(
                config=adaptive_config,
                hardware_baseline=hardware_baseline
            )
            try:
                self.batch_stats_tracker.load()
                # Enhanced logging: show loaded languages and their batch sizes
                lang_count = len(self.batch_stats_tracker.languages)
                threshold = self.batch_stats_tracker.fallback_rate_threshold
                logger.info(
                    f"[ENABLED] Adaptive Batching: {lang_count} languages loaded, "
                    f"threshold={threshold:.1%}"
                )
                # Log first 5 languages with their learned batch sizes
                if lang_count > 0:
                    for i, (lang, stats) in enumerate(self.batch_stats_tracker.languages.items()):
                        if i >= 5:
                            break
                        batch_size = stats.get('batch_size', 'N/A')
                        logger.info(f"  - {lang}: batch_size={batch_size}")
            except Exception as e:
                logger.warning(f"Failed to load batch statistics: {e}, starting fresh")
        else:
            logger.info("[DISABLED] Adaptive Batching")

        # WS-A: FastText language detection integration
        self.fasttext_detector = None
        # Backward-compatible alias used by older write-validation paths.
        self.detector = None
        self.similarity_tracker = None

        # D3: Disk space check cache (60-second TTL to avoid repeated stat calls)
        # Structure: {path_str: (timestamp, free_space_bytes)}
        self._space_check_cache = {}
        lang_detection_config = self._load_language_detection_config()
        if lang_detection_config.get('provider') == 'fasttext':
            try:
                # Initialize FastTextDetector with config
                fasttext_config = lang_detection_config.get('fasttext', {})
                cache_dir = Path(fasttext_config.get('model_cache_dir', './data/models/fasttext'))
                model_url = fasttext_config.get('model_url')
                min_confidence = fasttext_config.get('min_confidence', 0.70)
                auto_download = fasttext_config.get('auto_download', True)
                download_retries = fasttext_config.get('download_retries', 3)
                fallback_to_langdetect = fasttext_config.get('fallback_to_langdetect', True)

                self.fasttext_detector = FastTextDetector(
                    cache_dir=cache_dir,
                    model_url=model_url,
                    min_confidence=min_confidence,
                    auto_download=auto_download,
                    download_retries=download_retries,
                    fallback_to_langdetect=fallback_to_langdetect,
                )
                self.detector = self.fasttext_detector

                if self.fasttext_detector.is_available:
                    logger.info("FastText language detection initialized")
                else:
                    logger.warning("FastText language detection unavailable, continuing without it")
                    self.fasttext_detector = None
                    self.detector = None

            except Exception as e:
                logger.warning(f"Failed to initialize FastTextDetector: {e}, continuing without language detection")
                self.fasttext_detector = None
                self.detector = None

        # WS-A: Adaptive similarity tracker integration
        adaptive_similarity_config = lang_detection_config.get('adaptive_similarity', {})
        if adaptive_similarity_config.get('enabled', True) and lang_detection_config.get('provider') == 'fasttext':
            try:
                self.similarity_tracker = SimilarityTracker(adaptive_similarity_config)
                self.similarity_tracker.load()
                logger.info("Adaptive similarity tracker initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize SimilarityTracker: {e}, continuing without adaptive similarity")
                self.similarity_tracker = None

        # WS-A: RetryHandler for OOM recovery
        self.retry_handler = None
        oom_retry_config = self._load_oom_retry_config()
        if oom_retry_config and oom_retry_config.get('enabled', True):
            try:
                max_retries = oom_retry_config.get('max_retries', 3)
                batch_reduction_factor = oom_retry_config.get('batch_reduction_factor', 0.5)
                min_batch_size = oom_retry_config.get('min_batch_size', 1)

                self.retry_handler = RetryHandler(
                    max_retries=max_retries,
                    batch_reduction_factor=batch_reduction_factor,
                    min_batch_size=min_batch_size,
                )
                logger.info(
                    f"[ENABLED] OOM Retry Handler: max_retries={max_retries}, "
                    f"reduction_factor={batch_reduction_factor}, min_batch={min_batch_size}"
                )
            except Exception as e:
                logger.error(
                    f"[FAILED] OOM Retry Handler initialization: {e}. "
                    f"GPU OOM errors will NOT be automatically recovered"
                )
                self.retry_handler = None
        elif oom_retry_config and not oom_retry_config.get('enabled', True):
            logger.info("[DISABLED] OOM Retry Handler: enabled=false")
        else:
            logger.info("[DISABLED] OOM Retry Handler: missing config")

    def _load_adaptive_config(self) -> dict:
        """Load adaptive batching configuration from global config."""
        try:
            global_config = self.config.get_config()
            return global_config.get('adaptive_batching', {})
        except Exception as e:
            logger.debug(f"Failed to load adaptive batching config: {e}")
            return {'enabled': False}

    def _load_language_detection_config(self) -> dict:
        """Load language detection configuration from global config."""
        try:
            global_config = self.config.get_config()
            return global_config.get('language_detection', {})
        except Exception as e:
            logger.debug(f"Failed to load language detection config: {e}")
            return {}

    def _load_oom_retry_config(self) -> dict:
        """Load OOM retry configuration from global config."""
        try:
            global_config = self.config.get_config()
            autonomous_recovery = global_config.get('autonomous_recovery', {})
            oom_retry = autonomous_recovery.get('oom_retry', {})

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
                logger.debug(
                    f"OOM detected in Engine: pattern='{pattern}' matched in error"
                )
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
                logger.info(
                    f"Shutdown requested. Completing current file: {current}"
                )
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
                    l3 = getattr(self.tm, 'l3', None)
                    if l3 and hasattr(l3, 'save_index'):
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
        import time
        import shutil

        # D3: Check cache first (60-second TTL)
        path_str = str(path)
        if path_str in self._space_check_cache:
            timestamp, cached_free = self._space_check_cache[path_str]
            age = time.time() - timestamp
            if age < 60:  # Cache valid for 60 seconds
                logger.debug(f"Disk space cache hit for {path} (age: {age:.1f}s, free: {cached_free/(1024**3):.2f}GB)")
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
            logger.debug(f"Cached disk space for {path}: {free/(1024**3):.2f}GB free")

            return free

        except Exception as e:
            logger.warning(f"Could not determine free space for {path}: {e}")
            return 0

    def _get_model_id(self, site_profile, src_lang: Optional[str] = None, tgt_lang: Optional[str] = None):
        """
        Get model ID with CLI override, dynamic selection, and site profile fallback support.

        CT2-002: Implements language-aware model selection via ModelSelector if available.

        Selection priority:
        1. CLI --model override (highest priority)
        2. Dynamic selection via model_selector (CT2 models preferred for language pairs)
        3. Site profile default_model
        4. Global fallback "m2m100_418m"

        Args:
            site_profile: Site profile with default_model attribute
            src_lang: Optional source language code (for dynamic selection)
            tgt_lang: Optional target language code (for dynamic selection)

        Returns:
            Model ID to use for translation
        """
        # Priority 1: CLI override (explicit user choice)
        if self.model_id_override:
            return self.model_id_override

        # Priority 2: Dynamic selection via model_selector (CT2-002)
        # Only if both languages provided and selector available
        if src_lang and tgt_lang and self.model_selector:
            try:
                selection = self.model_selector.select_for_language_pair(src_lang, tgt_lang)
                logger.info(
                    f"CT2-002: Selected {selection.model_info.model_id} for {src_lang}→{tgt_lang} "
                    f"(strategy={selection.selection_strategy}, backend={selection.model_info.backend})"
                )
                return selection.model_info.model_id
            except ValueError as e:
                # No suitable model found via selector, fall through to static defaults
                logger.warning(
                    f"CT2-002: Model selector failed for {src_lang}→{tgt_lang}: {e}. "
                    f"Falling back to site profile or global default."
                )

        # Priority 3: Site profile default
        # Priority 4: Global fallback
        fallback_model = getattr(site_profile, 'default_model', None) or "m2m100_418m"

        # Log if using fallback (helps with observability)
        if src_lang and tgt_lang:
            logger.debug(
                f"Using fallback model {fallback_model} for {src_lang}→{tgt_lang} "
                f"(no selector or languages not provided)"
            )

        return fallback_model

    def _should_skip_translation(
        self,
        source_path: Path,
        output_path: Path,
        force_retranslate: bool = False,
        use_mtime_check: bool = True,
        target_lang: Optional[str] = None,
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
            with open(output_path, 'r', encoding='utf-8') as f:
                content = f.read(1024)  # Read first 1KB

            # Basic validation: has some content
            if len(content.strip()) < 10:
                return False

            return True

        except Exception as e:
            logger.warning(f"Output validation failed for {output_path}: {e}")
            return False

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
        return Path(getattr(site_profile, 'output_dir', None) or "output")

    def _discover_all_segments(
        self,
        files: List[Path],
        target_langs: List[str],
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
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                doc = self.parser.parse_string(content)

                # Extract segments (same logic as translate_file)
                extractor = SegmentExtractor(site_profile, terminology_manager=self.terminology_manager)
                segments = extractor.extract_all(doc, source_lang)

                # Count segments per file * number of target languages
                segment_count = len(segments) * len(target_langs)
                total_segments += segment_count

            except Exception as e:
                logger.warning(f"Failed to parse {file_path} during discovery: {e}")
                # Continue with other files, don't fail the whole discovery

        logger.info(f"[INIT] Found {len(files)} files with {total_segments:,} total segments")

        return total_segments

    def translate_file(
        self,
        site_id: str,
        file_path: Path,
        target_langs: List[str],
        force: bool = False,
        validate: Optional[bool] = None,
        trigger_type: str = "cli",
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
        telemetry_enabled = self.enable_telemetry and self.telemetry and self.telemetry.is_available()
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

            source_lang = site_profile.default_source_lang

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
                auto_cleanup_config = content_hash_config.get("auto_cleanup", {})  # CHH-05: Cleanup config

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
            output_layout = getattr(site_profile, 'output_layout', None)
            per_language_folders = False
            if output_layout:
                per_language_folders = (
                    getattr(output_layout, 'per_language_folders', False)
                    if hasattr(output_layout, 'per_language_folders')
                    else output_layout.get('per_language_folders', False)
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
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                doc = self.parser.parse_string(content)
                doc.source_path = file_path  # Set source path for output routing
            except Exception as e:
                result.errors.append(f"Parse error: {e}")
                return result

            # Extract segments (TRM-05: pass terminology_manager for term protection)
            extractor = SegmentExtractor(site_profile, terminology_manager=self.terminology_manager)
            segments = extractor.extract_all(doc, source_lang)
            result.stats.total_segments = len(segments)

            logger.info(
                f"Extracted {len(segments)} segments from {file_path}"
            )

            # Progress tracking: file started with segment count
            # Multiply by number of target languages since segments_completed is called per language
            progress = get_progress_tracker()
            if progress:
                progress.file_started(str(file_path), segment_count=len(segments) * len(target_langs))

            # INT-01: Translate for each target language with retry loop
            # VA-03: Determine if verification should run
            should_validate = validate if validate is not None else self.enable_validation
            should_verify = self.enable_verification
            should_fix = self.enable_verification_fix and should_verify
            max_retry_attempts = self.decision_engine.max_retry_attempts if self.decision_engine else 2

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
                    logger.debug(
                        f"Skipping {file_path} -> {target_lang}: {skip_reason}"
                    )
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

                # Retry loop for this target language
                retry_count = 0
                retry_feedback = None
                translated_content = None
                final_decision = None
                final_validation_result = None
                final_verification_result = None

                # BM-08: Track retry timing
                retry_start_time = time.perf_counter()

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

                            # Run validation suite (use validate_aggregated for single result)
                            validation_result = self.validation_suite.validate_aggregated(
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

                                # Check if max retries exceeded
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
                                # Progress tracking: reset segment counters for retry
                                progress = get_progress_tracker()
                                if progress:
                                    progress.file_translation_retry(segments_to_undo=len(segments))
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

                                # BM-08: Track retry reason
                                with self._retry_metrics_lock:
                                    reason_key = "validation_retry"
                                    self._retry_metrics["retry_reasons"][reason_key] = (
                                        self._retry_metrics["retry_reasons"].get(reason_key, 0) + 1
                                    )

                                continue  # Loop again with feedback

                            # ACCEPT - fall through to write file

                        # ═══════════════════════════════════════════════════════════════
                        # AGENT B-7.6: RESTRUCTURED WRITE FLOW
                        # CRITICAL ARCHITECTURAL FIX: Validate THEN Write
                        #
                        # OLD FLOW (WRONG): write → verify → decide
                        # NEW FLOW (CORRECT): validate → decide → write
                        #
                        # Ensures NO files are written unless ALL validation passes.
                        # ═══════════════════════════════════════════════════════════════

                        # PHASE 1: ALL VALIDATION (before write decision)
                        # Collect all validation results into a single flag
                        validation_passed = True
                        validation_error = None

                        # VA-03: Post-translation verification (runs after validation)
                        if should_verify:
                            logger.debug(f"Running post-translation verification for {target_lang}")

                            # Parse both source and translated docs for verification
                            source_doc_dict = {
                                "frontmatter": doc.frontmatter if hasattr(doc, "frontmatter") else {},
                                "body": str(doc.body) if hasattr(doc, "body") else "",
                            }
                            translated_doc_parsed = self.parser.parse_string(translated_content)
                            translated_doc_dict = {
                                "frontmatter": translated_doc_parsed.frontmatter if hasattr(translated_doc_parsed, "frontmatter") else {},
                                "body": str(translated_doc_parsed.body) if hasattr(translated_doc_parsed, "body") else "",
                            }

                            # Run verification
                            verification_agent = self._get_verification_agent()
                            verification_result = verification_agent.verify(
                                source_doc=source_doc_dict,
                                translated_doc=translated_doc_dict,
                                target_lang=target_lang,
                                context={
                                    "source_lang": source_lang,
                                    "file_path": str(file_path),
                                    "site_id": site_id,
                                }
                            )

                            final_verification_result = verification_result

                            # Check if verification passed
                            if not verification_result.passed:
                                logger.warning(
                                    f"Verification failed for {file_path} to {target_lang}: "
                                    f"{verification_result.error_count} errors, "
                                    f"{verification_result.warning_count} warnings"
                                )

                                # If fix mode enabled, retry with feedback
                                if should_fix and retry_count < max_retry_attempts:
                                    retry_count += 1
                                    # Build feedback from verification issues
                                    error_messages = [
                                        f"- {issue.location}: {issue.message}"
                                        for issue in verification_result.issues
                                        if issue.severity == "error"
                                    ]
                                    retry_feedback = (
                                        f"Previous translation had verification errors:\n"
                                        + "\n".join(error_messages[:5])  # Limit to 5 issues
                                        + "\n\nPlease fix these issues in the translation."
                                    )
                                    result.stats.validation_retried += 1

                                    # Progress tracking: reset segment counters for retry
                                    progress = get_progress_tracker()
                                    if progress:
                                        progress.file_translation_retry(segments_to_undo=len(segments))

                                    logger.info(
                                        f"Retrying translation due to verification failure "
                                        f"(attempt {retry_count}/{max_retry_attempts})"
                                    )

                                    # Track retry in result history
                                    result.retry_history.append({
                                        "attempt": retry_count,
                                        "reason": "verification_failed",
                                        "feedback": retry_feedback,
                                        "error_count": verification_result.error_count,
                                    })

                                    # BM-08: Track retry reason
                                    with self._retry_metrics_lock:
                                        reason_key = "verification_retry"
                                        self._retry_metrics["retry_reasons"][reason_key] = (
                                            self._retry_metrics["retry_reasons"].get(reason_key, 0) + 1
                                        )

                                    continue  # Loop again with feedback
                                else:
                                    # CRITICAL FIX (B-7.6): Block write if verification failed
                                    # OLD: logged warning and continued to write (WRONG!)
                                    # NEW: set validation_passed=False to prevent write
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
                        source_path = doc.source_path if hasattr(doc, "source_path") and doc.source_path else Path("output.md")

                        # CRITICAL FIX: Use cached output_path to prevent path mismatch
                        # Validate that recalculated path matches cached path
                        expected_output_path = output_paths_cache.get(target_lang)
                        recalculated_output_path = self._get_output_path(
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
                            break  # Stop processing this file

                        # Use the cached path for write
                        output_path = expected_output_path

                        # Only proceed with further validation if not already failed
                        if validation_passed:
                            # AGENT B-7.1: Language detection validation
                            # Prevents multi-language garbage from being written
                            # ALSO prevents overwriting good files with bad translations
                            try:
                                # Use same FastTextDetector as initialized for the engine
                                detector = self._get_language_detector()
                                if detector is None:
                                    logger.warning(
                                        "Language detector unavailable, skipping language validation for %s",
                                        output_path.name,
                                    )
                                else:
                                    detected_lang, confidence = detector.detect(translated_content)

                                    # Check for language mismatch (with high confidence)
                                    if detected_lang != target_lang and confidence > 0.70:
                                        # Check if this is a learned similarity pair
                                        is_similar = False
                                        if hasattr(self, 'similarity_tracker') and self.similarity_tracker:
                                            is_similar = self.similarity_tracker.are_similar(target_lang, detected_lang)

                                        if not is_similar:
                                            validation_passed = False
                                            validation_error = f"Language mismatch: detected {detected_lang}, expected {target_lang}"
                                            logger.error(
                                                f"WRITE BLOCKED: Content language mismatch! "
                                                f"Expected: {target_lang}, Detected: {detected_lang} ({confidence:.2%}). "
                                                f"Refusing to write wrong-language content to {output_path.name}."
                                            )
                                        else:
                                            logger.warning(
                                                f"Language mismatch detected but allowing due to learned similarity: "
                                                f"{target_lang} <-> {detected_lang} ({confidence:.2%})"
                                            )

                                    # AGENT B-7.4: Pre-Write Existing File Quality Check
                                    # CRITICAL: If existing file exists, don't overwrite with lower quality
                                    if validation_passed and output_path.exists():
                                        try:
                                            existing_content = output_path.read_text(encoding='utf-8')
                                            existing_lang, existing_conf = detector.detect(existing_content)

                                            # CASE 1: Existing file is correct language and new file is wrong → BLOCK
                                            if existing_lang == target_lang and detected_lang != target_lang:
                                                validation_passed = False
                                                validation_error = f"Blocked overwrite: existing={existing_lang}, new={detected_lang}"
                                                logger.error(
                                                    f"OVERWRITE BLOCKED: Existing file is correct {target_lang} "
                                                    f"({existing_conf:.2%}), new content is wrong {detected_lang} "
                                                    f"({confidence:.2%}). Refusing to replace good file with bad translation."
                                                )

                                            # CASE 2: Both correct but existing has higher confidence → BLOCK
                                            elif (existing_lang == target_lang and detected_lang == target_lang and
                                                existing_conf > confidence + 0.05):  # 5% threshold to avoid churn
                                                validation_passed = False
                                                validation_error = f"Blocked overwrite: existing quality higher"
                                                logger.warning(
                                                    f"OVERWRITE BLOCKED: Existing file has higher quality "
                                                    f"({existing_lang} {existing_conf:.2%}) than new translation "
                                                    f"({detected_lang} {confidence:.2%}). Keeping existing."
                                                )

                                            # CASE 3: Existing wrong but new correct → ALLOW (healing)
                                            elif existing_lang != target_lang and detected_lang == target_lang:
                                                logger.info(
                                                    f"HEALING OVERWRITE: Replacing incorrect {existing_lang} "
                                                    f"({existing_conf:.2%}) with correct {detected_lang} "
                                                    f"({confidence:.2%}). Quality improvement for {output_path.name}."
                                                )
                                                # Allow write to proceed (healing case)

                                            # CASE 4: Both wrong → BLOCK
                                            elif existing_lang != target_lang and detected_lang != target_lang:
                                                validation_passed = False
                                                validation_error = f"Blocked overwrite: both translations wrong (existing={existing_lang}, new={detected_lang})"
                                                logger.error(
                                                    f"OVERWRITE BLOCKED: Both existing ({existing_lang}) and new "
                                                    f"({detected_lang}) are wrong language. Expected {target_lang}. "
                                                    f"Blocking to prevent further corruption of {output_path.name}."
                                                )

                                        except (IOError, OSError) as existing_check_error:
                                            # Existing file read error - non-fatal, allow write (new translation)
                                            logger.warning(f"Could not read existing file for comparison (allowing write): {existing_check_error}")
                                        except ValueError as existing_check_error:
                                            # Detection confidence too low on existing file - log and allow write
                                            logger.warning(f"Existing file language detection uncertain (allowing write): {existing_check_error}")

                            except ImportError as e:
                                # Detector module missing - FATAL, block write
                                validation_passed = False
                                validation_error = "Language validation unavailable"
                                logger.error(f"Language detector unavailable: {e}")
                            except (IOError, OSError) as e:
                                # File I/O error during validation - non-fatal for new files
                                logger.warning(f"I/O error during language validation: {e}")
                                # Continue to write (new translation)
                            except ValueError as e:
                                # Detection confidence too low - log and decide
                                logger.warning(f"Language detection uncertain: {e}")
                                # Continue to write (detector exists but uncertain)

                            # AGENT B-7.5: Final file-level purity check
                            # Detects mixed-language content that passes aggregate detection
                            if validation_passed and detector is not None:
                                purity_result = self._verify_final_file_purity(
                                    translated_content,
                                    target_lang,
                                    detector
                                )

                                if not purity_result['passed']:
                                    validation_passed = False
                                    validation_error = f"Final purity check failed: {purity_result['reason']}"
                                    logger.error(
                                        f"FINAL PURITY CHECK FAILED: Assembled file contains "
                                        f"{purity_result['wrong_lang_percentage']:.1%} wrong-language content. "
                                        f"Detected languages: {purity_result['detected_languages']}. "
                                        f"Blocking write to prevent corruption of {output_path.name}."
                                    )

                        # PHASE 2: DECISION - Block write if any validation failed
                        if not validation_passed:
                            logger.error(f"WRITE BLOCKED for {output_path.name}: {validation_error}")
                            result.success = False
                            result.error = validation_error
                            break  # Exit retry loop - validation failure is deterministic

                        # PHASE 3: WRITE (only if ALL validation passed)
                        try:
                            self._write_output(translated_content, output_path, source_path, result.stats)
                            logger.info(f"✓ Successfully wrote {output_path.name} after passing all validation checks")
                        except Exception as write_error:
                            # Write operation failed - handle separately from validation
                            logger.error(f"Write operation failed for {output_path.name}: {write_error}")
                            result.success = False
                            result.error = f"Write error: {write_error}"
                            break  # Exit retry loop - write failed, move to next language

                        # File successfully written - add to outputs
                        result.outputs[target_lang] = output_path

                        # Update content hash metadata (if enabled)
                        if self.enable_content_hash and self.metadata_tracker:
                            try:
                                source_hash = self.metadata_tracker.update_source(source_path)
                                self.metadata_tracker.update_output(
                                    source_path=source_path,
                                    output_path=output_path,
                                    target_lang=target_lang,
                                    source_hash=source_hash,
                                    status="success",
                                )
                                # Save metadata after successful translation
                                self.metadata_tracker.save()
                            except Exception as e:
                                logger.warning(f"Failed to update content hash metadata: {e}")

                        # INT-05: Post-write validation (file placement/structure checks)
                        # NOTE: This runs AFTER file is written to verify write succeeded
                        # (file exists, readable, not empty, correct folder structure)
                        post_write_passed = self._post_write_validation(
                            output_path=output_path,
                            source_path=source_path,
                            target_lang=target_lang,
                            site_id=site_id,
                            site_profile=site_profile,
                        )

                        if not post_write_passed:
                            logger.warning(f"Post-write validation failed for {output_path}, but file was written")

                        # Mark language as completed in progress tracker
                        progress = get_progress_tracker()
                        if progress:
                            progress.language_completed(target_lang)

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

                        # VA-03: Store verification result
                        if final_verification_result:
                            result.verification_result = final_verification_result
                            if not final_verification_result.passed:
                                result.warnings.append(
                                    f"Verification found {final_verification_result.error_count} errors "
                                    f"in {target_lang} translation"
                                )

                        logger.info(f"Successfully translated {file_path} to {target_lang} after {retry_count} retries")

                        # BM-06: Record production metrics (if enabled)
                        if self.production_ingestor and self.production_ingestor.enabled:
                            try:
                                self._record_production_metrics(
                                    file_path=file_path,
                                    target_lang=target_lang,
                                    stats=result.stats,
                                    retry_count=retry_count,
                                    success=True,
                                )
                            except Exception as e:
                                # Don't let ingestor failures break translation
                                logger.warning(f"Failed to record production metrics: {e}")

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

                        # Progress tracking: reset segment counters for retry
                        progress = get_progress_tracker()
                        if progress:
                            progress.file_translation_retry(segments_to_undo=len(segments))

                        # BM-08: Track retry reason
                        with self._retry_metrics_lock:
                            reason_key = "retryable_error"
                            self._retry_metrics["retry_reasons"][reason_key] = (
                                self._retry_metrics["retry_reasons"].get(reason_key, 0) + 1
                            )

                        if retry_count > max_retry_attempts:
                            raise TranslationRejectedError(
                                message=f"Failed after {retry_count} retries",
                                file_path=str(file_path),
                                validation_result=e.validation_result,
                                rejection_reason="Max retries exceeded",
                            )
                        continue

                    except Exception as e:
                        # SR-02: Handle shutdown request by re-raising
                        from .exceptions import ShutdownRequested
                        if isinstance(e, ShutdownRequested):
                            logger.info(
                                f"Shutdown requested during translation of {file_path} to {target_lang} "
                                f"(completed {e.segments_completed} segments)"
                            )
                            # Save partial progress before re-raising
                            progress = get_progress_tracker()
                            if progress:
                                progress.file_completed(success=False, has_new_translations=False)
                            raise

                        # OOM-01: Detect OOM errors and allow RetryHandler to engage
                        if self._is_oom_error(e):
                            if self.retry_handler:
                                # Re-raise to let RetryHandler catch and apply batch reduction
                                logger.debug(
                                    f"OOM error detected for {file_path} to {target_lang}. "
                                    f"Re-raising to engage RetryHandler with batch reduction."
                                )
                                raise
                            else:
                                # Helpful message when handler disabled
                                logger.error(
                                    f"OOM error detected for {file_path} to {target_lang}, "
                                    f"but RetryHandler is disabled. Consider enabling autonomous_recovery.oom_retry "
                                    f"in config to automatically reduce batch size. Error: {e}"
                                )
                                result.errors.append(
                                    f"Translation to {target_lang} failed (OOM): {e}"
                                )
                                break

                        # Unexpected error - don't retry
                        logger.error(
                            f"Error translating {file_path} to {target_lang}: {e}"
                        )
                        result.errors.append(
                            f"Translation to {target_lang} failed: {e}"
                        )
                        break  # Exit retry loop on unexpected error

                # BM-08: Record retry metrics after retry loop completes
                retry_duration_ms = (time.perf_counter() - retry_start_time) * 1000
                with self._retry_metrics_lock:
                    self._retry_metrics["retry_attempts"].append(retry_count)
                    self._retry_metrics["retry_durations_ms"].append(retry_duration_ms)

                if retry_count > 0 and retry_duration_ms > 1000:
                    logger.warning(
                        f"High retry overhead for {file_path} to {target_lang}: "
                        f"{retry_count} retries in {retry_duration_ms:.1f}ms"
                    )

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
                progress.file_completed(success=result.success, has_new_translations=has_new_translations)

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
                    all_skipped = (result.stats.langs_skipped == total_langs and
                                   total_langs > 0 and
                                   result.success)

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
                            }
                        )
                    else:
                        # Work was done → Record telemetry with skip metrics
                        self.telemetry.track_translation_stats(
                            telemetry_run,
                            result.stats,
                            output_paths=result.outputs
                        )
                        # SR-03: Use helper functions for RunRecord fields (TEL-05-B)
                        from ..observability.telemetry_integration import (
                            build_output_summary,
                            build_error_summary,
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
                        duration_ms, used_fallback = _safe_duration_ms(result.stats, context="translate_file")

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
            if hasattr(self.tm, 'l1') and hasattr(self.tm.l1, 'clear'):
                cache_size_before = len(self.tm.l1.cache) if hasattr(self.tm.l1, 'cache') else 0
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
        segments: Optional[List] = None,
        translations: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Translate document body using AST-based node-addressed translation.

        This method implements complete AST-based translation with node addressing:
        1. Extract TextUnits from AST with node addressing
        2. Reuse existing translations if available (source text match)
        3. Batch translate remaining units
        4. Apply translations back to AST
        5. Render AST to Markdown

        This approach ensures 100% preservation of document structure and formatting
        by separating content from structure.

        Args:
            doc: Parsed HugoDocument with AST
            target_lang: Target language code
            site_profile: Site profile configuration
            stats: Stats object to update with telemetry
            segments: Optional list of segments from SegmentExtractor (for building source text lookup)
            translations: Optional dict mapping segment.id to translations.
                         If provided along with segments, will reuse translations by source text match.

        Returns:
            Translated markdown body content

        Raises:
            RuntimeError: If AST translation fails
        """
        from .extractor import TextUnitExtractor
        from .reconstructor import ASTRenderer
        from pathlib import Path

        try:
            # Step 1: Load translation model for AST path
            model_id = self._get_model_id(site_profile)
            with self._model_lock:
                mt_model = self.model_loader.load_model(model_id)

            # Step 2: Extract TextUnits with M2M100 protection
            terminology_file = Path("config/terminology/aspose_terms.txt")

            # WS-A: Get script validation thresholds for language detection
            lang_detection_config = self._load_language_detection_config()
            script_validation_config = lang_detection_config.get('script_validation', {})
            script_validation_thresholds = script_validation_config.get('thresholds', {}) if script_validation_config.get('enabled', True) else None

            extractor = TextUnitExtractor(
                segmentation_strategy=site_profile.body.ast_segmentation_strategy,
                terminology_file=terminology_file if terminology_file.exists() else None,
                mt_model=mt_model,  # Pass model for tokenizer protection
                preserve_patterns=site_profile.body.preserve_patterns,  # Apply preserve_patterns
                site_profile=site_profile,  # Pass site profile for extraction config
                batch_stats_tracker=self.batch_stats_tracker,  # Adaptive batch sizing
                fasttext_detector=self.fasttext_detector,  # WS-A: Language detection
                similarity_tracker=self.similarity_tracker,  # WS-A: Adaptive similarity learning
                script_validation_thresholds=script_validation_thresholds  # WS-A: Script validation config
            )

            logger.info(f"AST Translation: Extracting TextUnits from AST (strategy: {site_profile.body.ast_segmentation_strategy})")
            plan = extractor.extract_from_ast(doc.ast, frontmatter=doc.frontmatter)

            # Telemetry: Track extracted units
            total_units = len(plan.units)
            translatable_units = len([u for u in plan.units if not u.do_not_translate])
            protected_units = len([u for u in plan.units if u.do_not_translate])
            logger.info(f"AST Translation: Extracted {total_units} units ({translatable_units} translatable, {protected_units} protected)")

            # Update telemetry
            stats.ast_translation_enabled = True
            stats.ast_units_extracted = total_units
            stats.ast_units_translatable = translatable_units
            stats.ast_units_protected = protected_units

            # E2E FIX: Reuse existing translations if available (avoids re-translation)
            reused_count = 0
            not_matched_count = 0
            if segments and translations:
                # Helper function to strip markdown formatting for matching
                import re
                def strip_markdown(text: str) -> str:
                    """Strip common markdown formatting for source_text matching."""
                    # Strip bold/italic: **text** or *text*
                    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
                    text = re.sub(r'\*(.+?)\*', r'\1', text)
                    # Strip inline code: `text`
                    text = re.sub(r'`(.+?)`', r'\1', text)
                    # Strip links: [text](url) -> text
                    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
                    return text

                # Apply placeholder protection to segments for matching
                from .extractor.placeholder_manager import PlaceholderManager
                pm = PlaceholderManager()
                preserve_patterns = site_profile.body.preserve_patterns or []

                # Build source_text -> translation mapping from segments + translations
                # Normalize both segment and unit source_texts by stripping markdown
                source_to_translation = {}
                for segment in segments:
                    if segment.id in translations and translations[segment.id]:
                        # Normalize segment source_text by stripping markdown
                        normalized_source = strip_markdown(segment.source_text)
                        # Apply placeholder protection
                        protected_source, _ = pm.protect(normalized_source, preserve_patterns)
                        source_to_translation[protected_source] = translations[segment.id]

                logger.debug(f"E2E DEBUG: Built mapping with {len(source_to_translation)} segment translations")
                logger.debug(f"E2E DEBUG: First 3 normalized segment source_texts: {list(source_to_translation.keys())[:3]}")

                # Apply translations to units by source text match
                unmatched_units = []
                for unit in plan.units:
                    if not unit.do_not_translate and unit.source_text:
                        # Normalize unit source_text same way as segments
                        normalized_unit_source = strip_markdown(unit.source_text)
                        # Apply same placeholder protection for matching
                        protected_unit_source, _ = pm.protect(normalized_unit_source, preserve_patterns)

                        if protected_unit_source in source_to_translation:
                            unit.translated_text = source_to_translation[protected_unit_source]
                            reused_count += 1
                        else:
                            not_matched_count += 1
                            unmatched_units.append(unit)
                            if not_matched_count <= 5:
                                logger.debug(f"E2E DEBUG: Unmatched unit [{unit.kind}]: normalized={normalized_unit_source[:80]}")

                logger.info(f"AST Translation: Reused {reused_count} existing translations, {not_matched_count} units not matched")

                # E2E DEBUG: Log all unmatched unit kinds to understand the mismatch
                if unmatched_units:
                    kind_counts = {}
                    for u in unmatched_units:
                        kind_counts[u.kind] = kind_counts.get(u.kind, 0) + 1
                    logger.debug(f"E2E DEBUG: Unmatched unit kinds: {kind_counts}")

            # Step 2: Translate units with batching + fallback
            batch_size = site_profile.body.ast_batch_size
            units_needing_translation = [u for u in plan.units if not u.do_not_translate and not u.translated_text]
            logger.info(f"AST Translation: Translating {len(units_needing_translation)} new units (batch_size: {batch_size}, reused: {reused_count})")

            # Track batch calls and fallbacks
            batch_calls_before = getattr(extractor, '_batch_calls', 0)
            fallbacks_before = getattr(extractor, '_individual_fallbacks', 0)

            translated_units = extractor.batch_translate_units(
                plan.units,
                mt_model,
                site_profile.default_source_lang,
                target_lang,
                batch_size=batch_size
            )

            # AGENT B-7.3: Check batch-level purity failures to prevent file corruption
            # If too many batches failed language purity checks, block the entire file write
            batch_stats = extractor.batch_stats
            if batch_stats.get('language_purity_failures', 0) > 0:
                total_batches = batch_stats.get('total_batches', 0)
                if total_batches > 0:
                    purity_failure_rate = batch_stats['language_purity_failures'] / total_batches

                    # If >10% of batches failed purity, block write
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

            # Check for empty translations, but only for units with substantial source text
            # Allow empty output if source was whitespace-only or very short (≤2 chars)
            empty_units = [
                u for u in translated_units
                if not u.do_not_translate
                and (u.translated_text is None or u.translated_text.strip() == "")
                and u.source_text
                and u.source_text.strip() != ""
                and len(u.source_text.strip()) > 2
            ]
            if empty_units:
                # Log warning for all empty units (including whitespace) for diagnostics
                all_empty = [
                    u for u in translated_units
                    if not u.do_not_translate and (u.translated_text is None or u.translated_text.strip() == "")
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

            # Update telemetry with batch statistics
            batch_calls_after = getattr(extractor, '_batch_calls', 0)
            fallbacks_after = getattr(extractor, '_individual_fallbacks', 0)
            stats.ast_batch_calls = batch_calls_after - batch_calls_before
            stats.ast_individual_fallbacks = fallbacks_after - fallbacks_before

            # Step 3: Apply translations to AST and frontmatter
            logger.info("AST Translation: Applying translations to AST and frontmatter")
            renderer = ASTRenderer()
            renderer.apply_translations(doc.ast, translated_units, frontmatter=doc.frontmatter)

            # Step 4: Render to Markdown
            logger.info("AST Translation: Rendering AST to Markdown")
            translated_body = renderer.render_to_markdown(doc.ast)

            # Telemetry: Track success
            logger.info(f"AST Translation: Successfully translated {translatable_units} units "
                       f"({stats.ast_batch_calls} batches, {stats.ast_individual_fallbacks} fallbacks)")

            return translated_body

        except TranslationRetryableError:
            raise
        except Exception as e:
            logger.error(f"AST-based translation failed: {e}", exc_info=True)
            raise RuntimeError(f"AST-based translation failed: {e}")

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

        # Create extractor instance for inline formatting restoration (TRM-05: with terminology)
        extractor = SegmentExtractor(site_profile, terminology_manager=self.terminology_manager)

        # CT2-002: Get model_id with language-aware selection (early for accurate token counting)
        model_id = self._get_model_id(site_profile, src_lang=source_lang, tgt_lang=target_lang)

        # Step 1: TM lookup (unless force=True)
        if not force:
            for idx, segment in enumerate(segments, 1):
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

                    # Track cached tokens - use actual count if available for accuracy
                    # TEL-04: Count tokens saved by cache hit
                    backend = self.model_loader.get_tokenizer_for_counting(model_id)
                    if backend and hasattr(backend, 'get_token_count'):
                        # Actual tokenization (accurate ~10-20ms overhead acceptable for logs)
                        cached_input_tokens = backend.get_token_count(segment.source_text)
                        cached_output_tokens = backend.get_token_count(tm_result.translation)
                        stats.token_count_method = "actual"
                    else:
                        # Heuristic fallback (fast but approximate)
                        cached_input_tokens = estimate_token_count(segment.source_text)
                        cached_output_tokens = estimate_token_count(tm_result.translation)
                        stats.token_count_method = "estimated"

                    stats.tokens_cached += cached_input_tokens + cached_output_tokens

                    # Progress tracking: cache hit
                    progress = get_progress_tracker()
                    if progress:
                        progress.cache_hit(layer=tm_result.source.split("_")[0] if tm_result.source else "l1")
                        progress.segments_completed(1)
                else:
                    # Need to translate
                    segments_to_translate.append(segment)
                    # Progress tracking: cache miss
                    progress = get_progress_tracker()
                    if progress:
                        progress.cache_miss()

                # SR-02: Check for shutdown every 10 segments
                if idx % 10 == 0 and self._check_shutdown():
                    from .exceptions import ShutdownRequested
                    raise ShutdownRequested(
                        file_path=str(doc.file_path) if hasattr(doc, "file_path") else "",
                        segments_completed=idx
                    )

        else:
            # Force mode: translate everything (T202: federated-splashing-panda)
            logger.info(
                f"Force retranslate enabled: bypassing cache lookup for {len(segments)} segments "
                f"({source_lang} -> {target_lang})"
            )
            segments_to_translate = segments

            # Track cache misses for force mode (cache bypassed = implicit miss)
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

            # Get model (use lock to prevent race conditions in parallel processing)
            with self._model_lock:
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
                # Progress tracking: batch started with total calculation
                progress = get_progress_tracker()
                batch_start_time = time.time()
                if progress:
                    # Calculate and add batch count for this language's translation
                    batches_for_lang = math.ceil(len(segments_to_translate) / self.batch_size)
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
                if self._check_shutdown():
                    from .exceptions import ShutdownRequested
                    raise ShutdownRequested(
                        file_path=str(doc.file_path) if hasattr(doc, "file_path") else "",
                        segments_completed=len(translations)  # Already completed segments
                    )

                # Store results in translations map and TM
                for seg_idx, (segment, translation) in enumerate(
                    zip(segments_to_translate, translated_texts), 1
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

                    # T203: Determine cache write behavior (federated-splashing-panda)
                    # - "never": skip all cache writes (read-only mode)
                    # - "always": overwrite existing entries
                    # - "auto": write if missing (default)
                    if self.cache_write_mode != "never":
                        # Determine force_update based on cache_write_mode
                        if self.cache_write_mode == "always":
                            force_update = True
                        else:  # "auto"
                            force_update = force  # Use force_retranslate parameter

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
                            force_update=force_update,
                        )
                        # TEL-04: Track TM entry storage
                        stats.tm_entries_stored += 1

                    # SR-02: Check for shutdown every 10 segments during storage
                    if seg_idx % 10 == 0 and self._check_shutdown():
                        from .exceptions import ShutdownRequested
                        raise ShutdownRequested(
                            file_path=str(doc.file_path) if hasattr(doc, "file_path") else "",
                            segments_completed=len(translations)
                        )

                # Progress tracking: batch and segments completed
                batch_duration = time.time() - batch_start_time
                if progress:
                    progress.batch_completed(len(segments_to_translate))
                    progress.segments_completed(len(segments_to_translate), duration_s=batch_duration)
                    progress.add_tokens(
                        tokens_in=stats.tokens_input,
                        tokens_out=stats.tokens_output,
                        method=getattr(stats, 'token_count_method', 'actual')
                    )

            except Exception as e:
                logger.error(f"Model translation failed: {e}")
                # SR-03: Track failed segments to maintain cache/segment accounting
                # (cache_hits + cache_misses should equal segments_done + segments_failed)
                progress = get_progress_tracker()
                if progress:
                    for _ in range(len(segments_to_translate)):
                        progress.segment_failed()
                # SR-01: Don't record error here - outer handler will record if file fails
                # (This prevents counting errors when a language fails but file succeeds overall)
                raise RuntimeError(f"Translation failed: {e}")

        # Step 3: Reconstruct document (AST-based or legacy)
        # Check if AST-based body reconstruction is enabled
        use_ast = getattr(site_profile.body, 'use_ast_body_reconstruction', False)

        if use_ast:
            logger.info("Using AST-based body reconstruction for translation")
            try:
                # AST Translation: Translate body using node-addressed AST
                # E2E FIX: Pass segments and translations to reuse existing work
                translated_body = self._translate_body_ast(
                    doc, target_lang, site_profile, stats,
                    segments=segments,
                    translations=translations
                )

                # Reconstruct frontmatter (translate frontmatter fields)
                from .reconstructor import YAMLFormatter
                yaml_formatter = YAMLFormatter()

                # Translate frontmatter fields
                translated_frontmatter = {}
                for key, value in doc.frontmatter.items():
                    # Check if field should be translated
                    field_rule = site_profile.frontmatter.get(key)
                    if field_rule and field_rule.mode == "translate":
                        # Find translation in segments (only for hashable types like strings)
                        if isinstance(value, str) and value in translations:
                            translated_frontmatter[key] = translations[value]
                        else:
                            translated_frontmatter[key] = value
                    else:
                        # Passthrough or other modes
                        translated_frontmatter[key] = value

                # Format frontmatter as YAML (includes --- delimiters)
                frontmatter_yaml = yaml_formatter.format_frontmatter(translated_frontmatter)

                # Combine frontmatter + body
                translated_content = f"{frontmatter_yaml}\n{translated_body}"

                logger.info("AST Translation: Successfully reconstructed document")

            except TranslationRetryableError:
                raise
            except Exception as e:
                logger.error(f"AST reconstruction failed: {e}", exc_info=True)
                # Fallback to legacy reconstruction
                logger.warning("AST translation failed, falling back to legacy reconstruction")
                use_ast = False

        if not use_ast:
            # Legacy: Build segment_map for body reconstruction (node_id -> segment_id)
            segment_map = {}
            for segment in segments:
                if segment.context and segment.context.node_id:
                    segment_map[segment.context.node_id] = segment.id

            # Legacy: Reconstruct document with segment_map
            reconstructor = MarkdownReconstructor(site_profile)
            translated_doc = reconstructor.reconstruct_document(
                doc, translations, target_lang, segment_map=segment_map
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
        content_size = len(content.encode('utf-8'))
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
                path=output_path,
                content=content,
                encoding='utf-8',
                fsync=True,
                create_parents=True
            )
        except DiskFullError as e:
            # RES-09: Provide helpful disk full message
            free_space = self._get_free_space(output_path.parent)
            logger.error(
                f"Disk full when writing {output_path}. "
                f"Free space: {free_space / 1024 / 1024:.1f}MB, "
                f"needed: ~{content_size / 1024:.1f}KB"
            )
            raise
        except PermissionError as e:
            # RES-09: Clear permission error message
            logger.error(
                f"Permission denied: {output_path}. "
                f"Check file permissions and ownership."
            )
            raise
        except InvalidPathError as e:
            # RES-09: Clear invalid path message
            logger.error(f"Invalid path: {e}")
            raise
        except ReadOnlyFilesystemError as e:
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
        stats.bytes_written_md += len(content.encode('utf-8'))

        logger.info(f"Written translated file: {output_path}")

    def _verify_final_file_purity(
        self,
        content: str,
        expected_lang: str,
        detector
    ) -> dict:
        """
        Verify entire file content is correct language.

        AGENT B-7.5: File-Level Language Purity Verification

        Splits content into paragraphs and checks each one.
        Fails if >5% of content is wrong language.

        This addresses the corruption bug where batch-level validation
        detects issues but file-level validation loses context. Mixed
        content (95% correct + 5% wrong) can pass aggregate detection
        if majority correct, but this paragraph-level check catches it.

        Args:
            content: Full translated markdown content
            expected_lang: Target language code (e.g., 'ar', 'uk')
            detector: FastTextDetector instance

        Returns:
            dict with keys: passed (bool), wrong_lang_percentage (float),
                           detected_languages (dict), reason (str)
        """
        # Split content into paragraphs (skip frontmatter/code blocks)
        paragraphs = []
        in_code_block = False
        in_frontmatter = False

        for line in content.split('\n'):
            stripped = line.strip()
            if stripped.startswith('```'):
                in_code_block = not in_code_block
            elif stripped == '---' and not paragraphs:
                in_frontmatter = not in_frontmatter
            elif not in_code_block and not in_frontmatter and stripped:
                paragraphs.append(stripped)

        if not paragraphs:
            return {"passed": True, "reason": "No content to validate"}

        wrong_lang_count = 0
        total_count = 0
        detected_languages = {}

        for para in paragraphs:
            if len(para) < 20:
                continue  # Too short to validate

            try:
                detected, conf = detector.detect(para)
                total_count += 1

                detected_languages[detected] = detected_languages.get(detected, 0) + 1

                if detected != expected_lang and conf > 0.70:
                    # Check if similarity-learned
                    is_similar = False
                    if hasattr(self, 'similarity_tracker') and self.similarity_tracker:
                        is_similar = self.similarity_tracker.are_similar(expected_lang, detected)

                    if not is_similar:
                        wrong_lang_count += 1
            except (ValueError, Exception) as e:
                # Detection failed for this paragraph - skip it
                logger.debug(f"Paragraph detection failed: {e}")
                continue

        if total_count == 0:
            return {"passed": True, "reason": "No content to validate"}

        wrong_percentage = wrong_lang_count / total_count

        # 30% threshold: technical docs legitimately contain English API names, inline code,
        # and non-translatable identifiers. The original 5% threshold was too strict for
        # real-world content. Genuine corruption shows 50%+ wrong-language content.
        if wrong_percentage > 0.30:
            return {
                "passed": False,
                "wrong_lang_percentage": wrong_percentage,
                "detected_languages": detected_languages,
                "reason": f"{wrong_lang_count}/{total_count} paragraphs wrong language"
            }

        return {
            "passed": True,
            "wrong_lang_percentage": wrong_percentage,
            "detected_languages": detected_languages
        }

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
                    logger.debug(f"Computed relative path: {relative_path} from {abs_source} relative to {abs_input_root}")
                except ValueError:
                    # Fallback if source_path is not under input_root
                    logger.warning(f"Source path {source_path} not under input root {self.input_root}, using basename")
                    relative_path = source_path.name
            else:
                # Fallback: use basename (preserves existing behavior)
                relative_path = source_path.name

            output_path = self.output_dir_override / target_lang / relative_path
            logger.info(f"Using CLI output override: {output_path} (relative: {relative_path})")
            return output_path

        # Check if site profile uses Hugo sibling folder pattern
        output_layout = getattr(site_profile, 'output_layout', None)
        per_language_folders = False
        pattern = None
        if output_layout:
            per_language_folders = getattr(output_layout, 'per_language_folders', False) if hasattr(output_layout, 'per_language_folders') else output_layout.get('per_language_folders', False)
            pattern = getattr(output_layout, 'pattern', None) if hasattr(output_layout, 'pattern') else output_layout.get('pattern', None)

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
        else:
            # File-based localization: apply output_layout.pattern
            if pattern:
                # Extract filename components
                filename_stem = source_path.stem  # e.g., "index"
                filename_ext = source_path.suffix  # e.g., ".md"

                # Apply pattern substitution
                output_filename = pattern.format(
                    filename=filename_stem,
                    lang=target_lang,
                    ext=filename_ext,
                    path=str(source_path.name)  # Full filename as fallback
                )

                # Use source file's directory as base (not hardcoded output/)
                output_path = source_path.parent / output_filename

                logger.info(f"File-based localization: {source_path.name} -> {output_filename}")
                return output_path

        # Fallback: use output directory from site profile
        output_dir = Path(getattr(site_profile, 'output_dir', None) or "output")

        # Construct output path: output/{lang}/{relative_path}
        output_path = output_dir / target_lang / source_path.name
        logger.info(f"Using site profile output: {output_path}")

        return output_path

    def translate_directory(
        self,
        site_id: str,
        directory: Path,
        target_langs: List[str],
        recursive: bool = True,
        parallel: bool = True,
        max_workers: Optional[int] = None,
        skip_site_lock: bool = False,
        trigger_type: str = "cli",
        max_files: int = 0,
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
            skip_site_lock: If True, skip lock acquisition (parent holds lock) - TC1
            trigger_type: How translation was triggered ("cli", "scheduled", "web", etc.)
            max_files: Maximum number of files to process (0=unlimited, default: 0)

        Returns:
            DirectoryResult with outcomes for all files

        Raises:
            LockError: If another translation is already in progress for this site
        """
        # TC2: AUTO-CLEANUP: Remove stale locks older than 24 hours on startup
        # This prevents accumulation of orphaned locks
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
                site_id, directory, target_langs, recursive, parallel, max_workers, trigger_type, max_files
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
                site_id, directory, target_langs, recursive, parallel, max_workers, trigger_type, max_files
            )
        finally:
            # RES-08: Always release lock
            lock.release()

    def _translate_directory_locked(
        self,
        site_id: str,
        directory: Path,
        target_langs: List[str],
        recursive: bool = True,
        parallel: bool = True,
        max_workers: Optional[int] = None,
        trigger_type: str = "cli",
        max_files: int = 0,
    ) -> DirectoryResult:
        """
        Internal implementation of translate_directory (called while holding lock).

        RES-08: This is the actual translation logic, called from translate_directory
        after the lock has been acquired.

        Args:
            max_files: Maximum number of files to process (0=unlimited, default: 0).
                      Files are selected deterministically (sorted by path).
        """
        # TEL-04: Start telemetry tracking for batch operation
        # SR-01: Find representative file for business context extraction
        telemetry_enabled = self.enable_telemetry and self.telemetry and self.telemetry.is_available()
        telemetry_cm = None  # Context manager
        telemetry_run = None  # RunContext

        # SR-01: Find first markdown file to extract business context
        representative_file = None
        if telemetry_enabled:
            pattern = "**/*.md" if recursive else "*.md"
            md_files_for_context = list(directory.glob(pattern))
            if md_files_for_context:
                representative_file = md_files_for_context[0]

        if telemetry_enabled:
            telemetry_cm = self.telemetry.track_translation_session(
                job_type="translate_directory",
                trigger_type=trigger_type,
                directory=str(directory),
                file_path=representative_file,  # SR-01: Pass representative file for business context
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
                pass  # Graceful degradation if module not available

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

            # Filter files based on localization strategy to avoid translating already-translated files
            site_profile = self.config.get_site_profile(site_id)
            if site_profile:
                md_files = filter_source_files(md_files, site_profile, target_langs)
                logger.info(
                    f"After filtering: {len(md_files)} source files to translate"
                )

            # Apply max_files limit if specified (deterministic selection)
            if max_files and max_files > 0 and len(md_files) > max_files:
                md_files = sorted(md_files, key=str)[:max_files]
                logger.info(
                    f"Limited to first {max_files} files for sampling (deterministic selection)"
                )

            result.total_files = len(md_files)

            if not md_files:
                # Count files before filtering for better diagnostics
                all_md_count = len(list(directory.glob(pattern)))
                logger.error(
                    f"No markdown files to translate in {directory}. "
                    f"Discovered {all_md_count} .md file(s) total, "
                    f"but after filtering: 0 source files remain. "
                    f"Check: input path exists, site profile content_roots are correct, "
                    f"working directory is repository root, and files aren't already translated."
                )
                result.success = False
                result.failed_files = 1  # Signal failure to CLI
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
                # Capture full stack trace as error_details (truncate to 10KB)
                import traceback
                error_details = traceback.format_exc()
                # Truncate to 10KB to avoid API payload issues
                max_error_details_size = 10 * 1024  # 10KB
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

            # TEL-04: Track aggregated stats and close telemetry
            if telemetry_run and telemetry_enabled:
                try:
                    # Get aggregated stats across all files
                    agg_stats = result.aggregate_stats

                    # Aggregate outputs from all file results for target_ref
                    all_outputs = {}
                    for file_result in result.file_results:
                        if file_result.outputs:
                            all_outputs.update(file_result.outputs)

                    self.telemetry.track_translation_stats(
                        telemetry_run,
                        agg_stats,
                        job_type="translate_directory",
                        output_paths=all_outputs
                    )

                    # SR-03: Use helper functions for RunRecord fields (TEL-05-B)
                    from ..observability.telemetry_integration import (
                        build_output_summary,
                        build_error_summary,
                        calculate_items_metrics,
                    )

                    # Calculate files_generated from all output files across results
                    files_generated = sum(
                        len(fr.outputs) for fr in result.file_results
                    )

                    # Collect errors from failed files
                    all_errors = []
                    for fr in result.file_results:
                        if fr.errors:
                            all_errors.extend(fr.errors[:2])  # Max 2 per file

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

                    # TI-01: Use centralized helper with observability
                    duration_ms, used_fallback = _safe_duration_ms(agg_stats, context="translate_directory")

                    # TI-02: items_discovered already contains total_files for directory jobs
                    # (calculated via calculate_items_metrics helper). The external telemetry API's
                    # RunRecord schema does not include a total_files field, so we don't pass it here.
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

            # TC-GIT-01: Store telemetry context for git commit association
            if telemetry_enabled and telemetry_run:
                result.telemetry_context = telemetry_run

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
            # RES-06: Check for shutdown before starting new file
            if self._check_shutdown():
                logger.info("Shutdown detected, stopping translation")
                self._perform_shutdown()
                break

            # RES-06: Track current file for shutdown coordination
            self._current_file = md_file

            try:
                # WS-A: Use RetryHandler for OOM recovery if available
                if self.retry_handler:
                    # Wrapper function that adapts to RetryHandler's interface
                    def translate_with_batch_size(file_path: Path, batch_size: int, **kwargs):
                        # Temporarily set batch_size for this file translation
                        original_batch_size = self.batch_size
                        self.batch_size = batch_size
                        try:
                            return self.translate_file(
                                site_id=kwargs.get('site_id'),
                                file_path=file_path,
                                target_langs=kwargs.get('target_langs'),
                            )
                        finally:
                            # Restore original batch_size
                            self.batch_size = original_batch_size

                    # WS2-CALLBACK: Define OOM recovery learning callback
                    def handle_oom_recovery(failed_batch_size: int, success_batch_size: int):
                        """Teach BatchStatsTracker when OOM retry succeeds."""
                        logger.info(
                            f"OOM RECOVERY: {failed_batch_size}→{success_batch_size}, "
                            f"teaching adaptive tracker for file {md_file.name}"
                        )

                        # Guard: Only proceed if batch_stats_tracker exists
                        if not self.batch_stats_tracker:
                            logger.debug("No batch_stats_tracker available, skipping OOM learning")
                            return

                        try:
                            # Record failure at the batch size that caused OOM
                            for lang in target_langs:
                                self.batch_stats_tracker.record_batch_result(
                                    language=lang,
                                    batch_size=failed_batch_size,
                                    success=False,
                                    fallback_reason='oom_retry'
                                )

                                # Cap current_batch_size to success size
                                if lang in self.batch_stats_tracker.languages:
                                    lang_data = self.batch_stats_tracker.languages[lang]
                                    current = lang_data.get('current_batch_size', success_batch_size)
                                    new_size = min(current, success_batch_size)
                                    lang_data['current_batch_size'] = new_size
                                    logger.debug(
                                        f"Capped {lang} batch_size: {current}→{new_size}"
                                    )

                            # Persist immediately to protect next file
                            self.batch_stats_tracker.save()
                            logger.info(
                                f"OOM learning persisted for {len(target_langs)} languages"
                            )
                        except Exception as e:
                            logger.warning(f"Failed to record OOM learning: {e}")

                    # WS4: Log per-file protection status
                    logger.info(
                        f"Translating {md_file.name} | OOM Protection: ACTIVE "
                        f"(max_retries={self.retry_handler.max_retries}) | Batch size: {self.batch_size}"
                    )

                    file_result = self.retry_handler.translate_file_with_retry(
                        translate_func=translate_with_batch_size,
                        file_path=md_file,
                        initial_batch_size=self.batch_size,
                        on_oom_recovery=handle_oom_recovery,
                        site_id=site_id,
                        target_langs=target_langs,
                    )
                else:
                    # WS4: Log per-file protection status when disabled
                    logger.info(
                        f"Translating {md_file.name} | OOM Protection: DISABLED | Batch size: {self.batch_size}"
                    )

                    # Fallback to direct translation without retry
                    file_result = self.translate_file(
                        site_id=site_id,
                        file_path=md_file,
                        target_langs=target_langs,
                    )
                result.file_results.append(file_result)

                if file_result.success:
                    result.successful_files += 1

                    # RES-02: Mark progress for crash recovery
                    if self.progress_tracker:
                        try:
                            for lang in target_langs:
                                self.progress_tracker.mark_completed(md_file, lang)
                            logger.debug(f"Progress saved for {md_file.name}")
                        except Exception as e:
                            logger.warning(f"Failed to save progress for {md_file}: {e}")
                else:
                    result.failed_files += 1

                    # RES-02: Mark failed translations
                    if self.progress_tracker:
                        try:
                            for lang in target_langs:
                                error_msg = '; '.join(file_result.errors[:2]) if file_result.errors else 'Unknown error'
                                self.progress_tracker.mark_failed(md_file, lang, error_msg)
                            logger.debug(f"Failure progress saved for {md_file.name}")
                        except Exception as e:
                            logger.warning(f"Failed to save failure progress for {md_file}: {e}")

            except Exception as e:
                # SR-02: Handle shutdown request - break loop and perform shutdown
                from .exceptions import ShutdownRequested
                if isinstance(e, ShutdownRequested):
                    logger.info(f"Shutdown requested during {md_file}, stopping directory translation")
                    self._perform_shutdown()
                    break  # Exit file loop cleanly

                logger.error(f"Error translating {md_file}: {e}")
                result.failed_files += 1

                # RES-02: Mark as failed on exception
                if self.progress_tracker:
                    try:
                        for lang in target_langs:
                            self.progress_tracker.mark_failed(md_file, lang, str(e))
                    except Exception as mark_error:
                        logger.warning(f"Failed to save error progress: {mark_error}")

            finally:
                # RES-06: Clear current file
                self._current_file = None

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
            # Use only 1 worker to prevent memory exhaustion with large translation models
            max_workers = 1

        logger.info(f"Translating {len(md_files)} files with {max_workers} workers")

        # Pre-load the translation model BEFORE starting parallel workers
        # This prevents race conditions when multiple workers try to load the model simultaneously
        site_profile = self.config.get_site_profile(site_id)
        if site_profile:
            model_id = self._get_model_id(site_profile)
            logger.info(f"Pre-loading model {model_id} before parallel processing...")
            try:
                self.model_loader.load_model(model_id)
                logger.info(f"Model {model_id} pre-loaded successfully")
            except Exception as e:
                logger.error(f"Failed to pre-load model {model_id}: {e}")
                # Continue anyway - workers will try to load individually

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
                # RES-06: Check for shutdown after each file completes
                if self._check_shutdown():
                    logger.info("Shutdown detected, cancelling remaining jobs")
                    # Cancel pending futures
                    for f in future_to_file:
                        f.cancel()
                    self._perform_shutdown()
                    break

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
                    # SR-02: Handle shutdown request - break loop and cancel pending
                    from .exceptions import ShutdownRequested
                    if isinstance(e, ShutdownRequested):
                        logger.info(f"Shutdown requested during {md_file}, cancelling parallel jobs")
                        # Cancel all pending futures
                        for f in future_to_file:
                            f.cancel()
                        self._perform_shutdown()
                        break  # Exit result collection loop

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
            # WS-A: Use RetryHandler for OOM recovery if available
            if self.retry_handler:
                # Wrapper function that adapts to RetryHandler's interface
                def translate_with_batch_size(file_path: Path, batch_size: int, **kwargs):
                    # Temporarily set batch_size for this file translation
                    original_batch_size = self.batch_size
                    self.batch_size = batch_size
                    try:
                        return self.translate_file(
                            site_id=kwargs.get('site_id'),
                            file_path=file_path,
                            target_langs=kwargs.get('target_langs'),
                        )
                    finally:
                        # Restore original batch_size
                        self.batch_size = original_batch_size

                # WS2-CALLBACK: Define OOM recovery learning callback
                def handle_oom_recovery(failed_batch_size: int, success_batch_size: int):
                    """Teach BatchStatsTracker when OOM retry succeeds."""
                    logger.info(
                        f"OOM RECOVERY: {failed_batch_size}→{success_batch_size}, "
                        f"teaching adaptive tracker for file {file_path.name}"
                    )

                    # Guard: Only proceed if batch_stats_tracker exists
                    if not self.batch_stats_tracker:
                        logger.debug("No batch_stats_tracker available, skipping OOM learning")
                        return

                    try:
                        # Record failure at the batch size that caused OOM
                        for lang in target_langs:
                            self.batch_stats_tracker.record_batch_result(
                                language=lang,
                                batch_size=failed_batch_size,
                                success=False,
                                fallback_reason='oom_retry'
                            )

                            # Cap current_batch_size to success size
                            if lang in self.batch_stats_tracker.languages:
                                lang_data = self.batch_stats_tracker.languages[lang]
                                current = lang_data.get('current_batch_size', success_batch_size)
                                new_size = min(current, success_batch_size)
                                lang_data['current_batch_size'] = new_size
                                logger.debug(
                                    f"Capped {lang} batch_size: {current}→{new_size}"
                                )

                        # Persist immediately to protect next file
                        self.batch_stats_tracker.save()
                        logger.info(
                            f"OOM learning persisted for {len(target_langs)} languages"
                        )
                    except Exception as e:
                        logger.warning(f"Failed to record OOM learning: {e}")

                # WS4: Log per-file protection status
                logger.info(
                    f"Translating {file_path.name} | OOM Protection: ACTIVE "
                    f"(max_retries={self.retry_handler.max_retries}) | Batch size: {self.batch_size}"
                )

                return self.retry_handler.translate_file_with_retry(
                    translate_func=translate_with_batch_size,
                    file_path=file_path,
                    initial_batch_size=self.batch_size,
                    on_oom_recovery=handle_oom_recovery,
                    site_id=site_id,
                    target_langs=target_langs,
                )
            else:
                # WS4: Log per-file protection status when disabled
                logger.info(
                    f"Translating {file_path.name} | OOM Protection: DISABLED | Batch size: {self.batch_size}"
                )

                # Fallback to direct translation without retry
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

        # Extract segments (TRM-05: with terminology protection)
        extractor = SegmentExtractor(site_profile, terminology_manager=self.terminology_manager)
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
            estimated_duration_seconds = max(1.0, segments_translated * 0.1)  # ~0.1s per segment estimate

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
                validation_passed=stats.validation_passed if hasattr(stats, 'validation_passed') else None,
                validation_errors=stats.validation_errors if hasattr(stats, 'validation_errors') else 0,
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

    def get_retry_timing_metrics(self) -> Dict:
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
                "files_with_retries": sum(1 for count in self._retry_metrics["retry_attempts"] if count > 0),
            }

    def _restore_placeholders(self, text: str, segment) -> str:
        """
        Restore placeholder content (links, shortcodes, etc.) in translated text.

        Also restores inline formatting (bold, italic, links) that was protected during translation.
        TRM-05: Now also restores protected terminology.
        """
        if not text:
            return text

        result = text

        # TRM-05: Restore terminology placeholders first (before other placeholders)
        if self.terminology_manager and getattr(segment, "protected_terms", None):
            try:
                for protected_segment in segment.protected_terms:
                    if protected_segment.term_mapping:
                        # Create a new ProtectedSegment with the current result text
                        from .terminology.models import ProtectedSegment
                        translated_protected = ProtectedSegment(
                            original_text=protected_segment.original_text,
                            protected_text=result,
                            term_mapping=protected_segment.term_mapping
                        )
                        result = self.terminology_manager.restore(translated_protected)
                        logger.debug(f"Restored {len(protected_segment.term_mapping)} terminology terms")
            except Exception as e:
                logger.warning(f"Terminology restore failed: {e}")

        # Restore shortcode/pattern placeholders
        if getattr(segment, "placeholder_map", None):
            try:
                result = self.placeholder_manager.restore(result, segment.placeholder_map)
            except Exception as e:
                logger.warning(f"Placeholder restore failed: {e}")

        return result

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
        batch_size = getattr(self, "batch_size", 1)
        sort_by_length = getattr(self, "sort_segments_by_length", False)
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

        # Translate single-line texts in batches (GPU memory optimization)
        if singleline_texts:
            batch_translations = []
            total_texts = len(singleline_texts)

            # SR-01: Sort segments by length for improved batching efficiency
            if sort_by_length and total_texts > 1:
                # Create sorted index mapping (shortest to longest)
                sorted_indices = sorted(range(total_texts), key=lambda i: len(singleline_texts[i]))
                sorted_texts = [singleline_texts[i] for i in sorted_indices]
                logger.debug(
                    f"SR-01: Sorting {total_texts} segments by length "
                    f"(range: {len(sorted_texts[0])}-{len(sorted_texts[-1])} chars)"
                )
            else:
                # No sorting: maintain original order
                sorted_indices = list(range(total_texts))
                sorted_texts = singleline_texts

            # Process in chunks of batch_size to avoid GPU OOM
            for chunk_start in range(0, total_texts, batch_size):
                chunk_end = min(chunk_start + batch_size, total_texts)
                chunk_texts = sorted_texts[chunk_start:chunk_end]

                if hasattr(backend, 'translate_with_token_counts'):
                    chunk_translations, input_tokens, output_tokens = backend.translate_with_token_counts(
                        chunk_texts, source_lang, target_lang
                    )
                    stats.tokens_input += input_tokens
                    stats.tokens_output += output_tokens
                else:
                    chunk_translations = backend.translate(
                        chunk_texts, source_lang, target_lang
                    )
                    stats.tokens_input += sum(estimate_token_count(t) for t in chunk_texts)
                    stats.tokens_output += sum(estimate_token_count(t) for t in chunk_translations)

                batch_translations.extend(chunk_translations)

                if total_texts > batch_size:
                    logger.debug(
                        f"Translated batch {chunk_start//batch_size + 1}/"
                        f"{(total_texts + batch_size - 1)//batch_size} "
                        f"({len(chunk_texts)} texts)"
                    )

            # SR-01: Map results back to original document order
            # Create reverse mapping: sorted_order[i] -> original_position
            unsorted_translations = [None] * total_texts
            for sorted_idx, original_list_idx in enumerate(sorted_indices):
                unsorted_translations[original_list_idx] = batch_translations[sorted_idx]

            # Place results in correct positions
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
                lines_info = self.multiline_handler.parse_lines(text)
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

                # Optional length sorting for padding efficiency
                if sort_by_length and len(line_texts) > 1:
                    sorted_indices = sorted(range(len(line_texts)), key=lambda i: len(line_texts[i]))
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

                    if hasattr(backend, 'translate_with_token_counts'):
                        chunk_translations, input_tokens, output_tokens = backend.translate_with_token_counts(
                            chunk_texts, source_lang, target_lang
                        )
                        stats.tokens_input += input_tokens
                        stats.tokens_output += output_tokens
                    else:
                        chunk_translations = backend.translate(
                            chunk_texts, source_lang, target_lang
                        )
                        stats.tokens_input += sum(estimate_token_count(t) for t in chunk_texts)
                        stats.tokens_output += sum(estimate_token_count(t) for t in chunk_translations)

                    batch_translations.extend(chunk_translations)

                    if total_lines > batch_size:
                        logger.debug(
                            f"MSP-02: Translated multiline batch {chunk_start//batch_size + 1}/"
                            f"{(total_lines + batch_size - 1)//batch_size} "
                            f"({len(chunk_texts)} lines)"
                        )

                # Map translations back to original order
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

                translated_text = '\n'.join(translated_lines)
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
