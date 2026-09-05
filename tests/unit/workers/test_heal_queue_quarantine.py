"""TC-APT-038: gate-close semantics via (target_lang, root_cause_class) quarantine.

Acceptance criterion (plan §11): "a unit test proves a quarantined pair is
skipped and later re-queued." The tests below prove both halves directly
against heal_queue.jsonl's real on-disk schema.
"""

import json

from src.workers.heal_queue import (
    QUARANTINE_THRESHOLD,
    is_quarantined,
    open_ticket_counts_by_pair,
    quarantined_pairs,
)


def _write_tickets(path, tickets):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for ticket in tickets:
            f.write(json.dumps(ticket) + "\n")


def _ticket(lang, root_cause_class, status="OPEN", disposition=None, source_path="p"):
    ticket = {
        "ticket_id": f"{source_path}:{lang}:{root_cause_class}",
        "source_path": source_path,
        "target_lang": lang,
        "root_cause_class": root_cause_class,
        "status": status,
    }
    if disposition is not None:
        ticket["disposition"] = disposition
    return ticket


class TestCountingAndThreshold:
    def test_below_threshold_is_not_quarantined(self, tmp_path):
        queue = tmp_path / "heal_queue.jsonl"
        _write_tickets(
            queue,
            [
                _ticket("ar", "auto:StructureValidator", source_path="page1"),
                _ticket("ar", "auto:StructureValidator", source_path="page2"),
            ],
        )
        assert QUARANTINE_THRESHOLD == 3
        assert not is_quarantined("ar", "auto:StructureValidator", heal_queue_path=queue)
        assert quarantined_pairs(heal_queue_path=queue) == set()

    def test_at_threshold_across_different_pages_is_quarantined(self, tmp_path):
        queue = tmp_path / "heal_queue.jsonl"
        _write_tickets(
            queue,
            [
                _ticket("ar", "auto:StructureValidator", source_path="page1"),
                _ticket("ar", "auto:StructureValidator", source_path="page2"),
                _ticket("ar", "auto:StructureValidator", source_path="page3"),
            ],
        )
        assert is_quarantined("ar", "auto:StructureValidator", heal_queue_path=queue)
        assert ("ar", "auto:StructureValidator") in quarantined_pairs(heal_queue_path=queue)

    def test_pairs_are_independent_by_language_and_class(self, tmp_path):
        queue = tmp_path / "heal_queue.jsonl"
        _write_tickets(
            queue,
            [
                _ticket("ar", "auto:StructureValidator", source_path="page1"),
                _ticket("ar", "auto:StructureValidator", source_path="page2"),
                _ticket("ar", "auto:StructureValidator", source_path="page3"),
                # Same language, different class: must not inherit ar's quarantine.
                _ticket("ar", "auto:TC-SAS-01", source_path="page1"),
                # Same class, different language: must not inherit it either.
                _ticket("fa", "auto:StructureValidator", source_path="page1"),
            ],
        )
        assert is_quarantined("ar", "auto:StructureValidator", heal_queue_path=queue)
        assert not is_quarantined("ar", "auto:TC-SAS-01", heal_queue_path=queue)
        assert not is_quarantined("fa", "auto:StructureValidator", heal_queue_path=queue)

    def test_missing_heal_queue_file_means_nothing_is_quarantined(self, tmp_path):
        queue = tmp_path / "does_not_exist.jsonl"
        assert quarantined_pairs(heal_queue_path=queue) == set()
        assert open_ticket_counts_by_pair(heal_queue_path=queue) == {}


class TestReQueueOnResolution:
    def test_a_pair_is_skipped_once_quarantined(self, tmp_path):
        queue = tmp_path / "heal_queue.jsonl"
        _write_tickets(
            queue,
            [_ticket("hi", "auto:TC-SAS-01", source_path=f"page{i}") for i in range(3)],
        )
        assert is_quarantined("hi", "auto:TC-SAS-01", heal_queue_path=queue)

    def test_it_is_later_re_queued_once_enough_tickets_resolve(self, tmp_path):
        queue = tmp_path / "heal_queue.jsonl"
        # Same 3 tickets, but one is now marked resolved by disposition --
        # only 2 unresolved OPEN tickets remain, below threshold.
        _write_tickets(
            queue,
            [
                _ticket("hi", "auto:TC-SAS-01", source_path="page0", disposition="FIXED_VERIFIED"),
                _ticket("hi", "auto:TC-SAS-01", source_path="page1"),
                _ticket("hi", "auto:TC-SAS-01", source_path="page2"),
            ],
        )
        assert not is_quarantined("hi", "auto:TC-SAS-01", heal_queue_path=queue)

    def test_closed_status_also_stops_counting(self, tmp_path):
        queue = tmp_path / "heal_queue.jsonl"
        _write_tickets(
            queue,
            [
                _ticket("hi", "auto:TC-SAS-01", source_path="page0", status="CLOSED"),
                _ticket("hi", "auto:TC-SAS-01", source_path="page1"),
                _ticket("hi", "auto:TC-SAS-01", source_path="page2"),
            ],
        )
        assert not is_quarantined("hi", "auto:TC-SAS-01", heal_queue_path=queue)

    def test_waived_and_model_limitation_dispositions_also_stop_counting(self, tmp_path):
        queue = tmp_path / "heal_queue.jsonl"
        _write_tickets(
            queue,
            [
                _ticket("ko", "auto:FrontmatterLanguageCheck", source_path="p0", disposition="WAIVED_RUBRIC"),
                _ticket(
                    "ko",
                    "auto:FrontmatterLanguageCheck",
                    source_path="p1",
                    disposition="MODEL_LIMITATION_DEFERRED",
                ),
                _ticket("ko", "auto:FrontmatterLanguageCheck", source_path="p2"),
            ],
        )
        assert not is_quarantined("ko", "auto:FrontmatterLanguageCheck", heal_queue_path=queue)
