"""Tests for the L2PersistentTM map_size compliance scanner."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.ci.check_lmdb_test_map_size import check_file, scan_paths


def _write(tmp_path: Path, code: str, name: str = "test_sample.py") -> Path:
    p = tmp_path / name
    p.write_text(code, encoding="utf-8")
    return p


class TestCompliantCalls:

    def test_small_max_size_passes(self, tmp_path):
        f = _write(tmp_path, 'tm = L2PersistentTM(db, max_size_mb=20)\n')
        assert check_file(f) == []

    def test_max_100_passes(self, tmp_path):
        f = _write(tmp_path, 'tm = L2PersistentTM(db, max_size_mb=100)\n')
        assert check_file(f) == []

    def test_justified_large_passes(self, tmp_path):
        code = (
            '# LMDB_MAX_SIZE_JUSTIFIED: capacity test; expected data: 150 MB; owner: tm\n'
            'tm = L2PersistentTM(db, max_size_mb=200)\n'
        )
        f = _write(tmp_path, code)
        assert check_file(f) == []

    def test_justified_three_lines_above(self, tmp_path):
        code = (
            '# LMDB_MAX_SIZE_JUSTIFIED: capacity test; expected data: 150 MB; owner: tm\n'
            'x = 1\n'
            'y = 2\n'
            'tm = L2PersistentTM(db, max_size_mb=200)\n'
        )
        f = _write(tmp_path, code)
        assert check_file(f) == []


class TestViolations:

    def test_missing_arg_fails(self, tmp_path):
        f = _write(tmp_path, 'tm = L2PersistentTM(some_path)\n')
        violations = check_file(f)
        assert len(violations) == 1
        assert "missing max_size_mb" in violations[0].reason

    def test_multiline_missing_arg_fails(self, tmp_path):
        code = (
            'tm = L2PersistentTM(\n'
            '    db_path=some_path,\n'
            ')\n'
        )
        f = _write(tmp_path, code)
        violations = check_file(f)
        assert len(violations) == 1
        assert "missing max_size_mb" in violations[0].reason

    def test_oversized_without_justification_fails(self, tmp_path):
        f = _write(tmp_path, 'tm = L2PersistentTM(db, max_size_mb=200)\n')
        violations = check_file(f)
        assert len(violations) == 1
        assert "200" in violations[0].reason
        assert "LMDB_MAX_SIZE_JUSTIFIED" in violations[0].reason


class TestFalsePositives:

    def test_string_not_matched(self, tmp_path):
        f = _write(tmp_path, 'x = "L2PersistentTM(db)"\n')
        assert check_file(f) == []

    def test_comment_not_matched(self, tmp_path):
        f = _write(tmp_path, '# L2PersistentTM(db)\n')
        assert check_file(f) == []

    def test_non_test_code_scanned_when_passed(self, tmp_path):
        """Scanner scans whatever file path is passed — filtering is the caller's job."""
        f = _write(tmp_path, 'tm = L2PersistentTM(db)\n')
        assert len(check_file(f)) == 1


class TestScanPaths:

    def test_directory_scan(self, tmp_path):
        _write(tmp_path, 'tm = L2PersistentTM(db, max_size_mb=10)\n', "test_ok.py")
        _write(tmp_path, 'tm = L2PersistentTM(db)\n', "test_bad.py")
        violations = scan_paths([str(tmp_path)])
        assert len(violations) == 1
        assert "test_bad.py" in violations[0].path
