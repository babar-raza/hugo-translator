"""
TC-17: Unit tests for SemanticSimilarityValidator.

Verifies:
- Happy path: similarity above both thresholds → success=True, no issues
- Warning path: similarity below warn_threshold → WARNING issue
- Error path: similarity below error_threshold → ERROR, success=False
- Short text → INFO skip (no encoder needed)
- No encoder available → INFO skip
- set_encoder() injects shared encoder accessible to all instances
- set_encoder() → _get_encoder() returns injected encoder
- Embedding exception fails open (success=True)
"""

import math
from unittest.mock import MagicMock

import pytest

from src.translation_engine.validation.base import ValidationSeverity
from src.translation_engine.validation.semantic_similarity_validator import (
    SemanticSimilarityValidator,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_encoder(similarity: float):
    """Return a mock encoder whose embeddings produce a fixed cosine similarity."""
    # cos(θ) = a·b / (|a||b|). Use unit vectors in 2D space.
    # vec_a = (1, 0), vec_b = (cos θ, sin θ) → dot = cos θ, norms = 1.
    angle = math.acos(max(-1.0, min(1.0, similarity)))
    vec_a = [1.0, 0.0]
    vec_b = [math.cos(angle), math.sin(angle)]

    call_count = [0]

    def encode(text, convert_to_numpy=True, show_progress_bar=False):
        v = vec_a if call_count[0] % 2 == 0 else vec_b
        call_count[0] += 1
        try:
            import numpy as np

            return np.array(v)
        except ImportError:
            return v

    enc = MagicMock()
    enc.encode.side_effect = encode
    return enc


LONG_TEXT = "x" * 300


# ---------------------------------------------------------------------------
# Threshold logic
# ---------------------------------------------------------------------------


def test_above_warn_threshold_returns_ok():
    validator = SemanticSimilarityValidator(
        encoder=_make_encoder(0.80),
        warn_threshold=0.55,
        error_threshold=0.40,
    )
    result = validator.validate(LONG_TEXT, LONG_TEXT)
    assert result.success
    assert not any(
        i.severity in (ValidationSeverity.ERROR, ValidationSeverity.WARNING) for i in result.issues
    )


def test_below_warn_threshold_returns_warning():
    validator = SemanticSimilarityValidator(
        encoder=_make_encoder(0.50),
        warn_threshold=0.55,
        error_threshold=0.40,
    )
    result = validator.validate(LONG_TEXT, LONG_TEXT)
    assert result.success  # WARNING does not fail
    severities = [i.severity for i in result.issues]
    assert ValidationSeverity.WARNING in severities
    assert ValidationSeverity.ERROR not in severities


def test_below_error_threshold_returns_error():
    validator = SemanticSimilarityValidator(
        encoder=_make_encoder(0.30),
        warn_threshold=0.55,
        error_threshold=0.40,
    )
    result = validator.validate(LONG_TEXT, LONG_TEXT)
    assert not result.success
    severities = [i.severity for i in result.issues]
    assert ValidationSeverity.ERROR in severities


# ---------------------------------------------------------------------------
# Short text skip
# ---------------------------------------------------------------------------


def test_short_text_returns_info_skip():
    validator = SemanticSimilarityValidator(
        encoder=_make_encoder(0.90),
        min_body_chars=200,
    )
    # Encoder should NOT be called
    result = validator.validate("Hello", "Hola")
    assert result.success
    assert any(i.severity == ValidationSeverity.INFO for i in result.issues)
    validator.encoder.encode.assert_not_called()


# ---------------------------------------------------------------------------
# No encoder — skip
# ---------------------------------------------------------------------------


def test_no_encoder_returns_info_skip():
    # Reset class-level shared encoder to None for isolation
    original = SemanticSimilarityValidator._shared_encoder
    SemanticSimilarityValidator._shared_encoder = None
    try:
        validator = SemanticSimilarityValidator(encoder=None)
        result = validator.validate(LONG_TEXT, LONG_TEXT)
        assert result.success
        assert any(i.severity == ValidationSeverity.INFO for i in result.issues)
    finally:
        SemanticSimilarityValidator._shared_encoder = original


# ---------------------------------------------------------------------------
# set_encoder() / _get_encoder() injection
# ---------------------------------------------------------------------------


def test_set_encoder_populates_shared_slot():
    original = SemanticSimilarityValidator._shared_encoder
    try:
        mock_enc = MagicMock()
        SemanticSimilarityValidator.set_encoder(mock_enc)
        assert SemanticSimilarityValidator._shared_encoder is mock_enc
    finally:
        SemanticSimilarityValidator._shared_encoder = original


def test_get_encoder_returns_shared_when_instance_is_none():
    original = SemanticSimilarityValidator._shared_encoder
    try:
        mock_enc = MagicMock()
        SemanticSimilarityValidator.set_encoder(mock_enc)
        validator = SemanticSimilarityValidator(encoder=None)
        assert validator._get_encoder() is mock_enc
    finally:
        SemanticSimilarityValidator._shared_encoder = original


def test_instance_encoder_takes_priority_over_shared():
    original = SemanticSimilarityValidator._shared_encoder
    try:
        shared_enc = MagicMock(name="shared")
        instance_enc = MagicMock(name="instance")
        SemanticSimilarityValidator.set_encoder(shared_enc)
        validator = SemanticSimilarityValidator(encoder=instance_enc)
        assert validator._get_encoder() is instance_enc
    finally:
        SemanticSimilarityValidator._shared_encoder = original


def test_shared_encoder_used_by_validate(tmp_path):
    """When set_encoder is called, validate() actually computes similarity."""
    original = SemanticSimilarityValidator._shared_encoder
    try:
        SemanticSimilarityValidator.set_encoder(_make_encoder(0.80))
        validator = SemanticSimilarityValidator(encoder=None, min_body_chars=50)
        result = validator.validate("A" * 100, "B" * 100)
        assert result.success
    finally:
        SemanticSimilarityValidator._shared_encoder = original


# ---------------------------------------------------------------------------
# Embedding exception fails open
# ---------------------------------------------------------------------------


def test_embedding_exception_fails_open():
    enc = MagicMock()
    enc.encode.side_effect = RuntimeError("CUDA OOM")
    validator = SemanticSimilarityValidator(encoder=enc)
    result = validator.validate(LONG_TEXT, LONG_TEXT)
    assert result.success  # fail open — no false positives on embedding error
    assert not any(i.severity == ValidationSeverity.ERROR for i in result.issues)
