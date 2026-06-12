#!/usr/bin/env python3
"""
Benchmark Corpus Collection Script

Scans a directory of markdown files and builds metadata.yaml for benchmarking.

This script is designed to work with the aspose.net content directory structure,
scanning thousands of .md files and creating a metadata index for benchmark corpus.

Usage:
    python scripts/collect_benchmark_corpus.py \
        --content-dir "D:\\onedrive\\Documents\\GitHub\\aspose.net\\content" \
        --output data/benchmark_corpus/metadata.yaml \
        --sample-size 200 \
        --categories blog,products,kb \
        --token-range 50-500

Features:
    - Scans directory tree for .md files
    - Estimates token counts using heuristic (4 chars/token)
    - Infers category from directory structure
    - Supports filtering by category and token range
    - Generates reproducible sample set (random seed)
    - Creates YAML metadata file for CorpusManager

Pattern matching (follows scripts/analyze_ast_corpus.py):
    - Directory scanning: Path.rglob("*.md")
    - Token estimation: estimate_token_count() heuristic
    - Category inference: from path structure
    - Metadata format: YAML with samples list
"""

import argparse
import logging
import sys
from pathlib import Path

# Import from project
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.benchmarking.corpus import CorpusManager

logger = logging.getLogger(__name__)


def parse_token_range(token_range_str: str) -> tuple[int, int]:
    """
    Parse token range string like "50-500" into (min, max) tuple.

    Args:
        token_range_str: Token range string (e.g., "50-500")

    Returns:
        Tuple of (min_tokens, max_tokens)

    Raises:
        ValueError: If format is invalid
    """
    if not token_range_str:
        return (0, 1000000)

    parts = token_range_str.split("-")
    if len(parts) != 2:
        raise ValueError(
            f"Invalid token range format: {token_range_str}. Expected format: '50-500'"
        )

    try:
        min_tokens = int(parts[0].strip())
        max_tokens = int(parts[1].strip())
    except ValueError:
        raise ValueError(f"Invalid token range values: {token_range_str}")

    if min_tokens < 0 or max_tokens < min_tokens:
        raise ValueError(
            f"Invalid token range: {token_range_str}. Min must be >= 0 and max must be >= min"
        )

    return (min_tokens, max_tokens)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Collect benchmark corpus from markdown directory",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Collect from aspose.net content directory
  python scripts/collect_benchmark_corpus.py \\
    --content-dir "D:\\onedrive\\Documents\\GitHub\\aspose.net\\content" \\
    --output data/benchmark_corpus/metadata.yaml \\
    --sample-size 200

  # Collect with category and token filters
  python scripts/collect_benchmark_corpus.py \\
    --content-dir "D:\\onedrive\\Documents\\GitHub\\aspose.net\\content" \\
    --output data/benchmark_corpus/metadata.yaml \\
    --sample-size 500 \\
    --categories blog,products,kb \\
    --token-range 50-500

  # Collect all files (no sampling)
  python scripts/collect_benchmark_corpus.py \\
    --content-dir "D:\\onedrive\\Documents\\GitHub\\aspose.net\\content" \\
    --output data/benchmark_corpus/metadata.yaml
        """,
    )

    parser.add_argument(
        "--content-dir",
        required=True,
        type=Path,
        help="Root directory containing .md files (e.g., aspose.net/content)",
    )

    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Output path for metadata.yaml",
    )

    parser.add_argument(
        "--sample-size",
        type=int,
        help="Number of samples to collect (default: all files)",
    )

    parser.add_argument(
        "--categories",
        help="Comma-separated list of categories to include (e.g., blog,products,kb)",
    )

    parser.add_argument(
        "--token-range",
        help="Token count range filter (e.g., 50-500)",
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible sampling (default: 42)",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be collected without writing metadata",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    # Validate content directory
    if not args.content_dir.exists():
        logger.error(f"Content directory not found: {args.content_dir}")
        return 1

    if not args.content_dir.is_dir():
        logger.error(f"Content path is not a directory: {args.content_dir}")
        return 1

    # Parse categories
    categories = None
    if args.categories:
        categories = [cat.strip() for cat in args.categories.split(",")]
        logger.info(f"Filtering by categories: {categories}")

    # Parse token range
    token_range = None
    if args.token_range:
        try:
            token_range = parse_token_range(args.token_range)
            logger.info(f"Filtering by token range: {token_range[0]}-{token_range[1]}")
        except ValueError as e:
            logger.error(f"Invalid token range: {e}")
            return 1

    # Initialize corpus manager
    manager = CorpusManager()

    logger.info("=" * 60)
    logger.info("Benchmark Corpus Collection")
    logger.info("=" * 60)
    logger.info(f"Content Directory: {args.content_dir}")
    logger.info(f"Output: {args.output}")
    logger.info(f"Sample Size: {args.sample_size or 'all'}")
    logger.info(f"Categories: {categories or 'all'}")
    logger.info(f"Token Range: {token_range or 'all'}")
    logger.info(f"Seed: {args.seed}")
    logger.info(f"Dry Run: {args.dry_run}")
    logger.info("")

    # Collect corpus
    try:
        logger.info("Scanning markdown files...")
        metadata = manager.collect_markdown_corpus(
            content_dir=args.content_dir,
            output_metadata=args.output,
            sample_size=args.sample_size,
            categories=categories,
            token_range=token_range,
            seed=args.seed,
        )

        # Show summary
        logger.info("")
        logger.info("=" * 60)
        logger.info("COLLECTION COMPLETE")
        logger.info("=" * 60)
        logger.info(f"Total files found: {metadata['total_files']}")
        logger.info(f"Samples collected: {len(metadata['samples'])}")
        logger.info(f"Source: {metadata['source']}")
        logger.info(f"Version: {metadata['version']}")
        logger.info(f"Collected: {metadata['collected']}")

        # Category distribution
        category_counts = {}
        for sample in metadata["samples"]:
            cat = sample.get("category", "unknown")
            category_counts[cat] = category_counts.get(cat, 0) + 1

        logger.info("")
        logger.info("Category Distribution:")
        for cat, count in sorted(category_counts.items()):
            logger.info(f"  {cat}: {count} samples")

        # Token stats
        token_counts = [s.get("tokens", 0) for s in metadata["samples"]]
        if token_counts:
            logger.info("")
            logger.info("Token Statistics:")
            logger.info(f"  Min: {min(token_counts)}")
            logger.info(f"  Max: {max(token_counts)}")
            logger.info(f"  Avg: {sum(token_counts) / len(token_counts):.1f}")
            logger.info(f"  Total: {sum(token_counts):,}")

        # Sample examples
        logger.info("")
        logger.info("Sample Examples (first 5):")
        for sample in metadata["samples"][:5]:
            logger.info(
                f"  {sample['id']}: {sample['category']} ({sample['tokens']} tokens) - {sample['path']}"
            )

        if not args.dry_run:
            logger.info("")
            logger.info(f"Metadata written to: {args.output}")
            logger.info("")
            logger.info("Next steps:")
            logger.info("  1. Validate metadata:")
            logger.info('     python -c "from src.benchmarking.corpus import CorpusManager; ')
            logger.info(
                f"     m = CorpusManager(); print('Valid:', m.validate('markdown', '{args.output}'))\""
            )
            logger.info("")
            logger.info("  2. Test loading samples:")
            logger.info('     python -c "from src.benchmarking.corpus import CorpusManager; ')
            logger.info(
                f"     m = CorpusManager(); s = m.load_samples('markdown', path='{args.output}', limit=10); "
            )
            logger.info("     print(f'Loaded {len(s)} samples')\"")
            logger.info("")
            logger.info("  3. Run benchmark with markdown corpus:")
            logger.info("     python -m src.benchmarking.runner --model m2m100_418m --device cpu ")
            logger.info(
                f"     --corpus-source markdown --corpus-path {args.output} --max-samples 10"
            )
        else:
            logger.info("")
            logger.info("DRY RUN - No files written")

        return 0

    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        return 1
    except ValueError as e:
        logger.error(f"Invalid configuration: {e}")
        return 1
    except Exception as e:
        logger.error(f"Collection failed: {e}", exc_info=args.verbose)
        return 1


if __name__ == "__main__":
    sys.exit(main())
