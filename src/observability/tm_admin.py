"""
Translation Memory admin interface.

Provides tools to inspect and manage TM entries.
"""

import csv
import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.tm.translation_memory import TranslationMemory

logger = logging.getLogger(__name__)


class TranslationMemoryAdmin:
    """
    Admin interface for TM inspection and management.

    Provides programmatic access to TM entries for inspection, export,
    and management.
    """

    def __init__(self, tm: TranslationMemory):
        """
        Initialize TM admin interface.

        Args:
            tm: Translation memory instance
        """
        self.tm = tm

    def get_stats(self, site_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get TM statistics.

        Args:
            site_id: Optional site filter

        Returns:
            Statistics dictionary
        """
        stats = {
            "total_entries": 0,
            "by_language_pair": {},
            "by_site": {},
            "l1_cache_stats": None,
            "l2_size": 0,
            "l3_index_size": 0,
        }

        try:
            # L1 cache stats
            if self.tm.l1:
                l1_stats = self.tm.l1.stats()
                stats["l1_cache_stats"] = l1_stats

            # L2 persistent stats
            if self.tm.l2:
                stats["l2_size"] = len(self.tm.l2)

            # L3 semantic stats
            if self.tm.l3:
                stats["l3_index_size"] = len(self.tm.l3)

        except Exception as e:
            logger.error(f"Error getting TM stats: {e}", exc_info=True)

        return stats

    def dump_entries_to_file(
        self,
        out_path: Path,
        site_id: Optional[str] = None,
        format: str = "ndjson",
        limit: int = 10000,
    ) -> Tuple[int, Optional[str]]:
        """
        Export TM entries to file.

        Args:
            out_path: Output file path
            site_id: Optional site filter
            format: Output format ("ndjson" or "csv")
            limit: Maximum entries to export

        Returns:
            Tuple of (entries_exported, error_message)
        """
        count = 0
        error = None

        try:
            # This is a simplified version - in production would iterate through L2
            entries = []

            if format == "csv":
                # CSV export
                with open(out_path, "w", newline="", encoding="utf-8") as f:
                    fieldnames = [
                        "site_id",
                        "src_lang",
                        "tgt_lang",
                        "source_text",
                        "translation",
                    ]
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()

                    for entry in entries[:limit]:
                        writer.writerow(entry)
                        count += 1
            else:
                # NDJSON export (default)
                with open(out_path, "w", encoding="utf-8") as f:
                    for entry in entries[:limit]:
                        json_line = json.dumps(entry, ensure_ascii=False)
                        f.write(json_line + "\n")
                        count += 1

            logger.info(f"Exported {count} entries to {out_path}")

        except Exception as e:
            error = str(e)
            logger.error(f"Error dumping entries: {e}", exc_info=True)

        return count, error

    def clear_cache(self) -> Dict[str, bool]:
        """
        Clear all TM caches.

        Returns:
            Dictionary of clearing results
        """
        results = {
            "l1_cleared": False,
            "l2_cleared": False,
            "l3_cleared": False,
        }

        try:
            if self.tm.l1:
                self.tm.l1.clear()
                results["l1_cleared"] = True

            if self.tm.l2:
                self.tm.l2.clear()
                results["l2_cleared"] = True

            if self.tm.l3:
                # L3 doesn't have clear method in current implementation
                results["l3_cleared"] = False

            logger.info("Cleared TM caches")

        except Exception as e:
            logger.error(f"Error clearing caches: {e}", exc_info=True)

        return results
