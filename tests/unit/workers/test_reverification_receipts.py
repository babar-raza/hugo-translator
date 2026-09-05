"""TC-APT-057: reverification receipts, the RECURRENCE step 2 evidence standard.

project/loop-prompt.md §3: "a data/campaigns/reverification_receipts.jsonl
row with gates_passed: true for every (source_path, target_lang) the class's
original tickets name is the ONLY thing that lifts the obligation -- prose
does not count."
"""

import json

from src.workers.reverification_receipts import (
    has_passing_receipt,
    missing_receipts_for_class,
    record_receipt,
    recurrence_step2_satisfied,
)

CLASS = "auto:StructureValidator"


def _write_heal_tickets(path, tickets):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for ticket in tickets:
            f.write(json.dumps(ticket) + "\n")


def _open_ticket(source_path, target_lang, root_cause_class=CLASS):
    return {
        "ticket_id": f"{source_path}:{target_lang}",
        "source_path": source_path,
        "target_lang": target_lang,
        "root_cause_class": root_cause_class,
        "status": "OPEN",
    }


class TestRecordAndQuery:
    def test_never_stores_candidate_text_fields(self, tmp_path):
        row = record_receipt(
            source_path="p.md", target_lang="ar", root_cause_class=CLASS,
            gates_passed=True, evidence_path="data/summaries/x.json",
            receipts_path=tmp_path / "r.jsonl",
        )
        assert set(row.keys()) == {
            "source_path", "target_lang", "root_cause_class", "gates_passed",
            "evidence_path", "verified_at",
        }

    def test_an_unrecorded_cell_has_no_passing_receipt(self, tmp_path):
        assert not has_passing_receipt("p.md", "ar", CLASS, receipts_path=tmp_path / "r.jsonl")

    def test_a_passing_receipt_is_found(self, tmp_path):
        receipts = tmp_path / "r.jsonl"
        record_receipt(
            source_path="p.md", target_lang="ar", root_cause_class=CLASS,
            gates_passed=True, evidence_path="e", receipts_path=receipts,
        )
        assert has_passing_receipt("p.md", "ar", CLASS, receipts_path=receipts)

    def test_a_failing_receipt_does_not_count_as_passing(self, tmp_path):
        receipts = tmp_path / "r.jsonl"
        record_receipt(
            source_path="p.md", target_lang="ar", root_cause_class=CLASS,
            gates_passed=False, evidence_path="e", receipts_path=receipts,
        )
        assert not has_passing_receipt("p.md", "ar", CLASS, receipts_path=receipts)

    def test_the_most_recent_receipt_wins_over_an_earlier_one(self, tmp_path):
        receipts = tmp_path / "r.jsonl"
        record_receipt(
            source_path="p.md", target_lang="ar", root_cause_class=CLASS,
            gates_passed=True, evidence_path="e1", receipts_path=receipts,
        )
        record_receipt(
            source_path="p.md", target_lang="ar", root_cause_class=CLASS,
            gates_passed=False, evidence_path="e2", receipts_path=receipts,
        )
        assert not has_passing_receipt("p.md", "ar", CLASS, receipts_path=receipts)

    def test_a_different_root_cause_class_on_the_same_cell_is_independent(self, tmp_path):
        receipts = tmp_path / "r.jsonl"
        record_receipt(
            source_path="p.md", target_lang="ar", root_cause_class=CLASS,
            gates_passed=True, evidence_path="e", receipts_path=receipts,
        )
        assert not has_passing_receipt("p.md", "ar", "auto:TC-SAS-01", receipts_path=receipts)


class TestMissingReceiptsForClass:
    def test_an_open_ticket_with_no_receipt_is_missing(self, tmp_path):
        heal_queue = tmp_path / "heal_queue.jsonl"
        _write_heal_tickets(heal_queue, [_open_ticket("p1.md", "ar")])
        missing = missing_receipts_for_class(
            CLASS, heal_queue_path=heal_queue, receipts_path=tmp_path / "r.jsonl"
        )
        assert missing == [("p1.md", "ar")]

    def test_a_passing_receipt_clears_its_ticket_from_missing(self, tmp_path):
        heal_queue = tmp_path / "heal_queue.jsonl"
        receipts = tmp_path / "r.jsonl"
        _write_heal_tickets(heal_queue, [_open_ticket("p1.md", "ar"), _open_ticket("p2.md", "fa")])
        record_receipt(
            source_path="p1.md", target_lang="ar", root_cause_class=CLASS,
            gates_passed=True, evidence_path="e", receipts_path=receipts,
        )
        missing = missing_receipts_for_class(CLASS, heal_queue_path=heal_queue, receipts_path=receipts)
        assert missing == [("p2.md", "fa")]

    def test_a_resolved_ticket_is_not_required_to_have_a_receipt(self, tmp_path):
        heal_queue = tmp_path / "heal_queue.jsonl"
        ticket = _open_ticket("p1.md", "ar")
        ticket["disposition"] = "FIXED_VERIFIED"
        _write_heal_tickets(heal_queue, [ticket])
        missing = missing_receipts_for_class(
            CLASS, heal_queue_path=heal_queue, receipts_path=tmp_path / "r.jsonl"
        )
        assert missing == []

    def test_a_failing_receipt_still_counts_as_missing(self, tmp_path):
        heal_queue = tmp_path / "heal_queue.jsonl"
        receipts = tmp_path / "r.jsonl"
        _write_heal_tickets(heal_queue, [_open_ticket("p1.md", "ar")])
        record_receipt(
            source_path="p1.md", target_lang="ar", root_cause_class=CLASS,
            gates_passed=False, evidence_path="e", receipts_path=receipts,
        )
        assert missing_receipts_for_class(CLASS, heal_queue_path=heal_queue, receipts_path=receipts) == [
            ("p1.md", "ar")
        ]


class TestRecurrenceStep2Satisfied:
    def test_not_satisfied_while_any_receipt_is_missing(self, tmp_path):
        heal_queue = tmp_path / "heal_queue.jsonl"
        _write_heal_tickets(heal_queue, [_open_ticket("p1.md", "ar")])
        assert not recurrence_step2_satisfied(
            CLASS, heal_queue_path=heal_queue, receipts_path=tmp_path / "r.jsonl"
        )

    def test_satisfied_once_every_named_cell_has_a_passing_receipt(self, tmp_path):
        heal_queue = tmp_path / "heal_queue.jsonl"
        receipts = tmp_path / "r.jsonl"
        _write_heal_tickets(heal_queue, [_open_ticket("p1.md", "ar"), _open_ticket("p2.md", "fa")])
        record_receipt(
            source_path="p1.md", target_lang="ar", root_cause_class=CLASS,
            gates_passed=True, evidence_path="e", receipts_path=receipts,
        )
        record_receipt(
            source_path="p2.md", target_lang="fa", root_cause_class=CLASS,
            gates_passed=True, evidence_path="e", receipts_path=receipts,
        )
        assert recurrence_step2_satisfied(CLASS, heal_queue_path=heal_queue, receipts_path=receipts)

    def test_vacuously_satisfied_when_the_class_has_no_open_tickets(self, tmp_path):
        assert recurrence_step2_satisfied(
            "auto:NeverSeen", heal_queue_path=tmp_path / "missing.jsonl",
            receipts_path=tmp_path / "r.jsonl",
        )

    def test_prose_alone_never_satisfies_it(self, tmp_path):
        """The runbook is explicit: 'prose does not count.' No receipt call, no satisfaction."""
        heal_queue = tmp_path / "heal_queue.jsonl"
        _write_heal_tickets(heal_queue, [_open_ticket("p1.md", "ar")])
        assert not recurrence_step2_satisfied(
            CLASS, heal_queue_path=heal_queue, receipts_path=tmp_path / "never_written.jsonl"
        )
