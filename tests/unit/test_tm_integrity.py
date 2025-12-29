"""Unit tests for Translation Memory cache integrity verification.

Tests cover:
- Detection of corrupted JSON
- Detection of missing required fields
- Detection of empty field values
- Detection of invalid language codes
- Repair mode behavior
- Read-only mode preservation
- Empty cache handling
- Max errors limit
- Performance requirements
"""

import json
import sys
import time
import pytest
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from tm.integrity import CacheIntegrityChecker, IntegrityReport, check_cache_integrity
from tm.l2_persistent import L2PersistentTM


class TestIntegrityReport:
    """Tests for IntegrityReport dataclass."""

    def test_report_health_percentage_full(self):
        """Test 100% health when all entries valid."""
        report = IntegrityReport(
            total_scanned=100,
            valid_count=100,
            corrupt_count=0,
            repaired_count=0
        )
        assert report.health_percentage == 100.0
        assert report.is_healthy is True

    def test_report_health_percentage_partial(self):
        """Test partial health calculation."""
        report = IntegrityReport(
            total_scanned=100,
            valid_count=90,
            corrupt_count=10,
            repaired_count=0
        )
        assert report.health_percentage == 90.0
        assert report.is_healthy is False

    def test_report_health_percentage_empty(self):
        """Test 100% health for empty cache."""
        report = IntegrityReport(
            total_scanned=0,
            valid_count=0,
            corrupt_count=0,
            repaired_count=0
        )
        assert report.health_percentage == 100.0
        assert report.is_healthy is True

    def test_report_string_format(self):
        """Test string representation has expected format."""
        report = IntegrityReport(
            total_scanned=1000,
            valid_count=998,
            corrupt_count=2,
            repaired_count=0
        )
        report_str = str(report)
        assert "scanned=1000" in report_str
        assert "valid=998" in report_str
        assert "corrupt=2" in report_str
        assert "health=99.8%" in report_str

    def test_report_to_dict(self):
        """Test dictionary conversion."""
        report = IntegrityReport(
            total_scanned=100,
            valid_count=95,
            corrupt_count=5,
            repaired_count=3,
            errors=[(b"key1", "error1"), (b"key2", "error2")]
        )
        d = report.to_dict()
        assert d["total_scanned"] == 100
        assert d["valid_count"] == 95
        assert d["corrupt_count"] == 5
        assert d["repaired_count"] == 3
        assert d["health_percentage"] == 95.0
        assert d["is_healthy"] is False
        assert d["error_count"] == 2


class TestCacheIntegrityChecker:
    """Tests for CacheIntegrityChecker class."""

    @pytest.fixture
    def l2_db(self, tmp_path):
        """Create a fresh L2PersistentTM database."""
        db_path = tmp_path / "test_tm"
        return L2PersistentTM(db_path, max_size_mb=10)

    def _insert_raw_entry(self, l2, key: str, value: bytes):
        """Insert raw bytes directly into LMDB (for testing corruption)."""
        with l2.env.begin(write=True) as txn:
            txn.put(key.encode('utf-8'), value)

    def _insert_valid_entry(self, l2, i: int = 0):
        """Insert a valid translation entry."""
        l2.store(
            site_id="test.site",
            src_lang="en",
            tgt_lang="es",
            text=f"Test source text {i}",
            translation=f"Test translation {i}"
        )

    def test_integrity_detects_corrupted_json(self, l2_db):
        """Corrupted JSON entries are detected."""
        # Insert invalid JSON
        self._insert_raw_entry(l2_db, "invalid_json_key", b"{not valid json")

        checker = CacheIntegrityChecker(l2_db)
        report = checker.verify_all(log_progress=False)

        assert report.corrupt_count == 1
        assert report.valid_count == 0
        assert any("Invalid JSON" in msg for _, msg in report.errors)

    def test_integrity_detects_missing_fields(self, l2_db):
        """Entries with missing required fields are detected."""
        # Insert entry missing 'translation' field
        entry = {
            "source_text": "Hello",
            # "translation" missing
            "site_id": "test.site",
            "src_lang": "en",
            "tgt_lang": "es"
        }
        self._insert_raw_entry(l2_db, "missing_field_key", json.dumps(entry).encode('utf-8'))

        checker = CacheIntegrityChecker(l2_db)
        report = checker.verify_all(log_progress=False)

        assert report.corrupt_count == 1
        assert any("Missing required field" in msg for _, msg in report.errors)

    def test_integrity_detects_empty_fields(self, l2_db):
        """Entries with empty field values are detected."""
        # Insert entry with empty 'translation'
        entry = {
            "source_text": "Hello",
            "translation": "",  # Empty
            "site_id": "test.site",
            "src_lang": "en",
            "tgt_lang": "es"
        }
        self._insert_raw_entry(l2_db, "empty_field_key", json.dumps(entry).encode('utf-8'))

        checker = CacheIntegrityChecker(l2_db)
        report = checker.verify_all(log_progress=False)

        assert report.corrupt_count == 1
        assert any("Empty value" in msg for _, msg in report.errors)

    def test_integrity_detects_null_fields(self, l2_db):
        """Entries with null field values are detected."""
        entry = {
            "source_text": "Hello",
            "translation": None,  # Null
            "site_id": "test.site",
            "src_lang": "en",
            "tgt_lang": "es"
        }
        self._insert_raw_entry(l2_db, "null_field_key", json.dumps(entry).encode('utf-8'))

        checker = CacheIntegrityChecker(l2_db)
        report = checker.verify_all(log_progress=False)

        assert report.corrupt_count == 1
        assert any("Null value" in msg for _, msg in report.errors)

    def test_integrity_detects_invalid_language_codes(self, l2_db):
        """Invalid ISO language codes are detected."""
        # Insert entry with invalid language code
        entry = {
            "source_text": "Hello",
            "translation": "Hola",
            "site_id": "test.site",
            "src_lang": "english",  # Invalid - should be 2-letter code
            "tgt_lang": "es"
        }
        self._insert_raw_entry(l2_db, "invalid_lang_key", json.dumps(entry).encode('utf-8'))

        checker = CacheIntegrityChecker(l2_db)
        report = checker.verify_all(log_progress=False)

        assert report.corrupt_count == 1
        assert any("language code" in msg.lower() for _, msg in report.errors)

    def test_integrity_detects_unknown_language_codes(self, l2_db):
        """Unknown 2-letter language codes are detected."""
        entry = {
            "source_text": "Hello",
            "translation": "Hola",
            "site_id": "test.site",
            "src_lang": "xx",  # Unknown code
            "tgt_lang": "es"
        }
        self._insert_raw_entry(l2_db, "unknown_lang_key", json.dumps(entry).encode('utf-8'))

        checker = CacheIntegrityChecker(l2_db)
        report = checker.verify_all(log_progress=False)

        assert report.corrupt_count == 1
        assert any("Unknown language code" in msg for _, msg in report.errors)

    def test_integrity_repair_removes_bad_entries(self, l2_db):
        """Repair mode removes corrupted entries."""
        # Insert 3 valid entries
        for i in range(3):
            self._insert_valid_entry(l2_db, i)

        # Insert 2 corrupted entries
        self._insert_raw_entry(l2_db, "corrupt1", b"not json")
        self._insert_raw_entry(l2_db, "corrupt2", b"{invalid}")

        checker = CacheIntegrityChecker(l2_db)

        # First verify without repair
        report1 = checker.verify_all(repair=False, log_progress=False)
        assert report1.total_scanned == 5
        assert report1.valid_count == 3
        assert report1.corrupt_count == 2
        assert report1.repaired_count == 0

        # Now repair
        report2 = checker.verify_all(repair=True, log_progress=False)
        assert report2.repaired_count == 2

        # Verify again - should be clean now
        report3 = checker.verify_all(repair=False, log_progress=False)
        assert report3.total_scanned == 3
        assert report3.valid_count == 3
        assert report3.corrupt_count == 0

    def test_integrity_readonly_preserves_cache(self, l2_db):
        """Read-only mode does not modify cache."""
        # Insert 3 valid + 2 corrupted
        for i in range(3):
            self._insert_valid_entry(l2_db, i)
        self._insert_raw_entry(l2_db, "corrupt1", b"bad1")
        self._insert_raw_entry(l2_db, "corrupt2", b"bad2")

        checker = CacheIntegrityChecker(l2_db)

        # Verify without repair (read-only)
        report = checker.verify_all(repair=False, log_progress=False)
        assert report.corrupt_count == 2
        assert report.repaired_count == 0

        # Verify again - should still have 5 entries
        report2 = checker.verify_all(repair=False, log_progress=False)
        assert report2.total_scanned == 5

    def test_integrity_handles_empty_cache(self, l2_db):
        """Empty cache does not cause errors."""
        checker = CacheIntegrityChecker(l2_db)
        report = checker.verify_all(log_progress=False)

        assert report.total_scanned == 0
        assert report.valid_count == 0
        assert report.corrupt_count == 0
        assert report.health_percentage == 100.0

    def test_integrity_max_errors_limit(self, l2_db):
        """Scan stops after max_errors limit."""
        # Insert 200 corrupted entries
        for i in range(200):
            self._insert_raw_entry(l2_db, f"corrupt_{i}", b"bad data")

        checker = CacheIntegrityChecker(l2_db)
        report = checker.verify_all(max_errors=100, log_progress=False)

        # Should have stopped at or shortly after 100 errors
        assert len(report.errors) == 100
        # May scan one more entry before the check triggers
        assert report.total_scanned <= 101

    def test_integrity_valid_entries_pass(self, l2_db):
        """Valid entries pass all checks."""
        # Insert multiple valid entries
        for i in range(10):
            self._insert_valid_entry(l2_db, i)

        checker = CacheIntegrityChecker(l2_db)
        report = checker.verify_all(log_progress=False)

        assert report.total_scanned == 10
        assert report.valid_count == 10
        assert report.corrupt_count == 0
        assert report.is_healthy is True

    def test_integrity_detects_non_dict_entry(self, l2_db):
        """Non-dictionary entries are detected."""
        # Insert a JSON array instead of object
        self._insert_raw_entry(l2_db, "array_key", b'["not", "a", "dict"]')

        checker = CacheIntegrityChecker(l2_db)
        report = checker.verify_all(log_progress=False)

        assert report.corrupt_count == 1
        assert any("not a dictionary" in msg for _, msg in report.errors)

    def test_integrity_detects_invalid_utf8(self, l2_db):
        """Invalid UTF-8 encoding is detected."""
        # Insert invalid UTF-8 bytes
        self._insert_raw_entry(l2_db, "invalid_utf8", b'\xff\xfe invalid')

        checker = CacheIntegrityChecker(l2_db)
        report = checker.verify_all(log_progress=False)

        assert report.corrupt_count == 1
        assert any("UTF-8" in msg for _, msg in report.errors)


class TestCacheIntegrityPerformance:
    """Performance tests for integrity checking."""

    @pytest.fixture
    def l2_with_many_entries(self, tmp_path):
        """Create L2 with 10K entries for performance testing."""
        db_path = tmp_path / "perf_tm"
        l2 = L2PersistentTM(db_path, max_size_mb=100)

        # Insert 10K valid entries
        for i in range(10000):
            l2.store(
                site_id="test.site",
                src_lang="en",
                tgt_lang="es",
                text=f"Test source text number {i} with some content",
                translation=f"Texto de prueba numero {i} con algo de contenido"
            )

        return l2

    def test_integrity_performance_10k_entries(self, l2_with_many_entries):
        """Performance test: 10K entries should complete in <2s."""
        checker = CacheIntegrityChecker(l2_with_many_entries)

        start = time.perf_counter()
        report = checker.verify_all(log_progress=False)
        elapsed = time.perf_counter() - start

        assert report.total_scanned == 10000
        assert report.valid_count == 10000
        assert elapsed < 2.0, f"10K entries took {elapsed:.2f}s, expected <2s"


class TestVerifyEntry:
    """Tests for single entry verification."""

    @pytest.fixture
    def checker(self, tmp_path):
        """Create checker with empty database."""
        db_path = tmp_path / "test_tm"
        l2 = L2PersistentTM(db_path)
        return CacheIntegrityChecker(l2)

    def test_verify_entry_valid(self, checker):
        """Valid entry passes verification."""
        entry = {
            "source_text": "Hello",
            "translation": "Hola",
            "site_id": "test.site",
            "src_lang": "en",
            "tgt_lang": "es"
        }
        is_valid, error = checker.verify_entry(
            b"test_key",
            json.dumps(entry).encode('utf-8')
        )
        assert is_valid is True
        assert error is None

    def test_verify_entry_invalid_json(self, checker):
        """Invalid JSON fails verification."""
        is_valid, error = checker.verify_entry(b"key", b"not json")
        assert is_valid is False
        assert error is not None


class TestCheckCacheIntegrity:
    """Tests for convenience function."""

    def test_check_cache_integrity_function(self, tmp_path):
        """Test convenience function works."""
        db_path = tmp_path / "test_tm"

        # Create and populate database
        l2 = L2PersistentTM(db_path)
        l2.store(
            site_id="test.site",
            src_lang="en",
            tgt_lang="es",
            text="Hello",
            translation="Hola"
        )
        l2.close()

        # Use convenience function
        report = check_cache_integrity(db_path)

        assert report.total_scanned == 1
        assert report.valid_count == 1
        assert report.is_healthy is True
