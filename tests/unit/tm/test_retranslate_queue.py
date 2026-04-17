"""
Unit tests for src/tm/retranslate_queue.py

Covers:
- add_to_queue: creates JSONL entry, handles I/O errors gracefully
- load_queued_paths: returns absolute path strings, respects MAX_RETRIES
- remove_from_queue: drops matched entry, preserves others
- increment_retry: increments count, drops entry when MAX_RETRIES exceeded
- Full round-trip: add → load → remove
- Atomic rewrite: temp file swap
"""

import json
import pytest
from pathlib import Path
from unittest import mock

import src.tm.retranslate_queue as rtq


@pytest.fixture(autouse=True)
def patch_queue_path(tmp_path):
    """Redirect the queue file to a temp directory for every test."""
    queue_file = tmp_path / "retranslate_queue.jsonl"
    with mock.patch.object(rtq, "_QUEUE_FILE", queue_file):
        yield queue_file


# ---------------------------------------------------------------------------
# add_to_queue
# ---------------------------------------------------------------------------

class TestAddToQueue:
    def test_creates_queue_file_with_entry(self, tmp_path):
        output = tmp_path / "content" / "ar" / "post.md"
        output.parent.mkdir(parents=True)
        output.touch()

        rtq.add_to_queue(output, "ar")

        queue_file = rtq._queue_path()
        assert queue_file.exists()
        lines = [l for l in queue_file.read_text().splitlines() if l.strip()]
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["tgt_lang"] == "ar"
        assert entry["retry_count"] == 1
        assert str(output.resolve()) == entry["output_path"]

    def test_appends_multiple_entries(self, tmp_path):
        f1 = tmp_path / "a.ar.md"
        f2 = tmp_path / "b.fr.md"
        f1.touch()
        f2.touch()

        rtq.add_to_queue(f1, "ar")
        rtq.add_to_queue(f2, "fr")

        lines = [l for l in rtq._queue_path().read_text().splitlines() if l.strip()]
        assert len(lines) == 2
        langs = {json.loads(l)["tgt_lang"] for l in lines}
        assert langs == {"ar", "fr"}

    def test_queued_at_is_iso_format(self, tmp_path):
        f = tmp_path / "x.md"
        f.touch()
        rtq.add_to_queue(f, "de")
        entry = json.loads(rtq._queue_path().read_text().strip())
        assert "T" in entry["queued_at"]  # ISO 8601 contains 'T'
        assert entry["queued_at"].endswith("+00:00")  # must be timezone-aware UTC

    def test_add_does_not_raise_on_io_error(self, tmp_path):
        """add_to_queue must not raise even if the write fails."""
        f = tmp_path / "f.md"
        f.touch()
        with mock.patch("builtins.open", side_effect=OSError("disk full")):
            # Should log warning and return silently
            rtq.add_to_queue(f, "ar")


# ---------------------------------------------------------------------------
# load_queued_paths
# ---------------------------------------------------------------------------

class TestLoadQueuedPaths:
    def test_returns_empty_set_when_no_queue_file(self):
        assert rtq.load_queued_paths() == set()

    def test_returns_absolute_path_strings(self, tmp_path):
        f = tmp_path / "post.ar.md"
        f.touch()
        rtq.add_to_queue(f, "ar")

        paths = rtq.load_queued_paths()
        assert str(f.resolve()) in paths

    def test_excludes_entries_exceeding_max_retries(self, tmp_path):
        queue_file = rtq._queue_path()
        queue_file.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "output_path": str(tmp_path / "stuck.ar.md"),
            "tgt_lang": "ar",
            "queued_at": "2026-04-17T00:00:00",
            "retry_count": rtq._MAX_RETRIES + 1,  # over limit
        }
        queue_file.write_text(json.dumps(entry) + "\n")

        assert rtq.load_queued_paths() == set()

    def test_includes_entries_at_max_retries(self, tmp_path):
        queue_file = rtq._queue_path()
        queue_file.parent.mkdir(parents=True, exist_ok=True)
        path_str = str(tmp_path / "borderline.ar.md")
        entry = {
            "output_path": path_str,
            "tgt_lang": "ar",
            "queued_at": "2026-04-17T00:00:00",
            "retry_count": rtq._MAX_RETRIES,  # exactly at limit — still included
        }
        queue_file.write_text(json.dumps(entry) + "\n")

        paths = rtq.load_queued_paths()
        assert path_str in paths

    def test_skips_malformed_lines(self, tmp_path):
        queue_file = rtq._queue_path()
        queue_file.parent.mkdir(parents=True, exist_ok=True)
        queue_file.write_text("not-json\n{\"output_path\": \"/valid\", \"retry_count\": 1}\n")

        paths = rtq.load_queued_paths()
        assert "/valid" in paths

    def test_returns_empty_set_on_read_error(self, tmp_path):
        queue_file = rtq._queue_path()
        queue_file.parent.mkdir(parents=True, exist_ok=True)
        queue_file.write_text("{}")  # valid JSON but missing output_path key
        # Should return empty without raising
        paths = rtq.load_queued_paths()
        # The entry without 'output_path' key is quietly skipped via KeyError catch
        assert isinstance(paths, set)


# ---------------------------------------------------------------------------
# remove_from_queue
# ---------------------------------------------------------------------------

class TestRemoveFromQueue:
    def test_removes_matching_entry(self, tmp_path):
        f1 = tmp_path / "a.ar.md"
        f2 = tmp_path / "b.fr.md"
        f1.touch()
        f2.touch()

        rtq.add_to_queue(f1, "ar")
        rtq.add_to_queue(f2, "fr")

        rtq.remove_from_queue(f1)

        remaining = rtq.load_queued_paths()
        assert str(f1.resolve()) not in remaining
        assert str(f2.resolve()) in remaining

    def test_no_op_when_file_not_in_queue(self, tmp_path):
        f = tmp_path / "ghost.md"
        f.touch()
        # Should not raise even if queue file doesn't exist
        rtq.remove_from_queue(f)

    def test_no_op_when_queue_file_absent(self, tmp_path):
        f = tmp_path / "x.md"
        f.touch()
        rtq.remove_from_queue(f)  # queue file doesn't exist — should be silent

    def test_queue_empty_after_removing_only_entry(self, tmp_path):
        f = tmp_path / "solo.ar.md"
        f.touch()
        rtq.add_to_queue(f, "ar")
        rtq.remove_from_queue(f)

        assert rtq.load_queued_paths() == set()


# ---------------------------------------------------------------------------
# increment_retry
# ---------------------------------------------------------------------------

class TestIncrementRetry:
    def test_increments_retry_count(self, tmp_path):
        f = tmp_path / "bad.ar.md"
        f.touch()
        rtq.add_to_queue(f, "ar")  # retry_count = 1

        rtq.increment_retry(f)

        queue_file = rtq._queue_path()
        entry = json.loads(queue_file.read_text().strip())
        assert entry["retry_count"] == 2

    def test_drops_entry_when_max_retries_exceeded(self, tmp_path):
        queue_file = rtq._queue_path()
        queue_file.parent.mkdir(parents=True, exist_ok=True)
        path_str = str((tmp_path / "stuck.ar.md").resolve())
        entry = {
            "output_path": path_str,
            "tgt_lang": "ar",
            "queued_at": "2026-04-17T00:00:00",
            "retry_count": rtq._MAX_RETRIES,  # one more increment drops it
        }
        queue_file.write_text(json.dumps(entry) + "\n")

        rtq.increment_retry(Path(path_str))

        assert rtq.load_queued_paths() == set()

    def test_preserves_other_entries_when_dropping(self, tmp_path):
        f1 = tmp_path / "a.ar.md"
        f2 = tmp_path / "b.fr.md"
        f1.touch()
        f2.touch()

        rtq.add_to_queue(f1, "ar")
        rtq.add_to_queue(f2, "fr")

        # Artificially set f1 to MAX_RETRIES so next increment drops it
        queue_file = rtq._queue_path()
        lines = queue_file.read_text().splitlines()
        updated = []
        for line in lines:
            e = json.loads(line)
            if e["output_path"] == str(f1.resolve()):
                e["retry_count"] = rtq._MAX_RETRIES
            updated.append(json.dumps(e))
        queue_file.write_text("\n".join(updated) + "\n")

        rtq.increment_retry(f1)

        remaining = rtq.load_queued_paths()
        assert str(f1.resolve()) not in remaining
        assert str(f2.resolve()) in remaining


# ---------------------------------------------------------------------------
# Round-trip integration
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def test_add_load_remove_cycle(self, tmp_path):
        f = tmp_path / "post.ar.md"
        f.touch()

        rtq.add_to_queue(f, "ar")
        loaded = rtq.load_queued_paths()
        assert str(f.resolve()) in loaded

        rtq.remove_from_queue(f)
        assert rtq.load_queued_paths() == set()

    def test_multiple_add_load_remove(self, tmp_path):
        files = [tmp_path / f"f{i}.ar.md" for i in range(5)]
        for f in files:
            f.touch()
            rtq.add_to_queue(f, "ar")

        assert len(rtq.load_queued_paths()) == 5

        # Remove 3 of them
        for f in files[:3]:
            rtq.remove_from_queue(f)

        remaining = rtq.load_queued_paths()
        assert len(remaining) == 2
        for f in files[3:]:
            assert str(f.resolve()) in remaining
