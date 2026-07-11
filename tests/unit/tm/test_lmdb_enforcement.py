"""
Unit tests for lmdb_registry path enforcement and L2PersistentTM idempotency.
"""
import json
from pathlib import Path

import pytest

from src.tm import lmdb_registry
from src.tm.l2_persistent import L2_DB_NAME, L2PersistentTM, TranslationEntry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_registry():
    """Reset registry state between tests."""
    lmdb_registry._PROJECT_ROOT = None


# ---------------------------------------------------------------------------
# lmdb_registry tests
# ---------------------------------------------------------------------------

class TestLmdbRegistry:
    def setup_method(self):
        _reset_registry()

    def teardown_method(self):
        _reset_registry()

    def test_unapproved_path_raises(self, tmp_path):
        project_root = tmp_path / "project"
        project_root.mkdir()
        lmdb_registry.set_project_root(project_root)
        with pytest.raises(ValueError, match="Unapproved"):
            lmdb_registry.assert_approved_path(project_root / "data/tm/wrong_name.lmdb")

    def test_canonical_path_passes(self, tmp_path):
        project_root = tmp_path / "project"
        project_root.mkdir()
        lmdb_registry.set_project_root(project_root)
        canonical = project_root / "data" / "tm" / L2_DB_NAME
        lmdb_registry.assert_approved_path(canonical)  # must not raise

    def test_outside_project_root_bypasses_enforcement(self, tmp_path):
        """Paths outside the project root (e.g. pytest tmp_path) are always allowed."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        lmdb_registry.set_project_root(project_root)
        outside = tmp_path / "some_other_db.lmdb"
        lmdb_registry.assert_approved_path(outside)  # must not raise

    def test_no_root_set_bypasses_enforcement(self, tmp_path):
        """If set_project_root was never called, no path raises."""
        lmdb_registry.assert_approved_path(tmp_path / "any_path.lmdb")

    def test_get_canonical_l2_path_raises_without_root(self):
        with pytest.raises(RuntimeError, match="set_project_root"):
            lmdb_registry.get_canonical_l2_path()

    def test_get_canonical_l2_path_returns_correct_path(self, tmp_path):
        project_root = tmp_path / "project"
        project_root.mkdir()
        lmdb_registry.set_project_root(project_root)
        expected = project_root / "data" / "tm" / L2_DB_NAME
        assert lmdb_registry.get_canonical_l2_path() == expected

    def test_migration_source_path_bypasses_enforcement(self, tmp_path):
        project_root = tmp_path / "project"
        project_root.mkdir()
        lmdb_registry.set_project_root(project_root)
        # Register a migration source
        migration_path = "data/tm/legacy.lmdb"
        original = lmdb_registry.MIGRATION_SOURCE_PATHS
        try:
            lmdb_registry.MIGRATION_SOURCE_PATHS = frozenset({migration_path})
            lmdb_registry.assert_approved_path(project_root / migration_path)  # must not raise
        finally:
            lmdb_registry.MIGRATION_SOURCE_PATHS = original


# ---------------------------------------------------------------------------
# L2PersistentTM enforcement integration test
# ---------------------------------------------------------------------------

class TestL2PersistentTMEnforcement:
    def setup_method(self):
        _reset_registry()

    def teardown_method(self):
        _reset_registry()

    def test_l2_outside_project_root_allowed(self, tmp_path):
        """L2PersistentTM with tmp_path is always allowed (outside project root)."""
        db_path = tmp_path / "test.lmdb"
        db = L2PersistentTM(db_path=db_path)
        db.close()

    def test_l2_unapproved_path_raises(self, tmp_path):
        """L2PersistentTM with a wrong path inside project root raises ValueError."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        lmdb_registry.set_project_root(project_root)
        bad_path = project_root / "data/tm/wrong.lmdb"
        with pytest.raises(ValueError, match="Unapproved"):
            L2PersistentTM(db_path=bad_path)

    def test_l2_canonical_path_allowed(self, tmp_path):
        """L2PersistentTM with canonical path passes enforcement."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        lmdb_registry.set_project_root(project_root)
        canonical = project_root / "data" / "tm" / L2_DB_NAME
        db = L2PersistentTM(db_path=canonical)
        db.close()


# ---------------------------------------------------------------------------
# Idempotency: batch_store must not create duplicates
# ---------------------------------------------------------------------------

class TestBatchStoreIdempotency:
    def test_double_store_no_duplicate(self, tmp_path):
        db = L2PersistentTM(db_path=tmp_path / "test.lmdb")
        entry = TranslationEntry(
            source_text="hello",
            translation="مرحبا",
            site_id="test",
            src_lang="en",
            tgt_lang="ar",
        )
        db.batch_store([entry])
        before = db.count()
        db.batch_store([entry])
        after = db.count()
        assert before == after == 1, f"Duplicate after second store: {after}"
        db.close()

    def test_store_different_translations_keeps_first_with_overwrite_false(self, tmp_path):
        db = L2PersistentTM(db_path=tmp_path / "test.lmdb")
        e1 = TranslationEntry("hello", "مرحبا", "test", "en", "ar")
        e2 = TranslationEntry("hello", "أهلا", "test", "en", "ar")
        db.batch_store([e1], overwrite=False)
        db.batch_store([e2], overwrite=False)
        result = db.exact_lookup("test", "en", "ar", "hello")
        assert result is not None
        assert result.translation == "مرحبا"  # first write preserved
        assert db.count() == 1
        db.close()
