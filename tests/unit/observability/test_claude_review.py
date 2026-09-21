"""TC-APT-012: Claude review protocol -- schema, queues, persistence, and the section-10 STOP trigger."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.observability import claude_review as cr


def _result(**over) -> cr.ClaudeReviewResult:
    base = dict(
        review_id="rev-1",
        campaign_id="camp",
        batch_id="b1",
        source_path="content/docs.aspose.org/en/cells/net/a.md",
        output_path="content/docs.aspose.org/de/cells/net/a.md",
        target_lang="de",
        source_sha256="a" * 64,
        output_sha256="b" * 64,
        reviewed_at="2026-09-02T00:00:00+00:00",
        verdict="APPROVE",
        confidence=0.9,
    )
    base.update(over)
    return cr.ClaudeReviewResult(**base)


def test_schema_matches_plan_9_3_and_ledger_pointer_is_redacted():
    result = _result(
        issues=[
            cr.ClaudeReviewIssue(
                category="meaning_inversion",
                severity="critical",
                description="negation dropped",
                gate_id_correlate=42,
                unit_fingerprint="deadbeef",
            )
        ],
        verdict="REJECT_ISOLATED",
    )
    assert result.is_rejection is True
    pointer = result.ledger_pointer()
    assert set(pointer) == {"review_id", "verdict", "confidence", "reviewed_at", "issue_count"}
    assert pointer["issue_count"] == 1
    assert "description" not in str(pointer) and "negation" not in str(pointer)  # content-free


def test_confidence_is_bounded():
    with pytest.raises(Exception):
        _result(confidence=1.5)


def test_blocked_external_is_explicit_never_a_silent_pass():
    result = cr.blocked_external(
        campaign_id="camp",
        batch_id="b1",
        source_path="s.md",
        output_path="o.md",
        target_lang="ar",
        source_sha256="a" * 64,
        output_sha256="b" * 64,
        reason="source unreadable from the reviewing session",
        recommended_action="re-run the review from a session with content-repo access",
    )
    assert result.verdict == "BLOCKED_EXTERNAL" and result.confidence == 0.0
    assert result.issues[0].severity == "critical" and result.recommended_action
    assert result.is_rejection is False  # it blocks, but it is not a quality rejection


@pytest.mark.parametrize("gate", sorted(cr.UNVALIDATED_GATE_IDS))
def test_every_unvalidated_gate_enters_the_block_queue(gate):
    assert cr.is_block_queue_failure({"gate": gate}) is True


def test_validated_gate_and_provider_failure_classification():
    assert cr.is_block_queue_failure({"gate": 12}) is False
    assert cr.is_block_queue_failure({"gate": "llm_provider_failure"}) is True
    assert cr.is_block_queue_failure({"gate": None, "reason": "llm_provider_failure"}) is True
    assert cr.is_block_queue_failure({"gate": "36"}) is False


def test_block_queue_is_batch_size_one_and_deduplicated():
    failures = [
        {"gate": 31, "output_path": "o1.md", "target_lang": "de"},
        {"gate": 31, "output_path": "o1.md", "target_lang": "de"},  # duplicate
        {"gate": 44, "output_path": "o2.md", "target_lang": "ja"},
        {"gate": 12, "output_path": "o3.md", "target_lang": "fr"},  # validated gate -> not queued
    ]
    queue = cr.build_block_queue(failures)
    assert [q["output_path"] for q in queue] == ["o1.md", "o2.md"]
    assert all(q["batch_size"] == 1 and q["mandatory"] for q in queue)


def test_risk_flags_force_batch_size_one():
    assert cr.risk_flags_of({"rerouted": True}) == ["fallback_produced"]
    assert cr.risk_flags_of({"attempt": 3}) == ["retried"]
    assert cr.risk_flags_of({"gate_results": {"36": {"action": "warn", "passed": True}}}) == [
        "gate36_warn"
    ]
    assert cr.risk_flags_of({"receipt_recovery": {"commit_sha": "x"}}) == ["revalidated_receipt"]
    assert cr.risk_flags_of({"content_type_route": "hallucination_prone"}) == [
        "hallucination_routed"
    ]
    assert cr.risk_flags_of({"drift_adjacent": True}) == ["drift_adjacent"]
    assert cr.risk_flags_of({"attempt": 1}) == []


def test_accepted_sample_queue_is_stratified_deterministic_and_includes_risk_flagged():
    receipts = []
    for site in ("docs.aspose.org", "kb.aspose.org"):
        for lang in ("de", "ja"):
            for i in range(10):
                receipts.append(
                    {
                        "site_id": site,
                        "target_lang": lang,
                        "output_path": f"{site}/{lang}/{i}.md",
                        "receipt_sha256": f"{site[:2]}{lang}{i:02d}",
                    }
                )
    receipts.append(
        {
            "site_id": "blog.aspose.org",
            "target_lang": "ar",
            "output_path": "risky.md",
            "receipt_sha256": "zz",
            "rerouted": True,
            "attempt": 2,
        }
    )
    queue = cr.build_accepted_sample_queue(receipts, sample_size=9)
    risky = [q for q in queue if q["output_path"] == "risky.md"]
    assert len(risky) == 1 and risky[0]["batch_size"] == 1 and risky[0]["mandatory"] is True
    assert sorted(risky[0]["risk_flags"]) == ["fallback_produced", "retried"]
    sampled = [q for q in queue if not q["mandatory"]]
    assert len(sampled) == 8  # sample_size minus the forced risk-flagged file
    strata = {(q["site_id"], q["target_lang"]) for q in sampled}
    assert len(strata) == 4  # every (site, lang) stratum is represented
    assert [q["output_path"] for q in cr.build_accepted_sample_queue(receipts, sample_size=9)] == [
        q["output_path"] for q in queue
    ]  # deterministic


def test_persistence_roundtrip(tmp_path: Path):
    result = _result(
        campaign_id="camp-x",
        verdict="REJECT_SYSTEMIC",
        systemic_scope={"pipeline_stage": "reconstruct"},
    )
    path = cr.append_review(result, root=tmp_path)
    assert path == tmp_path / "camp-x" / "claude_reviews.jsonl"
    cr.append_review(_result(campaign_id="camp-x", review_id="rev-2"), root=tmp_path)
    loaded = cr.load_reviews("camp-x", root=tmp_path)
    assert [r.review_id for r in loaded] == ["rev-1", "rev-2"]
    assert loaded[0].systemic_scope == {"pipeline_stage": "reconstruct"}
    assert cr.load_reviews("missing", root=tmp_path) == []


def test_stop_decision_systemic_stops_the_portfolio_and_names_the_blast_radius():
    result = _result(
        verdict="REJECT_SYSTEMIC",
        gate_hits_reviewed=[37],
        systemic_scope={
            "pipeline_stage": "tm",
            "blocker_category": "DATA_QUALITY",
            "affected_gate_ids": [37],
        },
    )
    decision = cr.stop_decision(result)
    assert decision["stop"] is True and decision["scope"] == "portfolio"
    assert decision["pipeline_stage"] == "tm" and decision["blocker_category"] == "DATA_QUALITY"
    assert decision["affected_gate_ids"] == [37]
    assert "audit_all_content.py" in decision["blast_radius_query"]
    assert "producer-side fix" in decision["required_cycle"]


def test_stop_decision_isolated_stops_only_the_shard():
    decision = cr.stop_decision(_result(verdict="REJECT_ISOLATED"))
    assert decision["stop"] is True and decision["scope"] == "shard"
    assert "content/docs.aspose.org/de/cells/net/a.md" in decision["blast_radius_query"]


def test_stop_decision_approve_and_blocked_external():
    approve = cr.stop_decision(_result(verdict="APPROVE"))
    assert approve == {"stop": False, "scope": "none", "reason": "APPROVE", "mark_rows": False}
    blocked = cr.stop_decision(_result(verdict="BLOCKED_EXTERNAL", confidence=0.0))
    assert blocked["stop"] is False and blocked["mark_rows"] is True


def test_new_review_id_is_unique_and_readable():
    a = cr.new_review_id("content/docs/de/page.md", "de")
    b = cr.new_review_id("content/docs/de/page.md", "de")
    assert a != b and a.startswith("rev-de-page-")
