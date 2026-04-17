#!/usr/bin/env python
"""
Legacy Cache Migration Tool

Migrates translation cache from legacy JSON files to the new LMDB-based
Translation Memory system.

Usage:
    python scripts/migrate_legacy_cache.py --legacy_cache <path> [--output <tm_dir>] [--dry-run]

Arguments:
    --legacy_cache    Path to legacy translation cache directory (contains cache_*.json)
    --output         Output directory for new TM database (default: ./data/tm)
    --dry-run        Preview migration without writing to database
    --verbose        Enable verbose logging

Description:
    The legacy system stores translations in JSON files:
    - Format: cache_{language_code}.json
    - Structure: {"text": "translation", ...}

    The new system uses LMDB for L2 persistent storage with:
    - Multi-layer architecture (L1 in-memory, L2 persistent, L3 semantic)
    - Normalized keys
    - Metadata tracking (created_at, access_count, etc.)

    This script:
    1. Scans legacy cache directory for cache_*.json files
    2. Loads each JSON file
    3. Normalizes and validates entries
    4. Migrates to new TM with proper metadata
    5. Reports statistics and any errors

Example:
    # Dry run to preview migration
    python scripts/migrate_legacy_cache.py --legacy_cache ./translation --dry-run

    # Execute migration
    python scripts/migrate_legacy_cache.py --legacy_cache ./translation --output ./data/tm
"""

import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from tm import TranslationMemory
from tm.normalization import normalize_text

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class LegacyCacheMigrator:
    """Migrates legacy JSON cache to new LMDB Translation Memory"""

    def __init__(self, legacy_cache_dir: str, output_dir: str, dry_run: bool = False):
        self.legacy_cache_dir = Path(legacy_cache_dir)
        self.output_dir = Path(output_dir)
        self.dry_run = dry_run
        self.stats = defaultdict(int)
        self.errors = []

        if not self.legacy_cache_dir.exists():
            raise ValueError(f"Legacy cache directory not found: {legacy_cache_dir}")

        # Initialize TM only if not dry run
        self.tm = None
        if not dry_run:
            os.makedirs(self.output_dir, exist_ok=True)
            # Initialize TM layers
            from tm.l1_cache import L1Cache
            from tm.l2_persistent import L2PersistentTM

            l1 = L1Cache(max_size=10000)
            # Set max_size_mb to 10GB to accommodate full migration (6M+ entries)
            l2 = L2PersistentTM(db_path=str(self.output_dir / "l2.lmdb"), max_size_mb=10240)
            # L3 semantic search disabled during migration for speed
            self.tm = TranslationMemory(l1_cache=l1, l2_persistent=l2, l3_semantic=None)

    def find_legacy_cache_files(self) -> list[tuple[str, Path]]:
        """Find all legacy cache files and extract language codes"""
        cache_files = []

        # Try both naming patterns: cache_*.json and *_cache.json
        patterns = ["cache_*.json", "*_cache.json"]

        for pattern in patterns:
            for file_path in self.legacy_cache_dir.glob(pattern):
                # Extract language code from filename
                if file_path.stem.startswith("cache_"):
                    # Pattern: cache_de.json -> de
                    lang_code = file_path.stem.replace("cache_", "")
                else:
                    # Pattern: de_cache.json -> de
                    lang_code = file_path.stem.replace("_cache", "")

                # Avoid duplicates
                if not any(code == lang_code for code, _ in cache_files):
                    cache_files.append((lang_code, file_path))
                    logger.info(f"Found legacy cache for language: {lang_code} ({file_path.name})")

        return cache_files

    def load_legacy_cache(self, file_path: Path) -> dict[str, str]:
        """Load legacy JSON cache file"""
        try:
            with open(file_path, encoding='utf-8') as f:
                cache = json.load(f)

            if not isinstance(cache, dict):
                raise ValueError(f"Invalid cache format: expected dict, got {type(cache)}")

            return cache
        except Exception as e:
            logger.error(f"Failed to load cache file {file_path}: {e}")
            self.errors.append(f"Load error ({file_path.name}): {e}")
            return {}

    def migrate_language_cache(
        self,
        lang_code: str,
        cache_data: dict[str, str],
        subdomain: str = "default"
    ) -> int:
        """Migrate cache entries for a single language"""
        migrated_count = 0
        skipped_count = 0
        error_count = 0

        logger.info(f"Migrating {len(cache_data)} entries for language: {lang_code}")

        for source_text, translation in cache_data.items():
            try:
                # Validate entry
                if not source_text or not translation:
                    skipped_count += 1
                    continue

                if not isinstance(source_text, str) or not isinstance(translation, str):
                    skipped_count += 1
                    continue

                # Normalize text (same as new system does)
                normalized_source = normalize_text(source_text)
                normalized_translation = normalize_text(translation)

                if not normalized_source or not normalized_translation:
                    skipped_count += 1
                    continue

                # Migrate to new TM
                if not self.dry_run:
                    # Store in TM (assumes English source by default)
                    self.tm.store(
                        site_id=subdomain,
                        src_lang="en",
                        tgt_lang=lang_code,
                        text=source_text,
                        translation=translation,
                        # Legacy cache doesn't have metadata, use defaults
                        context=""
                    )

                migrated_count += 1

            except Exception as e:
                error_count += 1
                self.errors.append(f"Migration error ({lang_code}): {source_text[:50]}... -> {e}")
                if error_count <= 5:  # Log first 5 errors
                    logger.warning(f"Failed to migrate entry: {e}")

        self.stats[f'{lang_code}_migrated'] = migrated_count
        self.stats[f'{lang_code}_skipped'] = skipped_count
        self.stats[f'{lang_code}_errors'] = error_count

        return migrated_count

    def migrate_all(self, subdomain: str = "default") -> dict:
        """Migrate all legacy cache files"""
        logger.info("=" * 60)
        logger.info("Starting Legacy Cache Migration")
        logger.info("=" * 60)
        logger.info(f"Legacy cache directory: {self.legacy_cache_dir}")
        logger.info(f"Output directory: {self.output_dir}")
        logger.info(f"Dry run: {self.dry_run}")
        logger.info("")

        # Find all cache files
        cache_files = self.find_legacy_cache_files()

        if not cache_files:
            logger.warning("No legacy cache files found!")
            return self.stats

        logger.info(f"Found {len(cache_files)} language cache files\n")

        # Migrate each language
        total_migrated = 0
        for lang_code, file_path in cache_files:
            logger.info(f"Processing {lang_code}...")

            # Load legacy cache
            cache_data = self.load_legacy_cache(file_path)

            if not cache_data:
                logger.warning(f"No valid data in {file_path.name}, skipping")
                continue

            # Migrate
            migrated = self.migrate_language_cache(lang_code, cache_data, subdomain)
            total_migrated += migrated

            logger.info(f"  ✓ Migrated {migrated} entries for {lang_code}")
            logger.info(f"  ⊘ Skipped {self.stats[f'{lang_code}_skipped']} invalid entries")
            if self.stats[f'{lang_code}_errors'] > 0:
                logger.warning(f"  ✗ {self.stats[f'{lang_code}_errors']} errors")
            logger.info("")

        self.stats['total_migrated'] = total_migrated
        self.stats['languages_processed'] = len(cache_files)

        # Print summary
        self.print_summary()

        return self.stats

    def print_summary(self):
        """Print migration summary"""
        logger.info("=" * 60)
        logger.info("Migration Summary")
        logger.info("=" * 60)
        logger.info(f"Languages processed: {self.stats['languages_processed']}")
        logger.info(f"Total entries migrated: {self.stats['total_migrated']}")

        total_skipped = sum(v for k, v in self.stats.items() if k.endswith('_skipped'))
        total_errors = sum(v for k, v in self.stats.items() if k.endswith('_errors'))

        logger.info(f"Total skipped: {total_skipped}")
        logger.info(f"Total errors: {total_errors}")

        if self.dry_run:
            logger.info("\n⚠️  DRY RUN - No changes were made")
        else:
            logger.info("\n✅ Migration complete!")

        if self.errors and len(self.errors) <= 10:
            logger.info("\nErrors encountered:")
            for error in self.errors[:10]:
                logger.info(f"  - {error}")
        elif len(self.errors) > 10:
            logger.info(f"\n⚠️  {len(self.errors)} errors encountered (showing first 10)")
            for error in self.errors[:10]:
                logger.info(f"  - {error}")

        logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Migrate legacy JSON cache to new LMDB Translation Memory",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        '--legacy_cache',
        required=True,
        help='Path to legacy translation cache directory'
    )

    parser.add_argument(
        '--output',
        default='./data/tm',
        help='Output directory for new TM database (default: ./data/tm)'
    )

    parser.add_argument(
        '--subdomain',
        default='default',
        help='Subdomain for migrated entries (default: default)'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview migration without writing to database'
    )

    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )

    parser.add_argument(
        '--populate-l3',
        action='store_true',
        help='Populate L3 semantic index after migration'
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        # Execute migration
        migrator = LegacyCacheMigrator(
            legacy_cache_dir=args.legacy_cache,
            output_dir=args.output,
            dry_run=args.dry_run
        )

        stats = migrator.migrate_all(subdomain=args.subdomain)

        # Populate L3 index if requested
        if args.populate_l3 and not args.dry_run:
            logger.info("")
            logger.info("=" * 60)
            logger.info("Populating L3 Semantic Index")
            logger.info("=" * 60)

            try:
                import subprocess
                result = subprocess.run(
                    [
                        sys.executable,
                        str(Path(__file__).parent / "populate_l3_index.py"),
                        "--tm-path", args.output,
                        "--batch-size", "1000"
                    ],
                    capture_output=True,
                    text=True
                )

                if result.returncode == 0:
                    logger.info("✅ L3 index populated successfully")
                else:
                    logger.error(f"L3 population failed: {result.stderr}")

            except Exception as e:
                logger.error(f"Failed to populate L3 index: {e}")
                logger.info("You can manually populate later with:")
                logger.info(f"  python scripts/populate_l3_index.py --tm-path {args.output}")

        # Exit with success
        sys.exit(0)

    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
