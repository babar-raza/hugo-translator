"""Unit tests for engine content hash integration."""

import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock


def test_should_skip_translation_with_hash_enabled(tmp_path):
    """Test _should_skip_translation uses content hash when enabled."""
    from src.translation_engine.engine import TranslationEngine
    from src.utils.metadata_tracker import MetadataTracker

    # Create test file
    source_file = tmp_path / "source.md"
    output_file = tmp_path / "output.md"
    source_file.write_text("# Test")
    output_file.write_text("# Prueba")

    # Mock engine with content hash enabled
    engine = Mock(spec=TranslationEngine)
    engine.enable_content_hash = True
    engine.metadata_tracker = MetadataTracker(
        tmp_path / "metadata.json", hash_algorithm="md5"
    )
    engine.metadata_tracker.load()

    # Record initial hash
    engine.metadata_tracker.update_source(source_file)

    # Create real method
    from src.translation_engine.engine import TranslationEngine as RealEngine
    method = RealEngine._should_skip_translation

    # Call with content unchanged
    should_skip, reason = method(
        engine, source_file, output_file, force_retranslate=False, use_mtime_check=True
    )

    # Should skip because content unchanged
    assert should_skip is True
    assert "unchanged" in reason


def test_should_skip_translation_with_hash_disabled(tmp_path):
    """Test _should_skip_translation falls back to mtime when hash disabled."""
    from src.translation_engine.engine import TranslationEngine

    # Create test file
    source_file = tmp_path / "source.md"
    output_file = tmp_path / "output.md"
    source_file.write_text("# Test")
    output_file.write_text("# Prueba")

    # Mock engine with content hash disabled
    engine = Mock(spec=TranslationEngine)
    engine.enable_content_hash = False
    engine.metadata_tracker = None

    # Create real method
    from src.translation_engine.engine import TranslationEngine as RealEngine
    method = RealEngine._should_skip_translation

    # Call
    should_skip, reason = method(
        engine, source_file, output_file, force_retranslate=False, use_mtime_check=True
    )

    # Should skip based on mtime (output exists and valid)
    assert should_skip is True
    assert "mtime" in reason


def test_should_skip_translation_content_changed(tmp_path):
    """Test _should_skip_translation detects content changes."""
    from src.translation_engine.engine import TranslationEngine
    from src.utils.metadata_tracker import MetadataTracker

    # Create test file
    source_file = tmp_path / "source.md"
    output_file = tmp_path / "output.md"
    source_file.write_text("# Test")
    output_file.write_text("# Prueba")

    # Mock engine with content hash enabled
    engine = Mock(spec=TranslationEngine)
    engine.enable_content_hash = True
    engine.metadata_tracker = MetadataTracker(
        tmp_path / "metadata.json", hash_algorithm="md5"
    )
    engine.metadata_tracker.load()

    # Record initial hash
    engine.metadata_tracker.update_source(source_file)

    # Modify source content
    source_file.write_text("# Test Modified")

    # Create real method
    from src.translation_engine.engine import TranslationEngine as RealEngine
    method = RealEngine._should_skip_translation

    # Call
    should_skip, reason = method(
        engine, source_file, output_file, force_retranslate=False, use_mtime_check=True
    )

    # Should NOT skip because content changed
    assert should_skip is False
    assert "changed" in reason


def test_should_skip_translation_force_retranslate(tmp_path):
    """Test force_retranslate bypasses all checks."""
    from src.translation_engine.engine import TranslationEngine

    # Create test file
    source_file = tmp_path / "source.md"
    output_file = tmp_path / "output.md"
    source_file.write_text("# Test")
    output_file.write_text("# Prueba")

    # Mock engine
    engine = Mock(spec=TranslationEngine)
    engine.enable_content_hash = True
    engine.metadata_tracker = Mock()

    # Create real method
    from src.translation_engine.engine import TranslationEngine as RealEngine
    method = RealEngine._should_skip_translation

    # Call with force=True
    should_skip, reason = method(
        engine, source_file, output_file, force_retranslate=True, use_mtime_check=True
    )

    # Should NOT skip (force retranslate)
    assert should_skip is False
    assert "force" in reason


def test_should_skip_translation_output_missing(tmp_path):
    """Test missing output triggers translation."""
    from src.translation_engine.engine import TranslationEngine

    # Create only source file
    source_file = tmp_path / "source.md"
    output_file = tmp_path / "output.md"
    source_file.write_text("# Test")

    # Mock engine
    engine = Mock(spec=TranslationEngine)
    engine.enable_content_hash = True
    engine.metadata_tracker = Mock()

    # Create real method
    from src.translation_engine.engine import TranslationEngine as RealEngine
    method = RealEngine._should_skip_translation

    # Call
    should_skip, reason = method(
        engine, source_file, output_file, force_retranslate=False, use_mtime_check=True
    )

    # Should NOT skip (output missing)
    assert should_skip is False
    assert "not exist" in reason
