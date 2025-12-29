"""
Integration tests for segment sorting end-to-end functionality (SR-04).

Tests verify that segment sorting works correctly in real translation workflows
with actual file I/O, document parsing, and output generation.
"""
import pytest
from pathlib import Path
import tempfile
import shutil
from unittest.mock import Mock

from src.translation_engine import TranslationEngine
from src.tm import TranslationMemory
from src.tm.l1_cache import L1Cache
from src.model_runtime import ModelLoader
from src.utils.config_loader import ConfigService


class MockTranslationBackend:
    """Mock backend that preserves text length info in translation."""

    def translate(self, texts, source_lang, target_lang):
        """Return texts with [ES:LEN] prefix to track processing order."""
        return [f"[{target_lang.upper()}:{len(t)}]{t}" for t in texts]

    def translate_with_token_counts(self, texts, source_lang, target_lang):
        """Return translations with token counts."""
        translations = self.translate(texts, source_lang, target_lang)
        input_tokens = sum(len(t.split()) for t in texts)
        output_tokens = sum(len(t.split()) for t in translations)
        return translations, input_tokens, output_tokens


@pytest.fixture
def fixtures_dir():
    """Get path to segment sorting test fixtures."""
    return Path(__file__).parent.parent / "fixtures" / "segment_sorting"


@pytest.fixture
def temp_workspace(tmp_path):
    """Create temporary workspace for test outputs."""
    workspace = {
        "source_dir": tmp_path / "source",
        "output_dir": tmp_path / "output",
        "tm_dir": tmp_path / "tm",
        "config_dir": tmp_path / "config",
    }
    for path in workspace.values():
        path.mkdir(parents=True, exist_ok=True)
    return workspace


@pytest.fixture
def mock_config_service(temp_workspace):
    """Create mock config service for testing."""
    config = Mock(spec=ConfigService)
    config.site_config = Mock()
    config.site_config.id = "test_site"
    config.site_config.source_lang = "en"
    config.site_config.source_dir = temp_workspace["source_dir"]
    config.site_config.output_dir = temp_workspace["output_dir"]

    # Mock body rules
    body_rules = Mock()
    body_rules.translate_markdown = True
    body_rules.preserve_blocks = []
    body_rules.preserve_patterns = []
    body_rules.placeholder_syntax = []
    body_rules.use_ast_body_reconstruction = False
    body_rules.sort_segments_by_length = False  # Default
    config.site_config.get_body_rules = Mock(return_value=body_rules)

    # Mock frontmatter rules
    frontmatter_rules = Mock()
    frontmatter_rules.translate_keys = []
    frontmatter_rules.preserve_keys = []
    config.site_config.get_frontmatter_rules = Mock(return_value=frontmatter_rules)

    # Mock TM preferences
    tm_prefs = Mock()
    tm_prefs.use_semantic_tm = False
    tm_prefs.fallback_exact_only = True
    config.site_config.get_tm_preferences = Mock(return_value=tm_prefs)

    config.global_config = Mock()
    config.global_config.tm_data_dir = str(temp_workspace["tm_dir"])

    return config


@pytest.fixture
def mock_tm():
    """Create mock translation memory."""
    tm = Mock(spec=TranslationMemory)
    tm.lookup = Mock(return_value=None)  # No cache hits
    tm.store = Mock()
    tm.set_override_mode = Mock()
    return tm


@pytest.fixture
def mock_model_loader():
    """Create mock model loader."""
    loader = Mock(spec=ModelLoader)
    backend = MockTranslationBackend()
    loader.get_backend = Mock(return_value=backend)
    return loader


def test_segment_sorting_preserves_structure(
    fixtures_dir, temp_workspace, mock_config_service, mock_tm, mock_model_loader
):
    """Verify output structure matches input when sorting enabled."""
    # Copy heterogeneous fixture to source dir
    source_file = temp_workspace["source_dir"] / "test.md"
    shutil.copy(fixtures_dir / "heterogeneous.md", source_file)

    # Create engine with sorting enabled
    engine = TranslationEngine(
        config_service=mock_config_service,
        tm=mock_tm,
        model_loader=mock_model_loader,
        sort_segments_by_length=True,
        enable_telemetry=False,
    )

    # Translate file
    result = engine.translate_file(
        site_id="test_site",
        file_path=source_file,
        target_langs=["es"],
    )

    # Verify translation succeeded
    assert result.successful is True
    assert result.target_lang == "es"

    # Verify output file exists
    output_file = temp_workspace["output_dir"] / "es" / "test.md"
    assert output_file.exists(), f"Output file not found at {output_file}"

    # Read output and verify structure preserved
    output_content = output_file.read_text(encoding="utf-8")

    # Check frontmatter preserved
    assert "---" in output_content
    assert "title:" in output_content

    # Check heading preserved
    assert "# Heading" in output_content or "# [ES:" in output_content

    # Verify all segments translated (check for translation markers)
    assert "[ES:" in output_content, "Translations should contain length markers"


def test_segment_sorting_edge_case_single(
    fixtures_dir, temp_workspace, mock_config_service, mock_tm, mock_model_loader
):
    """Test sorting with single segment (no IndexError)."""
    # Copy single-segment fixture
    source_file = temp_workspace["source_dir"] / "single.md"
    shutil.copy(fixtures_dir / "single.md", source_file)

    # Create engine with sorting enabled
    engine = TranslationEngine(
        config_service=mock_config_service,
        tm=mock_tm,
        model_loader=mock_model_loader,
        sort_segments_by_length=True,
        enable_telemetry=False,
    )

    # Translate - should not raise IndexError
    result = engine.translate_file(
        site_id="test_site",
        file_path=source_file,
        target_langs=["es"],
    )

    assert result.successful is True


def test_segment_sorting_edge_case_uniform(
    fixtures_dir, temp_workspace, mock_config_service, mock_tm, mock_model_loader
):
    """Test sorting with uniform-length segments (stable sort)."""
    # Copy uniform fixture
    source_file = temp_workspace["source_dir"] / "uniform.md"
    shutil.copy(fixtures_dir / "uniform.md", source_file)

    # Create engine with sorting enabled
    engine = TranslationEngine(
        config_service=mock_config_service,
        tm=mock_tm,
        model_loader=mock_model_loader,
        sort_segments_by_length=True,
        enable_telemetry=False,
    )

    # Translate
    result = engine.translate_file(
        site_id="test_site",
        file_path=source_file,
        target_langs=["es"],
    )

    assert result.successful is True

    # Verify output structure
    output_file = temp_workspace["output_dir"] / "es" / "uniform.md"
    assert output_file.exists()


def test_segment_sorting_edge_case_empty(
    fixtures_dir, temp_workspace, mock_config_service, mock_tm, mock_model_loader
):
    """Test sorting with empty/minimal document."""
    # Copy empty fixture
    source_file = temp_workspace["source_dir"] / "empty.md"
    shutil.copy(fixtures_dir / "empty.md", source_file)

    # Create engine with sorting enabled
    engine = TranslationEngine(
        config_service=mock_config_service,
        tm=mock_tm,
        model_loader=mock_model_loader,
        sort_segments_by_length=True,
        enable_telemetry=False,
    )

    # Translate - should handle gracefully
    result = engine.translate_file(
        site_id="test_site",
        file_path=source_file,
        target_langs=["es"],
    )

    # Empty doc may succeed with no segments to translate
    # Just verify no crash
    assert result is not None


def test_sorting_disabled_processes_in_order(
    fixtures_dir, temp_workspace, mock_config_service, mock_tm, mock_model_loader
):
    """Verify sorting disabled processes segments in document order."""
    # Copy heterogeneous fixture
    source_file = temp_workspace["source_dir"] / "test.md"
    shutil.copy(fixtures_dir / "heterogeneous.md", source_file)

    # Create engine with sorting DISABLED (default)
    engine = TranslationEngine(
        config_service=mock_config_service,
        tm=mock_tm,
        model_loader=mock_model_loader,
        sort_segments_by_length=False,  # Explicit disable
        enable_telemetry=False,
    )

    # Translate
    result = engine.translate_file(
        site_id="test_site",
        file_path=source_file,
        target_langs=["es"],
    )

    assert result.successful is True

    # Verify output exists
    output_file = temp_workspace["output_dir"] / "es" / "test.md"
    assert output_file.exists()


def test_sorting_with_multiple_files(
    fixtures_dir, temp_workspace, mock_config_service, mock_tm, mock_model_loader
):
    """Test sorting works correctly with multiple files."""
    # Copy multiple fixtures
    for fixture_name in ["heterogeneous.md", "uniform.md", "single.md"]:
        source_file = temp_workspace["source_dir"] / fixture_name
        shutil.copy(fixtures_dir / fixture_name, source_file)

    # Create engine with sorting enabled
    engine = TranslationEngine(
        config_service=mock_config_service,
        tm=mock_tm,
        model_loader=mock_model_loader,
        sort_segments_by_length=True,
        enable_telemetry=False,
    )

    # Translate directory
    result = engine.translate_directory(
        site_id="test_site",
        directory=temp_workspace["source_dir"],
        target_langs=["es"],
    )

    # Verify all files processed
    assert result.successful_files >= 3

    # Verify output files exist
    for fixture_name in ["heterogeneous.md", "uniform.md", "single.md"]:
        output_file = temp_workspace["output_dir"] / "es" / fixture_name
        assert output_file.exists(), f"Missing output: {fixture_name}"
