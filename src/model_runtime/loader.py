"""
Model Loader and Lifecycle Manager.

Manages loading, caching, and lifecycle of translation models across different backends.
"""
import gc
import logging
import time
from pathlib import Path
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import torch

from .registry import ModelInfo, ModelRegistry
from .language_codes import map_language_code
from .gpu_cache_manager import GPUCacheManager  # D5: Import GPU cache manager
from src.observability.metrics import get_metrics

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
        self,
        texts: List[str],
        src_lang: str,
        tgt_lang: str,
        max_new_tokens: Optional[int] = None,
        generation_params: Optional[Dict[str, Any]] = None
    ) -> List[str]:
        """
        Translate batch of texts.

        Args:
            texts: List of source texts
            src_lang: Source language code
            tgt_lang: Target language code
            max_new_tokens: Optional override for maximum new tokens
            generation_params: Optional dict of generation parameters
                              (e.g., {"num_beams": 4, "repetition_penalty": 1.2})

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


def _check_sentencepiece_available() -> bool:
    """Check if sentencepiece is installed."""
    try:
        import sentencepiece  # noqa: F401
        return True
    except ImportError:
        return False


def _model_requires_sentencepiece(model_id: str, hf_model_id: Optional[str] = None) -> bool:
    """
    Check if a model requires sentencepiece for tokenization.

    M2M100 and NLLB models use SentencePiece tokenization.
    """
    check_ids = [model_id.lower()]
    if hf_model_id:
        check_ids.append(hf_model_id.lower())

    sentencepiece_models = ["m2m100", "nllb", "mbart", "xlm"]
    return any(
        sp_model in check_id
        for check_id in check_ids
        for sp_model in sentencepiece_models
    )


class HuggingFaceBackend(ModelBackend):
    """Backend for HuggingFace Transformers models."""

    def __init__(
        self,
        model_info: ModelInfo,
        device: str,
        max_memory_mb: Optional[int] = None,
        use_fp16: Optional[bool] = None,
        use_int8: bool = False,
        generation_config: Optional[Dict] = None
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
        self.generation_config = generation_config or {}

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

        # BM-08: Track model load time
        load_start = time.perf_counter()

        # Check for sentencepiece dependency before attempting to load
        if _model_requires_sentencepiece(self.model_info.model_id, self.model_info.hf_model_id):
            if not _check_sentencepiece_available():
                raise RuntimeError(
                    f"Model '{self.model_info.model_id}' requires sentencepiece for tokenization. "
                    f"Install it with: pip install 'hugo-translation-system[m2m100]' "
                    f"or: pip install sentencepiece>=0.1.99"
                )

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

            # NOTE: GPU memory limit enforcement is handled by vram_enforcer.py
            # Do NOT set torch.cuda.set_per_process_memory_fraction here as it conflicts
            # with the global VRAM budget enforcement
            if self.device.startswith("cuda") and self.max_memory_mb:
                logger.debug(
                    f"GPU memory limit: {self.max_memory_mb}MB "
                    f"(enforced by vram_enforcer, not set here)"
                )

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

            # BM-08: Record model load duration
            load_duration = time.perf_counter() - load_start
            metrics = get_metrics()
            if metrics:
                metrics.observe("model_load_duration_seconds", load_duration)
                logger.debug(f"Model load took {load_duration:.2f}s")

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
        self, texts: List[str], src_lang: str, tgt_lang: str, max_new_tokens: Optional[int] = None,
        generation_params: Optional[Dict[str, Any]] = None
    ) -> List[str]:
        """
        Translate texts using HuggingFace model.

        Args:
            texts: List of source texts
            src_lang: Source language code
            tgt_lang: Target language code
            max_new_tokens: Override maximum new tokens (default: 512)
            generation_params: Optional dict of generation parameters to override defaults
                              (e.g., {"num_beams": 4, "temperature": 0.7})

        Returns:
            List of translated texts

        Note:
            Token counts are stored in instance variables:
            - self.last_input_tokens
            - self.last_output_tokens
        """
        translations, input_tokens, output_tokens = self.translate_with_token_counts(
            texts, src_lang, tgt_lang, max_new_tokens, generation_params
        )
        return translations

    def translate_with_token_counts(
        self, texts: List[str], src_lang: str, tgt_lang: str, max_new_tokens: Optional[int] = None,
        generation_params: Optional[Dict[str, Any]] = None
    ) -> tuple[List[str], int, int]:
        """
        Translate texts and return token counts.

        Args:
            texts: List of source texts
            src_lang: Source language code
            tgt_lang: Target language code
            max_new_tokens: Override maximum new tokens (default: 512)
            generation_params: Optional dict of generation parameters to override defaults
                              (e.g., {"num_beams": 4, "temperature": 0.7})

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

            # CRITICAL FIX: Reset tokenizer state before each translation
            # This prevents state bleeding between sequential translations to different languages

            # Step 1: Ensure model is in eval mode (should already be, but enforce it)
            self.model.eval()

            # Step 2: Set source language on tokenizer
            if hasattr(self.tokenizer, 'src_lang'):
                old_src = getattr(self.tokenizer, 'src_lang', None)
                if old_src and old_src != mapped_src_lang:
                    logger.debug(f"Language switch detected: src {old_src} -> {mapped_src_lang}")

                self.tokenizer.src_lang = mapped_src_lang
                # NLLB tokenizers also need special tokens set
                if hasattr(self.tokenizer, 'set_src_lang_special_tokens'):
                    self.tokenizer.set_src_lang_special_tokens(mapped_src_lang)

            # Step 3: Set target language for NLLB tokenizers
            if hasattr(self.tokenizer, 'tgt_lang'):
                old_tgt = getattr(self.tokenizer, 'tgt_lang', None)
                if old_tgt and old_tgt != mapped_tgt_lang:
                    logger.debug(f"Language switch detected: tgt {old_tgt} -> {mapped_tgt_lang}")

                self.tokenizer.tgt_lang = mapped_tgt_lang
                if hasattr(self.tokenizer, 'set_tgt_lang_special_tokens'):
                    self.tokenizer.set_tgt_lang_special_tokens(mapped_tgt_lang)
                    logger.debug(f"Set NLLB target language: {mapped_tgt_lang} (from {tgt_lang})")

            total_start = time.perf_counter()

            # Tokenize
            tokenize_start = time.perf_counter()
            inputs = self.tokenizer(
                texts, return_tensors="pt", padding=True, truncation=True
            )
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
            tokenize_ms = (time.perf_counter() - tokenize_start) * 1000

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
            # Note: max_new_tokens reduced to 256 for better memory efficiency
            # (was 512, but caused OOM with larger batches)
            # TR-01: Allow override via max_new_tokens parameter
            effective_max_tokens = max_new_tokens if max_new_tokens is not None else 256
            speed_mode = self.generation_config.get("speed_mode", True)
            generate_kwargs = {
                "max_new_tokens": effective_max_tokens,
                "num_beams": 1,
                "do_sample": False,
                "use_cache": True,
            }
            if not speed_mode:
                generate_kwargs["no_repeat_ngram_size"] = self.generation_config.get(
                    "no_repeat_ngram_size", 2
                )
                generate_kwargs["repetition_penalty"] = self.generation_config.get(
                    "repetition_penalty", 1.2
                )
            if forced_bos_token_id is not None:
                generate_kwargs["forced_bos_token_id"] = forced_bos_token_id

            # FIX-BATCH-API: Merge user-provided generation_params if present
            # Allow caller to override generation settings (e.g., num_beams, temperature)
            if generation_params:
                generate_kwargs.update(generation_params)
                logger.debug(f"Applied generation_params override: {generation_params}")

            generate_start = time.perf_counter()
            with torch.inference_mode():
                outputs = self.model.generate(
                    **inputs,
                    **generate_kwargs,
                )
            generate_ms = (time.perf_counter() - generate_start) * 1000

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
            decode_start = time.perf_counter()
            translations = self.tokenizer.batch_decode(
                outputs, skip_special_tokens=True
            )
            decode_ms = (time.perf_counter() - decode_start) * 1000

            # EMPTY TRANSLATION FALLBACK (Iter6 empty-translation fix)
            # Detect empty translations and retry with safer generation parameters
            empty_indices = []
            for idx, (translation, source_text) in enumerate(zip(translations, texts)):
                source_stripped = source_text.strip()
                translation_stripped = translation.strip()
                # Check if source is non-empty but translation is empty
                if source_stripped and not translation_stripped:
                    empty_indices.append(idx)
                    logger.warning(
                        f"Empty translation detected for text[{idx}]: '{source_text[:100]}...' "
                        f"(src_lang={src_lang}, tgt_lang={tgt_lang})"
                    )

            # If empty translations detected, attempt fallback recovery
            if empty_indices:
                metrics = get_metrics()
                if metrics:
                    metrics.increment("empty_translation_detected", len(empty_indices))

                logger.info(
                    f"Attempting recovery for {len(empty_indices)} empty translation(s) "
                    f"using fallback ladder"
                )

                # Attempt recovery using fallback ladder
                translations, recovered_count = self._recover_empty_translations(
                    texts, empty_indices, translations, inputs,
                    src_lang, tgt_lang, mapped_src_lang, mapped_tgt_lang,
                    forced_bos_token_id
                )

                if metrics and recovered_count > 0:
                    metrics.increment("empty_translation_recovered", recovered_count)

                # Check if any are still empty after recovery
                still_empty = []
                for idx in empty_indices:
                    if not translations[idx].strip():
                        still_empty.append(idx)

                if still_empty:
                    # Log detailed error for unrecovered empties
                    error_details = []
                    for idx in still_empty[:5]:  # Limit to 5 for logging
                        source_preview = texts[idx][:100] + "..." if len(texts[idx]) > 100 else texts[idx]
                        error_details.append(f"  [{idx}] '{source_preview}'")

                    logger.error(
                        f"Failed to recover {len(still_empty)} empty translation(s) after fallback attempts. "
                        f"Samples:\n" + "\n".join(error_details)
                    )
                else:
                    logger.info(
                        f"Successfully recovered all {len(empty_indices)} empty translation(s) "
                        f"using fallback strategies"
                    )

            # Store for backward compatibility
            self.last_input_tokens = input_token_count
            self.last_output_tokens = output_token_count

            total_ms = (time.perf_counter() - total_start) * 1000
            logger.info(
                "HF timing: batch=%d tokens_in=%d tokens_out=%d "
                "tokenize=%.1fms generate=%.1fms decode=%.1fms total=%.1fms speed_mode=%s",
                len(texts),
                input_token_count,
                output_token_count,
                tokenize_ms,
                generate_ms,
                decode_ms,
                total_ms,
                speed_mode,
            )

            return translations, input_token_count, output_token_count

        except torch.cuda.OutOfMemoryError as e:
            logger.error(f"GPU OOM during translation. Batch size: {len(texts)}")
            # Clear cache and retry with smaller batch
            if self.device.startswith("cuda"):
                torch.cuda.empty_cache()
            raise RuntimeError(
                f"GPU Out of Memory during translation. Reduce batch size (current: {len(texts)})"
            ) from e

    def _recover_empty_translations(
        self,
        texts: List[str],
        empty_indices: List[int],
        current_translations: List[str],
        inputs: Dict,
        src_lang: str,
        tgt_lang: str,
        mapped_src_lang: str,
        mapped_tgt_lang: str,
        forced_bos_token_id: Optional[int]
    ) -> tuple[List[str], int]:
        """
        Attempt to recover empty translations using a fallback ladder.

        Args:
            texts: Original source texts
            empty_indices: Indices of texts with empty translations
            current_translations: Current translation results
            inputs: Tokenized inputs (for reuse)
            src_lang: Source language code
            tgt_lang: Target language code
            mapped_src_lang: Mapped source language code
            mapped_tgt_lang: Mapped target language code
            forced_bos_token_id: Forced BOS token ID for target language

        Returns:
            Tuple of (updated_translations, recovered_count)
        """
        import re

        recovered_count = 0
        updated_translations = current_translations.copy()

        # Fallback strategies (tried in order)
        fallback_strategies = [
            {
                "name": "min_tokens_forced",
                "description": "Force min_new_tokens=1 with greedy decoding",
                "params": {
                    "min_new_tokens": 1,
                    "max_new_tokens": 256,
                    "num_beams": 1,
                    "do_sample": False,
                    "early_stopping": False,
                },
            },
            {
                "name": "beam_search",
                "description": "Use beam search with 5 beams",
                "params": {
                    "min_new_tokens": 1,
                    "max_new_tokens": 256,
                    "num_beams": 5,
                    "do_sample": False,
                    "early_stopping": True,
                },
            },
            {
                "name": "stripped_markdown",
                "description": "Strip markdown formatting and retry",
                "params": {
                    "min_new_tokens": 1,
                    "max_new_tokens": 256,
                    "num_beams": 3,
                    "do_sample": False,
                },
                "strip_markdown": True,
            },
        ]

        # Process each empty translation
        for idx in empty_indices:
            source_text = texts[idx]
            logger.debug(f"Attempting recovery for empty translation at index {idx}")

            # Try each fallback strategy in order
            for strategy in fallback_strategies:
                strategy_name = strategy["name"]
                gen_params = strategy["params"].copy()
                strip_markdown = strategy.get("strip_markdown", False)

                # Prepare text for this strategy
                if strip_markdown:
                    # Strip common markdown formatting
                    processed_text = re.sub(r'\*\*([^*]+)\*\*', r'\1', source_text)  # Bold
                    processed_text = re.sub(r'\*([^*]+)\*', r'\1', processed_text)  # Italic
                    processed_text = re.sub(r'`([^`]+)`', r'\1', processed_text)  # Code
                    logger.debug(
                        f"Strategy '{strategy_name}': stripped markdown "
                        f"'{source_text[:50]}...' -> '{processed_text[:50]}...'"
                    )
                else:
                    processed_text = source_text

                try:
                    # Tokenize the (possibly processed) text
                    single_input = self.tokenizer(
                        [processed_text], return_tensors="pt", padding=True, truncation=True
                    )
                    single_input = {k: v.to(self.device) for k, v in single_input.items()}

                    # Add forced_bos_token_id if available
                    if forced_bos_token_id is not None:
                        gen_params["forced_bos_token_id"] = forced_bos_token_id

                    # Generate with fallback parameters
                    logger.debug(
                        f"Strategy '{strategy_name}' attempt for index {idx}: {gen_params}"
                    )

                    with torch.inference_mode():
                        output = self.model.generate(
                            **single_input,
                            **gen_params,
                        )

                    # Decode
                    translation = self.tokenizer.batch_decode(
                        output, skip_special_tokens=True
                    )[0]

                    # Check if we got a non-empty translation
                    if translation.strip():
                        logger.info(
                            f"Strategy '{strategy_name}' recovered empty translation at index {idx}: "
                            f"'{translation[:100]}...' (source: '{source_text[:50]}...')"
                        )

                        # If we stripped markdown, we need to re-wrap the result
                        if strip_markdown and "**" in source_text:
                            # Attempt to re-wrap in bold (simple heuristic)
                            # Only if source had bold and translation doesn't
                            if "**" not in translation:
                                translation = f"**{translation}**"
                                logger.debug(
                                    f"Re-wrapped translation in bold: '{translation}'"
                                )

                        updated_translations[idx] = translation
                        recovered_count += 1
                        break  # Success, move to next empty index

                    else:
                        logger.debug(
                            f"Strategy '{strategy_name}' still produced empty output for index {idx}"
                        )

                except Exception as e:
                    logger.warning(
                        f"Strategy '{strategy_name}' failed for index {idx}: {e}"
                    )
                    continue

        return updated_translations, recovered_count

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

    def get_token_count(self, text: str) -> int:
        """
        Get actual token count using model tokenizer (accurate but ~5-10ms overhead).

        Args:
            text: Text to tokenize

        Returns:
            Token count, or 0 if tokenizer unavailable
        """
        if not self.tokenizer or not self.loaded:
            return 0
        try:
            tokens = self.tokenizer.tokenize(text)
            return len(tokens)
        except Exception as e:
            logger.debug(f"Token count failed: {e}")
            return 0

    def get_batch_token_counts(self, texts: List[str]) -> List[int]:
        """
        Get token counts for multiple texts efficiently.

        Args:
            texts: List of texts to tokenize

        Returns:
            List of token counts, or list of zeros if tokenizer unavailable
        """
        if not self.tokenizer or not self.loaded:
            return [0] * len(texts)
        try:
            encodings = self.tokenizer(texts, padding=False, truncation=False)
            return [len(ids) for ids in encodings["input_ids"]]
        except Exception:
            return [0] * len(texts)


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

            # NOTE: GPU memory limit enforcement is handled by vram_enforcer.py
            # Do NOT set torch.cuda.set_per_process_memory_fraction here
            if self.device.startswith("cuda") and self.max_memory_mb:
                logger.debug(
                    f"GPU memory limit for CT2: {self.max_memory_mb}MB "
                    f"(enforced by vram_enforcer, not set here)"
                )

            # Load tokenizer
            tokenizer_id = self.model_info.hf_model_id or model_path
            self.tokenizer = AutoTokenizer.from_pretrained(tokenizer_id)

            # Load CT2 model with compute type based on device
            compute_type = "int8" if self.device == "cpu" else "float16"
            logger.info(
                f"Loading CTranslate2 model: {self.model_info.model_id} "
                f"(path={model_path}, device={self.device}, compute_type={compute_type})"
            )

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

    def _convert_to_nllb_code(self, lang_code: str) -> str:
        """
        Convert ISO language code to NLLB format.

        NLLB uses format: {lang}_{script} (e.g., "fra_Latn", "eng_Latn", "zho_Hans")
        """
        # Map common codes to NLLB format
        nllb_map = {
            "en": "eng_Latn", "fr": "fra_Latn", "de": "deu_Latn", "es": "spa_Latn",
            "it": "ita_Latn", "pt": "por_Latn", "nl": "nld_Latn", "ru": "rus_Cyrl",
            "zh": "zho_Hans", "ja": "jpn_Jpan", "ko": "kor_Hang", "ar": "arb_Arab",
            "hi": "hin_Deva", "tr": "tur_Latn", "pl": "pol_Latn", "uk": "ukr_Cyrl",
            "cs": "ces_Latn", "sv": "swe_Latn", "da": "dan_Latn", "no": "nob_Latn",
            "fi": "fin_Latn", "el": "ell_Grek", "he": "heb_Hebr", "th": "tha_Thai",
            "vi": "vie_Latn", "id": "ind_Latn", "ro": "ron_Latn", "hu": "hun_Latn",
            "bg": "bul_Cyrl", "sk": "slk_Latn", "hr": "hrv_Latn", "sr": "srp_Cyrl",
            "sl": "slv_Latn", "et": "est_Latn", "lv": "lvs_Latn", "lt": "lit_Latn",
            "fa": "pes_Arab", "ca": "cat_Latn",
        }
        return nllb_map.get(lang_code, f"{lang_code}_Latn")

    def translate(
        self,
        texts: List[str],
        src_lang: str,
        tgt_lang: str,
        max_new_tokens: Optional[int] = None,
        generation_params: Optional[Dict[str, Any]] = None
    ) -> List[str]:
        """
        Translate texts using CTranslate2.

        Args:
            texts: List of source texts
            src_lang: Source language code
            tgt_lang: Target language code
            max_new_tokens: Override maximum new tokens (default: 512)
            generation_params: Optional dict of generation parameters
                              (e.g., {"beam_size": 4, "repetition_penalty": 1.2})

        Returns:
            List of translated texts
        """
        if not self.loaded:
            raise RuntimeError("Model not loaded. Call load() first.")

        if not texts:
            return []

        try:
            # For NLLB models, we need to:
            # 1. Encode to token IDs, then convert to token strings
            # 2. Use target language code as prefix
            # 3. Strip language token from output and decode

            # Set source language for tokenizer
            src_lang_code = self._convert_to_nllb_code(src_lang)
            self.tokenizer.src_lang = src_lang_code

            # Tokenize: encode to IDs, then convert to token strings
            tokenized = [
                self.tokenizer.convert_ids_to_tokens(self.tokenizer.encode(text, add_special_tokens=True))
                for text in texts
            ]

            # Set target language as prefix
            tgt_lang_code = self._convert_to_nllb_code(tgt_lang)
            target_prefix = [[tgt_lang_code]] * len(texts)

            # Extract generation parameters with defaults
            if generation_params is None:
                generation_params = {}

            beam_size = generation_params.get('num_beams', generation_params.get('beam_size', 4))
            max_decoding_length = max_new_tokens or generation_params.get('max_new_tokens', 512)
            repetition_penalty = generation_params.get('repetition_penalty', 1.0)
            length_penalty = generation_params.get('length_penalty', 1.0)
            no_repeat_ngram_size = generation_params.get('no_repeat_ngram_size', 0)

            # Translate with generation parameters
            results = self.translator.translate_batch(
                tokenized,
                target_prefix=target_prefix,
                beam_size=beam_size,
                max_decoding_length=max_decoding_length,
                repetition_penalty=repetition_penalty,
                length_penalty=length_penalty,
                no_repeat_ngram_size=no_repeat_ngram_size
            )

            # Detokenize: strip language token if present, convert tokens to IDs, decode
            translations = []
            for result in results:
                output_tokens = result.hypotheses[0]
                # Strip target language token if it's the first token
                if output_tokens and output_tokens[0] == tgt_lang_code:
                    output_tokens = output_tokens[1:]
                # Convert tokens to IDs and decode
                translation = self.tokenizer.decode(
                    self.tokenizer.convert_tokens_to_ids(output_tokens),
                    skip_special_tokens=True
                )
                translations.append(translation)

            # EMPTY TRANSLATION FALLBACK (parity with HuggingFaceBackend)
            # Detect empty translations and fall back to source text
            empty_indices = []
            for idx, (translation, source_text) in enumerate(zip(translations, texts)):
                source_stripped = source_text.strip()
                translation_stripped = translation.strip()
                # Check if source is non-empty but translation is empty
                if source_stripped and not translation_stripped:
                    empty_indices.append(idx)
                    logger.warning(
                        f"CT2 empty translation detected for text[{idx}]: '{source_text[:100]}...' "
                        f"(src_lang={src_lang}, tgt_lang={tgt_lang})"
                    )

            # If empty translations detected, fall back to source text
            if empty_indices:
                from ..observability.metrics import get_metrics
                metrics = get_metrics()
                if metrics:
                    metrics.increment("ct2_empty_translation_detected", len(empty_indices))

                logger.info(
                    f"CT2: Falling back to source text for {len(empty_indices)} empty translation(s)"
                )

                # Replace empty translations with source text
                recovered_count = 0
                for idx in empty_indices:
                    translations[idx] = texts[idx]
                    recovered_count += 1
                    logger.debug(
                        f"CT2: Fallback applied for index {idx}: '{texts[idx][:100]}...'"
                    )

                if metrics and recovered_count > 0:
                    metrics.increment("ct2_empty_translation_recovered", recovered_count)

                logger.info(
                    f"CT2: Applied source text fallback to {recovered_count} empty translation(s)"
                )

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

    def get_token_count(self, text: str) -> int:
        """
        CTranslate2 tokenizer wrapper for token counting.

        Args:
            text: Text to tokenize

        Returns:
            Token count, or 0 if tokenizer unavailable
        """
        if not self.tokenizer or not self.loaded:
            return 0
        try:
            tokens = self.tokenizer.tokenize(text)
            return len(tokens)
        except Exception:
            return 0


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
        load_mode: Optional[str] = None,
        config: Optional[Dict] = None
    ):
        """
        Initialize model loader.

        Args:
            registry: ModelRegistry instance
            device: Default device for models
            max_memory_mb: Maximum GPU memory per model (MB)
            load_mode: Model precision mode ("fp16", "fp32", "int8", or None for auto)
                      (T103: federated-splashing-panda)
            config: Optional config dict for hardware settings (D5)
        """
        self.registry = registry
        self.device = device
        self.max_memory_mb = max_memory_mb
        self.load_mode = load_mode
        self.loaded_models: Dict[str, ModelBackend] = {}

        # D5: Initialize GPU cache manager with config
        self.config = config or {}
        hardware_config = self.config.get("hardware", {})
        clear_every_n = hardware_config.get("clear_cache_frequency", 10)  # Default: every 10 files
        self.gpu_cache_manager = GPUCacheManager(clear_every_n_files=clear_every_n)
        logger.debug(f"ModelLoader initialized with GPU cache manager (clear_every_n_files={clear_every_n})")
        translation_config = self.config.get("translation") or {}
        self.generation_config = translation_config.get("generation") or {}

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
                use_int8=use_int8,   # T104: federated-splashing-panda
                generation_config=self.generation_config
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

    def get_tokenizer_for_counting(self, model_id: str) -> Optional[ModelBackend]:
        """
        Get backend with tokenizer for token counting (if loaded).

        Args:
            model_id: Model identifier

        Returns:
            ModelBackend if loaded and has tokenizer, None otherwise
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

    def clear_cache_after_file(self) -> None:
        """
        D5: Clear GPU cache after file translation using cache manager.

        This should be called after each file is translated to prevent
        memory accumulation and fragmentation.
        """
        self.gpu_cache_manager.clear_after_file(self.device)

    def check_and_clear_cache(self) -> bool:
        """
        D5: Check if aggressive cache clear is needed and perform if necessary.

        This should be called before large translation operations to ensure
        sufficient GPU memory is available.

        Returns:
            True if aggressive clear was performed, False otherwise
        """
        return self.gpu_cache_manager.check_and_clear(self.device)
