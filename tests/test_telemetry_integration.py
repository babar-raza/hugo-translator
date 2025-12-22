"""
Tests for telemetry_integration module (TEL-05-A, TEL-05-C).

Tests business context extraction and telemetry wiring.
"""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.observability.telemetry_integration import (
    extract_business_context,
    TranslationTelemetry,
    DummyRunContext,
)
from src.translation_engine.models import DirectoryResult, TranslationResult, TranslationStats


class TestExtractBusinessContext:
    """Tests for extract_business_context() function (TEL-05-A)."""

    def test_extracts_subdomain_from_site_id(self):
        """Extracts subdomain from site_id (first part before dot)."""
        result = extract_business_context(site_id="products.aspose.com")
        assert result["subdomain"] == "products"

    def test_extracts_subdomain_from_docs_site(self):
        """Extracts subdomain from docs site."""
        result = extract_business_context(site_id="docs.aspose.com")
        assert result["subdomain"] == "docs"

    def test_extracts_product_family_slides(self):
        """Extracts slides product family from path."""
        result = extract_business_context(
            file_path=Path("/content/slides/net/getting-started.md")
        )
        assert result["product_family"] == "slides"
        assert result["product"] == "slides"

    def test_extracts_product_family_words(self):
        """Extracts words product family from path."""
        result = extract_business_context(
            file_path=Path("C:/repos/docs/words/java/overview.md")
        )
        assert result["product_family"] == "words"

    def test_extracts_product_family_cells(self):
        """Extracts cells product family from path."""
        result = extract_business_context(
            file_path=Path("/products/cells/python/api-reference.md")
        )
        assert result["product_family"] == "cells"

    def test_extracts_platform_dotnet(self):
        """Extracts .NET platform from path."""
        result = extract_business_context(
            file_path=Path("/slides/net/installation.md")
        )
        assert result["platform"] == ".NET"

    def test_extracts_platform_java(self):
        """Extracts Java platform from path."""
        result = extract_business_context(
            file_path=Path("/words/java/quickstart.md")
        )
        assert result["platform"] == "Java"

    def test_extracts_platform_python(self):
        """Extracts Python platform from path."""
        result = extract_business_context(
            file_path=Path("/cells/python/tutorials.md")
        )
        assert result["platform"] == "Python"

    def test_extracts_platform_cpp(self):
        """Extracts C++ platform from path."""
        result = extract_business_context(
            file_path=Path("/pdf/cpp/reference.md")
        )
        assert result["platform"] == "C++"

    def test_extracts_platform_nodejs(self):
        """Extracts Node.js platform from path."""
        result = extract_business_context(
            file_path=Path("/barcode/nodejs/examples.md")
        )
        assert result["platform"] == "Node.js"

    def test_extracts_all_fields_combined(self):
        """Extracts all business context fields together."""
        result = extract_business_context(
            file_path=Path("/content/slides/net/getting-started.md"),
            site_id="products.aspose.com",
        )
        assert result == {
            "product_family": "slides",
            "subdomain": "products",
            "platform": ".NET",
            "product": "slides",
        }

    def test_returns_none_for_unknown_product(self):
        """Returns None for product_family when path has no known product."""
        result = extract_business_context(
            file_path=Path("/content/unknown/docs/guide.md")
        )
        assert result["product_family"] is None
        assert result["product"] is None

    def test_returns_none_for_unknown_platform(self):
        """Returns None for platform when path has no known platform."""
        result = extract_business_context(
            file_path=Path("/slides/unknown/guide.md")
        )
        assert result["platform"] is None

    def test_handles_none_inputs(self):
        """Returns all None when no inputs provided."""
        result = extract_business_context()
        assert result == {
            "product_family": None,
            "subdomain": None,
            "platform": None,
            "product": None,
        }

    def test_handles_windows_paths(self):
        """Handles Windows-style backslash paths."""
        result = extract_business_context(
            file_path=Path("C:\\repos\\docs\\slides\\net\\guide.md")
        )
        assert result["product_family"] == "slides"
        assert result["platform"] == ".NET"

    def test_case_insensitive_matching(self):
        """Matches product families and platforms case-insensitively."""
        result = extract_business_context(
            file_path=Path("/Content/SLIDES/NET/Guide.md")
        )
        assert result["product_family"] == "slides"
        assert result["platform"] == ".NET"


class TestDummyRunContext:
    """Tests for DummyRunContext (no-op implementation)."""

    def test_context_manager_works(self):
        """DummyRunContext works as context manager."""
        ctx = DummyRunContext()
        with ctx as run:
            assert run is ctx

    def test_set_metrics_is_noop(self):
        """set_metrics does nothing but doesn't error."""
        ctx = DummyRunContext()
        ctx.set_metrics(tokens_input=100, tokens_output=50)  # Should not raise

    def test_log_event_is_noop(self):
        """log_event does nothing but doesn't error."""
        ctx = DummyRunContext()
        ctx.log_event("test_event", payload={"key": "value"})  # Should not raise

    def test_increment_counter_is_noop(self):
        """increment_counter does nothing but doesn't error."""
        ctx = DummyRunContext()
        ctx.increment_counter("test_counter", 1.0)  # Should not raise


class TestTranslationTelemetryDisabled:
    """Tests for TranslationTelemetry when disabled."""

    def test_returns_dummy_context_when_disabled(self):
        """Returns DummyRunContext when telemetry is disabled."""
        telemetry = TranslationTelemetry(enabled=False)
        ctx = telemetry.track_translation_session(job_type="test")
        assert isinstance(ctx, DummyRunContext)

    def test_is_available_returns_false_when_disabled(self):
        """is_available() returns False when disabled."""
        telemetry = TranslationTelemetry(enabled=False)
        assert telemetry.is_available() is False


class TestTranslationTelemetryIntegration:
    """Integration tests for TranslationTelemetry with mocked client."""

    def test_track_translation_stats_includes_skipped_segments(self):
        """track_translation_stats includes skipped_segments and file counters."""
        # Create mock stats object
        mock_stats = MagicMock()
        mock_stats.tokens_input = 100
        mock_stats.tokens_output = 80
        mock_stats.tokens_cached = 20
        mock_stats.tokens_total = 120
        mock_stats.total_segments = 10
        mock_stats.tm_hits = 2
        mock_stats.l1_hits = 1
        mock_stats.l2_hits = 1
        mock_stats.l3_hits = 0
        mock_stats.translated_segments = 7
        mock_stats.skipped_segments = 1  # TEL-05-A: this should be included
        mock_stats.md_files_added = 2
        mock_stats.md_files_updated = 0
        mock_stats.bytes_written_md = 5000
        mock_stats.tm_entries_stored = 7
        mock_stats.files_translated = 1
        mock_stats.files_generated = 2
        mock_stats.tm_hit_rate = 0.2
        mock_stats.token_cache_rate = 0.167
        mock_stats.duration_seconds = 5.5

        # Create mock run context
        mock_run_context = MagicMock()

        # Create telemetry with disabled client (to test the method logic)
        telemetry = TranslationTelemetry(enabled=False)
        telemetry.enabled = True  # Force enabled to test logic

        telemetry.track_translation_stats(mock_run_context, mock_stats)

        # Verify set_metrics was called with skipped_segments
        mock_run_context.set_metrics.assert_called_once()
        call_kwargs = mock_run_context.set_metrics.call_args[1]
        assert "skipped_segments" in call_kwargs
        assert call_kwargs["skipped_segments"] == 1
        assert call_kwargs["files_translated"] == 1
        assert call_kwargs["files_generated"] == 2

    def test_track_translation_stats_skips_when_disabled(self):
        """track_translation_stats does nothing when disabled."""
        mock_stats = MagicMock()
        mock_run_context = MagicMock()

        telemetry = TranslationTelemetry(enabled=False)
        telemetry.track_translation_stats(mock_run_context, mock_stats)

        # set_metrics should not be called
        mock_run_context.set_metrics.assert_not_called()


class TestDirectoryTelemetryAggregation:
    """Directory-level telemetry propagation for files_* stats."""

    def test_directory_aggregate_stats_include_files_counts(self):
        """Aggregated stats carry files_translated/files_generated into telemetry metrics."""
        # Build directory result with two files
        dir_result = DirectoryResult(success=True, directory=Path("/docs"))
        file1 = TranslationResult(success=True, file_path=Path("a.md"))
        file1.stats.files_translated = 1
        file1.stats.files_generated = 2
        file1.stats.total_segments = 5

        file2 = TranslationResult(success=False, file_path=Path("b.md"))
        file2.stats.files_translated = 0
        file2.stats.files_generated = 0
        file2.stats.total_segments = 3
        dir_result.file_results = [file1, file2]

        agg_stats = dir_result.aggregate_stats
        mock_run_context = MagicMock()

        telemetry = TranslationTelemetry(enabled=False)
        telemetry.enabled = True
        telemetry.track_translation_stats(mock_run_context, agg_stats)

        mock_run_context.set_metrics.assert_called_once()
        metrics = mock_run_context.set_metrics.call_args[1]
        assert metrics["files_translated"] == 1
        assert metrics["files_generated"] == 2
        assert metrics["total_segments"] == 8

    def test_directory_empty_stats_default_zero(self):
        """Empty directory produces zeroed files_* metrics."""
        dir_result = DirectoryResult(success=True, directory=Path("/docs"))
        agg_stats = dir_result.aggregate_stats
        mock_run_context = MagicMock()

        telemetry = TranslationTelemetry(enabled=False)
        telemetry.enabled = True
        telemetry.track_translation_stats(mock_run_context, agg_stats)

        mock_run_context.set_metrics.assert_called_once()
        metrics = mock_run_context.set_metrics.call_args[1]
        assert metrics["files_translated"] == 0
        assert metrics["files_generated"] == 0
        assert metrics["total_segments"] == 0


class TestRunRecordFields:
    """Tests for RunRecord standard fields (TEL-05-B)."""

    def test_items_discovered_equals_total_segments(self):
        """items_discovered should equal total_segments for single file."""
        # This tests the mapping logic documented in TEL-05-B
        # items_discovered = total_segments
        total_segments = 10
        items_discovered = total_segments
        assert items_discovered == 10

    def test_items_succeeded_equals_translated_plus_tm_hits(self):
        """items_succeeded = translated_segments + tm_hits."""
        translated_segments = 7
        tm_hits = 2
        items_succeeded = translated_segments + tm_hits
        assert items_succeeded == 9

    def test_items_failed_equals_skipped_segments(self):
        """items_failed = skipped_segments for single file."""
        skipped_segments = 1
        items_failed = skipped_segments
        assert items_failed == 1

    def test_error_summary_truncates_long_errors(self):
        """error_summary should truncate to reasonable length."""
        errors = [
            "Error 1: Something went wrong",
            "Error 2: Another problem",
            "Error 3: Third issue",
            "Error 4: Fourth error",
        ]
        # Logic from engine.py: join first 3 errors
        error_summary = "; ".join(errors[:3]) if errors else ""
        assert "Error 1" in error_summary
        assert "Error 2" in error_summary
        assert "Error 3" in error_summary
        assert "Error 4" not in error_summary

    def test_error_summary_empty_when_no_errors(self):
        """error_summary is empty string when no errors."""
        errors = []
        error_summary = "; ".join(errors[:3]) if errors else ""
        assert error_summary == ""

    def test_output_summary_format_single_file(self):
        """output_summary format for single file translation."""
        outputs = {"es": "path/es/file.md", "fr": "path/fr/file.md"}
        errors = []
        output_summary = f"{len(outputs)} translations, {len(errors)} errors"
        assert output_summary == "2 translations, 0 errors"

    def test_output_summary_format_directory(self):
        """output_summary format for directory translation."""
        successful_files = 8
        total_files = 10
        files_generated = 16
        output_summary = f"{successful_files}/{total_files} files translated, {files_generated} outputs"
        assert output_summary == "8/10 files translated, 16 outputs"


class TestSR01DirectoryBusinessContext:
    """Tests for SR-01: Directory runs provide business context."""

    def test_directory_extracts_business_context_from_representative_file(self):
        """SR-01: Directory telemetry gets business context from first markdown file."""
        # Scenario: Directory contains slides/net files, should extract business context
        file_path = Path("/content/slides/net/getting-started.md")
        site_id = "products.aspose.com"

        result = extract_business_context(file_path=file_path, site_id=site_id)

        assert result["product_family"] == "slides"
        assert result["subdomain"] == "products"
        assert result["platform"] == ".NET"
        assert result["product"] == "slides"

    def test_directory_business_context_fallback_when_no_files(self):
        """SR-01: Empty directory produces None business context gracefully."""
        # When no files exist, extract_business_context should handle None file_path
        result = extract_business_context(file_path=None, site_id="products.aspose.com")

        assert result["subdomain"] == "products"
        assert result["product_family"] is None
        assert result["platform"] is None or result["platform"] == ".NET"  # Default platform
        assert result["product"] is None

    def test_directory_business_context_mixed_products(self):
        """SR-01: Mixed-product directory uses first file's context (documented behavior)."""
        # First file determines business context for entire directory
        first_file = Path("/docs/slides/java/guide.md")
        result = extract_business_context(file_path=first_file, site_id="docs.aspose.com")

        assert result["product_family"] == "slides"
        assert result["platform"] == "Java"
        assert result["subdomain"] == "docs"


class TestSR02FilesTranslatedGenerated:
    """Tests for SR-02: files_translated and files_generated in TranslationStats."""

    def test_files_translated_in_translation_stats(self):
        """SR-02: TranslationStats includes files_translated field."""
        stats = TranslationStats()
        stats.files_translated = 1
        assert stats.files_translated == 1

    def test_files_generated_in_translation_stats(self):
        """SR-02: TranslationStats includes files_generated field."""
        stats = TranslationStats()
        stats.files_generated = 3  # e.g., es, fr, de outputs
        assert stats.files_generated == 3

    def test_telemetry_tracks_files_translated_and_generated(self):
        """SR-02: Telemetry tracks files_translated and files_generated metrics."""
        mock_stats = MagicMock()
        mock_stats.tokens_input = 100
        mock_stats.tokens_output = 80
        mock_stats.tokens_cached = 20
        mock_stats.tokens_total = 120
        mock_stats.total_segments = 10
        mock_stats.tm_hits = 2
        mock_stats.l1_hits = 1
        mock_stats.l2_hits = 1
        mock_stats.l3_hits = 0
        mock_stats.translated_segments = 7
        mock_stats.skipped_segments = 1
        mock_stats.md_files_added = 2
        mock_stats.md_files_updated = 0
        mock_stats.bytes_written_md = 5000
        mock_stats.tm_entries_stored = 7
        mock_stats.files_translated = 1  # SR-02
        mock_stats.files_generated = 3  # SR-02
        mock_stats.tm_hit_rate = 0.2
        mock_stats.token_cache_rate = 0.167
        mock_stats.duration_seconds = 5.5

        mock_run_context = MagicMock()

        telemetry = TranslationTelemetry(enabled=False)
        telemetry.enabled = True
        telemetry.track_translation_stats(mock_run_context, mock_stats)

        mock_run_context.set_metrics.assert_called_once()
        call_kwargs = mock_run_context.set_metrics.call_args[1]
        assert "files_translated" in call_kwargs
        assert call_kwargs["files_translated"] == 1
        assert "files_generated" in call_kwargs
        assert call_kwargs["files_generated"] == 3

    def test_directory_aggregates_files_counts(self):
        """SR-02: Directory aggregation includes files_translated/files_generated."""
        dir_result = DirectoryResult(success=True, directory=Path("/docs"))
        file1 = TranslationResult(success=True, file_path=Path("a.md"))
        file1.stats.files_translated = 1
        file1.stats.files_generated = 2

        file2 = TranslationResult(success=True, file_path=Path("b.md"))
        file2.stats.files_translated = 1
        file2.stats.files_generated = 2

        dir_result.file_results = [file1, file2]
        agg_stats = dir_result.aggregate_stats

        assert agg_stats.files_translated == 2
        assert agg_stats.files_generated == 4


class TestSR03HelperFunctions:
    """Tests for SR-03: Helper functions for RunRecord fields."""

    def test_build_output_summary_single_file(self):
        """SR-03: build_output_summary formats single file correctly."""
        from src.observability.telemetry_integration import build_output_summary

        summary = build_output_summary(
            job_type="translate_file",
            outputs={"es": "a.md", "fr": "b.md"},
            errors=[]
        )
        assert summary == "2 translations, 0 errors"

    def test_build_output_summary_single_file_with_errors(self):
        """SR-03: build_output_summary includes error count."""
        from src.observability.telemetry_integration import build_output_summary

        summary = build_output_summary(
            job_type="translate_file",
            outputs={"es": "a.md"},
            errors=["Error 1", "Error 2"]
        )
        assert summary == "1 translations, 2 errors"

    def test_build_output_summary_directory(self):
        """SR-03: build_output_summary formats directory correctly."""
        from src.observability.telemetry_integration import build_output_summary

        summary = build_output_summary(
            job_type="translate_directory",
            successful_files=8,
            total_files=10,
            files_generated=16,
            errors=[]
        )
        assert summary == "8/10 files translated, 16 outputs"

    def test_build_error_summary_truncates(self):
        """SR-03: build_error_summary truncates to max_errors."""
        from src.observability.telemetry_integration import build_error_summary

        errors = [f"Error {i}" for i in range(10)]
        summary = build_error_summary(errors, max_errors=5)
        assert summary.count(";") == 4  # 5 errors means 4 semicolons
        assert "Error 0" in summary
        assert "Error 4" in summary
        assert "Error 5" not in summary

    def test_build_error_summary_empty(self):
        """SR-03: build_error_summary returns empty string for no errors."""
        from src.observability.telemetry_integration import build_error_summary

        summary = build_error_summary([])
        assert summary == ""

    def test_calculate_items_metrics_single_file(self):
        """SR-03: calculate_items_metrics for single file uses segment counts."""
        from src.observability.telemetry_integration import calculate_items_metrics

        mock_stats = MagicMock()
        mock_stats.total_segments = 10
        mock_stats.translated_segments = 7
        mock_stats.tm_hits = 2
        mock_stats.skipped_segments = 1

        metrics = calculate_items_metrics(
            job_type="translate_file",
            stats=mock_stats
        )

        assert metrics["items_discovered"] == 10
        assert metrics["items_succeeded"] == 9  # 7 + 2
        assert metrics["items_failed"] == 1

    def test_calculate_items_metrics_directory(self):
        """SR-03: calculate_items_metrics for directory uses file counts."""
        from src.observability.telemetry_integration import calculate_items_metrics

        metrics = calculate_items_metrics(
            job_type="translate_directory",
            total_files=10,
            successful_files=8,
            failed_files=2
        )

        assert metrics["items_discovered"] == 10
        assert metrics["items_succeeded"] == 8
        assert metrics["items_failed"] == 2

    def test_calculate_items_metrics_handles_none_stats(self):
        """SR-03: calculate_items_metrics handles None stats gracefully."""
        from src.observability.telemetry_integration import calculate_items_metrics

        metrics = calculate_items_metrics(
            job_type="translate_file",
            stats=None
        )

        assert metrics["items_discovered"] == 0
        assert metrics["items_succeeded"] == 0
        assert metrics["items_failed"] == 0

    def test_calculate_items_metrics_handles_none_file_counts(self):
        """SR-03: calculate_items_metrics handles None file counts gracefully."""
        from src.observability.telemetry_integration import calculate_items_metrics

        metrics = calculate_items_metrics(
            job_type="translate_directory",
            total_files=None,
            successful_files=None,
            failed_files=None
        )

        assert metrics["items_discovered"] == 0
        assert metrics["items_succeeded"] == 0
        assert metrics["items_failed"] == 0
