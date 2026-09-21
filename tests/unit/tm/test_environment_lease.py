"""TM-02: `environment_lease.py`'s docstring previously described the lease
mechanism without stating what it does NOT guarantee -- a reader could
reasonably (and incorrectly) assume it serializes writes between two
already-running, already-leased processes. It never has: `admission.lock`
only serializes lease *acquisition* against `maintenance()`.

This file proves, against the real mechanism (no mocks):
1. Today's actual, by-design behavior the corrected docstring describes --
   multiple concurrent leases on the same environment succeed, and
   `maintenance()` excludes both directions (existing lease vs. new
   maintenance, and existing maintenance vs. new lease).
2. The actual write-serialization guarantee available to callers: it comes
   entirely from LMDB's own internal writer lock, not from this module --
   demonstrated with two real OS processes, one holding an open write
   transaction while the other calls `L2PersistentTM.store()`, proving the
   second process's write provably waits rather than racing it.
"""

from __future__ import annotations

import multiprocessing as mp
import time
from pathlib import Path

import pytest

from src.tm.environment_lease import EnvironmentBusy, EnvironmentLease, maintenance


class TestConcurrentLeaseBehavior:
    """The behavior the corrected docstring claims: distinct leases on the
    same environment coexist; admission.lock only guards lease-acquisition
    vs. maintenance, in both directions."""

    def test_multiple_concurrent_leases_on_same_environment_succeed(self, tmp_path):
        env_path = tmp_path / "some_env"
        lease1 = EnvironmentLease(env_path)
        lease2 = EnvironmentLease(env_path)
        lease3 = EnvironmentLease(env_path)
        try:
            pass  # construction succeeding, with no exception, IS the proof
        finally:
            lease1.close()
            lease2.close()
            lease3.close()

    def test_maintenance_is_refused_while_a_lease_is_active(self, tmp_path):
        env_path = tmp_path / "some_env"
        lease = EnvironmentLease(env_path)
        try:
            with pytest.raises(EnvironmentBusy):
                with maintenance([env_path]):
                    pass  # pragma: no cover - must never be reached
        finally:
            lease.close()

    def test_a_new_lease_is_refused_while_maintenance_is_running(self, tmp_path):
        env_path = tmp_path / "some_env"
        with maintenance([env_path]):
            with pytest.raises(EnvironmentBusy):
                EnvironmentLease(env_path)

    def test_a_lease_succeeds_again_once_maintenance_completes(self, tmp_path):
        env_path = tmp_path / "some_env"
        with maintenance([env_path]):
            pass
        # maintenance() released the admission lock on exit -- a fresh lease
        # must succeed immediately afterward, not stay refused.
        lease = EnvironmentLease(env_path)
        lease.close()


# --- Real multi-process write-serialization proof ---------------------------
# Must be module-level (not nested) so Windows' spawn start method can pickle
# and re-import them in the child process.


def _mp_hold_write_txn_then_release(db_path_str: str, hold_seconds: float, ready, released_at):
    from src.tm.l2_persistent import L2PersistentTM

    tm = L2PersistentTM(db_path=Path(db_path_str))
    try:
        with tm.env.begin(write=True) as txn:
            txn.put(b"marker-holder", b"1")
            ready.set()
            time.sleep(hold_seconds)
        released_at.value = time.time()
    finally:
        tm.close()


def _mp_store_one_entry(db_path_str: str, ready, completed_at):
    from src.tm.l2_persistent import L2PersistentTM

    ready.wait(timeout=20)
    tm = L2PersistentTM(db_path=Path(db_path_str))
    try:
        tm.store(site_id="s", src_lang="en", tgt_lang="de", text="hello", translation="hallo")
        completed_at.value = time.time()
    finally:
        tm.close()


class TestRealWriteSerializationComesFromLmdb:
    def test_a_second_processs_write_waits_for_the_firsts_open_transaction(self, tmp_path):
        """Two real OS processes, same LMDB environment. Process A opens a
        write transaction and holds it open for `hold_seconds`. Process B
        waits for A to have started (so both writers are genuinely racing
        for the same environment, not merely sequential), then calls the
        real production `store()`. If LMDB's own writer lock is doing the
        serializing (this module does none), B's store() cannot complete
        until A releases -- proven by comparing wall-clock completion
        times, not by trusting the absence of a crash."""
        db_path = tmp_path / "l2.lmdb"
        ctx = mp.get_context("spawn")
        ready = ctx.Event()
        released_at = ctx.Value("d", 0.0)
        completed_at = ctx.Value("d", 0.0)
        hold_seconds = 1.5

        holder = ctx.Process(
            target=_mp_hold_write_txn_then_release,
            args=(str(db_path), hold_seconds, ready, released_at),
        )
        writer = ctx.Process(
            target=_mp_store_one_entry,
            args=(str(db_path), ready, completed_at),
        )

        holder.start()
        writer.start()
        holder.join(timeout=30)
        writer.join(timeout=30)

        assert holder.exitcode == 0, "holder process crashed"
        assert writer.exitcode == 0, "writer process crashed"
        assert released_at.value > 0.0, "holder never released its transaction"
        assert completed_at.value > 0.0, "writer's store() never completed"

        # The proof: B's store() could not complete before A released the lock.
        assert completed_at.value >= released_at.value, (
            f"writer completed at {completed_at.value}, before holder released "
            f"at {released_at.value} -- LMDB did not serialize the writes"
        )

        # And no corruption: both writes landed.
        from src.tm.l2_persistent import L2PersistentTM

        tm = L2PersistentTM(db_path=db_path)
        try:
            with tm.env.begin() as txn:
                assert txn.get(b"marker-holder") == b"1"
            entry = tm.exact_lookup(site_id="s", src_lang="en", tgt_lang="de", text="hello")
            assert entry is not None
            assert entry.translation == "hallo"
        finally:
            tm.close()
