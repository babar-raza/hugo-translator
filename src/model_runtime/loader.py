"""
Model Loader and Lifecycle Manager.

Manages loading, caching, and lifecycle of translation models across different backends.
"""
import gc
import logging
from pathlib import Path
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

import torch

from .registry import ModelInfo, ModelRegistry
from .language_codes import map_language_code

logger = logging.getLogger(__name__)


class ModelBackend(ABC):
    """Abstract base for translation model backends."""

    def __init__(self, model_info: ModelInfo, device: str):
        """
        Initialize backend.

        Args:
            model_info: Model metadata
            device: Device to load model on ("cpu", "cuda", "mps")
        """
        self.model_info = model_info
        self.device = device
        self.loaded = False

    @abstractmethod
    def load(self) -> None:
        """Load model into memory."""
        pass

    @abstractmethod
    def translate(
        self, texts: List[str], src_lang: str, tgt_lang: str
    ) -> List[str]:
        """
        Translate batch of texts.

        Args:
            texts: List of source texts
            src_lang: Source language code
            tgt_lang: Target language code

        Returns:
            List of translated texts
        """
        pass

    @abstractmethod
    def unload(self) -> None:
        """Release model resources."""
        pass

    def is_loaded(self) -> bool:
        """Check if model is loaded."""
        return self.loaded


class HuggingFaceBackend(ModelBackend):
    """Backend for HuggingFace Transformers models."""

    def __init__(
        self,
        model_info: ModelInfo,
        device: str,
        max_memory_mb: Optional[int] = None,
        use_fp16: Optional[bool] = None,
        use_int8: bool = False
    ):
        """
        Initialize HuggingFace backend.

        Args:
            model_info: Model metadata
            device: Device to load model on
            max_memory_mb: Maximum GPU memory to use (MB)
            use_fp16: Use float16 precision (None=auto, True=force, False=disable)
            use_int8: Use INT8 dynamic quantization (CPU-optimized)
                     (T104: federated-splashing-panda)
        """
        super().__init__(model_info, device)
        self.model = None
        self.tokenizer = None
        self.max_memory_mb = max_memory_mb

        # Precision mode determination (T104: federated-splashing-panda)
        if use_int8:
            # INT8 quantization (CPU-optimized, mutually exclusive with FP16)
            self.use_int8 = True
            self.use_fp16 = False
        else:
            self.use_int8 = False
            # FP16 mode: None=auto (CUDA default), True=force, False=disable
            if use_fp16 is None:
                self.use_fp16 = device.startswith("cuda")
            else:
                self.use_fp16 = use_fp16 and device.startswith("cuda")

        # Token tracking (TEL-04 integration)
        self.last_input_tokens = 0
        self.last_output_tokens = 0
        # Truncation detection (TR-02)
        self.last_truncation_detected = False
        self.truncation_count = 0

    def load(self) -> None:
        """Load HuggingFace model and tokenizer."""
        if self.loaded:
            return

        try:
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
            from transformers.utils import logging as hf_logging

            model_id = self.model_info.hf_model_id or self.model_info.model_id
            if self.model_info.local_path:
                local_path = Path(self.model_info.local_path)
                if (local_path / "config.json").exists():
                    model_id = str(local_path)

            # Suppress noisy tokenizer/model warnings during automated runs
            hf_logging.set_verbosity_error()

            # Enforce GPU memory limit if specified
            if self.device.startswith("cuda") and self.max_memory_mb:
                device_id = 0 if ":" not in self.device else int(self.device.split(":")[1])
                try:
                    total_memory = torch.cuda.get_device_properties(device_id).total_memory / (1024**2)
                    fraction = min(1.0, self.max_memory_mb / total_memory)
                    torch.cuda.set_per_process_memory_fraction(fraction, device_id)
                    logger.info(
                        f"Set GPU memory limit: {self.max_memory_mb}MB (fraction: {fraction:.2f})"
                    )
                except Exception as e:
                    logger.warning(f"Failed to set GPU memory limit: {e}")

            # Load tokenizer
            self.tokenizer = AutoTokenizer.from_pretrained(
                model_id, use_fast=True
            )

            # Load model with precision mode (T104: federated-splashing-panda)
            if self.use_int8:
                precision_str = "int8"
                logger.info(f"Loading HuggingFace model {model_id} on {self.device} ({precision_str})")

                # Load FP32 model first, then quantize to INT8
                self.model = AutoModelForSeq2SeqLM.from_pretrained(model_id)
                self.model.to(self.device)

                # Apply dynamic INT8 quantization (CPU-optimized)
                self.model = torch.quantization.quantize_dynamic(
                    self.model, {torch.nn.Linear}, dtype=torch.qint8
                )
                self.model.eval()

            elif self.use_fp16:
                precision_str = "fp16"
                logger.info(f"Loading HuggingFace model {model_id} on {self.device} ({precision_str})")

                # Load with FP16 precision (halves GPU memory)
                self.model = AutoModelForSeq2SeqLM.from_pretrained(
                    model_id, torch_dtype=torch.float16
                )
                self.model.to(self.device)
                self.model.eval()

            else:
                precision_str = "fp32"
                logger.info(f"Loading HuggingFace model {model_id} on {self.device} ({precision_str})")

                # Load with FP32 precision (full precision)
                self.model = AutoModelForSeq2SeqLM.from_pretrained(model_id)
                self.model.to(self.device)
                self.model.eval()

            # Log GPU memory usage if on GPU
            if self.device.startswith("cuda"):
                device_id = 0 if ":" not in self.device else int(self.device.split(":")[1])
                allocated = torch.cuda.memory_allocated(device_id) / (1024**2)
                logger.info(f"Model loaded ({precision_str}). GPU memory allocated: {allocated:.0f}MB")
            else:
                logger.info(f"Model loaded ({precision_str}) on CPU")

            self.loaded = True

        except torch.cuda.OutOfMemoryError as e:
            logger.error(f"GPU OOM loading model. Try reducing max_memory_mb or batch size.")
            raise RuntimeError(
                f"GPU Out of Memory loading {self.model_info.model_id}. "
                f"Reduce max_memory_mb or use CPU fallback."
            ) from e
        except Exception as e:
            raise RuntimeError(
                f"Failed to load HuggingFace model {self.model_info.model_id}: {e}"
            )

    def translate(
        self, texts: List[str], src_lang: str, tgt_lang: str, max_new_tokens: Optional[int] = None
    ) -> List[str]:
        """
        Translate texts using HuggingFace model.

        Args:
            texts: List of source texts
            src_lang: Source language code
            tgt_lang: Target language code
            max_new_tokens: Override maximum new tokens (default: 512)

        Returns:
            List of translated texts

        Note:
            Token counts are stored in instance variables:
            - self.last_input_tokens
            - self.last_output_tokens
        """
        translations, input_tokens, output_tokens = self.translate_with_token_counts(
            texts, src_lang, tgt_lang, max_new_tokens
        )
        return translations

    def translate_with_token_counts(
        self, texts: List[str], src_lang: str, tgt_lang: str, max_new_tokens: Optional[int] = None
    ) -> tuple[List[str], int, int]:
        """
        Translate texts and return token counts.

        Args:
            texts: List of source texts
            src_lang: Source language code
            tgt_lang: Target language code
            max_new_tokens: Override maximum new tokens (default: 512)

        Returns:
            Tuple of (translations, input_token_count, output_token_count)

        Note:
            Logs warning if truncation is detected (output length >= max_new_tokens).
            Truncation detection available via self.last_truncation_detected.
        """
        if not self.loaded:
            raise RuntimeError("Model not loaded. Call load() first.")

        if not texts:
            return [], 0, 0

        try:
            # Map language codes to model-specific format (M2M100 vs NLLB)
            # M2M100 uses ISO 639-1 codes (en, es, de)
            # NLLB uses language_Script format (eng_Latn, spa_Latn, deu_Latn)
            mapped_src_lang = map_language_code(
                src_lang,
                self.model_info.model_id,
                self.model_info.hf_model_id
            )
            mapped_tgt_lang = map_language_code(
                tgt_lang,
                self.model_info.model_id,
                self.model_info.hf_model_id
            )

            logger.debug(
                f"Language code mapping: {src_lang} -> {mapped_src_lang}, "
                f"{tgt_lang} -> {mapped_tgt_lang}"
            )

            # Set source language on tokenizer
            if hasattr(self.tokenizer, 'src_lang'):
                self.tokenizer.src_lang = mapped_src_lang
                # NLLB tokenizers also need special tokens set
                if hasattr(self.tokenizer, 'set_src_lang_special_tokens'):
                    self.tokenizer.set_src_lang_special_tokens(mapped_src_lang)

            # Set target language for NLLB tokenizers
            if hasattr(self.tokenizer, 'tgt_lang'):
                self.tokenizer.tgt_lang = mapped_tgt_lang
                if hasattr(self.tokenizer, 'set_tgt_lang_special_tokens'):
                    self.tokenizer.set_tgt_lang_special_tokens(mapped_tgt_lang)
                    logger.debug(f"Set NLLB target language: {mapped_tgt_lang} (from {tgt_lang})")

            # Tokenize
            inputs = self.tokenizer(
                texts, return_tensors="pt", padding=True, truncation=True
            )
            inputs = {k: v.to(self.device) for k, v in inputs.items()}

            # Calculate input token count
            # Shape: (batch_size, sequence_length)
            input_token_count = inputs["input_ids"].numel()

            # Get forced_bos_token_id for target language
            # Different models use different methods:
            # - M2M100: tokenizer.get_lang_id(lang)
            # - NLLB: tokenizer.convert_tokens_to_ids(lang)
            # - Others: tokenizer.lang_code_to_id[lang]
            forced_bos_token_id = None

            # Try M2M100 method
            if hasattr(self.tokenizer, 'get_lang_id'):
                try:
                    forced_bos_token_id = self.tokenizer.get_lang_id(mapped_tgt_lang)
                    logger.debug(
                        f"Set forced_bos_token_id={forced_bos_token_id} for {mapped_tgt_lang} "
                        f"(from {tgt_lang}) using get_lang_id()"
                    )
                except KeyError:
                    logger.warning(
                        f"Target language '{mapped_tgt_lang}' (from '{tgt_lang}') "
                        f"not found in tokenizer via get_lang_id()"
                    )
            # Try NLLB method
            elif hasattr(self.tokenizer, 'convert_tokens_to_ids') and hasattr(self.tokenizer, 'tgt_lang'):
                try:
                    forced_bos_token_id = self.tokenizer.convert_tokens_to_ids(mapped_tgt_lang)
                    logger.debug(
                        f"Set forced_bos_token_id={forced_bos_token_id} for {mapped_tgt_lang} "
                        f"(from {tgt_lang}) using convert_tokens_to_ids() [NLLB]"
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to get token ID for '{mapped_tgt_lang}' via convert_tokens_to_ids(): {e}"
                    )
            # Try generic lang_code_to_id
            elif hasattr(self.tokenizer, 'lang_code_to_id'):
                forced_bos_token_id = self.tokenizer.lang_code_to_id.get(mapped_tgt_lang)
                if forced_bos_token_id:
                    logger.debug(
                        f"Set forced_bos_token_id={forced_bos_token_id} for {mapped_tgt_lang} "
                        f"(from {tgt_lang}) using lang_code_to_id"
                    )
                else:
                    logger.warning(
                        f"Target language '{mapped_tgt_lang}' (from '{tgt_lang}') "
                        f"not found in tokenizer.lang_code_to_id"
                    )
            else:
                logger.debug(
                    f"Tokenizer doesn't use forced_bos_token_id. "
                    f"Target language may be set via tokenizer.tgt_lang instead."
                )

            # Generate translations (using settings from legacy/ast-translator.py)
            # Note: max_new_tokens increased from 200 to 512 to handle longer
            # multiline content like overview.content and content_left/content_right
            # TR-01: Allow override via max_new_tokens parameter
            effective_max_tokens = max_new_tokens if max_new_tokens is not None else 512
            generate_kwargs = {
                "max_new_tokens": effective_max_tokens,
                "no_repeat_ngram_size": 2,
                "repetition_penalty": 1.2,
            }
            if forced_bos_token_id is not None:
                generate_kwargs["forced_bos_token_id"] = forced_bos_token_id

            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    **generate_kwargs,
                )

            # Calculate output token count
            # Shape: (batch_size, generated_sequence_length)
            output_token_count = outputs.numel()

            # Detect truncation: check if any sequence in the batch reached max_new_tokens
            # outputs.shape is (batch_size, sequence_length)
            max_new_tokens = generate_kwargs["max_new_tokens"]
            max_output_length = outputs.shape[1]
            self.last_truncation_detected = False

            # Check if output length reached or exceeded the token limit
            # Allow a small tolerance (within 5 tokens) to account for early stopping
            if max_output_length >= max_new_tokens - 5:
                self.last_truncation_detected = True
                self.truncation_count += 1

                # Log warning with context for debugging
                for idx, text in enumerate(texts):
                    # Truncate source text for logging (first 100 chars)
                    text_preview = text[:100] + "..." if len(text) > 100 else text
                    logger.warning(
                        f"Possible truncation detected: output reached {max_output_length} tokens "
                        f"(limit: {max_new_tokens}). Source[{idx}]: '{text_preview}' "
                        f"(src_lang={src_lang}, tgt_lang={tgt_lang})"
                    )

            # Decode
            translations = self.tokenizer.batch_decode(
                outputs, skip_special_tokens=True
            )

            # Store for backward compatibility
            self.last_input_tokens = input_token_count
            self.last_output_tokens = output_token_count

            # Clear GPU cache after translation if on GPU
            if self.device.startswith("cuda"):
                torch.cuda.empty_cache()

            return translations, input_token_count, output_token_count

        except torch.cuda.OutOfMemoryError as e:
            logger.error(f"GPU OOM during translation. Batch size: {len(texts)}")
            # Clear cache and retry with smaller batch
            if self.device.startswith("cuda"):
                torch.cuda.empty_cache()
            raise RuntimeError(
                f"GPU Out of Memory during translation. Reduce batch size (current: {len(texts)})"
            ) from e

    def unload(self) -> None:
        """Unload model and free resources."""
        if self.model is not None:
            del self.model
            self.model = None

        if self.tokenizer is not None:
            del self.tokenizer
            self.tokenizer = None

        # Force garbage collection
        gc.collect()

        # Clear CUDA cache if using GPU
        if self.device == "cuda" and torch.cuda.is_available():
            torch.cuda.empty_cache()

        self.loaded = False


class CTranslate2Backend(ModelBackend):
    """Backend for CTranslate2 optimized models."""

    def __init__(self, model_info: ModelInfo, device: str, max_memory_mb: Optional[int] = None):
        """
        Initialize CTranslate2 backend.

        Args:
            model_info: Model metadata
            device: Device to load model on
            max_memory_mb: Maximum GPU memory to use (MB)
        """
        super().__init__(model_info, device)
        self.translator = None
        self.tokenizer = None
        self.max_memory_mb = max_memory_mb

    def load(self) -> None:
        """Load CTranslate2 model."""
        if self.loaded:
            return

        try:
            import ctranslate2
            from transformers import AutoTokenizer

            model_path = str(
                self.model_info.local_path or self.model_info.model_id
            )

            # Enforce GPU memory limit if specified
            if self.device.startswith("cuda") and self.max_memory_mb:
                device_id = 0 if ":" not in self.device else int(self.device.split(":")[1])
                try:
                    total_memory = torch.cuda.get_device_properties(device_id).total_memory / (1024**2)
                    fraction = min(1.0, self.max_memory_mb / total_memory)
                    torch.cuda.set_per_process_memory_fraction(fraction, device_id)
                    logger.info(
                        f"Set GPU memory limit for CT2: {self.max_memory_mb}MB (fraction: {fraction:.2f})"
                    )
                except Exception as e:
                    logger.warning(f"Failed to set GPU memory limit: {e}")

            # Load tokenizer
            tokenizer_id = self.model_info.hf_model_id or model_path
            self.tokenizer = AutoTokenizer.from_pretrained(tokenizer_id)

            # Load CT2 model with compute type based on device
            logger.info(f"Loading CTranslate2 model {model_path} on {self.device}")
            compute_type = "int8" if self.device == "cpu" else "float16"

            self.translator = ctranslate2.Translator(
                model_path,
                device=self.device,
                compute_type=compute_type,
            )

            # Log GPU memory if on GPU
            if self.device.startswith("cuda"):
                device_id = 0 if ":" not in self.device else int(self.device.split(":")[1])
                allocated = torch.cuda.memory_allocated(device_id) / (1024**2)
                logger.info(f"CT2 model loaded. GPU memory allocated: {allocated:.0f}MB")

            self.loaded = True

        except torch.cuda.OutOfMemoryError as e:
            logger.error(f"GPU OOM loading CTranslate2 model.")
            raise RuntimeError(
                f"GPU Out of Memory loading {self.model_info.model_id}. "
                f"Reduce max_memory_mb or use CPU fallback."
            ) from e
        except Exception as e:
            raise RuntimeError(
                f"Failed to load CTranslate2 model {self.model_info.model_id}: {e}"
            )

    def translate(
        self, texts: List[str], src_lang: str, tgt_lang: str
    ) -> List[str]:
        """
        Translate texts using CTranslate2.

        Args:
            texts: List of source texts
            src_lang: Source language code
            tgt_lang: Target language code

        Returns:
            List of translated texts
        """
        if not self.loaded:
            raise RuntimeError("Model not loaded. Call load() first.")

        if not texts:
            return []

        try:
            # Tokenize
            tokenized = [self.tokenizer.tokenize(text) for text in texts]

            # Translate
            results = self.translator.translate_batch(
                tokenized, beam_size=4, max_decoding_length=512
            )

            # Detokenize
            translations = [
                self.tokenizer.convert_tokens_to_string(result.hypotheses[0])
                for result in results
            ]

            # Clear GPU cache after translation if on GPU
            if self.device.startswith("cuda"):
                torch.cuda.empty_cache()

            return translations

        except RuntimeError as e:
            if "out of memory" in str(e).lower():
                logger.error(f"GPU OOM during CT2 translation. Batch size: {len(texts)}")
                if self.device.startswith("cuda"):
                    torch.cuda.empty_cache()
                raise RuntimeError(
                    f"GPU Out of Memory during translation. Reduce batch size (current: {len(texts)})"
                ) from e
            raise

    def unload(self) -> None:
        """Unload model and free resources."""
        if self.translator is not None:
            del self.translator
            self.translator = None

        if self.tokenizer is not None:
            del self.tokenizer
            self.tokenizer = None

        gc.collect()
        self.loaded = False


class ModelLoader:
    """
    Manages model lifecycle and caching.

    Handles loading, unloading, and caching of translation models.
    """

    def __init__(
        self,
        registry: ModelRegistry,
        device: str = "cpu",
        max_memory_mb: Optional[int] = None,
        load_mode: Optional[str] = None
    ):
        """
        Initialize model loader.

        Args:
            registry: ModelRegistry instance
            device: Default device for models
            max_memory_mb: Maximum GPU memory per model (MB)
            load_mode: Model precision mode ("fp16", "fp32", "int8", or None for auto)
                      (T103: federated-splashing-panda)
        """
        self.registry = registry
        self.device = device
        self.max_memory_mb = max_memory_mb
        self.load_mode = load_mode
        self.loaded_models: Dict[str, ModelBackend] = {}

    def load_model(self, model_id: str, device: Optional[str] = None) -> ModelBackend:
        """
        Load model, return backend instance.

        Args:
            model_id: Model identifier
            device: Optional device override

        Returns:
            Loaded ModelBackend instance
        """
        # Check if already loaded
        if model_id in self.loaded_models:
            return self.loaded_models[model_id]

        # Get model info
        model_info = self.registry.get_model(model_id)

        # Determine device
        target_device = device or self.device

        # Create backend
        backend = self._create_backend(model_info, target_device)

        # Load model
        backend.load()

        # Cache
        self.loaded_models[model_id] = backend

        return backend

    def _create_backend(
        self, model_info: ModelInfo, device: str
    ) -> ModelBackend:
        """
        Create appropriate backend for model.

        Args:
            model_info: Model metadata
            device: Device to load on

        Returns:
            ModelBackend instance
        """
        # Translate load_mode to backend parameters (T103: federated-splashing-panda)
        use_fp16 = None  # Auto by default
        use_int8 = False

        if self.load_mode == "fp16":
            use_fp16 = True
        elif self.load_mode == "fp32":
            use_fp16 = False
        elif self.load_mode == "int8":
            use_int8 = True
            use_fp16 = False  # INT8 and FP16 are mutually exclusive
        # else: load_mode is None (auto mode) - use backend defaults

        if model_info.backend == "huggingface":
            return HuggingFaceBackend(
                model_info,
                device,
                self.max_memory_mb,
                use_fp16=use_fp16,  # None = auto, True = force, False = disable
                use_int8=use_int8   # T104: federated-splashing-panda
            )
        elif model_info.backend == "ctranslate2":
            return CTranslate2Backend(model_info, device, self.max_memory_mb)
        else:
            raise ValueError(
                f"Unsupported backend: {model_info.backend}"
            )

    def get_loaded_model(self, model_id: str) -> Optional[ModelBackend]:
        """
        Get already-loaded model.

        Args:
            model_id: Model identifier

        Returns:
            ModelBackend if loaded, None otherwise
        """
        return self.loaded_models.get(model_id)

    def unload_model(self, model_id: str) -> None:
        """
        Unload model from memory.

        Args:
            model_id: Model identifier
        """
        if model_id in self.loaded_models:
            backend = self.loaded_models[model_id]
            backend.unload()
            del self.loaded_models[model_id]

    def unload_all(self) -> None:
        """Unload all models."""
        model_ids = list(self.loaded_models.keys())
        for model_id in model_ids:
            self.unload_model(model_id)

    def preload_models(self, model_ids: List[str]) -> None:
        """
        Preload multiple models.

        Args:
            model_ids: List of model identifiers to preload
        """
        for model_id in model_ids:
            if model_id not in self.loaded_models:
                self.load_model(model_id)

    def list_loaded_models(self) -> List[str]:
        """
        Get list of currently loaded model IDs.

        Returns:
            List of model IDs
        """
        return list(self.loaded_models.keys())

    def get_memory_usage(self) -> Dict[str, Dict[str, any]]:
        """
        Get memory usage for loaded models.

        Returns:
            Dict mapping model_id to memory info
        """
        usage = {}
        for model_id, backend in self.loaded_models.items():
            usage[model_id] = {
                "loaded": backend.is_loaded(),
                "device": backend.device,
                "backend": backend.model_info.backend,
                "size_mb": backend.model_info.model_size_mb,
            }
        return usage

    def __len__(self) -> int:
        """Return number of loaded models."""
        return len(self.loaded_models)

    def __contains__(self, model_id: str) -> bool:
        """Check if model is loaded."""
        return model_id in self.loaded_models

    def has_loaded_models(self) -> bool:
        """Check if any models are loaded."""
        return len(self.loaded_models) > 0

    def get_loaded_models(self) -> List[str]:
        """Get list of loaded model IDs."""
        return self.list_loaded_models()
