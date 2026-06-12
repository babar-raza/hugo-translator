"""
Sync L3 Index with L2 Database

Verifies L3 is in sync with L2 and adds any missing entries.
Run this periodically to ensure consistency.
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


class L3Synchronizer:
    """Synchronizes L3 index with L2 database."""

    def __init__(
        self,
        l2_path: str,
        l3_path: str,
        embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        use_gpu: bool = False,
    ):
        """Initialize synchronizer."""
        self.l2_path = Path(l2_path)
        self.l3_path = Path(l3_path)
        self.embedding_model = embedding_model
        self.use_gpu = use_gpu

    def sync(self, dry_run: bool = False) -> None:
        """
        Sync L3 with L2.

        Args:
            dry_run: If True, only report what would be done
        """
        logger.info("=" * 60)
        logger.info("L3 Sync Verification")
        logger.info("=" * 60)
        logger.info(f"L2 database: {self.l2_path}")
        logger.info(f"L3 index: {self.l3_path}")
        logger.info(f"Mode: {'DRY RUN' if dry_run else 'SYNC'}")
        logger.info("")

        # Check L2
        if not self.l2_path.exists():
            logger.error(f"L2 database not found: {self.l2_path}")
            return

        # Check L3
        l3_index_file = self.l3_path / "index.faiss"
        if not l3_index_file.exists():
            logger.warning(f"L3 index not found: {l3_index_file}")
            logger.warning("Run build_l3_index.py first to create the index")
            return

        # Load L3
        logger.info("Loading L3 index...")
        l3 = L3SemanticTM(
            index_path=str(self.l3_path),
            embedding_model=self.embedding_model,
            use_gpu=self.use_gpu,
        )

        # Build set of entry IDs in L3
        logger.info("Building L3 entry map...")
        l3_entries = set()
        for meta in l3.metadata:
            entry_id = meta.get("entry_id")
            if entry_id:
                l3_entries.add(entry_id)

        logger.info(f"L3 has {len(l3_entries):,} entries")

        # Open L2
        logger.info("Opening L2 database...")
        env = lmdb.open(
            str(self.l2_path),
            readonly=True,
            max_dbs=1,
            lock=False,
        )

        # Count entries
        with env.begin() as txn:
            stat = txn.stat()
            l2_count = stat["entries"]
            logger.info(f"L2 has {l2_count:,} entries")

        # Find missing entries
        logger.info("")
        logger.info("Checking for missing entries...")
        missing_entries = []

        with env.begin() as txn:
            cursor = txn.cursor()
            for key_bytes, value_bytes in cursor:
                try:
                    # Parse key
                    key = key_bytes.decode("utf-8")
                    key_parts = key.split(":", 3)
                    if len(key_parts) != 4:
                        continue

                    site_id, src_lang, tgt_lang, entry_hash = key_parts
                    entry_id = f"{site_id}:{src_lang}:{tgt_lang}:{entry_hash}"

                    # Check if in L3
                    if entry_id not in l3_entries:
                        # Parse value
                        value = json.loads(value_bytes.decode("utf-8"))
                        missing_entries.append(
                            {
                                "entry_id": entry_id,
                                "site_id": site_id,
                                "src_lang": src_lang,
                                "tgt_lang": tgt_lang,
                                "source_text": value.get("source_text", ""),
                                "translation": value.get("translation", ""),
                                "context": value.get("context", ""),
                            }
                        )

                except Exception as e:
                    logger.error(f"Error processing entry: {e}")
                    continue

        env.close()

        # Report
        logger.info("")
        logger.info("=" * 60)
        logger.info("Sync Results")
        logger.info("=" * 60)
        logger.info(f"L2 entries: {l2_count:,}")
        logger.info(f"L3 entries: {len(l3_entries):,}")
        logger.info(f"Missing in L3: {len(missing_entries):,}")

        if len(missing_entries) == 0:
            logger.info("✓ L3 is in sync with L2")
            return

        # Add missing entries
        if not dry_run:
            logger.info("")
            logger.info(f"Adding {len(missing_entries):,} missing entries to L3...")

            for i, entry in enumerate(missing_entries):
                try:
                    l3.add_entry(
                        entry_id=entry["entry_id"],
                        site_id=entry["site_id"],
                        src_lang=entry["src_lang"],
                        tgt_lang=entry["tgt_lang"],
                        source_text=entry["source_text"],
                        translation=entry["translation"],
                        context=entry["context"],
                    )

                    if (i + 1) % 1000 == 0:
                        logger.info(f"  Added {i + 1:,} / {len(missing_entries):,}")
                        l3.save_index()

                except Exception as e:
                    logger.error(f"Error adding entry: {e}")
                    continue

            # Final save
            logger.info("Saving index...")
            l3.save_index()

            logger.info(f"✓ Added {len(missing_entries):,} entries to L3")
        else:
            logger.info("")
            logger.info("DRY RUN: No changes made")
            logger.info(f"Run without --dry-run to add {len(missing_entries):,} entries")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Sync L3 semantic index with L2 database")
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
        help="Use GPU for embedding generation",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be synced without making changes",
    )

    args = parser.parse_args()

    # Sync
    synchronizer = L3Synchronizer(
        l2_path=args.l2_path,
        l3_path=args.l3_path,
        embedding_model=args.embedding_model,
        use_gpu=args.use_gpu,
    )

    synchronizer.sync(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
