"""TC-APT-096: LMDB hardening before K-lane fan-out (plan SS0.10, BLITZ
critical path 2 of 3).

Direct reproduction on the PREVIOUS code confirmed the defect the plan
describes as a "self-deadlock waiting for load": store()/batch_store()
caught lmdb.MapFullError INSIDE the still-open outer write transaction and
tried to open a second write transaction there. On this platform/lmdb build
that raised InvalidParameterError from set_mapsize() itself (LMDB forbids
resizing while any transaction in this process is open), then BadTxnError
unwinding the outer transaction -- a hard crash, not the graceful "resize
and retry" the removed code's comments claimed. The fix retries the ENTIRE
write in a fresh transaction only after the failing one has fully aborted.

Also confirmed: zero call sites anywhere caught lmdb.MapResizedError before
this fix, so a sibling K-lane process resizing the shared LMDB file would
crash every other lane's very next TM read or write.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import lmdb
import pytest

from src.tm.l2_persistent import L2PersistentTM, TranslationEntry


@pytest.fixture()
def temp_db(tmp_path: Path) -> Path:
    return tmp_path / "l2_test.lmdb"


def _fill_to_map_full(tm: L2PersistentTM, prefix: str) -> int:
    """Store entries directly (bypassing the class's own retry-wrapped
    store()) until the tiny test map is truly saturated -- to seed a
    MapFullError on the NEXT real store() call under test.

    A single MapFullError from a large filler write can still leave a small
    unused fragment (partial page) behind, big enough for a much smaller
    subsequent write to slip through without ever needing to resize -- which
    would make a test built on "one big write fails" silently test nothing.
    So after the first failure, keep hammering with TINY writes (a handful
    of bytes each) until several in a row also fail, confirming no usable
    fragment remains.
    """
    i = 0
    try:
        while True:
            with tm.env.begin(write=True) as txn:
                txn.put(f"{prefix}{i}".encode(), b"x" * 500)
            i += 1
    except lmdb.MapFullError:
        pass

    consecutive_tiny_failures = 0
    while consecutive_tiny_failures < 5:
        try:
            with tm.env.begin(write=True) as txn:
                txn.put(f"{prefix}tiny{i}".encode(), b"x")
            i += 1
            consecutive_tiny_failures = 0
        except lmdb.MapFullError:
            consecutive_tiny_failures += 1
    return i


class TestStoreRecoversFromMapFullError:
    def test_store_survives_map_full_and_the_entry_lands(self, temp_db: Path):
        with L2PersistentTM(temp_db, max_size_mb=1) as tm:
            _fill_to_map_full(tm, "seed")
            # The map is now full; the class must resize and retry rather
            # than crash (the confirmed BadTxnError/InvalidParameterError
            # chain on the previous code).
            result = tm.store("site1", "en", "es", "Hello", "Hola")
            assert result is True
            entry = tm.exact_lookup("site1", "en", "es", "Hello")
            assert entry is not None
            assert entry.translation == "Hola"

    def test_map_size_actually_grew_after_recovery(self, temp_db: Path):
        with L2PersistentTM(temp_db, max_size_mb=1) as tm:
            before_mb = tm.env.info()["map_size"] / (1024 * 1024)
            _fill_to_map_full(tm, "seed")
            tm.store("site1", "en", "es", "Hello", "Hola")
            after_mb = tm.env.info()["map_size"] / (1024 * 1024)
            assert after_mb > before_mb


class TestBatchStoreRecoversFromMapFullError:
    def test_batch_store_survives_map_full_and_all_entries_land(self, temp_db: Path):
        with L2PersistentTM(temp_db, max_size_mb=1) as tm:
            _fill_to_map_full(tm, "seed")
            entries = [
                TranslationEntry(
                    source_text=f"Text {i}",
                    translation=f"Texto {i}",
                    site_id="site1",
                    src_lang="en",
                    tgt_lang="es",
                )
                for i in range(5)
            ]
            stored = tm.batch_store(entries)
            assert stored == 5
            for i in range(5):
                entry = tm.exact_lookup("site1", "en", "es", f"Text {i}")
                assert entry is not None
                assert entry.translation == f"Texto {i}"


class TestMapFullRecoveryGivesUpAtTheCeiling:
    def test_raises_once_the_cap_is_already_reached(self, temp_db: Path):
        with L2PersistentTM(temp_db, max_size_mb=1) as tm:
            with patch("src.tm.l2_persistent._MAX_MAP_SIZE_MB", 1):
                # Cap equals current size, so recovery cannot grow further --
                # must raise MapFullError rather than loop forever.
                with pytest.raises(lmdb.MapFullError):
                    _fill_to_map_full_raising(tm, "seed")


def _fill_to_map_full_raising(tm: L2PersistentTM, prefix: str) -> None:
    i = 0
    while True:
        tm.store("site1", "en", "es", f"{prefix}{i}", "x" * 500)
        i += 1


class _FlakyEnvProxy:
    """lmdb.Environment is a C-extension type -- its methods are read-only
    and cannot be patched via unittest.mock.patch.object directly. This
    thin proxy stands in for `tm.env` itself (a plain Python instance
    attribute, which CAN be swapped) and forwards everything to the real
    environment except `begin`, which it can fail on demand."""

    def __init__(self, real_env, fail_times: int, fail_with: Exception):
        self._real_env = real_env
        self._fail_times = fail_times
        self._fail_with = fail_with
        self.begin_calls = 0
        self.set_mapsize_calls: list[int] = []

    def begin(self, *args, **kwargs):
        self.begin_calls += 1
        if self.begin_calls <= self._fail_times:
            raise self._fail_with
        return self._real_env.begin(*args, **kwargs)

    def set_mapsize(self, size):
        self.set_mapsize_calls.append(size)
        return self._real_env.set_mapsize(size)

    def __getattr__(self, name):
        return getattr(self._real_env, name)


class TestMapResizedErrorRecovery:
    """A sibling process resizing the shared LMDB file first raises
    MapResizedError in every OTHER process's next transaction. Simulated
    here (a second real process is impractical in a unit test) via
    _FlakyEnvProxy, matching the exact exception py-lmdb raises for
    MDB_MAP_RESIZED."""

    def test_a_transient_map_resized_error_is_recovered_by_adopting_the_new_size(
        self, temp_db: Path
    ):
        with L2PersistentTM(temp_db, max_size_mb=20) as tm:
            proxy = _FlakyEnvProxy(tm.env, fail_times=1, fail_with=lmdb.MapResizedError("simulated"))
            with patch.object(tm, "env", proxy):
                result = tm.store("site1", "en", "es", "Hello", "Hola")
            assert result is True
            assert proxy.set_mapsize_calls == [0]

    def test_exact_lookup_also_recovers_from_map_resized_error(self, temp_db: Path):
        with L2PersistentTM(temp_db, max_size_mb=20) as tm:
            tm.store("site1", "en", "es", "Hello", "Hola")
            proxy = _FlakyEnvProxy(tm.env, fail_times=1, fail_with=lmdb.MapResizedError("simulated"))
            with patch.object(tm, "env", proxy):
                entry = tm.exact_lookup("site1", "en", "es", "Hello")
            assert entry is not None
            assert proxy.set_mapsize_calls == [0]

    def test_persistent_map_resized_error_eventually_raises(self, temp_db: Path):
        """Regression guard: this must not retry forever."""
        with L2PersistentTM(temp_db, max_size_mb=20) as tm:
            proxy = _FlakyEnvProxy(
                tm.env, fail_times=999, fail_with=lmdb.MapResizedError("permanently stale")
            )
            with patch.object(tm, "env", proxy):
                with pytest.raises(lmdb.MapResizedError):
                    tm.store("site1", "en", "es", "Hello", "Hola")


class TestTwoRealEnvironmentHandlesOnTheSamePath:
    """Closer to genuine cross-process behavior than mocking: two independent
    L2PersistentTM instances (two separate lmdb.Environment handles, as two
    K-lane launcher processes would each hold) opened on the SAME on-disk
    path. One resizes by filling to MapFull; the other's next operation
    must recover rather than crash."""

    def test_a_sibling_handles_resize_is_survived_by_this_handle(self, temp_db: Path):
        tm_a = L2PersistentTM(temp_db, max_size_mb=1)
        tm_b = L2PersistentTM(temp_db, max_size_mb=1)
        try:
            _fill_to_map_full(tm_a, "seed")
            # tm_a's own next store() resizes the shared on-disk map.
            assert tm_a.store("site1", "en", "es", "FromA", "DeA") is True

            # tm_b's environment handle now has a stale idea of the map size.
            # Its next operation must not crash.
            result = tm_b.store("site1", "en", "es", "FromB", "DeB")
            assert result is True
            entry = tm_b.exact_lookup("site1", "en", "es", "FromA")
            assert entry is not None
            assert entry.translation == "DeA"
        finally:
            tm_a.close()
            tm_b.close()
