"""
Performance Baseline Tests

Verifies that performance meets minimum requirements.
"""

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.tm import L1Cache
from src.translation_engine.extractor import SegmentExtractor
from src.translation_engine.parser import HugoParser
from src.translation_engine.reconstructor import MarkdownReconstructor
from src.utils.models import BodyRules, FrontmatterMode, FrontmatterRule, SiteProfile


@pytest.fixture
def site_profile():
    """Create test site profile."""
    return SiteProfile(
        site_id="perf_test",
        content_roots=["content"],
        default_source_lang="en",
        target_langs=["es"],
        frontmatter={"title": FrontmatterRule(mode=FrontmatterMode.TRANSLATE)},
        body=BodyRules(translate_markdown=True),
    )


@pytest.fixture
def parser():
    return HugoParser()


class TestTMPerformance:
    """Test TM lookup performance."""

    def test_l1_cache_performance(self, tmpdir):
        """Test L1 cache meets performance targets."""
        l1 = L1Cache(max_size=1000)

        # Populate
        for i in range(1000):
            l1.put("site", "en", "es", f"text {i}", f"texto {i}")

        # Benchmark
        start = time.perf_counter()
        for i in range(1000):
            result = l1.get("site", "en", "es", f"text {i}")
        elapsed = time.perf_counter() - start

        # Should do 1000 lookups in under 100ms (>10k lookups/sec)
        assert elapsed < 0.1, f"L1 cache too slow: {1000 / elapsed:.0f} lookups/sec"

    def test_parser_performance(self, parser):
        """Test parser meets performance targets."""
        content = "---\ntitle: Test\n---\n\n# Heading\n\nContent."

        # Benchmark
        start = time.perf_counter()
        for _ in range(100):
            doc = parser.parse_string(content)
        elapsed = time.perf_counter() - start

        # Should parse 100 docs in under 500ms (5ms per parse)
        assert elapsed < 0.5, f"Parser too slow: {elapsed * 10:.1f}ms per parse"


class TestPipelinePerformance:
    """Test full pipeline performance."""

    def test_full_pipeline_performance(self, parser, site_profile):
        """Test full pipeline meets performance targets."""
        content = """---
title: Test Document
---

# Main Heading

This is a test paragraph with multiple sentences.

## Subheading

More content here.
"""

        extractor = SegmentExtractor(site_profile)
        reconstructor = MarkdownReconstructor(site_profile)

        # Benchmark full pipeline
        times = []
        for _ in range(10):
            start = time.perf_counter()

            doc = parser.parse_string(content)
            segments = extractor.extract_all(doc)
            translations = {seg.id: f"[ES] {seg.source_text}" for seg in segments}
            translated = reconstructor.reconstruct_document(doc, translations, "es")

            times.append((time.perf_counter() - start) * 1000)

        avg_time = sum(times) / len(times)

        # Should complete pipeline in under 20ms
        assert avg_time < 20, f"Pipeline too slow: {avg_time:.2f}ms average"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
