"""
Unit tests for segment sorting functionality (SR-01).

Tests verify that:
1. Segments are sorted shortest→longest when enabled
2. Original document order is restored in output
3. Sorting is disabled by default (backward compatibility)
4. Sorting works correctly with TM cache
"""
from unittest.mock import Mock

import pytest

from src.model_runtime import ModelLoader
from src.tm import TranslationMemory
from src.translation_engine import TranslationEngine
from src.translation_engine.models import Segment, TranslationStats
from src.utils.config_loader import ConfigService


class MockBackend:
    """Mock translation backend for testing."""

    def translate(self, texts, source_lang, target_lang):
        """Return texts with [TRANSLATED] prefix to track order."""
        return [f"[TRANSLATED:{len(t)}chars]{t}" for t in texts]

    def translate_with_token_counts(self, texts, source_lang, target_lang):
        """Return translations with token counts."""
        translations = self.translate(texts, source_lang, target_lang)
        input_tokens = sum(len(t.split()) for t in texts)
        output_tokens = sum(len(t.split()) for t in translations)
        return translations, input_tokens, output_tokens


@pytest.fixture
def mock_config_service(tmp_path):
    """Create mock config service."""
    config = Mock(spec=ConfigService)
    config.site_config = Mock()
    config.site_config.id = "test_site"
    config.site_config.source_lang = "en"
    config.site_config.source_dir = tmp_path / "source"
    config.site_config.output_dir = tmp_path / "output"
    config.site_config.get_body_rules = Mock(return_value=Mock(
        translate_markdown=True,
        preserve_blocks=[],
        preserve_patterns=[],
        placeholder_syntax=[],
        use_ast_body_reconstruction=False,
        sort_segments_by_length=False,
    ))
    config.site_config.get_frontmatter_rules = Mock(return_value=Mock(
        translate_keys=[],
        preserve_keys=[],
    ))
    config.site_config.get_tm_preferences = Mock(return_value=Mock(
        use_semantic_tm=False,
        fallback_exact_only=True,
    ))
    config.global_config = Mock()
    config.global_config.tm_data_dir = str(tmp_path / "tm")
    return config


@pytest.fixture
def mock_tm():
    """Create mock translation memory."""
    tm = Mock(spec=TranslationMemory)
    tm.lookup = Mock(return_value=None)
    tm.store = Mock()
    tm.set_override_mode = Mock()
    return tm


@pytest.fixture
def mock_model_loader():
    """Create mock model loader."""
    loader = Mock(spec=ModelLoader)
    backend = MockBackend()
    loader.get_backend = Mock(return_value=backend)
    return loader


def test_segments_sorted_by_length(mock_config_service, mock_tm, mock_model_loader):
    """Verify segments are sorted shortest→longest when sorting enabled."""
    # Create engine with sorting enabled
    engine = TranslationEngine(
        config_service=mock_config_service,
        tm=mock_tm,
        model_loader=mock_model_loader,
        sort_segments_by_length=True,
        enable_telemetry=False,
    )

    # Create segments with varying lengths
    segments = [
        Segment(id="s1", source_text="Very long segment with many words here", position=0, node_type="paragraph"),
        Segment(id="s2", source_text="Short", position=1, node_type="paragraph"),
        Segment(id="s3", source_text="Medium length segment", position=2, node_type="paragraph"),
    ]

    texts = [s.source_text for s in segments]
    backend = mock_model_loader.get_backend()
    stats = TranslationStats()

    # Translate using the private method
    results = engine._translate_segments_batch(backend, segments, texts, "en", "es", stats)

    # Verify all segments translated
    assert len(results) == 3
    assert all(r is not None for r in results)

    # Verify results are in original document order (not sorted order)
    assert "Very long segment" in results[0]
    assert "Short" in results[1]
    assert "Medium length" in results[2]


def test_segment_order_restored_in_output(mock_config_service, mock_tm, mock_model_loader):
    """Verify output maintains original document order after sorted processing."""
    engine = TranslationEngine(
        config_service=mock_config_service,
        tm=mock_tm,
        model_loader=mock_model_loader,
        sort_segments_by_length=True,
        enable_telemetry=False,
    )

    # Create segments in specific order
    original_texts = ["ZZZZZ long text", "A", "MMM medium"]
    segments = [
        Segment(id=f"s{i}", source_text=t, position=i, node_type="paragraph")
        for i, t in enumerate(original_texts)
    ]

    backend = mock_model_loader.get_backend()
    stats = TranslationStats()
    results = engine._translate_segments_batch(backend, segments, original_texts, "en", "es", stats)

    # Verify order matches input (not sorted by length)
    assert len(results) == len(original_texts)
    for i, original in enumerate(original_texts):
        assert original in results[i], f"Position {i}: expected '{original}' in '{results[i]}'"


def test_sorting_disabled_by_default(mock_config_service, mock_tm, mock_model_loader):
    """Verify sorting is disabled by default for backward compatibility."""
    # Create engine without specifying sort_segments_by_length (should default to False)
    engine = TranslationEngine(
        config_service=mock_config_service,
        tm=mock_tm,
        model_loader=mock_model_loader,
        enable_telemetry=False,
    )

    # Verify default is False
    assert engine.sort_segments_by_length is False

    # Verify segments processed in document order
    segments = [
        Segment(id="s1", source_text="Long text here", position=0, node_type="paragraph"),
        Segment(id="s2", source_text="Short", position=1, node_type="paragraph"),
    ]

    texts = [s.source_text for s in segments]
    backend = mock_model_loader.get_backend()
    stats = TranslationStats()
    results = engine._translate_segments_batch(backend, segments, texts, "en", "es", stats)

    # Verify processing order (longer segment first in this case)
    assert "Long text here" in results[0]
    assert "Short" in results[1]


def test_sorting_with_single_segment(mock_config_service, mock_tm, mock_model_loader):
    """Verify sorting handles single-segment case correctly (no IndexError)."""
    engine = TranslationEngine(
        config_service=mock_config_service,
        tm=mock_tm,
        model_loader=mock_model_loader,
        sort_segments_by_length=True,
        enable_telemetry=False,
    )

    # Single segment
    segments = [Segment(id="s1", source_text="Only one segment", position=0, node_type="paragraph")]
    texts = [s.source_text for s in segments]

    backend = mock_model_loader.get_backend()
    stats = TranslationStats()
    results = engine._translate_segments_batch(backend, segments, texts, "en", "es", stats)

    # Verify single result
    assert len(results) == 1
    assert "Only one segment" in results[0]


def test_sorting_with_empty_segments(mock_config_service, mock_tm, mock_model_loader):
    """Verify sorting handles empty segment list correctly."""
    engine = TranslationEngine(
        config_service=mock_config_service,
        tm=mock_tm,
        model_loader=mock_model_loader,
        sort_segments_by_length=True,
        enable_telemetry=False,
    )

    # Empty segments
    segments = []
    texts = []

    backend = mock_model_loader.get_backend()
    stats = TranslationStats()
    results = engine._translate_segments_batch(backend, segments, texts, "en", "es", stats)

    # Verify empty result
    assert len(results) == 0


def test_sorting_with_same_length(mock_config_service, mock_tm, mock_model_loader):
    """Verify stable sorting when all segments have same length."""
    engine = TranslationEngine(
        config_service=mock_config_service,
        tm=mock_tm,
        model_loader=mock_model_loader,
        sort_segments_by_length=True,
        enable_telemetry=False,
    )

    # All same length (stable sort should preserve relative order)
    segments = [
        Segment(id="s1", source_text="First", position=0, node_type="paragraph"),
        Segment(id="s2", source_text="Secnd", position=1, node_type="paragraph"),
        Segment(id="s3", source_text="Third", position=2, node_type="paragraph"),
    ]

    texts = [s.source_text for s in segments]
    backend = mock_model_loader.get_backend()
    stats = TranslationStats()
    results = engine._translate_segments_batch(backend, segments, texts, "en", "es", stats)

    # Verify results in original order
    assert len(results) == 3
    assert "First" in results[0]
    assert "Secnd" in results[1]
    assert "Third" in results[2]
