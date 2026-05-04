"""
TC-TM-02: L2 LMDB dual-path detection and migration tests.

Verifies:
1. L2PersistentTM emits UserWarning when a sibling l2*.lmdb directory exists.
2. No warning is emitted when only the canonical database is present.
3. migrate_l2_lmdb.py --dry-run counts correctly without writing.
4. migrate_l2_lmdb.py --apply merges missing keys idempotently.

Gap: G-TM-02 — two live L2 LMDB directories (data/tm/l2.lmdb + data/tm/l2_lmdb).
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import pytest

try:
    import lmdb
    LMDB_AVAILABLE = True
except ImportError:
    LMDB_AVAILABLE = False

pytestmark = pytest.mark.skipif(not LMDB_AVAILABLE, reason="lmdb not installed")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_lmdb(path: Path, entries: dict[bytes, bytes]) -> None:
    """Create a minimal LMDB database at *path* with the given entries."""
    path.mkdir(parents=True, exist_ok=True)
    env = lmdb.open(str(path), map_size=10 * 1024 * 1024, max_dbs=1)
    with env.begin(write=True) as txn:
        for key, value in entries.items():
            txn.put(key, value)
    env.close()


def _read_lmdb(path: Path) -> dict[bytes, bytes]:
    """Return all entries in the given LMDB database as a dict."""
    env = lmdb.open(str(path), readonly=True, lock=False, max_dbs=1)
    result = {}
    with env.begin() as txn:
        cursor = txn.cursor()
        for key, value in cursor.iternext(keys=True, values=True):
            result[key] = value
    env.close()
    return result


# ---------------------------------------------------------------------------
# L2PersistentTM startup warning tests
# ---------------------------------------------------------------------------

class TestSiblingDetectionWarning:

    def test_no_warning_when_only_canonical_present(self, tmp_path: Path):
        """No warning when only the canonical l2.lmdb directory exists."""
        from src.tm.l2_persistent import L2_DB_NAME, L2PersistentTM
        db_path = tmp_path / L2_DB_NAME
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            tm = L2PersistentTM(db_path, max_size_mb=10)
            tm.env.close()
        sibling_warns = [w for w in caught if issubclass(w.category, UserWarning)
                         and "sibling" in str(w.message).lower()]
        assert len(sibling_warns) == 0, (
            f"Unexpected sibling warning with only canonical present: {sibling_warns}"
        )

    def test_warning_when_sibling_exists(self, tmp_path: Path):
        """UserWarning is emitted when a sibling l2*.lmdb directory exists."""
        from src.tm.l2_persistent import L2_DB_NAME, L2PersistentTM
        db_path = tmp_path / L2_DB_NAME
        # Create a sibling directory BEFORE opening canonical
        sibling = tmp_path / "l2_lmdb"
        _make_lmdb(sibling, {b"key1": b"val1"})

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            tm = L2PersistentTM(db_path, max_size_mb=10)
            tm.env.close()

        sibling_warns = [w for w in caught if issubclass(w.category, UserWarning)
                         and "sibling" in str(w.message).lower()]
        assert len(sibling_warns) == 1, (
            f"Expected exactly 1 sibling UserWarning, got {len(sibling_warns)}: "
            f"{[str(w.message) for w in caught]}"
        )
        assert "l2_lmdb" in str(sibling_warns[0].message), (
            "Warning should name the sibling directory."
        )
        assert "migrate_l2_lmdb.py" in str(sibling_warns[0].message), (
            "Warning should reference the migration script."
        )

    def test_warning_names_all_siblings(self, tmp_path: Path):
        """Warning message includes all sibling directory names."""
        from src.tm.l2_persistent import L2_DB_NAME, L2PersistentTM
        db_path = tmp_path / L2_DB_NAME
        _make_lmdb(tmp_path / "l2_lmdb", {b"a": b"1"})
        _make_lmdb(tmp_path / "l2_lmdb_old", {b"b": b"2"})

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            tm = L2PersistentTM(db_path, max_size_mb=10)
            tm.env.close()

        sibling_warns = [w for w in caught if issubclass(w.category, UserWarning)
                         and "sibling" in str(w.message).lower()]
        assert len(sibling_warns) == 1
        msg = str(sibling_warns[0].message)
        assert "l2_lmdb" in msg
        assert "l2_lmdb_old" in msg


# ---------------------------------------------------------------------------
# Migration script tests
# ---------------------------------------------------------------------------

class TestMigrationScript:

    def _run_migrate(self, *args: str) -> int:
        """Call migrate_l2_lmdb.main() with the given CLI args. Returns exit code."""
        # Import fresh each call so sys.argv doesn't leak
        from scripts import migrate_l2_lmdb
        try:
            migrate_l2_lmdb.main(list(args))
            return 0
        except SystemExit as exc:
            return int(exc.code) if exc.code is not None else 0

    def test_dry_run_does_not_write(self, tmp_path: Path, capsys):
        """--dry-run must not copy any keys into the destination."""
        src = tmp_path / "l2_lmdb"
        dst = tmp_path / "l2.lmdb"
        _make_lmdb(src, {b"k1": b"v1", b"k2": b"v2"})
        _make_lmdb(dst, {})

        from scripts.migrate_l2_lmdb import migrate
        migrate(src, dst, dry_run=True)

        dst_entries = _read_lmdb(dst)
        assert len(dst_entries) == 0, "dry-run must not write any keys"

        out = capsys.readouterr().out
        assert "Migrated" in out and "2" in out  # 2 would-be migrations

    def test_apply_copies_missing_keys(self, tmp_path: Path):
        """--apply must copy keys from source that are absent in destination."""
        src = tmp_path / "l2_lmdb"
        dst = tmp_path / "l2.lmdb"
        _make_lmdb(src, {b"k1": b"v1", b"k2": b"v2"})
        _make_lmdb(dst, {b"k1": b"already_there"})  # k1 already present

        from scripts.migrate_l2_lmdb import migrate
        migrate(src, dst, dry_run=False)

        dst_entries = _read_lmdb(dst)
        assert dst_entries[b"k1"] == b"already_there", "Existing key must not be overwritten"
        assert dst_entries[b"k2"] == b"v2", "Missing key must be copied"

    def test_apply_is_idempotent(self, tmp_path: Path):
        """Running --apply twice must produce the same result as running once."""
        src = tmp_path / "l2_lmdb"
        dst = tmp_path / "l2.lmdb"
        _make_lmdb(src, {b"k1": b"v1"})
        _make_lmdb(dst, {})

        from scripts.migrate_l2_lmdb import migrate
        migrate(src, dst, dry_run=False)
        after_first = _read_lmdb(dst)

        migrate(src, dst, dry_run=False)
        after_second = _read_lmdb(dst)

        assert after_first == after_second, "Second run must not change the database"

    def test_apply_no_source_is_noop(self, tmp_path: Path):
        """If source does not exist, migrate() should exit gracefully."""
        src = tmp_path / "l2_lmdb_nonexistent"
        dst = tmp_path / "l2.lmdb"
        _make_lmdb(dst, {b"k": b"v"})

        from scripts.migrate_l2_lmdb import migrate
        # Should not raise — just report nothing to migrate
        migrate(src, dst, dry_run=False)
        assert _read_lmdb(dst) == {b"k": b"v"}, "Destination must be unchanged"

    def test_cli_requires_dry_run_or_apply(self, tmp_path: Path, monkeypatch):
        """Running without --dry-run or --apply must exit with an error."""
        monkeypatch.chdir(tmp_path)
        from scripts.migrate_l2_lmdb import main
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code != 0
