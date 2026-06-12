"""
Build L3 Semantic Index from L2 LMDB Database

Reads all entries from L2 (LMDB) and creates embeddings in L3 (FAISS).
This script should be run:
- After migration to populate L3 for the first time
- Periodically to ensure L3 is in sync with L2
- After any manual L2 modifications
"""

import argparse
import json
import sys
from pathlib import Path

import lmdb
import structlog

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.tm.l3_semantic import L3SemanticTM

# Setup logging
logger = structlog.get_logger()


class L3IndexBuilder:
    """Builds L3 semantic index from L2 database."""

    def __init__(
        self,
        l2_path: str,
        l3_path: str,
        embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        use_gpu: bool = False,
        batch_size: int = 1000,
    ):
        """
        Initialize builder.

        Args:
            l2_path: Path to L2 LMDB database
            l3_path: Path to L3 FAISS index directory
            embedding_model: Model to use for embeddings
            use_gpu: Whether to use GPU for embeddings
            batch_size: Number of entries to process before saving
        """
        self.l2_path = Path(l2_path)
        self.l3_path = Path(l3_path)
        self.embedding_model = embedding_model
        self.use_gpu = use_gpu
        self.batch_size = batch_size

        # Stats
        self.total_entries = 0
        self.processed_entries = 0
        self.skipped_entries = 0
        self.skipped_already_processed = 0
        self.error_entries = 0

    def build_index(self, force: bool = False, resume: bool = False) -> None:
        """
        Build L3 index from L2 database.

        Args:
            force: If True, rebuild even if L3 index exists
            resume: If True, resume from existing L3 index (skip already processed entries)
        """
        logger.info("=" * 60)
        logger.info("L3 Semantic Index Builder")
        logger.info("=" * 60)
        logger.info(f"L2 database: {self.l2_path}")
        logger.info(f"L3 index: {self.l3_path}")
        logger.info(f"Embedding model: {self.embedding_model}")
        logger.info(f"Use GPU: {self.use_gpu}")
        logger.info(f"Mode: {'RESUME' if resume else 'REBUILD' if force else 'NEW BUILD'}")
        logger.info("")

        # Check if L2 exists
        if not self.l2_path.exists():
            logger.error(f"L2 database not found: {self.l2_path}")
            return

        # Check if L3 exists
        l3_index_file = self.l3_path / "index.faiss"
        existing_entry_ids = set()

        if l3_index_file.exists():
            if resume:
                # Load existing L3 and build set of processed entry IDs
                logger.info("Loading existing L3 index for resume...")
                try:
                    l3_temp = L3SemanticTM(
                        index_path=str(self.l3_path),
                        embedding_model=self.embedding_model,
                        use_gpu=False,  # Use CPU for loading
                    )
                except Exception as e:
                    logger.error(f"Failed to load existing L3 index: {e}")
                    logger.error("The index may be corrupted or incompatible.")
                    logger.error("Options:")
                    logger.error("  1. Use --force to rebuild from scratch")
                    logger.error("  2. Delete the L3 index manually and retry")
                    logger.error("  3. Use scripts/sync_l3_index.py as fallback")
                    return

                # Validate metadata structure
                if not isinstance(l3_temp.metadata, list):
                    logger.error(f"Unexpected metadata type: {type(l3_temp.metadata)}")
                    logger.error("Expected list of dictionaries")
                    logger.error("Cannot resume with invalid metadata structure")
                    return

                # Build entry ID set with validation
                logger.info("Extracting entry IDs from metadata...")
                invalid_entries = 0
                for meta in l3_temp.metadata:
                    # Validate metadata entry is a dict
                    if not isinstance(meta, dict):
                        invalid_entries += 1
                        continue

                    # Extract entry_id with fallback
                    entry_id = meta.get("entry_id")
                    if entry_id and isinstance(entry_id, str):
                        existing_entry_ids.add(entry_id)
                    else:
                        invalid_entries += 1

                # Report results
                logger.info(f"Found {len(existing_entry_ids):,} valid entries in L3")
                if invalid_entries > 0:
                    logger.warning(f"Skipped {invalid_entries:,} invalid metadata entries")
                    logger.warning("These entries may be missing entry_id field")

                if len(existing_entry_ids) == 0:
                    logger.warning("No valid entry IDs found in existing index")
                    logger.warning("Resume will process all entries (same as rebuild)")

                # Memory warning for large datasets
                entry_id_memory_mb = (
                    len(existing_entry_ids) * 150 / 1_000_000
                )  # ~150 bytes per entry_id
                if entry_id_memory_mb > 500:
                    logger.warning(f"Entry ID set uses ~{entry_id_memory_mb:.0f}MB of memory")
                    logger.warning("Consider using sync script for very large datasets")

                logger.info("Will skip these and only add new entries")
                logger.info("")
            elif not force:
                logger.warning(f"L3 index already exists: {l3_index_file}")
                logger.warning("Use --force to rebuild or --resume to continue")
                return

        # Initialize L3
        logger.info("Initializing L3 semantic TM...")
        l3 = L3SemanticTM(
            index_path=str(self.l3_path),
            embedding_model=self.embedding_model,
            use_gpu=self.use_gpu,
        )

        # Open L2
        logger.info("Opening L2 database...")
        env = lmdb.open(
            str(self.l2_path),
            readonly=True,
            max_dbs=1,
            lock=False,
        )

        # Get total count
        with env.begin() as txn:
            stat = txn.stat()
            self.total_entries = stat["entries"]
            logger.info(f"Total entries in L2: {self.total_entries:,}")

        # Process all entries
        logger.info("")
        logger.info("Processing entries...")
        logger.info("-" * 60)

        batch_count = 0
        with env.begin() as txn:
            cursor = txn.cursor()
            for key_bytes, value_bytes in cursor:
                try:
                    # Parse key: site_id:src_lang:tgt_lang:hash
                    key = key_bytes.decode("utf-8")
                    key_parts = key.split(":", 3)
                    if len(key_parts) != 4:
                        logger.warning(f"Invalid key format: {key}")
                        self.skipped_entries += 1
                        continue

                    site_id, src_lang, tgt_lang, entry_hash = key_parts
                    entry_id = f"{site_id}:{src_lang}:{tgt_lang}:{entry_hash}"

                    # Skip if already processed (resume mode)
                    if entry_id in existing_entry_ids:
                        self.skipped_already_processed += 1
                        continue

                    # Parse value
                    value = json.loads(value_bytes.decode("utf-8"))
                    source_text = value.get("source_text", "")
                    translation = value.get("translation", "")
                    context = value.get("context", "")

                    # Skip empty entries
                    if not source_text or not translation:
                        self.skipped_entries += 1
                        continue

                    # Add to L3
                    l3.add_entry(
                        entry_id=entry_id,
                        site_id=site_id,
                        src_lang=src_lang,
                        tgt_lang=tgt_lang,
                        source_text=source_text,
                        translation=translation,
                        context=context,
                    )

                    self.processed_entries += 1
                    batch_count += 1

                    # Progress update
                    if self.processed_entries % 1000 == 0:
                        progress = (self.processed_entries / self.total_entries) * 100
                        logger.info(
                            f"Progress: {self.processed_entries:,} / {self.total_entries:,} "
                            f"({progress:.1f}%) - Last: {site_id}:{src_lang}→{tgt_lang}"
                        )

                    # Save periodically
                    if batch_count >= self.batch_size:
                        logger.info(f"Saving index (batch at {self.processed_entries:,})...")
                        l3.save_index()
                        batch_count = 0

                except Exception as e:
                    logger.error(f"Error processing entry: {e}")
                    self.error_entries += 1
                    continue

        # Final save
        logger.info("")
        logger.info("Saving final index...")
        l3.save_index()

        # Close L2
        env.close()

        # Report
        logger.info("")
        logger.info("=" * 60)
        logger.info("Build Complete")
        logger.info("=" * 60)
        logger.info(f"Total entries in L2: {self.total_entries:,}")
        logger.info(f"Entries added to L3: {self.processed_entries:,}")
        if self.skipped_already_processed > 0:
            logger.info(f"Entries already in L3 (skipped): {self.skipped_already_processed:,}")
        logger.info(f"Empty entries skipped: {self.skipped_entries:,}")
        logger.info(f"Entries with errors: {self.error_entries:,}")
        logger.info(f"L3 index saved to: {self.l3_path}")
        logger.info("")

        # Verify
        logger.info("Verifying index...")
        l3_verify = L3SemanticTM(
            index_path=str(self.l3_path),
            embedding_model=self.embedding_model,
            use_gpu=False,  # Use CPU for verification
        )
        index_size = l3_verify.index.ntotal if l3_verify.index else 0
        logger.info("✓ Index loaded successfully")
        logger.info(f"✓ Vectors in index: {index_size:,}")
        logger.info(f"✓ Metadata entries: {len(l3_verify.metadata):,}")

        if index_size != self.processed_entries:
            logger.warning(
                f"⚠ Index size ({index_size:,}) != processed entries ({self.processed_entries:,})"
            )
        else:
            logger.info("✓ Index verification successful")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Build L3 semantic index from L2 database")
    parser.add_argument(
        "--l2_path",
        type=str,
        default="./data/tm/l2.lmdb",
        help="Path to L2 LMDB database",
    )
    parser.add_argument(
        "--l3_path",
        type=str,
        default="./data/tm/l3_faiss",
        help="Path to L3 FAISS index directory",
    )
    parser.add_argument(
        "--embedding_model",
        type=str,
        default="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        help="Sentence transformer model for embeddings",
    )
    parser.add_argument(
        "--use_gpu",
        action="store_true",
        help="Use GPU for embedding generation (faster)",
    )
    parser.add_argument(
        "--batch_size",
        type=int,
        default=1000,
        help="Save index every N entries",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force rebuild even if L3 index exists",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from existing L3 index (skip already processed entries)",
    )

    args = parser.parse_args()

    # Validate argument conflicts
    if args.force and args.resume:
        logger.error("Cannot specify both --force and --resume")
        logger.error("  --force: Rebuild from scratch (deletes existing index)")
        logger.error("  --resume: Continue from existing index")
        logger.error("Choose one or the other.")
        sys.exit(1)

    # Build index
    builder = L3IndexBuilder(
        l2_path=args.l2_path,
        l3_path=args.l3_path,
        embedding_model=args.embedding_model,
        use_gpu=args.use_gpu,
        batch_size=args.batch_size,
    )

    builder.build_index(force=args.force, resume=args.resume)


if __name__ == "__main__":
    main()
