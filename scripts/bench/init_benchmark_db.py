#!/usr/bin/env python3
"""Initialize benchmark database.

This script creates a new benchmark database with the correct schema.
It's idempotent - running it multiple times is safe.

Usage:
    python scripts/init_benchmark_db.py --db data/benchmarks.db
    python scripts/init_benchmark_db.py --db data/benchmarks.db --verify
"""

import argparse
import logging
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.benchmarking.storage import BenchmarkDatabase

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> int:
    """Initialize benchmark database."""
    parser = argparse.ArgumentParser(
        description="Initialize benchmark database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create new database
  python scripts/init_benchmark_db.py --db data/benchmarks.db

  # Create and verify
  python scripts/init_benchmark_db.py --db data/benchmarks.db --verify

  # Use custom location
  python scripts/init_benchmark_db.py --db /path/to/custom.db
        """,
    )

    parser.add_argument(
        "--db",
        type=Path,
        default=Path("data/benchmarks/benchmarks.db"),
        help="Path to database file (default: data/benchmarks/benchmarks.db)",
    )

    parser.add_argument(
        "--verify",
        action="store_true",
        help="Run integrity check after initialization",
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        logger.info(f"Initializing benchmark database at: {args.db}")

        # Create database (this will create schema if needed)
        db = BenchmarkDatabase(args.db)

        # Get schema version
        version = db.get_schema_version()
        logger.info(f"Database schema version: {version}")

        if args.verify:
            logger.info("Running integrity check...")
            if db.verify_integrity():
                logger.info("Integrity check PASSED")
            else:
                logger.error("Integrity check FAILED")
                return 1

        # Print summary
        runs = db.list_runs(limit=5)
        logger.info(f"Database contains {len(runs)} run(s)")

        logger.info("Database initialization completed successfully")
        logger.info(f"Database path: {args.db.absolute()}")

        # Check for WAL files
        wal_file = Path(str(args.db) + "-wal")
        shm_file = Path(str(args.db) + "-shm")
        if wal_file.exists():
            logger.info(f"WAL file: {wal_file}")
        if shm_file.exists():
            logger.info(f"Shared memory file: {shm_file}")

        return 0

    except Exception as e:
        logger.error(f"Failed to initialize database: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
