#!/usr/bin/env python3
"""
Historical Telemetry Cleanup - Identify Fake Skip Entries

This script identifies telemetry events where translations were skipped (no work done)
but logged as "completed" successes. This occurred before the skip handling fix was
deployed on 2026-01-11.

Detection Criteria:
- Event status is "completed" or "success"
- Job type is "translate_file" or "translate_directory"
- Field langs_translated is NULL (didn't exist) OR equals 0
- Timestamp is before 2026-01-11 (before fix deployed)

Usage:
  # Dry run (default) - identify fake entries
  python identify_fake_skip_entries.py --dry-run

  # Export event IDs to JSON file
  python identify_fake_skip_entries.py --export fake_entries.json

  # Count affected events
  python identify_fake_skip_entries.py --dry-run --count

  # Specify custom cutoff date
  python identify_fake_skip_entries.py --cutoff-date 2026-01-15 --dry-run

Created: 2026-01-11
Version: 1.0.0
"""

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


class FakeEntryDetector:
    """Detects and exports fake skip entries from telemetry database."""

    def __init__(self, db_path: str | None = None, cutoff_date: str = "2026-01-11T00:00:00"):
        """
        Initialize detector.

        Args:
            db_path: Path to telemetry SQLite database (default: auto-detect)
            cutoff_date: ISO 8601 date string for detection cutoff
        """
        self.db_path = db_path or self._find_database()
        self.cutoff_date = cutoff_date
        self.conn = None

    def _find_database(self) -> str:
        """Auto-detect telemetry database location."""
        # Common locations for local-telemetry database
        possible_paths = [
            Path.home() / ".local-telemetry" / "telemetry.db",
            Path.home() / ".claude" / "local-telemetry" / "telemetry.db",
            Path("telemetry.db"),
        ]

        for path in possible_paths:
            if path.exists():
                return str(path)

        raise FileNotFoundError(
            "Could not find telemetry database. Specify with --db-path option."
        )

    def connect(self) -> None:
        """Connect to telemetry database."""
        try:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row
            print(f"✅ Connected to database: {self.db_path}")
        except sqlite3.Error as e:
            print(f"❌ Database connection failed: {e}", file=sys.stderr)
            sys.exit(1)

    def disconnect(self) -> None:
        """Disconnect from database."""
        if self.conn:
            self.conn.close()
            print("✅ Disconnected from database")

    def detect_fake_entries(self) -> list[dict]:
        """
        Detect fake skip entries using detection criteria.

        Returns:
            List of fake entry records with event_id, timestamp, status, reason
        """
        query = """
        SELECT
            event_id,
            timestamp,
            job_type,
            status,
            output_summary,
            metrics_json
        FROM telemetry_events
        WHERE job_type IN ('translate_file', 'translate_directory')
          AND status IN ('completed', 'success')
          AND timestamp < ?
        ORDER BY timestamp DESC;
        """

        cursor = self.conn.cursor()
        cursor.execute(query, (self.cutoff_date,))
        rows = cursor.fetchall()

        fake_entries = []

        for row in rows:
            # Parse metrics_json to check langs_translated field
            metrics = {}
            if row["metrics_json"]:
                try:
                    metrics = json.loads(row["metrics_json"])
                except json.JSONDecodeError:
                    pass

            langs_translated = metrics.get("langs_translated")

            # Detection criteria: langs_translated is NULL or 0
            if langs_translated is None or langs_translated == 0:
                reason = self._determine_reason(row, metrics)
                fake_entries.append({
                    "event_id": row["event_id"],
                    "timestamp": row["timestamp"],
                    "job_type": row["job_type"],
                    "status": row["status"],
                    "output_summary": row["output_summary"],
                    "reason": reason,
                })

        return fake_entries

    def _determine_reason(self, row: sqlite3.Row, metrics: dict) -> str:
        """Determine why entry is considered fake."""
        if "langs_translated" not in metrics:
            return "langs_translated field missing (pre-fix version)"
        elif metrics.get("langs_translated") == 0:
            return "langs_translated equals 0 (all skipped but logged as success)"
        else:
            return "unknown"

    def export_to_json(self, entries: list[dict], output_path: str) -> None:
        """
        Export fake entries to JSON file.

        Args:
            entries: List of fake entry records
            output_path: Path to output JSON file
        """
        metadata = {
            "detection_date": datetime.now().isoformat(),
            "criteria": "langs_translated is NULL or 0",
            "count": len(entries),
            "cutoff_date": self.cutoff_date,
            "time_range": f"inception to {self.cutoff_date}",
            "database_path": self.db_path,
        }

        output_data = {
            "metadata": metadata,
            "events": entries,
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)

        print(f"✅ Exported {len(entries)} fake entries to: {output_path}")

    def print_summary(self, entries: list[dict]) -> None:
        """Print summary of detected fake entries."""
        print("\n" + "=" * 80)
        print("FAKE SKIP ENTRY DETECTION SUMMARY")
        print("=" * 80)
        print(f"Database: {self.db_path}")
        print(f"Cutoff Date: {self.cutoff_date}")
        print(f"Total Fake Entries Detected: {len(entries)}")
        print("=" * 80)

        if entries:
            print("\nSample Entries (first 5):")
            for i, entry in enumerate(entries[:5], 1):
                print(f"\n{i}. Event ID: {entry['event_id']}")
                print(f"   Timestamp: {entry['timestamp']}")
                print(f"   Status: {entry['status']}")
                print(f"   Reason: {entry['reason']}")
                print(f"   Output Summary: {entry['output_summary'][:60]}...")

            if len(entries) > 5:
                print(f"\n... and {len(entries) - 5} more entries")
        else:
            print("\n✅ No fake entries detected (database clean or fix already applied)")

        print("\n" + "=" * 80)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Identify fake skip entries in telemetry database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run (identify fake entries)
  python identify_fake_skip_entries.py --dry-run

  # Export event IDs to JSON
  python identify_fake_skip_entries.py --export fake_entries.json

  # Count only
  python identify_fake_skip_entries.py --dry-run --count

  # Custom database path
  python identify_fake_skip_entries.py --db-path /path/to/telemetry.db --dry-run
        """,
    )

    parser.add_argument(
        "--db-path",
        type=str,
        help="Path to telemetry SQLite database (default: auto-detect)",
    )

    parser.add_argument(
        "--cutoff-date",
        type=str,
        default="2026-01-11T00:00:00",
        help="ISO 8601 cutoff date for detection (default: 2026-01-11T00:00:00)",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry run mode - identify fake entries without exporting (default)",
    )

    parser.add_argument(
        "--export",
        type=str,
        metavar="FILE",
        help="Export fake entries to JSON file",
    )

    parser.add_argument(
        "--count",
        action="store_true",
        help="Only print count of fake entries (no details)",
    )

    args = parser.parse_args()

    # Default to dry-run if no export specified
    if not args.export and not args.dry_run and not args.count:
        args.dry_run = True

    try:
        # Initialize detector
        detector = FakeEntryDetector(
            db_path=args.db_path,
            cutoff_date=args.cutoff_date,
        )

        # Connect to database
        detector.connect()

        # Detect fake entries
        print(f"🔍 Detecting fake skip entries (cutoff: {args.cutoff_date})...")
        fake_entries = detector.detect_fake_entries()

        # Handle output modes
        if args.count:
            print(f"\n✅ Total fake entries detected: {len(fake_entries)}")
        elif args.export:
            detector.export_to_json(fake_entries, args.export)
            print(f"\n✅ Export complete. Event IDs saved to: {args.export}")
        else:  # dry-run
            detector.print_summary(fake_entries)

        # Disconnect
        detector.disconnect()

        # Exit with appropriate code
        sys.exit(0 if len(fake_entries) == 0 else 1)

    except KeyboardInterrupt:
        print("\n⚠️  Interrupted by user", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
