"""
Unit tests for TranslationEngine.

INT-01: Added comprehensive tests for retry loop with validation and decision engine.
"""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

import src.tm.retranslate_queue as _rtq
from src.tm.models import LookupResult
from src.translation_engine import (
    TranslationEngine,
    TranslationRejectedError,
)
from src.translation_engine.extractor import Segment
from src.translation_engine.parser import HugoDocument
from src.translation_engine.validation import ValidationSuite
from src.translation_engine.validation.base import (
    ValidationIssue,
    ValidationResult,
    ValidationSeverity,
)
from src.translation_engine.validation.decision_engine import ValidationDecisionEngine
from src.translation_engine.validation.post_translation_validator import DecisionResult
from src.translation_engine.validation.post_translation_validator import (
    ValidationDecision as PostValidationDecision,
)


@pytest.fixture
def mock_config_service():
    """Create mock ConfigService."""
    service = Mock()

    # Mock site profile
    profile = Mock()
    profile.site_id = "test_site"
    profile.default_source_lang = "en"
    profile.default_model = "m2m100_418m"
    profile.output_dir = "output"
    profile.frontmatter = {}  # Empty dict to avoid iteration errors
    profile.body = Mock()
    profile.body.translate_markdown = True
    profile.body.preserve_patterns = []
    profile.body.preserve_blocks = []
    profile.body.placeholder_syntax = []

    service.get_site_profile.return_value = profile

    # Mock get_config to disable post-write validation
    service.get_config.return_value = {
        "validation_defaults": {
            "post_write": {
                "enabled": False,  # Disable post-write validation in unit tests
            }
        }
    }

    return service


@pytest.fixture
def mock_tm():
    """Create mock TranslationMemory."""
    tm = Mock()
    tm.lookup.return_value = LookupResult(hit=False)  # Default: no TM hits
    tm.store.return_value = "entry_id"
    tm.get_stats.return_value = {"entries": 0}
    return tm


@pytest.fixture
def mock_model_loader():
    """Create mock ModelLoader."""
    loader = Mock()

    # Mock backend
    backend = Mock()
    backend.translate.return_value = ["Bonjour le monde"]
    # Mock translate_with_token_counts to return tuple (translated_texts, input_tokens, output_tokens)
    backend.translate_with_token_counts.return_value = (
        ["Bonjour le monde"],
        100,  # input_tokens
        50,  # output_tokens
    )

    loader.load_model.return_value = backend
    return loader


@pytest.fixture
def translation_engine(mock_config_service, mock_tm, mock_model_loader):
    """Create TranslationEngine with mocks."""
    return TranslationEngine(
        config_service=mock_config_service,
        tm=mock_tm,
        model_loader=mock_model_loader,
    )


@pytest.fixture(autouse=True)
def _isolate_retranslate_queue(tmp_path):
    """Redirect queue/quarantine files to tmp_path for every test in this module.

    Without this, engine tests that trigger REJECT decisions write to the live
    production data/retranslate_queue.jsonl, contaminating it with pytest temp paths.
    """
    with (
        patch.object(_rtq, "_QUEUE_FILE", tmp_path / "retranslate_queue.jsonl"),
        patch.object(_rtq, "_QUARANTINE_FILE", tmp_path / "quarantine.jsonl"),
    ):
        yield


@pytest.fixture
def sample_markdown_file(tmp_path):
    """Create sample markdown file."""
    content = """---
title: "Test Page"
description: "A test page"
---

# Hello World

This is a test paragraph.
"""
    md_file = tmp_path / "test.md"
    md_file.write_text(content, encoding="utf-8")
    return md_file


class TestTranslationEngineInit:
    """Test TranslationEngine initialization."""

    def test_engine_initialization(self, mock_config_service, mock_tm, mock_model_loader):
        """Test creating TranslationEngine."""
        engine = TranslationEngine(
            config_service=mock_config_service,
            tm=mock_tm,
            model_loader=mock_model_loader,
        )

        assert engine.config == mock_config_service
        assert engine.tm == mock_tm
        assert engine.model_loader == mock_model_loader
        assert engine.parser is not None


class TestExtractSegments:
    """Test segment extraction."""

    def test_extract_segments_basic(self, translation_engine, sample_markdown_file):
        """Test extracting segments from file."""
        segments = translation_engine.extract_segments(
            site_id="test_site",
            file_path=sample_markdown_file,
        )

        # Should have extracted some segments
        assert len(segments) > 0
        assert all(hasattr(seg, "source_text") for seg in segments)


class TestTranslateFile:
    """Test file translation."""

    @patch("src.translation_engine.engine.HugoParser")
    @patch("src.translation_engine.engine.SegmentExtractor")
    @patch("src.translation_engine.engine.MarkdownReconstructor")
    def test_translate_file_success(
        self,
        mock_reconstructor_class,
        mock_extractor_class,
        mock_parser_class,
        translation_engine,
        sample_markdown_file,
        tmp_path,
    ):
        """Test successful file translation."""
        # Setup mocks
        mock_parser = mock_parser_class.return_value
        mock_doc = Mock(spec=HugoDocument)
        mock_doc.file_path = sample_markdown_file
        mock_doc.body = "# Hello World\n\nTest content"
        mock_doc.ast = []  # Empty AST list for reconstruction
        mock_doc.frontmatter = {}  # Empty frontmatter dict for reconstruction
        mock_parser.parse_string.return_value = mock_doc

        # Mock segments
        mock_extractor = mock_extractor_class.return_value
        segment1 = Mock(spec=Segment)
        segment1.source_text = "Hello World"
        segment1.id = "seg1"
        segment1.context = None
        mock_extractor.extract_all.return_value = [segment1]

        # Mock backend
        mock_backend = translation_engine.model_loader.load_model.return_value
        mock_backend.translate.return_value = ["Translated content"]
        mock_backend.translate_with_token_counts.return_value = (
            ["Translated content"],
            100,  # input_tokens
            50,  # output_tokens
        )

        # Mock reconstructor
        mock_reconstructor = mock_reconstructor_class.return_value
        mock_reconstructor.reconstruct_document.return_value = Mock(
            __str__=lambda x: "# Translated Content\n\nTranslated body"
        )

        # Mock output path in site profile
        translation_engine.config.get_site_profile.return_value.output_dir = str(
            tmp_path / "output"
        )

        # Translate
        result = translation_engine.translate_file(
            site_id="test_site",
            file_path=sample_markdown_file,
            target_langs=["fr"],
        )

        # Verify
        assert result.success is True
        assert sample_markdown_file in [result.file_path, Path(result.file_path)]
        assert "fr" in result.outputs
        assert result.stats.total_segments == 1

    def test_translate_file_no_site_profile(self, translation_engine, sample_markdown_file):
        """Test error when site profile not found."""
        translation_engine.config.get_site_profile.return_value = None

        result = translation_engine.translate_file(
            site_id="invalid_site",
            file_path=sample_markdown_file,
            target_langs=["fr"],
        )

        assert result.success is False
        assert len(result.errors) > 0
        assert "not found" in result.errors[0].lower()

    @patch("src.translation_engine.engine.HugoParser")
    def test_translate_file_parse_error(
        self,
        mock_parser_class,
        translation_engine,
        sample_markdown_file,
    ):
        """Test handling parse errors."""
        # Make parser raise exception
        mock_parser = mock_parser_class.return_value
        mock_parser.parse_string.side_effect = Exception("Parse failed")

        result = translation_engine.translate_file(
            site_id="test_site",
            file_path=sample_markdown_file,
            target_langs=["fr"],
        )

        assert result.success is False
        assert len(result.errors) > 0


class TestTranslateWithTM:
    """Test translation with Translation Memory."""

    @patch("src.translation_engine.engine.HugoParser")
    @patch("src.translation_engine.engine.SegmentExtractor")
    @patch("src.translation_engine.engine.MarkdownReconstructor")
    def test_translate_with_tm_hit(
        self,
        mock_reconstructor_class,
        mock_extractor_class,
        mock_parser_class,
        translation_engine,
        sample_markdown_file,
        tmp_path,
    ):
        """Test translation with TM hit."""
        # Setup mocks
        mock_parser = mock_parser_class.return_value
        mock_doc = Mock(spec=HugoDocument)
        mock_doc.file_path = sample_markdown_file
        mock_doc.body = "# Hello World\n\nTest content"
        mock_doc.ast = []  # Empty AST list for reconstruction
        mock_doc.frontmatter = {}  # Empty frontmatter dict for reconstruction
        mock_parser.parse_string.return_value = mock_doc

        # Mock segment
        segment = Mock(spec=Segment)
        segment.source_text = "Hello World"
        segment.id = "seg1"
        segment.context = None

        mock_extractor = mock_extractor_class.return_value
        mock_extractor.extract_all.return_value = [segment]

        # Mock TM hit
        tm_result = LookupResult(
            hit=True,
            translation="Bonjour le monde",
            source="l1_cache",
            confidence=1.0,
        )
        translation_engine.tm.lookup.return_value = tm_result

        # Mock backend (not used when TM hits, but needed for initialization)
        mock_backend = translation_engine.model_loader.load_model.return_value
        mock_backend.translate.return_value = ["Bonjour le monde"]
        mock_backend.translate_with_token_counts.return_value = (
            ["Bonjour le monde"],
            100,  # input_tokens
            50,  # output_tokens
        )

        # Mock reconstructor
        mock_reconstructor = mock_reconstructor_class.return_value
        mock_reconstructor.reconstruct_document.return_value = Mock(
            __str__=lambda x: "# Translated Content\n\nTranslated body"
        )

        # Mock output path
        translation_engine.config.get_site_profile.return_value.output_dir = str(
            tmp_path / "output"
        )

        # Translate
        result = translation_engine.translate_file(
            site_id="test_site",
            file_path=sample_markdown_file,
            target_langs=["fr"],
        )

        # Verify TM was used
        assert result.success is True
        assert result.stats.tm_hits == 1
        assert result.stats.l1_hits == 1
        assert result.stats.translated_segments == 0  # No new translations

    @patch("src.translation_engine.engine.HugoParser")
    @patch("src.translation_engine.engine.SegmentExtractor")
    @patch("src.translation_engine.engine.MarkdownReconstructor")
    def test_translate_force_bypass_tm(
        self,
        mock_reconstructor_class,
        mock_extractor_class,
        mock_parser_class,
        translation_engine,
        sample_markdown_file,
        tmp_path,
    ):
        """Test force translation bypasses TM."""
        # Setup mocks similar to tm_hit test
        mock_parser = mock_parser_class.return_value
        mock_doc = Mock(spec=HugoDocument)
        mock_doc.file_path = sample_markdown_file
        mock_doc.body = "# Hello World\n\nTest content"
        mock_doc.ast = []  # Empty AST list for reconstruction
        mock_doc.frontmatter = {}  # Empty frontmatter dict for reconstruction
        mock_parser.parse_string.return_value = mock_doc

        segment = Mock(spec=Segment)
        segment.source_text = "Hello World"
        segment.id = "seg1"
        segment.context = None

        mock_extractor = mock_extractor_class.return_value
        mock_extractor.extract_all.return_value = [segment]

        # Mock TM (should not be used with force=True)
        translation_engine.tm.lookup.return_value = LookupResult(
            hit=True,
            translation="Bonjour",
            source="l1_cache",
            confidence=1.0,
        )

        # Mock backend (will be used because force=True bypasses TM)
        mock_backend = translation_engine.model_loader.load_model.return_value
        mock_backend.translate.return_value = ["Bonjour le monde"]
        mock_backend.translate_with_token_counts.return_value = (
            ["Bonjour le monde"],
            100,  # input_tokens
            50,  # output_tokens
        )

        mock_reconstructor = mock_reconstructor_class.return_value
        mock_reconstructor.reconstruct_document.return_value = Mock(
            __str__=lambda x: "# Translated Content\n\nTranslated body"
        )

        translation_engine.config.get_site_profile.return_value.output_dir = str(
            tmp_path / "output"
        )

        # Translate with force=True
        result = translation_engine.translate_file(
            site_id="test_site",
            file_path=sample_markdown_file,
            target_langs=["fr"],
            force=True,
        )

        # Verify TM was bypassed
        assert result.success is True
        assert result.stats.tm_hits == 0
        assert result.stats.translated_segments == 1


class TestTranslateDirectory:
    """Test directory translation."""

    def test_translate_directory(self, translation_engine, tmp_path):
        """Test translating directory of files."""
        # Create test files
        (tmp_path / "file1.md").write_text("# Test 1", encoding="utf-8")
        (tmp_path / "file2.md").write_text("# Test 2", encoding="utf-8")

        # Mock translate_file to return success
        original_translate = translation_engine.translate_file
        translation_engine.translate_file = Mock(
            side_effect=lambda **kwargs: Mock(
                success=True,
                file_path=kwargs["file_path"],
                outputs={"fr": Path("output/fr/test.md")},
                stats=Mock(
                    total_segments=1,
                    tm_hits=0,
                    translated_segments=1,
                ),
            )
        )

        # Translate directory
        result = translation_engine.translate_directory(
            site_id="test_site",
            directory=tmp_path,
            target_langs=["fr"],
            recursive=False,
        )

        # Verify
        assert result.total_files == 2
        assert result.successful_files == 2
        assert len(result.file_results) == 2


class TestTMOperations:
    """Test TM-related operations."""

    def test_get_tm_stats(self, translation_engine):
        """Test getting TM statistics."""
        translation_engine.tm.get_stats.return_value = {
            "total_entries": 1000,
            "l1_entries": 500,
            "l2_entries": 300,
        }

        stats = translation_engine.get_tm_stats("test_site")
        assert stats["total_entries"] == 1000

    def test_clear_tm(self, translation_engine):
        """Test clearing TM."""
        translation_engine.clear_tm(
            site_id="test_site",
            src_lang="en",
            tgt_lang="fr",
        )

        translation_engine.tm.clear.assert_called_once_with("test_site", "en", "fr")


class TestWriteOutput:
    """Test _write_output method."""

    def test_write_output_creates_directories(self, translation_engine, tmp_path):
        """Test that _write_output creates parent directories."""
        from src.translation_engine.models import TranslationStats

        # Create paths with nested directories
        output_path = tmp_path / "output" / "fr" / "nested" / "test.md"
        source_path = tmp_path / "source" / "test.md"
        stats = TranslationStats()

        # Ensure directories don't exist yet
        assert not output_path.parent.exists()

        # Write output
        content = "# Test Content\n\nTranslated text."
        translation_engine._write_output(content, output_path, source_path, stats)

        # Verify directories were created
        assert output_path.parent.exists()
        assert output_path.parent.is_dir()

    def test_write_output_writes_file(self, translation_engine, tmp_path):
        """Test that _write_output writes file correctly."""
        from src.translation_engine.models import TranslationStats

        output_path = tmp_path / "output.md"
        source_path = tmp_path / "source.md"
        stats = TranslationStats()

        content = "# Test Content\n\nTranslated text with unicode: \u00e9\u00e0\u00fc"
        translation_engine._write_output(content, output_path, source_path, stats)

        # Verify file was written
        assert output_path.exists()
        assert output_path.read_text(encoding="utf-8") == content

    def test_write_output_logs_correctly(self, translation_engine, tmp_path):
        """Test that _write_output logs file writing."""
        from src.translation_engine.models import TranslationStats

        output_path = tmp_path / "output.md"
        source_path = tmp_path / "source.md"
        stats = TranslationStats()

        content = "# Test Content"

        with patch("src.translation_engine.engine.logger") as mock_logger:
            translation_engine._write_output(content, output_path, source_path, stats)

            # Verify logger.info was called
            mock_logger.info.assert_called_once()
            call_args = mock_logger.info.call_args[0][0]
            assert "Written translated file" in call_args
            assert str(output_path) in call_args

    def test_write_output_updates_stats_new_file(self, translation_engine, tmp_path):
        """Test that _write_output updates stats for new file."""
        from src.translation_engine.models import TranslationStats

        output_path = tmp_path / "new_file.md"
        source_path = tmp_path / "source.md"
        stats = TranslationStats()

        content = "# Test Content\n\nNew file content."

        # Ensure file doesn't exist
        assert not output_path.exists()

        translation_engine._write_output(content, output_path, source_path, stats)

        # Verify stats for new file
        assert stats.md_files_added == 1
        assert stats.md_files_updated == 0
        assert stats.bytes_written_md == len(content.encode("utf-8"))

    def test_write_output_updates_stats_existing_file(self, translation_engine, tmp_path):
        """Test that _write_output updates stats for existing file."""
        from src.translation_engine.models import TranslationStats

        output_path = tmp_path / "existing_file.md"
        source_path = tmp_path / "source.md"
        stats = TranslationStats()

        # Create existing file
        output_path.write_text("Old content", encoding="utf-8")
        assert output_path.exists()

        content = "# Test Content\n\nUpdated file content."
        translation_engine._write_output(content, output_path, source_path, stats)

        # Verify stats for updated file
        assert stats.md_files_added == 0
        assert stats.md_files_updated == 1
        assert stats.bytes_written_md == len(content.encode("utf-8"))

    def test_write_output_handles_unicode(self, translation_engine, tmp_path):
        """Test that _write_output handles unicode content correctly."""
        from src.translation_engine.models import TranslationStats

        output_path = tmp_path / "unicode_test.md"
        source_path = tmp_path / "source.md"
        stats = TranslationStats()

        # Content with various unicode characters
        content = """# Test Unicode

French: \u00e9\u00e8\u00ea\u00e0\u00e7
German: \u00fc\u00f6\u00e4\u00df
Spanish: \u00f1\u00ed\u00f3
Chinese: \u4e2d\u6587
Emoji: \U0001f600\U0001f44d"""

        translation_engine._write_output(content, output_path, source_path, stats)

        # Verify content is preserved
        written_content = output_path.read_text(encoding="utf-8")
        assert written_content == content

    def test_write_output_handles_empty_content(self, translation_engine, tmp_path):
        """Test that _write_output handles empty content."""
        from src.translation_engine.models import TranslationStats

        output_path = tmp_path / "empty.md"
        source_path = tmp_path / "source.md"
        stats = TranslationStats()

        content = ""
        translation_engine._write_output(content, output_path, source_path, stats)

        # Verify file was created with empty content
        assert output_path.exists()
        assert output_path.read_text(encoding="utf-8") == ""
        assert stats.bytes_written_md == 0


class TestRetryLoop:
    """INT-01: Test retry loop with validation and decision engine."""

    @pytest.fixture
    def mock_validation_suite(self):
        """Create mock ValidationSuite."""
        suite = Mock(spec=ValidationSuite)
        # Default: validation passes
        valid_result = ValidationResult(success=True, issues=[])
        suite.validate.return_value = valid_result
        return suite

    @pytest.fixture
    def mock_decision_engine(self):
        """Create mock ValidationDecisionEngine."""
        engine = Mock(spec=ValidationDecisionEngine)
        engine.max_retry_attempts = 2
        # Default: ACCEPT decision
        accept_decision = DecisionResult(
            decision=PostValidationDecision.ACCEPT,
            decision_reason="No errors, warnings acceptable",
            retry_feedback=None,
            validation_result=ValidationResult(success=True, issues=[]),
        )
        engine.make_decision.return_value = accept_decision
        return engine

    @pytest.fixture
    def engine_with_validation(
        self,
        mock_config_service,
        mock_tm,
        mock_model_loader,
        mock_validation_suite,
        mock_decision_engine,
    ):
        """Create TranslationEngine with validation enabled."""
        return TranslationEngine(
            config_service=mock_config_service,
            tm=mock_tm,
            model_loader=mock_model_loader,
            enable_validation=True,
            validation_suite=mock_validation_suite,
            decision_engine=mock_decision_engine,
        )

    @patch("src.translation_engine.engine.HugoParser")
    @patch("src.translation_engine.engine.SegmentExtractor")
    @patch("src.translation_engine.engine.MarkdownReconstructor")
    def test_accept_on_first_try(
        self,
        mock_reconstructor_class,
        mock_extractor_class,
        mock_parser_class,
        engine_with_validation,
        sample_markdown_file,
        tmp_path,
        mock_validation_suite,
        mock_decision_engine,
    ):
        """Test ACCEPT decision on first translation attempt."""
        # Setup mocks
        mock_parser = mock_parser_class.return_value
        mock_doc = Mock(spec=HugoDocument)
        mock_doc.file_path = sample_markdown_file
        mock_doc.body = "# Test Content"
        mock_parser.parse_string.return_value = mock_doc

        # Mock segment
        segment = Mock(spec=Segment)
        segment.source_text = "Test content"
        segment.id = "seg1"
        segment.context = None

        mock_extractor = mock_extractor_class.return_value
        mock_extractor.extract_all.return_value = [segment]

        # Mock backend
        mock_backend = engine_with_validation.model_loader.load_model.return_value
        mock_backend.translate.return_value = ["Translated content"]
        mock_backend.translate_with_token_counts.return_value = (
            ["Translated content"],
            100,  # input_tokens
            50,  # output_tokens
        )

        # Mock reconstructor
        mock_reconstructor = mock_reconstructor_class.return_value
        mock_reconstructor.reconstruct_document.return_value = Mock(
            __str__=lambda x: "# Translated Content\n\nTranslated body"
        )

        # Set output directory
        engine_with_validation.config.get_site_profile.return_value.output_dir = str(
            tmp_path / "output"
        )

        # Translate
        result = engine_with_validation.translate_file(
            site_id="test_site",
            file_path=sample_markdown_file,
            target_langs=["fr"],
            validate=True,
        )

        # Verify ACCEPT decision
        assert result.success is True
        assert result.retry_attempts == 0
        assert "fr" in result.outputs
        assert result.outputs["fr"].exists()

        # Verify decision engine was called once
        mock_decision_engine.make_decision.assert_called_once()

    @patch("src.translation_engine.engine.HugoParser")
    @patch("src.translation_engine.engine.SegmentExtractor")
    @patch("src.translation_engine.engine.MarkdownReconstructor")
    def test_retry_on_validation_failure(
        self,
        mock_reconstructor_class,
        mock_extractor_class,
        mock_parser_class,
        engine_with_validation,
        sample_markdown_file,
        tmp_path,
        mock_validation_suite,
        mock_decision_engine,
    ):
        """Test RETRY decision with feedback."""
        # Setup mocks
        mock_parser = mock_parser_class.return_value
        mock_doc = Mock(spec=HugoDocument)
        mock_doc.file_path = sample_markdown_file
        mock_doc.body = "# Test Content"
        mock_parser.parse_string.return_value = mock_doc

        segment = Mock(spec=Segment)
        segment.source_text = "Test content"
        segment.id = "seg1"
        segment.context = None

        mock_extractor = mock_extractor_class.return_value
        mock_extractor.extract_all.return_value = [segment]

        # Mock backend
        mock_backend = engine_with_validation.model_loader.load_model.return_value
        mock_backend.translate.return_value = ["Translated content"]
        mock_backend.translate_with_token_counts.return_value = (
            ["Translated content"],
            100,  # input_tokens
            50,  # output_tokens
        )

        # Mock reconstructor
        mock_reconstructor = mock_reconstructor_class.return_value
        mock_reconstructor.reconstruct_document.return_value = Mock(
            __str__=lambda x: "# Translated Content\n\nTranslated body"
        )

        engine_with_validation.config.get_site_profile.return_value.output_dir = str(
            tmp_path / "output"
        )

        # First attempt: RETRY decision
        retry_decision = DecisionResult(
            decision=PostValidationDecision.RETRY,
            decision_reason="Terminology preservation issue",
            retry_feedback="Preserve 'Aspose' brand name",
            validation_result=ValidationResult(
                success=False,
                issues=[
                    ValidationIssue(
                        severity=ValidationSeverity.WARNING,
                        validator="TerminologyPreservationValidator",
                        message="Brand name 'Aspose' should be preserved",
                    )
                ],
            ),
        )

        # Second attempt: ACCEPT decision
        accept_decision = DecisionResult(
            decision=PostValidationDecision.ACCEPT,
            decision_reason="Issues resolved",
            retry_feedback=None,
            validation_result=ValidationResult(success=True, issues=[]),
        )

        mock_decision_engine.make_decision.side_effect = [retry_decision, accept_decision]

        # Translate
        result = engine_with_validation.translate_file(
            site_id="test_site",
            file_path=sample_markdown_file,
            target_langs=["fr"],
            validate=True,
        )

        # Verify retry occurred
        assert result.success is True
        assert result.retry_attempts == 1
        assert len(result.retry_history) == 1
        assert result.retry_history[0]["attempt"] == 1
        assert result.retry_history[0]["feedback"] == "Preserve 'Aspose' brand name"

        # Verify decision engine was called twice
        assert mock_decision_engine.make_decision.call_count == 2

        # Verify file was written after ACCEPT
        assert "fr" in result.outputs
        assert result.outputs["fr"].exists()

    @patch("src.translation_engine.engine.HugoParser")
    @patch("src.translation_engine.engine.SegmentExtractor")
    @patch("src.translation_engine.engine.MarkdownReconstructor")
    def test_reject_after_max_retries(
        self,
        mock_reconstructor_class,
        mock_extractor_class,
        mock_parser_class,
        engine_with_validation,
        sample_markdown_file,
        tmp_path,
        mock_validation_suite,
        mock_decision_engine,
    ):
        """Test REJECT decision after exhausting retry attempts."""
        # Setup mocks
        mock_parser = mock_parser_class.return_value
        mock_doc = Mock(spec=HugoDocument)
        mock_doc.file_path = sample_markdown_file
        mock_doc.body = "# Test Content"
        mock_parser.parse_string.return_value = mock_doc

        segment = Mock(spec=Segment)
        segment.source_text = "Test content"
        segment.id = "seg1"
        segment.context = None

        mock_extractor = mock_extractor_class.return_value
        mock_extractor.extract_all.return_value = [segment]

        # Mock backend
        mock_backend = engine_with_validation.model_loader.load_model.return_value
        mock_backend.translate.return_value = ["Translated content"]
        mock_backend.translate_with_token_counts.return_value = (
            ["Translated content"],
            100,  # input_tokens
            50,  # output_tokens
        )

        mock_reconstructor = mock_reconstructor_class.return_value
        mock_reconstructor.reconstruct_document.return_value = Mock(
            __str__=lambda x: "# Translated Content\n\nTranslated body"
        )

        engine_with_validation.config.get_site_profile.return_value.output_dir = str(
            tmp_path / "output"
        )

        # All attempts: REJECT decision
        reject_decision = DecisionResult(
            decision=PostValidationDecision.REJECT,
            decision_reason="Critical validation failure",
            retry_feedback=None,
            validation_result=ValidationResult(
                success=False,
                issues=[
                    ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        validator="PlaceholderValidator",
                        message="Missing placeholder {{< shortcode >}}",
                    )
                ],
            ),
        )

        mock_decision_engine.make_decision.return_value = reject_decision

        # Translate - should raise TranslationRejectedError
        with pytest.raises(TranslationRejectedError) as exc_info:
            engine_with_validation.translate_file(
                site_id="test_site",
                file_path=sample_markdown_file,
                target_langs=["fr"],
                validate=True,
            )

        # Verify exception details
        assert "Translation rejected" in str(exc_info.value)
        assert exc_info.value.rejection_reason == "Critical validation failure"

        # Verify file was NOT written
        output_path = tmp_path / "output" / "fr" / sample_markdown_file.name
        assert not output_path.exists()

    @patch("src.translation_engine.engine.HugoParser")
    @patch("src.translation_engine.engine.SegmentExtractor")
    @patch("src.translation_engine.engine.MarkdownReconstructor")
    def test_feedback_applied_to_retry_prompt(
        self,
        mock_reconstructor_class,
        mock_extractor_class,
        mock_parser_class,
        engine_with_validation,
        sample_markdown_file,
        tmp_path,
        mock_validation_suite,
        mock_decision_engine,
    ):
        """Test that feedback is passed to retry translation attempt."""
        # Setup mocks
        mock_parser = mock_parser_class.return_value
        mock_doc = Mock(spec=HugoDocument)
        mock_doc.file_path = sample_markdown_file
        mock_doc.body = "# Test Content"
        mock_parser.parse_string.return_value = mock_doc

        segment = Mock(spec=Segment)
        segment.source_text = "Test content"
        segment.id = "seg1"
        segment.context = None

        mock_extractor = mock_extractor_class.return_value
        mock_extractor.extract_all.return_value = [segment]

        # Mock backend
        mock_backend = engine_with_validation.model_loader.load_model.return_value
        mock_backend.translate.return_value = ["Translated content"]
        mock_backend.translate_with_token_counts.return_value = (
            ["Translated content"],
            100,  # input_tokens
            50,  # output_tokens
        )

        mock_reconstructor = mock_reconstructor_class.return_value
        mock_reconstructor.reconstruct_document.return_value = Mock(
            __str__=lambda x: "# Translated Content\n\nTranslated body"
        )

        engine_with_validation.config.get_site_profile.return_value.output_dir = str(
            tmp_path / "output"
        )

        # First attempt: RETRY with feedback
        retry_decision = DecisionResult(
            decision=PostValidationDecision.RETRY,
            decision_reason="Structure mismatch",
            retry_feedback="Ensure all headings are preserved with same level",
            validation_result=ValidationResult(success=False, issues=[]),
        )

        # Second attempt: ACCEPT
        accept_decision = DecisionResult(
            decision=PostValidationDecision.ACCEPT,
            decision_reason="All issues resolved",
            retry_feedback=None,
            validation_result=ValidationResult(success=True, issues=[]),
        )

        mock_decision_engine.make_decision.side_effect = [retry_decision, accept_decision]

        # Translate
        result = engine_with_validation.translate_file(
            site_id="test_site",
            file_path=sample_markdown_file,
            target_langs=["fr"],
            validate=True,
        )

        # Verify retry occurred with feedback
        assert result.success is True
        assert result.retry_attempts == 1

        # Verify _translate_to_language was called with retry_feedback
        # (this would require inspecting the actual call, but we can verify the result)
        assert (
            result.retry_history[0]["feedback"]
            == "Ensure all headings are preserved with same level"
        )

    def test_validation_disabled_no_retry(
        self,
        translation_engine,
        sample_markdown_file,
        tmp_path,
    ):
        """Test that retry loop is bypassed when validation is disabled."""
        # Mock parser and extractor
        with (
            patch("src.translation_engine.engine.HugoParser") as mock_parser_class,
            patch("src.translation_engine.engine.SegmentExtractor") as mock_extractor_class,
            patch(
                "src.translation_engine.engine.MarkdownReconstructor"
            ) as mock_reconstructor_class,
        ):
            mock_parser = mock_parser_class.return_value
            mock_doc = Mock(spec=HugoDocument)
            mock_doc.file_path = sample_markdown_file
            mock_doc.body = "# Test"
            mock_parser.parse_string.return_value = mock_doc

            segment = Mock(spec=Segment)
            segment.source_text = "Test"
            segment.id = "seg1"
            segment.context = None

            mock_extractor = mock_extractor_class.return_value
            mock_extractor.extract_all.return_value = [segment]

            # Mock backend
            mock_backend = translation_engine.model_loader.load_model.return_value
            mock_backend.translate.return_value = ["Translated"]
            mock_backend.translate_with_token_counts.return_value = (
                ["Translated"],
                100,  # input_tokens
                50,  # output_tokens
            )

            mock_reconstructor = mock_reconstructor_class.return_value
            mock_reconstructor.reconstruct_document.return_value = Mock(
                __str__=lambda x: "Translated"
            )

            translation_engine.config.get_site_profile.return_value.output_dir = str(
                tmp_path / "output"
            )

            # Translate with validation disabled
            result = translation_engine.translate_file(
                site_id="test_site",
                file_path=sample_markdown_file,
                target_langs=["fr"],
                validate=False,
            )

            # Verify success without validation
            assert result.success is True
            assert result.retry_attempts == 0
            assert len(result.retry_history) == 0


class TestINT02RetryFeedback:
    """INT-02: Test retry feedback integration and temperature variation."""

    @patch("src.translation_engine.engine.HugoParser")
    @patch("src.translation_engine.engine.SegmentExtractor")
    @patch("src.translation_engine.engine.MarkdownReconstructor")
    def test_retry_feedback_prepended_to_text(
        self,
        mock_reconstructor_class,
        mock_extractor_class,
        mock_parser_class,
        translation_engine,
        tmp_path,
    ):
        """INT-02: Test that retry_feedback is prepended to source texts."""
        # Setup mocks
        mock_parser = mock_parser_class.return_value
        mock_doc = Mock(spec=HugoDocument)
        mock_doc.source_path = Path("test.md")
        mock_doc.body = "# Test"
        mock_parser.parse_string.return_value = mock_doc

        segment = Mock(spec=Segment)
        segment.source_text = "Original text"
        segment.id = "seg1"
        segment.context = None

        mock_extractor = mock_extractor_class.return_value
        mock_extractor.extract_all.return_value = [segment]

        # Create a mock backend that captures the translate call
        mock_backend = Mock()
        translate_calls = []

        def capture_translate(texts, src_lang, tgt_lang):
            translate_calls.append(texts)
            return ["Translated text"]

        def capture_translate_with_token_counts(texts, src_lang, tgt_lang):
            translate_calls.append(texts)
            return (["Translated text"], 100, 50)

        mock_backend.translate = capture_translate
        mock_backend.translate_with_token_counts = capture_translate_with_token_counts
        translation_engine.model_loader.load_model.return_value = mock_backend

        mock_reconstructor = mock_reconstructor_class.return_value
        mock_reconstructor.reconstruct_document.return_value = Mock(__str__=lambda x: "Translated")

        translation_engine.config.get_site_profile.return_value.output_dir = str(
            tmp_path / "output"
        )

        # Call _translate_to_language with retry_feedback
        from src.translation_engine.models import TranslationStats

        stats = TranslationStats()

        translated_content = translation_engine._translate_to_language(
            site_id="test_site",
            site_profile=translation_engine.config.get_site_profile("test_site"),
            doc=mock_doc,
            segments=[segment],
            source_lang="en",
            target_lang="fr",
            force=False,
            stats=stats,
            retry_feedback="Preserve technical terms",
            retry_count=1,
        )

        # Verify feedback was prepended to the text
        assert len(translate_calls) == 1
        assert len(translate_calls[0]) == 1
        translated_text = translate_calls[0][0]
        assert "Preserve technical terms" in translated_text
        assert "SOURCE TEXT:" in translated_text
        assert "Original text" in translated_text

    @patch("src.translation_engine.engine.HugoParser")
    @patch("src.translation_engine.engine.SegmentExtractor")
    @patch("src.translation_engine.engine.MarkdownReconstructor")
    def test_no_feedback_on_first_attempt(
        self,
        mock_reconstructor_class,
        mock_extractor_class,
        mock_parser_class,
        translation_engine,
        tmp_path,
    ):
        """INT-02: Test that no feedback is applied on first attempt (retry_count=0)."""
        # Setup mocks
        mock_parser = mock_parser_class.return_value
        mock_doc = Mock(spec=HugoDocument)
        mock_doc.source_path = Path("test.md")
        mock_doc.body = "# Test"
        mock_parser.parse_string.return_value = mock_doc

        segment = Mock(spec=Segment)
        segment.source_text = "Original text"
        segment.id = "seg1"
        segment.context = None

        mock_extractor = mock_extractor_class.return_value
        mock_extractor.extract_all.return_value = [segment]

        # Capture translate calls
        mock_backend = Mock()
        translate_calls = []

        def capture_translate(texts, src_lang, tgt_lang):
            translate_calls.append(texts)
            return ["Translated text"]

        def capture_translate_with_token_counts(texts, src_lang, tgt_lang):
            translate_calls.append(texts)
            return (["Translated text"], 100, 50)

        mock_backend.translate = capture_translate
        mock_backend.translate_with_token_counts = capture_translate_with_token_counts
        translation_engine.model_loader.load_model.return_value = mock_backend

        mock_reconstructor = mock_reconstructor_class.return_value
        mock_reconstructor.reconstruct_document.return_value = Mock(__str__=lambda x: "Translated")

        translation_engine.config.get_site_profile.return_value.output_dir = str(
            tmp_path / "output"
        )

        # Call _translate_to_language WITHOUT retry_feedback (first attempt)
        from src.translation_engine.models import TranslationStats

        stats = TranslationStats()

        translated_content = translation_engine._translate_to_language(
            site_id="test_site",
            site_profile=translation_engine.config.get_site_profile("test_site"),
            doc=mock_doc,
            segments=[segment],
            source_lang="en",
            target_lang="fr",
            force=False,
            stats=stats,
            retry_feedback=None,
            retry_count=0,
        )

        # Verify NO feedback was prepended
        assert len(translate_calls) == 1
        assert len(translate_calls[0]) == 1
        translated_text = translate_calls[0][0]
        assert translated_text == "Original text"  # Unchanged
        assert "SOURCE TEXT:" not in translated_text

    @patch("src.translation_engine.engine.logger")
    @patch("src.translation_engine.engine.HugoParser")
    @patch("src.translation_engine.engine.SegmentExtractor")
    @patch("src.translation_engine.engine.MarkdownReconstructor")
    def test_temperature_variation_logged(
        self,
        mock_reconstructor_class,
        mock_extractor_class,
        mock_parser_class,
        mock_logger,
        translation_engine,
        tmp_path,
    ):
        """INT-02: Test that temperature variation is calculated and logged."""
        # Setup mocks
        mock_parser = mock_parser_class.return_value
        mock_doc = Mock(spec=HugoDocument)
        mock_doc.source_path = Path("test.md")
        mock_doc.body = "# Test"
        mock_parser.parse_string.return_value = mock_doc

        segment = Mock(spec=Segment)
        segment.source_text = "Text"
        segment.id = "seg1"
        segment.context = None

        mock_extractor = mock_extractor_class.return_value
        mock_extractor.extract_all.return_value = [segment]

        mock_backend = Mock()
        mock_backend.translate.return_value = ["Translated"]
        mock_backend.translate_with_token_counts.return_value = (
            ["Translated"],
            100,  # input_tokens
            50,  # output_tokens
        )
        translation_engine.model_loader.load_model.return_value = mock_backend

        mock_reconstructor = mock_reconstructor_class.return_value
        mock_reconstructor.reconstruct_document.return_value = Mock(__str__=lambda x: "Translated")

        translation_engine.config.get_site_profile.return_value.output_dir = str(
            tmp_path / "output"
        )

        # Call _translate_to_language with retry_count=1
        from src.translation_engine.models import TranslationStats

        stats = TranslationStats()

        translation_engine._translate_to_language(
            site_id="test_site",
            site_profile=translation_engine.config.get_site_profile("test_site"),
            doc=mock_doc,
            segments=[segment],
            source_lang="en",
            target_lang="fr",
            force=False,
            stats=stats,
            retry_feedback=None,
            retry_count=1,
        )

        # Verify temperature was logged
        # Should have logged: "Retry 1: temperature adjusted to 0.8"
        debug_calls = [call for call in mock_logger.debug.call_args_list]
        temperature_log = None
        for call in debug_calls:
            if len(call[0]) > 0 and "temperature adjusted" in str(call[0][0]):
                temperature_log = call[0][0]
                break

        assert temperature_log is not None
        assert "temperature adjusted to 0.8" in temperature_log
        assert "Retry 1" in temperature_log

    @patch("src.translation_engine.engine.logger")
    @patch("src.translation_engine.engine.HugoParser")
    @patch("src.translation_engine.engine.SegmentExtractor")
    @patch("src.translation_engine.engine.MarkdownReconstructor")
    def test_temperature_maxes_out(
        self,
        mock_reconstructor_class,
        mock_extractor_class,
        mock_parser_class,
        mock_logger,
        translation_engine,
        tmp_path,
    ):
        """INT-02: Test that temperature caps at max_temperature."""
        # Setup mocks
        mock_parser = mock_parser_class.return_value
        mock_doc = Mock(spec=HugoDocument)
        mock_doc.source_path = Path("test.md")
        mock_doc.body = "# Test"
        mock_parser.parse_string.return_value = mock_doc

        segment = Mock(spec=Segment)
        segment.source_text = "Text"
        segment.id = "seg1"
        segment.context = None

        mock_extractor = mock_extractor_class.return_value
        mock_extractor.extract_all.return_value = [segment]

        mock_backend = Mock()
        mock_backend.translate.return_value = ["Translated"]
        mock_backend.translate_with_token_counts.return_value = (
            ["Translated"],
            100,  # input_tokens
            50,  # output_tokens
        )
        translation_engine.model_loader.load_model.return_value = mock_backend

        mock_reconstructor = mock_reconstructor_class.return_value
        mock_reconstructor.reconstruct_document.return_value = Mock(__str__=lambda x: "Translated")

        translation_engine.config.get_site_profile.return_value.output_dir = str(
            tmp_path / "output"
        )

        # Call with very high retry_count (should cap at 1.0)
        from src.translation_engine.models import TranslationStats

        stats = TranslationStats()

        translation_engine._translate_to_language(
            site_id="test_site",
            site_profile=translation_engine.config.get_site_profile("test_site"),
            doc=mock_doc,
            segments=[segment],
            source_lang="en",
            target_lang="fr",
            force=False,
            stats=stats,
            retry_feedback=None,
            retry_count=10,  # Very high retry count
        )

        # Verify temperature was capped at 1.0
        debug_calls = [call for call in mock_logger.debug.call_args_list]
        temperature_log = None
        for call in debug_calls:
            if len(call[0]) > 0 and "temperature adjusted" in str(call[0][0]):
                temperature_log = call[0][0]
                break

        assert temperature_log is not None
        # Temperature should be: min(0.7 + (10 * 0.1), 1.0) = min(1.7, 1.0) = 1.0
        assert "temperature adjusted to 1.0" in temperature_log


class TestINT05PostWriteValidation:
    """INT-05: Test post-write validation integration."""

    def test_post_write_validation_success(self, translation_engine, tmp_path):
        """Test successful post-write validation."""
        # Create test file
        output_path = tmp_path / "content" / "products" / "de" / "test.md"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("# Test Content\n\nTranslated text", encoding="utf-8")

        source_path = tmp_path / "content" / "products" / "en" / "test.md"

        # Mock config
        mock_config = {
            "validation_defaults": {
                "post_write": {
                    "enabled": True,
                    "delete_on_failure": False,
                    "halt_on_failure": False,
                }
            }
        }
        translation_engine.config.get_config = Mock(return_value=mock_config)

        # Mock site profile with all required attributes
        mock_profile = Mock()
        mock_profile.default_source_lang = "en"
        mock_profile.content_roots = []  # Empty list to skip content root validation
        mock_profile.target_langs = ["de", "fr", "es"]
        mock_profile.output_layout = None  # No output layout validation

        # Run post-write validation
        result = translation_engine._post_write_validation(
            output_path=output_path,
            source_path=source_path,
            target_lang="de",
            site_id="products.aspose.net",
            site_profile=mock_profile,
        )

        # Should pass
        assert result is True

    def test_post_write_validation_file_not_exist(self, translation_engine, tmp_path):
        """Test post-write validation fails when file doesn't exist."""
        # Don't create the file - let it fail
        output_path = tmp_path / "content" / "products" / "de" / "nonexistent.md"
        source_path = tmp_path / "content" / "products" / "en" / "test.md"

        # Mock config
        mock_config = {
            "validation_defaults": {
                "post_write": {
                    "enabled": True,
                    "delete_on_failure": False,
                    "halt_on_failure": False,
                }
            }
        }
        translation_engine.config.get_config = Mock(return_value=mock_config)

        # Mock site profile
        mock_profile = Mock()
        mock_profile.default_source_lang = "en"

        # Run post-write validation
        result = translation_engine._post_write_validation(
            output_path=output_path,
            source_path=source_path,
            target_lang="de",
            site_id="products.aspose.net",
            site_profile=mock_profile,
        )

        # Should fail
        assert result is False

    def test_post_write_validation_empty_file(self, translation_engine, tmp_path):
        """Test post-write validation fails when file is empty."""
        # Create empty file
        output_path = tmp_path / "content" / "products" / "de" / "test.md"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("", encoding="utf-8")

        source_path = tmp_path / "content" / "products" / "en" / "test.md"

        # Mock config
        mock_config = {
            "validation_defaults": {
                "post_write": {
                    "enabled": True,
                    "delete_on_failure": False,
                    "halt_on_failure": False,
                }
            }
        }
        translation_engine.config.get_config = Mock(return_value=mock_config)

        # Mock site profile
        mock_profile = Mock()
        mock_profile.default_source_lang = "en"

        # Run post-write validation
        result = translation_engine._post_write_validation(
            output_path=output_path,
            source_path=source_path,
            target_lang="de",
            site_id="products.aspose.net",
            site_profile=mock_profile,
        )

        # Should fail
        assert result is False

    def test_post_write_validation_delete_on_failure(self, translation_engine, tmp_path):
        """Test that invalid file is deleted when delete_on_failure is enabled."""
        # Create empty file (will fail validation)
        output_path = tmp_path / "content" / "products" / "de" / "test.md"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("", encoding="utf-8")

        source_path = tmp_path / "content" / "products" / "en" / "test.md"

        # Mock config with delete_on_failure=True
        mock_config = {
            "validation_defaults": {
                "post_write": {
                    "enabled": True,
                    "delete_on_failure": True,
                    "halt_on_failure": False,
                }
            }
        }
        translation_engine.config.get_config = Mock(return_value=mock_config)

        # Mock site profile
        mock_profile = Mock()
        mock_profile.default_source_lang = "en"

        # Verify file exists before validation
        assert output_path.exists()

        # Run post-write validation
        result = translation_engine._post_write_validation(
            output_path=output_path,
            source_path=source_path,
            target_lang="de",
            site_id="products.aspose.net",
            site_profile=mock_profile,
        )

        # Should fail and delete file
        assert result is False
        assert not output_path.exists()

    def test_post_write_validation_halt_on_failure(self, translation_engine, tmp_path):
        """Test that RuntimeError is raised when halt_on_failure is enabled."""
        # Create empty file (will fail validation)
        output_path = tmp_path / "content" / "products" / "de" / "test.md"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("", encoding="utf-8")

        source_path = tmp_path / "content" / "products" / "en" / "test.md"

        # Mock config with halt_on_failure=True
        mock_config = {
            "validation_defaults": {
                "post_write": {
                    "enabled": True,
                    "delete_on_failure": False,
                    "halt_on_failure": True,
                }
            }
        }
        translation_engine.config.get_config = Mock(return_value=mock_config)

        # Mock site profile
        mock_profile = Mock()
        mock_profile.default_source_lang = "en"

        # Run post-write validation - should raise RuntimeError
        with pytest.raises(RuntimeError) as exc_info:
            translation_engine._post_write_validation(
                output_path=output_path,
                source_path=source_path,
                target_lang="de",
                site_id="products.aspose.net",
                site_profile=mock_profile,
            )

        assert "Post-write validation failed" in str(exc_info.value)

    def test_post_write_validation_disabled(self, translation_engine, tmp_path):
        """Test that post-write validation is skipped when disabled."""
        # Create empty file (would normally fail)
        output_path = tmp_path / "content" / "products" / "de" / "test.md"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("", encoding="utf-8")

        source_path = tmp_path / "content" / "products" / "en" / "test.md"

        # Mock config with enabled=False
        mock_config = {
            "validation_defaults": {
                "post_write": {
                    "enabled": False,
                    "delete_on_failure": False,
                    "halt_on_failure": False,
                }
            }
        }
        translation_engine.config.get_config = Mock(return_value=mock_config)

        # Mock site profile
        mock_profile = Mock()
        mock_profile.default_source_lang = "en"

        # Run post-write validation - should pass (validation skipped)
        result = translation_engine._post_write_validation(
            output_path=output_path,
            source_path=source_path,
            target_lang="de",
            site_id="products.aspose.net",
            site_profile=mock_profile,
        )

        # Should pass because validation is disabled
        assert result is True

    def test_post_write_validation_wrong_language_folder(self, translation_engine, tmp_path):
        """Test post-write validation detects wrong language folder."""
        # Create file in wrong language folder
        output_path = tmp_path / "content" / "products" / "en" / "test.md"  # Should be 'de'
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("# Test Content\n\nTranslated text", encoding="utf-8")

        source_path = tmp_path / "content" / "products" / "en" / "test.md"

        # Mock config
        mock_config = {
            "validation_defaults": {
                "post_write": {
                    "enabled": True,
                    "delete_on_failure": False,
                    "halt_on_failure": False,
                }
            }
        }
        translation_engine.config.get_config = Mock(return_value=mock_config)

        # Mock site profile with all required attributes
        mock_profile = Mock()
        mock_profile.default_source_lang = "en"
        mock_profile.content_roots = []  # Empty list to skip content root validation
        mock_profile.target_langs = ["de", "fr", "es"]
        mock_profile.output_layout = None  # No output layout validation

        # Run post-write validation
        result = translation_engine._post_write_validation(
            output_path=output_path,
            source_path=source_path,
            target_lang="de",  # Expected language
            site_id="products.aspose.net",
            site_profile=mock_profile,
        )

        # Should fail due to language mismatch
        assert result is False
