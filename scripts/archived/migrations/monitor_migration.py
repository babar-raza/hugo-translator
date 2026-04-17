#!/usr/bin/env python
"""
Monitor legacy cache migration in real-time.

Provides real-time monitoring of the migration process including:
- Current entry count in L2 database
- Migration progress percentage
- Estimated time remaining
- Database size and statistics

Usage:
    python scripts/monitor_migration.py --status        # Show current status
    python scripts/monitor_migration.py --watch         # Continuous monitoring
    python scripts/monitor_migration.py --tm-path <path> # Custom TM path
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

try:
    import lmdb
except ImportError:
    print("ERROR: lmdb not installed. Run: pip install lmdb")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MigrationMonitor:
    """Monitor LMDB migration progress."""

    def __init__(self, tm_path: Path, expected_entries: int = 6_097_941):
        """
        Initialize migration monitor.

        Args:
            tm_path: Path to TM directory containing l2.lmdb
            expected_entries: Expected total entries from legacy cache
        """
        self.tm_path = Path(tm_path)
        self.db_path = self.tm_path / "l2.lmdb"
        self.expected_entries = expected_entries

        if not self.db_path.exists():
            raise ValueError(f"Database not found: {self.db_path}")

    def get_db_stats(self) -> dict:
        """
        Get current database statistics.

        Returns:
            Dictionary with database stats
        """
        try:
            env = lmdb.open(str(self.db_path), readonly=True, max_dbs=10)

            stat = env.stat()
            info = env.info()

            # Get physical file size
            db_file = self.db_path / "data.mdb"
            file_size = 0
            if db_file.exists():
                file_size = os.path.getsize(db_file)

            stats = {
                'entries': stat['entries'],
                'page_size': stat['psize'],
                'branch_pages': stat['branch_pages'],
                'leaf_pages': stat['leaf_pages'],
                'overflow_pages': stat['overflow_pages'],
                'total_pages': stat['branch_pages'] + stat['leaf_pages'] + stat['overflow_pages'],
                'map_size': info['map_size'],
                'last_pgno': info['last_pgno'],
                'last_txnid': info['last_txnid'],
                'max_readers': info['max_readers'],
                'num_readers': info['num_readers'],
                'file_size': file_size,
                'timestamp': datetime.now().isoformat(),
            }

            env.close()
            return stats

        except Exception as e:
            logger.error(f"Failed to get database stats: {e}")
            raise

    def calculate_progress(self, current_entries: int) -> dict:
        """
        Calculate migration progress metrics.

        Args:
            current_entries: Current number of entries in database

        Returns:
            Dictionary with progress metrics
        """
        percentage = (current_entries / self.expected_entries) * 100
        remaining = max(0, self.expected_entries - current_entries)

        return {
            'current': current_entries,
            'expected': self.expected_entries,
            'percentage': percentage,
            'remaining': remaining,
            'is_complete': percentage >= 95.0,  # 95% threshold for completion
        }

    def print_status(self, watch_mode: bool = False) -> None:
        """
        Print current migration status.

        Args:
            watch_mode: If True, format for continuous monitoring
        """
        try:
            stats = self.get_db_stats()
            progress = self.calculate_progress(stats['entries'])

            if not watch_mode:
                print("=" * 80)
                print("MIGRATION STATUS REPORT")
                print("=" * 80)
                print(f"Database: {self.db_path}")
                print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print()

            print("Migration Progress:")
            print(f"  Current entries: {progress['current']:,}")
            print(f"  Expected entries: {progress['expected']:,}")
            print(f"  Progress: {progress['percentage']:.2f}%")
            print(f"  Remaining: {progress['remaining']:,} entries")
            print()

            print("Database Statistics:")
            print(f"  Physical size: {stats['file_size'] / 1024 / 1024:.2f} MB")
            print(f"  Map size: {stats['map_size'] / 1024 / 1024 / 1024:.2f} GB")
            print(f"  Total pages: {stats['total_pages']:,}")
            print(f"    - Branch pages: {stats['branch_pages']:,}")
            print(f"    - Leaf pages: {stats['leaf_pages']:,}")
            print(f"    - Overflow pages: {stats['overflow_pages']:,}")
            print(f"  Last transaction ID: {stats['last_txnid']:,}")
            print(f"  Active readers: {stats['num_readers']}")
            print()

            # Status verdict
            if progress['is_complete']:
                print("STATUS: COMPLETE ✓")
                print(f"Migration has reached {progress['percentage']:.1f}% completion threshold")
            elif progress['percentage'] > 0:
                print("STATUS: IN PROGRESS...")
                print(f"Migration is {progress['percentage']:.1f}% complete")
            else:
                print("STATUS: NOT STARTED")
                print("No entries found in database")

            if not watch_mode:
                print("=" * 80)

        except Exception as e:
            logger.error(f"Failed to print status: {e}")
            raise

    def watch(self, interval: int = 5) -> None:
        """
        Continuously monitor migration progress.

        Args:
            interval: Seconds between updates
        """
        print(f"Monitoring migration progress (updating every {interval}s)...")
        print("Press Ctrl+C to stop")
        print()

        last_entries = 0
        start_time = datetime.now()
        samples = []

        try:
            while True:
                os.system('cls' if os.name == 'nt' else 'clear')

                print("=" * 80)
                print(f"LIVE MIGRATION MONITORING - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print("=" * 80)
                print()

                stats = self.get_db_stats()
                progress = self.calculate_progress(stats['entries'])

                # Calculate rate
                current_entries = stats['entries']
                entries_per_second = 0
                eta_str = "Calculating..."

                if len(samples) >= 2:
                    # Calculate average rate from recent samples
                    time_elapsed = (datetime.now() - samples[0][0]).total_seconds()
                    entries_added = current_entries - samples[0][1]
                    if time_elapsed > 0:
                        entries_per_second = entries_added / time_elapsed

                    # Calculate ETA
                    if entries_per_second > 0 and progress['remaining'] > 0:
                        seconds_remaining = progress['remaining'] / entries_per_second
                        eta = datetime.now() + timedelta(seconds=seconds_remaining)
                        eta_str = eta.strftime('%Y-%m-%d %H:%M:%S')

                # Add current sample (keep last 10 samples)
                samples.append((datetime.now(), current_entries))
                if len(samples) > 10:
                    samples.pop(0)

                # Print progress
                self.print_status(watch_mode=True)

                print("Performance:")
                print(f"  Entries/second: {entries_per_second:.1f}")
                print(f"  ETA: {eta_str}")
                print()

                # Progress bar
                bar_width = 50
                filled = int(bar_width * progress['percentage'] / 100)
                bar = '█' * filled + '░' * (bar_width - filled)
                print(f"  [{bar}] {progress['percentage']:.1f}%")
                print()

                if progress['is_complete']:
                    print("Migration COMPLETE! ✓")
                    break

                last_entries = current_entries
                time.sleep(interval)

        except KeyboardInterrupt:
            print("\n\nMonitoring stopped by user")
            print("=" * 80)


def main():
    parser = argparse.ArgumentParser(
        description="Monitor legacy cache migration progress",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        '--status',
        action='store_true',
        help='Show current migration status (one-time)'
    )

    parser.add_argument(
        '--watch',
        action='store_true',
        help='Continuously monitor migration progress'
    )

    parser.add_argument(
        '--tm-path',
        default='./data/tm',
        help='Path to TM directory (default: ./data/tm)'
    )

    parser.add_argument(
        '--expected-entries',
        type=int,
        default=6_097_941,
        help='Expected total entries (default: 6,097,941)'
    )

    parser.add_argument(
        '--interval',
        type=int,
        default=5,
        help='Update interval in seconds for watch mode (default: 5)'
    )

    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Default to status if neither flag specified
    if not args.status and not args.watch:
        args.status = True

    try:
        monitor = MigrationMonitor(
            tm_path=Path(args.tm_path),
            expected_entries=args.expected_entries
        )

        if args.watch:
            monitor.watch(interval=args.interval)
        else:
            monitor.print_status()

        sys.exit(0)

    except Exception as e:
        logger.error(f"Monitoring failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
