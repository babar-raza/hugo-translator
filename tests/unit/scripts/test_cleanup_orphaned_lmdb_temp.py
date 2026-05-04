"""Tests for the orphaned LMDB temp cleanup script."""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from scripts.cleanup_orphaned_lmdb_temp import cleanup, find_candidates, main


def _make_lmdb_dir(path: Path, size_bytes: int = 1024) -> Path:
    """Create a fake LMDB directory with data.mdb and lock.mdb."""
    path.mkdir(parents=True, exist_ok=True)
    data_mdb = path / "data.mdb"
    data_mdb.write_bytes(b"\x00" * size_bytes)
    (path / "lock.mdb").write_bytes(b"\x00" * 64)
    # Backdate to make it older than max_age_hours
    old_time = time.time() - 7200  # 2 hours ago
    os.utime(data_mdb, (old_time, old_time))
    return path


def _make_pytest_structure(root: Path, test_name: str = "test_foo0") -> Path:
    """Create a pytest-style temp directory structure."""
    pytest_dir = root / "pytest-of-user" / "pytest-100" / test_name
    pytest_dir.mkdir(parents=True, exist_ok=True)
    return pytest_dir


class TestFindCandidates:

    def test_finds_pytest_owned_lmdb(self, tmp_path):
        pytest_dir = _make_pytest_structure(tmp_path)
        _make_lmdb_dir(pytest_dir / "l2.lmdb")
        candidates = find_candidates(tmp_path, max_age_hours=0.5)
        assert len(candidates) == 1
        assert candidates[0][0] == pytest_dir / "l2.lmdb"

    def test_skips_unknown_shape(self, tmp_path):
        """Directories not matching pytest patterns are skipped."""
        unknown = tmp_path / "random_dir" / "some_db"
        _make_lmdb_dir(unknown)
        candidates = find_candidates(tmp_path, max_age_hours=0.5)
        assert len(candidates) == 0

    def test_skips_missing_lock_mdb(self, tmp_path):
        """Directories without lock.mdb are skipped."""
        pytest_dir = _make_pytest_structure(tmp_path)
        lmdb_dir = pytest_dir / "l2.lmdb"
        lmdb_dir.mkdir(parents=True)
        (lmdb_dir / "data.mdb").write_bytes(b"\x00" * 100)
        # No lock.mdb
        candidates = find_candidates(tmp_path, max_age_hours=0.5)
        assert len(candidates) == 0

    def test_skips_too_new(self, tmp_path):
        """Directories newer than max_age_hours are skipped."""
        pytest_dir = _make_pytest_structure(tmp_path)
        lmdb_dir = pytest_dir / "l2.lmdb"
        lmdb_dir.mkdir(parents=True)
        (lmdb_dir / "data.mdb").write_bytes(b"\x00" * 100)
        (lmdb_dir / "lock.mdb").write_bytes(b"\x00" * 64)
        # Don't backdate — it's brand new
        candidates = find_candidates(tmp_path, max_age_hours=1.0)
        assert len(candidates) == 0

    def test_only_name_filter(self, tmp_path):
        """--only-name restricts to matching basenames."""
        pytest_dir = _make_pytest_structure(tmp_path)
        _make_lmdb_dir(pytest_dir / "l2.lmdb")
        _make_lmdb_dir(pytest_dir / "other.lmdb")

        candidates = find_candidates(tmp_path, max_age_hours=0.5, only_name="l2.lmdb")
        assert len(candidates) == 1
        assert candidates[0][0].name == "l2.lmdb"

    @pytest.mark.skipif(os.name == "nt", reason="Symlink creation may require admin on Windows")
    def test_skips_symlink(self, tmp_path):
        """Symlinked LMDB directories are skipped."""
        pytest_dir = _make_pytest_structure(tmp_path)
        real_dir = _make_lmdb_dir(tmp_path / "real_lmdb")
        symlink_dir = pytest_dir / "l2.lmdb"
        symlink_dir.symlink_to(real_dir, target_is_directory=True)

        candidates = find_candidates(tmp_path, max_age_hours=0.5)
        assert len(candidates) == 0


class TestCleanup:

    def test_dry_run_deletes_nothing(self, tmp_path):
        pytest_dir = _make_pytest_structure(tmp_path)
        lmdb_dir = _make_lmdb_dir(pytest_dir / "l2.lmdb")

        deleted, failed = cleanup(tmp_path, dry_run=True, max_age_hours=0.5)
        assert deleted == 0
        assert failed == 0
        assert lmdb_dir.exists(), "dry-run must not delete anything"

    def test_apply_deletes_owned_lmdb(self, tmp_path):
        pytest_dir = _make_pytest_structure(tmp_path)
        lmdb_dir = _make_lmdb_dir(pytest_dir / "l2.lmdb")

        deleted, failed = cleanup(tmp_path, dry_run=False, max_age_hours=0.5)
        assert deleted == 1
        assert failed == 0
        assert not lmdb_dir.exists(), "apply must delete the LMDB directory"

    def test_prints_candidates(self, tmp_path, capsys):
        pytest_dir = _make_pytest_structure(tmp_path)
        _make_lmdb_dir(pytest_dir / "l2.lmdb")

        cleanup(tmp_path, dry_run=True, max_age_hours=0.5)
        out = capsys.readouterr().out
        assert "l2.lmdb" in out
        assert "WOULD DELETE" in out


class TestMain:

    def test_root_outside_temp_rejected(self, tmp_path):
        exit_code = main(["--dry-run", "--root", str(tmp_path)])
        # tmp_path is typically under system temp, so this may pass.
        # Use a definitely-outside path instead:
        exit_code = main(["--dry-run", "--root", "C:/definitely_not_temp"])
        assert exit_code == 2

    def test_defaults_to_dry_run(self, tmp_path):
        """Running without --dry-run or --apply defaults to dry-run."""
        exit_code = main(["--root", str(tmp_path), "--allow-custom-root"])
        assert exit_code == 0
