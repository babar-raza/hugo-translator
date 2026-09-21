"""
TC-TM-02: L2 LMDB dual-path detection tests.

Verifies:
1. L2PersistentTM emits UserWarning for active sibling l2*.lmdb directories.
2. The explicitly inactive legacy ``l2_lmdb`` directory is silent.
3. No warning is emitted when only the canonical database is present.

Gap: G-TM-02 — two live L2 LMDB directories (data/tm/l2.lmdb + data/tm/l2_lmdb).

migrate_l2_lmdb.py's own merge/apply/idempotency/integrity behavior is covered
by tests/unit/tm/test_migrate_l2_lmdb.py against the current TranslationEntry-
JSON-payload contract (this file's former TestMigrationScript fixtures wrote
raw arbitrary bytes as values, which predates entry validation and no longer
reflects how the script is actually used).
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
        sibling_warns = [
            w
            for w in caught
            if issubclass(w.category, UserWarning) and "sibling" in str(w.message).lower()
        ]
        assert len(sibling_warns) == 0, (
            f"Unexpected sibling warning with only canonical present: {sibling_warns}"
        )

    def test_inactive_legacy_sibling_is_silent(self, tmp_path: Path):
        """The documented legacy/test-compatibility directory is not an active store."""
        from src.tm.l2_persistent import L2_DB_NAME, L2PersistentTM

        db_path = tmp_path / L2_DB_NAME
        # Create a sibling directory BEFORE opening canonical
        sibling = tmp_path / "l2_lmdb"
        _make_lmdb(sibling, {b"key1": b"val1"})

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            tm = L2PersistentTM(db_path, max_size_mb=10)
            tm.env.close()

        sibling_warns = [
            w
            for w in caught
            if issubclass(w.category, UserWarning) and "sibling" in str(w.message).lower()
        ]
        assert not sibling_warns, [str(w.message) for w in caught]

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

        sibling_warns = [
            w
            for w in caught
            if issubclass(w.category, UserWarning) and "sibling" in str(w.message).lower()
        ]
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
        from scripts.tm import migrate_l2_lmdb

        try:
            migrate_l2_lmdb.main(list(args))
            return 0
        except SystemExit as exc:
            return int(exc.code) if exc.code is not None else 0

    def test_default_paths_are_rooted_at_repository(self):
        from scripts.tm import migrate_l2_lmdb

        expected = Path(migrate_l2_lmdb.__file__).resolve().parents[2]
        assert migrate_l2_lmdb.repository_root() == expected
        assert (expected / "scripts" / "tm" / "migrate_l2_lmdb.py").is_file()

    def test_cli_requires_dry_run_or_apply(self, tmp_path: Path, monkeypatch):
        """Running without --dry-run or --apply must exit with an error."""
        monkeypatch.chdir(tmp_path)
        from scripts.tm.migrate_l2_lmdb import main

        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code != 0
