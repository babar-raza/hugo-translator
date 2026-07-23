"""
Integration tests for write gate 37 (HT-QUALITY-GATES-001 Phase 8, Tier C
#12): TM-collision cross-context metadata contamination -- a real-time port
of scripts/quality/audit_tm_collision.py's already-proven detection logic.

Ships "warn" per this registry's established rollout convention (see Gate
28/29's history in write_gate.py) -- no clean-sample false-positive check
has run yet for the write-gate context specifically.
"""
import logging
from pathlib import Path
from unittest.mock import MagicMock

from src.translation_engine.write_gate import WriteGateEvaluator


def _make_gate(force_accept: bool = True) -> WriteGateEvaluator:
    config = MagicMock()
    config.get_config.return_value = {"translation_engine": {}}
    detector = MagicMock()
    detector.detect.return_value = ("es", 0.99)
    return WriteGateEvaluator(
        detector=detector,
        similarity_tracker=MagicMock(),
        config=config,
        force_accept=force_accept,
    )


class TestGateTmCollision:
    def test_matching_identifier_is_silent(self, caplog):
        src = (
            "---\ntitle: Algorithm\ndescription: \"`Algorithm` enum with 3 values\"\n---\n"
            "Body text about the Algorithm enum.\n"
        )
        tr = (
            "---\ntitle: Algorithm\ndescription: \"`Algorithm` enum con 3 valores\"\n---\n"
            "Texto sobre la enumeracion Algorithm.\n"
        )
        gate = _make_gate()
        output_path = Path("/content/reference.aspose.org/es/pdf/java/Algorithm.md")

        with caplog.at_level(logging.WARNING):
            gate.evaluate(tr, src, "es", output_path)

        assert not any("GATE37" in r.message for r in caplog.records)

    def test_collided_identifier_is_flagged(self, caplog):
        """Pinned real shape: a description naming a DIFFERENT class than
        the file's own title is the TM-key-collision signature confirmed
        across the historical corpus by audit_tm_collision.py."""
        src = (
            "---\ntitle: Algorithm\ndescription: \"`Algorithm` enum with 3 values\"\n---\n"
            "Body text about the Algorithm enum.\n"
        )
        tr = (
            "---\ntitle: Algorithm\ndescription: \"`PsStack` enum with 3 values\"\n---\n"
            "Texto sobre la enumeracion.\n"
        )
        gate = _make_gate()
        output_path = Path("/content/reference.aspose.org/es/pdf/java/Algorithm.md")

        with caplog.at_level(logging.WARNING):
            result = gate.evaluate(tr, src, "es", output_path)

        # "warn" tier: evaluate() (via _run_content_gates) runs a warn gate
        # against a DISPOSABLE, discarded result, so production callers
        # correctly never see this block a write (mirrors Gate 31-35's
        # established pattern) -- the gate still logs, which is what this
        # asserts. Note this disposable-result behavior is specific to
        # evaluate()/_run_content_gates (the production write path); the
        # audit sweep and the healer's gate-rerun path instead call
        # run_all_content_gates(), which gives every gate -- warn-tier
        # included -- a REAL, non-discarded per-gate result (see the next
        # test and write_gate.py's run_all_content_gates docstring for why
        # that distinction is load-bearing, not stylistic).
        assert any("GATE37" in r.message for r in caplog.records)

    def test_run_all_content_gates_gives_a_real_non_discarded_result_for_a_warn_gate(self):
        """Regression test for a bug found during this session's independent
        verification pass: unit_heal.py's gate-rerun healing path originally
        called evaluate() to check whether a queued gate finding was still
        real -- but evaluate() discards warn-tier verdicts, so it ALWAYS
        reported "still passing" for gate 37 (and every other warn-tier
        gate: 31-35, 38-43) regardless of the actual content, silently
        reproducing root cause RC2 through a different mechanism.
        run_all_content_gates() is the fix: it must return this gate's REAL
        failing verdict, not a disposable one."""
        src = (
            "---\ntitle: Algorithm\ndescription: \"`Algorithm` enum with 3 values\"\n---\n"
            "Body text.\n"
        )
        tr = (
            "---\ntitle: Algorithm\ndescription: \"`PsStack` enum with 3 values\"\n---\n"
            "Texto.\n"
        )
        gate = _make_gate()
        results, final_content = gate.run_all_content_gates(src, tr, "es", Path("Algorithm.md"))

        assert results[37].passed is False
        assert "PsStack" in results[37].error
        # No auto_clean gate touches this content, so nothing should change.
        assert final_content == tr

    def test_direct_gate_call_flags_collision(self):
        from src.translation_engine.write_gate import WriteGateResult

        src = (
            "---\ntitle: Algorithm\ndescription: \"`Algorithm` enum with 3 values\"\n---\n"
            "Body text.\n"
        )
        tr = (
            "---\ntitle: Algorithm\ndescription: \"`PsStack` enum with 3 values\"\n---\n"
            "Texto.\n"
        )
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_tm_collision(src, tr, Path("Algorithm.md"), result)

        assert result.passed is False
        assert "expected=`Algorithm`" in result.error
        assert "found=`PsStack`" in result.error

    def test_summary_field_collision_also_flagged(self):
        from src.translation_engine.write_gate import WriteGateResult

        src = (
            "---\ntitle: Algorithm\ndescription: \"`Algorithm` enum with 3 values\"\n---\n"
            "Body text.\n"
        )
        tr = (
            "---\ntitle: Algorithm\ndescription: \"`Algorithm` enum con 3 valores\"\n"
            "summary: \"`PsStack` enum\"\n---\nTexto.\n"
        )
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_tm_collision(src, tr, Path("Algorithm.md"), result)

        assert result.passed is False
        assert "field=summary" in result.error

    def test_non_identifier_title_page_is_skipped(self):
        """Pages that aren't the single-identifier API-reference template
        (e.g. an ordinary title with spaces) must not be flagged -- this
        detector's scope is deliberately narrow, matching
        audit_tm_collision.py's own en_title regex guard."""
        from src.translation_engine.write_gate import WriteGateResult

        src = (
            "---\ntitle: Getting Started Guide\ndescription: \"An intro guide\"\n---\n"
            "Body text.\n"
        )
        tr = (
            "---\ntitle: Guia de Inicio\ndescription: \"`SomeOtherClass` enum\"\n---\n"
            "Texto.\n"
        )
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_tm_collision(src, tr, Path("guide.md"), result)

        assert result.passed is True

    def test_en_source_not_following_template_is_skipped(self):
        """EN source's own description doesn't name its own title -- this
        file was never the strict API-reference template to begin with, so
        skip (avoids false positives on non-template pages that merely
        happen to have a bare-word title)."""
        from src.translation_engine.write_gate import WriteGateResult

        src = (
            "---\ntitle: Algorithm\ndescription: \"A general overview page\"\n---\n"
            "Body text.\n"
        )
        tr = (
            "---\ntitle: Algorithm\ndescription: \"`PsStack` enum\"\n---\n"
            "Texto.\n"
        )
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_tm_collision(src, tr, Path("Algorithm.md"), result)

        assert result.passed is True

    def test_force_accept_does_not_bypass_content_gate(self):
        """Content gates 9-37 run unconditionally regardless of
        force_accept, per this registry's established convention (see
        Gates 9+'s docstring in evaluate())."""
        from src.translation_engine.write_gate import WriteGateResult

        src = (
            "---\ntitle: Algorithm\ndescription: \"`Algorithm` enum with 3 values\"\n---\n"
            "Body text.\n"
        )
        tr = (
            "---\ntitle: Algorithm\ndescription: \"`PsStack` enum with 3 values\"\n---\n"
            "Texto.\n"
        )
        gate = _make_gate(force_accept=True)
        result = WriteGateResult(passed=True)
        gate._gate_tm_collision(src, tr, Path("Algorithm.md"), result)

        assert result.passed is False
