"""Tests for metrics evidence sidecar, markers, and ledger."""

from __future__ import annotations

import json

import pytest

from src.observability.metrics_evidence import SCHEMA_VERSION, EvidenceWriter, compute_payload_hash


@pytest.fixture
def ew(tmp_path):
    return EvidenceWriter(
        evidence_dir=str(tmp_path / "evidence"),
        ledger_file=str(tmp_path / "evidence" / "ledger.jsonl"),
    )


def _sample_payload() -> dict:
    return {
        "timestamp": "2026-05-06T14:30:00+00:00",
        "agent_name": "Hugo Translator",
        "agent_owner": "Babar Raza",
        "job_type": "Test",
        "run_id": "run-001",
        "status": "success",
        "product": "Aspose.Words",
        "platform": ".NET",
        "website": "aspose.net",
        "website_section": "Docs",
        "item_name": "Tested Words Docs — 2 files",
        "items_discovered": 2,
        "items_failed": 0,
        "items_succeeded": 2,
        "run_duration_ms": 1000,
        "token_usage": 100,
        "api_calls_count": 2,
    }


def _sidecar_kwargs(payload: dict | None = None) -> dict:
    payload = payload or _sample_payload()
    return {
        "segment_run_id": "seg-001",
        "ids": {"segment_run_id": "seg-001", "stable_work_slice_id": "ws-001"},
        "execution_context": {"is_ci": False, "hostname": "test-host"},
        "scope": {
            "site_id": "docs.aspose.net",
            "source_site_domain": "aspose.net",
            "website": "aspose.net",
        },
        "llm_provider": {
            "provider_name": "openai_compatible",
            "endpoint_host": "llm.professionalize.com",
            "is_professionalize": True,
        },
        "posted_payload": payload,
        "call_accounting": {"attempted_provider_calls": 2, "completed_provider_calls": 2},
        "items_detail": {"total_files_selected": 2},
    }


class TestPayloadHash:
    def test_deterministic(self):
        p = _sample_payload()
        assert compute_payload_hash(p) == compute_payload_hash(p)

    def test_different_payloads_differ(self):
        p1 = _sample_payload()
        p2 = _sample_payload()
        p2["status"] = "failure"
        assert compute_payload_hash(p1) != compute_payload_hash(p2)


class TestPostedMarkers:
    def test_not_posted_initially(self, ew):
        assert ew.is_already_posted("seg-001") is False

    def test_marker_created(self, ew):
        ew.write_posted_marker("seg-001")
        assert ew.is_already_posted("seg-001") is True

    def test_different_ids_independent(self, ew):
        ew.write_posted_marker("seg-001")
        assert ew.is_already_posted("seg-002") is False


class TestSidecar:
    def test_pre_post_creates_file(self, ew):
        path = ew.write_pre_post_sidecar(**_sidecar_kwargs(), dry_run=False)
        assert path is not None
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["schema_version"] == SCHEMA_VERSION
        assert data["posting"]["status"] == "posting_in_progress"

    def test_dry_run_sidecar_status(self, ew):
        path = ew.write_pre_post_sidecar(**_sidecar_kwargs(), dry_run=True)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["posting"]["status"] == "dry_run"
        assert data["posting"]["dry_run"] is True

    def test_sidecar_has_llm_provider(self, ew):
        path = ew.write_pre_post_sidecar(**_sidecar_kwargs(), dry_run=True)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["llm_provider"]["is_professionalize"] is True
        assert "endpoint_host" in data["llm_provider"]

    def test_posted_payload_has_17_keys(self, ew):
        path = ew.write_pre_post_sidecar(**_sidecar_kwargs(), dry_run=True)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data["posted_payload"]) == 17

    def test_source_site_domain_preserved(self, ew):
        path = ew.write_pre_post_sidecar(**_sidecar_kwargs(), dry_run=True)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["scope"]["source_site_domain"] == "aspose.net"

    def test_update_sidecar(self, ew):
        ew.write_pre_post_sidecar(**_sidecar_kwargs(), dry_run=False)
        ok = ew.update_sidecar_post_result("seg-001", "posted", response_code=200)
        assert ok is True

    def test_update_missing_sidecar_returns_false(self, ew):
        ok = ew.update_sidecar_post_result("nonexistent", "posted")
        assert ok is False


class TestLedger:
    def test_append_creates_file(self, ew):
        ew.append_ledger("seg-001", "test_event")
        assert ew.ledger_file.exists()
        lines = ew.ledger_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["segment_run_id"] == "seg-001"
        assert entry["event"] == "test_event"

    def test_append_multiple(self, ew):
        ew.append_ledger("seg-001", "event1")
        ew.append_ledger("seg-001", "event2")
        lines = ew.ledger_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2


class TestFullLifecycle:
    def test_dry_run_lifecycle(self, ew):
        result = ew.full_post_lifecycle(**_sidecar_kwargs(), dry_run=True)
        assert result["action"] == "dry_run"
        assert result["sidecar_path"] is not None

    def test_duplicate_skipped(self, ew):
        ew.write_posted_marker("seg-001")
        result = ew.full_post_lifecycle(**_sidecar_kwargs(), dry_run=False)
        assert result["action"] == "skipped_duplicate"

    def test_post_success_records(self, ew):
        ew.full_post_lifecycle(**_sidecar_kwargs(), dry_run=False)
        ew.record_post_success("seg-001", 200)
        assert ew.is_already_posted("seg-001") is True

    def test_post_failure_no_marker(self, ew):
        ew.full_post_lifecycle(**_sidecar_kwargs(), dry_run=False)
        ew.record_post_failure("seg-001", "HTTP 500")
        assert ew.is_already_posted("seg-001") is False
