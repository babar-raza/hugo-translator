"""
CONTRACT: specs/core_invariants.md

Verifies that resume functionality correctly skips already-completed translations,
preventing duplicate work after crash recovery.

INV-007 Core Invariant: Resume Skips Completed Files

Key Guarantees:
1. Files marked as completed are skipped on resume
2. Partially completed files only skip completed languages
3. Progress state persists across tracker instances
4. get_pending() returns only uncompleted work
5. Completion tracking is per-file, per-language
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.translation_engine.progress import ProgressTracker

# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def progress_dir(tmp_path):
    """Temporary directory for progress files."""
    pdir = tmp_path / ".translation_progress"
    pdir.mkdir()
    return pdir


@pytest.fixture
def sample_files(tmp_path):
    """Create sample markdown files for testing."""
    content_dir = tmp_path / "content"
    content_dir.mkdir()

    files = []
    for i in range(3):
        f = content_dir / f"file{i}.md"
        f.write_text(f"# File {i}\n\nContent for file {i}.")
        files.append(f)

    return files


@pytest.fixture
def tracker(progress_dir, sample_files):
    """ProgressTracker instance with sample files initialized."""
    tracker = ProgressTracker(
        progress_dir=progress_dir,
        site_id="test-site",
        source_dir=sample_files[0].parent,
        output_dir=Path("/output"),
        target_langs=["es", "de", "fr"],
    )
    tracker.initialize(sample_files)
    return tracker


# ==============================================================================
# INV-007: Completed Files Skip Tests
# ==============================================================================


@pytest.mark.contract
def test_completed_file_excluded_from_pending(tracker, sample_files):
    """
    Verify completed file+lang pairs are excluded from pending list.

    CONTRACT: INV-007 - Completed files skipped on resume
    Evidence: src/translation_engine/progress.py lines 289-309 (get_pending)
    """
    # Mark first file as completed for Spanish
    tracker.mark_completed(sample_files[0], "es")

    # Get pending work
    pending = tracker.get_pending(sample_files)

    # Should NOT include (file0, es)
    pending_set = set((str(p[0]), p[1]) for p in pending)
    assert (str(sample_files[0]), "es") not in pending_set

    # But should include (file0, de) and (file0, fr)
    assert (str(sample_files[0]), "de") in pending_set
    assert (str(sample_files[0]), "fr") in pending_set


@pytest.mark.contract
def test_all_langs_completed_file_fully_excluded(tracker, sample_files):
    """
    Verify file with all languages completed has no pending work.

    CONTRACT: INV-007 - File fully completed = no pending
    Evidence: src/translation_engine/progress.py lines 303-307
    """
    # Mark all languages for first file as completed
    tracker.mark_completed(sample_files[0], "es")
    tracker.mark_completed(sample_files[0], "de")
    tracker.mark_completed(sample_files[0], "fr")

    # Get pending work
    pending = tracker.get_pending(sample_files)

    # Should NOT include file0 for any language
    pending_files = set(str(p[0]) for p in pending)
    assert str(sample_files[0]) not in pending_files

    # Other files should still be pending
    assert str(sample_files[1]) in pending_files
    assert str(sample_files[2]) in pending_files


@pytest.mark.contract
def test_partial_completion_preserves_pending_langs(tracker, sample_files):
    """
    Verify partially completed file still has pending languages.

    CONTRACT: INV-007 - Partial completion tracking
    Evidence: src/translation_engine/progress.py lines 247-251 (mark_completed)
    """
    # Mark only Spanish completed for file0
    tracker.mark_completed(sample_files[0], "es")

    # Get pending for file0
    pending = tracker.get_pending(sample_files)
    file0_pending_langs = [p[1] for p in pending if str(p[0]) == str(sample_files[0])]

    # Spanish should NOT be pending
    assert "es" not in file0_pending_langs
    # German and French should still be pending
    assert "de" in file0_pending_langs
    assert "fr" in file0_pending_langs


# ==============================================================================
# INV-007: Progress Persistence Tests
# ==============================================================================


@pytest.mark.contract
def test_progress_persists_across_instances(progress_dir, sample_files):
    """
    Verify progress state persists when creating new tracker instance.

    CONTRACT: INV-007 - Progress persists for resume
    Evidence: src/translation_engine/progress.py lines 356-400 (find_latest)
    """
    # First tracker: mark some work complete
    tracker1 = ProgressTracker(
        progress_dir=progress_dir,
        site_id="persist-test",
        source_dir=sample_files[0].parent,
        output_dir=Path("/output"),
        target_langs=["es", "de"],
    )
    tracker1.initialize(sample_files)
    tracker1.mark_completed(sample_files[0], "es")
    tracker1.mark_completed(sample_files[1], "de")

    # Simulate crash - create new tracker via find_latest
    tracker2 = ProgressTracker.find_latest(progress_dir=progress_dir, site_id="persist-test")

    assert tracker2 is not None, "Should find existing progress"

    # Check completed state was preserved
    pending = tracker2.get_pending(sample_files)
    pending_set = set((str(p[0]), p[1]) for p in pending)

    # Previously completed work should still be excluded
    assert (str(sample_files[0]), "es") not in pending_set
    assert (str(sample_files[1]), "de") not in pending_set


@pytest.mark.contract
def test_completed_files_dict_structure(tracker, sample_files):
    """
    Verify completed_files dict has correct structure.

    CONTRACT: INV-007 - Completion tracking structure
    Evidence: src/translation_engine/progress.py line 62 (completed_files field)
    """
    # Mark completions
    tracker.mark_completed(sample_files[0], "es")
    tracker.mark_completed(sample_files[0], "de")
    tracker.mark_completed(sample_files[1], "fr")

    # Check structure
    completed = tracker.state.completed_files

    # Should be dict {file_path: [langs]}
    assert isinstance(completed, dict)

    file0_key = str(sample_files[0])
    file1_key = str(sample_files[1])

    assert file0_key in completed
    assert isinstance(completed[file0_key], list)
    assert "es" in completed[file0_key]
    assert "de" in completed[file0_key]

    assert file1_key in completed
    assert "fr" in completed[file1_key]


# ==============================================================================
# INV-007: Idempotency Tests
# ==============================================================================


@pytest.mark.contract
def test_marking_same_file_twice_is_idempotent(tracker, sample_files):
    """
    Verify marking same file+lang completed twice doesn't duplicate.

    CONTRACT: INV-007 - Idempotent completion marking
    Evidence: src/translation_engine/progress.py lines 250-251 (if lang not in check)
    """
    initial_count = tracker.state.translations_completed

    # Mark same file+lang twice
    tracker.mark_completed(sample_files[0], "es")
    after_first = tracker.state.translations_completed

    tracker.mark_completed(sample_files[0], "es")
    after_second = tracker.state.translations_completed

    # Count should only increment once
    assert after_first == initial_count + 1
    assert after_second == after_first  # No double-counting


@pytest.mark.contract
def test_get_pending_returns_consistent_results(tracker, sample_files):
    """
    Verify get_pending returns consistent results on repeated calls.

    CONTRACT: INV-007 - Consistent pending calculation
    Evidence: src/translation_engine/progress.py lines 289-309
    """
    # Mark some work complete
    tracker.mark_completed(sample_files[0], "es")

    # Call get_pending multiple times
    pending1 = tracker.get_pending(sample_files)
    pending2 = tracker.get_pending(sample_files)
    pending3 = tracker.get_pending(sample_files)

    # Should return same results
    assert len(pending1) == len(pending2) == len(pending3)

    set1 = set((str(p[0]), p[1]) for p in pending1)
    set2 = set((str(p[0]), p[1]) for p in pending2)
    set3 = set((str(p[0]), p[1]) for p in pending3)

    assert set1 == set2 == set3


# ==============================================================================
# INV-007: is_complete() Tests
# ==============================================================================


@pytest.mark.contract
def test_is_complete_false_when_pending_exists(tracker, sample_files):
    """
    Verify is_complete returns False when work remains.

    CONTRACT: INV-007 - Completion detection
    Evidence: src/translation_engine/progress.py lines 343-354 (is_complete)
    """
    # Mark only some completions
    tracker.mark_completed(sample_files[0], "es")

    # Should not be complete
    assert tracker.is_complete() is False


@pytest.mark.contract
def test_is_complete_true_when_all_done(tracker, sample_files):
    """
    Verify is_complete returns True when all work done.

    CONTRACT: INV-007 - Full completion detection
    Evidence: src/translation_engine/progress.py lines 343-354
    """
    # Mark all files for all languages as complete
    for f in sample_files:
        for lang in ["es", "de", "fr"]:
            tracker.mark_completed(f, lang)

    # Should be complete
    assert tracker.is_complete() is True


# ==============================================================================
# INV-007: Resume Statistics Tests
# ==============================================================================


@pytest.mark.contract
def test_statistics_reflect_completion_state(tracker, sample_files):
    """
    Verify statistics accurately reflect completion progress.

    CONTRACT: INV-007 - Accurate resume statistics
    Evidence: src/translation_engine/progress.py lines 311-335 (get_statistics)
    """
    # Mark some completions (2 out of 9 total: 3 files * 3 langs)
    tracker.mark_completed(sample_files[0], "es")
    tracker.mark_completed(sample_files[1], "de")

    stats = tracker.get_statistics()

    assert stats["translations_completed"] == 2
    assert stats["total_files"] == 3
    assert stats["translations_pending"] == 7  # 9 - 2


# ==============================================================================
# INV-007: Failed Files Interaction Tests
# ==============================================================================


@pytest.mark.contract
def test_completed_clears_failed_status(tracker, sample_files):
    """
    Verify marking completed clears any previous failed status.

    CONTRACT: INV-007 - Failed -> Completed transition
    Evidence: src/translation_engine/progress.py lines 254-258 (remove from failed)
    """
    # First mark as failed
    tracker.mark_failed(sample_files[0], "es", "Test error")
    assert "es" in tracker.state.failed_files.get(str(sample_files[0]), {})

    # Then mark as completed
    tracker.mark_completed(sample_files[0], "es")

    # Should no longer be in failed_files
    failed_langs = tracker.state.failed_files.get(str(sample_files[0]), {})
    assert "es" not in failed_langs

    # Should be in completed_files
    completed_langs = tracker.state.completed_files.get(str(sample_files[0]), [])
    assert "es" in completed_langs


# ==============================================================================
# INV-007: Edge Cases
# ==============================================================================


@pytest.mark.contract
def test_empty_files_list_returns_empty_pending(tracker):
    """
    Verify get_pending with empty files list returns empty.

    CONTRACT: INV-007 - Edge case handling
    Evidence: src/translation_engine/progress.py lines 289-309
    """
    pending = tracker.get_pending([])
    assert pending == []


@pytest.mark.contract
def test_new_files_appear_as_pending(tracker, sample_files, tmp_path):
    """
    Verify newly added files appear in pending list.

    CONTRACT: INV-007 - New file detection
    Evidence: src/translation_engine/progress.py lines 301-307
    """
    # Mark all original files complete
    for f in sample_files:
        for lang in ["es", "de", "fr"]:
            tracker.mark_completed(f, lang)

    # Add new file
    new_file = tmp_path / "content" / "new_file.md"
    new_file.write_text("# New Content")

    all_files = sample_files + [new_file]

    # Get pending with new file included
    pending = tracker.get_pending(all_files)

    # Only new file should be pending
    pending_files = set(str(p[0]) for p in pending)
    assert str(new_file) in pending_files
    assert len(pending) == 3  # 1 file * 3 languages
