#!/usr/bin/env python3
"""
Force Retranslation of Contaminated Files

Takes an inventory JSON produced by scan_language_contamination.py (--json-output)
and queues all contaminated files for forced retranslation on the next worker run.

Optionally deletes the contaminated output files so that the worker's mtime-based
completion filter does not skip them.

Usage:
    python scripts/force_retranslate_contaminated.py --inventory PATH [options]

    --inventory PATH    Required. JSON from scan_language_contamination.py --json-output
    --site SITE_ID      Filter to one site profile
    --lang LANG         Filter to one target language (e.g. --lang de)
    --threshold FLOAT   Only process files below this purity % (default: 0.95)
    --delete-outputs    Delete contaminated output files (enables completion filter bypass)
    --dry-run           Print what would happen without doing it

After running this script, start the content worker to retranslate queued files:
    python -m src.workers.autonomous_content_translation_worker --mode oneshot --site <site>

IMPORTANT: Run scripts/audit_l2_cache_contamination.py --repair first to purge any
wrong-language L2 TM entries, so retranslated files are not immediately re-poisoned
from cache.

Task: TC-MLD-04 (harmonic-snacking-kernighan)
"""

import argparse
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _load_inventory(inventory_path: Path) -> list[dict]:
    """Load and validate the JSON inventory from the contamination scanner."""
    try:
        data = json.loads(inventory_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"Failed to read inventory: {e}")
        sys.exit(1)

    files = data.get("files", [])
    if not files:
        logger.warning("Inventory has no file entries. Nothing to process.")
    return files


def _already_queued_paths() -> set[str]:
    """Load currently queued paths from retranslate queue for idempotency check."""
    try:
        # Import here so script can run without full src package in path
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from src.tm.retranslate_queue import load_queued_paths

        return load_queued_paths()
    except Exception as e:
        logger.warning(
            f"Could not load existing retranslate queue: {e}. Skipping idempotency check."
        )
        return set()


def _add_to_queue(output_path: Path, tgt_lang: str, dry_run: bool) -> bool:
    """Add path to retranslate queue. Returns True if added, False if already queued."""
    try:
        from src.tm.retranslate_queue import add_to_queue

        if dry_run:
            return True
        add_to_queue(output_path, tgt_lang)
        return True
    except Exception as e:
        logger.error(f"Failed to queue {output_path}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Queue contaminated translated files for force retranslation (TC-MLD-04)"
    )
    parser.add_argument(
        "--inventory",
        required=True,
        help="JSON inventory from scan_language_contamination.py --json-output",
    )
    parser.add_argument(
        "--site", default=None, help="Filter to one site_id (e.g. --site blog.aspose.net)"
    )
    parser.add_argument(
        "--lang", default=None, help="Filter to one target language (e.g. --lang de)"
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.95,
        help="Process files with purity_percentage < this value (default: 0.95 = 95%%)",
    )
    parser.add_argument(
        "--delete-outputs",
        action="store_true",
        help="Delete contaminated output files (bypasses mtime completion filter on next run)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print what would happen without making any changes"
    )
    args = parser.parse_args()

    inventory_path = Path(args.inventory)
    if not inventory_path.exists():
        logger.error(f"Inventory file not found: {inventory_path}")
        sys.exit(1)

    # Add project root to sys.path so src.tm.retranslate_queue is importable
    project_root = Path(__file__).parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    logger.info(f"Loading inventory: {inventory_path}")
    all_files = _load_inventory(inventory_path)
    logger.info(f"Inventory: {len(all_files)} total files")

    # Apply filters — include files that either:
    #   (a) have purity below threshold, OR
    #   (b) have script_mixing issues (purity=100% in fast-mode scans)
    filtered = []
    for record in all_files:
        purity = record.get("purity_percentage", 100.0)
        site_id = record.get("site_id", "")
        tgt_lang = record.get("target_lang", "")
        script_mixing = record.get("script_mixing", [])

        # Normalise: if purity > 1.0 assume it's already a 0-100 percentage
        purity_frac = purity / 100.0 if purity > 1.0 else purity
        has_quality_issue = (purity_frac < args.threshold) or bool(script_mixing)
        if not has_quality_issue:
            continue
        if args.site and site_id != args.site:
            continue
        if args.lang and tgt_lang != args.lang:
            continue
        filtered.append(record)

    candidates = filtered
    logger.info(
        f"Filtered to {len(candidates)} files (purity < {args.threshold:.0%} or script mixing)"
        + (f" in site={args.site}" if args.site else "")
        + (f", lang={args.lang}" if args.lang else "")
    )

    if not candidates:
        logger.info("No files to process. Exiting.")
        sys.exit(0)

    if args.dry_run:
        logger.info("[DRY-RUN] No changes will be made.")

    # Load already-queued paths for idempotency
    already_queued = _already_queued_paths()
    logger.info(f"Existing retranslate queue: {len(already_queued)} entries")

    n_queued = 0
    n_already_queued = 0
    n_deleted = 0
    n_missing = 0
    n_failed = 0

    for record in candidates:
        file_path = record.get("file_path", "")
        tgt_lang = record.get("target_lang", "")
        purity = record.get("purity_percentage", 0.0)

        if not file_path or not tgt_lang:
            n_failed += 1
            continue

        output_path = Path(file_path)

        if not output_path.exists():
            logger.debug(f"File no longer exists (already cleaned?): {output_path}")
            n_missing += 1
            continue

        # Idempotency: skip if already queued
        path_str = str(output_path)
        if path_str in already_queued:
            logger.debug(f"Already in queue, skipping: {output_path.name}")
            n_already_queued += 1
            continue

        # Queue for retranslation
        if args.dry_run:
            logger.info(
                f"[DRY-RUN] Would queue: {output_path.name} ({tgt_lang}, purity={purity:.1f}%)"
            )
        else:
            success = _add_to_queue(output_path, tgt_lang, dry_run=False)
            if success:
                n_queued += 1
                logger.debug(f"Queued: {output_path.name} ({tgt_lang})")
            else:
                n_failed += 1
                continue

        # Optionally delete output file to bypass mtime completion filter
        if args.delete_outputs:
            if args.dry_run:
                logger.info(f"[DRY-RUN] Would delete: {output_path}")
            else:
                try:
                    output_path.unlink()
                    n_deleted += 1
                    logger.debug(f"Deleted: {output_path}")
                except OSError as e:
                    logger.warning(f"Could not delete {output_path}: {e}")

    # Summary
    print(f"\n{'=' * 60}")
    print("Force Retranslate — Summary")
    print(f"{'=' * 60}")
    print(f"Candidates:         {len(candidates)}")
    if args.dry_run:
        print("(DRY-RUN — no changes made)")
    else:
        print(f"Queued:             {n_queued}")
        print(f"Already queued:     {n_already_queued}")
        print(f"File missing:       {n_missing}")
        print(
            f"Deleted:            {n_deleted}"
            + (" (--delete-outputs)" if args.delete_outputs else "")
        )
        print(f"Errors:             {n_failed}")

    if not args.dry_run and n_queued > 0:
        print("\nNext step: Run the content worker to retranslate queued files.")
        print(
            "  python -m src.workers.autonomous_content_translation_worker --mode oneshot --site <site>"
        )
        print("\nRecommendation: Run L2 cache audit first if not already done:")
        print("  python scripts/audit_l2_cache_contamination.py --repair")

    sys.exit(0)


if __name__ == "__main__":
    main()
