"""Cache integrity verification for Translation Memory.

This module provides integrity checking capabilities for the LMDB-based L2 cache,
including detection of corrupted entries and optional auto-repair.

Implementation follows TM-01 from the TM cache integrity plan.

WS-COMP-5 extension: scan_language_validity() detects and optionally removes L2 entries
where the cached translation is in the wrong language (stale wrong-language entries from
early M2M100 runs that can propagate bad translations to new files via cache hits).
"""

import json
import logging
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .l2_persistent import L2PersistentTM

logger = logging.getLogger(__name__)


class IntegrityError(Exception):
    """Raised when cache integrity verification fails critically."""
    pass


@dataclass
class IntegrityReport:
    """Results from cache integrity verification."""
    total_scanned: int
    valid_count: int
    corrupt_count: int
    repaired_count: int
    corrupt_keys: list[bytes] = field(default_factory=list)
    errors: list[tuple[bytes, str]] = field(default_factory=list)

    @property
    def health_percentage(self) -> float:
        """Calculate cache health as percentage."""
        if self.total_scanned == 0:
            return 100.0
        return (self.valid_count / self.total_scanned) * 100.0

    @property
    def is_healthy(self) -> bool:
        """Check if cache is healthy (no corrupted entries)."""
        return self.corrupt_count == 0

    def __str__(self) -> str:
        return (
            f"IntegrityReport(scanned={self.total_scanned}, "
            f"valid={self.valid_count}, corrupt={self.corrupt_count}, "
            f"repaired={self.repaired_count}, health={self.health_percentage:.1f}%)"
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "total_scanned": self.total_scanned,
            "valid_count": self.valid_count,
            "corrupt_count": self.corrupt_count,
            "repaired_count": self.repaired_count,
            "health_percentage": round(self.health_percentage, 2),
            "is_healthy": self.is_healthy,
            "error_count": len(self.errors),
            "errors": [
                {"key": key[:50].hex() if key else "", "message": msg}
                for key, msg in self.errors[:10]  # Limit to first 10 errors
            ]
        }


@dataclass
class LanguageValidityReport:
    """Results from TM language validity scan (WS-COMP-5)."""
    tgt_lang: str
    total_entries: int       # Total entries for this tgt_lang in L2
    total_sampled: int       # Entries actually checked (sample_rate % of total)
    stale_found: int         # Entries where detected lang != tgt_lang
    repaired_count: int      # Entries deleted (if repair=True)
    stale_entries: list[dict] = field(default_factory=list)  # {key_hex, translation_snippet, detected_lang, confidence}

    @property
    def stale_rate(self) -> float:
        if self.total_sampled == 0:
            return 0.0
        return self.stale_found / self.total_sampled

    def __str__(self) -> str:
        return (
            f"LanguageValidityReport(lang={self.tgt_lang}, entries={self.total_entries}, "
            f"sampled={self.total_sampled}, stale={self.stale_found} "
            f"({self.stale_rate * 100:.1f}%), repaired={self.repaired_count})"
        )

    def to_dict(self) -> dict:
        return {
            "tgt_lang": self.tgt_lang,
            "total_entries": self.total_entries,
            "total_sampled": self.total_sampled,
            "stale_found": self.stale_found,
            "stale_rate_pct": round(self.stale_rate * 100, 2),
            "repaired_count": self.repaired_count,
            "stale_entries": self.stale_entries[:20],  # Cap for JSON output
        }


class CacheIntegrityChecker:
    """
    Verify and repair LMDB cache integrity.

    Scans all entries in the L2 cache and validates:
    1. Valid UTF-8 encoding
    2. Valid JSON structure
    3. Required fields present (source_text, translation, site_id, src_lang, tgt_lang)
    4. Non-empty values for required fields
    5. Valid ISO language codes (2-letter codes)
    """

    # Required fields for a valid translation entry
    REQUIRED_FIELDS = ['source_text', 'translation', 'site_id', 'src_lang', 'tgt_lang']

    # Valid 2-letter ISO 639-1 language codes (common ones)
    VALID_LANG_CODES = {
        'aa', 'ab', 'ae', 'af', 'ak', 'am', 'an', 'ar', 'as', 'av', 'ay', 'az',
        'ba', 'be', 'bg', 'bh', 'bi', 'bm', 'bn', 'bo', 'br', 'bs',
        'ca', 'ce', 'ch', 'co', 'cr', 'cs', 'cu', 'cv', 'cy',
        'da', 'de', 'dv', 'dz',
        'ee', 'el', 'en', 'eo', 'es', 'et', 'eu',
        'fa', 'ff', 'fi', 'fj', 'fo', 'fr', 'fy',
        'ga', 'gd', 'gl', 'gn', 'gu', 'gv',
        'ha', 'he', 'hi', 'ho', 'hr', 'ht', 'hu', 'hy', 'hz',
        'ia', 'id', 'ie', 'ig', 'ii', 'ik', 'io', 'is', 'it', 'iu',
        'ja', 'jv',
        'ka', 'kg', 'ki', 'kj', 'kk', 'kl', 'km', 'kn', 'ko', 'kr', 'ks', 'ku', 'kv', 'kw', 'ky',
        'la', 'lb', 'lg', 'li', 'ln', 'lo', 'lt', 'lu', 'lv',
        'mg', 'mh', 'mi', 'mk', 'ml', 'mn', 'mr', 'ms', 'mt', 'my',
        'na', 'nb', 'nd', 'ne', 'ng', 'nl', 'nn', 'no', 'nr', 'nv', 'ny',
        'oc', 'oj', 'om', 'or', 'os',
        'pa', 'pi', 'pl', 'ps', 'pt',
        'qu',
        'rm', 'rn', 'ro', 'ru', 'rw',
        'sa', 'sc', 'sd', 'se', 'sg', 'si', 'sk', 'sl', 'sm', 'sn', 'so', 'sq', 'sr', 'ss', 'st', 'su', 'sv', 'sw',
        'ta', 'te', 'tg', 'th', 'ti', 'tk', 'tl', 'tn', 'to', 'tr', 'ts', 'tt', 'tw', 'ty',
        'ug', 'uk', 'ur', 'uz',
        'va', 've', 'vi', 'vo',
        'wa', 'wo',
        'xh',
        'yi', 'yo',
        'za', 'zh', 'zu'
    }

    def __init__(self, l2: 'L2PersistentTM'):
        """
        Initialize integrity checker.

        Args:
            l2: L2PersistentTM instance to check
        """
        self.l2 = l2

    def verify_all(
        self,
        repair: bool = False,
        max_errors: int = 100,
        log_progress: bool = True
    ) -> IntegrityReport:
        """
        Scan all entries, validate JSON structure and required fields.

        Args:
            repair: If True, delete corrupted entries (USE WITH CAUTION)
            max_errors: Stop after this many errors (prevent runaway scans)
            log_progress: Log progress during scan

        Returns:
            IntegrityReport with validation results

        Validation Checks:
        1. Valid UTF-8 encoding
        2. Valid JSON structure
        3. Required fields present (source_text, translation, site_id, src_lang, tgt_lang)
        4. Non-empty values for required fields
        5. Valid ISO language codes
        """
        corrupt_keys = []
        errors = []
        valid_count = 0
        total_scanned = 0

        if log_progress:
            logger.info(f"Starting cache integrity verification (repair={repair})")

        with self.l2.env.begin() as txn:
            cursor = txn.cursor()
            for key, value in cursor:
                total_scanned += 1

                # Stop if too many errors
                if len(errors) >= max_errors:
                    logger.warning(f"Stopping scan after {max_errors} errors")
                    break

                # Progress logging every 10000 entries
                if log_progress and total_scanned % 10000 == 0:
                    logger.info(f"Scanned {total_scanned} entries...")

                try:
                    # Check 1: Valid UTF-8
                    decoded_value = value.decode('utf-8')

                    # Check 2: Valid JSON
                    entry = json.loads(decoded_value)

                    # Check 3-5: Validate entry structure
                    self._validate_entry_structure(entry)

                    valid_count += 1

                except UnicodeDecodeError as e:
                    error_msg = f"Invalid UTF-8: {str(e)}"
                    corrupt_keys.append(key)
                    errors.append((key, error_msg))
                    if log_progress:
                        logger.warning(f"Corrupted entry {key[:20]!r}: {error_msg}")

                except json.JSONDecodeError as e:
                    error_msg = f"Invalid JSON: {str(e)}"
                    corrupt_keys.append(key)
                    errors.append((key, error_msg))
                    if log_progress:
                        logger.warning(f"Corrupted entry {key[:20]!r}: {error_msg}")

                except ValueError as e:
                    error_msg = f"Invalid entry structure: {str(e)}"
                    corrupt_keys.append(key)
                    errors.append((key, error_msg))
                    if log_progress:
                        logger.warning(f"Corrupted entry {key[:20]!r}: {error_msg}")

                except Exception as e:
                    error_msg = f"Unexpected error: {type(e).__name__}: {str(e)}"
                    corrupt_keys.append(key)
                    errors.append((key, error_msg))
                    logger.error(f"Unexpected error for {key[:20]!r}: {error_msg}")

        # Repair phase (if requested)
        repaired_count = 0
        if repair and corrupt_keys:
            logger.warning(f"REPAIR MODE: Deleting {len(corrupt_keys)} corrupted entries")
            with self.l2.env.begin(write=True) as txn:
                for key in corrupt_keys:
                    try:
                        txn.delete(key)
                        repaired_count += 1
                    except Exception as e:
                        logger.error(f"Failed to delete corrupted key {key[:20]!r}: {e}")
            logger.info(f"Repair complete: {repaired_count} entries deleted")

        report = IntegrityReport(
            total_scanned=total_scanned,
            valid_count=valid_count,
            corrupt_count=len(corrupt_keys),
            repaired_count=repaired_count,
            corrupt_keys=corrupt_keys,
            errors=errors
        )

        if log_progress:
            logger.info(str(report))

        return report

    def _validate_entry_structure(self, entry: dict) -> None:
        """
        Validate entry has required fields with non-empty values.

        Args:
            entry: Dictionary to validate

        Raises:
            ValueError: If validation fails
        """
        if not isinstance(entry, dict):
            raise ValueError(f"Entry is not a dictionary: {type(entry)}")

        for field_name in self.REQUIRED_FIELDS:
            if field_name not in entry:
                raise ValueError(f"Missing required field: {field_name}")

            value = entry[field_name]
            if value is None:
                raise ValueError(f"Null value for required field: {field_name}")

            if isinstance(value, str) and not value.strip():
                raise ValueError(f"Empty value for required field: {field_name}")

        # Validate language codes (basic check - 2 letter ISO codes)
        for lang_field in ['src_lang', 'tgt_lang']:
            lang = entry[lang_field]
            if not isinstance(lang, str):
                raise ValueError(f"Invalid language code type for {lang_field}: {type(lang)}")

            lang_lower = lang.lower()
            if len(lang_lower) != 2:
                raise ValueError(f"Invalid language code length for {lang_field}: {lang}")

            if lang_lower not in self.VALID_LANG_CODES:
                raise ValueError(f"Unknown language code for {lang_field}: {lang}")

    def verify_entry(self, key: bytes, value: bytes) -> tuple[bool, str | None]:
        """
        Verify a single entry.

        Args:
            key: Entry key
            value: Entry value

        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            decoded_value = value.decode('utf-8')
            entry = json.loads(decoded_value)
            self._validate_entry_structure(entry)
            return True, None
        except Exception as e:
            return False, str(e)


    def scan_language_validity(
        self,
        tgt_lang: str,
        fasttext_model_path: Path,
        sample_rate: float = 0.05,
        confidence_threshold: float = 0.85,
        repair: bool = False,
        max_deletions_per_run: int = 100,
        dry_run: bool = False,
    ) -> "LanguageValidityReport":
        """
        WS-COMP-5: Scan L2 entries for a target language and detect wrong-language translations.

        Samples `sample_rate` fraction of entries where tgt_lang matches, runs FastText
        language detection on the cached translation text, and flags entries where
        detected language != expected tgt_lang with confidence >= confidence_threshold.

        Args:
            tgt_lang: Target language code to scan (e.g. "de")
            fasttext_model_path: Path to lid.176.bin FastText model
            sample_rate: Fraction of entries to check (0.0-1.0, default 0.05 = 5%)
            confidence_threshold: Min confidence to flag an entry (default 0.85)
            repair: If True AND not dry_run, delete flagged entries from L2
            max_deletions_per_run: Cap on deletions per invocation (prevents mass deletion spike)
            dry_run: If True, report but do not delete anything

        Returns:
            LanguageValidityReport with scan results.
        """
        try:
            import fasttext as _ft  # type: ignore
            model = _ft.load_model(str(fasttext_model_path))
        except ImportError:
            logger.error("fasttext-predict not installed — cannot scan language validity")
            return LanguageValidityReport(tgt_lang=tgt_lang, total_entries=0, total_sampled=0,
                                          stale_found=0, repaired_count=0)
        except Exception as e:
            logger.error(f"Failed to load FastText model {fasttext_model_path}: {e}")
            return LanguageValidityReport(tgt_lang=tgt_lang, total_entries=0, total_sampled=0,
                                          stale_found=0, repaired_count=0)

        # Similar language pairs — fasttext may confuse these; don't flag them
        _similar_pairs: set[frozenset] = {
            frozenset({"hr", "sr"}), frozenset({"hr", "bs"}), frozenset({"sr", "bs"}),
            frozenset({"ms", "id"}), frozenset({"cs", "sk"}), frozenset({"nb", "no"}),
            frozenset({"no", "da"}),
        }

        # Pass 1: collect keys for this tgt_lang (read-only scan)
        candidate_keys: list[bytes] = []
        with self.l2.env.begin() as txn:
            cursor = txn.cursor()
            for key, value in cursor:
                try:
                    entry = json.loads(value.decode("utf-8"))
                    if entry.get("tgt_lang") == tgt_lang:
                        candidate_keys.append(key)
                except Exception:
                    pass

        total_entries = len(candidate_keys)
        if total_entries == 0:
            return LanguageValidityReport(tgt_lang=tgt_lang, total_entries=0, total_sampled=0,
                                          stale_found=0, repaired_count=0)

        # Sample at sample_rate
        sample_size = max(1, int(total_entries * sample_rate))
        sampled_keys = random.sample(candidate_keys, min(sample_size, total_entries))

        stale_keys: list[bytes] = []
        stale_entries_info: list[dict] = []
        total_sampled = 0

        with self.l2.env.begin() as txn:
            for key in sampled_keys:
                value = txn.get(key)
                if value is None:
                    continue
                try:
                    entry = json.loads(value.decode("utf-8"))
                    translation = entry.get("translation", "")
                    if not translation or len(translation.strip()) < 20:
                        continue
                    total_sampled += 1

                    # Run FastText detection on translation
                    text_clean = translation.replace("\n", " ").strip()[:500]
                    predictions = model.predict(text_clean, k=1)
                    detected_lang = predictions[0][0].replace("__label__", "")
                    confidence = float(predictions[1][0])

                    if detected_lang == tgt_lang:
                        continue  # Correct language
                    if confidence < confidence_threshold:
                        continue  # Not confident enough
                    if frozenset({detected_lang, tgt_lang}) in _similar_pairs:
                        continue  # Known similar pair

                    stale_keys.append(key)
                    stale_entries_info.append({
                        "key_hex": key[:16].hex(),
                        "translation_snippet": translation[:80],
                        "detected_lang": detected_lang,
                        "confidence": round(confidence, 3),
                    })
                    logger.debug(
                        f"Stale TM entry: tgt={tgt_lang}, detected={detected_lang} "
                        f"conf={confidence:.2f}: {translation[:40]!r}"
                    )
                except Exception as e:
                    logger.debug(f"Error checking entry: {e}")

        stale_found = len(stale_keys)
        repaired_count = 0

        if stale_found > 0:
            logger.warning(
                f"TM language validity scan [{tgt_lang}]: {stale_found} wrong-language entries "
                f"found in {total_sampled} sampled ({total_entries} total). "
                f"repair={repair}, dry_run={dry_run}"
            )

        if repair and stale_keys and not dry_run:
            to_delete = stale_keys[:max_deletions_per_run]
            with self.l2.env.begin(write=True) as txn:
                for key in to_delete:
                    try:
                        txn.delete(key)
                        repaired_count += 1
                    except Exception as e:
                        logger.error(f"Failed to delete stale key: {e}")
            logger.info(
                f"TM language validity repair [{tgt_lang}]: deleted {repaired_count} "
                f"wrong-language entries (capped at {max_deletions_per_run}/run)"
            )
        elif dry_run and stale_found > 0:
            logger.info(f"TM language validity dry-run [{tgt_lang}]: would delete {stale_found} entries")

        return LanguageValidityReport(
            tgt_lang=tgt_lang,
            total_entries=total_entries,
            total_sampled=total_sampled,
            stale_found=stale_found,
            repaired_count=repaired_count,
            stale_entries=stale_entries_info,
        )


def check_cache_integrity(
    db_path: Path,
    repair: bool = False,
    max_errors: int = 100
) -> IntegrityReport:
    """
    Convenience function to check cache integrity.

    Args:
        db_path: Path to LMDB database directory
        repair: If True, delete corrupted entries
        max_errors: Stop after this many errors

    Returns:
        IntegrityReport with validation results
    """
    from .l2_persistent import L2PersistentTM

    l2 = L2PersistentTM(db_path)
    checker = CacheIntegrityChecker(l2)
    return checker.verify_all(repair=repair, max_errors=max_errors)
