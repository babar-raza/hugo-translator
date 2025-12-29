#!/usr/bin/env python3
"""
Check Translation Memory for corrupted entries.

This script checks if the corrupted translations were stored in TM
and are being served back instead of being freshly translated.
"""

import sys
import sqlite3
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def check_tm_contamination():
    """Check TM databases for contamination markers."""
    print("="*80)
    print("TRANSLATION MEMORY CONTAMINATION CHECK")
    print("="*80)

    # Find TM databases
    tm_dirs = [
        Path("work") / "tm",
        Path("tm"),
        Path(".") / "tm"
    ]

    db_files = []
    for tm_dir in tm_dirs:
        if tm_dir.exists():
            db_files.extend(tm_dir.glob("**/*.db"))

    if not db_files:
        print("\n✓ No TM database files found")
        print("  TM contamination is not the issue")
        return

    print(f"\n[1/3] Found {len(db_files)} TM database files:")
    for db_file in db_files:
        print(f"  - {db_file}")

    print("\n[2/3] Checking for contamination markers...")
    print("       Looking for: Zkouška, Übersetzer, ΠΡΟΣΟΧΗ, Arxius, تخزين\n")

    contamination_markers = [
        'Zkouška',
        'Übersetzer',
        'ΠΡΟΣΟΧΗ',
        'ΔΗΜΙΟΥΡΓΙΑ',
        'Arxius',
        "l'Orqu",
        'تخزين',
        'واسترداد'
    ]

    total_contaminated = 0
    contaminated_dbs = []

    for db_file in db_files:
        try:
            conn = sqlite3.connect(db_file)
            cursor = conn.cursor()

            # Get table names
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]

            db_contaminated = False
            db_contamination_count = 0

            for table in tables:
                # Get column names
                cursor.execute(f"PRAGMA table_info({table})")
                columns = [row[1] for row in cursor.fetchall()]

                # Look for text columns
                text_columns = [col for col in columns if 'text' in col.lower() or 'translation' in col.lower() or 'target' in col.lower()]

                for col in text_columns:
                    for marker in contamination_markers:
                        try:
                            query = f"SELECT COUNT(*) FROM {table} WHERE {col} LIKE ?"
                            cursor.execute(query, (f'%{marker}%',))
                            count = cursor.fetchone()[0]

                            if count > 0:
                                print(f"  ✗ {db_file.name:30s} | {table:20s} | {col:20s} | {marker:15s} | {count:5d} entries")
                                db_contaminated = True
                                db_contamination_count += count
                        except sqlite3.OperationalError:
                            # Column might not exist or query syntax issue
                            pass

            if db_contaminated:
                contaminated_dbs.append((db_file, db_contamination_count))
                total_contaminated += db_contamination_count

            conn.close()

        except Exception as e:
            print(f"  ⚠ Error reading {db_file}: {e}")

    print(f"\n[3/3] Results:")
    print("="*80)

    if total_contaminated > 0:
        print(f"\n✗ TM CONTAMINATION DETECTED!")
        print(f"\n  Total contaminated entries: {total_contaminated}")
        print(f"  Contaminated databases: {len(contaminated_dbs)}")
        print("\n  Affected databases:")
        for db_file, count in contaminated_dbs:
            print(f"    - {db_file}: {count} entries")

        print("\n  DIAGNOSIS:")
        print("    The corrupted translations were saved to TM and are being")
        print("    served back instead of fresh translations.")

        print("\n  FIX:")
        print("    1. Backup TM databases (just in case):")
        for db_file, _ in contaminated_dbs:
            print(f"       cp {db_file} {db_file}.backup")

        print("\n    2. Option A: Delete contaminated entries")
        print("       (Safer - only removes bad entries)")
        print("       python scripts/clean_tm_contamination.py")

        print("\n    3. Option B: Delete entire TM and rebuild")
        print("       (Nuclear option - loses all TM data)")
        for db_file, _ in contaminated_dbs:
            print(f"       rm {db_file}")

        print("\n    4. Re-translate files to rebuild TM with clean data")

    else:
        print("\n✓ No TM contamination detected")
        print("\n  The TM databases do not contain corrupted translations.")
        print("  The issue is likely in the live translation process.")


if __name__ == "__main__":
    check_tm_contamination()
