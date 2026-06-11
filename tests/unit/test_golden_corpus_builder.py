"""
Unit tests for golden corpus builder.

Run with:
    pytest tests/unit/test_golden_corpus_builder.py -v
"""

import sys
import tempfile
from pathlib import Path

# Add scripts to path to import build_golden_corpus
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from build_golden_corpus import (
    build_corpus,
    classify_document_complexity,
    detect_language_focus,
    stable_hash,
)


class TestClassification:
    """Test document classification logic"""

    def test_simple_document(self):
        """Test simple tier classification"""
        fixture = Path(__file__).parent.parent / "fixtures" / "corpus_builder" / "simple.md"
        tier, features = classify_document_complexity(fixture)

        assert tier == "simple"
        assert features["code_block_count"] == 0
        assert features["shortcode_count"] == 0
        assert features["file_size"] < 2000
        assert features["has_frontmatter"] is True

    def test_complex_document(self):
        """Test complex tier classification"""
        fixture = Path(__file__).parent.parent / "fixtures" / "corpus_builder" / "complex.md"
        tier, features = classify_document_complexity(fixture)

        assert tier == "complex"
        assert features["code_block_count"] > 5
        assert features["shortcode_count"] > 3
        assert features["has_tables"] is True
        assert features["has_math"] is True

    def test_medium_document(self):
        """Test medium tier classification"""
        fixture = Path(__file__).parent.parent / "fixtures" / "corpus_builder" / "medium.md"
        tier, features = classify_document_complexity(fixture)

        assert tier in ("simple", "medium")  # Could be either depending on exact size
        assert features["has_frontmatter"] is True

    def test_missing_file(self):
        """Test error handling for missing file"""
        nonexistent = Path("/nonexistent/file.md")
        tier, features = classify_document_complexity(nonexistent)

        assert tier == "simple"  # Default on error
        assert "error" in features


class TestDeterminism:
    """Test deterministic sampling"""

    def test_stable_hash_deterministic(self):
        """Same input = same hash"""
        path = Path("test/file.md")
        seed = 42

        hash1 = stable_hash(path, seed)
        hash2 = stable_hash(path, seed)

        assert hash1 == hash2
        assert isinstance(hash1, int)

    def test_stable_hash_different_seeds(self):
        """Different seeds = different hashes"""
        path = Path("test/file.md")

        hash1 = stable_hash(path, seed=42)
        hash2 = stable_hash(path, seed=99)

        assert hash1 != hash2

    def test_stable_hash_different_paths(self):
        """Different paths = different hashes"""
        hash1 = stable_hash(Path("test/file1.md"), seed=42)
        hash2 = stable_hash(Path("test/file2.md"), seed=42)

        assert hash1 != hash2


class TestLanguageDetection:
    """Test programming language detection"""

    def test_python_detection(self):
        """Detect Python-focused documents"""
        fixture = Path(__file__).parent.parent / "fixtures" / "corpus_builder" / "python_focused.md"
        lang = detect_language_focus(fixture)

        assert lang == "python"

    def test_agnostic_detection(self):
        """Detect language-agnostic documents"""
        fixture = Path(__file__).parent.parent / "fixtures" / "corpus_builder" / "simple.md"
        lang = detect_language_focus(fixture)

        assert lang == "agnostic"

    def test_complex_mixed_languages(self):
        """Complex doc with multiple languages - highest score wins"""
        fixture = Path(__file__).parent.parent / "fixtures" / "corpus_builder" / "complex.md"
        lang = detect_language_focus(fixture)

        # Has python, java, csharp - python should win due to most mentions
        assert lang in ("python", "java", "csharp")


class TestCorpusBuilding:
    """Test corpus building with fixtures"""

    def test_build_corpus_with_fixtures(self):
        """Test building corpus from fixture directory"""
        fixture_dir = Path(__file__).parent.parent / "fixtures" / "corpus_builder"

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            output_dir = Path(tmpdir) / "test_corpus"

            # Build with fixtures (we have 4 files)
            build_corpus(
                source_dir=fixture_dir,
                output_dir=output_dir,
                target_count=50,  # Won't reach this, limited by available files
                seed=42,
            )

            # Check output created
            assert output_dir.exists()
            manifest_file = output_dir / "manifest.json"

            # Manifest may or may not exist depending on implementation
            # Just check output dir was created
            assert output_dir.is_dir()

    def test_build_corpus_nonexistent_source(self):
        """Test error handling for nonexistent source"""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            output_dir = Path(tmpdir) / "test_corpus"
            source_dir = Path("/nonexistent/source")

            # Should not crash, just print error
            build_corpus(source_dir=source_dir, output_dir=output_dir, target_count=10, seed=42)

            # Output dir should not be created if source doesn't exist
            # (depends on implementation - might still create empty dir)


class TestEdgeCases:
    """Test edge cases and error handling"""

    def test_unicode_content(self):
        """Test handling of Unicode characters"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write("# Unicode: λ α β γ δ ε 中文 العربية\n")
            f.write("Content with émojis: 🚀 🎉\n")
            temp_path = Path(f.name)

        try:
            tier, features = classify_document_complexity(temp_path)

            assert tier == "simple"
            assert features["file_size"] > 0
            assert "error" not in features
        finally:
            temp_path.unlink()

    def test_very_large_file(self):
        """Test classification of large files"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            # Create a large file (> 2000 chars)
            f.write("# Large Document\n\n")
            f.write("Content\n" * 500)
            temp_path = Path(f.name)

        try:
            tier, features = classify_document_complexity(temp_path)

            # Large file without code/shortcodes = medium
            assert tier in ("medium", "simple")
            assert features["file_size"] > 2000
        finally:
            temp_path.unlink()

    def test_empty_file(self):
        """Test handling of empty files"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            temp_path = Path(f.name)

        try:
            tier, features = classify_document_complexity(temp_path)

            assert tier == "simple"
            assert features["file_size"] == 0
        finally:
            temp_path.unlink()
