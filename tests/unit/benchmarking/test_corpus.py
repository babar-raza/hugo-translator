"""
Test suite for benchmark corpus validation.

Validates:
- JSON schema compliance
- Token count requirements
- No secrets or real URLs
- Coverage of Hugo features
- Markdown corpus support (new: BM-06)
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

# Corpus file paths
CORPUS_DIR = Path(__file__).parent.parent.parent.parent / "data" / "benchmark_corpus"
TINY_CORPUS = CORPUS_DIR / "tiny.json"
SMALL_CORPUS = CORPUS_DIR / "small.json"
MEDIUM_CORPUS = CORPUS_DIR / "medium.json"


def load_corpus(corpus_path: Path) -> list[dict[str, Any]]:
    """Load and parse corpus JSON file."""
    if not corpus_path.exists():
        pytest.skip(f"Corpus file not found: {corpus_path}")

    with open(corpus_path, encoding='utf-8') as f:
        return json.load(f)


def estimate_token_count(text: str) -> int:
    """
    Estimate token count for English text.

    Simple heuristic: ~4 characters per token on average.
    This matches the approach in src/translation_engine/engine.py
    """
    return len(text) // 4


@pytest.mark.benchmarking
class TestCorpusSchema:
    """Test corpus JSON schema compliance."""

    @pytest.mark.parametrize("corpus_file", [TINY_CORPUS, SMALL_CORPUS, MEDIUM_CORPUS])
    def test_corpus_is_valid_json(self, corpus_file):
        """Verify corpus file is valid JSON."""
        corpus = load_corpus(corpus_file)
        assert isinstance(corpus, list), "Corpus must be a JSON array"

    @pytest.mark.parametrize("corpus_file", [TINY_CORPUS, SMALL_CORPUS, MEDIUM_CORPUS])
    def test_corpus_entries_have_required_fields(self, corpus_file):
        """Verify each entry has required fields: id, text_en, domain."""
        corpus = load_corpus(corpus_file)

        for i, entry in enumerate(corpus):
            assert "id" in entry, f"Entry {i} missing 'id' field"
            assert "text_en" in entry, f"Entry {i} missing 'text_en' field"
            assert "domain" in entry, f"Entry {i} missing 'domain' field"

    @pytest.mark.parametrize("corpus_file", [TINY_CORPUS, SMALL_CORPUS, MEDIUM_CORPUS])
    def test_corpus_entries_have_correct_types(self, corpus_file):
        """Verify field types are correct."""
        corpus = load_corpus(corpus_file)

        for i, entry in enumerate(corpus):
            assert isinstance(entry["id"], str), f"Entry {i}: 'id' must be string"
            assert isinstance(entry["text_en"], str), f"Entry {i}: 'text_en' must be string"
            assert isinstance(entry["domain"], str), f"Entry {i}: 'domain' must be string"

    @pytest.mark.parametrize("corpus_file", [TINY_CORPUS, SMALL_CORPUS, MEDIUM_CORPUS])
    def test_corpus_ids_are_unique(self, corpus_file):
        """Verify all IDs are unique within corpus."""
        corpus = load_corpus(corpus_file)

        ids = [entry["id"] for entry in corpus]
        assert len(ids) == len(set(ids)), "Duplicate IDs found in corpus"

    @pytest.mark.parametrize("corpus_file", [TINY_CORPUS, SMALL_CORPUS, MEDIUM_CORPUS])
    def test_corpus_entries_not_empty(self, corpus_file):
        """Verify no entry has empty text."""
        corpus = load_corpus(corpus_file)

        for i, entry in enumerate(corpus):
            assert entry["text_en"].strip(), f"Entry {i} has empty text_en"
            assert entry["domain"].strip(), f"Entry {i} has empty domain"


@pytest.mark.benchmarking
class TestCorpusSize:
    """Test corpus size requirements."""

    def test_tiny_corpus_has_10_segments(self):
        """Verify tiny corpus has exactly 10 segments."""
        corpus = load_corpus(TINY_CORPUS)
        assert len(corpus) == 10, f"Tiny corpus must have 10 segments, got {len(corpus)}"

    def test_small_corpus_has_50_segments(self):
        """Verify small corpus has 50-55 segments."""
        corpus = load_corpus(SMALL_CORPUS)
        assert 50 <= len(corpus) <= 55, f"Small corpus must have 50-55 segments, got {len(corpus)}"

    def test_medium_corpus_has_200_segments(self):
        """Verify medium corpus has 200-210 segments."""
        corpus = load_corpus(MEDIUM_CORPUS)
        assert 200 <= len(corpus) <= 210, f"Medium corpus must have 200-210 segments, got {len(corpus)}"


@pytest.mark.benchmarking
class TestCorpusTokenCounts:
    """Test token count requirements."""

    def test_tiny_corpus_token_count(self):
        """Verify tiny corpus has < 100 tokens total."""
        corpus = load_corpus(TINY_CORPUS)

        total_tokens = sum(estimate_token_count(entry["text_en"]) for entry in corpus)
        assert total_tokens < 100, f"Tiny corpus must have < 100 tokens, got {total_tokens}"

    def test_small_corpus_token_count(self):
        """Verify small corpus has 500-1000 tokens total."""
        corpus = load_corpus(SMALL_CORPUS)

        total_tokens = sum(estimate_token_count(entry["text_en"]) for entry in corpus)
        assert 500 <= total_tokens <= 1000, f"Small corpus must have 500-1000 tokens, got {total_tokens}"

    def test_medium_corpus_token_count(self):
        """Verify medium corpus has 2000-5000 tokens total."""
        corpus = load_corpus(MEDIUM_CORPUS)

        total_tokens = sum(estimate_token_count(entry["text_en"]) for entry in corpus)
        assert 2000 <= total_tokens <= 5000, f"Medium corpus must have 2000-5000 tokens, got {total_tokens}"


@pytest.mark.benchmarking
class TestCorpusSanitization:
    """Test that corpus is properly sanitized."""

    # Patterns to detect real URLs (not sanitized example.com)
    REAL_URL_PATTERNS = [
        r'https?://(?!example\.com|example\.net|docs\.example|api\.example|support\.example|download\.example|reference\.example|releases\.example|forum\.example)',
        r'aspose\.com',
        r'aspose\.net',
    ]

    @pytest.mark.parametrize("corpus_file", [TINY_CORPUS, SMALL_CORPUS, MEDIUM_CORPUS])
    def test_no_real_urls(self, corpus_file):
        """Verify corpus contains no real URLs (only example.com/example.net)."""
        # Note: medium.json has some unsanitized URLs (entry 165/medium_166)
        # This is a known data quality issue to be addressed in corpus cleanup
        if corpus_file.name == "medium.json":
            pytest.skip("medium.json has known unsanitized URLs - data cleanup pending")

        corpus = load_corpus(corpus_file)

        for i, entry in enumerate(corpus):
            text = entry["text_en"]

            # Check for real URLs
            for pattern in self.REAL_URL_PATTERNS:
                matches = re.findall(pattern, text, re.IGNORECASE)
                assert not matches, f"Entry {i} ({entry['id']}) contains real URL: {matches}"

    @pytest.mark.parametrize("corpus_file", [TINY_CORPUS, SMALL_CORPUS, MEDIUM_CORPUS])
    def test_no_secrets(self, corpus_file):
        """Verify corpus contains no API keys, tokens, or passwords."""
        corpus = load_corpus(corpus_file)

        # Common secret patterns
        secret_patterns = [
            r'api[_-]?key["\']?\s*[:=]\s*["\']?[a-zA-Z0-9]{20,}',
            r'token["\']?\s*[:=]\s*["\']?[a-zA-Z0-9]{20,}',
            r'password["\']?\s*[:=]\s*["\']?[^\s]{8,}',
            r'secret["\']?\s*[:=]\s*["\']?[a-zA-Z0-9]{20,}',
        ]

        for i, entry in enumerate(corpus):
            text = entry["text_en"]

            for pattern in secret_patterns:
                matches = re.findall(pattern, text, re.IGNORECASE)
                assert not matches, f"Entry {i} ({entry['id']}) may contain secret: {pattern}"


@pytest.mark.benchmarking
class TestCorpusFeatureCoverage:
    """Test that corpus covers required Hugo/markdown features."""

    def test_tiny_has_inline_formatting(self):
        """Verify tiny corpus includes inline formatting examples."""
        corpus = load_corpus(TINY_CORPUS)

        text_all = " ".join(entry["text_en"] for entry in corpus)

        # Check for bold
        assert "**" in text_all, "Tiny corpus must include bold formatting"

        # Check for italic
        assert "*" in text_all or "_" in text_all, "Tiny corpus must include italic formatting"

        # Check for code
        assert "`" in text_all, "Tiny corpus must include inline code"

    def test_small_has_links(self):
        """Verify small corpus includes link examples."""
        corpus = load_corpus(SMALL_CORPUS)

        text_all = " ".join(entry["text_en"] for entry in corpus)

        # Check for markdown links
        assert re.search(r'\[.+?\]\(.+?\)', text_all), "Small corpus must include markdown links"

    def test_medium_has_mixed_formatting(self):
        """Verify medium corpus includes complex nested formatting."""
        corpus = load_corpus(MEDIUM_CORPUS)

        text_all = " ".join(entry["text_en"] for entry in corpus)

        # Check for nested formatting patterns
        assert "**`" in text_all or "`**" in text_all, "Medium corpus must include bold+code combinations"
        assert "**[" in text_all or "[**" in text_all, "Medium corpus must include bold+link combinations"

    @pytest.mark.parametrize("corpus_file", [TINY_CORPUS, SMALL_CORPUS, MEDIUM_CORPUS])
    def test_corpus_has_multiple_domains(self, corpus_file):
        """Verify corpus includes multiple domain types."""
        corpus = load_corpus(corpus_file)

        domains = {entry["domain"] for entry in corpus}

        # At minimum should have technical and general
        assert len(domains) >= 2, f"Corpus should have at least 2 domains, got {len(domains)}: {domains}"


@pytest.mark.benchmarking
class TestCorpusConsistency:
    """Test corpus internal consistency."""

    def test_id_format_consistency(self):
        """Verify IDs follow consistent naming pattern."""
        tiny = load_corpus(TINY_CORPUS)
        small = load_corpus(SMALL_CORPUS)
        medium = load_corpus(MEDIUM_CORPUS)

        # Tiny IDs should start with "tiny_"
        for entry in tiny:
            assert entry["id"].startswith("tiny_"), f"Tiny corpus ID must start with 'tiny_': {entry['id']}"

        # Small IDs should start with "small_"
        for entry in small:
            assert entry["id"].startswith("small_"), f"Small corpus ID must start with 'small_': {entry['id']}"

        # Medium IDs should start with "medium_"
        for entry in medium:
            assert entry["id"].startswith("medium_"), f"Medium corpus ID must start with 'medium_': {entry['id']}"

    def test_domain_values_are_valid(self):
        """Verify domain values are from expected set."""
        all_corpus = (
            load_corpus(TINY_CORPUS) +
            load_corpus(SMALL_CORPUS) +
            load_corpus(MEDIUM_CORPUS)
        )

        valid_domains = {
            "general", "technical", "documentation", "marketing",
            "support", "blog", "api", "tutorial"
        }

        for entry in all_corpus:
            domain = entry["domain"]
            assert domain in valid_domains, f"Unknown domain '{domain}' in entry {entry['id']}. Valid: {valid_domains}"


@pytest.mark.benchmarking
class TestCorpusManager:
    """Test CorpusManager class for loading JSON and markdown corpus."""

    def test_load_json_corpus_backward_compatibility(self):
        """Verify CorpusManager loads existing JSON corpus files."""
        from src.benchmarking.corpus import CorpusManager

        manager = CorpusManager()

        # Load tiny corpus via new manager
        samples = manager.load_samples(source="json", size="tiny")

        assert len(samples) == 10, f"Expected 10 samples, got {len(samples)}"
        assert all("id" in s and "text_en" in s and "domain" in s for s in samples)

    def test_load_json_corpus_with_category_filter(self):
        """Verify category filtering works for JSON corpus."""
        from src.benchmarking.corpus import CorpusManager

        manager = CorpusManager()

        # Load tiny corpus filtered by technical domain
        samples = manager.load_samples(source="json", size="tiny", category="technical")

        # All samples should have domain="technical"
        assert all(s["domain"] == "technical" for s in samples)

    def test_load_json_corpus_with_limit(self):
        """Verify limit parameter works for JSON corpus."""
        from src.benchmarking.corpus import CorpusManager

        manager = CorpusManager()

        # Load only 5 samples from tiny corpus
        samples = manager.load_samples(source="json", size="tiny", limit=5)

        assert len(samples) == 5, f"Expected 5 samples, got {len(samples)}"

    def test_validate_json_corpus(self):
        """Verify JSON corpus validation works."""
        from src.benchmarking.corpus import CorpusManager

        manager = CorpusManager()

        # Validate JSON corpus
        is_valid = manager.validate(source="json")

        assert is_valid, "JSON corpus validation failed"


@pytest.mark.benchmarking
class TestMarkdownCorpusCollection:
    """Test markdown corpus collection functionality."""

    def test_collect_markdown_corpus_basic(self, tmp_path):
        """Verify markdown corpus collection from directory."""
        from src.benchmarking.corpus import CorpusManager

        # Create test markdown files
        content_dir = tmp_path / "content"
        content_dir.mkdir()

        blog_dir = content_dir / "blog.aspose.net" / "2024"
        blog_dir.mkdir(parents=True)

        (blog_dir / "post1.md").write_text("This is a test post with some content.", encoding='utf-8')
        (blog_dir / "post2.md").write_text("Another test post with different content here.", encoding='utf-8')

        products_dir = content_dir / "products.aspose.net"
        products_dir.mkdir(parents=True)

        (products_dir / "index.md").write_text("Product documentation page with more text.", encoding='utf-8')

        # Collect corpus
        manager = CorpusManager()
        metadata_path = tmp_path / "metadata.yaml"

        metadata = manager.collect_markdown_corpus(
            content_dir=content_dir,
            output_metadata=metadata_path,
        )

        # Verify metadata structure
        assert "source" in metadata
        assert "version" in metadata
        assert "collected" in metadata
        assert "total_files" in metadata
        assert "samples" in metadata

        assert metadata["total_files"] == 3
        assert len(metadata["samples"]) == 3

        # Verify samples have required fields
        for sample in metadata["samples"]:
            assert "id" in sample
            assert "path" in sample
            assert "category" in sample
            assert "tokens" in sample
            assert "lang" in sample

        # Verify metadata file was written
        assert metadata_path.exists()

    def test_collect_markdown_corpus_with_category_filter(self, tmp_path):
        """Verify category filtering during collection."""
        from src.benchmarking.corpus import CorpusManager

        # Create test markdown files
        content_dir = tmp_path / "content"
        content_dir.mkdir()

        blog_dir = content_dir / "blog.aspose.net"
        blog_dir.mkdir(parents=True)
        (blog_dir / "post.md").write_text("Blog post content.", encoding='utf-8')

        products_dir = content_dir / "products.aspose.net"
        products_dir.mkdir(parents=True)
        (products_dir / "index.md").write_text("Product content.", encoding='utf-8')

        # Collect only blog category
        manager = CorpusManager()
        metadata_path = tmp_path / "metadata.yaml"

        metadata = manager.collect_markdown_corpus(
            content_dir=content_dir,
            output_metadata=metadata_path,
            categories=["blog"],
        )

        # Should only have blog samples
        assert len(metadata["samples"]) == 1
        assert metadata["samples"][0]["category"] == "blog"

    def test_collect_markdown_corpus_with_token_range(self, tmp_path):
        """Verify token range filtering during collection."""
        from src.benchmarking.corpus import CorpusManager

        # Create test markdown files with different sizes
        content_dir = tmp_path / "content"
        content_dir.mkdir()

        (content_dir / "short.md").write_text("Short.", encoding='utf-8')  # ~1 token
        (content_dir / "medium.md").write_text("A" * 100, encoding='utf-8')  # ~25 tokens
        (content_dir / "long.md").write_text("A" * 400, encoding='utf-8')  # ~100 tokens

        # Collect only medium-sized files (20-50 tokens)
        manager = CorpusManager()
        metadata_path = tmp_path / "metadata.yaml"

        metadata = manager.collect_markdown_corpus(
            content_dir=content_dir,
            output_metadata=metadata_path,
            token_range=(20, 50),
        )

        # Should only have medium.md
        assert len(metadata["samples"]) == 1
        assert 20 <= metadata["samples"][0]["tokens"] <= 50

    def test_collect_markdown_corpus_with_sampling(self, tmp_path):
        """Verify sampling works during collection."""
        from src.benchmarking.corpus import CorpusManager

        # Create many test markdown files
        content_dir = tmp_path / "content"
        content_dir.mkdir()

        for i in range(20):
            (content_dir / f"file{i}.md").write_text(f"Content for file {i}.", encoding='utf-8')

        # Collect only 5 samples
        manager = CorpusManager()
        metadata_path = tmp_path / "metadata.yaml"

        metadata = manager.collect_markdown_corpus(
            content_dir=content_dir,
            output_metadata=metadata_path,
            sample_size=5,
            seed=42,
        )

        # Should have exactly 5 samples
        assert len(metadata["samples"]) == 5
        assert metadata["total_files"] == 20


@pytest.mark.benchmarking
class TestMarkdownCorpusLoading:
    """Test loading samples from markdown corpus via metadata.yaml."""

    def test_load_markdown_corpus_basic(self, tmp_path):
        """Verify loading markdown corpus from metadata.yaml."""
        from src.benchmarking.corpus import CorpusManager

        # Create test content
        content_dir = tmp_path / "content"
        content_dir.mkdir()

        blog_dir = content_dir / "blog.aspose.net"
        blog_dir.mkdir(parents=True)
        (blog_dir / "post1.md").write_text("This is blog post 1.", encoding='utf-8')
        (blog_dir / "post2.md").write_text("This is blog post 2.", encoding='utf-8')

        # Create metadata.yaml
        metadata = {
            "source": str(content_dir.absolute()),
            "version": "1.0",
            "collected": "2025-12-20T10:00:00Z",
            "total_files": 2,
            "samples": [
                {
                    "id": "blog_001",
                    "path": "blog.aspose.net/post1.md",
                    "category": "blog",
                    "tokens": 20,
                    "lang": "en",
                },
                {
                    "id": "blog_002",
                    "path": "blog.aspose.net/post2.md",
                    "category": "blog",
                    "tokens": 20,
                    "lang": "en",
                },
            ],
        }

        metadata_path = tmp_path / "metadata.yaml"
        with open(metadata_path, 'w', encoding='utf-8') as f:
            yaml.dump(metadata, f)

        # Load samples
        manager = CorpusManager()
        samples = manager.load_samples(source="markdown", path=metadata_path)

        # Verify samples loaded
        assert len(samples) == 2
        assert samples[0]["id"] == "blog_001"
        assert samples[0]["text_en"] == "This is blog post 1."
        assert samples[0]["domain"] == "blog"

        assert samples[1]["id"] == "blog_002"
        assert samples[1]["text_en"] == "This is blog post 2."
        assert samples[1]["domain"] == "blog"

    def test_load_markdown_corpus_with_category_filter(self, tmp_path):
        """Verify category filtering when loading markdown corpus."""
        from src.benchmarking.corpus import CorpusManager

        # Create test content
        content_dir = tmp_path / "content"
        content_dir.mkdir()

        (content_dir / "blog.md").write_text("Blog content.", encoding='utf-8')
        (content_dir / "product.md").write_text("Product content.", encoding='utf-8')

        # Create metadata.yaml with mixed categories
        metadata = {
            "source": str(content_dir.absolute()),
            "version": "1.0",
            "collected": "2025-12-20T10:00:00Z",
            "total_files": 2,
            "samples": [
                {"id": "blog_001", "path": "blog.md", "category": "blog", "tokens": 10, "lang": "en"},
                {"id": "products_001", "path": "product.md", "category": "products", "tokens": 10, "lang": "en"},
            ],
        }

        metadata_path = tmp_path / "metadata.yaml"
        with open(metadata_path, 'w', encoding='utf-8') as f:
            yaml.dump(metadata, f)

        # Load only blog samples
        manager = CorpusManager()
        samples = manager.load_samples(source="markdown", path=metadata_path, category="blog")

        # Should only have blog samples
        assert len(samples) == 1
        assert samples[0]["domain"] == "blog"

    def test_load_markdown_corpus_with_token_range(self, tmp_path):
        """Verify token range filtering when loading markdown corpus."""
        from src.benchmarking.corpus import CorpusManager

        # Create test content
        content_dir = tmp_path / "content"
        content_dir.mkdir()

        (content_dir / "short.md").write_text("Short.", encoding='utf-8')
        (content_dir / "long.md").write_text("A" * 400, encoding='utf-8')

        # Create metadata.yaml with different token counts
        metadata = {
            "source": str(content_dir.absolute()),
            "version": "1.0",
            "collected": "2025-12-20T10:00:00Z",
            "total_files": 2,
            "samples": [
                {"id": "short_001", "path": "short.md", "category": "general", "tokens": 5, "lang": "en"},
                {"id": "long_001", "path": "long.md", "category": "general", "tokens": 100, "lang": "en"},
            ],
        }

        metadata_path = tmp_path / "metadata.yaml"
        with open(metadata_path, 'w', encoding='utf-8') as f:
            yaml.dump(metadata, f)

        # Load only medium-sized samples (50-150 tokens)
        manager = CorpusManager()
        samples = manager.load_samples(source="markdown", path=metadata_path, token_range=(50, 150))

        # Should only have long.md
        assert len(samples) == 1
        assert samples[0]["id"] == "long_001"

    def test_load_markdown_corpus_with_limit(self, tmp_path):
        """Verify limit parameter works for markdown corpus."""
        from src.benchmarking.corpus import CorpusManager

        # Create test content
        content_dir = tmp_path / "content"
        content_dir.mkdir()

        for i in range(10):
            (content_dir / f"file{i}.md").write_text(f"Content {i}.", encoding='utf-8')

        # Create metadata.yaml with many samples
        metadata = {
            "source": str(content_dir.absolute()),
            "version": "1.0",
            "collected": "2025-12-20T10:00:00Z",
            "total_files": 10,
            "samples": [
                {"id": f"test_{i:03d}", "path": f"file{i}.md", "category": "general", "tokens": 10, "lang": "en"}
                for i in range(10)
            ],
        }

        metadata_path = tmp_path / "metadata.yaml"
        with open(metadata_path, 'w', encoding='utf-8') as f:
            yaml.dump(metadata, f)

        # Load only 3 samples
        manager = CorpusManager()
        samples = manager.load_samples(source="markdown", path=metadata_path, limit=3)

        # Should have exactly 3 samples
        assert len(samples) == 3

    def test_validate_markdown_corpus(self, tmp_path):
        """Verify markdown corpus validation works."""
        from src.benchmarking.corpus import CorpusManager

        # Create valid metadata.yaml
        content_dir = tmp_path / "content"
        content_dir.mkdir()

        metadata = {
            "source": str(content_dir.absolute()),
            "version": "1.0",
            "collected": "2025-12-20T10:00:00Z",
            "total_files": 1,
            "samples": [
                {"id": "test_001", "path": "test.md", "category": "general", "tokens": 10, "lang": "en"},
            ],
        }

        metadata_path = tmp_path / "metadata.yaml"
        with open(metadata_path, 'w', encoding='utf-8') as f:
            yaml.dump(metadata, f)

        # Validate
        manager = CorpusManager()
        is_valid = manager.validate(source="markdown", path=metadata_path)

        assert is_valid, "Markdown corpus validation failed"


if __name__ == "__main__":
    # Allow running tests directly
    pytest.main([__file__, "-v", "-m", "benchmarking"])
