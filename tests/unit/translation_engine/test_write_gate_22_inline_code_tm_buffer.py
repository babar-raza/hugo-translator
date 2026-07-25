"""HT-INLINE-CODE-001 TC-ICR-005: Gate 22 registry/behavior contract +
TM-buffer safety.

Gate 22 (_gate_inline_code_integrity) was registered "auto_clean" in
GATE_REGISTRY despite its implementation being a hard block
(result.passed = False) -- _verify_gate_registry() only checked the method
existed, never that its declared action matched its actual behavior. This
closes both halves: the registry now says "block" (matching reality), and
the gate explicitly sets clear_tm_buffer=True on failure (matching the
existing Gates 4/8 precedent), on top of file_pipeline.py's TC-11 buffer
already gating persistence on `validation_passed` overall.
"""
from __future__ import annotations

from pathlib import Path

from src.translation_engine.write_gate import WriteGateEvaluator, WriteGateResult


def _evaluator() -> WriteGateEvaluator:
    return WriteGateEvaluator(detector=None, similarity_tracker=None, config=None)


class TestGateRegistryDeclaresBlock:
    def test_gate_22_is_registered_as_block_not_auto_clean(self) -> None:
        entry = next(
            e for e in WriteGateEvaluator.GATE_REGISTRY if e[0] == 22
        )
        gate_id, method_name, category, action = entry
        assert method_name == "_gate_inline_code_integrity"
        assert action == "block", (
            "Gate 22's registry action must match its real behavior "
            "(a hard block) -- see TC-ICR-005"
        )


class TestGate22FailureClearsTmBuffer:
    def test_corrupted_inline_code_blocks_and_clears_tm_buffer(self) -> None:
        evaluator = _evaluator()
        result = WriteGateResult(passed=True)
        source = "Use `equals`, `close`, and `create` here."
        translated = "Utilisez `identité`, `close`, et `create` ici."

        evaluator._gate_inline_code_integrity(
            source, translated, Path("test.md"), result
        )

        assert result.passed is False
        assert "equals" in result.error
        assert result.clear_tm_buffer is True

    def test_clean_translation_does_not_block_or_clear_buffer(self) -> None:
        evaluator = _evaluator()
        result = WriteGateResult(passed=True)
        source = "Use `equals`, `close`, and `create` here."
        translated = "Utilisez `equals`, `close`, et `create` ici."

        evaluator._gate_inline_code_integrity(
            source, translated, Path("test.md"), result
        )

        assert result.passed is True
        assert result.clear_tm_buffer is False

    def test_span_count_mismatch_declines_to_fire_rather_than_guess(self) -> None:
        """TC-ICR-004's shared-primitive migration: a count mismatch is
        ambiguous pairing, not a confirmed hit -- this gate must not block
        on it (other structural gates independently catch real drift)."""
        evaluator = _evaluator()
        result = WriteGateResult(passed=True)
        source = "Use `create`, `close`, and `equals` here."
        translated = "Utilisez `create`, `equals`, et `extra` ici."  # dropped + added

        evaluator._gate_inline_code_integrity(
            source, translated, Path("test.md"), result
        )

        assert result.passed is True
        assert result.clear_tm_buffer is False


class TestFullEvaluatorRunReachesGate22(object):
    """End-to-end through evaluate() (detector=None path), not just the
    gate method in isolation -- proves the registry re-labeling didn't
    accidentally short-circuit the gate out of the real dispatch loop."""

    def test_evaluate_blocks_on_inline_code_corruption(self, tmp_path) -> None:
        evaluator = _evaluator()
        source = (
            "---\ntitle: Test\n---\n"
            "Use `equals`, `close`, and `create` here."
        )
        translated = (
            "---\ntitle: Test\n---\n"
            "Utilisez `identité`, `close`, et `create` ici."
        )
        result = evaluator.evaluate(
            translated_content=translated,
            source_content=source,
            target_lang="fr",
            output_path=tmp_path / "test.md",
        )
        assert result.passed is False
        assert result.clear_tm_buffer is True
