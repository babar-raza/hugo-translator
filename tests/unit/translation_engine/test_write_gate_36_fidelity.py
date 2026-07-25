"""
Integration tests for write gate 36 (HT-QUALITY-GATES-001 Part 22 / plan 5.4
items 3+5): LLM meaning-fidelity judge.

Registered "auto_clean" (not "warn"/"block") because it must always be able
to write the `translation_fidelity` frontmatter field for high-risk files
regardless of enforcement mode -- shadow-vs-enforce is a config flag read
inside the gate, not the registry action.

judge_fidelity() is patched at its defining module
(src.translation_engine.validation.fidelity_judge) since write_gate.py lazy-
imports it inside the gate method, same as every other lazy-imported
dependency in this file.
"""
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.translation_engine.validation.fidelity_judge import FidelityVerdict
from src.translation_engine.write_gate import WriteGateEvaluator


def _make_gate(fidelity_cfg: dict | None = None) -> WriteGateEvaluator:
    config = MagicMock()
    te_cfg = {"fidelity_judge": fidelity_cfg} if fidelity_cfg is not None else {}
    config.get_config.return_value = {"translation_engine": te_cfg}
    detector = MagicMock()
    detector.detect.return_value = ("de", 0.99)
    return WriteGateEvaluator(
        detector=detector,
        similarity_tracker=MagicMock(),
        config=config,
        force_accept=True,
    )


_SRC = (
    "---\ntitle: ColumnInfo\n---\n"
    "The ColumnInfo class returns the column definition for the table.\n"
    "It exposes several properties for formatting and alignment control.\n"
)
_TGT = (
    "---\ntitle: ColumnInfo\n---\n"
    "Die Klasse ColumnInfo gibt die Spaltendefinition für die Tabelle zurück.\n"
    "Sie stellt mehrere Eigenschaften für Formatierung und Ausrichtung bereit.\n"
)


class TestGate36HighRiskClassification:
    def test_reference_leaf_page_is_high_risk(self):
        path = Path("/content/reference.aspose.org/de/pdf/net/ColumnInfo.md")
        assert WriteGateEvaluator._gate36_is_high_risk(path, None) is True

    def test_reference_index_page_is_not_high_risk(self):
        path = Path("/content/reference.aspose.org/de/pdf/net/_index.md")
        assert WriteGateEvaluator._gate36_is_high_risk(path, None) is False

    def test_kb_family_root_is_high_risk(self):
        path = Path("/content/kb.aspose.org/de/words/_index.md")
        assert WriteGateEvaluator._gate36_is_high_risk(path, None) is True

    def test_kb_leaf_page_is_not_high_risk_without_llm_signal(self):
        path = Path("/content/kb.aspose.org/de/words/how-to-merge.md")
        assert WriteGateEvaluator._gate36_is_high_risk(path, None) is False

    def test_docs_page_is_not_high_risk_without_llm_signal(self):
        path = Path("/content/docs.aspose.org/de/words/getting-started.md")
        assert WriteGateEvaluator._gate36_is_high_risk(path, None) is False

    def test_llm_translated_unit_makes_any_site_high_risk(self):
        """The plan's own correction: 'was this unit LLM-escalated' must be
        usable directly, not inferred from locale/site alone."""
        path = Path("/content/docs.aspose.org/de/words/getting-started.md")
        stats = MagicMock()
        stats.llm_units_translated = 3
        assert WriteGateEvaluator._gate36_is_high_risk(path, stats) is True

    def test_zero_llm_units_is_not_high_risk(self):
        path = Path("/content/docs.aspose.org/de/words/getting-started.md")
        stats = MagicMock()
        stats.llm_units_translated = 0
        assert WriteGateEvaluator._gate36_is_high_risk(path, stats) is False


class TestGate36DisabledByDefault:
    """Safety: this gate can make a real, costed network call. It must never
    fire on an absent/incomplete config -- confirmed against the exact shape
    of config used by 13+ pre-existing write-gate tests (reference.aspose.org
    leaf paths, config={"translation_engine": {}})."""

    @patch("src.translation_engine.validation.fidelity_judge.judge_fidelity")
    def test_absent_fidelity_judge_config_never_calls_llm(self, mock_judge):
        config = MagicMock()
        config.get_config.return_value = {"translation_engine": {}}
        detector = MagicMock()
        detector.detect.return_value = ("de", 0.99)
        gate = WriteGateEvaluator(
            detector=detector, similarity_tracker=MagicMock(), config=config, force_accept=True,
        )
        output_path = Path("/content/reference.aspose.org/de/pdf/net/ColumnInfo.md")

        result = gate.evaluate(_TGT, _SRC, "de", output_path)

        mock_judge.assert_not_called()
        assert result.passed is True

    @patch("src.translation_engine.validation.fidelity_judge.judge_fidelity")
    def test_explicit_enabled_false_never_calls_llm(self, mock_judge):
        gate = _make_gate({"enabled": False})
        output_path = Path("/content/reference.aspose.org/de/pdf/net/ColumnInfo.md")

        gate.evaluate(_TGT, _SRC, "de", output_path)

        mock_judge.assert_not_called()


class TestGate36NotHighRisk:
    @patch("src.translation_engine.validation.fidelity_judge.judge_fidelity")
    def test_low_risk_file_skips_llm_call_even_when_enabled(self, mock_judge):
        gate = _make_gate({"enabled": True})
        output_path = Path("/content/docs.aspose.org/de/words/getting-started.md")

        result = gate.evaluate(_TGT, _SRC, "de", output_path)

        mock_judge.assert_not_called()
        assert result.passed is True


class TestGate36ShadowMode:
    @patch("src.translation_engine.validation.fidelity_judge.judge_fidelity")
    def test_fail_verdict_writes_field_but_does_not_block(self, mock_judge, caplog):
        """Part 6 item 3: shadow mode logs/writes, never blocks, until
        agreement rate against human close-reading is measured."""
        mock_judge.return_value = FidelityVerdict(
            score=0.1, verdict="fail",
            issues=["'core' mistranslated as the country 'Korea'"],
            model="professionalize_llm", raw_response='{"score": 1}',
        )
        gate = _make_gate({"enabled": True, "enforce": False})
        output_path = Path("/content/reference.aspose.org/de/pdf/net/ColumnInfo.md")

        result = gate.evaluate(_TGT, _SRC, "de", output_path)

        mock_judge.assert_called_once()
        assert result.passed is True  # shadow mode: never blocks
        assert result.cleaned_content is not None
        assert "translation_fidelity" in result.cleaned_content
        assert "fail" in result.cleaned_content

    @patch("src.translation_engine.validation.fidelity_judge.judge_fidelity")
    def test_pass_verdict_writes_field(self, mock_judge):
        mock_judge.return_value = FidelityVerdict(
            score=0.95, verdict="pass", issues=[], model="professionalize_llm",
            raw_response='{"score": 9.5}',
        )
        gate = _make_gate({"enabled": True})
        output_path = Path("/content/reference.aspose.org/de/pdf/net/ColumnInfo.md")

        result = gate.evaluate(_TGT, _SRC, "de", output_path)

        assert result.passed is True
        assert result.cleaned_content is not None
        assert "translation_fidelity" in result.cleaned_content
        assert "pass" in result.cleaned_content


class TestGate36EnforceMode:
    @patch("src.translation_engine.validation.fidelity_judge.judge_fidelity")
    def test_fail_verdict_blocks_when_enforced(self, mock_judge):
        mock_judge.return_value = FidelityVerdict(
            score=0.1, verdict="fail",
            issues=["factual reversal: 'supported' translated as 'not supported'"],
            model="professionalize_llm", raw_response='{"score": 1}',
        )
        gate = _make_gate({"enabled": True, "enforce": True, "block_threshold": 0.5})
        output_path = Path("/content/reference.aspose.org/de/pdf/net/ColumnInfo.md")

        result = gate.evaluate(_TGT, _SRC, "de", output_path)

        assert result.passed is False
        assert "GATE36" in result.error
        assert result.retranslate_queued is True
        assert (output_path, "de") in result.retranslate_paths

    @patch("src.translation_engine.validation.fidelity_judge.judge_fidelity")
    def test_warn_verdict_does_not_block_even_when_enforced(self, mock_judge):
        mock_judge.return_value = FidelityVerdict(
            score=0.6, verdict="warn", issues=["awkward phrasing"],
            model="professionalize_llm", raw_response='{"score": 6}',
        )
        gate = _make_gate({"enabled": True, "enforce": True})
        output_path = Path("/content/reference.aspose.org/de/pdf/net/ColumnInfo.md")

        result = gate.evaluate(_TGT, _SRC, "de", output_path)

        assert result.passed is True

    @patch("src.translation_engine.validation.fidelity_judge.judge_fidelity")
    def test_pass_verdict_does_not_block_when_enforced(self, mock_judge):
        mock_judge.return_value = FidelityVerdict(
            score=0.95, verdict="pass", issues=[], model="professionalize_llm",
            raw_response='{"score": 9.5}',
        )
        gate = _make_gate({"enabled": True, "enforce": True})
        output_path = Path("/content/reference.aspose.org/de/pdf/net/ColumnInfo.md")

        result = gate.evaluate(_TGT, _SRC, "de", output_path)

        assert result.passed is True


class TestGate36JudgeUnavailable:
    @patch("src.translation_engine.validation.fidelity_judge.judge_fidelity")
    def test_none_verdict_skips_silently(self, mock_judge):
        """judge_fidelity fails open (returns None) on any internal error --
        the gate must not write a field or block on a missing verdict."""
        mock_judge.return_value = None
        gate = _make_gate({"enabled": True, "enforce": True})
        output_path = Path("/content/reference.aspose.org/de/pdf/net/ColumnInfo.md")

        result = gate.evaluate(_TGT, _SRC, "de", output_path)

        assert result.passed is True
        assert result.cleaned_content is None


class TestGate36ShortBody:
    @patch("src.translation_engine.validation.fidelity_judge.judge_fidelity")
    def test_short_body_skips_llm_call(self, mock_judge):
        gate = _make_gate({"enabled": True})
        src = "---\ntitle: X\n---\nHi.\n"
        tgt = "---\ntitle: X\n---\nHallo.\n"
        output_path = Path("/content/reference.aspose.org/de/pdf/net/X.md")

        gate.evaluate(tgt, src, "de", output_path)

        mock_judge.assert_not_called()


class TestGate36SkipsWhenAlreadyFailed:
    """Gate 36 is registered 'auto_clean', so the dispatch loop's block-gate
    short-circuit (if not result.passed: continue) does not apply to it --
    without an explicit internal guard it would still spend a real LLM call
    on an already-rejected file AND overwrite the earlier gate's
    result.error with its own message, hiding the true root cause."""

    @patch("src.translation_engine.validation.fidelity_judge.judge_fidelity")
    def test_skips_llm_call_when_earlier_gate_already_failed(self, mock_judge):
        # Trigger Gate 13 (EU hallucination) to fail first -- any earlier
        # blocking gate works for this test; the point is result.passed is
        # already False by the time Gate 36 runs.
        src = "---\ntitle: X\n---\nOrdinary product documentation.\n"
        tgt = (
            "---\ntitle: X\n---\n"
            "This section references the European Commission and GDPR "
            "cookie consent requirements unrelated to the source content.\n"
        )
        gate = _make_gate({"enabled": True, "enforce": True})
        output_path = Path("/content/reference.aspose.org/de/pdf/net/ColumnInfo.md")

        result = gate.evaluate(tgt, src, "de", output_path)

        assert result.passed is False
        mock_judge.assert_not_called()
        assert "GATE36" not in (result.error or "")


class TestGate36TranslationStatsThreaded:
    @patch("src.translation_engine.validation.fidelity_judge.judge_fidelity")
    def test_translation_stats_param_reaches_classification(self, mock_judge):
        """A docs.aspose.org file wouldn't normally be high-risk, but a
        translation_stats showing LLM-escalated units must make it so --
        proves the parameter is actually threaded end-to-end through
        evaluate() -> _run_content_gates() -> the gate itself, not just
        unit-testable in isolation."""
        mock_judge.return_value = FidelityVerdict(
            score=0.95, verdict="pass", issues=[], model="professionalize_llm",
            raw_response="{}",
        )
        gate = _make_gate({"enabled": True})
        output_path = Path("/content/docs.aspose.org/de/words/getting-started.md")
        stats = MagicMock()
        stats.llm_units_translated = 1

        gate.evaluate(_TGT, _SRC, "de", output_path, translation_stats=stats)

        mock_judge.assert_called_once()
