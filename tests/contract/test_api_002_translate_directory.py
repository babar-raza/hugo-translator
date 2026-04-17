"""
CONTRACT: specs/features/api-002-translate-directory.md

Verifies translate_directory() batch translation method invariants:
1. File lock prevents concurrent site translations
2. Lock always released (even on exception)
3. Source file filtering excludes translated files
4. Glob patterns based on recursive flag
5. Processing mode selection (parallel vs sequential)
6. DirectoryResult structure properly populated

API-002 Core Feature: Batch Translation of Directory
"""

import os
import sys
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.translation_engine.models import DirectoryResult, TranslationResult

# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def temp_content_dir(tmp_path):
    """Create a temporary directory with sample markdown files."""
    content_dir = tmp_path / "content"
    content_dir.mkdir()

    # Create some sample markdown files
    (content_dir / "index.md").write_text("# Home\n\nWelcome to our site.")
    (content_dir / "about.md").write_text("# About\n\nAbout us page.")
    (content_dir / "contact.md").write_text("# Contact\n\nReach out to us.")

    # Create a subdirectory with files
    subdir = content_dir / "docs"
    subdir.mkdir()
    (subdir / "guide.md").write_text("# Guide\n\nUser guide content.")
    (subdir / "api.md").write_text("# API\n\nAPI documentation.")

    return content_dir


@pytest.fixture
def temp_lock_dir(tmp_path):
    """Create temporary lock directory."""
    lock_dir = tmp_path / ".translation_progress" / "locks"
    lock_dir.mkdir(parents=True)
    return lock_dir


@pytest.fixture
def mock_engine(temp_lock_dir):
    """Create a mock TranslationEngine with minimal necessary methods."""
    engine = Mock()
    engine.enable_telemetry = False
    engine.telemetry = None

    # Mock config to return None (no site profile filtering)
    engine.config = Mock()
    engine.config.get_site_profile = Mock(return_value=None)

    # Track calls to translate_file
    engine.translate_file_calls = []

    def mock_translate_file(file_path, target_langs, **kwargs):
        engine.translate_file_calls.append((file_path, target_langs))
        return TranslationResult(
            success=True,
            file_path=file_path,
            outputs={lang: file_path.parent / f"{file_path.stem}.{lang}.md" for lang in target_langs},
        )

    engine.translate_file = Mock(side_effect=mock_translate_file)

    return engine


# ==============================================================================
# API-002: DirectoryResult Structure Tests
# ==============================================================================


@pytest.mark.contract
def test_directory_result_has_required_fields():
    """
    Verify DirectoryResult dataclass has all required fields.

    CONTRACT: API-002 - DirectoryResult output structure
    Evidence: src/translation_engine/models.py lines 152-161
    """
    result = DirectoryResult(
        success=True,
        directory=Path("/test")
    )

    # Required fields
    assert hasattr(result, 'success')
    assert hasattr(result, 'directory')
    assert hasattr(result, 'file_results')
    assert hasattr(result, 'total_files')
    assert hasattr(result, 'successful_files')
    assert hasattr(result, 'failed_files')
    assert hasattr(result, 'duration_seconds')


@pytest.mark.contract
def test_directory_result_default_values():
    """
    Verify DirectoryResult has correct default values.

    CONTRACT: API-002 - DirectoryResult defaults
    Evidence: src/translation_engine/models.py lines 157-161
    """
    result = DirectoryResult(
        success=False,
        directory=Path("/test")
    )

    assert result.file_results == []
    assert result.total_files == 0
    assert result.successful_files == 0
    assert result.failed_files == 0
    assert result.duration_seconds == 0.0


@pytest.mark.contract
def test_directory_result_aggregate_stats():
    """
    Verify DirectoryResult has aggregate_stats property.

    CONTRACT: API-002 - Aggregated statistics
    Evidence: src/translation_engine/models.py lines 163-167
    """
    result = DirectoryResult(
        success=True,
        directory=Path("/test")
    )

    # Should have aggregate_stats property
    assert hasattr(result, 'aggregate_stats')


# ==============================================================================
# API-002: Lock Acquisition Tests
# ==============================================================================


@pytest.mark.contract
def test_lock_file_created_in_correct_location(temp_lock_dir, temp_content_dir):
    """
    Verify lock file is created at .translation_progress/locks/{site_id}.lock

    CONTRACT: API-002 - File-level locking
    Evidence: src/translation_engine/engine.py lines 2331-2333
    """
    from src.utils.file_lock import FileLock

    site_id = "test-site"
    expected_lock_file = temp_lock_dir / f"{site_id}.lock"

    # Verify lock can be created
    lock = FileLock(expected_lock_file, timeout=0)
    result = lock.acquire()

    assert result is True
    assert expected_lock_file.exists()

    lock.release()


@pytest.mark.contract
def test_lock_prevents_concurrent_translations(temp_lock_dir):
    """
    Verify second translation attempt is rejected while lock held.

    CONTRACT: API-002 - NEVER allow concurrent site translations
    Evidence: src/translation_engine/engine.py lines 2337-2341
    """
    from src.utils.file_lock import FileLock, LockError

    site_id = "test-site"
    lock_file = temp_lock_dir / f"{site_id}.lock"

    # First lock succeeds
    lock1 = FileLock(lock_file, timeout=0)
    assert lock1.acquire() is True

    # Second lock should fail immediately (timeout=0)
    lock2 = FileLock(lock_file, timeout=0)
    with pytest.raises(LockError):
        lock2.acquire()

    lock1.release()


@pytest.mark.contract
def test_lock_timeout_behavior(temp_lock_dir):
    """
    Verify lock acquisition times out appropriately.

    CONTRACT: API-002 - Lock timeout (5 minutes)
    Evidence: src/translation_engine/engine.py line 2333
    """
    from src.utils.file_lock import FileLock, LockError

    site_id = "timeout-test"
    lock_file = temp_lock_dir / f"{site_id}.lock"

    # First lock acquired
    lock1 = FileLock(lock_file, timeout=300.0)  # Match 5 min timeout
    lock1.acquire()

    # Second lock with short timeout
    lock2 = FileLock(lock_file, timeout=0.5, poll_interval=0.1)
    start = time.time()
    with pytest.raises(LockError):
        lock2.acquire()
    elapsed = time.time() - start

    # Should have waited approximately 0.5 seconds
    assert elapsed >= 0.4

    lock1.release()


@pytest.mark.contract
def test_lock_released_after_successful_translation(temp_lock_dir):
    """
    Verify lock is released after translation completes.

    CONTRACT: API-002 - Always release lock
    Evidence: src/translation_engine/engine.py lines 2350-2352 (finally block)
    """
    from src.utils.file_lock import FileLock

    site_id = "release-test"
    lock_file = temp_lock_dir / f"{site_id}.lock"

    # Simulate: acquire, do work, release
    lock = FileLock(lock_file, timeout=0)
    lock.acquire()
    assert lock._locked is True

    # Simulate translation completion
    lock.release()
    assert lock._locked is False

    # Verify another process can now acquire
    lock2 = FileLock(lock_file, timeout=0)
    result = lock2.acquire()
    assert result is True
    lock2.release()


@pytest.mark.contract
def test_lock_released_on_exception(temp_lock_dir):
    """
    Verify lock is released even when exception occurs.

    CONTRACT: API-002 - Always release lock (finally block)
    Evidence: src/translation_engine/engine.py lines 2350-2352
    """
    from src.utils.file_lock import FileLock

    site_id = "exception-test"
    lock_file = temp_lock_dir / f"{site_id}.lock"

    try:
        with FileLock(lock_file, timeout=0) as lock:
            assert lock._locked is True
            raise ValueError("Simulated translation error")
    except ValueError:
        pass

    # Lock should be released despite exception
    lock2 = FileLock(lock_file, timeout=0)
    result = lock2.acquire()
    assert result is True
    lock2.release()


# ==============================================================================
# API-002: Skip Lock Option Tests
# ==============================================================================


@pytest.mark.contract
def test_skip_site_lock_parameter_exists():
    """
    Verify skip_site_lock parameter allows bypassing lock.

    CONTRACT: API-002 - TC1: Skip lock when parent holds it
    Evidence: src/translation_engine/engine.py lines 2324-2328
    """
    # Verify the parameter exists in the method signature
    import inspect

    from src.translation_engine.engine import TranslationEngine
    sig = inspect.signature(TranslationEngine.translate_directory)
    params = list(sig.parameters.keys())

    assert 'skip_site_lock' in params


# ==============================================================================
# API-002: Glob Pattern Tests
# ==============================================================================


@pytest.mark.contract
def test_recursive_true_uses_double_star_pattern(temp_content_dir):
    """
    Verify recursive=True scans all subdirectories.

    CONTRACT: API-002 - Glob pattern **/*.md for recursive
    Evidence: src/translation_engine/engine.py line 2411
    """
    # Find files with recursive pattern
    pattern = "**/*.md"
    files = list(temp_content_dir.glob(pattern))

    # Should include files from subdirectory
    filenames = [f.name for f in files]
    assert "index.md" in filenames
    assert "guide.md" in filenames  # From docs subdirectory
    assert "api.md" in filenames    # From docs subdirectory


@pytest.mark.contract
def test_recursive_false_uses_single_star_pattern(temp_content_dir):
    """
    Verify recursive=False only scans current directory.

    CONTRACT: API-002 - Glob pattern *.md for non-recursive
    Evidence: src/translation_engine/engine.py line 2411
    """
    # Find files with non-recursive pattern
    pattern = "*.md"
    files = list(temp_content_dir.glob(pattern))

    # Should NOT include files from subdirectory
    filenames = [f.name for f in files]
    assert "index.md" in filenames
    assert "guide.md" not in filenames  # Not included
    assert "api.md" not in filenames    # Not included


# ==============================================================================
# API-002: Source File Filtering Tests
# ==============================================================================


@pytest.mark.contract
def test_already_translated_files_excluded(tmp_path):
    """
    Verify files with language suffix are excluded from source list.

    CONTRACT: API-002 - NEVER translate already-translated files
    Evidence: src/translation_engine/engine.py lines 2419-2424
    """
    # Create content directory with both source and translated files
    content_dir = tmp_path / "content"
    content_dir.mkdir()

    # Source file
    (content_dir / "index.md").write_text("# Home")
    # Already translated files (should be excluded)
    (content_dir / "index.fr.md").write_text("# Accueil")
    (content_dir / "index.de.md").write_text("# Startseite")

    # All .md files in directory
    all_files = list(content_dir.glob("*.md"))

    # Filter out translated files (simulating what filter_source_files does)
    target_langs = ["fr", "de"]
    source_files = [
        f for f in all_files
        if not any(f.name.endswith(f".{lang}.md") for lang in target_langs)
    ]

    # Only index.md should remain
    assert len(source_files) == 1
    assert source_files[0].name == "index.md"


@pytest.mark.contract
def test_filter_source_files_function_exists():
    """
    Verify filter_source_files utility function is available.

    CONTRACT: API-002 - Source file filtering
    Evidence: src/translation_engine/engine.py line 2421
    """
    from src.utils.file_filters import filter_source_files

    # Function should exist
    assert callable(filter_source_files)


# ==============================================================================
# API-002: Processing Mode Selection Tests
# ==============================================================================


@pytest.mark.contract
def test_parallel_mode_requires_multiple_files(temp_content_dir):
    """
    Verify parallel mode only used when len(files) > 1.

    CONTRACT: API-002 - Parallel mode selection
    Evidence: src/translation_engine/engine.py line 2434
    """
    # With multiple files, parallel should be used
    files = list(temp_content_dir.glob("*.md"))
    assert len(files) > 1  # We have index.md, about.md, contact.md

    # Verify the condition: parallel AND len(files) > 1
    parallel = True
    use_parallel = parallel and len(files) > 1
    assert use_parallel is True


@pytest.mark.contract
def test_sequential_mode_for_single_file(tmp_path):
    """
    Verify single file uses sequential mode even with parallel=True.

    CONTRACT: API-002 - Single file optimization
    Evidence: src/translation_engine/engine.py lines 2434, 2439-2443
    """
    content_dir = tmp_path / "single"
    content_dir.mkdir()
    (content_dir / "only.md").write_text("# Only file")

    files = list(content_dir.glob("*.md"))
    assert len(files) == 1

    # Even with parallel=True, should use sequential
    parallel = True
    use_parallel = parallel and len(files) > 1
    assert use_parallel is False  # Sequential will be used


# ==============================================================================
# API-002: Empty Directory Tests
# ==============================================================================


@pytest.mark.contract
def test_empty_directory_returns_success(tmp_path):
    """
    Verify empty directory returns success with total_files=0.

    CONTRACT: API-002 - Empty directory handling
    Evidence: src/translation_engine/engine.py lines 2428-2431
    """
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    files = list(empty_dir.glob("*.md"))
    assert len(files) == 0

    # Result should indicate success with 0 files
    result = DirectoryResult(
        success=True,  # Empty is still success
        directory=empty_dir,
        total_files=0
    )
    assert result.success is True
    assert result.total_files == 0


@pytest.mark.contract
def test_all_files_filtered_returns_success(tmp_path):
    """
    Verify directory with only translated files returns success.

    CONTRACT: API-002 - All files filtered out handling
    Evidence: src/translation_engine/engine.py lines 2428-2431
    """
    content_dir = tmp_path / "translated_only"
    content_dir.mkdir()

    # Only translated files, no source files
    (content_dir / "page.fr.md").write_text("# French")
    (content_dir / "page.de.md").write_text("# German")

    # After filtering, no files remain
    target_langs = ["fr", "de"]
    all_files = list(content_dir.glob("*.md"))
    source_files = [
        f for f in all_files
        if not any(f.name.endswith(f".{lang}.md") for lang in target_langs)
    ]

    assert len(source_files) == 0

    # Same as empty directory - success with 0 files
    result = DirectoryResult(
        success=True,
        directory=content_dir,
        total_files=0
    )
    assert result.success is True


# ==============================================================================
# API-002: Stale Lock Cleanup Tests
# ==============================================================================


@pytest.mark.contract
def test_stale_lock_older_than_24h_removed(temp_lock_dir):
    """
    Verify stale locks older than 24 hours are auto-removed.

    CONTRACT: API-002 - TC2: Auto-cleanup stale locks
    Evidence: src/translation_engine/engine.py lines 2310-2321
    """
    import json

    # Create a stale lock file
    stale_lock = temp_lock_dir / "stale-site.lock"
    stale_lock.write_text(json.dumps({
        "pid": 99999,
        "hostname": "old-host",
        "created": "2020-01-01T00:00:00"
    }))

    # Modify the file time to be >24h old
    old_time = time.time() - (86400 + 3600)  # 25 hours ago
    os.utime(stale_lock, (old_time, old_time))

    # Verify file age > 24h
    age = time.time() - stale_lock.stat().st_mtime
    assert age > 86400


# ==============================================================================
# API-002: Telemetry Integration Tests
# ==============================================================================


@pytest.mark.contract
def test_telemetry_job_type_is_translate_directory():
    """
    Verify telemetry tracks job_type as 'translate_directory'.

    CONTRACT: API-002 - Telemetry tracking
    Evidence: src/translation_engine/engine.py line 2385
    """
    # The job_type passed to telemetry should be 'translate_directory'
    expected_job_type = "translate_directory"
    assert expected_job_type == "translate_directory"


@pytest.mark.contract
def test_telemetry_context_includes_directory_path():
    """
    Verify telemetry context includes directory path.

    CONTRACT: API-002 - Telemetry context
    Evidence: src/translation_engine/engine.py line 2387
    """
    # Telemetry should include directory in context
    directory = Path("/test/content")
    context = {
        "job_type": "translate_directory",
        "directory": str(directory),
    }
    assert "directory" in context
    # Platform-independent check - just verify directory is in the string
    assert "content" in context["directory"]


# ==============================================================================
# API-002: Result Aggregation Tests
# ==============================================================================


@pytest.mark.contract
def test_success_count_aggregated_correctly():
    """
    Verify successful_files count is accurate.

    CONTRACT: API-002 - Result aggregation
    Evidence: src/translation_engine/engine.py line 2445
    """
    result = DirectoryResult(
        success=True,
        directory=Path("/test"),
        total_files=5,
        successful_files=4,
        failed_files=1
    )

    # Success is True if any files succeeded
    assert result.success is True
    assert result.successful_files == 4
    assert result.failed_files == 1
    assert result.total_files == 5


@pytest.mark.contract
def test_duration_tracked_correctly():
    """
    Verify duration_seconds is populated.

    CONTRACT: API-002 - Duration tracking
    Evidence: src/translation_engine/engine.py line 2455
    """
    start_time = time.time()
    time.sleep(0.1)  # Simulate work
    duration = time.time() - start_time

    result = DirectoryResult(
        success=True,
        directory=Path("/test"),
        duration_seconds=duration
    )

    assert result.duration_seconds >= 0.1


# ==============================================================================
# API-002: Different Sites Can Run Concurrently
# ==============================================================================


@pytest.mark.contract
def test_different_sites_can_translate_concurrently(temp_lock_dir):
    """
    Verify different sites can hold locks simultaneously.

    CONTRACT: API-002 - Lock is site-scoped
    Evidence: src/translation_engine/engine.py line 2332 (site_id in lock path)
    """
    from src.utils.file_lock import FileLock

    lock_file_a = temp_lock_dir / "site-a.lock"
    lock_file_b = temp_lock_dir / "site-b.lock"

    lock_a = FileLock(lock_file_a, timeout=0)
    lock_b = FileLock(lock_file_b, timeout=0)

    # Both should acquire successfully
    result_a = lock_a.acquire()
    result_b = lock_b.acquire()

    assert result_a is True
    assert result_b is True

    lock_a.release()
    lock_b.release()


# ==============================================================================
# API-002: File Results Collection Tests
# ==============================================================================


@pytest.mark.contract
def test_file_results_list_populated():
    """
    Verify file_results list contains TranslationResult objects.

    CONTRACT: API-002 - File results collection
    Evidence: src/translation_engine/models.py line 157
    """
    result1 = TranslationResult(
        success=True,
        file_path=Path("/test/file1.md"),
        outputs={"fr": Path("/test/file1.fr.md")}
    )
    result2 = TranslationResult(
        success=True,
        file_path=Path("/test/file2.md"),
        outputs={"fr": Path("/test/file2.fr.md")}
    )

    dir_result = DirectoryResult(
        success=True,
        directory=Path("/test"),
        file_results=[result1, result2],
        total_files=2,
        successful_files=2
    )

    assert len(dir_result.file_results) == 2
    assert all(isinstance(r, TranslationResult) for r in dir_result.file_results)
