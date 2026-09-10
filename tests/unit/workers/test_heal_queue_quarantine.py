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
    open_tickets_by_root_cause_class,
    open_tickets_for_source_path,
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


class TestOpenTicketsByRootCauseClass:
    def test_returns_only_open_tickets_of_the_named_class(self, tmp_path):
        queue = tmp_path / "heal_queue.jsonl"
        _write_tickets(
            queue,
            [
                _ticket("ar", "auto:StructureValidator", source_path="page1"),
                _ticket("fa", "auto:StructureValidator", source_path="page2"),
                _ticket("ar", "auto:TC-SAS-01", source_path="page3"),
            ],
        )
        tickets = open_tickets_by_root_cause_class("auto:StructureValidator", heal_queue_path=queue)
        assert {t["source_path"] for t in tickets} == {"page1", "page2"}

    def test_resolved_tickets_of_the_class_are_excluded(self, tmp_path):
        queue = tmp_path / "heal_queue.jsonl"
        _write_tickets(
            queue,
            [
                _ticket("ar", "auto:StructureValidator", source_path="page1", disposition="FIXED_VERIFIED"),
                _ticket("fa", "auto:StructureValidator", source_path="page2"),
            ],
        )
        tickets = open_tickets_by_root_cause_class("auto:StructureValidator", heal_queue_path=queue)
        assert {t["source_path"] for t in tickets} == {"page2"}

    def test_missing_file_returns_empty_list(self, tmp_path):
        assert open_tickets_by_root_cause_class("auto:X", heal_queue_path=tmp_path / "none.jsonl") == []


class TestOpenTicketsForSourcePath:
    """QU-01 (TC-APT-105 audit): the read-helper a manifest builder consults
    before scheduling new work against a source file."""

    def test_returns_only_tickets_for_the_exact_source_path(self, tmp_path):
        queue = tmp_path / "heal_queue.jsonl"
        _write_tickets(
            queue,
            [
                _ticket("de", "auto:LinkValidator", source_path="content/x/quickstart.md"),
                _ticket("fr", "auto:LinkValidator", source_path="content/x/quickstart.md"),
                _ticket("de", "auto:LinkValidator", source_path="content/x/other.md"),
            ],
        )
        tickets = open_tickets_for_source_path(
            "content/x/quickstart.md", heal_queue_path=queue
        )
        assert {t["target_lang"] for t in tickets} == {"de", "fr"}

    def test_resolved_ticket_for_the_path_is_excluded(self, tmp_path):
        queue = tmp_path / "heal_queue.jsonl"
        _write_tickets(
            queue,
            [
                _ticket(
                    "de",
                    "auto:LinkValidator",
                    source_path="content/x/quickstart.md",
                    disposition="FIXED_VERIFIED",
                ),
            ],
        )
        assert open_tickets_for_source_path(
            "content/x/quickstart.md", heal_queue_path=queue
        ) == []

    def test_no_matching_path_returns_empty_list(self, tmp_path):
        queue = tmp_path / "heal_queue.jsonl"
        _write_tickets(queue, [_ticket("de", "auto:LinkValidator", source_path="content/x/other.md")])
        assert (
            open_tickets_for_source_path("content/x/quickstart.md", heal_queue_path=queue) == []
        )

    def test_missing_file_returns_empty_list(self, tmp_path):
        assert (
            open_tickets_for_source_path("content/x/quickstart.md", heal_queue_path=tmp_path / "none.jsonl")
            == []
        )


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


# --- TC-APT-060 openness semantics -------------------------------------------
# The runbook defines this directly: "OPEN means `disposition` is absent or
# `OPEN`". The heal queue genuinely holds two shapes -- older rows carry only
# `disposition: "OPEN"`, newer ones carry `status: "OPEN"` -- and requiring
# status == "OPEN" made every disposition-only ticket invisible. Measured when
# found: all 16 producer_softwrap_sentence_split tickets read as ZERO open, so
# recurrence_step2_satisfied() returned True having verified nothing, and the
# quarantine threshold could never fire for those rows.

from src.workers.heal_queue import _counts_toward_quarantine


def test_a_disposition_only_open_ticket_counts():
    """The shape that was invisible: no status field at all."""
    assert _counts_toward_quarantine({"disposition": "OPEN"}) is True


def test_a_status_only_open_ticket_still_counts():
    """Neutrality: the shape that already worked must keep working."""
    assert _counts_toward_quarantine({"status": "OPEN"}) is True


def test_a_ticket_with_neither_field_counts_as_open():
    """'disposition is absent' is explicitly open per the rule."""
    assert _counts_toward_quarantine({"root_cause_class": "x"}) is True


def test_a_terminal_disposition_closes_it_even_when_status_says_open():
    """45 real rows carry status OPEN with a terminal disposition.

    Disposition is checked first precisely so the terminal verdict wins.
    """
    for terminal in ("FIXED_VERIFIED", "WAIVED_RUBRIC", "MODEL_LIMITATION_DEFERRED"):
        assert _counts_toward_quarantine({"status": "OPEN", "disposition": terminal}) is False


def test_a_non_open_status_closes_it():
    assert _counts_toward_quarantine({"status": "CLOSED"}) is False


def test_status_is_compared_case_insensitively():
    assert _counts_toward_quarantine({"status": "open"}) is True
