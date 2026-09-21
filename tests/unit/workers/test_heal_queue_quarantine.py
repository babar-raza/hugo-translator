"""TC-APT-038: gate-close semantics via (target_lang, root_cause_class) quarantine.

Acceptance criterion (plan §11): "a unit test proves a quarantined pair is
skipped and later re-queued." The tests below prove both halves directly
against heal_queue.jsonl's real on-disk schema.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.workers.heal_queue import (
    PER_FILE_QUARANTINE_THRESHOLD,
    QUARANTINE_THRESHOLD,
    active_hold,
    add_hold,
    is_quarantined,
    is_source_path_quarantined,
    main as heal_queue_main,
    open_ticket_counts_by_pair,
    open_tickets_by_root_cause_class,
    open_tickets_for_source_path,
    quarantined_files,
    quarantined_pairs,
    release_hold,
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


# --- QU-02 per-file quarantine dimension -------------------------------------
# The per-locale dimension above requires 3 OPEN tickets for ONE locale before
# tripping. The live incident showed this is blind to a source file whose
# defect reproduces identically across MANY locales, one ticket each: e.g.
# quickstart.md hit LinkValidator on 7+ distinct locales and never
# accumulated 3 tickets for any single locale, so is_quarantined() never
# fired for any of them even though the file was clearly, systemically
# broken.


class TestPerFileQuarantineDimension:
    def test_many_locales_one_ticket_each_trips_the_file_dimension(self, tmp_path):
        """Reproduces the exact live gap: no single locale reaches
        QUARANTINE_THRESHOLD, but the file-level dimension still trips."""
        queue = tmp_path / "heal_queue.jsonl"
        locales = ["de", "fr", "es", "it", "hi", "ja", "ko"]
        _write_tickets(
            queue,
            [
                _ticket(lang, "auto:LinkValidator", source_path="content/x/quickstart.md")
                for lang in locales
            ],
        )
        assert PER_FILE_QUARANTINE_THRESHOLD == 3

        # Old per-locale-only logic never trips: each locale has exactly 1 ticket.
        for lang in locales:
            assert not is_quarantined("de", "auto:LinkValidator", heal_queue_path=queue)

        # New per-file dimension does trip.
        tripped, root_cause = is_source_path_quarantined(
            "content/x/quickstart.md", heal_queue_path=queue
        )
        assert tripped is True
        assert root_cause == "auto:LinkValidator"
        assert ("content/x/quickstart.md", "auto:LinkValidator") in quarantined_files(
            heal_queue_path=queue
        )

    def test_below_threshold_distinct_locales_does_not_trip(self, tmp_path):
        queue = tmp_path / "heal_queue.jsonl"
        _write_tickets(
            queue,
            [
                _ticket("de", "auto:LinkValidator", source_path="content/x/quickstart.md"),
                _ticket("fr", "auto:LinkValidator", source_path="content/x/quickstart.md"),
            ],
        )
        tripped, root_cause = is_source_path_quarantined(
            "content/x/quickstart.md", heal_queue_path=queue
        )
        assert tripped is False
        assert root_cause is None

    def test_resolved_tickets_do_not_count_toward_the_file_dimension(self, tmp_path):
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
                _ticket("fr", "auto:LinkValidator", source_path="content/x/quickstart.md"),
                _ticket("es", "auto:LinkValidator", source_path="content/x/quickstart.md"),
            ],
        )
        # Only 2 unresolved distinct locales remain -- below threshold.
        tripped, _ = is_source_path_quarantined("content/x/quickstart.md", heal_queue_path=queue)
        assert tripped is False

    def test_other_files_are_unaffected(self, tmp_path):
        queue = tmp_path / "heal_queue.jsonl"
        _write_tickets(
            queue,
            [
                _ticket(lang, "auto:LinkValidator", source_path="content/x/quickstart.md")
                for lang in ("de", "fr", "es")
            ],
        )
        tripped, _ = is_source_path_quarantined("content/x/other.md", heal_queue_path=queue)
        assert tripped is False

    def test_existing_per_locale_dimension_is_unchanged_by_the_new_file_dimension(self, tmp_path):
        """Same scenario as TestCountingAndThreshold.test_at_threshold_across_different_pages_is_quarantined
        (three tickets, same locale, different files): both dimensions must
        agree it's per-locale-quarantined without the new per-file helper
        interfering, since each ticket's file only has 1 distinct locale."""
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
        # Neither page individually reaches the per-file distinct-locale threshold.
        for page in ("page1", "page2", "page3"):
            tripped, _ = is_source_path_quarantined(page, heal_queue_path=queue)
            assert tripped is False


# --- QU-03 advisory holds -----------------------------------------------------
# A hold is a distinct event kind from the automated ticket lifecycle above:
# a deliberate, human/agent-authored "stop touching this file" signal with a
# mandatory reason, that must have real, code-enforced effect on scheduling
# rather than being an unread prose note, as happened in the incident this
# closes.


class TestAdvisoryHoldLifecycle:
    def test_a_new_hold_is_active(self, tmp_path):
        queue = tmp_path / "heal_queue.jsonl"
        add_hold("content/x/broken.md", "investigating link corruption", heal_queue_path=queue)

        hold = active_hold("content/x/broken.md", heal_queue_path=queue)

        assert hold is not None
        assert hold["reason"] == "investigating link corruption"

    def test_hold_requires_a_non_empty_reason(self, tmp_path):
        queue = tmp_path / "heal_queue.jsonl"
        with pytest.raises(ValueError):
            add_hold("content/x/broken.md", "", heal_queue_path=queue)
        with pytest.raises(ValueError):
            add_hold("content/x/broken.md", "   ", heal_queue_path=queue)

    def test_release_clears_an_active_hold(self, tmp_path):
        queue = tmp_path / "heal_queue.jsonl"
        add_hold("content/x/broken.md", "investigating", heal_queue_path=queue)
        assert active_hold("content/x/broken.md", heal_queue_path=queue) is not None

        release_hold("content/x/broken.md", heal_queue_path=queue)

        assert active_hold("content/x/broken.md", heal_queue_path=queue) is None

    def test_a_new_hold_after_release_is_active_again(self, tmp_path):
        queue = tmp_path / "heal_queue.jsonl"
        add_hold("content/x/broken.md", "first pass", heal_queue_path=queue)
        release_hold("content/x/broken.md", heal_queue_path=queue)
        add_hold("content/x/broken.md", "second pass", heal_queue_path=queue)

        hold = active_hold("content/x/broken.md", heal_queue_path=queue)

        assert hold is not None
        assert hold["reason"] == "second pass"

    def test_a_hold_on_one_file_does_not_affect_another(self, tmp_path):
        queue = tmp_path / "heal_queue.jsonl"
        add_hold("content/x/broken.md", "investigating", heal_queue_path=queue)

        assert active_hold("content/x/other.md", heal_queue_path=queue) is None

    def test_an_unexpired_hold_is_still_active(self, tmp_path):
        queue = tmp_path / "heal_queue.jsonl"
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        add_hold("content/x/broken.md", "investigating", expiry=future, heal_queue_path=queue)

        assert active_hold("content/x/broken.md", heal_queue_path=queue) is not None

    def test_an_expired_hold_stops_blocking_automatically_without_release(self, tmp_path):
        queue = tmp_path / "heal_queue.jsonl"
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        add_hold("content/x/broken.md", "investigating", expiry=past, heal_queue_path=queue)

        assert active_hold("content/x/broken.md", heal_queue_path=queue) is None

    def test_a_hold_never_matches_the_quarantine_dimensions(self, tmp_path):
        """A hold has no root_cause_class/target_lang -- it must be invisible
        to every quarantine query, since it isn't a validator finding."""
        queue = tmp_path / "heal_queue.jsonl"
        add_hold("content/x/broken.md", "investigating", heal_queue_path=queue)

        assert open_ticket_counts_by_pair(heal_queue_path=queue) == {}
        assert quarantined_pairs(heal_queue_path=queue) == set()
        assert quarantined_files(heal_queue_path=queue) == set()
        tripped, _ = is_source_path_quarantined("content/x/broken.md", heal_queue_path=queue)
        assert tripped is False

    def test_release_with_no_prior_hold_leaves_nothing_active(self, tmp_path):
        queue = tmp_path / "heal_queue.jsonl"
        release_hold("content/x/broken.md", heal_queue_path=queue)

        assert active_hold("content/x/broken.md", heal_queue_path=queue) is None

    def test_missing_file_has_no_active_hold(self, tmp_path):
        queue = tmp_path / "does_not_exist.jsonl"
        assert active_hold("content/x/broken.md", heal_queue_path=queue) is None


class TestAdvisoryHoldCli:
    def test_hold_subcommand_places_a_hold(self, tmp_path, monkeypatch):
        queue = tmp_path / "heal_queue.jsonl"
        monkeypatch.setattr("src.workers.heal_queue._HEAL_QUEUE_FILE", queue)

        exit_code = heal_queue_main(
            ["hold", "--source-path", "content/x/broken.md", "--reason", "investigating"]
        )

        assert exit_code == 0
        hold = active_hold("content/x/broken.md", heal_queue_path=queue)
        assert hold is not None
        assert hold["reason"] == "investigating"

    def test_release_subcommand_clears_a_hold(self, tmp_path, monkeypatch):
        queue = tmp_path / "heal_queue.jsonl"
        monkeypatch.setattr("src.workers.heal_queue._HEAL_QUEUE_FILE", queue)
        add_hold("content/x/broken.md", "investigating", heal_queue_path=queue)

        exit_code = heal_queue_main(["release", "--source-path", "content/x/broken.md"])

        assert exit_code == 0
        assert active_hold("content/x/broken.md", heal_queue_path=queue) is None

    def test_hold_subcommand_requires_reason_argument(self, tmp_path, monkeypatch):
        queue = tmp_path / "heal_queue.jsonl"
        monkeypatch.setattr("src.workers.heal_queue._HEAL_QUEUE_FILE", queue)

        with pytest.raises(SystemExit):
            heal_queue_main(["hold", "--source-path", "content/x/broken.md"])
