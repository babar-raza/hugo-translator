"""
Unit tests for translation engine result models.
"""
from pathlib import Path

from src.translation_engine.models import (
    DirectoryResult,
    TranslationResult,
    TranslationStats,
    ValidationIssue,
    ValidationResult,
)


class TestTranslationStats:
    """Test TranslationStats model."""

    def test_stats_initialization(self):
        """Test creating TranslationStats."""
        stats = TranslationStats()
        assert stats.total_segments == 0
        assert stats.tm_hits == 0
        assert stats.translated_segments == 0

    def test_tm_hit_rate_calculation(self):
        """Test TM hit rate calculation."""
        stats = TranslationStats(total_segments=100, tm_hits=75)
        assert stats.tm_hit_rate == 0.75

    def test_tm_hit_rate_zero_segments(self):
        """Test TM hit rate with zero segments."""
        stats = TranslationStats(total_segments=0, tm_hits=0)
        assert stats.tm_hit_rate == 0.0

    def test_stats_string_representation(self):
        """Test string representation."""
        stats = TranslationStats(
            total_segments=50,
            tm_hits=30,
            translated_segments=20,
            duration_seconds=2.5,
        )
        str_repr = str(stats)
        assert "total=50" in str_repr
        assert "tm_hits=30" in str_repr
        assert "new=20" in str_repr

    def test_layer_specific_hits(self):
        """Test tracking layer-specific hits."""
        stats = TranslationStats(
            total_segments=100,
            tm_hits=80,
            l1_hits=50,
            l2_hits=20,
            l3_hits=10,
        )
        assert stats.l1_hits == 50
        assert stats.l2_hits == 20
        assert stats.l3_hits == 10


class TestTranslationResult:
    """Test TranslationResult model."""

    def test_result_initialization(self):
        """Test creating TranslationResult."""
        result = TranslationResult(
            success=True,
            file_path=Path("test.md"),
        )
        assert result.success is True
        assert result.file_path == Path("test.md")
        assert len(result.outputs) == 0
        assert len(result.errors) == 0

    def test_result_with_outputs(self):
        """Test result with output files."""
        result = TranslationResult(
            success=True,
            file_path=Path("test.md"),
            outputs={
                "fr": Path("output/fr/test.md"),
                "es": Path("output/es/test.md"),
            },
        )
        assert len(result.outputs) == 2
        assert "fr" in result.outputs
        assert "es" in result.outputs

    def test_result_with_errors(self):
        """Test result with errors."""
        result = TranslationResult(
            success=False,
            file_path=Path("test.md"),
            errors=["Parse error", "Translation failed"],
        )
        assert len(result.errors) == 2
        assert result.success is False

    def test_result_string_representation(self):
        """Test string representation."""
        result = TranslationResult(
            success=True,
            file_path=Path("test.md"),
        )
        str_repr = str(result)
        assert "SUCCESS" in str_repr
        assert "test.md" in str_repr


class TestDirectoryResult:
    """Test DirectoryResult model."""

    def test_directory_result_initialization(self):
        """Test creating DirectoryResult."""
        result = DirectoryResult(
            success=True,
            directory=Path("content/"),
        )
        assert result.success is True
        assert result.directory == Path("content/")
        assert len(result.file_results) == 0

    def test_aggregate_stats_empty(self):
        """Test aggregate stats with no files."""
        result = DirectoryResult(
            success=True,
            directory=Path("content/"),
        )
        agg = result.aggregate_stats
        assert agg.total_segments == 0

    def test_aggregate_stats_multiple_files(self):
        """Test aggregate stats across multiple files."""
        file1_result = TranslationResult(
            success=True,
            file_path=Path("test1.md"),
            stats=TranslationStats(
                total_segments=50,
                tm_hits=30,
                translated_segments=20,
            ),
        )
        file2_result = TranslationResult(
            success=True,
            file_path=Path("test2.md"),
            stats=TranslationStats(
                total_segments=30,
                tm_hits=20,
                translated_segments=10,
            ),
        )

        dir_result = DirectoryResult(
            success=True,
            directory=Path("content/"),
            file_results=[file1_result, file2_result],
            duration_seconds=5.0,
        )

        agg = dir_result.aggregate_stats
        assert agg.total_segments == 80
        assert agg.tm_hits == 50
        assert agg.translated_segments == 30
        assert agg.duration_seconds == 5.0

    def test_directory_result_string_representation(self):
        """Test string representation."""
        result = DirectoryResult(
            success=True,
            directory=Path("content/"),
            total_files=10,
            successful_files=8,
            failed_files=2,
        )
        str_repr = str(result)
        assert "SUCCESS" in str_repr
        assert "content" in str_repr  # Don't check separator (platform-specific)
        assert "8/10" in str_repr


class TestValidationIssue:
    """Test ValidationIssue model."""

    def test_issue_creation(self):
        """Test creating validation issue."""
        issue = ValidationIssue(
            severity="error",
            rule="YAMLValidRule",
            message="Invalid YAML syntax",
            location="test.md:10",
        )
        assert issue.severity == "error"
        assert issue.rule == "YAMLValidRule"
        assert issue.message == "Invalid YAML syntax"
        assert issue.location == "test.md:10"

    def test_issue_string_representation(self):
        """Test string representation."""
        issue = ValidationIssue(
            severity="warning",
            rule="LengthDeviation",
            message="Translation much shorter than original",
        )
        str_repr = str(issue)
        assert "WARNING" in str_repr
        assert "LengthDeviation" in str_repr


class TestValidationResult:
    """Test ValidationResult model."""

    def test_validation_result_valid(self):
        """Test valid validation result."""
        result = ValidationResult(valid=True, issues=[])
        assert result.valid is True
        assert len(result.errors) == 0

    def test_validation_result_with_errors(self):
        """Test validation result with errors."""
        issues = [
            ValidationIssue("error", "Rule1", "Error 1"),
            ValidationIssue("warning", "Rule2", "Warning 1"),
            ValidationIssue("info", "Rule3", "Info 1"),
        ]
        result = ValidationResult(valid=False, issues=issues)

        assert result.valid is False
        assert len(result.errors) == 1
        assert len(result.warnings) == 1
        assert len(result.info) == 1

    def test_validation_result_filters(self):
        """Test severity filtering."""
        issues = [
            ValidationIssue("error", "Rule1", "Error 1"),
            ValidationIssue("error", "Rule2", "Error 2"),
            ValidationIssue("warning", "Rule3", "Warning 1"),
        ]
        result = ValidationResult(valid=False, issues=issues)

        assert len(result.errors) == 2
        assert len(result.warnings) == 1
        assert len(result.info) == 0

    def test_validation_result_string_representation(self):
        """Test string representation."""
        issues = [
            ValidationIssue("error", "Rule1", "Error 1"),
            ValidationIssue("warning", "Rule2", "Warning 1"),
        ]
        result = ValidationResult(valid=False, issues=issues)
        str_repr = str(result)
        assert "INVALID" in str_repr
        assert "1 errors" in str_repr
        assert "1 warnings" in str_repr
