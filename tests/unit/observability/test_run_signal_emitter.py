"""Tests for TC-AGT-01: Run signal emitter."""

import json
import tempfile
from pathlib import Path

import pytest

from src.observability.run_signal_emitter import (
    Blocker,
    FileStats,
    LLMUsage,
    RunSignal,
    RunStatus,
    RunVerdict,
    ProductionSafety,
    ValidatorStats,
    build_signal_from_run_stats,
    compute_autonomy_score,
    compute_verdict,
    emit_run_signal,
)


class TestRunSignalSchema:
    """Test the RunSignal Pydantic model."""

    def test_default_signal(self):
        """Default signal has valid structure."""
        signal = RunSignal()
        assert signal.run_id  # UUID generated
        assert signal.timestamp  # ISO timestamp
        assert signal.mission == "Content Translation"
        assert signal.status == RunStatus.COMPLETED
        assert signal.verdict == RunVerdict.CLEAN_RUN
        assert signal.production_safety == ProductionSafety.SAFE
        assert signal.autonomy_score == 1.0

    def test_full_signal(self):
        """Full signal with all fields populated."""
        signal = RunSignal(
            run_id="test-run-123",
            site_id="docs.aspose.net.words",
            status=RunStatus.COMPLETED,
            files=FileStats(processed=10, accepted=8, rejected=1, retried=1),
            validators=ValidatorStats(run=50, passed=48, failed=2),
            llm_usage=LLMUsage(calls=3, tokens=1500, model="professionalize_llm", dry_run=False),
            evidence_path="data/metrics/agent_evidence/2026-06-13",
            autonomy_score=0.95,
            blockers=[Blocker(id="BLK-001", type="external", description="API timeout")],
            verdict=RunVerdict.DEGRADED_RUN,
            next_action="Retry failed files",
        )
        assert signal.files.processed == 10
        assert signal.files.rejected == 1
        assert len(signal.blockers) == 1
        assert signal.blockers[0].id == "BLK-001"

    def test_signal_to_json(self):
        """Signal serializes to valid JSON."""
        signal = RunSignal(
            run_id="json-test",
            site_id="test.site",
        )
        data = signal.model_dump(mode="json")
        json_str = json.dumps(data)
        parsed = json.loads(json_str)
        assert parsed["run_id"] == "json-test"
        assert parsed["status"] == "completed"

    def test_all_required_fields_present(self):
        """Signal JSON contains all required schema fields."""
        signal = RunSignal(site_id="test")
        data = signal.model_dump(mode="json")
        required_fields = [
            "run_id",
            "timestamp",
            "mission",
            "site_id",
            "status",
            "files",
            "validators",
            "verdict",
            "autonomy_score",
            "confidence",
            "production_safety",
        ]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"


class TestComputeVerdict:
    """Test verdict computation from file stats."""

    def test_clean_run(self):
        """All files accepted -> CLEAN_RUN."""
        assert compute_verdict(FileStats(processed=10, accepted=10)) == RunVerdict.CLEAN_RUN

    def test_degraded_run_with_rejections(self):
        """Some rejections -> DEGRADED_RUN."""
        assert (
            compute_verdict(FileStats(processed=10, accepted=8, rejected=2))
            == RunVerdict.DEGRADED_RUN
        )

    def test_degraded_run_with_retries(self):
        """Some retries -> DEGRADED_RUN."""
        assert (
            compute_verdict(FileStats(processed=10, accepted=10, retried=2))
            == RunVerdict.DEGRADED_RUN
        )

    def test_failed_run(self):
        """All rejected -> FAILED_RUN."""
        assert (
            compute_verdict(FileStats(processed=5, accepted=0, rejected=5)) == RunVerdict.FAILED_RUN
        )

    def test_blocked(self):
        """No files processed -> BLOCKED."""
        assert compute_verdict(FileStats(processed=0)) == RunVerdict.BLOCKED


class TestComputeAutonomyScore:
    """Test autonomy score computation."""

    def test_no_interventions(self):
        assert compute_autonomy_score(0, 10) == 1.0

    def test_all_interventions(self):
        assert compute_autonomy_score(10, 10) == 0.0

    def test_partial_interventions(self):
        assert compute_autonomy_score(2, 10) == 0.8

    def test_zero_decisions(self):
        assert compute_autonomy_score(0, 0) == 1.0


class TestEmitRunSignal:
    """Test signal file emission."""

    def test_emit_creates_file(self):
        """Emit writes a valid JSON file."""
        signal = RunSignal(run_id="emit-test-001", site_id="test")
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            path = emit_run_signal(signal, Path(tmpdir))
            assert path.exists()
            assert path.name == "run-signal-emit-test-001.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            assert data["run_id"] == "emit-test-001"
            assert data["site_id"] == "test"

    def test_emit_creates_parent_dirs(self):
        """Emit creates parent directories if needed."""
        signal = RunSignal(run_id="dir-test", site_id="test")
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            nested = Path(tmpdir) / "deep" / "signals"
            path = emit_run_signal(signal, nested)
            assert path.exists()


class TestBuildSignalFromRunStats:
    """Test building signals from translation run statistics."""

    def test_build_from_stats(self):
        """Build signal from typical run stats dict."""
        stats = {
            "files_processed": 20,
            "translated": 18,
            "rejected": 1,
            "retried": 1,
            "validators_run": 100,
            "validators_passed": 95,
            "validators_failed": 5,
        }
        signal = build_signal_from_run_stats(
            site_id="docs.aspose.net.words",
            stats=stats,
            llm_calls=3,
            llm_tokens=2000,
            llm_model="professionalize_llm",
        )
        assert signal.site_id == "docs.aspose.net.words"
        assert signal.files.processed == 20
        assert signal.files.accepted == 18
        assert signal.verdict == RunVerdict.DEGRADED_RUN
        assert signal.llm_usage.calls == 3

    def test_build_empty_stats(self):
        """Build signal from empty stats."""
        signal = build_signal_from_run_stats(site_id="test", stats={})
        assert signal.files.processed == 0
        assert signal.verdict == RunVerdict.BLOCKED
        assert signal.status == RunStatus.ABORTED
