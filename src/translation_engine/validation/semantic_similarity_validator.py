"""
Semantic Similarity Validator (TC-17).

Validates that the translation is semantically equivalent to the source using
cross-lingual sentence embeddings.  Reuses the L3SemanticTM encoder when available
to avoid loading a second SentenceTransformer model.

Only active in strict validation mode (controlled via config/validation.yaml).
"""

from __future__ import annotations

import logging
from typing import Any

from .base import ValidationIssue, ValidationResult, ValidationSeverity, Validator

logger = logging.getLogger(__name__)


class SemanticSimilarityValidator(Validator):
    """
    Validates cross-lingual semantic equivalence between source and translation.

    Uses cosine similarity between sentence embeddings to detect major semantic drift:
    - similarity < error_threshold  → ERROR (major divergence, likely wrong content)
    - similarity < warn_threshold   → WARNING (possible drift, should review)
    - similarity >= warn_threshold  → OK

    Skips documents shorter than min_body_chars — too short for reliable embedding.

    Designed for strict mode only. Falls back gracefully if the encoder is unavailable.

    Encoder injection:
        Call `SemanticSimilarityValidator.set_encoder(encoder)` once after the engine's
        L3SemanticTM is initialised (e.g. from engine.py `__init__`). All instances
        then share that encoder via the class-level `_shared_encoder` slot without
        loading a second SentenceTransformer model.
    """

    WARN_THRESHOLD_DEFAULT = 0.55
    ERROR_THRESHOLD_DEFAULT = 0.40
    MIN_BODY_CHARS_DEFAULT = 200
    # Only embed the first N chars to keep latency low for large documents
    _MAX_EMBED_CHARS = 1000

    # Class-level shared encoder — set once by the engine after L3 initialisation.
    _shared_encoder: Any = None

    def __init__(
        self,
        encoder: Any | None = None,
        warn_threshold: float = WARN_THRESHOLD_DEFAULT,
        error_threshold: float = ERROR_THRESHOLD_DEFAULT,
        min_body_chars: int = MIN_BODY_CHARS_DEFAULT,
    ):
        """
        Initialize semantic similarity validator.

        Args:
            encoder: Optional instance-level SentenceTransformer encoder.
                     When None, falls back to the class-level shared encoder set via
                     `set_encoder()`.  Falls back gracefully to skip if unavailable.
            warn_threshold: Cosine similarity below this → WARNING
            error_threshold: Cosine similarity below this → ERROR
            min_body_chars: Skip documents with fewer characters than this
        """
        super().__init__(name="SemanticSimilarityValidator")
        self.encoder = encoder
        self.warn_threshold = warn_threshold
        self.error_threshold = error_threshold
        self.min_body_chars = min_body_chars

    @classmethod
    def set_encoder(cls, encoder: Any) -> None:
        """
        Inject a shared sentence encoder for all validator instances.

        Called by the translation engine after L3SemanticTM is initialised so
        that all SemanticSimilarityValidator instances can reuse the same encoder
        without loading a second SentenceTransformer model.

        Args:
            encoder: A SentenceTransformer-compatible encoder with an `encode()` method.
        """
        cls._shared_encoder = encoder
        logger.debug(
            "SemanticSimilarityValidator: shared encoder registered (%s)", type(encoder).__name__
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def validate(
        self,
        source: str,
        translation: str,
        context: dict[str, Any] | None = None,
    ) -> ValidationResult:
        """
        Compute cross-lingual semantic similarity and return a ValidationResult.

        Args:
            source: Source text (English)
            translation: Translated text
            context: Optional context dict; may contain 'tgt_lang'

        Returns:
            ValidationResult — OK, WARNING, ERROR, or skipped (success=True, info issue)
        """
        source = source or ""
        translation = translation or ""

        # Skip if too short for reliable detection
        if len(translation) < self.min_body_chars:
            result = ValidationResult(success=True)
            result.issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.INFO,
                    validator=self.name,
                    message=f"Skipped (translation too short: {len(translation)} chars < {self.min_body_chars})",
                )
            )
            return result

        # Acquire encoder (lazy — don't block if unavailable)
        enc = self._get_encoder()
        if enc is None:
            zero_defect = (context or {}).get("validation_policy") == "zero-defect"
            result = ValidationResult(success=not zero_defect)
            result.issues.append(
                ValidationIssue(
                    severity=(ValidationSeverity.ERROR if zero_defect else ValidationSeverity.INFO),
                    validator=self.name,
                    message=(
                        "Validator unavailable (no sentence encoder available)"
                        if zero_defect
                        else "Skipped (no sentence encoder available)"
                    ),
                )
            )
            return result

        try:
            similarity = self._cosine_similarity(
                enc,
                source[: self._MAX_EMBED_CHARS],
                translation[: self._MAX_EMBED_CHARS],
            )
        except Exception as exc:
            logger.debug("SemanticSimilarityValidator: embedding failed: %s", exc)
            if (context or {}).get("validation_policy") == "zero-defect":
                return ValidationResult(
                    success=False,
                    issues=[
                        ValidationIssue(
                            severity=ValidationSeverity.ERROR,
                            validator=self.name,
                            message="Validator unavailable (embedding execution failed)",
                            details={"exception_type": type(exc).__name__},
                        )
                    ],
                )
            return ValidationResult(success=True)  # fail open

        result = ValidationResult(success=True)

        if similarity < self.error_threshold:
            result.success = False
            result.issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator=self.name,
                    message=(
                        f"Semantic similarity {similarity:.3f} < {self.error_threshold} "
                        f"— translation meaning diverges significantly from source"
                    ),
                    details={"similarity": similarity, "threshold": self.error_threshold},
                )
            )
        elif similarity < self.warn_threshold:
            result.issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    validator=self.name,
                    message=(
                        f"Semantic similarity {similarity:.3f} — possible semantic drift "
                        f"(warn threshold: {self.warn_threshold})"
                    ),
                    details={"similarity": similarity, "threshold": self.warn_threshold},
                )
            )

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_encoder(self) -> Any | None:
        """
        Return the sentence encoder to use for this validation call.

        Priority:
        1. Instance-level encoder (constructor argument or direct assignment)
        2. Class-level shared encoder (injected via set_encoder() by the engine)
        """
        if self.encoder is not None:
            return self.encoder
        return self.__class__._shared_encoder

    @staticmethod
    def _cosine_similarity(encoder: Any, text_a: str, text_b: str) -> float:
        """
        Compute cosine similarity between embeddings of two texts.

        Uses numpy if available; falls back to pure-Python dot product otherwise.
        """
        emb_a = encoder.encode(text_a, convert_to_numpy=True, show_progress_bar=False)
        emb_b = encoder.encode(text_b, convert_to_numpy=True, show_progress_bar=False)

        try:
            import numpy as np  # type: ignore

            norm_a = np.linalg.norm(emb_a)
            norm_b = np.linalg.norm(emb_b)
            if norm_a == 0 or norm_b == 0:
                return 0.0
            return float(np.dot(emb_a, emb_b) / (norm_a * norm_b))
        except ImportError:
            # Pure Python fallback (slower but dependency-free)
            dot = sum(a * b for a, b in zip(emb_a, emb_b))
            norm_a = sum(a * a for a in emb_a) ** 0.5
            norm_b = sum(b * b for b in emb_b) ** 0.5
            if norm_a == 0 or norm_b == 0:
                return 0.0
            return dot / (norm_a * norm_b)
