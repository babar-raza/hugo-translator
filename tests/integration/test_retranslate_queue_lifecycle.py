"""
Integration test: Stage 2C retranslate queue full lifecycle.

Verifies the CASE 4 recovery chain end-to-end using the public queue API and
the completion-filter logic — without instantiating a full TranslationEngine:

  Step 1 — CASE 4 fires: add_to_queue() writes a JSONL entry to disk.
  Step 2 — Completion filter reads queue: load_queued_paths() returns the path;
            the path is present even if all output mtimes are current.
  Step 3 — Successful write dequeues: remove_from_queue() purges the entry.
  Step 4 — Retry cap: after increment_retry() x MAX_RETRIES, entry is dropped
            silently (load_queued_paths returns empty set, no exception).
"""

import json
import os
from pathlib import Path
from unittest import mock

import pytest

import src.tm.retranslate_queue as rtq


@pytest.fixture(autouse=True)
def _redirect_queue(tmp_path):
    """Point the queue file at a temp location for every test."""
    queue_file = tmp_path / "retranslate_queue.jsonl"
    quarantine_file = tmp_path / "quarantine.jsonl"
    with (
        mock.patch.object(rtq, "_QUEUE_FILE", queue_file),
        mock.patch.object(rtq, "_QUARANTINE_FILE", quarantine_file),
    ):
        yield queue_file


# ---------------------------------------------------------------------------
# Step 1 — CASE 4 fires: add_to_queue writes entry to disk
# ---------------------------------------------------------------------------


class TestStep1Enqueue:
    def test_add_to_queue_writes_jsonl_entry(self, tmp_path):
        """
        Simulates the CASE 4 fire site in engine.py:
          _rtq_add(output_path, target_lang)
        Verifies the JSONL file is created with correct fields.
        """
        output = tmp_path / "content" / "ar" / "page.md"
        output.parent.mkdir(parents=True)
        output.touch()

        rtq.add_to_queue(output, "ar")

        queue_file = rtq._queue_path()
        assert queue_file.exists(), "Queue file must be created by add_to_queue"
        lines = [l for l in queue_file.read_text().splitlines() if l.strip()]
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["output_path"] == str(output.resolve())
        assert entry["tgt_lang"] == "ar"
        assert entry["retry_count"] == 1
        assert entry["queued_at"].endswith("+00:00")

    def test_multiple_case4_fires_append_distinct_entries(self, tmp_path):
        """Two different files in CASE 4 must both appear in the queue."""
        f1 = tmp_path / "a.ar.md"
        f2 = tmp_path / "b.de.md"
        f1.touch()
        f2.touch()

        rtq.add_to_queue(f1, "ar")
        rtq.add_to_queue(f2, "de")

        paths = rtq.load_queued_paths()
        assert str(f1.resolve()) in paths
        assert str(f2.resolve()) in paths


# ---------------------------------------------------------------------------
# Step 2 — Completion filter: queued path force-included despite current outputs
# ---------------------------------------------------------------------------


class TestStep2CompletionFilterReadsQueue:
    def test_queued_path_returned_by_load_queued_paths(self, tmp_path):
        """
        load_queued_paths() is called by the completion filter in
        _translate_directory_locked() to build _queued_output_paths.
        Verifies it returns the absolute path string for a queued entry.
        """
        output = tmp_path / "stuck.ar.md"
        output.touch()

        rtq.add_to_queue(output, "ar")

        queued = rtq.load_queued_paths()
        assert str(output.resolve()) in queued

    def test_queued_path_present_even_when_output_mtime_is_current(self, tmp_path):
        """
        The key invariant: a queued output file should be force-included by the
        completion filter even if its mtime is newer than the source (i.e., it
        would otherwise be skipped as complete).

        This test verifies the queue state — the engine-side filter logic that
        reads this set is covered by test_completion_aware_filter.py.
        """
        source = tmp_path / "src.md"
        output = tmp_path / "out.ar.md"
        source.touch()
        output.touch()

        # Make output newer than source (would normally trigger skip)
        future = source.stat().st_mtime + 100.0
        os.utime(output, (future, future))

        rtq.add_to_queue(output, "ar")

        queued = rtq.load_queued_paths()
        # Queue contains the path — caller (engine filter) must force-include it
        assert str(output.resolve()) in queued

    def test_load_queued_paths_empty_when_queue_absent(self, tmp_path):
        """No queue file → empty set; completion filter proceeds normally."""
        assert rtq.load_queued_paths() == set()


# ---------------------------------------------------------------------------
# Step 3 — Successful write dequeues the entry
# ---------------------------------------------------------------------------


class TestStep3Dequeue:
    def test_remove_from_queue_purges_entry(self, tmp_path):
        """
        Simulates the successful-write site in engine.py:
          _rtq_remove(output_path)
        Verifies the queue no longer contains the path.
        """
        output = tmp_path / "healed.ar.md"
        output.touch()

        rtq.add_to_queue(output, "ar")
        assert str(output.resolve()) in rtq.load_queued_paths()

        rtq.remove_from_queue(output)

        assert str(output.resolve()) not in rtq.load_queued_paths()

    def test_remove_preserves_other_entries(self, tmp_path):
        """Dequeue of one file must not affect other queued files."""
        f1 = tmp_path / "a.ar.md"
        f2 = tmp_path / "b.de.md"
        f1.touch()
        f2.touch()

        rtq.add_to_queue(f1, "ar")
        rtq.add_to_queue(f2, "de")

        rtq.remove_from_queue(f1)

        remaining = rtq.load_queued_paths()
        assert str(f1.resolve()) not in remaining
        assert str(f2.resolve()) in remaining

    def test_queue_file_empty_after_removing_only_entry(self, tmp_path):
        """After the last entry is removed the queue file exists but is empty."""
        output = tmp_path / "x.ar.md"
        output.touch()

        rtq.add_to_queue(output, "ar")
        rtq.remove_from_queue(output)

        queue_file = rtq._queue_path()
        assert queue_file.exists()
        assert rtq.load_queued_paths() == set()


# ---------------------------------------------------------------------------
# Step 4 — Retry cap: MAX_RETRIES increments → silent drop
# ---------------------------------------------------------------------------


class TestStep4RetryCapDrop:
    def test_entry_dropped_after_max_retries(self, tmp_path):
        """
        After increment_retry() is called MAX_RETRIES times, the entry is
        silently dropped. No exception raised; load_queued_paths returns empty.
        """
        output = tmp_path / "stuck.ar.md"
        output.touch()

        rtq.add_to_queue(output, "ar")
        assert str(output.resolve()) in rtq.load_queued_paths()

        for _ in range(rtq._MAX_RETRIES):
            rtq.increment_retry(output)

        assert rtq.load_queued_paths() == set(), (
            f"Entry should be dropped after {rtq._MAX_RETRIES} retries"
        )

    def test_entry_still_present_before_max_retries(self, tmp_path):
        """Entry must survive MAX_RETRIES - 1 increments (boundary condition)."""
        output = tmp_path / "slow.de.md"
        output.touch()

        rtq.add_to_queue(output, "de")

        for _ in range(rtq._MAX_RETRIES - 1):
            rtq.increment_retry(output)

        assert str(output.resolve()) in rtq.load_queued_paths()

    def test_increment_retry_does_not_raise_when_queue_absent(self, tmp_path):
        """increment_retry on a missing queue file must be a no-op, no exception."""
        ghost = tmp_path / "ghost.ar.md"
        ghost.touch()
        # Queue file intentionally never created
        rtq.increment_retry(ghost)  # must not raise

    def test_retry_cap_does_not_affect_other_entries(self, tmp_path):
        """Dropping one maxed-out entry must leave other entries intact."""
        maxed = tmp_path / "maxed.ar.md"
        alive = tmp_path / "alive.de.md"
        maxed.touch()
        alive.touch()

        rtq.add_to_queue(maxed, "ar")
        rtq.add_to_queue(alive, "de")

        for _ in range(rtq._MAX_RETRIES):
            rtq.increment_retry(maxed)

        remaining = rtq.load_queued_paths()
        assert str(maxed.resolve()) not in remaining
        assert str(alive.resolve()) in remaining
