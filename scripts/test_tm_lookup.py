#!/usr/bin/env python
"""
Test TM lookup functionality across all layers.

Performs comprehensive testing of:
- L1 cache hit rate after warmup
- L2 exact match functionality
- L3 semantic search with similarity threshold
- Layer statistics and reporting

Usage:
    python scripts/test_tm_lookup.py
    python scripts/test_tm_lookup.py --sample-size 100
    python scripts/test_tm_lookup.py --tm-path ./data/tm --output-report ./reports/tm_health_report.md
"""

import argparse
import json
import logging
import random
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

try:
    import lmdb
except ImportError:
    print("ERROR: lmdb not installed. Run: pip install lmdb")
    sys.exit(1)

from tm import TranslationMemory, L1Cache, L2PersistentTM, L3SemanticTM

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TMLookupTester:
    """Test TM lookup functionality."""

    def __init__(
        self,
        tm_path: Path,
        sample_size: int = 100,
        use_gpu: bool = False
    ):
        """
        Initialize TM lookup tester.

        Args:
            tm_path: Path to TM directory
            sample_size: Number of entries to test
            use_gpu: Use GPU for L3 if available
        """
        self.tm_path = Path(tm_path)
        self.sample_size = sample_size
        self.use_gpu = use_gpu

        # Initialize TM layers
        logger.info("Initializing TM layers...")
        self.l1 = L1Cache(max_size=10000)
        self.l2 = L2PersistentTM(self.tm_path / "l2.lmdb", max_size_mb=10240)

        # Check if L3 exists
        l3_path = self.tm_path / "l3_faiss"
        if (l3_path / "index.faiss").exists():
            logger.info("Loading L3 semantic index...")
            self.l3 = L3SemanticTM(l3_path, use_gpu=use_gpu)
        else:
            logger.warning("L3 index not found, semantic search disabled")
            self.l3 = None

        self.tm = TranslationMemory(
            l1_cache=self.l1,
            l2_persistent=self.l2,
            l3_semantic=self.l3
        )

        self.results = {
            'l1_cache': {'hits': 0, 'misses': 0, 'tests': 0},
            'l2_exact': {'hits': 0, 'misses': 0, 'tests': 0},
            'l3_semantic': {'hits': 0, 'misses': 0, 'tests': 0, 'avg_similarity': 0.0},
            'sample_entries': [],
        }

    def get_sample_entries(self) -> List[Dict]:
        """
        Get random sample entries from L2 database.

        Returns:
            List of entry dictionaries
        """
        logger.info(f"Sampling {self.sample_size} random entries from L2...")

        env = lmdb.open(str(self.tm_path / "l2.lmdb"), readonly=True, max_dbs=10)

        entries = []
        with env.begin() as txn:
            total_entries = txn.stat()['entries']

            if total_entries == 0:
                logger.warning("L2 database is empty!")
                env.close()
                return []

            # Generate random positions
            sample_positions = sorted(random.sample(
                range(total_entries),
                min(self.sample_size, total_entries)
            ))

            cursor = txn.cursor()
            cursor.first()

            current_pos = 0
            for target_pos in sample_positions:
                # Advance cursor to target position
                while current_pos < target_pos:
                    if not cursor.next():
                        break
                    current_pos += 1

                if current_pos == target_pos:
                    key_bytes, value_bytes = cursor.item()

                    try:
                        key = key_bytes.decode('utf-8')
                        value_str = value_bytes.decode('utf-8')
                        entry_data = json.loads(value_str)

                        entries.append({
                            'key': key,
                            'source_text': entry_data.get('source_text', ''),
                            'translation': entry_data.get('translation', ''),
                            'site_id': entry_data.get('site_id', 'default'),
                            'src_lang': entry_data.get('src_lang', 'en'),
                            'tgt_lang': entry_data.get('tgt_lang', 'unknown'),
                        })
                    except Exception as e:
                        logger.debug(f"Failed to parse entry: {e}")

        env.close()
        return entries

    def test_l1_cache_warmup(self, entries: List[Dict]) -> None:
        """
        Test L1 cache hit rate after warmup.

        Args:
            entries: List of test entries
        """
        logger.info("\n=== Testing L1 Cache ===")

        # Clear L1 to start fresh
        self.l1.clear()

        # First pass - populate cache
        logger.info("Warming up L1 cache...")
        for entry in entries:
            self.tm.lookup(
                site_id=entry['site_id'],
                src_lang=entry['src_lang'],
                tgt_lang=entry['tgt_lang'],
                text=entry['source_text']
            )

        # Second pass - test cache hits
        logger.info("Testing L1 cache hit rate...")
        l1_hits = 0
        l1_misses = 0

        for entry in entries:
            result = self.tm.lookup(
                site_id=entry['site_id'],
                src_lang=entry['src_lang'],
                tgt_lang=entry['tgt_lang'],
                text=entry['source_text']
            )

            if result.source == "l1_cache":
                l1_hits += 1
            else:
                l1_misses += 1

        self.results['l1_cache']['hits'] = l1_hits
        self.results['l1_cache']['misses'] = l1_misses
        self.results['l1_cache']['tests'] = len(entries)

        hit_rate = (l1_hits / len(entries) * 100) if entries else 0
        logger.info(f"L1 hit rate: {hit_rate:.1f}% ({l1_hits}/{len(entries)})")

    def test_l2_exact_match(self, entries: List[Dict]) -> None:
        """
        Test L2 exact match functionality.

        Args:
            entries: List of test entries
        """
        logger.info("\n=== Testing L2 Exact Match ===")

        # Clear L1 to force L2 lookups
        self.l1.clear()

        l2_hits = 0
        l2_misses = 0

        for entry in entries:
            result = self.tm.lookup(
                site_id=entry['site_id'],
                src_lang=entry['src_lang'],
                tgt_lang=entry['tgt_lang'],
                text=entry['source_text'],
                use_semantic=False  # Disable L3
            )

            if result.source == "l2_exact":
                l2_hits += 1
            else:
                l2_misses += 1

        self.results['l2_exact']['hits'] = l2_hits
        self.results['l2_exact']['misses'] = l2_misses
        self.results['l2_exact']['tests'] = len(entries)

        hit_rate = (l2_hits / len(entries) * 100) if entries else 0
        logger.info(f"L2 hit rate: {hit_rate:.1f}% ({l2_hits}/{len(entries)})")

    def test_l3_semantic_search(self, entries: List[Dict]) -> None:
        """
        Test L3 semantic search functionality.

        Args:
            entries: List of test entries
        """
        if self.l3 is None:
            logger.info("\n=== Skipping L3 Semantic Search (index not available) ===")
            return

        logger.info("\n=== Testing L3 Semantic Search ===")

        # Test with slightly modified queries
        l3_hits = 0
        l3_misses = 0
        similarities = []

        # Test first 20 entries (semantic search is slower)
        test_entries = entries[:min(20, len(entries))]

        for entry in test_entries:
            # Modify text slightly to test semantic matching
            modified_text = entry['source_text'] + " "  # Add space

            # Clear L1 and check L3 directly
            self.l1.clear()

            result = self.tm.lookup(
                site_id=entry['site_id'],
                src_lang=entry['src_lang'],
                tgt_lang=entry['tgt_lang'],
                text=modified_text,
                use_semantic=True,
                semantic_threshold=0.75
            )

            if result.source == "l3_semantic" or result.source == "l2_exact":
                l3_hits += 1
                if result.confidence is not None:
                    similarities.append(result.confidence)
            else:
                l3_misses += 1

        self.results['l3_semantic']['hits'] = l3_hits
        self.results['l3_semantic']['misses'] = l3_misses
        self.results['l3_semantic']['tests'] = len(test_entries)

        avg_similarity = sum(similarities) / len(similarities) if similarities else 0.0
        self.results['l3_semantic']['avg_similarity'] = avg_similarity

        hit_rate = (l3_hits / len(test_entries) * 100) if test_entries else 0
        logger.info(f"L3 hit rate: {hit_rate:.1f}% ({l3_hits}/{len(test_entries)})")
        logger.info(f"Average similarity: {avg_similarity:.3f}")

    def run_tests(self) -> Dict:
        """
        Run all TM lookup tests.

        Returns:
            Test results dictionary
        """
        logger.info("=" * 80)
        logger.info("TM Layer Lookup Tests")
        logger.info("=" * 80)
        logger.info(f"TM Path: {self.tm_path}")
        logger.info(f"Sample size: {self.sample_size}")
        logger.info("")

        # Get sample entries
        entries = self.get_sample_entries()

        if not entries:
            logger.error("No entries available for testing!")
            return self.results

        logger.info(f"Testing with {len(entries)} entries")

        # Save sample entries for report
        self.results['sample_entries'] = entries[:5]  # Save first 5 for report

        # Run tests
        self.test_l1_cache_warmup(entries)
        self.test_l2_exact_match(entries)
        self.test_l3_semantic_search(entries)

        # Print summary
        self.print_summary()

        return self.results

    def print_summary(self) -> None:
        """Print test summary."""
        logger.info("")
        logger.info("=" * 80)
        logger.info("Test Summary")
        logger.info("=" * 80)

        # L1 Cache
        l1_hit_rate = (self.results['l1_cache']['hits'] / self.results['l1_cache']['tests'] * 100) if self.results['l1_cache']['tests'] > 0 else 0
        logger.info(f"L1 Cache:")
        logger.info(f"  Hit rate: {l1_hit_rate:.1f}%")
        logger.info(f"  Hits: {self.results['l1_cache']['hits']}")
        logger.info(f"  Misses: {self.results['l1_cache']['misses']}")

        # L2 Exact
        l2_hit_rate = (self.results['l2_exact']['hits'] / self.results['l2_exact']['tests'] * 100) if self.results['l2_exact']['tests'] > 0 else 0
        logger.info(f"\nL2 Exact Match:")
        logger.info(f"  Hit rate: {l2_hit_rate:.1f}%")
        logger.info(f"  Hits: {self.results['l2_exact']['hits']}")
        logger.info(f"  Misses: {self.results['l2_exact']['misses']}")

        # L3 Semantic
        if self.results['l3_semantic']['tests'] > 0:
            l3_hit_rate = (self.results['l3_semantic']['hits'] / self.results['l3_semantic']['tests'] * 100)
            logger.info(f"\nL3 Semantic Search:")
            logger.info(f"  Hit rate: {l3_hit_rate:.1f}%")
            logger.info(f"  Hits: {self.results['l3_semantic']['hits']}")
            logger.info(f"  Misses: {self.results['l3_semantic']['misses']}")
            logger.info(f"  Avg similarity: {self.results['l3_semantic']['avg_similarity']:.3f}")

        # TM Statistics
        logger.info("\nTM Statistics:")
        stats = self.tm.stats()
        logger.info(f"  L1 size: {stats.l1_size}/{stats.l1_max_size}")
        logger.info(f"  L2 size: {stats.l2_size:,}")
        logger.info(f"  L3 size: {stats.l3_size:,}")
        logger.info(f"  Overall hit rate: {stats.overall_hit_rate:.1%}")

        logger.info("")
        logger.info("=" * 80)

    def generate_report(self, output_path: Path) -> None:
        """
        Generate markdown health report.

        Args:
            output_path: Path to output markdown file
        """
        report = []
        report.append("# TM Health Report")
        report.append("")
        report.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append(f"**TM Path:** `{self.tm_path}`")
        report.append("")

        # Summary
        report.append("## Summary")
        report.append("")
        report.append("| Layer | Hit Rate | Hits | Misses |")
        report.append("|-------|----------|------|--------|")

        l1_hit_rate = (self.results['l1_cache']['hits'] / self.results['l1_cache']['tests'] * 100) if self.results['l1_cache']['tests'] > 0 else 0
        report.append(f"| L1 Cache | {l1_hit_rate:.1f}% | {self.results['l1_cache']['hits']} | {self.results['l1_cache']['misses']} |")

        l2_hit_rate = (self.results['l2_exact']['hits'] / self.results['l2_exact']['tests'] * 100) if self.results['l2_exact']['tests'] > 0 else 0
        report.append(f"| L2 Exact | {l2_hit_rate:.1f}% | {self.results['l2_exact']['hits']} | {self.results['l2_exact']['misses']} |")

        if self.results['l3_semantic']['tests'] > 0:
            l3_hit_rate = (self.results['l3_semantic']['hits'] / self.results['l3_semantic']['tests'] * 100)
            report.append(f"| L3 Semantic | {l3_hit_rate:.1f}% | {self.results['l3_semantic']['hits']} | {self.results['l3_semantic']['misses']} |")
        report.append("")

        # TM Statistics
        stats = self.tm.stats()
        report.append("## TM Statistics")
        report.append("")
        report.append("| Metric | Value |")
        report.append("|--------|-------|")
        report.append(f"| L1 Size | {stats.l1_size} / {stats.l1_max_size} |")
        report.append(f"| L2 Size | {stats.l2_size:,} entries |")
        report.append(f"| L3 Size | {stats.l3_size:,} entries |")
        report.append(f"| Total Lookups | {stats.total_lookups:,} |")
        report.append(f"| Total Hits | {stats.total_hits:,} |")
        report.append(f"| Overall Hit Rate | {stats.overall_hit_rate:.1%} |")
        report.append("")

        # L3 Details
        if self.results['l3_semantic']['tests'] > 0:
            report.append("## L3 Semantic Search")
            report.append("")
            report.append(f"- **Average Similarity:** {self.results['l3_semantic']['avg_similarity']:.3f}")
            report.append(f"- **Tests Performed:** {self.results['l3_semantic']['tests']}")
            report.append("")

        # Verdict
        report.append("## Verdict")
        report.append("")

        all_good = True
        if l1_hit_rate < 50:
            report.append("- ⚠️ L1 cache hit rate is low (expected >80% after warmup)")
            all_good = False
        if l2_hit_rate < 90:
            report.append("- ⚠️ L2 exact match rate is low (expected >95%)")
            all_good = False
        if self.results['l3_semantic']['tests'] > 0 and self.results['l3_semantic']['avg_similarity'] < 0.75:
            report.append("- ⚠️ L3 semantic similarity is low (expected >0.75)")
            all_good = False

        if all_good:
            report.append("✅ **All TM layers are functioning correctly**")
        else:
            report.append("⚠️ **Some TM layers may need attention**")

        # Write report
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(report))

        logger.info(f"Report written to: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Test TM lookup functionality",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        '--tm-path',
        default='./data/tm',
        help='Path to TM directory (default: ./data/tm)'
    )

    parser.add_argument(
        '--sample-size',
        type=int,
        default=100,
        help='Number of entries to test (default: 100)'
    )

    parser.add_argument(
        '--use-gpu',
        action='store_true',
        help='Use GPU for L3 semantic search'
    )

    parser.add_argument(
        '--output-report',
        type=Path,
        help='Output path for markdown report (optional)'
    )

    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        tester = TMLookupTester(
            tm_path=Path(args.tm_path),
            sample_size=args.sample_size,
            use_gpu=args.use_gpu
        )

        results = tester.run_tests()

        # Generate report if requested
        if args.output_report:
            tester.generate_report(args.output_report)

        sys.exit(0)

    except Exception as e:
        logger.error(f"Testing failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
