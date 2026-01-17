"""
Corpus Manager - Load and manage benchmark corpus from JSON or Markdown files.

This module provides CorpusManager class that supports:
- Loading samples from JSON corpus (existing: tiny.json, small.json, medium.json)
- Loading samples from markdown files via metadata.yaml (new: real aspose.net content)
- Filtering by category, token range, and limit
- Validation of corpus integrity

Usage:
    # Load JSON corpus (existing)
    manager = CorpusManager()
    samples = manager.load_samples(source="json", size="tiny")

    # Load markdown corpus (new)
    samples = manager.load_samples(
        source="markdown",
        path="data/benchmark_corpus/metadata.yaml",
        category="blog",
        limit=50
    )
"""

import json
import logging
import random
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

logger = logging.getLogger(__name__)


def estimate_token_count(text: str) -> int:
    """
    Estimate token count for English text.

    Simple heuristic: ~4 characters per token on average.
    This matches the approach in src/translation_engine/engine.py

    Args:
        text: Text to estimate tokens for

    Returns:
        Estimated token count
    """
    return len(text) // 4


@dataclass
class CorpusSample:
    """A single corpus sample."""
    id: str
    text_en: str
    domain: str
    tokens: Optional[int] = None
    source_path: Optional[str] = None
    metadata: Dict = field(default_factory=dict)


@dataclass
class CorpusMetadata:
    """Metadata for markdown corpus."""
    source: str
    version: str
    collected: str
    total_files: int
    samples: List[Dict]


class CorpusManager:
    """
    Manage benchmark corpus from JSON or Markdown sources.

    Supports two corpus sources:
    1. JSON corpus: Synthetic/sanitized samples in data/benchmark_corpus/*.json
    2. Markdown corpus: Real content from aspose.net via metadata.yaml
    """

    def __init__(self, corpus_dir: Optional[Path | str] = None):
        """
        Initialize corpus manager.

        Args:
            corpus_dir: Directory containing corpus files (default: data/benchmark_corpus/)
        """
        if corpus_dir is None:
            corpus_dir = Path("data") / "benchmark_corpus"
        self.corpus_dir = Path(corpus_dir)
        logger.debug(f"Initialized CorpusManager with corpus_dir={self.corpus_dir}")

    def load_samples(
        self,
        source: str = "json",
        size: Optional[str] = None,
        path: Optional[str | Path] = None,
        category: Optional[str] = None,
        token_range: Optional[Tuple[int, int]] = None,
        limit: Optional[int] = None,
    ) -> List[Dict]:
        """
        Load corpus samples from JSON or markdown sources.

        Args:
            source: Corpus source ("json" or "markdown")
            size: For JSON source: corpus size ("tiny", "small", "medium")
            path: For markdown source: path to metadata.yaml
            category: Filter by category/domain (applies to both sources)
            token_range: Filter by token count range (min, max) - only for markdown
            limit: Maximum number of samples to return

        Returns:
            List of corpus samples as dicts with 'id', 'text_en', 'domain' keys

        Raises:
            ValueError: If invalid source or missing required parameters
            FileNotFoundError: If corpus file not found

        Examples:
            # Load JSON corpus
            samples = manager.load_samples(source="json", size="tiny")

            # Load markdown corpus
            samples = manager.load_samples(
                source="markdown",
                path="data/benchmark_corpus/metadata.yaml",
                category="blog",
                token_range=(50, 500),
                limit=100
            )
        """
        if source == "json":
            return self._load_json_corpus(size=size, category=category, limit=limit)
        elif source == "markdown":
            return self._load_markdown_corpus(
                path=path,
                category=category,
                token_range=token_range,
                limit=limit
            )
        else:
            raise ValueError(f"Invalid corpus source: {source}. Must be 'json' or 'markdown'")

    def _load_json_corpus(
        self,
        size: Optional[str] = None,
        category: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict]:
        """
        Load corpus from JSON files (existing behavior).

        Args:
            size: Corpus size ("tiny", "small", "medium")
            category: Filter by domain category
            limit: Maximum samples to return

        Returns:
            List of corpus samples
        """
        if not size:
            size = "tiny"

        corpus_path = self.corpus_dir / f"{size}.json"

        if not corpus_path.exists():
            raise FileNotFoundError(f"Corpus file not found: {corpus_path}")

        with open(corpus_path, 'r', encoding='utf-8') as f:
            corpus = json.load(f)

        if not corpus:
            raise ValueError(f"Corpus is empty: {corpus_path}")

        # Filter by category if specified
        if category:
            corpus = [sample for sample in corpus if sample.get('domain') == category]
            if not corpus:
                logger.warning(f"No samples found for category: {category}")

        # Apply limit
        if limit and len(corpus) > limit:
            corpus = corpus[:limit]

        logger.info(f"Loaded {len(corpus)} samples from JSON corpus: {corpus_path.name}")
        return corpus

    def _load_markdown_corpus(
        self,
        path: Optional[str | Path] = None,
        category: Optional[str] = None,
        token_range: Optional[Tuple[int, int]] = None,
        limit: Optional[int] = None,
    ) -> List[Dict]:
        """
        Load corpus from markdown files via metadata.yaml.

        Args:
            path: Path to metadata.yaml (required)
            category: Filter by category
            token_range: Filter by token count (min, max)
            limit: Maximum samples to return

        Returns:
            List of corpus samples compatible with JSON format
        """
        if not path:
            # Try default location
            path = self.corpus_dir / "metadata.yaml"

        metadata_path = Path(path)

        if not metadata_path.exists():
            raise FileNotFoundError(
                f"Markdown corpus metadata not found: {metadata_path}\n"
                f"Run scripts/collect_benchmark_corpus.py to generate it."
            )

        # Load metadata
        with open(metadata_path, 'r', encoding='utf-8') as f:
            metadata_dict = yaml.safe_load(f)

        samples_data = metadata_dict.get('samples', [])
        content_root = Path(metadata_dict.get('source', ''))

        logger.info(f"Loading markdown corpus from {metadata_path}")
        logger.info(f"  Content root: {content_root}")
        logger.info(f"  Total samples in metadata: {len(samples_data)}")

        # Filter samples
        filtered_samples = samples_data

        if category:
            filtered_samples = [s for s in filtered_samples if s.get('category') == category]
            logger.info(f"  Filtered by category '{category}': {len(filtered_samples)} samples")

        if token_range:
            min_tokens, max_tokens = token_range
            filtered_samples = [
                s for s in filtered_samples
                if min_tokens <= s.get('tokens', 0) <= max_tokens
            ]
            logger.info(f"  Filtered by token range [{min_tokens}, {max_tokens}]: {len(filtered_samples)} samples")

        if limit and len(filtered_samples) > limit:
            filtered_samples = filtered_samples[:limit]
            logger.info(f"  Limited to {limit} samples")

        # Load actual markdown content
        corpus = []
        for sample_meta in filtered_samples:
            sample_id = sample_meta.get('id')
            sample_path = sample_meta.get('path')

            if not sample_path:
                logger.warning(f"Sample {sample_id} missing path, skipping")
                continue

            # Construct full path
            full_path = content_root / sample_path

            if not full_path.exists():
                logger.warning(f"Sample {sample_id} file not found: {full_path}, skipping")
                continue

            # Read markdown content
            try:
                text_en = full_path.read_text(encoding='utf-8')

                # Create sample dict compatible with JSON corpus format
                sample = {
                    'id': sample_id,
                    'text_en': text_en,
                    'domain': sample_meta.get('category', 'general'),
                }
                corpus.append(sample)

            except Exception as e:
                logger.warning(f"Failed to read sample {sample_id} from {full_path}: {e}")
                continue

        logger.info(f"Loaded {len(corpus)} samples from markdown corpus")
        return corpus

    def collect_markdown_corpus(
        self,
        content_dir: str | Path,
        output_metadata: str | Path,
        sample_size: Optional[int] = None,
        categories: Optional[List[str]] = None,
        token_range: Optional[Tuple[int, int]] = None,
        seed: int = 42,
    ) -> Dict:
        """
        Scan markdown directory and build metadata.yaml.

        This is a convenience method that wraps the collection logic.
        The main collection script is in scripts/collect_benchmark_corpus.py

        Args:
            content_dir: Root directory containing .md files
            output_metadata: Path to write metadata.yaml
            sample_size: Number of samples to collect (default: all)
            categories: List of categories to include (based on directory structure)
            token_range: Token count range (min, max) for filtering
            seed: Random seed for reproducible sampling

        Returns:
            Metadata dictionary
        """
        content_dir = Path(content_dir)
        output_metadata = Path(output_metadata)

        if not content_dir.exists():
            raise FileNotFoundError(f"Content directory not found: {content_dir}")

        logger.info(f"Collecting markdown corpus from {content_dir}")

        # Scan for .md files
        md_files = list(content_dir.rglob("*.md"))
        logger.info(f"  Found {len(md_files)} markdown files")

        # Build sample metadata
        samples = []
        for md_file in md_files:
            try:
                # Read file to estimate tokens
                content = md_file.read_text(encoding='utf-8')
                tokens = estimate_token_count(content)

                # Infer category from path
                rel_path = md_file.relative_to(content_dir)
                category = self._infer_category_from_path(rel_path)

                # Apply filters
                if categories and category not in categories:
                    continue

                if token_range:
                    min_tokens, max_tokens = token_range
                    if not (min_tokens <= tokens <= max_tokens):
                        continue

                # Generate sample ID
                sample_id = self._generate_sample_id(rel_path, category)

                sample = {
                    'id': sample_id,
                    'path': str(rel_path.as_posix()),
                    'category': category,
                    'tokens': tokens,
                    'lang': 'en',
                }
                samples.append(sample)

            except Exception as e:
                logger.warning(f"Failed to process {md_file}: {e}")
                continue

        logger.info(f"  Collected {len(samples)} samples after filtering")

        # Sample if needed
        if sample_size and len(samples) > sample_size:
            random.seed(seed)
            samples = random.sample(samples, sample_size)
            samples.sort(key=lambda s: s['id'])
            logger.info(f"  Sampled {sample_size} samples (seed={seed})")

        # Create metadata
        metadata = {
            'source': str(content_dir.absolute()),
            'version': '1.0',
            'collected': datetime.utcnow().isoformat() + 'Z',
            'total_files': len(md_files),
            'samples': samples,
        }

        # Write metadata
        output_metadata.parent.mkdir(parents=True, exist_ok=True)
        with open(output_metadata, 'w', encoding='utf-8') as f:
            yaml.dump(metadata, f, default_flow_style=False, allow_unicode=True)

        logger.info(f"Metadata written to {output_metadata}")
        return metadata

    def _infer_category_from_path(self, rel_path: Path) -> str:
        """
        Infer category from file path.

        Examples:
            blog.aspose.net/2024/01/example.md -> "blog"
            products.aspose.net/cells/net/index.md -> "products"
            kb.aspose.net/troubleshooting/index.md -> "kb"
        """
        parts = rel_path.parts

        if len(parts) == 0:
            return "general"

        # First part is usually the site name
        site = parts[0].lower()

        if 'blog' in site:
            return 'blog'
        elif 'product' in site:
            return 'products'
        elif 'kb' in site or 'knowledge' in site:
            return 'kb'
        elif 'doc' in site:
            return 'documentation'
        elif 'api' in site or 'reference' in site:
            return 'api'
        else:
            return 'general'

    def _generate_sample_id(self, rel_path: Path, category: str) -> str:
        """
        Generate unique sample ID from path.

        Format: {category}_{hash[:8]}

        Args:
            rel_path: Relative path to markdown file
            category: Inferred category

        Returns:
            Sample ID like "blog_a1b2c3d4"
        """
        import hashlib

        # Use path hash for uniqueness
        path_str = str(rel_path.as_posix())
        path_hash = hashlib.md5(path_str.encode(), usedforsecurity=False).hexdigest()[:8]

        return f"{category}_{path_hash}"

    def validate(self, source: str = "json", path: Optional[str | Path] = None) -> bool:
        """
        Validate corpus integrity.

        Args:
            source: Corpus source ("json" or "markdown")
            path: For markdown: path to metadata.yaml

        Returns:
            True if valid, False otherwise

        Checks:
            - Files exist and are readable
            - All required fields present
            - IDs are unique
            - No empty text
            - Token counts reasonable (for markdown)
        """
        try:
            if source == "json":
                # Validate all JSON corpus files
                for size in ['tiny', 'small', 'medium']:
                    corpus = self._load_json_corpus(size=size)
                    if not self._validate_samples(corpus):
                        return False

            elif source == "markdown":
                if not path:
                    path = self.corpus_dir / "metadata.yaml"

                metadata_path = Path(path)

                if not metadata_path.exists():
                    logger.error(f"Metadata file not found: {metadata_path}")
                    return False

                # Load and validate metadata structure
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    metadata = yaml.safe_load(f)

                required_fields = ['source', 'version', 'collected', 'samples']
                for field in required_fields:
                    if field not in metadata:
                        logger.error(f"Metadata missing required field: {field}")
                        return False

                # Validate samples
                samples = metadata.get('samples', [])
                sample_ids = set()

                for sample in samples:
                    # Check required fields
                    if not all(k in sample for k in ['id', 'path', 'category', 'tokens']):
                        logger.error(f"Sample missing required fields: {sample}")
                        return False

                    # Check unique IDs
                    if sample['id'] in sample_ids:
                        logger.error(f"Duplicate sample ID: {sample['id']}")
                        return False
                    sample_ids.add(sample['id'])

                    # Check token count is reasonable
                    if sample['tokens'] < 0 or sample['tokens'] > 1000000:
                        logger.error(f"Invalid token count for {sample['id']}: {sample['tokens']}")
                        return False

            else:
                logger.error(f"Invalid source: {source}")
                return False

            logger.info(f"Corpus validation passed for source={source}")
            return True

        except Exception as e:
            logger.error(f"Corpus validation failed: {e}")
            return False

    def _validate_samples(self, samples: List[Dict]) -> bool:
        """Validate sample list structure."""
        if not samples:
            logger.error("Samples list is empty")
            return False

        sample_ids = set()

        for sample in samples:
            # Check required fields
            if not all(k in sample for k in ['id', 'text_en', 'domain']):
                logger.error(f"Sample missing required fields: {sample.get('id', 'unknown')}")
                return False

            # Check unique IDs
            if sample['id'] in sample_ids:
                logger.error(f"Duplicate sample ID: {sample['id']}")
                return False
            sample_ids.add(sample['id'])

            # Check not empty
            if not sample['text_en'].strip():
                logger.error(f"Sample has empty text: {sample['id']}")
                return False

        return True
