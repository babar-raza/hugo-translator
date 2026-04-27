"""
TM Consistency Warner — detects diverging translations for the same source phrase.

After each TM improvement run, scans the L2 persistent store for source phrases
that have been translated differently across sites. Divergences are logged to
data/logs/consistency_divergences.jsonl for operator review. Non-blocking.

Gate: config/global.yaml → tm_improvement.consistency_check_enabled: true
"""

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .l2_persistent import L2PersistentTM

logger = logging.getLogger(__name__)

_DIVERGENCE_LOG = Path("data/logs/consistency_divergences.jsonl")
# Only report source phrases longer than this to avoid noise from short snippets
_MIN_SOURCE_LEN = 30
# Cap on records written per run to prevent log explosion on large TM stores
_MAX_RECORDS_PER_RUN = 500


def _edit_distance(a: str, b: str) -> int:
    """Compute Levenshtein edit distance between two strings (capped at 200 chars each)."""
    a, b = a[:200], b[:200]
    if a == b:
        return 0
    m, n = len(a), len(b)
    prev = list(range(n + 1))
    for i in range(1, m + 1):
        curr = [i] + [0] * n
        for j in range(1, n + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[n]


class ConsistencyWarner:
    """
    Scans L2 for source phrases with >1 distinct translation across sites.

    Uses export_all() to iterate entries, groups by (src_lang, tgt_lang, source_text),
    then reports groups where the same phrase was translated differently on different
    sites. Results are appended to data/logs/consistency_divergences.jsonl.

    Non-blocking — all exceptions are caught and logged as warnings.
    """

    def __init__(self, l2: "L2PersistentTM"):
        self.l2 = l2

    def run(self, run_id: str | None = None) -> dict:
        """
        Execute a consistency check across all L2 entries.

        Args:
            run_id: Optional identifier for the triggering improvement run.

        Returns:
            Summary dict: {divergent_phrases, records_written, elapsed_seconds}
        """
        import time
        start = time.monotonic()

        try:
            return self._run_inner(run_id)
        except Exception as e:
            logger.warning("ConsistencyWarner: unexpected error (non-fatal): %s", e)
            return {"divergent_phrases": 0, "records_written": 0, "elapsed_seconds": 0.0}

    def _run_inner(self, run_id: str | None) -> dict:
        import time
        start = time.monotonic()

        logger.info("ConsistencyWarner: scanning L2 for translation divergences...")

        # Export all L2 entries (read-only scan)
        try:
            entries = self.l2.export_all()
        except Exception as e:
            logger.warning("ConsistencyWarner: export_all failed: %s", e)
            return {"divergent_phrases": 0, "records_written": 0, "elapsed_seconds": 0.0}

        if not entries:
            logger.info("ConsistencyWarner: L2 is empty — nothing to check")
            return {"divergent_phrases": 0, "records_written": 0, "elapsed_seconds": 0.0}

        # Group by (src_lang, tgt_lang, normalized_source_text)
        # Each value is a list of (site_id, translation) pairs
        groups: dict[tuple, list[tuple[str, str]]] = defaultdict(list)
        for entry in entries:
            src = (entry.source_text or "").strip()
            if len(src) < _MIN_SOURCE_LEN:
                continue
            key = (entry.src_lang, entry.tgt_lang, src)
            groups[key].append((entry.site_id, entry.translation or ""))

        # Find groups with >1 distinct translation
        records: list[dict] = []
        for (src_lang, tgt_lang, source_text), site_translations in groups.items():
            distinct = {}
            for site_id, translation in site_translations:
                normalized_tr = translation.strip()
                if normalized_tr not in distinct:
                    distinct[normalized_tr] = site_id

            if len(distinct) <= 1:
                continue  # All sites agree

            # Build sorted list for deterministic output
            translations_list = sorted(distinct.keys())
            # Compute edit distance between first two distinct translations
            ed = _edit_distance(translations_list[0], translations_list[1])
            ed_ratio = ed / max(len(translations_list[0]), len(translations_list[1]), 1)

            record = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "run_id": run_id,
                "src_lang": src_lang,
                "tgt_lang": tgt_lang,
                "source_preview": source_text[:120],
                "distinct_translation_count": len(distinct),
                "translation_previews": [t[:120] for t in translations_list[:3]],
                "edit_distance": ed,
                "edit_distance_ratio": round(ed_ratio, 3),
                "sites": list(distinct.values()),
            }
            records.append(record)

            if len(records) >= _MAX_RECORDS_PER_RUN:
                logger.info(
                    "ConsistencyWarner: capped at %d records per run", _MAX_RECORDS_PER_RUN
                )
                break

        records_written = self._append_records(records)
        elapsed = time.monotonic() - start

        if records:
            logger.warning(
                "ConsistencyWarner: found %d divergent phrase(s) across sites "
                "(%d records written to %s in %.1fs)",
                len(records),
                records_written,
                _DIVERGENCE_LOG,
                elapsed,
            )
        else:
            logger.info(
                "ConsistencyWarner: no divergences found in %d entries (%.1fs)",
                len(entries),
                elapsed,
            )

        return {
            "divergent_phrases": len(records),
            "records_written": records_written,
            "elapsed_seconds": round(elapsed, 2),
        }

    def _append_records(self, records: list[dict]) -> int:
        """Atomically append records to the divergence log. Returns count written."""
        if not records:
            return 0
        try:
            _DIVERGENCE_LOG.parent.mkdir(parents=True, exist_ok=True)
            lines = "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n"
            # Atomic append via temp file → rename is not possible for append;
            # use direct append which is safe for single-writer scenarios.
            with _DIVERGENCE_LOG.open("a", encoding="utf-8") as f:
                f.write(lines)
            return len(records)
        except Exception as e:
            logger.warning("ConsistencyWarner: failed to write divergence log: %s", e)
            return 0


def run_consistency_check(l2: "L2PersistentTM", run_id: str | None = None) -> dict:
    """
    Top-level convenience function — gate-checked wrapper around ConsistencyWarner.

    Reads `tm_improvement.consistency_check_enabled` from global config. Returns
    an empty summary dict immediately if the gate is disabled or config is unavailable.

    Args:
        l2: L2 persistent TM instance to scan.
        run_id: Optional run identifier for correlation.

    Returns:
        Summary dict from ConsistencyWarner.run(), or empty dict if gated off.
    """
    try:
        from src.utils.config_loader import get_global_config
        cfg = get_global_config()
        enabled = cfg.get("tm_improvement", {}).get("consistency_check_enabled", False)
        if not enabled:
            return {}
    except Exception:
        return {}

    return ConsistencyWarner(l2).run(run_id=run_id)
