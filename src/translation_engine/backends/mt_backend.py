"""
Machine Translation backend using local models (M2M100, NLLB).

Wraps the existing ModelLoader to provide ITranslationBackend interface.
"""

import logging
from typing import Any

from src.model_runtime.loader import ModelLoader
from src.model_runtime.registry import ModelRegistry

from .interface import ITranslationBackend

logger = logging.getLogger(__name__)


class MTBackend(ITranslationBackend):
    """
    Machine Translation backend for local GPU/CPU models.

    Wraps the existing ModelLoader to provide pluggable backend interface.
    Supports M2M100, NLLB, and other HuggingFace seq2seq models.

    Args:
        model_id: Model identifier (e.g., "m2m100_418m", "m2m100_1.2b")
        device: Execution device ("cuda", "cpu", "mps")
        max_memory_mb: Maximum GPU memory per model (MB)
        load_mode: Model precision ("fp16", "fp32", "int8", or None for auto)
        config: Optional config dict for hardware settings

    Example:
        backend = MTBackend(model_id="m2m100_418m", device="cuda")
        result = backend.translate("Hello", src_lang="en", tgt_lang="es")
    """

    def __init__(
        self,
        model_id: str,
        device: str = "cuda",
        max_memory_mb: int | None = None,
        load_mode: str | None = None,
        config: dict | None = None
    ):
        """Initialize MT backend with model configuration."""
        self.model_id = model_id
        self.device = device
        self.max_memory_mb = max_memory_mb
        self.load_mode = load_mode
        self.config = config or {}

        # Initialize model loader
        registry = ModelRegistry()
        self.loader = ModelLoader(
            registry=registry,
            device=device,
            max_memory_mb=max_memory_mb,
            load_mode=load_mode,
            config=config
        )

        # Backend will be loaded on first translate() call
        self.backend = None
        self._loaded = False

        # Lazy-loaded TerminologyManager — None means "not yet attempted", False means "unavailable"
        self._terminology_manager = None

        logger.info(
            f"MTBackend initialized: model={model_id}, device={device}, "
            f"max_memory={max_memory_mb}MB, load_mode={load_mode}"
        )

    @property
    def _term_manager(self):
        """Lazy-load TerminologyManager for pre/post-translation term protection.

        Gated by config flag `translation_engine.mt_terminology_protection` (default: false).
        Disabled by default because M2M100 may drop OOV placeholder tokens.
        Enable only after smoke-testing on real M2M100 output.
        """
        # Check feature gate first (avoid loading TM if disabled)
        try:
            from src.utils.config_loader import get_global_config
            enabled = get_global_config().get('translation_engine', {}).get(
                'mt_terminology_protection', False
            )
            if not enabled:
                return None
        except Exception:
            return None

        if self._terminology_manager is None:
            try:
                from pathlib import Path as _Path
                from src.translation_engine.terminology.terminology_manager import (
                    TerminologyManager,
                )
                _cfg = _Path("config/terminology.yaml")
                if not _cfg.exists():
                    _cfg = _Path(__file__).parent.parent.parent.parent / "config" / "terminology.yaml"
                self._terminology_manager = TerminologyManager(str(_cfg))
                logger.debug("TerminologyManager loaded for MT backend term protection")
            except Exception as e:
                logger.warning(
                    "TerminologyManager unavailable for MT backend: %s — terms sent raw to model", e
                )
                self._terminology_manager = False  # sentinel: don't retry
        return self._terminology_manager if self._terminology_manager else None

    def translate(
        self,
        text: str,
        src_lang: str,
        tgt_lang: str,
        **kwargs: Any
    ) -> str:
        """
        Translate a single text segment.

        Args:
            text: Source text to translate
            src_lang: Source language code (ISO 639-1)
            tgt_lang: Target language code (ISO 639-1)
            **kwargs: Optional MT-specific parameters:
                - max_new_tokens: Maximum tokens to generate (default: 512)

        Returns:
            Translated text string

        Raises:
            RuntimeError: If model loading fails
            torch.cuda.OutOfMemoryError: If GPU runs out of memory
        """
        # Lazy load model on first translate call
        if not self._loaded:
            self._load_model()

        # Extract optional parameters
        max_new_tokens = kwargs.get("max_new_tokens", None)

        # Optional terminology protect/restore (gated by mt_terminology_protection flag)
        tm = self._term_manager
        protected = None
        input_text = text
        if tm:
            try:
                protected = tm.protect(text)
                input_text = protected.protected_text
            except Exception as e:
                logger.debug("MT term protection failed, sending raw text: %s", e)
                protected = None
                input_text = text

        # Translate using HuggingFace backend
        # Backend.translate() expects List[str], returns List[str]
        translations = self.backend.translate(
            texts=[input_text],
            src_lang=src_lang,
            tgt_lang=tgt_lang,
            max_new_tokens=max_new_tokens
        )

        result = translations[0] if translations else ""

        if protected and tm:
            try:
                protected.protected_text = result
                result = tm.restore(protected)
            except Exception as e:
                logger.debug("MT term restoration failed, using raw translation: %s", e)

        return result

    def translate_batch(
        self,
        texts: list[str],
        src_lang: str,
        tgt_lang: str,
        **kwargs: Any
    ) -> list[str]:
        """
        Translate multiple texts in one batch (optimized).

        Args:
            texts: List of source texts to translate
            src_lang: Source language code
            tgt_lang: Target language code
            **kwargs: Optional MT-specific parameters

        Returns:
            List of translated texts (same order as input)
        """
        # Lazy load model on first translate call
        if not self._loaded:
            self._load_model()

        # Extract optional parameters
        max_new_tokens = kwargs.get("max_new_tokens", None)

        # Optional terminology protect/restore per segment (gated by config flag)
        tm = self._term_manager
        protected_segments = [None] * len(texts)
        input_texts = list(texts)
        if tm:
            for idx, text in enumerate(texts):
                try:
                    ps = tm.protect(text)
                    protected_segments[idx] = ps
                    input_texts[idx] = ps.protected_text
                except Exception as e:
                    logger.debug("MT batch term protection failed for segment %d: %s", idx, e)

        # Batch translate using HuggingFace backend
        translations = self.backend.translate(
            texts=input_texts,
            src_lang=src_lang,
            tgt_lang=tgt_lang,
            max_new_tokens=max_new_tokens
        )

        # Restore protected terms
        if tm:
            for idx, (ps, result) in enumerate(zip(protected_segments, translations)):
                if ps is not None:
                    try:
                        ps.protected_text = result
                        translations[idx] = tm.restore(ps)
                    except Exception as e:
                        logger.debug("MT batch term restoration failed for segment %d: %s", idx, e)

        return translations

    def get_model_info(self) -> dict[str, Any]:
        """
        Return backend metadata for telemetry.

        Returns:
            Dictionary with:
                - backend_type: "mt"
                - model_id: Model identifier
                - device: Execution device
                - load_mode: Precision mode
                - loaded: Whether model is currently loaded
        """
        return {
            "backend_type": "mt",
            "model_id": self.model_id,
            "device": self.device,
            "load_mode": self.load_mode or "auto",
            "max_memory_mb": self.max_memory_mb,
            "loaded": self._loaded,
        }

    def warmup(self) -> None:
        """
        Pre-load model for faster first translation.

        Loads model into memory without translating anything.
        Useful for reducing latency on first translate() call.
        """
        if not self._loaded:
            logger.info(f"Warming up MTBackend: {self.model_id}")
            self._load_model()
            logger.info(f"MTBackend warmed up: {self.model_id}")

    def shutdown(self) -> None:
        """
        Clean up GPU/CPU resources.

        Unloads model from memory and releases GPU resources.
        """
        if self._loaded and self.backend:
            logger.info(f"Shutting down MTBackend: {self.model_id}")
            self.backend.unload()
            self._loaded = False
            self.backend = None
            logger.info(f"MTBackend shut down: {self.model_id}")

    def _load_model(self) -> None:
        """
        Internal: Load model via ModelLoader.

        Raises:
            RuntimeError: If model loading fails
        """
        try:
            logger.info(f"Loading MT model: {self.model_id} on {self.device}")
            self.backend = self.loader.load_model(
                model_id=self.model_id,
                device=self.device
            )
            self._loaded = True
            logger.info(f"MT model loaded: {self.model_id}")
        except Exception as e:
            logger.error(f"Failed to load MT model {self.model_id}: {e}")
            raise RuntimeError(f"Failed to load MT model {self.model_id}: {e}") from e
