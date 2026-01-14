"""
Machine Translation backend using local models (M2M100, NLLB).

Wraps the existing ModelLoader to provide ITranslationBackend interface.
"""

import logging
from typing import List, Dict, Any, Optional

from .interface import ITranslationBackend
from src.model_runtime.loader import ModelLoader
from src.model_runtime.registry import ModelRegistry

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
        max_memory_mb: Optional[int] = None,
        load_mode: Optional[str] = None,
        config: Optional[Dict] = None
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

        logger.info(
            f"MTBackend initialized: model={model_id}, device={device}, "
            f"max_memory={max_memory_mb}MB, load_mode={load_mode}"
        )

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

        # Translate using HuggingFace backend
        # Backend.translate() expects List[str], returns List[str]
        translations = self.backend.translate(
            texts=[text],
            src_lang=src_lang,
            tgt_lang=tgt_lang,
            max_new_tokens=max_new_tokens
        )

        return translations[0] if translations else ""

    def translate_batch(
        self,
        texts: List[str],
        src_lang: str,
        tgt_lang: str,
        **kwargs: Any
    ) -> List[str]:
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

        # Batch translate using HuggingFace backend
        translations = self.backend.translate(
            texts=texts,
            src_lang=src_lang,
            tgt_lang=tgt_lang,
            max_new_tokens=max_new_tokens
        )

        return translations

    def get_model_info(self) -> Dict[str, Any]:
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
