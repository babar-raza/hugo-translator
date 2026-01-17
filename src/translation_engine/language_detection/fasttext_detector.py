"""
FastText-based language detection for translation validation.

Provides accurate language identification using Facebook's lid.176.bin model
with support for 176 languages. Significantly more accurate than langdetect
for distinguishing similar languages (Romance, Cyrillic, Arabic script, etc.).
"""

import logging
import re
import urllib.request
from pathlib import Path
from typing import Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from .similarity_tracker import SimilarityTracker

logger = logging.getLogger(__name__)

# Unicode range constants for script validation
UNICODE_RANGES = {
    "latin": (0x0000, 0x024F),        # Basic Latin + Latin Extended
    "cyrillic": (0x0400, 0x04FF),     # Cyrillic
    "arabic": (0x0600, 0x06FF),       # Arabic
    "devanagari": (0x0900, 0x097F),   # Devanagari
    "cjk": (0x4E00, 0x9FFF),          # CJK Unified Ideographs
}


class FastTextDetector:
    """
    FastText language detector with automatic model download and caching.

    Features:
    - Automatic model download from Facebook's CDN
    - Local model caching
    - Confidence-based detection
    - Script-based validation fallback
    - Integration with adaptive similarity tracker
    """

    # Model constants
    DEFAULT_MODEL_URL = "https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.bin"
    DEFAULT_MODEL_FILENAME = "lid.176.bin"
    MODEL_SIZE_MB = 126  # Approximate size for progress reporting

    def __init__(
        self,
        cache_dir: Path,
        model_url: Optional[str] = None,
        model_filename: Optional[str] = None,
        min_confidence: float = 0.70,
        auto_download: bool = True,
        download_retries: int = 3,
        fallback_to_langdetect: bool = True,
    ):
        """
        Initialize FastText detector.

        Args:
            cache_dir: Directory for caching model file
            model_url: URL to download model from (default: Facebook's CDN)
            model_filename: Filename for cached model (default: lid.176.bin)
            min_confidence: Minimum confidence threshold for acceptance
            auto_download: Automatically download model if not cached
            download_retries: Number of retry attempts for download
            fallback_to_langdetect: Fall back to langdetect if FastText unavailable
        """
        self.cache_dir = Path(cache_dir)
        self.model_url = model_url or self.DEFAULT_MODEL_URL
        self.model_filename = model_filename or self.DEFAULT_MODEL_FILENAME
        self.model_path = self.cache_dir / self.model_filename
        self.min_confidence = min_confidence
        self.auto_download = auto_download
        self.download_retries = download_retries
        self.fallback_to_langdetect = fallback_to_langdetect

        self._model = None
        self._langdetect_available = False

        # Ensure cache directory exists
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Try to load model
        self._initialize_model()

    def _initialize_model(self) -> None:
        """Initialize FastText model with automatic download if needed."""
        try:
            import fasttext
            self._fasttext = fasttext
        except ImportError:
            logger.error("fasttext package not installed. Install with: pip install fasttext")
            self._try_langdetect_fallback()
            return

        # Check if model exists
        if not self.model_path.exists():
            if self.auto_download:
                logger.info(f"FastText model not found at {self.model_path}, downloading...")
                if not self._download_model():
                    self._try_langdetect_fallback()
                    return
            else:
                logger.error(
                    f"FastText model not found at {self.model_path}. "
                    f"Set auto_download=True or download manually from {self.model_url}"
                )
                self._try_langdetect_fallback()
                return

        # Load model
        try:
            # Suppress FastText warnings
            logger.debug(f"Loading FastText model from {self.model_path}...")
            self._model = self._fasttext.load_model(str(self.model_path))
            logger.info(f"FastText model loaded successfully (176 languages)")
        except Exception as e:
            logger.error(f"Failed to load FastText model: {e}")
            self._try_langdetect_fallback()

    def _download_model(self) -> bool:
        """
        Download FastText model with retry and progress reporting.

        Returns:
            True if download successful, False otherwise
        """
        for attempt in range(self.download_retries):
            try:
                logger.info(
                    f"Downloading FastText model (attempt {attempt + 1}/{self.download_retries}): "
                    f"{self.model_url} (~{self.MODEL_SIZE_MB}MB)"
                )

                # Download to temp file first
                temp_path = self.model_path.with_suffix(".tmp")

                # Simple progress callback
                def reporthook(block_num, block_size, total_size):
                    if total_size > 0 and block_num % 100 == 0:
                        downloaded_mb = (block_num * block_size) / (1024 ** 2)
                        total_mb = total_size / (1024 ** 2)
                        percent = min(100, (downloaded_mb / total_mb) * 100)
                        logger.info(f"Download progress: {downloaded_mb:.1f}MB / {total_mb:.1f}MB ({percent:.1f}%)")

                urllib.request.urlretrieve(self.model_url, temp_path, reporthook)

                # Move to final location
                temp_path.rename(self.model_path)

                logger.info(f"FastText model downloaded successfully to {self.model_path}")
                return True

            except Exception as e:
                logger.error(f"Download attempt {attempt + 1} failed: {e}")
                if attempt < self.download_retries - 1:
                    logger.info("Retrying in 5 seconds...")
                    import time
                    time.sleep(5)
                else:
                    logger.error(
                        f"Failed to download FastText model after {self.download_retries} attempts. "
                        f"You can manually download from {self.model_url} to {self.model_path}"
                    )
                    return False

        return False

    def _try_langdetect_fallback(self) -> None:
        """Try to enable langdetect as fallback."""
        if not self.fallback_to_langdetect:
            return

        try:
            import langdetect
            from langdetect import DetectorFactory
            DetectorFactory.seed = 0  # Deterministic results
            self._langdetect_available = True
            logger.warning("FastText unavailable, using langdetect as fallback")
        except ImportError:
            logger.error("Neither fasttext nor langdetect available. Language detection disabled.")

    def detect(self, text: str, min_length: int = 10) -> Tuple[str, float]:
        """
        Detect language of text with confidence score.

        Args:
            text: Text to detect language for
            min_length: Minimum text length for detection

        Returns:
            Tuple of (language_code, confidence)
            Example: ('ca', 0.95)
            Returns ('unknown', 0.0) if detection fails
        """
        # Check text length
        if not text or len(text.strip()) < min_length:
            return ("unknown", 0.0)

        # FastText detection
        if self._model:
            try:
                # FastText expects single line, normalize whitespace
                text_normalized = " ".join(text.split())

                # Predict language (returns tuple of labels and probabilities)
                predictions = self._model.predict(text_normalized, k=1)
                labels, probs = predictions

                # Extract language code (FastText returns '__label__xx' format)
                lang_code = labels[0].replace("__label__", "")
                confidence = float(probs[0])

                logger.debug(f"FastText detected: {lang_code} (confidence={confidence:.2f})")
                return (lang_code, confidence)

            except Exception as e:
                logger.warning(f"FastText detection failed: {e}")

        # Langdetect fallback
        if self._langdetect_available:
            try:
                import langdetect

                lang_code = langdetect.detect(text)
                # langdetect doesn't provide confidence, use fixed value
                confidence = 0.80

                logger.debug(f"langdetect detected: {lang_code} (confidence={confidence:.2f} assumed)")
                return (lang_code, confidence)

            except Exception as e:
                logger.warning(f"langdetect detection failed: {e}")

        # No detection available
        return ("unknown", 0.0)

    def verify_language(
        self,
        text: str,
        expected_lang: str,
        similarity_tracker: Optional["SimilarityTracker"] = None,
        script_validation_thresholds: Optional[dict] = None,
    ) -> bool:
        """
        Verify text is in expected language (or similar language).

        Uses multi-tier validation:
        1. FastText/langdetect detection with confidence threshold
        2. Adaptive similarity groups (if detected language is similar to expected)
        3. Script-based validation (Unicode ranges)

        Args:
            text: Text to verify
            expected_lang: Expected language code (ISO 639-1)
            similarity_tracker: Adaptive similarity tracker for learned pairs
            script_validation_thresholds: Script validation thresholds
                (e.g., {'latin': 0.90, 'cyrillic': 0.90})

        Returns:
            True if text is in expected language (or similar language), False otherwise
        """
        # Detect language
        detected_lang, confidence = self.detect(text)

        # Unknown detection = assume OK (can't verify)
        if detected_lang == "unknown":
            logger.debug("Language detection failed, assuming text is correct")
            return True

        # Exact match with high confidence = accept
        if detected_lang == expected_lang and confidence >= self.min_confidence:
            logger.debug(f"Exact language match: {expected_lang} (confidence={confidence:.2f})")
            return True

        # Check if languages are similar (adaptive learning)
        if similarity_tracker and similarity_tracker.are_similar(expected_lang, detected_lang):
            # WS4: Log acceptance at INFO level when similarity allows (Requirement 15)
            text_preview = text[:100] if len(text) > 100 else text
            logger.info(
                f"LANGUAGE PURITY NOTE: Expected {expected_lang}, detected {detected_lang} "
                f"(confidence: {confidence:.2%}) | "
                f"Text preview: {text_preview}... | "
                f"Action: ACCEPTED (similarity pair learned)"
            )

            # Record detection for adaptive learning
            similarity_tracker.record_detection(
                expected_lang=expected_lang,
                detected_lang=detected_lang,
                confidence=confidence,
                success=True,  # Accepted due to similarity
            )
            return True

        # Script-based validation fallback
        if script_validation_thresholds:
            script_result = self._validate_script(text, expected_lang, script_validation_thresholds)
            if script_result:
                logger.debug(
                    f"Script validation passed for {expected_lang}, "
                    f"overriding detection: {detected_lang} (confidence={confidence:.2f})"
                )

                # Record as successful detection (script override)
                if similarity_tracker:
                    similarity_tracker.record_detection(
                        expected_lang=expected_lang,
                        detected_lang=detected_lang,
                        confidence=confidence,
                        success=True,  # Accepted due to script validation
                    )
                return True

        # Failed all checks - WS4: Enhanced logging (Requirement 15)
        text_preview = text[:100] if len(text) > 100 else text
        logger.info(
            f"LANGUAGE PURITY ISSUE: Expected {expected_lang}, detected {detected_lang} "
            f"(confidence: {confidence:.2%}) | "
            f"Text preview: {text_preview}... | "
            f"Action: REJECTED (fallback to smaller batch)"
        )

        # Record failed detection for adaptive learning
        if similarity_tracker:
            similarity_tracker.record_detection(
                expected_lang=expected_lang,
                detected_lang=detected_lang,
                confidence=confidence,
                success=False,  # Rejected
            )

        return False

    def _validate_script(
        self, text: str, expected_lang: str, thresholds: dict
    ) -> bool:
        """
        Validate text matches expected script (Unicode ranges).

        Args:
            text: Text to validate
            expected_lang: Expected language code
            thresholds: Script validation thresholds (e.g., {'latin': 0.90})

        Returns:
            True if text passes script validation, False otherwise
        """
        # Map language to script
        script_map = {
            # Romance languages → Latin
            "ca": "latin", "es": "latin", "pt": "latin", "fr": "latin",
            "it": "latin", "ro": "latin", "gl": "latin",
            # Germanic/Nordic → Latin
            "en": "latin", "de": "latin", "nl": "latin", "da": "latin",
            "no": "latin", "sv": "latin", "is": "latin",
            # Slavic → Cyrillic
            "bg": "cyrillic", "ru": "cyrillic", "mk": "cyrillic",
            "uk": "cyrillic", "sr": "cyrillic", "be": "cyrillic",
            # Arabic script
            "ar": "arabic", "fa": "arabic", "ur": "arabic", "ps": "arabic",
            # Devanagari
            "hi": "devanagari", "mr": "devanagari", "ne": "devanagari", "sa": "devanagari",
            # CJK
            "zh": "cjk", "ja": "cjk", "ko": "cjk",
        }

        # Get script for language
        script = script_map.get(expected_lang)
        if not script or script not in thresholds:
            logger.debug(f"No script validation available for language: {expected_lang}")
            return False

        # Get threshold
        threshold = thresholds[script]

        # Count characters in script range
        range_start, range_end = UNICODE_RANGES[script]
        script_chars = sum(1 for char in text if range_start <= ord(char) <= range_end)
        total_chars = len([c for c in text if c.strip()])  # Exclude whitespace

        if total_chars == 0:
            return False

        # Calculate ratio
        ratio = script_chars / total_chars

        logger.debug(
            f"Script validation: {expected_lang}/{script} ratio={ratio:.2%} "
            f"(threshold={threshold:.2%})"
        )

        return ratio >= threshold

    @property
    def is_available(self) -> bool:
        """Check if FastText or fallback detection is available."""
        return self._model is not None or self._langdetect_available

    def __repr__(self) -> str:
        if self._model:
            return f"FastTextDetector(model={self.model_path.name}, threshold={self.min_confidence})"
        elif self._langdetect_available:
            return f"FastTextDetector(fallback=langdetect, threshold={self.min_confidence})"
        else:
            return "FastTextDetector(unavailable)"
