#!/usr/bin/env python3
"""
L2 TM Cache Contamination Auditor

Scans the L2 LMDB translation memory for entries where the stored translation
text is detected as a different language than the entry's declared target language.
These "poisoned" entries (P0-C defect) cause future cache hits to return English
(or other wrong-language) text, which then appears directly in translated output.

Usage:
    python scripts/audit_l2_cache_contamination.py [options]

    --dry-run         Report contaminated entries without deleting (default)
    --repair          Delete contaminated entries from L2 (irreversible)
    --lang LANG       Audit only one target language (e.g. --lang de)
    --output PATH     Write JSON report of contaminated entry keys
    --db PATH         L2 LMDB path (default: data/tm/l2.lmdb)
    --model PATH      FastText model path (default: data/models/fasttext/lid.176.bin)
    --confidence F    Detection confidence threshold (default: 0.80)
    --batch N         Process N entries before logging progress (default: 5000)

Task: TC-MLD-02 (harmonic-snacking-kernighan)
"""

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


@dataclass
class ContaminatedEntry:
    """Record of a single contaminated L2 entry."""

    lmdb_key: str
    site_id: str
    src_lang: str
    tgt_lang: str
    declared_tgt_lang: str
    detected_lang: str
    detection_confidence: float
    translation_preview: str  # first 80 chars of translation


@dataclass
class AuditReport:
    """Summary of the L2 contamination audit."""

    audit_timestamp: str
    db_path: str
    total_entries_scanned: int
    entries_skipped_short: int
    entries_skipped_detection_error: int
    contaminated_count: int
    repaired_count: int
    lang_filter: str | None
    contaminated: list[ContaminatedEntry] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "audit_timestamp": self.audit_timestamp,
            "db_path": self.db_path,
            "total_entries_scanned": self.total_entries_scanned,
            "entries_skipped_short": self.entries_skipped_short,
            "entries_skipped_detection_error": self.entries_skipped_detection_error,
            "contaminated_count": self.contaminated_count,
            "repaired_count": self.repaired_count,
            "lang_filter": self.lang_filter,
            "contaminated": [
                {
                    "lmdb_key": e.lmdb_key,
                    "site_id": e.site_id,
                    "src_lang": e.src_lang,
                    "tgt_lang": e.tgt_lang,
                    "detected_lang": e.detected_lang,
                    "detection_confidence": round(e.detection_confidence, 4),
                    "translation_preview": e.translation_preview,
                }
                for e in self.contaminated
            ],
        }


# Languages whose scripts are visually similar — don't flag these as contaminated
# (mirrors similarity_tracker.py baseline_groups)
_SIMILAR_LANG_GROUPS: list[set[str]] = [
    {"hr", "sr", "bs", "sl", "sh"},  # south slavic
    {"ms", "id"},  # malay-indonesian
    {"cs", "sk"},  # west slavic
    {"ca", "es", "pt", "fr", "it", "ro", "gl"},  # romance
    {"bg", "ru", "uk", "mk", "sr", "be"},  # cyrillic
    {"ar", "fa", "ur", "ps"},  # arabic-script
    {"hi", "mr", "ne", "sa"},  # devanagari
    {"da", "no", "nb", "sv", "is"},  # nordic
    {"zh", "zh-cn", "zh-tw", "zh-hk"},  # chinese variants
]


def _are_similar(lang1: str, lang2: str) -> bool:
    for group in _SIMILAR_LANG_GROUPS:
        if lang1 in group and lang2 in group:
            return True
    return False


def _load_fasttext(model_path: Path):
    """Load FastText lid model, return model or None on failure."""
    try:
        import fasttext

        model = fasttext.load_model(str(model_path))
        logger.info(f"FastText model loaded: {model_path}")
        return model
    except Exception as e:
        logger.error(f"Failed to load FastText model at {model_path}: {e}")
        return None


def _detect_lang(model, text: str) -> tuple[str, float]:
    """Return (lang_code, confidence) for text, or ('', 0.0) on failure."""
    try:
        labels, probs = model.predict(text.replace("\n", " "), k=1)
        lang = labels[0].replace("__label__", "")
        conf = float(probs[0])
        return lang, conf
    except Exception:
        return "", 0.0


def _clean_for_detection(text: str) -> str:
    """Strip technical identifiers to reduce false positives."""
    import re

    # Remove code fences
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"`[^`]+`", " ", text)
    # Remove URLs
    text = re.sub(r"https?://\S+", " ", text)
    # Remove Aspose product names and PascalCase identifiers
    text = re.sub(r"Aspose\.[A-Z]\w+", " ", text)
    text = re.sub(r"\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b", " ", text)
    # Remove ALL-CAPS acronyms 2-8 chars
    text = re.sub(r"\b[A-Z]{2,8}\b", " ", text)
    # Remove API call patterns like ClassName.methodName()
    text = re.sub(r"\b[A-Z]\w+\.[a-zA-Z]\w+\(?[^)]*\)?", " ", text)
    return text.strip()


def run_audit(
    db_path: Path,
    model_path: Path,
    lang_filter: str | None,
    confidence_threshold: float,
    repair: bool,
    dry_run: bool,
    batch_size: int,
) -> AuditReport:
    """
    Iterate L2 LMDB and identify entries with wrong-language translations.

    Returns an AuditReport with all contaminated entries found.
    If repair=True and dry_run=False, deletes contaminated entries.
    """
    import json as _json

    import lmdb

    model = _load_fasttext(model_path)
    if model is None:
        logger.error("Cannot proceed without FastText model. Aborting.")
        sys.exit(1)

    report = AuditReport(
        audit_timestamp=datetime.now(timezone.utc).isoformat(),
        db_path=str(db_path),
        total_entries_scanned=0,
        entries_skipped_short=0,
        entries_skipped_detection_error=0,
        contaminated_count=0,
        repaired_count=0,
        lang_filter=lang_filter,
    )

    # Keys to delete in repair mode (collected first, deleted in a second pass)
    keys_to_delete: list[bytes] = []

    _readonly = not repair or dry_run
    # On Windows, opening writable after a readonly open in the same session can fail with
    # ERROR_USER_MAPPED_FILE. Use lock=False to work around this OS-level restriction.
    env = lmdb.open(str(db_path), readonly=_readonly, max_dbs=1, lock=not repair)

    start_time = time.time()

    try:
        with env.begin() as txn:
            cursor = txn.cursor()
            for raw_key, raw_value in cursor:
                report.total_entries_scanned += 1

                # Progress logging
                if report.total_entries_scanned % batch_size == 0:
                    elapsed = time.time() - start_time
                    rate = report.total_entries_scanned / max(elapsed, 0.001)
                    logger.info(
                        f"Progress: {report.total_entries_scanned:,} scanned | "
                        f"{report.contaminated_count} contaminated | "
                        f"{rate:.0f} entries/sec"
                    )

                try:
                    entry_dict = _json.loads(raw_value.decode("utf-8"))
                    tgt_lang = entry_dict.get("tgt_lang", "")
                    translation = entry_dict.get("translation", "")
                    site_id = entry_dict.get("site_id", "")
                    src_lang = entry_dict.get("src_lang", "")
                except Exception:
                    continue  # Skip malformed entries

                # Apply language filter
                if lang_filter and tgt_lang != lang_filter:
                    continue

                # Skip English target lang — we're looking for non-EN files with EN content
                if tgt_lang == "en":
                    continue

                # Skip very short translations (not enough signal)
                cleaned = _clean_for_detection(translation)
                if len(cleaned) < 20:
                    report.entries_skipped_short += 1
                    continue

                # Detect language of translation
                detected_lang, conf = _detect_lang(model, cleaned)
                if not detected_lang or conf == 0.0:
                    report.entries_skipped_detection_error += 1
                    continue

                # Check if detected language matches declared target language
                if detected_lang == tgt_lang:
                    continue  # Clean entry

                if conf < confidence_threshold:
                    continue  # Not confident enough to flag

                if _are_similar(tgt_lang, detected_lang):
                    continue  # Similar language group — not contamination

                # This entry is contaminated: translation is in wrong language
                report.contaminated_count += 1
                entry = ContaminatedEntry(
                    lmdb_key=raw_key.decode("utf-8", errors="replace"),
                    site_id=site_id,
                    src_lang=src_lang,
                    tgt_lang=tgt_lang,
                    declared_tgt_lang=tgt_lang,
                    detected_lang=detected_lang,
                    detection_confidence=conf,
                    translation_preview=translation[:80],
                )
                report.contaminated.append(entry)

                if repair and not dry_run:
                    keys_to_delete.append(raw_key)

    finally:
        env.close()

    # Second pass: delete contaminated entries
    if repair and not dry_run and keys_to_delete:
        logger.info(f"Deleting {len(keys_to_delete)} contaminated entries from L2...")
        # TC-MLD-05: set map_size to 2 GiB so delete transactions don't hit MDB_MAP_FULL
        # on a ~921 MiB database (default map_size is 10 MiB which is too small for writes)
        env = lmdb.open(str(db_path), readonly=False, max_dbs=1, map_size=2 * 1024**3)
        try:
            with env.begin(write=True) as txn:
                for key in keys_to_delete:
                    txn.delete(key)
                    report.repaired_count += 1
        finally:
            env.close()
        logger.info(f"Deleted {report.repaired_count} entries.")

    elapsed = time.time() - start_time
    logger.info(
        f"\nAudit complete in {elapsed:.1f}s: "
        f"{report.total_entries_scanned:,} scanned, "
        f"{report.contaminated_count} contaminated"
        + (f", {report.repaired_count} deleted" if repair and not dry_run else "")
    )
    return report


def main():
    parser = argparse.ArgumentParser(
        description="Audit L2 TM cache for wrong-language translation entries (TC-MLD-02)"
    )
    parser.add_argument(
        "--db", default="data/tm/l2.lmdb", help="L2 LMDB path (default: data/tm/l2.lmdb)"
    )
    parser.add_argument(
        "--model", default="data/models/fasttext/lid.176.bin", help="FastText language model path"
    )
    parser.add_argument(
        "--lang", default=None, help="Audit only this target language (e.g. --lang de)"
    )
    parser.add_argument(
        "--confidence",
        type=float,
        default=0.80,
        help="Detection confidence threshold (default: 0.80)",
    )
    parser.add_argument(
        "--repair", action="store_true", help="Delete contaminated entries (default: report only)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Report only, do not modify DB (default: True; use --repair to delete)",
    )
    parser.add_argument("--output", default=None, help="Write JSON report to this path")
    parser.add_argument(
        "--batch", type=int, default=5000, help="Progress log interval in entries (default: 5000)"
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        logger.error(f"L2 LMDB not found at {db_path}. Run from hugo-translator root.")
        sys.exit(1)

    model_path = Path(args.model)
    if not model_path.exists():
        logger.error(f"FastText model not found at {model_path}.")
        sys.exit(1)

    dry_run = not args.repair  # repair flag overrides dry-run default

    logger.info(
        f"L2 Contamination Audit — db={db_path}, lang={args.lang or 'all'}, "
        f"confidence>={args.confidence}, "
        f"mode={'DRY-RUN' if dry_run else 'REPAIR (will delete entries)'}"
    )
    if not dry_run:
        logger.warning("REPAIR mode active — contaminated L2 entries WILL be deleted.")
        logger.warning("This is IRREVERSIBLE. The entries will be rebuilt on next translation run.")

    report = run_audit(
        db_path=db_path,
        model_path=model_path,
        lang_filter=args.lang,
        confidence_threshold=args.confidence,
        repair=args.repair,
        dry_run=dry_run,
        batch_size=args.batch,
    )

    # Print summary
    print(f"\n{'=' * 60}")
    print("L2 Cache Contamination Audit Report")
    print(f"{'=' * 60}")
    print(f"Timestamp:         {report.audit_timestamp}")
    print(f"DB path:           {report.db_path}")
    print(f"Lang filter:       {report.lang_filter or 'all'}")
    print(f"Entries scanned:   {report.total_entries_scanned:,}")
    print(f"Skipped (short):   {report.entries_skipped_short:,}")
    print(f"Skipped (error):   {report.entries_skipped_detection_error:,}")
    print(f"Contaminated:      {report.contaminated_count:,}")
    if report.repaired_count:
        print(f"Deleted (repair):  {report.repaired_count:,}")

    if report.contaminated:
        print("\nSample contaminated entries (first 10):")
        for entry in report.contaminated[:10]:
            preview = entry.translation_preview.encode("ascii", errors="replace").decode("ascii")
            print(
                f"  [{entry.site_id}] {entry.src_lang}->{entry.tgt_lang} "
                f"detected={entry.detected_lang} ({entry.detection_confidence:.0%}): "
                f"{preview!r:.60}"
            )

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"\nReport written to: {args.output}")

    if report.contaminated_count > 0 and dry_run:
        print("\nTo delete contaminated entries, re-run with --repair:")
        print(
            "  python scripts/audit_l2_cache_contamination.py --repair"
            + (f" --lang {args.lang}" if args.lang else "")
        )
        sys.exit(0)  # Not an error — just informational

    sys.exit(0)


if __name__ == "__main__":
    main()
