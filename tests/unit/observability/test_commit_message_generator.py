"""
Unit tests for CommitMessageGenerator.

Tests path analysis, product/section detection, and message generation.
"""
import unittest
from pathlib import Path
from dataclasses import dataclass, field
from typing import List

from src.observability.commit_message_generator import CommitMessageGenerator


# Mock classes matching actual DirectoryResult/TranslationResult structure
@dataclass
class MockTranslationStats:
    """Mock TranslationStats for testing."""
    model_used: str = ""
    total_segments: int = 0
    l1_hits: int = 0
    l2_hits: int = 0
    l3_hits: int = 0
    tm_hit_rate: float = 0.0


@dataclass
class MockTranslationResult:
    """Mock TranslationResult for testing."""
    input_path: Path
    output_path: Path
    stats: MockTranslationStats
    success: bool = True


@dataclass
class MockDirectoryResult:
    """Mock DirectoryResult for testing."""
    file_results: List[MockTranslationResult] = field(default_factory=list)
    success: bool = True
    directory: Path = Path(".")
    total_files: int = 0
    successful_files: int = 0
    failed_files: int = 0
    duration_seconds: float = 0.0

    def __post_init__(self):
        """Auto-calculate counts from file_results."""
        if self.total_files == 0:
            self.total_files = len(self.file_results)
        if self.successful_files == 0:
            self.successful_files = sum(1 for fr in self.file_results if fr.success)
        if self.failed_files == 0:
            self.failed_files = self.total_files - self.successful_files

    @property
    def aggregate_stats(self) -> MockTranslationStats:
        """Aggregate stats from all file results."""
        if not self.file_results:
            return MockTranslationStats()

        total_segments = sum(r.stats.total_segments for r in self.file_results)
        l1_hits = sum(r.stats.l1_hits for r in self.file_results)
        l2_hits = sum(r.stats.l2_hits for r in self.file_results)
        l3_hits = sum(r.stats.l3_hits for r in self.file_results)

        tm_hit_rate = (l1_hits + l2_hits + l3_hits) / total_segments if total_segments > 0 else 0.0

        return MockTranslationStats(
            model_used=self.file_results[0].stats.model_used if self.file_results else "",
            total_segments=total_segments,
            l1_hits=l1_hits,
            l2_hits=l2_hits,
            l3_hits=l3_hits,
            tm_hit_rate=tm_hit_rate,
        )


class TestCommitMessageGenerator(unittest.TestCase):
    """Test CommitMessageGenerator functionality."""

    def test_initialization(self):
        """Test generator initializes correctly."""
        generator = CommitMessageGenerator()
        self.assertIsNotNone(generator)
        self.assertGreater(len(generator.product_patterns), 0)

    def test_aspose_slides_detection(self):
        """Test detection of Aspose.Slides product and section."""
        generator = CommitMessageGenerator()

        output_files = [
            Path("D:/aspose.net/content/products.aspose.net/slides/cs/presentation-converter/_index.md"),
            Path("D:/aspose.net/content/products.aspose.net/slides/cs/presentation-converter/ppt-to-pdf/_index.md"),
        ]

        subject, body = generator.generate(
            output_files=output_files,
            target_langs=["cs"],
            site_id="aspose.net",
            run_id="test-001",
        )

        # Verify subject components
        self.assertIn("slides", subject.lower())
        self.assertIn("presentation-converter", subject.lower())
        self.assertIn("2", subject)
        self.assertIn("cs", subject.lower())

        # Verify body components
        self.assertIn("Aspose.Slides", body)
        # Body displays with spaces, not hyphens
        self.assertTrue("presentation converter" in body.lower() or "presentation-converter" in body.lower())

    def test_aspose_cells_detection(self):
        """Test detection of Aspose.Cells product."""
        generator = CommitMessageGenerator()

        output_files = [
            Path("D:/aspose.net/content/products.aspose.net/cells/fr/features/chart-to-pdf/_index.md")
        ]

        subject, body = generator.generate(
            output_files=output_files,
            target_langs=["fr"],
            site_id="aspose.net",
            run_id="test-002",
        )

        self.assertIn("cells", subject.lower())
        self.assertIn("Aspose.Cells", body)

    def test_with_translation_metadata(self):
        """Test message generation with full translation metadata."""
        generator = CommitMessageGenerator()

        output_files = [
            Path("D:/aspose.net/content/products.aspose.net/pdf/es/features/create-pdf/_index.md")
        ]

        mock_stats = MockTranslationStats(
            model_used="facebook/m2m100_418M",
            total_segments=150,
            l1_hits=45,
            l2_hits=30,
            l3_hits=15,
        )

        mock_results = [
            MockTranslationResult(
                input_path=Path("D:/aspose.net/content/products.aspose.net/pdf/en/features/create-pdf/_index.md"),
                output_path=output_files[0],
                stats=mock_stats,
            )
        ]

        mock_dir_result = MockDirectoryResult(file_results=mock_results)

        subject, body = generator.generate(
            output_files=output_files,
            target_langs=["es"],
            site_id="aspose.net",
            run_id="test-004",
            translation_result=mock_dir_result,
        )

        # Verify model or TM information is mentioned (flexible check)
        has_model_info = "Model:" in body or "m2m100" in body.lower() or "facebook" in body.lower()
        has_validation_info = "Validation:" in body or "passed" in body.lower()

        self.assertTrue(has_model_info or has_validation_info, "Should include translation metadata")

    def test_fallback_no_metadata(self):
        """Test fallback message generation without metadata."""
        generator = CommitMessageGenerator()

        output_files = [
            Path("D:/somewhere/random/file.md"),
            Path("D:/somewhere/random/other.md"),
        ]

        subject, body = generator.generate(
            output_files=output_files,
            target_langs=["it"],
            site_id="test-site",
            run_id="test-005",
            translation_result=None,
        )

        # Should still generate a valid message
        self.assertIn("2", subject)
        self.assertIn("file", subject.lower())
        self.assertIn("it", subject.lower())
        self.assertGreater(len(body), 0)

    def test_single_file(self):
        """Test message generation for single file."""
        generator = CommitMessageGenerator()

        output_files = [
            Path("D:/aspose.net/content/products.aspose.net/diagram/pt/features/visio-to-pdf/_index.md")
        ]

        subject, body = generator.generate(
            output_files=output_files,
            target_langs=["pt"],
            site_id="aspose.net",
            run_id="test-006",
        )

        self.assertIn("1", subject)
        self.assertIn("diagram", subject.lower())
        self.assertIn("pt", subject.lower())

    def test_subject_length_limit(self):
        """Test that subject line doesn't exceed conventional limit."""
        generator = CommitMessageGenerator()

        # Create a path with a very long section name
        output_files = [
            Path("D:/aspose.net/content/products.aspose.net/slides/cs/very-long-section-name-that-exceeds-normal-limits/_index.md")
        ]

        subject, body = generator.generate(
            output_files=output_files,
            target_langs=["cs"],
            site_id="aspose.net",
            run_id="test-009",
        )

        # Subject should be reasonable length (allow some margin beyond 72)
        self.assertLessEqual(len(subject), 80)

    def test_empty_file_list(self):
        """Test handling of empty file list."""
        generator = CommitMessageGenerator()

        output_files = []

        subject, body = generator.generate(
            output_files=output_files,
            target_langs=["en"],
            site_id="test-site",
            run_id="test-012",
        )

        # Should still generate something (fallback)
        self.assertGreater(len(subject), 0)
        self.assertGreater(len(body), 0)


if __name__ == "__main__":
    unittest.main()
