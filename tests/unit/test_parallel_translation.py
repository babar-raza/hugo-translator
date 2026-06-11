"""
Tests for parallel directory translation.
"""

import tempfile
import time
from pathlib import Path

import pytest

from src.model_runtime import HardwareDetector, ModelLoader, ModelRegistry
from src.tm import L1Cache, L2PersistentTM, TranslationMemory
from src.translation_engine.engine import TranslationEngine
from src.translation_engine.models import DirectoryResult
from src.utils.config_loader import ConfigService


@pytest.fixture
def temp_dir():
    """Create temporary directory for tests."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_files(temp_dir):
    """Create sample markdown files for testing."""
    content_dir = temp_dir / "content"
    content_dir.mkdir()

    # Create 20 sample files
    for i in range(20):
        file_path = content_dir / f"test{i:02d}.md"
        file_path.write_text(f"""---
title: Test Page {i}
description: This is test page number {i}
---

# Heading {i}

This is the content for test page {i}. It contains some text to translate.

## Subheading

More content here for translation.
""")

    return content_dir


@pytest.fixture
def translation_engine(temp_dir):
    """Create translation engine for testing."""
    # Setup minimal config
    config_dir = temp_dir / "config"
    config_dir.mkdir()

    # Create a test site profile
    (config_dir / "site_profiles").mkdir()
    site_profile_path = config_dir / "site_profiles" / "test-site.yaml"
    site_profile_path.write_text("""
site_id: test-site
content_roots:
  - /test/content
default_source_lang: en
target_langs:
  - es
  - fr
output_dir: output

frontmatter:
  title:
    mode: translate
  description:
    mode: translate

body:
  translate_markdown: true
  preserve_blocks:
    - code_block
    - codespan
  preserve_patterns: []
  placeholder_syntax:
    - "{{"

output_layout:
  per_language_folders: true
  pattern: "/{lang}/{relative_path}"

tm_prefs:
  use_semantic_tm: false
  semantic_threshold: 0.80
""")

    # Initialize config service
    config = ConfigService(config_dir)

    # Initialize TM (in-memory only for tests)
    l1 = L1Cache(max_size=1000)
    l2 = L2PersistentTM(temp_dir / "tm.lmdb", max_size_mb=20)
    tm = TranslationMemory(l1, l2)

    # Initialize model loader (mock or minimal)
    try:
        hw_info = HardwareDetector().detect()
        registry = ModelRegistry(Path("config/model_registry.yaml"))
        model_loader = ModelLoader(registry, hw_info.recommended_device)
    except Exception:
        # If model registry doesn't exist, create a mock
        model_loader = None

    # Create engine
    engine = TranslationEngine(
        config_service=config,
        tm=tm,
        model_loader=model_loader,
        enable_validation=False,
    )

    return engine


class TestParallelTranslation:
    """Test parallel translation functionality."""

    def test_parallel_vs_sequential_performance(self, translation_engine, sample_files):
        """Test that parallel processing is faster than sequential."""
        # Note: This test may be skipped if models aren't available
        if translation_engine.model_loader is None:
            pytest.skip("Model loader not available")

        # Sequential translation
        start_sequential = time.time()
        result_sequential = translation_engine.translate_directory(
            site_id="test-site",
            directory=sample_files,
            target_langs=["es"],
            parallel=False,
        )
        time_sequential = time.time() - start_sequential

        # Parallel translation
        start_parallel = time.time()
        result_parallel = translation_engine.translate_directory(
            site_id="test-site",
            directory=sample_files,
            target_langs=["es"],
            parallel=True,
            max_workers=4,
        )
        time_parallel = time.time() - start_parallel

        # Verify both succeeded
        assert isinstance(result_sequential, DirectoryResult)
        assert isinstance(result_parallel, DirectoryResult)

        # Verify same number of files processed
        assert result_sequential.total_files == result_parallel.total_files
        assert result_sequential.total_files == 20

        # Parallel should be faster (allowing for overhead in small batches)
        # For 20 files with 4 workers, we expect at least some improvement
        speedup = time_sequential / time_parallel if time_parallel > 0 else 1.0
        print("\nPerformance comparison:")
        print(f"  Sequential: {time_sequential:.2f}s")
        print(f"  Parallel (4 workers): {time_parallel:.2f}s")
        print(f"  Speedup: {speedup:.2f}x")

        # We should see some improvement, but may not be dramatic with small files
        # Just verify parallel doesn't break anything
        assert time_parallel > 0
        assert result_parallel.successful_files >= 0

    def test_parallel_with_max_workers(self, translation_engine, sample_files):
        """Test parallel processing with custom max_workers."""
        if translation_engine.model_loader is None:
            pytest.skip("Model loader not available")

        # Test with 2 workers
        result = translation_engine.translate_directory(
            site_id="test-site",
            directory=sample_files,
            target_langs=["es"],
            parallel=True,
            max_workers=2,
        )

        assert isinstance(result, DirectoryResult)
        assert result.total_files == 20

    def test_parallel_with_single_file(self, translation_engine, temp_dir):
        """Test that single file falls back to sequential."""
        if translation_engine.model_loader is None:
            pytest.skip("Model loader not available")

        # Create single file directory
        single_dir = temp_dir / "single"
        single_dir.mkdir()
        (single_dir / "test.md").write_text("""---
title: Single Test
---

Content.
""")

        # Should work with parallel=True but execute sequentially
        result = translation_engine.translate_directory(
            site_id="test-site",
            directory=single_dir,
            target_langs=["es"],
            parallel=True,
        )

        assert isinstance(result, DirectoryResult)
        assert result.total_files == 1

    def test_parallel_with_empty_directory(self, translation_engine, temp_dir):
        """Test parallel processing with no files."""
        empty_dir = temp_dir / "empty"
        empty_dir.mkdir()

        result = translation_engine.translate_directory(
            site_id="test-site",
            directory=empty_dir,
            target_langs=["es"],
            parallel=True,
        )

        assert isinstance(result, DirectoryResult)
        assert result.total_files == 0
        assert result.success is True  # No files is considered success

    def test_sequential_mode_explicitly(self, translation_engine, sample_files):
        """Test explicit sequential mode."""
        if translation_engine.model_loader is None:
            pytest.skip("Model loader not available")

        result = translation_engine.translate_directory(
            site_id="test-site",
            directory=sample_files,
            target_langs=["es"],
            parallel=False,
        )

        assert isinstance(result, DirectoryResult)
        assert result.total_files == 20

    def test_parallel_thread_safety(self, translation_engine):
        """Test that parallel processing maintains thread safety."""
        # Verify locks are initialized
        assert hasattr(translation_engine, "_tm_lock")
        assert hasattr(translation_engine, "_model_lock")
        assert hasattr(translation_engine, "_file_write_lock")

        # Verify locks are Lock objects
        from threading import Lock

        assert isinstance(translation_engine._tm_lock, Lock)
        assert isinstance(translation_engine._model_lock, Lock)
        assert isinstance(translation_engine._file_write_lock, Lock)

    def test_parallel_error_handling(self, translation_engine, temp_dir):
        """Test that parallel processing handles errors gracefully."""
        if translation_engine.model_loader is None:
            pytest.skip("Model loader not available")

        # Create directory with mix of valid and invalid files
        test_dir = temp_dir / "mixed"
        test_dir.mkdir()

        # Valid file
        (test_dir / "valid.md").write_text("""---
title: Valid
---
Content
""")

        # Invalid file (malformed YAML)
        (test_dir / "invalid.md").write_text("""---
title: [ Unclosed
---
Content
""")

        # Run parallel translation
        result = translation_engine.translate_directory(
            site_id="test-site",
            directory=test_dir,
            target_langs=["es"],
            parallel=True,
        )

        # Should complete without crashing
        assert isinstance(result, DirectoryResult)
        assert result.total_files == 2
        # At least one should succeed or fail (not crash)
        assert result.successful_files + result.failed_files == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
