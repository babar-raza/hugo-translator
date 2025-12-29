"""Cache integrity verification for Translation Memory.

This module provides integrity checking capabilities for the LMDB-based L2 cache,
including detection of corrupted entries and optional auto-repair.

Implementation follows TM-01 from the TM cache integrity plan.
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple, Optional, TYPE_CHECKING

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
    corrupt_keys: List[bytes] = field(default_factory=list)
    errors: List[Tuple[bytes, str]] = field(default_factory=list)

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

    def verify_entry(self, key: bytes, value: bytes) -> Tuple[bool, Optional[str]]:
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
