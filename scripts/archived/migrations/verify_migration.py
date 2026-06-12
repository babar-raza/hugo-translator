#!/usr/bin/env python
"""
Comprehensive migration verification tool.

Verifies migration completion by:
- Checking database integrity
- Validating entry structure and content
- Sampling random entries for quality checks
- Comparing against expected totals
- Detecting corrupt or invalid entries
- Generating detailed verification report

Usage:
    python scripts/verify_migration.py --tm-path ./data/tm
    python scripts/verify_migration.py --tm-path ./data/tm --verbose
    python scripts/verify_migration.py --tm-path ./data/tm --sample-size 1000
    python scripts/verify_migration.py --tm-path ./data/tm --output-report ./reports/migration_verification.md
"""

import argparse
import json
import logging
import os
import random
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

try:
    import lmdb
except ImportError:
    print("ERROR: lmdb not installed. Run: pip install lmdb")
    sys.exit(1)


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class MigrationVerifier:
    """Verify LMDB migration completion and integrity."""

    def __init__(self, tm_path: Path, expected_entries: int = 6_097_941, sample_size: int = 500):
        """
        Initialize migration verifier.

        Args:
            tm_path: Path to TM directory containing l2.lmdb
            expected_entries: Expected total entries from legacy cache
            sample_size: Number of random entries to sample for quality check
        """
        self.tm_path = Path(tm_path)
        self.db_path = self.tm_path / "l2.lmdb"
        self.expected_entries = expected_entries
        self.sample_size = sample_size

        self.stats = defaultdict(int)
        self.errors = []
        self.warnings = []
        self.language_stats = defaultdict(int)

        if not self.db_path.exists():
            raise ValueError(f"Database not found: {self.db_path}")

    def get_db_info(self) -> dict:
        """
        Get database information and statistics.

        Returns:
            Dictionary with database info
        """
        env = lmdb.open(str(self.db_path), readonly=True, max_dbs=10)

        stat = env.stat()
        info = env.info()

        # Get physical file size
        db_file = self.db_path / "data.mdb"
        file_size = 0
        if db_file.exists():
            file_size = os.path.getsize(db_file)

        db_info = {
            "entries": stat["entries"],
            "page_size": stat["psize"],
            "branch_pages": stat["branch_pages"],
            "leaf_pages": stat["leaf_pages"],
            "overflow_pages": stat["overflow_pages"],
            "total_pages": stat["branch_pages"] + stat["leaf_pages"] + stat["overflow_pages"],
            "map_size": info["map_size"],
            "file_size": file_size,
            "last_txnid": info["last_txnid"],
        }

        env.close()
        return db_info

    def validate_entry(self, key: bytes, value: bytes) -> tuple[bool, str | None]:
        """
        Validate a single database entry.

        Args:
            key: Entry key
            value: Entry value

        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            # Decode key
            try:
                key_str = key.decode("utf-8")
            except UnicodeDecodeError:
                return False, "Key is not valid UTF-8"

            # Decode value
            try:
                value_str = value.decode("utf-8")
            except UnicodeDecodeError:
                return False, "Value is not valid UTF-8"

            # Parse JSON value
            try:
                entry_data = json.loads(value_str)
            except json.JSONDecodeError as e:
                return False, f"Invalid JSON: {e}"

            # Validate required fields
            required_fields = ["source_text", "translation", "site_id", "src_lang", "tgt_lang"]
            for field in required_fields:
                if field not in entry_data:
                    return False, f"Missing required field: {field}"

            # Validate field types
            if not isinstance(entry_data["source_text"], str):
                return False, "source_text must be string"
            if not isinstance(entry_data["translation"], str):
                return False, "translation must be string"

            # Validate non-empty
            if not entry_data["source_text"].strip():
                return False, "source_text is empty"
            if not entry_data["translation"].strip():
                return False, "translation is empty"

            # Validate language codes (basic check)
            if len(entry_data["src_lang"]) < 2 or len(entry_data["tgt_lang"]) < 2:
                return False, "Invalid language codes"

            return True, None

        except Exception as e:
            return False, f"Validation exception: {e}"

    def sample_entries(self, num_samples: int) -> list[tuple[bytes, bytes]]:
        """
        Randomly sample entries from database.

        Args:
            num_samples: Number of entries to sample

        Returns:
            List of (key, value) tuples
        """
        env = lmdb.open(str(self.db_path), readonly=True, max_dbs=10)

        samples = []
        with env.begin() as txn:
            total_entries = txn.stat()["entries"]

            if total_entries == 0:
                env.close()
                return []

            # Generate random positions
            sample_positions = sorted(
                random.sample(range(total_entries), min(num_samples, total_entries))
            )

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
                    key, value = cursor.item()
                    samples.append((key, value))

        env.close()
        return samples

    def verify_database(self) -> dict:
        """
        Perform comprehensive database verification.

        Returns:
            Dictionary with verification results
        """
        logger.info("Starting database verification...")

        # Get database info
        db_info = self.get_db_info()
        self.stats["total_entries"] = db_info["entries"]
        self.stats["file_size_mb"] = db_info["file_size"] / 1024 / 1024

        logger.info(f"Total entries: {db_info['entries']:,}")
        logger.info(f"File size: {self.stats['file_size_mb']:.2f} MB")

        # Check if migration is complete
        completion_percentage = (db_info["entries"] / self.expected_entries) * 100
        self.stats["completion_percentage"] = completion_percentage

        if completion_percentage < 95.0:
            self.warnings.append(
                f"Migration incomplete: {completion_percentage:.1f}% "
                f"({db_info['entries']:,} / {self.expected_entries:,})"
            )

        # Sample and validate entries
        logger.info(f"Sampling {self.sample_size} random entries for validation...")
        samples = self.sample_entries(self.sample_size)

        valid_count = 0
        invalid_count = 0

        for key, value in samples:
            is_valid, error_msg = self.validate_entry(key, value)

            if is_valid:
                valid_count += 1

                # Parse for language statistics
                try:
                    value_str = value.decode("utf-8")
                    entry_data = json.loads(value_str)
                    lang_pair = f"{entry_data['src_lang']}->{entry_data['tgt_lang']}"
                    self.language_stats[lang_pair] += 1
                except:
                    pass
            else:
                invalid_count += 1
                self.errors.append(f"Invalid entry: {error_msg}")

        self.stats["sampled_entries"] = len(samples)
        self.stats["valid_entries"] = valid_count
        self.stats["invalid_entries"] = invalid_count
        self.stats["validation_rate"] = (valid_count / len(samples) * 100) if samples else 0

        logger.info(f"Validated {valid_count} / {len(samples)} sampled entries")

        # Check file size expectations (6-8 GB expected)
        expected_size_gb_min = 5.0
        expected_size_gb_max = 10.0
        actual_size_gb = db_info["file_size"] / 1024 / 1024 / 1024

        if actual_size_gb < expected_size_gb_min:
            self.warnings.append(
                f"Database size {actual_size_gb:.2f} GB is smaller than expected "
                f"({expected_size_gb_min:.1f} GB minimum)"
            )
        elif actual_size_gb > expected_size_gb_max:
            self.warnings.append(
                f"Database size {actual_size_gb:.2f} GB is larger than expected "
                f"({expected_size_gb_max:.1f} GB maximum)"
            )

        return db_info

    def print_report(self, db_info: dict) -> None:
        """
        Print verification report to console.

        Args:
            db_info: Database information dictionary
        """
        print()
        print("=" * 80)
        print("MIGRATION VERIFICATION REPORT")
        print("=" * 80)
        print(f"Database: {self.db_path}")
        print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print()

        print("Database Statistics:")
        print(f"  Total entries: {self.stats['total_entries']:,}")
        print(f"  Expected entries: {self.expected_entries:,}")
        print(f"  Completion: {self.stats['completion_percentage']:.2f}%")
        print(
            f"  Physical size: {self.stats['file_size_mb']:.2f} MB ({self.stats['file_size_mb'] / 1024:.2f} GB)"
        )
        print(f"  Map size: {db_info['map_size'] / 1024 / 1024 / 1024:.2f} GB")
        print()

        print("Sample Validation:")
        print(f"  Entries sampled: {self.stats['sampled_entries']:,}")
        print(f"  Valid entries: {self.stats['valid_entries']:,}")
        print(f"  Invalid entries: {self.stats['invalid_entries']:,}")
        print(f"  Validation rate: {self.stats['validation_rate']:.2f}%")
        print()

        if self.language_stats:
            print("Language Pair Distribution (from sample):")
            for lang_pair, count in sorted(
                self.language_stats.items(), key=lambda x: x[1], reverse=True
            ):
                percentage = (count / self.stats["sampled_entries"]) * 100
                print(f"  {lang_pair}: {count:,} ({percentage:.1f}%)")
            print()

        # Warnings
        if self.warnings:
            print("Warnings:")
            for warning in self.warnings:
                print(f"  ⚠ {warning}")
            print()

        # Errors
        if self.errors:
            print("Errors (first 10):")
            for error in self.errors[:10]:
                print(f"  ✗ {error}")
            if len(self.errors) > 10:
                print(f"  ... and {len(self.errors) - 10} more errors")
            print()

        # Verdict
        print("=" * 80)
        print("VERDICT:")

        if self.stats["invalid_entries"] > 0:
            print(f"FAILED: Found {self.stats['invalid_entries']} invalid entries in sample")
        elif self.stats["completion_percentage"] < 95.0:
            print(f"INCOMPLETE: Only {self.stats['completion_percentage']:.1f}% migrated")
        elif len(self.warnings) > 0:
            print(f"PASSED WITH WARNINGS: {len(self.warnings)} warnings found")
        else:
            print("SUCCESS: Migration completed successfully")
            print(
                f"  - {self.stats['total_entries']:,} entries migrated ({self.stats['completion_percentage']:.1f}%)"
            )
            print(
                f"  - {self.stats['validation_rate']:.1f}% validation rate from {self.stats['sampled_entries']} samples"
            )
            print(f"  - Database size: {self.stats['file_size_mb'] / 1024:.2f} GB")

        print("=" * 80)
        print()

    def generate_markdown_report(self, output_path: Path, db_info: dict) -> None:
        """
        Generate markdown verification report.

        Args:
            output_path: Path to output markdown file
            db_info: Database information dictionary
        """
        report = []
        report.append("# Migration Verification Report")
        report.append("")
        report.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append(f"**Database:** `{self.db_path}`")
        report.append("")

        report.append("## Summary")
        report.append("")
        report.append(f"- **Total Entries:** {self.stats['total_entries']:,}")
        report.append(f"- **Expected Entries:** {self.expected_entries:,}")
        report.append(f"- **Completion:** {self.stats['completion_percentage']:.2f}%")
        report.append(f"- **Database Size:** {self.stats['file_size_mb'] / 1024:.2f} GB")
        report.append(f"- **Validation Rate:** {self.stats['validation_rate']:.2f}%")
        report.append("")

        report.append("## Database Statistics")
        report.append("")
        report.append("| Metric | Value |")
        report.append("|--------|-------|")
        report.append(f"| Total Entries | {self.stats['total_entries']:,} |")
        report.append(f"| Physical Size | {self.stats['file_size_mb']:.2f} MB |")
        report.append(f"| Map Size | {db_info['map_size'] / 1024 / 1024 / 1024:.2f} GB |")
        report.append(f"| Page Size | {db_info['page_size']:,} bytes |")
        report.append(f"| Total Pages | {db_info['total_pages']:,} |")
        report.append(f"| Last Transaction | {db_info['last_txnid']:,} |")
        report.append("")

        report.append("## Sample Validation")
        report.append("")
        report.append(f"Randomly sampled {self.stats['sampled_entries']} entries for validation.")
        report.append("")
        report.append("| Metric | Count | Percentage |")
        report.append("|--------|-------|------------|")
        report.append(
            f"| Valid Entries | {self.stats['valid_entries']:,} | {self.stats['validation_rate']:.2f}% |"
        )
        report.append(
            f"| Invalid Entries | {self.stats['invalid_entries']:,} | {100 - self.stats['validation_rate']:.2f}% |"
        )
        report.append("")

        if self.language_stats:
            report.append("## Language Pair Distribution")
            report.append("")
            report.append("Distribution from sampled entries:")
            report.append("")
            report.append("| Language Pair | Count | Percentage |")
            report.append("|---------------|-------|------------|")
            for lang_pair, count in sorted(
                self.language_stats.items(), key=lambda x: x[1], reverse=True
            ):
                percentage = (count / self.stats["sampled_entries"]) * 100
                report.append(f"| {lang_pair} | {count:,} | {percentage:.1f}% |")
            report.append("")

        if self.warnings:
            report.append("## Warnings")
            report.append("")
            for warning in self.warnings:
                report.append(f"- ⚠️ {warning}")
            report.append("")

        if self.errors:
            report.append("## Errors")
            report.append("")
            report.append(f"Found {len(self.errors)} errors during validation:")
            report.append("")
            for error in self.errors[:20]:  # Show first 20 errors
                report.append(f"- ❌ {error}")
            if len(self.errors) > 20:
                report.append(f"- ... and {len(self.errors) - 20} more errors")
            report.append("")

        report.append("## Verdict")
        report.append("")
        if self.stats["invalid_entries"] > 0:
            report.append("**Status:** ❌ FAILED")
            report.append("")
            report.append(f"Found {self.stats['invalid_entries']} invalid entries in sample.")
        elif self.stats["completion_percentage"] < 95.0:
            report.append("**Status:** ⚠️ INCOMPLETE")
            report.append("")
            report.append(
                f"Only {self.stats['completion_percentage']:.1f}% of expected entries migrated."
            )
        elif len(self.warnings) > 0:
            report.append("**Status:** ✅ PASSED WITH WARNINGS")
            report.append("")
            report.append(f"Migration completed with {len(self.warnings)} warnings.")
        else:
            report.append("**Status:** ✅ SUCCESS")
            report.append("")
            report.append("Migration completed successfully:")
            report.append(
                f"- {self.stats['total_entries']:,} entries migrated ({self.stats['completion_percentage']:.1f}%)"
            )
            report.append(f"- {self.stats['validation_rate']:.1f}% validation rate")
            report.append(f"- Database size: {self.stats['file_size_mb'] / 1024:.2f} GB")

        # Write report
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(report))

        logger.info(f"Report written to: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Verify legacy cache migration completion",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--tm-path", default="./data/tm", help="Path to TM directory (default: ./data/tm)"
    )

    parser.add_argument(
        "--expected-entries",
        type=int,
        default=6_097_941,
        help="Expected total entries (default: 6,097,941)",
    )

    parser.add_argument(
        "--sample-size",
        type=int,
        default=500,
        help="Number of entries to sample for validation (default: 500)",
    )

    parser.add_argument(
        "--output-report", type=Path, help="Output path for markdown report (optional)"
    )

    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        verifier = MigrationVerifier(
            tm_path=Path(args.tm_path),
            expected_entries=args.expected_entries,
            sample_size=args.sample_size,
        )

        db_info = verifier.verify_database()
        verifier.print_report(db_info)

        # Generate markdown report if requested
        if args.output_report:
            verifier.generate_markdown_report(args.output_report, db_info)

        # Exit code based on verification result
        if verifier.stats["invalid_entries"] > 0:
            sys.exit(1)  # Failed
        elif verifier.stats["completion_percentage"] < 95.0:
            sys.exit(1)  # Incomplete
        else:
            sys.exit(0)  # Success

    except Exception as e:
        logger.error(f"Verification failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
