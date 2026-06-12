#!/usr/bin/env python3
"""
Discover and register translation models from HuggingFace Hub.

Usage:
    python scripts/discover_models.py --limit 10 --min-downloads 5000
    python scripts/discover_models.py --dry-run  # Preview without changes
"""

import argparse
import logging
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.model_runtime.discovery import ModelDiscovery

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Discover translation models from HuggingFace Hub",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Discover top 10 popular models
  python scripts/discover_models.py --limit 10

  # Discover with high download threshold
  python scripts/discover_models.py --limit 20 --min-downloads 10000

  # Preview without modifying registry
  python scripts/discover_models.py --dry-run

  # Discover models for specific languages
  python scripts/discover_models.py --languages en,de,fr --limit 15
        """,
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of models to discover (default: 10)",
    )

    parser.add_argument(
        "--min-downloads",
        type=int,
        default=1000,
        help="Minimum number of downloads required (default: 1000)",
    )

    parser.add_argument(
        "--languages",
        type=str,
        help="Comma-separated list of language codes to filter by (e.g., 'en,de,fr')",
    )

    parser.add_argument(
        "--sort",
        type=str,
        default="downloads",
        choices=["downloads", "likes", "trending"],
        help="Sort models by criterion (default: downloads)",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview models without modifying registry",
    )

    parser.add_argument(
        "--registry",
        type=str,
        default="config/model_registry.yaml",
        help="Path to model registry file (default: config/model_registry.yaml)",
    )

    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")

    return parser.parse_args()


def main() -> int:
    """Main entry point."""
    args = parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Parse languages
    languages = None
    if args.languages:
        languages = [lang.strip() for lang in args.languages.split(",")]
        logger.info(f"Filtering by languages: {languages}")

    # Create discovery client
    discovery = ModelDiscovery(registry_path=args.registry)

    try:
        # Discover and register
        count = discovery.discover_and_register(
            limit=args.limit,
            min_downloads=args.min_downloads,
            dry_run=args.dry_run,
            languages=languages,
        )

        logger.info(f"\n{'=' * 60}")
        if args.dry_run:
            logger.info(f"[DRY RUN] Would register {count} new models")
            logger.info("Run without --dry-run to update registry")
        else:
            logger.info(f"Successfully registered {count} new models!")
            logger.info(f"Registry updated: {args.registry}")
        logger.info(f"{'=' * 60}")

        return 0

    except Exception as e:
        logger.error(f"Model discovery failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
