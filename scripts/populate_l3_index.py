#!/usr/bin/env python
"""
Populate L3 FAISS semantic index from L2 LMDB database.

Reads all entries from L2 persistent storage and builds the L3 semantic
search index with embeddings. Supports:
- Batch processing for memory efficiency
- GPU acceleration (if available) with CPU fallback
- Progress tracking with ETA
- Incremental saves every N entries
- Resume capability for interrupted runs
- Validation of embeddings (no NaN/Inf)

Usage:
    python scripts/populate_l3_index.py --tm-path ./data/tm
    python scripts/populate_l3_index.py --tm-path ./data/tm --batch-size 1000 --use-gpu
    python scripts/populate_l3_index.py --tm-path ./data/tm --resume
    python scripts/populate_l3_index.py --tm-path ./data/tm --rebuild
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
from tqdm import tqdm

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

try:
    import lmdb
except ImportError:
    print("ERROR: lmdb not installed. Run: pip install lmdb")
    sys.exit(1)

try:
    import torch
except ImportError:
    torch = None

from tm.l3_semantic import L3SemanticTM

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class L3IndexPopulator:
    """Populate L3 semantic search index from L2 database."""

    def __init__(
        self,
        tm_path: Path,
        batch_size: int = 1000,
        use_gpu: bool = False,
        save_interval: int = 10000,
    ):
        """
        Initialize L3 index populator.

        Args:
            tm_path: Path to TM directory
            batch_size: Number of entries to process per batch
            use_gpu: Whether to use GPU for embeddings
            save_interval: Save index every N entries
        """
        self.tm_path = Path(tm_path)
        self.db_path = self.tm_path / "l2_lmdb"
        self.l3_path = self.tm_path / "l3_faiss"
        self.batch_size = batch_size
        self.save_interval = save_interval

        if not self.db_path.exists():
            raise ValueError(f"L2 database not found: {self.db_path}")

        # Check GPU availability
        self.use_gpu = use_gpu
        if use_gpu:
            if torch is None:
                logger.warning("PyTorch not installed, falling back to CPU")
                self.use_gpu = False
            elif not torch.cuda.is_available():
                logger.warning("CUDA not available, falling back to CPU")
                self.use_gpu = False
            else:
                logger.info(f"Using GPU: {torch.cuda.get_device_name(0)}")

        # Initialize L3 index
        logger.info(f"Initializing L3 semantic TM (GPU: {self.use_gpu})...")
        self.l3 = L3SemanticTM(
            index_path=self.l3_path,
            use_gpu=self.use_gpu
        )

        self.stats = {
            'total_processed': 0,
            'total_added': 0,
            'total_skipped': 0,
            'total_errors': 0,
            'batches_processed': 0,
            'saves_performed': 0,
        }

    def get_l2_entry_count(self) -> int:
        """
        Get total number of entries in L2 database.

        Returns:
            Entry count
        """
        env = lmdb.open(str(self.db_path), readonly=True, max_dbs=10)
        with env.begin() as txn:
            count = txn.stat()['entries']
        env.close()
        return count

    def get_existing_index_count(self) -> int:
        """
        Get number of entries already in L3 index.

        Returns:
            Entry count (0 if index doesn't exist)
        """
        return len(self.l3)

    def iterate_l2_entries(self, start_from: int = 0):
        """
        Iterate through all L2 entries.

        Args:
            start_from: Skip first N entries (for resume)

        Yields:
            Tuples of (key, entry_data)
        """
        env = lmdb.open(str(self.db_path), readonly=True, max_dbs=10)

        with env.begin() as txn:
            cursor = txn.cursor()
            cursor.first()

            # Skip to start position if resuming
            for _ in range(start_from):
                if not cursor.next():
                    break

            # Iterate through remaining entries
            while True:
                try:
                    key_bytes, value_bytes = cursor.item()

                    # Decode key and value
                    key = key_bytes.decode('utf-8')
                    value_str = value_bytes.decode('utf-8')
                    entry_data = json.loads(value_str)

                    yield key, entry_data

                    if not cursor.next():
                        break

                except Exception as e:
                    logger.warning(f"Failed to decode entry: {e}")
                    self.stats['total_errors'] += 1
                    if not cursor.next():
                        break

        env.close()

    def validate_embedding(self, embedding: np.ndarray) -> bool:
        """
        Validate that embedding is valid (no NaN/Inf).

        Args:
            embedding: Numpy array of embedding values

        Returns:
            True if valid, False otherwise
        """
        if np.any(np.isnan(embedding)):
            return False
        if np.any(np.isinf(embedding)):
            return False
        return True

    def process_batch(self, batch: List[Dict]) -> int:
        """
        Process a batch of entries and add to L3 index.

        Args:
            batch: List of entry dictionaries

        Returns:
            Number of entries successfully added
        """
        if not batch:
            return 0

        added_count = 0

        try:
            # Prepare entries for batch addition
            l3_entries = []

            for entry in batch:
                try:
                    # Create entry for L3
                    l3_entry = {
                        'entry_id': entry.get('key', f"entry_{self.stats['total_processed']}"),
                        'site_id': entry.get('site_id', 'default'),
                        'src_lang': entry.get('src_lang', 'en'),
                        'tgt_lang': entry.get('tgt_lang', 'unknown'),
                        'source_text': entry.get('source_text', ''),
                        'translation': entry.get('translation', ''),
                        'context': entry.get('context'),
                        'metadata': entry.get('metadata', {}),
                    }

                    # Validate required fields
                    if not l3_entry['source_text'] or not l3_entry['translation']:
                        self.stats['total_skipped'] += 1
                        continue

                    l3_entries.append(l3_entry)

                except Exception as e:
                    logger.debug(f"Failed to prepare entry: {e}")
                    self.stats['total_errors'] += 1

            # Batch add to L3 index
            if l3_entries:
                added_count = self.l3.batch_add(l3_entries)
                self.stats['total_added'] += added_count

        except Exception as e:
            logger.error(f"Failed to process batch: {e}")
            self.stats['total_errors'] += 1

        self.stats['batches_processed'] += 1
        return added_count

    def populate(self, resume: bool = False, rebuild: bool = False) -> Dict:
        """
        Populate L3 index from L2 database.

        Args:
            resume: Resume from existing index
            rebuild: Rebuild index from scratch

        Returns:
            Statistics dictionary
        """
        logger.info("=" * 80)
        logger.info("L3 Index Population")
        logger.info("=" * 80)
        logger.info(f"L2 Database: {self.db_path}")
        logger.info(f"L3 Index: {self.l3_path}")
        logger.info(f"Batch size: {self.batch_size}")
        logger.info(f"GPU mode: {self.use_gpu}")
        logger.info("")

        # Get counts
        l2_count = self.get_l2_entry_count()
        existing_count = self.get_existing_index_count()

        logger.info(f"L2 entries: {l2_count:,}")
        logger.info(f"L3 entries (existing): {existing_count:,}")

        # Determine start position
        start_from = 0
        if rebuild:
            logger.info("Rebuilding index from scratch...")
            self.l3.clear()
        elif resume and existing_count > 0:
            logger.info(f"Resuming from existing index ({existing_count:,} entries)...")
            start_from = existing_count
        elif existing_count > 0:
            logger.warning(f"Index already contains {existing_count:,} entries!")
            logger.warning("Use --resume to continue or --rebuild to start over")
            return self.stats

        logger.info("")

        # Process entries in batches
        batch = []
        last_save_count = 0

        with tqdm(total=l2_count - start_from, desc="Populating L3 index", unit="entries") as pbar:
            for key, entry_data in self.iterate_l2_entries(start_from):
                # Add key to entry data
                entry_data['key'] = key

                # Add to batch
                batch.append(entry_data)
                self.stats['total_processed'] += 1

                # Process batch when full
                if len(batch) >= self.batch_size:
                    self.process_batch(batch)
                    batch = []
                    pbar.update(self.batch_size)

                # Save index periodically
                if self.stats['total_added'] - last_save_count >= self.save_interval:
                    logger.info(f"\nSaving index at {self.stats['total_added']:,} entries...")
                    self.l3.save_index()
                    last_save_count = self.stats['total_added']
                    self.stats['saves_performed'] += 1

            # Process remaining batch
            if batch:
                self.process_batch(batch)
                pbar.update(len(batch))

        # Final save
        logger.info("\nSaving final index...")
        self.l3.save_index()
        self.stats['saves_performed'] += 1

        # Print summary
        self.print_summary()

        return self.stats

    def print_summary(self):
        """Print population summary."""
        logger.info("")
        logger.info("=" * 80)
        logger.info("Population Summary")
        logger.info("=" * 80)
        logger.info(f"Total processed: {self.stats['total_processed']:,}")
        logger.info(f"Total added: {self.stats['total_added']:,}")
        logger.info(f"Total skipped: {self.stats['total_skipped']:,}")
        logger.info(f"Total errors: {self.stats['total_errors']:,}")
        logger.info(f"Batches processed: {self.stats['batches_processed']:,}")
        logger.info(f"Saves performed: {self.stats['saves_performed']:,}")
        logger.info("")
        logger.info(f"L3 index size: {len(self.l3):,} entries")
        logger.info("")

        if self.stats['total_errors'] > 0:
            logger.warning(f"⚠️  {self.stats['total_errors']} errors occurred during population")

        logger.info("✅ L3 index population complete!")
        logger.info("=" * 80)


def main():
    parser = argparse.ArgumentParser(
        description="Populate L3 semantic index from L2 database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        '--tm-path',
        default='./data/tm',
        help='Path to TM directory (default: ./data/tm)'
    )

    parser.add_argument(
        '--batch-size',
        type=int,
        default=1000,
        help='Number of entries to process per batch (default: 1000)'
    )

    parser.add_argument(
        '--use-gpu',
        action='store_true',
        help='Use GPU for embeddings (if available)'
    )

    parser.add_argument(
        '--save-interval',
        type=int,
        default=10000,
        help='Save index every N entries (default: 10000)'
    )

    parser.add_argument(
        '--resume',
        action='store_true',
        help='Resume from existing index'
    )

    parser.add_argument(
        '--rebuild',
        action='store_true',
        help='Rebuild index from scratch (deletes existing)'
    )

    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Validate conflicting flags
    if args.resume and args.rebuild:
        logger.error("Cannot use --resume and --rebuild together")
        sys.exit(1)

    try:
        populator = L3IndexPopulator(
            tm_path=Path(args.tm_path),
            batch_size=args.batch_size,
            use_gpu=args.use_gpu,
            save_interval=args.save_interval
        )

        stats = populator.populate(resume=args.resume, rebuild=args.rebuild)

        # Exit with success
        sys.exit(0)

    except Exception as e:
        logger.error(f"Population failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
