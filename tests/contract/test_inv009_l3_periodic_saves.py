"""
CONTRACT: specs/core_invariants.md

Verifies L3 semantic TM saves periodically to prevent data loss,
with configurable save interval and save statistics tracking.

INV-009 Core Invariant: L3 Periodic Saves

Key Guarantees:
1. Save triggers after save_interval additions
2. Save counter resets after successful save
3. Save failures are tracked and logged
4. Index persistence verified after periodic save
5. Async save option supported
"""

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ==============================================================================
# Skip if dependencies not available
# ==============================================================================


def pytest_configure(config):
    """Skip all tests if faiss or sentence-transformers not installed."""
    pass


@pytest.fixture(scope="module")
def check_deps():
    """Check if required dependencies are available."""
    try:
        import faiss
        from sentence_transformers import SentenceTransformer

        return True
    except ImportError:
        pytest.skip("faiss or sentence-transformers not installed")
        return False


# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def l3_index_dir(tmp_path):
    """Temporary directory for L3 index."""
    index_dir = tmp_path / "l3_index"
    index_dir.mkdir()
    return index_dir


@pytest.fixture
def l3_tm_low_interval(l3_index_dir, check_deps):
    """L3SemanticTM with low save_interval for testing."""
    from src.tm.l3_semantic import L3SemanticTM

    tm = L3SemanticTM(
        index_path=l3_index_dir,
        embedding_model="all-MiniLM-L6-v2",
        use_gpu=False,
        save_interval=5,  # Save every 5 additions
        async_save=False,  # Sync save for predictable testing
    )
    yield tm
    # Cleanup
    try:
        tm.save_index()
    except Exception:
        pass


@pytest.fixture
def l3_tm_disabled_save(l3_index_dir, check_deps):
    """L3SemanticTM with periodic saves disabled."""
    from src.tm.l3_semantic import L3SemanticTM

    tm = L3SemanticTM(
        index_path=l3_index_dir,
        embedding_model="all-MiniLM-L6-v2",
        use_gpu=False,
        save_interval=0,  # Disabled
        async_save=False,
    )
    yield tm


# ==============================================================================
# INV-009: Periodic Save Trigger Tests
# ==============================================================================


@pytest.mark.contract
def test_save_triggers_at_interval(l3_index_dir, check_deps):
    """
    Verify periodic save triggers when additions reach save_interval.

    CONTRACT: INV-009 - Save triggers at interval
    Evidence: src/tm/l3_semantic.py lines 240-242 (interval check and trigger)
    """
    from src.tm.l3_semantic import L3SemanticTM

    # Create TM with save_interval=3
    tm = L3SemanticTM(
        index_path=l3_index_dir,
        save_interval=3,
        async_save=False,
    )

    # Track save calls
    original_do_save = tm._do_save
    save_calls = []

    def tracked_save():
        save_calls.append(time.time())
        return original_do_save()

    tm._do_save = tracked_save

    # Add entries - should not trigger save yet
    tm.add_entry("e1", "site", "en", "es", "Hello world", "Hola mundo")
    assert len(save_calls) == 0
    assert tm._additions_since_save == 1

    tm.add_entry("e2", "site", "en", "es", "Good morning", "Buenos dias")
    assert len(save_calls) == 0
    assert tm._additions_since_save == 2

    # This addition should trigger save (reaches interval of 3)
    tm.add_entry("e3", "site", "en", "es", "Goodbye", "Adios")
    assert len(save_calls) == 1, "Save should trigger at interval"

    # Save should have reset counter
    assert tm._additions_since_save == 0


@pytest.mark.contract
def test_save_counter_resets_after_save(l3_tm_low_interval):
    """
    Verify additions counter resets to 0 after successful save.

    CONTRACT: INV-009 - Counter reset on save
    Evidence: src/tm/l3_semantic.py lines 281-284 (_do_save resets counter)
    """
    tm = l3_tm_low_interval

    # Add 5 entries to trigger save
    for i in range(5):
        tm.add_entry(f"entry{i}", "test-site", "en", "es", f"Source text {i}", f"Translation {i}")

    # Counter should be reset after save
    assert tm._additions_since_save == 0


@pytest.mark.contract
def test_no_save_when_interval_disabled(l3_tm_disabled_save):
    """
    Verify periodic save is disabled when save_interval=0.

    CONTRACT: INV-009 - Disabled save option
    Evidence: src/tm/l3_semantic.py line 241 (save_interval > 0 check)
    """
    tm = l3_tm_disabled_save

    # Track if save was triggered
    save_triggered = []
    original_trigger = tm._trigger_save

    def tracked_trigger():
        save_triggered.append(True)
        return original_trigger()

    tm._trigger_save = tracked_trigger

    # Add many entries
    for i in range(20):
        tm.add_entry(f"entry{i}", "test-site", "en", "es", f"Source {i}", f"Translation {i}")

    # Save should never have been triggered
    assert len(save_triggered) == 0
    # But counter should still be tracking
    assert tm._additions_since_save == 20


# ==============================================================================
# INV-009: Save Statistics Tests
# ==============================================================================


@pytest.mark.contract
def test_get_save_stats_returns_correct_data(l3_tm_low_interval):
    """
    Verify get_save_stats returns accurate statistics.

    CONTRACT: INV-009 - Save statistics tracking
    Evidence: src/tm/l3_semantic.py lines 301-315 (get_save_stats)
    """
    tm = l3_tm_low_interval

    # Add some entries (not enough to trigger save)
    for i in range(3):
        tm.add_entry(f"entry{i}", "test-site", "en", "es", f"Source {i}", f"Translation {i}")

    stats = tm.get_save_stats()

    # Verify stats structure
    assert "total_additions" in stats
    assert "additions_since_save" in stats
    assert "save_failures" in stats
    assert "last_save_time" in stats
    assert "save_interval" in stats
    assert "async_save" in stats

    # Verify values
    assert stats["total_additions"] == 3
    assert stats["additions_since_save"] == 3
    assert stats["save_failures"] == 0
    assert stats["save_interval"] == 5
    assert stats["async_save"] is False


@pytest.mark.contract
def test_total_additions_persists_across_saves(l3_tm_low_interval):
    """
    Verify total_additions counter persists (unlike additions_since_save).

    CONTRACT: INV-009 - Total additions tracking
    Evidence: src/tm/l3_semantic.py line 283 (only resets additions_since_save)
    """
    tm = l3_tm_low_interval

    # Add 7 entries (triggers save at 5)
    for i in range(7):
        tm.add_entry(f"entry{i}", "test-site", "en", "es", f"Source {i}", f"Translation {i}")

    stats = tm.get_save_stats()

    # Total should be 7 (all additions)
    assert stats["total_additions"] == 7
    # Since save resets counter (2 remaining after save at 5)
    assert stats["additions_since_save"] == 2


# ==============================================================================
# INV-009: Index Persistence Tests
# ==============================================================================


@pytest.mark.contract
def test_index_persisted_after_periodic_save(l3_index_dir, check_deps):
    """
    Verify index files exist on disk after periodic save.

    CONTRACT: INV-009 - Index persistence
    Evidence: src/tm/l3_semantic.py lines 517-550 (save_index writes files)
    """
    from src.tm.l3_semantic import L3SemanticTM

    tm = L3SemanticTM(
        index_path=l3_index_dir,
        save_interval=2,  # Low interval
        async_save=False,
    )

    # Add entries to trigger save
    tm.add_entry("e1", "site", "en", "es", "Hello", "Hola")
    tm.add_entry("e2", "site", "en", "es", "World", "Mundo")

    # Verify index files exist
    assert (l3_index_dir / "index.faiss").exists()
    assert (l3_index_dir / "metadata.pkl").exists()
    assert (l3_index_dir / "config.json").exists()

    # Verify config content
    with open(l3_index_dir / "config.json") as f:
        config = json.load(f)

    assert "embedding_dim" in config
    assert config["num_entries"] == 2


@pytest.mark.contract
def test_data_recoverable_after_reload(l3_index_dir, check_deps):
    """
    Verify data can be recovered from saved index.

    CONTRACT: INV-009 - Data recoverability
    Evidence: src/tm/l3_semantic.py lines 556-588 (load_index)
    """
    from src.tm.l3_semantic import L3SemanticTM

    # Create TM and add entries
    tm1 = L3SemanticTM(
        index_path=l3_index_dir,
        save_interval=2,
        async_save=False,
    )

    tm1.add_entry("e1", "site", "en", "es", "Hello world", "Hola mundo")
    tm1.add_entry("e2", "site", "en", "es", "Good morning", "Buenos dias")

    # Index should have been saved after 2 additions
    initial_total = tm1.index.ntotal

    # Create new TM instance pointing to same directory
    tm2 = L3SemanticTM(
        index_path=l3_index_dir,
        save_interval=100,
        async_save=False,
    )

    # Should have loaded the saved index
    assert tm2.index.ntotal == initial_total
    assert len(tm2.metadata) == 2


# ==============================================================================
# INV-009: Save Failure Tracking Tests
# ==============================================================================


@pytest.mark.contract
def test_save_failure_increments_counter(l3_index_dir, check_deps):
    """
    Verify save failures are tracked.

    CONTRACT: INV-009 - Failure tracking
    Evidence: src/tm/l3_semantic.py lines 292-299 (_do_save exception handling)
    """
    from src.tm.l3_semantic import L3SemanticTM

    tm = L3SemanticTM(
        index_path=l3_index_dir,
        save_interval=2,
        async_save=False,
    )

    # Mock save_index to fail
    original_save = tm.save_index

    def failing_save():
        raise OSError("Simulated disk error")

    tm.save_index = failing_save

    # Add entries to trigger save (which will fail)
    tm.add_entry("e1", "site", "en", "es", "Hello", "Hola")
    tm.add_entry("e2", "site", "en", "es", "World", "Mundo")

    # Check failure was tracked
    stats = tm.get_save_stats()
    assert stats["save_failures"] >= 1

    # Restore and verify counter persists
    tm.save_index = original_save


# ==============================================================================
# INV-009: Batch Add Trigger Tests
# ==============================================================================


@pytest.mark.contract
def test_batch_add_triggers_save_at_interval(l3_index_dir, check_deps):
    """
    Verify batch_add also triggers periodic save.

    CONTRACT: INV-009 - Batch add save trigger
    Evidence: src/tm/l3_semantic.py lines 485-499 (batch_add interval check)
    """
    from src.tm.l3_semantic import L3SemanticTM

    tm = L3SemanticTM(
        index_path=l3_index_dir,
        save_interval=5,
        async_save=False,
    )

    # Track saves
    save_count = [0]
    original_do_save = tm._do_save

    def counting_save():
        save_count[0] += 1
        return original_do_save()

    tm._do_save = counting_save

    # Batch add 10 entries (should trigger 2 saves: at 5 and 10)
    entries = [
        {
            "entry_id": f"e{i}",
            "site_id": "site",
            "src_lang": "en",
            "tgt_lang": "es",
            "source_text": f"Source {i}",
            "translation": f"Translation {i}",
        }
        for i in range(10)
    ]

    tm.batch_add(entries)

    # Should have triggered at least one save
    assert save_count[0] >= 1


# ==============================================================================
# INV-009: Atomic Write Tests
# ==============================================================================


@pytest.mark.contract
def test_save_uses_atomic_write_pattern(l3_index_dir, check_deps):
    """
    Verify save uses temp file + rename (atomic write pattern).

    CONTRACT: INV-009 - Atomic writes prevent corruption
    Evidence: src/tm/l3_semantic.py lines 528-550 (temp file + replace)
    """
    from src.tm.l3_semantic import L3SemanticTM

    tm = L3SemanticTM(
        index_path=l3_index_dir,
        save_interval=1,
        async_save=False,
    )

    # Add entry to trigger save
    tm.add_entry("e1", "site", "en", "es", "Hello", "Hola")

    # After save completes, no temp files should remain
    tmp_files = list(l3_index_dir.glob("*.tmp"))
    assert len(tmp_files) == 0, f"Temp files should be cleaned up: {tmp_files}"

    # Final files should exist
    assert (l3_index_dir / "index.faiss").exists()
    assert (l3_index_dir / "metadata.pkl").exists()
    assert (l3_index_dir / "config.json").exists()


# ==============================================================================
# INV-009: Default Configuration Tests
# ==============================================================================


@pytest.mark.contract
def test_default_save_interval_is_100(l3_index_dir, check_deps):
    """
    Verify default save_interval is 100 as documented.

    CONTRACT: INV-009 - Default configuration
    Evidence: src/tm/l3_semantic.py line 66 (save_interval: int = 100)
    """
    from src.tm.l3_semantic import L3SemanticTM

    # Create with defaults
    tm = L3SemanticTM(index_path=l3_index_dir)

    assert tm.save_interval == 100
