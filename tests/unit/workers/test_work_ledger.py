"""TC-APT-003: work ledger schema, content-free invariant, queries, event replay."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src.workers import work_ledger as wl

SHA = "a" * 64


def _row(**over):
    base = {
        "site_id": "docs.aspose.org",
        "family": "cells",
        "platform": "net",
        "source_path": "content/docs.aspose.org/en/cells/net/a.md",
        "target_lang": "de",
        "expected_output_path": "content/docs.aspose.org/de/cells/net/a.md",
        "source_sha256": SHA,
        "profile_fingerprint": "p" * 64,
        "protection_fingerprint": "q" * 64,
        "target_exists": False,
        "eligibility_state": "MISSING_TRANSLATION",
        "eligibility_reason_code": "target_absent",
    }
    base.update(over)
    return base


@pytest.fixture()
def ledger(tmp_path: Path):
    with wl.WorkLedger(tmp_path / "work_ledger.sqlite3") as led:
        yield led


def test_schema_matches_plan_14_1(ledger):
    cols = {r[1] for r in ledger._conn.execute("PRAGMA table_info(page_language_work)")}
    assert cols == set(wl.COLUMNS)
    idx = {r[1] for r in ledger._conn.execute("PRAGMA index_list(page_language_work)")}
    assert {"ux_plw_cell", "ix_plw_state", "ix_plw_site_lang"} <= idx


def test_work_id_is_deterministic_and_unique_per_cell(ledger):
    a = ledger.upsert(_row())
    assert a["work_id"] == wl.work_id_for("docs.aspose.org", _row()["source_path"], "de")
    ledger.upsert(
        _row(target_lang="fr", expected_output_path="content/docs.aspose.org/fr/cells/net/a.md")
    )
    assert ledger.total() == 2
    # re-upsert same cell updates in place (exactly one row per cell)
    ledger.upsert(
        _row(
            eligibility_state="UP_TO_DATE",
            eligibility_reason_code="x",
            target_exists=True,
            target_sha256="b" * 64,
        )
    )
    assert ledger.total() == 2
    assert ledger.duplicate_cells() == 0
    assert (
        ledger.get_cell("docs.aspose.org", _row()["source_path"], "de")["eligibility_state"]
        == "UP_TO_DATE"
    )


def test_content_free_invariant_rejects_nested_content_keys(ledger):
    bad = _row(
        validation_results=json.dumps({"gates": {"12": {"passed": True, "content": "Hallo Welt"}}})
    )
    with pytest.raises(wl.WorkLedgerError):
        ledger.upsert(bad)
    bad2 = _row(validation_results={"a": [{"translated_content": "x"}]})
    with pytest.raises(wl.WorkLedgerError):
        ledger.upsert(bad2)
    ok = _row(validation_results={"1": {"passed": True, "action": "verification", "error": None}})
    ledger.upsert(ok)
    assert ledger.total() == 1


def test_invalid_enums_and_hashes_rejected(ledger):
    with pytest.raises(wl.WorkLedgerError):
        ledger.upsert(_row(eligibility_state="MAYBE"))
    with pytest.raises(wl.WorkLedgerError):
        ledger.upsert(_row(provenance_kind="TRUST_ME"))
    with pytest.raises(wl.WorkLedgerError):
        ledger.upsert(_row(source_sha256="nothex"))
    with pytest.raises(wl.WorkLedgerError):
        ledger.upsert(_row(claude_review_note="n" * 501))
    with pytest.raises(wl.WorkLedgerError):
        ledger.upsert(_row(bogus_column=1))


def test_query_counts_and_state_transition(ledger):
    ledger.upsert(_row())
    ledger.upsert(
        _row(
            target_lang="ja",
            expected_output_path="x/ja.md",
            eligibility_state="UNKNOWN_PROVENANCE",
            eligibility_reason_code="no_trustworthy_provenance",
            target_exists=True,
            target_sha256="c" * 64,
        )
    )
    ledger.upsert(
        _row(
            site_id="kb.aspose.org",
            expected_output_path="y.md",
            eligibility_state="EXCLUDED_BY_PROFILE",
            eligibility_reason_code="locale_not_in_profile_allowlist",
            target_lang="bg",
        )
    )
    assert ledger.counts_by_state() == {
        "EXCLUDED_BY_PROFILE": 1,
        "MISSING_TRANSLATION": 1,
        "UNKNOWN_PROVENANCE": 1,
    }
    assert ledger.counts_by_site_state()["kb.aspose.org"] == {"EXCLUDED_BY_PROFILE": 1}
    assert [
        r["target_lang"]
        for r in ledger.query(
            site_id="docs.aspose.org",
            eligibility_state=["MISSING_TRANSLATION", "UNKNOWN_PROVENANCE"],
        )
    ] == ["de", "ja"]
    wid = wl.work_id_for("docs.aspose.org", _row()["source_path"], "de")
    ledger.set_state(
        wid, "UP_TO_DATE", "accepted", output_commit_ref="abc123", claude_review_result="APPROVED"
    )
    row = ledger.get(wid)
    assert row["eligibility_state"] == "UP_TO_DATE" and row["output_commit_ref"] == "abc123"


def test_event_log_written_and_replay_rebuilds_table(ledger, tmp_path):
    ledger.upsert(_row(), reason="backfill")
    wid = wl.work_id_for("docs.aspose.org", _row()["source_path"], "de")
    ledger.set_state(wid, "SOURCE_CHANGED", "receipt_source_drift")
    events = [json.loads(l) for l in ledger.events_path.read_text(encoding="utf-8").splitlines()]
    assert [e["event"] for e in events] == ["insert", "update"]
    assert events[0]["reason"] == "backfill"
    assert not any(wl._contains_forbidden_key(e["row"]) for e in events)
    rebuilt = wl.WorkLedger.replay_events(ledger.events_path, tmp_path / "rebuilt.sqlite3")
    try:
        assert rebuilt.total() == 1
        assert rebuilt.get(wid)["eligibility_state"] == "SOURCE_CHANGED"
    finally:
        rebuilt.close()


def test_unique_cell_index_enforced_at_sqlite_level(ledger):
    ledger.upsert(_row())
    with pytest.raises(sqlite3.IntegrityError):
        ledger._conn.execute(
            "INSERT INTO page_language_work (work_id, site_id, source_path, target_lang, expected_output_path, "
            "source_sha256, profile_fingerprint, protection_fingerprint, target_exists, eligibility_state, "
            "eligibility_reason_code, created_at, updated_at) VALUES ('other', 'docs.aspose.org', ?, 'de', 'x', ?, 'p', 'q', 0, "
            "'MISSING_TRANSLATION', 'r', 't', 't')",
            (_row()["source_path"], SHA),
        )


def test_metadata_path_for_site_is_per_site():
    assert (
        wl.metadata_path_for_site("docs.aspose.org", Path("m")).as_posix()
        == "m/docs.aspose.org/.translation_metadata.json"
    )
