"""TC-APT-094: cross-process LLM call slot semaphore."""

import json
import time
from datetime import datetime, timedelta, timezone

import pytest

from src.utils.file_lock import FileLock, LockError
from src.workers.llm_slot_semaphore import (
    LLMSlot,
    LLMSlotTimeoutError,
    acquire_slot,
    release_slot,
)


def _write_raw(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


class TestAcquireSlot:
    def test_holders_up_to_capacity_all_acquire(self, tmp_path):
        slots = tmp_path / "llm_slots.json"
        a = acquire_slot("holder-a", capacity=2, slots_path=slots)
        b = acquire_slot("holder-b", capacity=2, slots_path=slots)
        assert a is not None
        assert b is not None
        assert a != b

    def test_a_holder_beyond_capacity_is_rejected(self, tmp_path):
        slots = tmp_path / "llm_slots.json"
        acquire_slot("holder-a", capacity=1, slots_path=slots)
        assert acquire_slot("holder-b", capacity=1, slots_path=slots) is None

    def test_the_same_holder_renews_instead_of_taking_a_second_slot(self, tmp_path):
        slots = tmp_path / "llm_slots.json"
        first = acquire_slot("holder-a", capacity=1, slots_path=slots)
        second = acquire_slot("holder-a", capacity=1, slots_path=slots)
        assert first == second
        data = json.loads(slots.read_text(encoding="utf-8"))
        assert len(data["slots"]) == 1

    def test_an_expired_slot_is_reaped_and_frees_capacity(self, tmp_path):
        slots = tmp_path / "llm_slots.json"
        now = datetime.now(timezone.utc)
        _write_raw(
            slots,
            {
                "slots": {
                    "holder-a:stale": {
                        "holder_id": "holder-a",
                        "acquired_at": (now - timedelta(seconds=200)).isoformat(),
                        "expires_at": (now - timedelta(seconds=100)).isoformat(),
                    }
                }
            },
        )
        assert acquire_slot("holder-b", capacity=1, slots_path=slots) is not None

    def test_dead_pid_slot_is_reaped_before_ttl_expires(self, tmp_path):
        slots = tmp_path / "llm_slots.json"
        now = datetime.now(timezone.utc)
        _write_raw(
            slots,
            {
                "slots": {
                    "pid99999999-dead:stale": {
                        "holder_id": "pid99999999-dead",
                        "acquired_at": now.isoformat(),
                        "expires_at": (now + timedelta(hours=1)).isoformat(),
                    }
                }
            },
        )
        assert acquire_slot("holder-b", capacity=1, slots_path=slots) is not None


class TestReleaseSlot:
    def test_release_frees_capacity_for_another_holder(self, tmp_path):
        slots = tmp_path / "llm_slots.json"
        slot_id = acquire_slot("holder-a", capacity=1, slots_path=slots)
        assert acquire_slot("holder-b", capacity=1, slots_path=slots) is None
        release_slot(slot_id, "holder-a", slots_path=slots)
        assert acquire_slot("holder-b", capacity=1, slots_path=slots) is not None

    def test_release_from_non_owner_does_not_free_someone_elses_slot(self, tmp_path):
        slots = tmp_path / "llm_slots.json"
        slot_id = acquire_slot("holder-a", capacity=1, slots_path=slots)
        release_slot(slot_id, "holder-b", slots_path=slots)  # holder-b never held it
        assert acquire_slot("holder-c", capacity=1, slots_path=slots) is None


class TestLLMSlotContextManager:
    def test_acquires_and_releases_around_the_body(self, tmp_path):
        slots = tmp_path / "llm_slots.json"
        with LLMSlot("holder-a", capacity=1, slots_path=slots):
            assert acquire_slot("holder-b", capacity=1, slots_path=slots) is None
        assert acquire_slot("holder-b", capacity=1, slots_path=slots) is not None

    def test_releases_even_when_the_body_raises(self, tmp_path):
        slots = tmp_path / "llm_slots.json"
        with pytest.raises(ValueError):
            with LLMSlot("holder-a", capacity=1, slots_path=slots):
                raise ValueError("simulated LLM call failure")
        assert acquire_slot("holder-b", capacity=1, slots_path=slots) is not None

    def test_times_out_when_the_semaphore_never_frees(self, tmp_path):
        slots = tmp_path / "llm_slots.json"
        acquire_slot("holder-a", capacity=1, slots_path=slots)
        start = time.monotonic()
        with pytest.raises(LLMSlotTimeoutError):
            with LLMSlot(
                "holder-b",
                capacity=1,
                slots_path=slots,
                wait_timeout=0.3,
                poll_interval=0.1,
            ):
                pass
        assert time.monotonic() - start < 5.0

    def test_two_instances_in_one_process_get_distinct_holder_ids(self, tmp_path):
        slots = tmp_path / "llm_slots.json"
        slot_a = LLMSlot(capacity=2, slots_path=slots)
        slot_b = LLMSlot(capacity=2, slots_path=slots)
        assert slot_a.holder_id != slot_b.holder_id
        with slot_a, slot_b:
            data = json.loads(slots.read_text(encoding="utf-8"))
            assert len(data["slots"]) == 2


class TestRealCrossProcessExclusion:
    def test_acquire_raises_while_the_lock_file_is_externally_held(self, tmp_path):
        """Proves this actually uses FileLock, not just a read-then-write race."""
        slots = tmp_path / "llm_slots.json"
        lock = FileLock(slots.with_suffix(".json.lock"), timeout=0)
        lock.acquire()
        try:
            with pytest.raises(LockError):
                acquire_slot("holder-a", slots_path=slots, lock_timeout=0.2)
        finally:
            lock.release()

        # Once released, acquisition proceeds normally.
        assert acquire_slot("holder-a", slots_path=slots) is not None
