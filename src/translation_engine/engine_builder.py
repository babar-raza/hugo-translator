"""
TC-DECOMP-05: Engine construction logic.

Extracted from TranslationEngine.__init__ to reduce the 473-line constructor
to a concise attribute-assignment + builder call.

The builder receives all constructor parameters and wires up all subsystems
on the engine instance via build_into().
"""

from __future__ import annotations

import logging
from collections import deque
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .engine import TranslationEngine

logger = logging.getLogger(__name__)


class EngineBuilder:
    """Constructs and wires all TranslationEngine subsystems."""

    def __init__(
        self,
        config_service,
        tm,
        model_loader,
        enable_validation: bool = True,
        enable_telemetry: bool = True,
        validation_suite=None,
        decision_engine=None,
        validation_mode: str | None = None,
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
        progress_tracker=None,
        production_ingestor=None,
        sort_segments_by_length: bool = False,
        redis_client=None,
        **kwargs,
    ):
        # Store all params for build_into
        self._p = dict(
            config_service=config_service,
            tm=tm,
            model_loader=model_loader,
            enable_validation=enable_validation,
            enable_telemetry=enable_telemetry,
            validation_suite=validation_suite,
            decision_engine=decision_engine,
            validation_mode=validation_mode,
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
        )

    def build_into(self, engine: TranslationEngine) -> None:
        """Wire all subsystems onto the engine instance."""
        p = self._p
        self._init_core_state(engine, p)
        self._init_review_cache(engine, p)
        self._init_multi_language(engine, p)
        self._init_tm_override(engine, p)
        self._init_components(engine, p)
        self._init_telemetry(engine, p)
        self._init_terminology(engine, p)
        self._init_locks(engine, p)
        self._init_retry_metrics(engine, p)
        self._init_content_hash(engine, p)
        self._init_adaptive_batching(engine, p)
        self._init_detection(engine, p)
        self._init_retry_handler(engine, p)
        self._init_tm_wiring(engine, p)
        self._init_extracted_components(engine, p)

    # ------------------------------------------------------------------
    # Phase 1: Core state
    # ------------------------------------------------------------------
    @staticmethod
    def _init_core_state(engine, p):
        engine.config = p["config_service"]
        engine.tm = p["tm"]
        engine.model_loader = p["model_loader"]
        engine.enable_validation = p["enable_validation"]
        engine.enable_telemetry = p["enable_telemetry"]
        engine.production_ingestor = p["production_ingestor"]
        engine.redis_client = p["redis_client"]

        engine.validation_mode = p["validation_mode"]
        engine.enable_terminology = p["enable_terminology"]
        engine.terminology_mode = p["terminology_mode"]
        engine.max_retries_override = p["max_retries"]
        engine.dry_run = p["dry_run"]
        engine.save_rejected = p["save_rejected"]
        engine.batch_size = p["batch_size"]
        engine.output_dir_override = p["output_dir_override"]
        engine.input_root = p["input_root"]
        engine.sort_segments_by_length = p["sort_segments_by_length"]

        if p["output_dir_override"] is not None and not isinstance(p["output_dir_override"], Path):
            raise ValueError(
                f"output_dir_override must be Path or None, got {type(p['output_dir_override']).__name__}"
            )

        engine.enable_verification = p["enable_verification"]
        engine.enable_verification_fix = p["enable_verification_fix"]
        engine.verification_agent = None

        engine.model_id_override = p.get("model_id", None)
        engine.model_selector = p.get("model_selector", None)
        if engine.model_selector:
            logger.info(
                f"Language-aware model selector enabled "
                f"(device={engine.model_selector.hardware_info.recommended_device})"
            )

        engine._force_accept = p.get("force_accept", False)
        engine.force_retranslate = p.get("force_retranslate", False)
        engine.cache_write_mode = p.get("cache_write_mode", "auto")
        engine.changed_since_sha = p.get("changed_since_sha", None)

        if engine.cache_write_mode != "auto":
            logger.info(f"Cache write mode: {engine.cache_write_mode}")
        if engine.force_retranslate:
            logger.info("Force retranslate enabled (cache lookup will be bypassed)")

    # ------------------------------------------------------------------
    # Phase 2: Review cache
    # ------------------------------------------------------------------
    @staticmethod
    def _init_review_cache(engine, p):
        engine._review_cache = None
        engine._review_cache_config_fingerprint = ""
        try:
            _rc_cfg = (
                engine.config.get_config().get("review_cache", {})
                if hasattr(engine.config, "get_config")
                else {}
            )
            if _rc_cfg.get("enabled", False):
                from .validation.review_cache import ReviewCache

                engine._review_cache = ReviewCache(
                    cache_path=_rc_cfg.get("cache_path"),
                    max_entries=_rc_cfg.get("max_entries", 10_000),
                    max_age_days=_rc_cfg.get("max_age_days", 14),
                )
                _te_cfg = (
                    engine.config.get_config().get("translation_engine", {})
                    if hasattr(engine.config, "get_config")
                    else {}
                )
                engine._review_cache_config_fingerprint = (
                    ReviewCache.compute_config_fingerprint(_te_cfg)
                )
                logger.info(
                    "Review cache enabled (%d entries loaded, config_fingerprint=%s)",
                    engine._review_cache.size,
                    engine._review_cache_config_fingerprint,
                )
        except Exception as _rc_err:
            logger.debug("Review cache init failed (disabled): %s", _rc_err)

    # ------------------------------------------------------------------
    # Phase 3: Multi-language config
    # ------------------------------------------------------------------
    @staticmethod
    def _init_multi_language(engine, p):
        engine.parallel_languages = p.get("parallel_languages", 0)
        engine.global_lang_rounds = p.get("global_lang_rounds", 0)
        engine.global_lang_sort = p.get("global_lang_sort", "desc")

        if engine.parallel_languages > 0 and engine.global_lang_rounds > 0:
            raise ValueError(
                "Cannot use both parallel_languages and global_lang_rounds simultaneously. "
                "Choose either parallel processing or round-robin, not both."
            )

        if engine.parallel_languages > 0:
            logger.info(
                f"Parallel language processing enabled: {engine.parallel_languages} workers"
            )
        elif engine.global_lang_rounds > 0:
            logger.info(
                f"Round-robin language processing enabled: {engine.global_lang_rounds} texts/round, "
                f"sort={engine.global_lang_sort}"
            )

    # ------------------------------------------------------------------
    # Phase 4: TM override mode
    # ------------------------------------------------------------------
    @staticmethod
    def _init_tm_override(engine, p):
        from ..tm.override_controller import OverrideMode

        override_mode = p["override_mode"]
        if override_mode:
            mode_map = {
                "normal": OverrideMode.NORMAL,
                "bypass": OverrideMode.BYPASS,
                "refresh": OverrideMode.REFRESH,
                "validate": OverrideMode.VALIDATE,
            }
            mode = mode_map.get(override_mode.lower(), OverrideMode.NORMAL)
            engine.tm.set_override_mode(mode, p["override_filters"])

    # ------------------------------------------------------------------
    # Phase 5: Core components
    # ------------------------------------------------------------------
    @staticmethod
    def _init_components(engine, p):
        from .extractor.placeholder_manager import PlaceholderManager
        from .handlers.multiline_handler import MultilineHandler
        from .parser import HugoParser
        from .validation import ValidationSuite
        from .validation.decision_engine import ValidationDecisionEngine

        engine.parser = HugoParser()
        engine.validation_suite = p["validation_suite"] or (
            ValidationSuite() if p["enable_validation"] else None
        )
        engine.placeholder_manager = PlaceholderManager()
        engine.multiline_handler = MultilineHandler()

        max_retries = p["max_retries"]
        validation_mode = p["validation_mode"]

        decision_config = {
            "decision_rules": {
                "max_retry_attempts": max_retries if max_retries is not None else 2,
                "reject_on_error_count": 3,
                "accept_warnings": True,
                "accept_after_max_retries": False,
                "reject_on_placeholder_error": True,
                "reject_on_code_block_error": True,
                "reject_on_link_error": True,
                "reject_on_repetition_error": True,
                "retry_on_structure_error": True,
                "retry_on_terminology_warning": True,
            }
        }

        if validation_mode == "strict":
            decision_config["decision_rules"]["reject_on_error_count"] = 1
            decision_config["decision_rules"]["accept_warnings"] = False
        elif validation_mode == "lenient":
            decision_config["decision_rules"]["reject_on_error_count"] = 5
            decision_config["decision_rules"]["accept_warnings"] = True
        elif validation_mode == "fast":
            # Fast mode for MT batch runs: accepts non-critical single errors.
            # max_retry_attempts=0 skips RETRY→REJECT loop; accept_after_max_retries=True
            # allows non-critical validator failures to pass (LanguageConsistency, etc.).
            # Critical validators (Placeholder, CodeBlock, Link, Structure) still block.
            decision_config["decision_rules"]["max_retry_attempts"] = 0
            decision_config["decision_rules"]["accept_after_max_retries"] = True
            decision_config["decision_rules"]["accept_warnings"] = True

        if p["decision_engine"] is not None:
            engine.decision_engine = p["decision_engine"]
        elif p["enable_validation"]:
            _adaptive_provider = None
            try:
                from src.utils.config_loader import get_global_config

                _at_cfg = get_global_config().get("adaptive_thresholds", {})
                if _at_cfg.get("enabled", False):
                    from src.observability.run_history import RunHistoryTracker

                    from .validation.decision_engine import AdaptiveThresholdProvider

                    _rh_cfg = get_global_config().get("run_history", {})
                    _db_path = _rh_cfg.get("db_path", "data/metrics/run_history.db")
                    _tracker = RunHistoryTracker(_db_path)
                    _adaptive_provider = AdaptiveThresholdProvider(
                        run_history=_tracker, config=_at_cfg
                    )
            except Exception:
                pass
            engine.decision_engine = ValidationDecisionEngine(
                decision_config, adaptive_provider=_adaptive_provider
            )
        else:
            engine.decision_engine = None

    # ------------------------------------------------------------------
    # Phase 6: Telemetry
    # ------------------------------------------------------------------
    @staticmethod
    def _init_telemetry(engine, p):
        from ..observability.telemetry_integration import get_telemetry

        engine.telemetry = get_telemetry() if p["enable_telemetry"] else None

    # ------------------------------------------------------------------
    # Phase 7: Terminology
    # ------------------------------------------------------------------
    @staticmethod
    def _init_terminology(engine, p):
        engine.terminology_manager = None
        if engine.enable_terminology:
            try:
                from .terminology import TerminologyManager

                terminology_config_path = "config/terminology.yaml"
                if Path(terminology_config_path).exists():
                    engine.terminology_manager = TerminologyManager(terminology_config_path)
                    logger.info(
                        f"Terminology protection enabled (config: {terminology_config_path})"
                    )
                else:
                    logger.warning(
                        f"Terminology config not found at {terminology_config_path}, terminology protection disabled"
                    )
            except Exception as e:
                logger.warning(f"Failed to initialize TerminologyManager: {e}")

    # ------------------------------------------------------------------
    # Phase 8: Locks
    # ------------------------------------------------------------------
    @staticmethod
    def _init_locks(engine, p):
        engine._tm_lock = Lock()
        engine._model_lock = Lock()

        engine._shutdown_requested = False
        engine._shutdown_lock = Lock()
        engine._current_file = None
        engine._shutdown_callbacks = []

        engine.progress_tracker = p["progress_tracker"]

    # ------------------------------------------------------------------
    # Phase 9: Retry metrics
    # ------------------------------------------------------------------
    @staticmethod
    def _init_retry_metrics(engine, p):
        from ..utils.config_loader import get_metrics_config

        metrics_config = get_metrics_config()
        retry_maxlen = metrics_config["metrics"]["storage"]["translation_engine"][
            "retry_metrics_maxlen"
        ]

        engine._retry_metrics = {
            "retry_attempts": deque(maxlen=retry_maxlen),
            "retry_durations_ms": deque(maxlen=retry_maxlen),
            "retry_reasons": {},
        }
        engine._retry_metrics_lock = Lock()

    # ------------------------------------------------------------------
    # Phase 10: Content hash
    # ------------------------------------------------------------------
    @staticmethod
    def _init_content_hash(engine, p):
        engine.enable_content_hash = p.get("enable_content_hash_tracking", True)
        engine.metadata_tracker = None

    # ------------------------------------------------------------------
    # Phase 11: Adaptive batching
    # ------------------------------------------------------------------
    @staticmethod
    def _init_adaptive_batching(engine, p):
        engine.batch_stats_tracker = None
        adaptive_config = engine._load_adaptive_config()
        if adaptive_config.get("enabled", False):
            from .extractor.batch_stats_tracker import BatchStatsTracker

            hardware_baseline = p.get("hardware_baseline")
            engine.batch_stats_tracker = BatchStatsTracker(
                config=adaptive_config, hardware_baseline=hardware_baseline
            )
            try:
                engine.batch_stats_tracker.load()
                lang_count = len(engine.batch_stats_tracker.languages)
                threshold = engine.batch_stats_tracker.fallback_rate_threshold
                logger.info(
                    f"[ENABLED] Adaptive Batching: {lang_count} languages loaded, "
                    f"threshold={threshold:.1%}"
                )
                if lang_count > 0:
                    for i, (lang, stats) in enumerate(engine.batch_stats_tracker.languages.items()):
                        if i >= 5:
                            break
                        batch_size = stats.get("batch_size", "N/A")
                        logger.info(f"  - {lang}: batch_size={batch_size}")
            except Exception as e:
                logger.warning(f"Failed to load batch statistics: {e}, starting fresh")
        else:
            logger.info("[DISABLED] Adaptive Batching")

    # ------------------------------------------------------------------
    # Phase 12: Language detection
    # ------------------------------------------------------------------
    @staticmethod
    def _init_detection(engine, p):
        from .language_detection.fasttext_detector import FastTextDetector
        from .language_detection.similarity_tracker import SimilarityTracker

        engine.fasttext_detector = None
        engine.detector = None
        engine.similarity_tracker = None
        engine._space_check_cache = {}

        lang_detection_config = engine._load_language_detection_config()
        if lang_detection_config.get("provider") == "fasttext":
            try:
                fasttext_config = lang_detection_config.get("fasttext", {})
                cache_dir = Path(fasttext_config.get("model_cache_dir", "./data/models/fasttext"))
                model_url = fasttext_config.get("model_url")
                min_confidence = fasttext_config.get("min_confidence", 0.70)
                auto_download = fasttext_config.get("auto_download", True)
                download_retries = fasttext_config.get("download_retries", 3)
                fallback_to_langdetect = fasttext_config.get("fallback_to_langdetect", True)

                engine.fasttext_detector = FastTextDetector(
                    cache_dir=cache_dir,
                    model_url=model_url,
                    min_confidence=min_confidence,
                    auto_download=auto_download,
                    download_retries=download_retries,
                    fallback_to_langdetect=fallback_to_langdetect,
                )
                engine.detector = engine.fasttext_detector

                if engine.fasttext_detector.is_available:
                    logger.info("FastText language detection initialized")
                else:
                    logger.warning("FastText language detection unavailable, continuing without it")
                    engine.fasttext_detector = None
                    engine.detector = None

            except Exception as e:
                logger.warning(
                    f"Failed to initialize FastTextDetector: {e}, continuing without language detection"
                )
                engine.fasttext_detector = None
                engine.detector = None

        adaptive_similarity_config = lang_detection_config.get("adaptive_similarity", {})
        if (
            adaptive_similarity_config.get("enabled", True)
            and lang_detection_config.get("provider") == "fasttext"
        ):
            try:
                engine.similarity_tracker = SimilarityTracker(adaptive_similarity_config)
                engine.similarity_tracker.load()
                logger.info("Adaptive similarity tracker initialized")
            except Exception as e:
                logger.warning(
                    f"Failed to initialize SimilarityTracker: {e}, continuing without adaptive similarity"
                )
                engine.similarity_tracker = None

    # ------------------------------------------------------------------
    # Phase 13: Retry handler
    # ------------------------------------------------------------------
    @staticmethod
    def _init_retry_handler(engine, p):
        from .retry_handler import RetryHandler

        engine.retry_handler = None
        oom_retry_config = engine._load_oom_retry_config()
        if oom_retry_config and oom_retry_config.get("enabled", True):
            try:
                max_retries = oom_retry_config.get("max_retries", 3)
                batch_reduction_factor = oom_retry_config.get("batch_reduction_factor", 0.5)
                min_batch_size = oom_retry_config.get("min_batch_size", 1)

                engine.retry_handler = RetryHandler(
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
                engine.retry_handler = None
        elif oom_retry_config and not oom_retry_config.get("enabled", True):
            logger.info("[DISABLED] OOM Retry Handler: enabled=false")
        else:
            logger.info("[DISABLED] OOM Retry Handler: missing config")

    # ------------------------------------------------------------------
    # Phase 14: TM wiring
    # ------------------------------------------------------------------
    @staticmethod
    def _init_tm_wiring(engine, p):
        if engine.tm is not None:
            try:
                _det = engine._get_language_detector()
                if _det is not None and getattr(engine.tm, "_language_detector", None) is None:
                    engine.tm._language_detector = _det
                _sim = getattr(engine, "similarity_tracker", None)
                if _sim is not None and getattr(engine.tm, "_similarity_tracker", None) is None:
                    engine.tm._similarity_tracker = _sim
                if _det is not None:
                    logger.info("Wired language detector into TM for cache hit validation")
            except Exception as _tm_wire_err:
                logger.debug(f"TM detector wiring failed (non-fatal): {_tm_wire_err}")

        try:
            _l3_enc = getattr(getattr(engine.tm, "l3", None), "encoder", None)
            if _l3_enc is not None:
                from src.translation_engine.validation.semantic_similarity_validator import (
                    SemanticSimilarityValidator,
                )

                SemanticSimilarityValidator.set_encoder(_l3_enc)
        except Exception as _sem_wire_err:
            logger.debug(
                "SemanticSimilarityValidator encoder wiring failed (non-fatal): %s", _sem_wire_err
            )

    # ------------------------------------------------------------------
    # Phase 15: Extracted components
    # ------------------------------------------------------------------
    @staticmethod
    def _init_extracted_components(engine, p):
        from .directory_orchestrator import DirectoryOrchestrator
        from .file_pipeline import FileTranslationPipeline
        from .segment_translator import SegmentTranslator
        from .write_gate import WriteGateEvaluator

        engine._dir_orchestrator = DirectoryOrchestrator(engine)

        engine._write_gate = WriteGateEvaluator(
            detector=engine._get_language_detector(),
            similarity_tracker=engine.similarity_tracker,
            config=engine.config,
            force_accept=engine._force_accept,
        )

        engine._file_pipeline = FileTranslationPipeline(engine)
        engine._segment_translator = SegmentTranslator(engine)
