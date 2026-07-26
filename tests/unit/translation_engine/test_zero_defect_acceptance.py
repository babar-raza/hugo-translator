from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.translation_engine.engine import TranslationEngine
from src.translation_engine.engine_builder import EngineBuilder
from src.translation_engine.models import AcceptedTranslation
from src.translation_engine.write_gate import WriteGateEvaluator, WriteGateResult
from src.translation_engine.validation.post_translation_validator import (
    ValidationDecision,
)


def _accepted(tmp_path: Path) -> AcceptedTranslation:
    return AcceptedTranslation.from_text(
        content="---\ntitle: Hola\n---\nContenido.\n",
        source_content="---\ntitle: Hello\n---\nContent.\n",
        source_path=tmp_path / "en" / "page.md",
        output_path=tmp_path / "es" / "page.md",
        target_lang="es",
        gate_results={
            gate_id: {"passed": True, "action": "test", "error": None}
            for gate_id in range(1, 45)
        },
        campaign_id="pilot",
    )


def test_accepted_translation_is_immutable_and_hashed(tmp_path):
    accepted = _accepted(tmp_path)
    assert accepted.output_sha256
    assert len(accepted.gate_results) == 44
    assert "content" not in accepted.receipt()
    with pytest.raises(FrozenInstanceError):
        accepted.target_lang = "fr"


def test_accepted_translation_hashes_raw_source_bytes(tmp_path):
    source_path = tmp_path / "en" / "page.md"
    source_path.parent.mkdir(parents=True)
    source_bytes = b"---\r\ntitle: Hello\r\n---\r\nContent.\r\n"
    source_path.write_bytes(source_bytes)

    accepted = AcceptedTranslation.from_text(
        content="translated",
        source_content=source_path.read_text(encoding="utf-8"),
        source_path=source_path,
        output_path=tmp_path / "es" / "page.md",
        target_lang="es",
        gate_results={
            gate_id: {"passed": True, "action": "test", "error": None}
            for gate_id in range(1, 45)
        },
    )

    import hashlib

    assert accepted.source_sha256 == hashlib.sha256(source_bytes).hexdigest()


def test_zero_defect_writer_rejects_unaccepted_payload(tmp_path):
    engine = TranslationEngine.__new__(TranslationEngine)
    with pytest.raises(TypeError):
        engine._write_accepted_output("not accepted", MagicMock())


def test_zero_defect_writer_checksums_and_calls_receipt_sink(tmp_path):
    engine = TranslationEngine.__new__(TranslationEngine)
    accepted = _accepted(tmp_path)
    sink = MagicMock()
    engine.campaign_context = {"receipt_sink": sink}

    def write_output(content, output_path, source_path, stats):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")

    engine._write_output = write_output
    engine._write_accepted_output(accepted, MagicMock())

    assert accepted.output_path.read_bytes() == accepted.content
    sink.assert_called_once()


def test_receipt_failure_removes_output(tmp_path):
    engine = TranslationEngine.__new__(TranslationEngine)
    accepted = _accepted(tmp_path)
    engine.campaign_context = {
        "receipt_sink": MagicMock(side_effect=OSError("ledger full"))
    }

    def write_output(content, output_path, source_path, stats):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")

    engine._write_output = write_output
    with pytest.raises(OSError, match="ledger full"):
        engine._write_accepted_output(accepted, MagicMock())
    assert not accepted.output_path.exists()


def test_pre_write_validation_fails_closed_on_validator_exception(tmp_path):
    engine = TranslationEngine.__new__(TranslationEngine)
    engine.parser = MagicMock()
    engine.config = MagicMock()
    engine.output_dir_override = None
    with patch(
        "src.translation_engine.validation.file_placement_validator."
        "FilePlacementValidator.validate",
        side_effect=RuntimeError("validator unavailable"),
    ):
        passed, errors = engine._pre_write_validation(
            content="---\ntitle: Hola\n---\nContenido.\n",
            output_path=tmp_path / "es" / "page.md",
            source_path=tmp_path / "en" / "page.md",
            target_lang="es",
            site_id="docs.aspose.org",
            site_profile=MagicMock(default_source_lang="en"),
        )
    assert passed is False
    assert "unavailable" in errors[0]


def test_warn_gate_is_blocking_under_zero_defect():
    config = MagicMock()
    config.get_config.return_value = {"translation_engine": {}}
    gate = WriteGateEvaluator(
        detector=MagicMock(),
        similarity_tracker=None,
        config=config,
        validation_policy="zero-defect",
    )
    gate.GATE_REGISTRY = [(31, "_gate_partial_script_contamination", "content", "warn")]

    def fail_gate(source, translated, path, result):
        result.passed = False
        result.error = "mixed script"

    gate._build_content_gate_dispatch = MagicMock(
        return_value={"_gate_partial_script_contamination": fail_gate}
    )
    result = WriteGateResult(passed=True)
    gate._run_content_gates(
        "source", "translation", "es", Path("page.md"), None, result
    )
    assert result.passed is False
    assert result.gate_results[31]["passed"] is False


def test_fidelity_pass_evidence_survives_disposable_gate_result():
    config = MagicMock()
    config.get_config.return_value = {"translation_engine": {}}
    gate = WriteGateEvaluator(
        detector=MagicMock(),
        similarity_tracker=None,
        config=config,
        validation_policy="zero-defect",
    )
    gate.GATE_REGISTRY = [(36, "_gate_fidelity_judge", "content", "auto_clean")]

    def pass_fidelity(_source, translated, _path, result):
        result._fidelity_result = {
            "verdict": "pass",
            "score": 0.99,
            "model": "independent-judge",
            "issues": [],
        }
        return translated

    gate._build_content_gate_dispatch = MagicMock(
        return_value={"_gate_fidelity_judge": pass_fidelity}
    )
    result = WriteGateResult(passed=True)

    gate._run_content_gates(
        "source", "translation", "es", Path("page.md"), None, result
    )

    assert result.gate_results[36]["passed"] is True
    assert result._fidelity_result["verdict"] == "pass"
    assert result._fidelity_result["model"] == "independent-judge"


def test_zero_defect_requires_language_detector():
    config = MagicMock()
    config.get_config.return_value = {"translation_engine": {}}
    gate = WriteGateEvaluator(
        detector=None,
        similarity_tracker=None,
        config=config,
        validation_policy="zero-defect",
    )
    result = gate.evaluate(
        translated_content="---\ntitle: Hola\n---\nContenido.\n",
        source_content="---\ntitle: Hello\n---\nContent.\n",
        target_lang="es",
        output_path=Path("page.md"),
    )
    assert result.passed is False
    assert "detector" in result.error


def test_engine_builder_rejects_zero_defect_without_verification():
    with pytest.raises(ValueError, match="requires verification"):
        EngineBuilder(
            config_service=MagicMock(),
            tm=MagicMock(),
            model_loader=MagicMock(),
            validation_policy="zero-defect",
            enable_validation=True,
            enable_verification=False,
        )._init_core_state(MagicMock(), {
            **EngineBuilder(
                config_service=MagicMock(),
                tm=MagicMock(),
                model_loader=MagicMock(),
                validation_policy="zero-defect",
            )._p,
        })


def test_campaign_tm_namespace_binds_config_and_source():
    engine = object.__new__(TranslationEngine)
    engine.campaign_context = {
        "campaign_id": "pilot-v1",
        "config_fingerprint": "abcdef0123456789fedcba",
    }

    first = engine._tm_site_namespace("docs.aspose.org", "content/a.md")
    same = engine._tm_site_namespace("docs.aspose.org", "content/a.md")
    other = engine._tm_site_namespace("docs.aspose.org", "content/b.md")

    assert first == same
    assert first != other
    assert "campaign=pilot-v1" in first
    assert "config=abcdef0123456789" in first


def test_tm_flush_requires_accepted_translation():
    engine = object.__new__(TranslationEngine)
    engine.tm = MagicMock()

    with pytest.raises(TypeError, match="AcceptedTranslation"):
        engine._flush_accepted_tm("raw translation", [{"text": "source"}])

    engine.tm.store.assert_not_called()


def _candidate_acceptance_engine(*, validation_warnings: int = 0):
    engine = object.__new__(TranslationEngine)
    engine.validation_policy = "zero-defect"
    validation = SimpleNamespace(
        issues=[],
        error_count=0,
        warning_count=validation_warnings,
    )
    engine.validation_suite = SimpleNamespace(
        validate_aggregated=MagicMock(return_value=validation)
    )
    engine.decision_engine = SimpleNamespace(
        make_decision=MagicMock(
            return_value=SimpleNamespace(decision=ValidationDecision.ACCEPT)
        )
    )
    engine.config = SimpleNamespace(
        get_site_profile=lambda _site: SimpleNamespace(default_source_lang="en")
    )
    docs = [
        SimpleNamespace(ast=None, body="Source body", frontmatter={"title": "Source"}),
        SimpleNamespace(ast=None, body="Cuerpo", frontmatter={"title": "Destino"}),
    ]
    engine.parser = SimpleNamespace(parse_string=MagicMock(side_effect=docs))
    engine._check_frontmatter_language = MagicMock(return_value=[])
    verification = SimpleNamespace(
        passed=True,
        error_count=0,
        warning_count=0,
        issues=[],
    )
    engine._get_verification_agent = MagicMock(
        return_value=SimpleNamespace(verify=MagicMock(return_value=verification))
    )
    gates = WriteGateResult(
        passed=True,
        cleaned_content="---\ntitle: Destino\n---\nCuerpo.\n",
        gate_results={
            gate_id: {"passed": True, "action": "test", "error": None}
            for gate_id in range(2, 45)
        },
    )
    gates._fidelity_result = {
        "verdict": "pass",
        "score": 1.0,
        "model": "professionalize_llm",
        "issues": [],
    }
    engine._write_gate = SimpleNamespace(
        evaluate_zero_defect=MagicMock(return_value=gates)
    )
    engine._pre_write_validation = MagicMock(return_value=(True, []))
    engine.campaign_context = {
        "campaign_id": "pilot",
        "config_fingerprint": "c" * 64,
    }
    return engine


def test_candidate_byte_acceptance_reruns_all_gates_without_writing(tmp_path):
    engine = _candidate_acceptance_engine()
    source_path = tmp_path / "en" / "page.md"
    output_path = tmp_path / "es" / "page.md"
    candidate = b"---\ntitle: Destino\n---\nCuerpo.\n"

    accepted = engine.accept_candidate_bytes(
        source_bytes=b"---\ntitle: Source\n---\nSource body.\n",
        candidate_bytes=candidate,
        source_path=source_path,
        output_path=output_path,
        target_lang="es",
        site_id="docs.aspose.org",
    )

    assert accepted.content == candidate
    assert len(accepted.gate_results) == 44
    assert all(item["passed"] for item in accepted.gate_results.values())
    assert accepted.model_fingerprint == (
        "receipt-recovery:fidelity=professionalize_llm"
    )
    assert not output_path.exists()


def test_candidate_byte_acceptance_blocks_warning_without_receipt_or_write(tmp_path):
    engine = _candidate_acceptance_engine(validation_warnings=1)
    output_path = tmp_path / "es" / "page.md"

    with pytest.raises(ValueError, match="validation suite"):
        engine.accept_candidate_bytes(
            source_bytes=b"source",
            candidate_bytes=b"---\ntitle: Destino\n---\nCuerpo.\n",
            source_path=tmp_path / "en" / "page.md",
            output_path=output_path,
            target_lang="es",
            site_id="docs.aspose.org",
        )

    engine._write_gate.evaluate_zero_defect.assert_not_called()
    assert not output_path.exists()


def test_candidate_byte_acceptance_rejects_cleaned_byte_drift(tmp_path):
    engine = _candidate_acceptance_engine()
    engine._write_gate.evaluate_zero_defect.return_value.cleaned_content = (
        "---\ntitle: Corregido\n---\nCuerpo.\n"
    )

    with pytest.raises(ValueError, match="fixed-point"):
        engine.accept_candidate_bytes(
            source_bytes=b"source",
            candidate_bytes=b"---\ntitle: Destino\n---\nCuerpo.\n",
            source_path=tmp_path / "en" / "page.md",
            output_path=tmp_path / "es" / "page.md",
            target_lang="es",
            site_id="docs.aspose.org",
        )


def test_candidate_byte_acceptance_reports_gate_id_without_reason_payload(tmp_path):
    engine = _candidate_acceptance_engine()
    failed = WriteGateResult(
        passed=False,
        error="SECRET CANDIDATE-DERIVED REASON",
        gate_results={
            31: {
                "passed": False,
                "action": "warn",
                "error": "SECRET CANDIDATE-DERIVED REASON",
            }
        },
    )
    engine._write_gate.evaluate_zero_defect.return_value = failed

    with pytest.raises(ValueError) as caught:
        engine.accept_candidate_bytes(
            source_bytes=b"source",
            candidate_bytes=b"---\ntitle: Destino\n---\nCuerpo.\n",
            source_path=tmp_path / "en" / "page.md",
            output_path=tmp_path / "es" / "page.md",
            target_lang="es",
            site_id="docs.aspose.org",
        )

    assert "failed_gates=31" in str(caught.value)
    assert "reason_sha256=" in str(caught.value)
    assert "SECRET" not in str(caught.value)
