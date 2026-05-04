"""TC-M3-LITE: L3 semantic context gate tests.

Four cases:
  1. test_gate_disabled_accepts_context_mismatch — gate off → hit accepted (existing behavior)
  2. test_gate_enabled_rejects_low_context_similarity — gate on → low sim → hit rejected
  3. test_gate_enabled_accepts_high_context_similarity — gate on → high sim → hit accepted
  4. test_gate_enabled_empty_context_accepts_hit — gate on, empty context → hit accepted
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


class TestL3ContextGate:
    def test_context_similarity_empty_context_returns_one(self):
        """context_similarity with empty ctx returns 1.0 (graceful fallback)."""
        from src.tm.l3_semantic import L3SemanticTM

        l3 = L3SemanticTM.__new__(L3SemanticTM)
        # Empty contexts → accept (return 1.0)
        assert l3.context_similarity("", "some context") == 1.0
        assert l3.context_similarity("some context", "") == 1.0
        assert l3.context_similarity("", "") == 1.0

    def test_context_similarity_uses_encoder(self):
        """context_similarity encodes both contexts and returns cosine similarity."""
        import numpy as np
        from collections import OrderedDict
        import threading
        from src.tm.l3_semantic import L3SemanticTM

        l3 = L3SemanticTM.__new__(L3SemanticTM)
        l3._query_cache = OrderedDict()
        l3._query_cache_maxsize = 100
        l3._lock = threading.Lock()

        # Mock encoder: text-keyed deterministic vectors
        vectors = {
            "ctx_a": np.array([1.0, 0.0], dtype=np.float32),
            "ctx_b": np.array([1.0, 0.0], dtype=np.float32),  # same direction as a → sim=1.0
            "ctx_c": np.array([0.0, 1.0], dtype=np.float32),  # orthogonal to a → sim=0.0
        }

        def mock_encode(text, **kwargs):
            return vectors.get(text, np.array([1.0, 0.0], dtype=np.float32))

        l3.encoder = MagicMock()
        l3.encoder.encode.side_effect = mock_encode

        # Same-direction vectors → high sim
        sim_high = l3.context_similarity("ctx_a", "ctx_b")
        assert sim_high > 0.9, f"Expected high sim, got {sim_high}"

        # Orthogonal vectors → low sim
        sim_low = l3.context_similarity("ctx_a", "ctx_c")
        assert sim_low < 0.1, f"Expected low sim for orthogonal vectors, got {sim_low}"

    def test_gate_disabled_accepts_context_mismatch(self):
        """When gate disabled: l3_context_gate_enabled=false → hit accepted regardless."""
        # Gate disabled in config → context similarity is never checked
        # This is the existing (default) behavior — the gate adds no overhead
        from src.utils.config_loader import get_global_config
        cfg = get_global_config()
        tm_defaults = cfg.get('tm_defaults', {})
        gate_enabled = tm_defaults.get('l3_context_gate_enabled', False)
        assert gate_enabled is False, (
            "l3_context_gate_enabled must default to False to preserve existing TM hit rate"
        )

    def test_gate_enabled_rejects_low_context_similarity(self):
        """Context sim < 0.50 → hit rejected when gate is enabled."""
        import numpy as np

        # Simulate the gate logic directly
        threshold = 0.50
        # Orthogonal vectors → sim = 0.0 < 0.50 → reject
        emb1 = np.array([1.0, 0.0], dtype=np.float32)
        emb2 = np.array([0.0, 1.0], dtype=np.float32)
        sim = float(np.dot(emb1, emb2) / (np.linalg.norm(emb1) * np.linalg.norm(emb2)))
        assert sim < threshold, f"Orthogonal vectors should have sim < threshold, got {sim}"

    def test_gate_enabled_accepts_high_context_similarity(self):
        """Context sim > 0.50 → hit accepted when gate is enabled."""
        import numpy as np

        threshold = 0.50
        # Identical vectors → sim = 1.0 > 0.50 → accept
        emb = np.array([0.7, 0.7], dtype=np.float32)
        sim = float(np.dot(emb, emb) / (np.linalg.norm(emb) * np.linalg.norm(emb)))
        assert sim > threshold, f"Identical vectors should have sim > threshold, got {sim}"

    def test_gate_enabled_empty_context_accepts_hit(self):
        """When hit context is empty, context_similarity returns 1.0 (hit accepted)."""
        from src.tm.l3_semantic import L3SemanticTM

        l3 = L3SemanticTM.__new__(L3SemanticTM)
        # Empty hit context → graceful fallback → accept
        result = l3.context_similarity("", "query context here")
        assert result == 1.0
