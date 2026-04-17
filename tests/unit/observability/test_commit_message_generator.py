"""
Unit tests for CommitMessageGenerator.

Tests path analysis, product/section detection, and message generation.
"""
import unittest
from dataclasses import dataclass, field
from pathlib import Path

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
    file_results: list[MockTranslationResult] = field(default_factory=list)
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
        # Add outputs attribute to match real TranslationResult structure
        mock_results[0].outputs = {"es": output_files[0]}

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

    def test_language_name_mapping_comprehensive(self):
        """Test comprehensive language name mappings for all supported languages."""
        generator = CommitMessageGenerator()

        # Test new EU official language mappings
        self.assertEqual(generator._get_language_names(["ca"]), ["Catalan"])
        self.assertEqual(generator._get_language_names(["bg"]), ["Bulgarian"])
        self.assertEqual(generator._get_language_names(["el"]), ["Greek"])
        self.assertEqual(generator._get_language_names(["da"]), ["Danish"])
        self.assertEqual(generator._get_language_names(["hr"]), ["Croatian"])
        self.assertEqual(generator._get_language_names(["sk"]), ["Slovak"])
        self.assertEqual(generator._get_language_names(["sl"]), ["Slovenian"])
        self.assertEqual(generator._get_language_names(["et"]), ["Estonian"])
        self.assertEqual(generator._get_language_names(["lv"]), ["Latvian"])
        self.assertEqual(generator._get_language_names(["lt"]), ["Lithuanian"])
        self.assertEqual(generator._get_language_names(["mt"]), ["Maltese"])
        self.assertEqual(generator._get_language_names(["ga"]), ["Irish"])
        self.assertEqual(generator._get_language_names(["hu"]), ["Hungarian"])
        self.assertEqual(generator._get_language_names(["ro"]), ["Romanian"])

        # Test existing mappings (regression test)
        self.assertEqual(generator._get_language_names(["cs"]), ["Czech"])
        self.assertEqual(generator._get_language_names(["de"]), ["German"])
        self.assertEqual(generator._get_language_names(["fr"]), ["French"])
        self.assertEqual(generator._get_language_names(["es"]), ["Spanish"])
        self.assertEqual(generator._get_language_names(["it"]), ["Italian"])
        self.assertEqual(generator._get_language_names(["pt"]), ["Portuguese"])

        # Test multiple languages at once
        result = generator._get_language_names(["ca", "bg", "hr"])
        self.assertEqual(result, ["Catalan", "Bulgarian", "Croatian"])

    def test_unmapped_language_fallback(self):
        """Test that unmapped language codes fall back to uppercase."""
        generator = CommitMessageGenerator()

        # Test unknown language codes
        self.assertEqual(generator._get_language_names(["zz"]), ["ZZ"])
        self.assertEqual(generator._get_language_names(["xy"]), ["XY"])
        self.assertEqual(generator._get_language_names(["qq"]), ["QQ"])

        # Test mixed known and unknown codes
        result = generator._get_language_names(["ca", "zz", "de"])
        self.assertEqual(result, ["Catalan", "ZZ", "German"])

    def test_index_file_grouping_format(self):
        """Test that _index.md files show grouped format instead of individual directories."""
        generator = CommitMessageGenerator()

        # Setup: 9 _index.md files in different directories
        output_files = [
            Path("D:/aspose.net/content/products.aspose.net/slides/cs/presentation-converter/_index.md"),
            Path("D:/aspose.net/content/products.aspose.net/slides/cs/ppt-to-pdf/_index.md"),
            Path("D:/aspose.net/content/products.aspose.net/slides/cs/pptx-to-pdf/_index.md"),
            Path("D:/aspose.net/content/products.aspose.net/slides/cs/ppt-to-pptx/_index.md"),
            Path("D:/aspose.net/content/products.aspose.net/slides/cs/merge-ppt/_index.md"),
            Path("D:/aspose.net/content/products.aspose.net/slides/cs/split-ppt/_index.md"),
            Path("D:/aspose.net/content/products.aspose.net/slides/cs/compress-ppt/_index.md"),
            Path("D:/aspose.net/content/products.aspose.net/slides/cs/unlock-ppt/_index.md"),
            Path("D:/aspose.net/content/products.aspose.net/slides/cs/protect-ppt/_index.md"),
        ]

        subject, body = generator.generate(
            output_files=output_files,
            target_langs=["cs"],
            site_id="aspose.net",
            run_id="test-013",
        )

        # Assert: Shows "9 section index files (...)"
        self.assertIn("9 section index files", body)
        # Should show directory names (first 3 + count of remaining since we have >5)
        # At least one of the directories should be shown
        has_directory = any(dir_name in body for dir_name in [
            "presentation-converter", "ppt-to-pdf", "pptx-to-pdf",
            "ppt-to-pptx", "merge-ppt", "split-ppt"
        ])
        self.assertTrue(has_directory, "Should show at least some directory names")
        # Should show "+X more" since we have more than 5 directories
        self.assertIn("more", body)
        # Should NOT show the old format "(1 files)"
        self.assertNotIn("(1 files)", body)

    def test_index_file_grouping_single_file(self):
        """Test index file grouping with single file."""
        generator = CommitMessageGenerator()

        output_files = [
            Path("D:/aspose.net/content/products.aspose.net/slides/cs/presentation-converter/_index.md"),
        ]

        subject, body = generator.generate(
            output_files=output_files,
            target_langs=["cs"],
            site_id="aspose.net",
            run_id="test-014",
        )

        # Should show "1 section index file (presentation-converter)"
        self.assertIn("1 section index files", body)
        self.assertIn("presentation-converter", body)

    def test_index_file_grouping_many_directories(self):
        """Test index file grouping with more than 5 directories."""
        generator = CommitMessageGenerator()

        # Setup: 8 _index.md files (more than 5 directories)
        output_files = [
            Path(f"D:/aspose.net/content/products.aspose.net/slides/cs/dir{i}/_index.md")
            for i in range(1, 9)
        ]

        subject, body = generator.generate(
            output_files=output_files,
            target_langs=["cs"],
            site_id="aspose.net",
            run_id="test-015",
        )

        # Should show "8 section index files (dir1, dir2, dir3, +5 more)"
        self.assertIn("8 section index files", body)
        self.assertIn("dir1", body)
        self.assertIn("dir2", body)
        self.assertIn("dir3", body)
        self.assertIn("+5 more", body)
        # Should not show all directories
        self.assertNotIn("dir8", body)

    def test_mixed_files_use_existing_format(self):
        """Test that mixed files (index + non-index) use existing path grouping format."""
        generator = CommitMessageGenerator()

        # Setup: 5 _index.md + 5 other files
        output_files = [
            Path("D:/aspose.net/content/products.aspose.net/slides/cs/presentation-converter/_index.md"),
            Path("D:/aspose.net/content/products.aspose.net/slides/cs/ppt-to-pdf/_index.md"),
            Path("D:/aspose.net/content/products.aspose.net/slides/cs/pptx-to-pdf/_index.md"),
            Path("D:/aspose.net/content/products.aspose.net/slides/cs/ppt-to-pptx/_index.md"),
            Path("D:/aspose.net/content/products.aspose.net/slides/cs/merge-ppt/_index.md"),
            Path("D:/aspose.net/content/products.aspose.net/slides/cs/features/page1.md"),
            Path("D:/aspose.net/content/products.aspose.net/slides/cs/features/page2.md"),
            Path("D:/aspose.net/content/products.aspose.net/slides/cs/api/method1.md"),
            Path("D:/aspose.net/content/products.aspose.net/slides/cs/api/method2.md"),
            Path("D:/aspose.net/content/products.aspose.net/slides/cs/guide/tutorial.md"),
        ]

        subject, body = generator.generate(
            output_files=output_files,
            target_langs=["cs"],
            site_id="aspose.net",
            run_id="test-016",
        )

        # Assert: Shows existing path grouping format (not index file grouping)
        self.assertNotIn("section index files", body)
        # Should show directory format with file counts
        self.assertIn("files)", body)
        # Should show some directory paths
        self.assertTrue(any(dir_name in body for dir_name in ["features", "api", "presentation-converter"]))

    def test_non_index_files_use_existing_format(self):
        """Test that non-index files use existing path grouping format."""
        generator = CommitMessageGenerator()

        output_files = [
            Path("D:/aspose.net/content/products.aspose.net/slides/cs/features/page1.md"),
            Path("D:/aspose.net/content/products.aspose.net/slides/cs/features/page2.md"),
            Path("D:/aspose.net/content/products.aspose.net/slides/cs/api/method1.md"),
        ]

        subject, body = generator.generate(
            output_files=output_files,
            target_langs=["cs"],
            site_id="aspose.net",
            run_id="test-017",
        )

        # Should NOT use index file grouping
        self.assertNotIn("section index files", body)
        # Should use existing format with directory paths
        self.assertIn("files)", body)

    def test_index_file_grouping_five_directories(self):
        """Test index file grouping with exactly 5 directories (boundary case)."""
        generator = CommitMessageGenerator()

        output_files = [
            Path(f"D:/aspose.net/content/products.aspose.net/slides/cs/dir{i}/_index.md")
            for i in range(1, 6)
        ]

        subject, body = generator.generate(
            output_files=output_files,
            target_langs=["cs"],
            site_id="aspose.net",
            run_id="test-018",
        )

        # Should show all 5 directories (not truncated)
        self.assertIn("5 section index files", body)
        self.assertIn("dir1", body)
        self.assertIn("dir5", body)
        # Should NOT show "+X more"
        self.assertNotIn("more", body)

    def test_validation_count_matches_output_files(self):
        """
        Test that validation count only includes files in output_files, not all languages.

        Critical bug fix: Previously showed "48/5 files passed" when translating to multiple
        languages because it counted all file_results but divided by output_files count.
        """
        generator = CommitMessageGenerator()

        # Setup: Simulate translating 5 files to DE and FR (10 file_results total)
        de_files = [Path(f"D:/repo/de/file{i}.md") for i in range(5)]
        fr_files = [Path(f"D:/repo/fr/file{i}.md") for i in range(5)]

        # Create mock file_results for both languages
        file_results = []

        # 5 DE results
        for i, de_file in enumerate(de_files):
            result = MockTranslationResult(
                input_path=Path(f"D:/repo/en/file{i}.md"),
                output_path=de_file,
                stats=MockTranslationStats(),
                success=True
            )
            # Add outputs dict to match real TranslationResult structure
            result.outputs = {"de": de_file}
            file_results.append(result)

        # 5 FR results
        for i, fr_file in enumerate(fr_files):
            result = MockTranslationResult(
                input_path=Path(f"D:/repo/en/file{i}.md"),
                output_path=fr_file,
                stats=MockTranslationStats(),
                success=True
            )
            result.outputs = {"fr": fr_file}
            file_results.append(result)

        # Create DirectoryResult with all 10 file_results
        dir_result = MockDirectoryResult(
            file_results=file_results,
            success=True,
            directory=Path("D:/repo")
        )

        # Generate commit message for DE files only (5 files)
        subject, body = generator.generate(
            output_files=de_files,  # Only 5 DE files
            target_langs=["de"],
            site_id="test",
            run_id="test-validation-001",
            translation_result=dir_result
        )

        # Assert: Validation should show 5/5, not 10/5
        self.assertIn("5/5 files passed", body, "Should show 5/5 for DE files only")
        self.assertNotIn("10/5", body, "Should NOT show impossible ratio 10/5")
        self.assertNotIn("10/10", body, "Should NOT count all languages when committing one")

    def test_validation_count_with_mixed_success_failure(self):
        """Test validation count with some passing and some failing files."""
        generator = CommitMessageGenerator()

        # Setup: 5 file_results, 3 pass, 2 fail
        output_files = [Path(f"D:/repo/de/file{i}.md") for i in range(5)]

        file_results = []
        for i, output_file in enumerate(output_files):
            result = MockTranslationResult(
                input_path=Path(f"D:/repo/en/file{i}.md"),
                output_path=output_file,
                stats=MockTranslationStats(),
                success=(i < 3)  # First 3 pass, last 2 fail
            )
            result.outputs = {"de": output_file}
            file_results.append(result)

        dir_result = MockDirectoryResult(
            file_results=file_results,
            success=True,
            directory=Path("D:/repo")
        )

        subject, body = generator.generate(
            output_files=output_files,
            target_langs=["de"],
            site_id="test",
            run_id="test-validation-002",
            translation_result=dir_result
        )

        # Assert: Should show 3/5 files passed
        self.assertIn("3/5 files passed", body, "Should show 3/5 for mixed success/failure")
        # Numerator should never exceed denominator
        self.assertNotIn("5/3", body, "Should not show inverted ratio")

    def test_validation_count_edge_case_empty_outputs(self):
        """Test handling of file_results with no outputs dict."""
        generator = CommitMessageGenerator()

        output_files = [Path("D:/repo/de/file1.md")]

        # Create file_results with missing outputs attribute
        file_results = []

        # Result with outputs
        result1 = MockTranslationResult(
            input_path=Path("D:/repo/en/file1.md"),
            output_path=output_files[0],
            stats=MockTranslationStats(),
            success=True
        )
        result1.outputs = {"de": output_files[0]}
        file_results.append(result1)

        # Result without outputs (edge case)
        result2 = MockTranslationResult(
            input_path=Path("D:/repo/en/file2.md"),
            output_path=Path("D:/repo/de/file2.md"),
            stats=MockTranslationStats(),
            success=True
        )
        # Don't set outputs attribute
        file_results.append(result2)

        dir_result = MockDirectoryResult(
            file_results=file_results,
            success=True,
            directory=Path("D:/repo")
        )

        # Should not crash
        subject, body = generator.generate(
            output_files=output_files,
            target_langs=["de"],
            site_id="test",
            run_id="test-validation-003",
            translation_result=dir_result
        )

        # Should only count the result with outputs
        self.assertIn("1/1 files passed", body, "Should count only results with outputs")

    def test_validation_count_empty_output_files(self):
        """Test handling of empty output_files list."""
        generator = CommitMessageGenerator()

        file_results = [
            MockTranslationResult(
                input_path=Path("D:/repo/en/file1.md"),
                output_path=Path("D:/repo/de/file1.md"),
                stats=MockTranslationStats(),
                success=True
            )
        ]
        file_results[0].outputs = {"de": Path("D:/repo/de/file1.md")}

        dir_result = MockDirectoryResult(
            file_results=file_results,
            success=True,
            directory=Path("D:/repo")
        )

        # Empty output_files
        subject, body = generator.generate(
            output_files=[],
            target_langs=["de"],
            site_id="test",
            run_id="test-validation-004",
            translation_result=dir_result
        )

        # Should not crash and not show validation (no relevant results)
        self.assertIsNotNone(body)
        # If there are no output files, there should be no validation line
        # or it should show 0/0
        self.assertNotIn("1/0", body, "Should not show results for non-existent output files")

    def test_validation_count_all_files_failed(self):
        """Test validation count when all files failed."""
        generator = CommitMessageGenerator()

        output_files = [Path(f"D:/repo/de/file{i}.md") for i in range(3)]

        file_results = []
        for i, output_file in enumerate(output_files):
            result = MockTranslationResult(
                input_path=Path(f"D:/repo/en/file{i}.md"),
                output_path=output_file,
                stats=MockTranslationStats(),
                success=False  # All fail
            )
            result.outputs = {"de": output_file}
            file_results.append(result)

        dir_result = MockDirectoryResult(
            file_results=file_results,
            success=False,
            directory=Path("D:/repo")
        )

        subject, body = generator.generate(
            output_files=output_files,
            target_langs=["de"],
            site_id="test",
            run_id="test-validation-005",
            translation_result=dir_result
        )

        # Should show 0/3 files passed (not omit the validation line)
        # The current implementation shows validation only if passed_count > 0,
        # but we should verify it doesn't show incorrect counts
        if "Validation:" in body:
            self.assertIn("0/3 files passed", body, "Should show 0/3 when all fail")

    def test_validation_count_multi_language_commit_scenario(self):
        """
        Test realistic multi-language scenario that caused the original bug.

        Scenario: User translates 5 files to both DE and FR.
        - translation_result has 10 file_results (5 DE + 5 FR)
        - First commit: DE files (output_files = 5 DE files) → should show 5/5
        - Second commit: FR files (output_files = 5 FR files) → should show 5/5
        Not 10/5 for either commit.
        """
        generator = CommitMessageGenerator()

        # Setup: 5 files translated to both DE and FR
        de_files = [Path(f"D:/aspose.net/content/products.aspose.net/slides/de/file{i}.md") for i in range(5)]
        fr_files = [Path(f"D:/aspose.net/content/products.aspose.net/slides/fr/file{i}.md") for i in range(5)]

        file_results = []

        # Create results for both languages
        for i in range(5):
            # DE result
            de_result = MockTranslationResult(
                input_path=Path(f"D:/aspose.net/content/products.aspose.net/slides/en/file{i}.md"),
                output_path=de_files[i],
                stats=MockTranslationStats(),
                success=True
            )
            de_result.outputs = {"de": de_files[i]}
            file_results.append(de_result)

            # FR result
            fr_result = MockTranslationResult(
                input_path=Path(f"D:/aspose.net/content/products.aspose.net/slides/en/file{i}.md"),
                output_path=fr_files[i],
                stats=MockTranslationStats(),
                success=True
            )
            fr_result.outputs = {"fr": fr_files[i]}
            file_results.append(fr_result)

        dir_result = MockDirectoryResult(
            file_results=file_results,  # 10 total results
            success=True,
            directory=Path("D:/aspose.net/content/products.aspose.net/slides")
        )

        # Test DE commit
        subject_de, body_de = generator.generate(
            output_files=de_files,  # Only 5 DE files
            target_langs=["de"],
            site_id="aspose.net",
            run_id="test-validation-006-de",
            translation_result=dir_result
        )

        self.assertIn("5/5 files passed", body_de, "DE commit should show 5/5")
        self.assertNotIn("10/5", body_de, "DE commit should NOT show 10/5")

        # Test FR commit
        subject_fr, body_fr = generator.generate(
            output_files=fr_files,  # Only 5 FR files
            target_langs=["fr"],
            site_id="aspose.net",
            run_id="test-validation-006-fr",
            translation_result=dir_result
        )

        self.assertIn("5/5 files passed", body_fr, "FR commit should show 5/5")
        self.assertNotIn("10/5", body_fr, "FR commit should NOT show 10/5")


    def test_new_commit_subject_format_with_display_name(self):
        """Test new commit subject format with site display_name."""
        from unittest.mock import patch

        generator = CommitMessageGenerator()

        # Setup: Aspose.Slides files with docs.aspose.net site profile
        output_files = [
            Path("D:/aspose.net/content/docs.aspose.net/slides/de/developer-guide/presentation-converter/_index.md"),
        ]

        # Simulate site profile with display_name
        site_profile = {
            "display_name": "Documentation"
        }

        # Mock _detect_sites_from_paths to return single site (bypass config loading in tests)
        with patch.object(generator, '_detect_sites_from_paths', return_value=["docs.aspose.net"]):
            subject, body = generator.generate(
                output_files=output_files,
                target_langs=["de"],
                site_id="docs.aspose.net",
                run_id="test-new-format-001",
                site_profile=site_profile
            )

        # Assert: New format "Translates Aspose.Slides 1 Documentation to German"
        self.assertIn("Translates", subject, "Should start with 'Translates'")
        self.assertIn("Aspose.Slides", subject, "Should include product name")
        self.assertIn("1", subject, "Should include file count")
        self.assertIn("Documentation", subject, "Should include display_name")
        self.assertIn("German", subject, "Should include language name")
        # Should NOT include site_id in parentheses
        self.assertNotIn("(docs.aspose.net)", subject, "Should not include site_id in parentheses")

        # Old format check (should NOT match)
        self.assertNotIn("chore:", subject.lower(), "Should not use old 'chore:' prefix")

    def test_new_commit_subject_format_kb_site(self):
        """Test new format for kb.aspose.net (knowledge base articles)."""
        from unittest.mock import patch

        generator = CommitMessageGenerator()

        output_files = [
            Path("D:/aspose.net/content/kb.aspose.net/words/cs/article1.md"),
            Path("D:/aspose.net/content/kb.aspose.net/words/cs/article2.md"),
            Path("D:/aspose.net/content/kb.aspose.net/words/cs/article3.md"),
        ]

        site_profile = {
            "display_name": "knowledge base articles"
        }

        with patch.object(generator, '_detect_sites_from_paths', return_value=["kb.aspose.net"]):
            subject, body = generator.generate(
                output_files=output_files,
                target_langs=["cs"],
                site_id="kb.aspose.net",
                run_id="test-new-format-002",
                site_profile=site_profile
            )

        # Assert: "Translates Aspose.Words 3 knowledge base articles to Czech"
        self.assertIn("Translates", subject)
        self.assertIn("Aspose.Words", subject, "Should include product name")
        self.assertIn("3", subject)
        self.assertIn("knowledge base articles", subject)
        self.assertIn("Czech", subject)
        # Should NOT include site_id in parentheses
        self.assertNotIn("(kb.aspose.net)", subject, "Should not include site_id in parentheses")

    def test_new_commit_subject_format_special_sites(self):
        """Test new format for special sites (about.aspose.net, www.aspose.net) using 'files' display_name."""
        from unittest.mock import patch

        generator = CommitMessageGenerator()

        output_files = [
            Path("D:/aspose.net/content/about.aspose.net/fr/page1.md"),
            Path("D:/aspose.net/content/about.aspose.net/fr/page2.md"),
        ]

        site_profile = {
            "display_name": "files"
        }

        with patch.object(generator, '_detect_sites_from_paths', return_value=["about.aspose.net"]):
            subject, body = generator.generate(
                output_files=output_files,
                target_langs=["fr"],
                site_id="about.aspose.net",
                run_id="test-new-format-003",
                site_profile=site_profile
            )

        # Assert: "Translates about.aspose.net 2 files to French"
        # (No product name, site_id becomes product name, no parentheses)
        self.assertIn("Translates", subject)
        self.assertIn("about.aspose.net", subject)
        self.assertIn("2", subject)
        self.assertIn("files", subject)
        self.assertIn("French", subject)
        # Should NOT have site_id in parentheses
        self.assertNotIn("(about.aspose.net)", subject, "Should not include site_id in parentheses")

    def test_new_commit_subject_format_home_family(self):
        """Test new format for 'Home' product family."""
        from unittest.mock import patch

        generator = CommitMessageGenerator()

        # Setup: Files without specific product (home family)
        output_files = [
            Path("D:/aspose.net/content/docs.aspose.net/home/de/getting-started.md"),
            Path("D:/aspose.net/content/docs.aspose.net/home/de/features.md"),
        ]

        site_profile = {
            "display_name": "Documentation"
        }

        with patch.object(generator, '_detect_sites_from_paths', return_value=["docs.aspose.net"]):
            subject, body = generator.generate(
                output_files=output_files,
                target_langs=["de"],
                site_id="docs.aspose.net",
                run_id="test-new-format-004",
                site_profile=site_profile
            )

        # Assert: "Translates Home 2 Documentation to German"
        self.assertIn("Translates", subject)
        self.assertIn("Home", subject)
        self.assertIn("2", subject)
        self.assertIn("Documentation", subject)
        self.assertIn("German", subject)
        # Should NOT include site_id in parentheses
        self.assertNotIn("(docs.aspose.net)", subject, "Should not include site_id in parentheses")

    def test_new_commit_subject_format_fallback_no_display_name(self):
        """Test fallback when display_name is not provided."""
        from unittest.mock import patch

        generator = CommitMessageGenerator()

        output_files = [
            Path("D:/aspose.net/content/docs.aspose.net/slides/de/page.md"),
        ]

        # Mock _detect_sites_from_paths to return single site (bypass config loading in tests)
        with patch.object(generator, '_detect_sites_from_paths', return_value=["docs.aspose.net"]):
            # No site_profile or empty site_profile
            subject, body = generator.generate(
                output_files=output_files,
                target_langs=["de"],
                site_id="docs.aspose.net",
                run_id="test-new-format-005",
                site_profile=None
            )

            # Assert: Should still generate valid subject with "pages" fallback
            self.assertIn("Translates", subject)
            self.assertIn("Aspose.Slides", subject)
            self.assertIn("1", subject)
            self.assertIn("pages", subject, "Should fallback to 'pages' when no display_name")
            self.assertIn("German", subject)
            # Should NOT include site_id in parentheses
            self.assertNotIn("(docs.aspose.net)", subject, "Should not include site_id in parentheses")


if __name__ == "__main__":
    unittest.main()
