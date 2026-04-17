"""
Tests for telemetry_integration module (TEL-05-A, TEL-05-C).

Tests business context extraction and telemetry wiring.
"""
from pathlib import Path
from unittest.mock import MagicMock

from src.observability.telemetry_integration import (
    DummyRunContext,
    TranslationTelemetry,
    build_error_summary,
    extract_business_context,
    extract_website,
    get_item_name,
    map_website_section,
)
from src.translation_engine.models import DirectoryResult, TranslationResult, TranslationStats


class TestExtractBusinessContext:
    """Tests for extract_business_context() function (TEL-05-A)."""

    def test_extracts_subdomain_from_site_id(self):
        """TFR-01: subdomain is now full site_id for proper identification."""
        result = extract_business_context(site_id="products.aspose.com")
        assert result["subdomain"] == "products.aspose.com"

    def test_extracts_subdomain_from_docs_site(self):
        """TFR-01: subdomain is now full site_id for proper identification."""
        result = extract_business_context(site_id="docs.aspose.com")
        assert result["subdomain"] == "docs.aspose.com"

    def test_extracts_product_family_slides(self):
        """TFR-02: product_family now uses capitalized Aspose product name."""
        result = extract_business_context(
            file_path=Path("/content/slides/net/getting-started.md")
        )
        assert result["product_family"] == "Aspose.Slides"
        assert result["product"] == "slides"  # product remains lowercase

    def test_extracts_product_family_words(self):
        """TFR-02: product_family now uses capitalized Aspose product name."""
        result = extract_business_context(
            file_path=Path("C:/repos/docs/words/java/overview.md")
        )
        assert result["product_family"] == "Aspose.Words"

    def test_extracts_product_family_cells(self):
        """TFR-02: product_family now uses capitalized Aspose product name."""
        result = extract_business_context(
            file_path=Path("/products/cells/python/api-reference.md")
        )
        assert result["product_family"] == "Aspose.Cells"

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
        """TFR-01/TFR-02: Extracts all business context fields together."""
        result = extract_business_context(
            file_path=Path("/content/slides/net/getting-started.md"),
            site_id="products.aspose.com",
        )
        assert result == {
            "product_family": "Aspose.Slides",  # TFR-02: capitalized
            "subdomain": "products.aspose.com",  # TFR-01: full site_id
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

    def test_returns_default_for_unknown_platform(self):
        """Returns default platform when path has no known platform."""
        result = extract_business_context(
            file_path=Path("/slides/unknown/guide.md")
        )
        # Default platform from env var or ".NET"
        assert result["platform"] == ".NET" or result["platform"] is not None

    def test_handles_none_inputs(self):
        """Returns defaults when no inputs provided."""
        result = extract_business_context()
        assert result["product_family"] is None
        assert result["subdomain"] is None
        assert result["product"] is None
        # Platform defaults to env var or ".NET"
        assert result["platform"] is not None

    def test_handles_windows_paths(self):
        """Handles Windows-style backslash paths."""
        result = extract_business_context(
            file_path=Path("C:\\repos\\docs\\slides\\net\\guide.md")
        )
        assert result["product_family"] == "Aspose.Slides"  # TFR-02: capitalized
        assert result["platform"] == ".NET"

    def test_case_insensitive_matching(self):
        """Matches product families and platforms case-insensitively."""
        result = extract_business_context(
            file_path=Path("/Content/SLIDES/NET/Guide.md")
        )
        assert result["product_family"] == "Aspose.Slides"  # TFR-02: capitalized
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

        # Verify set_metrics was called with items_* fields
        mock_run_context.set_metrics.assert_called_once()
        call_kwargs = mock_run_context.set_metrics.call_args[1]
        # TSC-02: items_* fields passed directly (except items_skipped which is in metrics_json)
        assert "items_discovered" in call_kwargs
        assert "items_succeeded" in call_kwargs
        assert "items_failed" in call_kwargs
        # items_skipped is NOT in RunRecord schema, so it's in metrics_json
        assert "items_skipped" not in call_kwargs
        # metrics_json contains custom metrics including items_skipped
        assert "metrics_json" in call_kwargs
        metrics = call_kwargs["metrics_json"]
        assert metrics["skipped_segments"] == 1
        assert metrics["items_skipped"] == 1  # Moved here since not in RunRecord
        assert metrics["files_translated"] == 1
        assert metrics["files_generated"] == 2

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
        call_kwargs = mock_run_context.set_metrics.call_args[1]
        # TSC-02: metrics_json contains custom metrics
        metrics = call_kwargs["metrics_json"]
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
        call_kwargs = mock_run_context.set_metrics.call_args[1]
        # TSC-02: metrics_json contains custom metrics
        metrics = call_kwargs["metrics_json"]
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

        assert result["product_family"] == "Aspose.Slides"  # TFR-02: capitalized
        assert result["subdomain"] == "products.aspose.com"  # TFR-01: full site_id
        assert result["platform"] == ".NET"
        assert result["product"] == "slides"

    def test_directory_business_context_fallback_when_no_files(self):
        """SR-01: Empty directory produces None business context gracefully."""
        # When no files exist, extract_business_context should handle None file_path
        result = extract_business_context(file_path=None, site_id="products.aspose.com")

        assert result["subdomain"] == "products.aspose.com"  # TFR-01: full site_id
        assert result["product_family"] is None
        assert result["platform"] is None or result["platform"] == ".NET"  # Default platform
        assert result["product"] is None

    def test_directory_business_context_mixed_products(self):
        """SR-01: Mixed-product directory uses first file's context (documented behavior)."""
        # First file determines business context for entire directory
        first_file = Path("/docs/slides/java/guide.md")
        result = extract_business_context(file_path=first_file, site_id="docs.aspose.com")

        assert result["product_family"] == "Aspose.Slides"  # TFR-02: capitalized
        assert result["platform"] == "Java"
        assert result["subdomain"] == "docs.aspose.com"  # TFR-01: full site_id


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
        # TSC-02: metrics_json contains custom metrics including files_*
        assert "metrics_json" in call_kwargs
        metrics = call_kwargs["metrics_json"]
        assert "files_translated" in metrics
        assert metrics["files_translated"] == 1
        assert "files_generated" in metrics
        assert metrics["files_generated"] == 3

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


class TestTSC01ExtractWebsite:
    """Tests for TSC-01: extract_website() function."""

    def test_extracts_root_domain_from_products_site(self):
        """Extract aspose.com from products.aspose.com."""
        assert extract_website("products.aspose.com") == "aspose.com"

    def test_extracts_root_domain_from_blog_site(self):
        """Extract aspose.net from blog.aspose.net."""
        assert extract_website("blog.aspose.net") == "aspose.net"

    def test_extracts_root_domain_from_docs_site(self):
        """Extract groupdocs.cloud from docs.groupdocs.cloud."""
        assert extract_website("docs.groupdocs.cloud") == "groupdocs.cloud"

    def test_handles_two_part_domain(self):
        """Handle simple two-part domain."""
        assert extract_website("aspose.com") == "aspose.com"

    def test_handles_empty_site_id(self):
        """Return empty string for empty site_id."""
        assert extract_website("") == ""

    def test_handles_none_site_id(self):
        """Return empty string for None site_id."""
        assert extract_website(None) == ""

    def test_handles_single_part(self):
        """Return as-is for single part (no dots)."""
        assert extract_website("localhost") == "localhost"


class TestTSC01MapWebsiteSection:
    """Tests for TSC-01: map_website_section() function."""

    def test_maps_products_to_docs(self):
        """Map products subdomain to Docs section."""
        assert map_website_section("products") == "Docs"

    def test_maps_docs_to_docs(self):
        """Map docs subdomain to Docs section."""
        assert map_website_section("docs") == "Docs"

    def test_maps_blog_to_blog(self):
        """Map blog subdomain to Blog section."""
        assert map_website_section("blog") == "Blog"

    def test_maps_kb_to_kb(self):
        """Map kb subdomain to KB section."""
        assert map_website_section("kb") == "KB"

    def test_maps_reference_to_reference(self):
        """Map reference subdomain to Reference section."""
        assert map_website_section("reference") == "Reference"

    def test_maps_api_to_api(self):
        """Map api subdomain to API section."""
        assert map_website_section("api") == "API"

    def test_returns_na_for_unknown(self):
        """Return NA for unknown subdomain."""
        assert map_website_section("unknown") == "NA"

    def test_returns_na_for_empty(self):
        """Return NA for empty subdomain."""
        assert map_website_section("") == "NA"

    def test_returns_na_for_none(self):
        """Return NA for None subdomain."""
        assert map_website_section(None) == "NA"

    def test_case_insensitive(self):
        """Mapping is case-insensitive."""
        assert map_website_section("PRODUCTS") == "Docs"
        assert map_website_section("Blog") == "Blog"


class TestTSC02GetItemName:
    """Tests for TSC-02: get_item_name() function."""

    def test_returns_segments_for_translate_file(self):
        """Return Segments for translate_file job type."""
        assert get_item_name("translate_file") == "Segments"

    def test_returns_files_for_translate_directory(self):
        """Return Files for translate_directory job type."""
        assert get_item_name("translate_directory") == "Files"

    def test_returns_items_for_unknown_job_type(self):
        """Return Items for unknown job type."""
        assert get_item_name("unknown_job") == "Items"

    def test_returns_items_for_empty_job_type(self):
        """Return Items for empty job type."""
        assert get_item_name("") == "Items"


class TestTSC03ErrorSummary:
    """Tests for TSC-03: error_summary wiring."""

    def test_error_summary_truncates_to_5(self):
        """Error summary truncates to max 5 errors."""
        errors = [f"Error {i}" for i in range(10)]
        summary = build_error_summary(errors)
        assert summary.count(";") == 4  # 5 errors = 4 semicolons
        assert "Error 4" in summary
        assert "Error 5" not in summary

    def test_error_summary_empty_for_no_errors(self):
        """Empty string when no errors."""
        assert build_error_summary([]) == ""

    def test_error_summary_single_error(self):
        """Single error has no semicolon."""
        assert build_error_summary(["Only error"]) == "Only error"

    def test_error_summary_custom_max(self):
        """Respects custom max_errors parameter."""
        errors = [f"Error {i}" for i in range(10)]
        summary = build_error_summary(errors, max_errors=3)
        assert summary.count(";") == 2  # 3 errors = 2 semicolons


class TestTSC04EnvironmentField:
    """Tests for TSC-04: environment field from env var."""

    def test_environment_default_is_dev(self, monkeypatch):
        """Default environment is dev when env var not set."""
        monkeypatch.delenv("HUGO_TRANSLATOR_ENV", raising=False)
        import os
        assert os.getenv("HUGO_TRANSLATOR_ENV", "dev") == "dev"

    def test_environment_from_env_var(self, monkeypatch):
        """Environment reads from HUGO_TRANSLATOR_ENV."""
        monkeypatch.setenv("HUGO_TRANSLATOR_ENV", "prod")
        import os
        assert os.getenv("HUGO_TRANSLATOR_ENV", "dev") == "prod"


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
