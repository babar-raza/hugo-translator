"""
L2 Persistent Translation Memory using LMDB.

Durable key-value store for exact translation matches across sessions.
"""

import hashlib
import json
import logging
import threading
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import lmdb

from .normalization import make_tm_key, make_tm_key_scoped

# TC-APT-096: hard ceiling on auto-resize growth (existing behavior, now a
# named constant instead of a magic number repeated at every call site).
_MAX_MAP_SIZE_MB = 8192

# Module-level FastText singleton with 60-second retry cooldown (SW-3 / TC-01).
# These are kept for test compatibility; active code uses L2PersistentTM._detector.
_FASTTEXT_RETRY_COOLDOWN: float = 60.0
_fasttext_detector_instance = None
_fasttext_detector_failed_at: float | None = None


def _get_fasttext_detector():
    """Return module-level FastText singleton with 60-second retry cooldown.

    Returns None when: the detector is unavailable, or a load failure occurred
    within the last _FASTTEXT_RETRY_COOLDOWN seconds.
    """
    import time

    global _fasttext_detector_instance, _fasttext_detector_failed_at

    if _fasttext_detector_instance is not None:
        return _fasttext_detector_instance

    # Within cooldown window after a load failure — skip retry
    if (
        _fasttext_detector_failed_at is not None
        and (time.time() - _fasttext_detector_failed_at) < _FASTTEXT_RETRY_COOLDOWN
    ):
        return None

    # Attempt (re-)load
    try:
        from src.translation_engine.language_detection.fasttext_detector import (
            FastTextDetector,
        )

        _fasttext_detector_instance = FastTextDetector(cache_dir=Path("data/models/fasttext"))
        _fasttext_detector_failed_at = None
        return _fasttext_detector_instance
    except Exception as e:
        logger.warning("FastText unavailable (module-level singleton): %s", e)
        _fasttext_detector_failed_at = time.time()
        return None


# Canonical sub-directory name for the L2 LMDB database.
# All callers must use this constant so the path is never mis-typed.
L2_DB_NAME = "l2.lmdb"

# T204: Integrity safeguards (federated-splashing-panda)
logger = logging.getLogger(__name__)


#: TC-APT-008: name of the lineage sub-database. LMDB stores a named sub-db under this key
#: in the MAIN database, so every main-DB scan/count must skip it.
LINEAGE_DB_NAME = b"by_config_fingerprint"


@dataclass
class TranslationEntry:
    """Translation memory entry."""

    source_text: str
    translation: str
    site_id: str
    src_lang: str
    tgt_lang: str
    context: str | None = None
    timestamp: str | None = None
    metadata: dict[str, Any] = None
    # HT-QUALITY-GATES-001 Part 22 (root cause A): optional field scope (e.g.
    # "description", "title"), mirroring store()'s field_name parameter.
    # batch_store() previously had no way to receive this per-entry, so bulk
    # TM population bypassed field-scoping entirely regardless of what the
    # single-entry store() path already enforced. Default "" preserves the
    # legacy unscoped key for existing callers/entries.
    field_name: str = ""
    # TC-APT-008 (plan 7.5): first-class lineage, dual-written alongside the metadata dict.
    config_fingerprint: str | None = None
    model_id: str | None = None

    def __post_init__(self):
        """Initialize defaults."""
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        if self.metadata is None:
            self.metadata = {}
        if self.config_fingerprint is None or self.model_id is None:
            from src.tm.lineage import lineage_of

            fp, model = lineage_of(self.metadata)
            if self.config_fingerprint is None:
                self.config_fingerprint = fp
            if self.model_id is None:
                self.model_id = model

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TranslationEntry":
        """Create from dictionary (unknown keys are ignored for forward compatibility)."""
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def is_valid(self) -> bool:
        """
        Validate entry fields (T204: federated-splashing-panda).

        Returns:
            True if entry is valid, False otherwise
        """
        # Check required fields are non-empty strings
        if not isinstance(self.source_text, str) or not self.source_text:
            return False
        if not isinstance(self.translation, str) or not self.translation:
            return False
        if not isinstance(self.site_id, str) or not self.site_id:
            return False
        if not isinstance(self.src_lang, str) or not self.src_lang:
            return False
        if not isinstance(self.tgt_lang, str) or not self.tgt_lang:
            return False

        # Check optional fields have correct types if present
        if self.context is not None and not isinstance(self.context, str):
            return False
        if self.metadata is not None and not isinstance(self.metadata, dict):
            return False
        if self.timestamp is not None and not isinstance(self.timestamp, str):
            return False

        return True


class L2PersistentTM:
    """
    LMDB-backed persistent translation memory.

    Provides durable storage for exact translation matches
    with fast lookups and batch operations.
    """

    def __init__(self, db_path: Path | str, max_size_mb: int = 4096):
        """
        Initialize L2 persistent TM.

        Args:
            db_path: Path to LMDB database directory
            max_size_mb: Maximum database size in MB (default: 4096 MB).
                reference.aspose.org fills fast; 4 GB is the safe lower bound.
                Callers should read this value from config; the default here is
                the fallback of last resort.
        """
        self.db_path = Path(db_path)
        self.db_path.mkdir(parents=True, exist_ok=True)

        # Hard enforcement: reject unapproved LMDB paths at runtime
        from src.tm import lmdb_registry as _reg

        _reg.assert_approved_path(self.db_path)

        # TC-TM-02: Warn if a sibling LMDB directory exists next to the canonical
        # path.  Two live L2 databases imply split writes and diverging caches.
        # The canonical name is L2_DB_NAME ("l2.lmdb"); anything else alongside it
        # is a migration artefact.  Run scripts/tm/migrate_l2_lmdb.py to consolidate.
        self._warn_on_sibling_l2_dirs()

        # Convert MB to bytes for LMDB
        max_size_bytes = max_size_mb * 1024 * 1024

        # Open LMDB environment
        from src.tm.environment_lease import EnvironmentLease

        self._environment_lease = EnvironmentLease(self.db_path)
        try:
            self.env = lmdb.open(
                str(self.db_path),
                map_size=max_size_bytes,
                max_dbs=4,  # main + by_config_fingerprint lineage index
                sync=True,
                writemap=False,
            )
        except BaseException:
            self._environment_lease.close()
            raise

        self._lock = threading.RLock()
        self._lang_detector = None  # lazy-loaded; set externally or on first use
        # TC-APT-008: secondary index config_fingerprint -> main key (dupsort), O(matches) lookup.
        self._lineage_db = self.env.open_db(LINEAGE_DB_NAME, dupsort=True)
        from src.tm.lineage import default_denylist

        self._denylist = default_denylist()
        self.denied_lookups = 0

    @property
    def _detector(self):
        """FastText detector — loaded once, reused. Returns None if unavailable."""
        if self._lang_detector is None:
            try:
                from src.translation_engine.language_detection.fasttext_detector import (
                    FastTextDetector,
                )

                self._lang_detector = FastTextDetector(cache_dir=Path("data/models/fasttext"))
            except Exception as e:
                logger.warning("FastText unavailable for TM validation: %s", e)
                self._lang_detector = False  # sentinel: skip detection, don't retry
        return self._lang_detector if self._lang_detector is not False else None

    def _validate_translation_language(self, translation: str, tgt_lang: str) -> bool:
        """Return True if translation passes language check (or check is unavailable)."""
        if len(translation.strip()) <= 50:
            return True  # too short for reliable detection
        detector = self._detector
        if detector is None:
            return True  # detector unavailable → allow storage
        try:
            detected_lang, confidence = detector.detect(translation)
            if confidence < 0.80:
                return True  # low confidence → allow (avoid false rejections)
            # Allow similar language groups
            _TM_SIMILAR_GROUPS = [
                {"ms", "id"},
                {"cs", "sk"},
                {"hr", "sr", "bs"},
                {"nb", "da", "no"},
            ]
            if any(tgt_lang in grp and detected_lang in grp for grp in _TM_SIMILAR_GROUPS):
                return True
            if detected_lang != tgt_lang:
                logger.warning(
                    "TM contamination blocked: detected=%s expected=%s (conf=%.2f)",
                    detected_lang,
                    tgt_lang,
                    confidence,
                )
                return False
        except Exception:
            return True  # validation error → allow
        return True

    def _warn_on_sibling_l2_dirs(self, *, strict: bool = False) -> None:
        """Emit a UserWarning if sibling l2*.lmdb directories exist alongside the canonical path.

        Two live LMDB databases imply split writes (TC-TM-02 gap).  By default
        this only warns so the worker can still start.  Pass ``strict=True``
        (TM-01) to raise instead -- for a pre-flight/CI check that wants to
        hard-fail on this condition rather than let it linger unresolved, as
        happened live: five scripts kept opening a hardcoded sibling path
        indefinitely with only a warning that nothing consumed.  Not the
        default, to avoid surprising existing callers that only expect a
        warning. To fix, run::

            python scripts/tm/migrate_l2_lmdb.py --dry-run
            python scripts/tm/migrate_l2_lmdb.py --apply
        """
        import warnings

        parent = self.db_path.parent
        canonical_name = self.db_path.name
        # Match both "l2.lmdb" (dot-style) and "l2_lmdb" (underscore-style) variants.
        siblings = [p for p in parent.glob("l2*") if p.is_dir() and p.name != canonical_name]
        if siblings:
            names = ", ".join(p.name for p in siblings)
            message = (
                f"L2PersistentTM: sibling LMDB director{'y' if len(siblings) == 1 else 'ies'} "
                f"found alongside canonical '{canonical_name}': {names}. "
                "This indicates split writes. Run scripts/tm/migrate_l2_lmdb.py to consolidate."
            )
            if strict:
                raise RuntimeError(message)
            warnings.warn(message, UserWarning, stacklevel=3)
            logger.warning(
                "TC-TM-02: sibling L2 LMDB dir(s) detected: %s (canonical: %s). "
                "Run scripts/tm/migrate_l2_lmdb.py --apply to consolidate.",
                names,
                self.db_path,
            )

    def _run_txn_with_map_recovery(self, txn_fn, *, max_attempts: int = 3):
        """Run `txn_fn()` -- a zero-arg callable that opens its OWN
        `with self.env.begin(...) as txn:` block and returns a result --
        with automatic recovery from the two failure modes an LMDB resize
        can cause (TC-APT-096).

        MapFullError (this environment is full): grow it, bounded by
        _MAX_MAP_SIZE_MB, and retry. The failing transaction's `with` block
        must have already exited (fully aborted) before set_mapsize is
        called -- LMDB forbids resizing while ANY transaction is open in
        this process. Confirmed by direct reproduction: nesting a second
        write transaction inside the still-open failing one (the previous
        code's shape) raised InvalidParameterError from set_mapsize itself,
        then BadTxnError unwinding the outer transaction -- a hard crash,
        not the graceful "resize and retry" the code's comments claimed.
        Retrying the FULL txn_fn() (not a nested transaction) is the only
        safe unit of retry: LMDB transactions have no partial commit.

        MapResizedError (MDB_MAP_RESIZED): a SIBLING process -- a different
        K-lane launcher sharing this same LMDB file (plan SS0.10 TC-APT-094)
        -- resized the map first. This process's environment handle is now
        stale; adopt the new size with set_mapsize(0) (LMDB's documented
        "read the current size from disk" call) and retry. Unhandled prior
        to this fix -- zero call sites anywhere caught it -- so any lane's
        resize would crash every OTHER lane's very next TM read or write.
        """
        last_exc: Exception | None = None
        for attempt in range(max_attempts):
            try:
                return txn_fn()
            except lmdb.MapFullError as exc:
                last_exc = exc
                current_mb = self.env.info()["map_size"] // (1024 * 1024)
                # +1 floor: int(current_mb * 1.5) truncates to a no-op growth
                # at small starting sizes (e.g. 1 MB * 1.5 = 1.5 -> int() = 1),
                # which would otherwise hit the "cannot grow further" raise
                # below immediately, on the very first MapFullError, without
                # ever actually resizing.
                new_mb = min(max(int(current_mb * 1.5), current_mb + 1), _MAX_MAP_SIZE_MB)
                if new_mb <= current_mb:
                    raise
                logger.warning(
                    "LMDB MapFullError (attempt %d/%d) — resizing %d MB → %d MB",
                    attempt + 1, max_attempts, current_mb, new_mb,
                )
                self.env.set_mapsize(new_mb * 1024 * 1024)
            except lmdb.MapResizedError as exc:
                last_exc = exc
                logger.warning(
                    "LMDB MDB_MAP_RESIZED (attempt %d/%d) — a sibling process resized "
                    "the map; adopting its current size",
                    attempt + 1, max_attempts,
                )
                self.env.set_mapsize(0)
        raise last_exc

    def exact_lookup(
        self,
        site_id: str,
        src_lang: str,
        tgt_lang: str,
        text: str,
        context: str | None = None,
        field_name: str = "",
    ) -> TranslationEntry | None:
        """
        Find exact match for text with corruption detection (T204: federated-splashing-panda).

        Tries keys from most to least specific -- (field_name, context), then
        field_name alone, then context alone, then the fully legacy unscoped
        key -- so a lookup that supplies context only matches an entry stored
        under that *same* context (HT-QUALITY-GATES-001 Part 22: context was
        previously accepted end-to-end but never affected the key at all,
        meaning two unrelated occurrences of identical text under different
        contexts silently collided). Falling back to less-specific tiers is
        the same backward-compatibility pattern already used for field_name.

        Args:
            site_id: Site identifier
            src_lang: Source language code
            tgt_lang: Target language code
            text: Source text to look up
            context: Optional context for disambiguation (e.g. "frontmatter.title")
            field_name: Optional field scope (e.g. "description", "title")

        Returns:
            TranslationEntry if found and valid, None otherwise
        """
        ctx = context or ""
        keys_to_try: list[str] = []
        if field_name and ctx:
            keys_to_try.append(
                make_tm_key_scoped(site_id, src_lang, tgt_lang, text, field_name, ctx)
            )
        if field_name:
            keys_to_try.append(make_tm_key_scoped(site_id, src_lang, tgt_lang, text, field_name))
        if ctx:
            keys_to_try.append(make_tm_key_scoped(site_id, src_lang, tgt_lang, text, context=ctx))
        keys_to_try.append(make_tm_key(site_id, src_lang, tgt_lang, text))

        def _do_lookup():
            with self._lock:
                with self.env.begin() as txn:
                    value_bytes = None
                    for key in keys_to_try:
                        value_bytes = txn.get(key.encode("utf-8"))
                        if value_bytes is not None:
                            break

                    if value_bytes is None:
                        return None

                    # T204: Deserialize with corruption detection
                    try:
                        value_dict = json.loads(value_bytes.decode("utf-8"))
                        entry = TranslationEntry.from_dict(value_dict)
                    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
                        # T204: Corrupted entry detected
                        logger.warning(
                            f"Corrupted cache entry detected and skipped: "
                            f"site_id={site_id}, src_lang={src_lang}, tgt_lang={tgt_lang}, "
                            f"text={text[:50]}..., error={e}"
                        )
                        return None

                    # TC-APT-008: read-time lineage invalidation (reversible denylist, never a delete)
                    if self._denylist.denies(entry):
                        self.denied_lookups += 1
                        logger.debug(
                            "TM entry suppressed by lineage denylist: site=%s %s->%s fp=%s model=%s",
                            site_id,
                            src_lang,
                            tgt_lang,
                            entry.config_fingerprint,
                            entry.model_id,
                        )
                        return None
                    # T204: Validate entry integrity
                    if not entry.is_valid():
                        logger.warning(
                            f"Invalid cache entry detected and skipped: "
                            f"site_id={site_id}, src_lang={src_lang}, tgt_lang={tgt_lang}, "
                            f"text={text[:50]}..."
                        )
                        return None

                    return entry

        return self._run_txn_with_map_recovery(_do_lookup)

    def store(
        self,
        site_id: str,
        src_lang: str,
        tgt_lang: str,
        text: str,
        translation: str,
        context: str | None = None,
        metadata: dict[str, Any] | None = None,
        overwrite: bool = True,
        field_name: str = "",
    ) -> bool:
        """
        Store translation entry with integrity safeguards (T204: federated-splashing-panda).

        When field_name is given, stores under the scoped key to prevent cross-field
        TM contamination (TC-HDN-003). Unscoped legacy entries remain in place and
        are still resolved by exact_lookup() via its fallback path.

        Args:
            site_id: Site identifier
            src_lang: Source language code
            tgt_lang: Target language code
            text: Source text
            translation: Translated text
            context: Optional context (frontmatter key, AST path)
            metadata: Optional additional metadata
            overwrite: If True, overwrite existing entry. If False, skip if exists.
            field_name: Optional field scope (e.g. "description", "title")

        Returns:
            True if stored, False if skipped (existing entry and overwrite=False)

        Raises:
            ValueError: If entry validation fails
            RuntimeError: If JSON serialization or database write fails
        """
        # Validate translation language before storing (prevents TM contamination)
        if not self._validate_translation_language(translation, tgt_lang):
            return False

        # T204: Create and validate entry before write
        entry = TranslationEntry(
            source_text=text,
            translation=translation,
            site_id=site_id,
            src_lang=src_lang,
            tgt_lang=tgt_lang,
            context=context,
            metadata=metadata or {},
        )

        # T204: Validate entry integrity
        if not entry.is_valid():
            logger.error(
                f"Invalid translation entry rejected: site_id={site_id}, "
                f"src_lang={src_lang}, tgt_lang={tgt_lang}, text={text[:50]}..."
            )
            raise ValueError("Translation entry failed validation")

        key = make_tm_key_scoped(site_id, src_lang, tgt_lang, text, field_name, context or "")
        key_bytes = key.encode("utf-8")

        def _do_store():
            with self._lock:
                # T204: LMDB transaction provides atomic write with automatic rollback on failure
                with self.env.begin(write=True) as txn:
                    # Check if exists when not overwriting
                    if not overwrite:
                        existing = txn.get(key_bytes)
                        if existing is not None:
                            return False  # Skip - already exists

                    # T204: Serialize with error handling
                    try:
                        value_json = json.dumps(entry.to_dict())
                    except (TypeError, ValueError) as e:
                        logger.error(f"JSON serialization failed for entry: {e}")
                        raise RuntimeError(f"Failed to serialize translation entry: {e}")

                    # T204: Store with automatic rollback on failure. MapFullError/
                    # MapResizedError propagate out of this ENTIRE function (past
                    # both `with` blocks, so the transaction is fully aborted) to
                    # _run_txn_with_map_recovery, which resizes/adopts and calls
                    # _do_store() again fresh -- TC-APT-096, see that method's
                    # docstring for why a nested transaction here is unsafe.
                    txn.put(key_bytes, value_json.encode("utf-8"))
                    self._index_lineage(txn, entry, key_bytes)
                    return True

        try:
            return self._run_txn_with_map_recovery(_do_store)
        except Exception as e:
            # T204: Log integrity failure and propagate
            logger.error(
                f"Cache write failed (integrity safeguard triggered): "
                f"site_id={site_id}, src_lang={src_lang}, tgt_lang={tgt_lang}, "
                f"error={e}"
            )
            raise

    def batch_store(self, entries: list[TranslationEntry], overwrite: bool = True) -> int:
        """
        Efficiently store many entries at once with integrity safeguards (T204: federated-splashing-panda).

        Args:
            entries: List of TranslationEntry objects
            overwrite: If False, skip entries whose key already exists in the DB.

        Returns:
            Number of entries stored

        Raises:
            ValueError: If any entry validation fails
            RuntimeError: If JSON serialization or database write fails
        """
        # T204: Validate all entries before starting transaction
        for i, entry in enumerate(entries):
            if not entry.is_valid():
                logger.error(
                    f"Invalid entry in batch at index {i}: "
                    f"site_id={entry.site_id}, src_lang={entry.src_lang}, "
                    f"tgt_lang={entry.tgt_lang}"
                )
                raise ValueError(f"Entry at index {i} failed validation")

        def _do_batch():
            with self._lock:
                # T204: LMDB transaction provides atomic batch write with automatic rollback.
                # MapFullError/MapResizedError propagate out of this ENTIRE function (past
                # the `with` block, so the transaction is fully aborted) to
                # _run_txn_with_map_recovery, which resizes/adopts and calls _do_batch()
                # again fresh, redoing the whole batch -- TC-APT-096, see that method's
                # docstring for why a nested transaction here is unsafe. LMDB transactions
                # have no partial commit, so a full-batch retry is the only safe unit.
                with self.env.begin(write=True) as txn:
                    stored = 0
                    rejected = 0
                    for entry in entries:
                        # Fix E: language validation before write
                        if not self._validate_translation_language(
                            entry.translation, entry.tgt_lang
                        ):
                            rejected += 1
                            continue

                        # HT-QUALITY-GATES-001 Part 22 (root cause A): use the
                        # scoped key (falls back to the unscoped legacy format
                        # when entry.field_name/entry.context are both "") instead
                        # of always calling make_tm_key() directly -- this was the
                        # gap that let bulk population bypass field/context scoping
                        # entirely even after store()'s single-entry path was
                        # already fixed.
                        key = make_tm_key_scoped(
                            entry.site_id,
                            entry.src_lang,
                            entry.tgt_lang,
                            entry.source_text,
                            entry.field_name,
                            entry.context or "",
                        )

                        # Ensure timestamp is set
                        if entry.timestamp is None:
                            entry.timestamp = datetime.now(timezone.utc).isoformat()

                        # T204: Serialize with error handling
                        try:
                            value_json = json.dumps(entry.to_dict())
                        except (TypeError, ValueError) as e:
                            logger.error(
                                f"JSON serialization failed in batch at index {stored}: {e}"
                            )
                            raise RuntimeError(f"Failed to serialize entry at index {stored}: {e}")

                        key_bytes = key.encode("utf-8")
                        val_bytes = value_json.encode("utf-8")
                        if not overwrite and txn.get(key_bytes) is not None:
                            continue  # skip existing entry
                        txn.put(key_bytes, val_bytes)
                        stored += 1

                    if rejected:
                        logger.warning(
                            "batch_store: rejected %d/%d entries (language mismatch)",
                            rejected,
                            len(entries),
                        )
                    return stored

        try:
            return self._run_txn_with_map_recovery(_do_batch)
        except Exception as e:
            # T204: Log integrity failure and propagate
            logger.error(f"Batch cache write failed (integrity safeguard triggered): error={e}")
            raise

    # ------------------------------------------------------------------ TC-APT-008 lineage index
    def _index_lineage(self, txn, entry: "TranslationEntry", key_bytes: bytes) -> None:
        """Record key under its config_fingerprint in the dupsort index (no-op without lineage)."""
        fp = entry.config_fingerprint
        if fp:
            txn.put(fp.encode("utf-8"), key_bytes, db=self._lineage_db, dupdata=True)

    def iter_by_config_fingerprint(self, config_fingerprint: str):
        """Yield every entry produced under ``config_fingerprint`` -- O(matches), not O(store).

        TC-APT-096 known gap: unlike every other method here, this holds its
        read transaction open across the caller's iteration (a generator),
        so it is NOT wrapped in _run_txn_with_map_recovery -- retrying would
        mean re-entering a generator mid-yield, which does not safely
        resume the caller's own consumption loop. A sibling process's
        resize mid-iteration will surface as an uncaught MapResizedError
        here. Lower-frequency backfill/reporting path, not the blitz's hot
        store/lookup path; restructuring to buffer-then-yield to make this
        safely retryable is a follow-on if it proves to matter in practice.
        """
        with self._lock:
            with self.env.begin() as txn:
                cursor = txn.cursor(db=self._lineage_db)
                if not cursor.set_key(config_fingerprint.encode("utf-8")):
                    return
                for main_key in cursor.iternext_dup():
                    raw = txn.get(main_key)
                    if raw is None:
                        continue
                    try:
                        yield TranslationEntry.from_dict(json.loads(raw.decode("utf-8")))
                    except Exception:
                        continue

    def count_by_config_fingerprint(self, config_fingerprint: str) -> int:
        def _do_count():
            with self._lock:
                with self.env.begin() as txn:
                    cursor = txn.cursor(db=self._lineage_db)
                    if not cursor.set_key(config_fingerprint.encode("utf-8")):
                        return 0
                    return cursor.count()

        return self._run_txn_with_map_recovery(_do_count)

    def lineage_index_stats(self) -> dict[str, int]:
        """Distinct fingerprints and indexed keys (cheap: index only)."""

        def _do_stats():
            with self._lock:
                with self.env.begin() as txn:
                    stat = txn.stat(db=self._lineage_db)
                    cursor = txn.cursor(db=self._lineage_db)
                    distinct = 0
                    if cursor.first():
                        distinct = 1
                        while cursor.next_nodup():
                            distinct += 1
                    return {"indexed_keys": int(stat["entries"]), "distinct_fingerprints": distinct}

        return self._run_txn_with_map_recovery(_do_stats)

    def rewrite_entry_lineage(self, txn, key_bytes: bytes, entry: "TranslationEntry") -> None:
        """Backfill helper: rewrite one stored entry with first-class lineage and index it."""
        txn.put(key_bytes, json.dumps(entry.to_dict()).encode("utf-8"))
        self._index_lineage(txn, entry, key_bytes)

    def delete(self, site_id: str, src_lang: str, tgt_lang: str, text: str) -> bool:
        """
        Delete translation entry.

        Args:
            site_id: Site identifier
            src_lang: Source language code
            tgt_lang: Target language code
            text: Source text

        Returns:
            True if entry was deleted, False if not found
        """
        key = make_tm_key(site_id, src_lang, tgt_lang, text)

        def _do_delete():
            with self._lock:
                with self.env.begin(write=True) as txn:
                    return txn.delete(key.encode("utf-8"))

        return self._run_txn_with_map_recovery(_do_delete)

    def delete_namespace(
        self,
        *,
        site_id: str,
        src_lang: str | None = None,
        tgt_lang: str | None = None,
    ) -> int:
        """Atomically remove every entry in an exact governed namespace.

        Matching uses only entry metadata; translation payloads are never
        returned or logged.  This is intended for invalidating a campaign
        source/locale namespace after its previously accepted output loses
        acceptance under a hardened policy.
        """
        if not site_id:
            raise ValueError("delete_namespace requires an exact site_id")

        def _do_delete_namespace():
            keys: list[bytes] = []
            with self._lock:
                with self.env.begin() as txn:
                    cursor = txn.cursor()
                    for key, value in cursor:
                        if key == LINEAGE_DB_NAME:
                            continue  # TC-APT-008: sub-db name key, not a TM entry
                        try:
                            entry = json.loads(value.decode("utf-8"))
                        except Exception as exc:
                            raise RuntimeError(
                                "refusing namespace deletion with an unreadable TM entry"
                            ) from exc
                        if entry.get("site_id") != site_id:
                            continue
                        if src_lang is not None and entry.get("src_lang") != src_lang:
                            continue
                        if tgt_lang is not None and entry.get("tgt_lang") != tgt_lang:
                            continue
                        keys.append(bytes(key))
                if not keys:
                    return 0
                # Re-scanning and re-deleting on retry is safe: deleting an
                # already-deleted key is a no-op, so redoing this whole
                # function fresh after a resize (TC-APT-096) cannot double-count.
                with self.env.begin(write=True) as txn:
                    removed = sum(1 for key in keys if txn.delete(key))
                    if removed != len(keys):
                        raise RuntimeError(
                            "TM namespace deletion count changed during atomic removal"
                        )
            return len(keys)

        removed_count = self._run_txn_with_map_recovery(_do_delete_namespace)
        if removed_count:
            logger.warning(
                "Deleted %d L2 entries from exact namespace hash=%s",
                removed_count,
                hashlib.sha256(site_id.encode("utf-8")).hexdigest()[:16],
            )
        return removed_count

    def count(self) -> int:
        """
        Get total number of entries in database.

        Excludes the ``by_config_fingerprint`` sub-database's name key, which LMDB keeps in
        the main database (TC-APT-008).

        Returns:
            Entry count
        """
        def _do_count():
            with self._lock:
                with self.env.begin() as txn:
                    total = txn.stat()["entries"]
                    if txn.get(LINEAGE_DB_NAME) is not None:
                        total -= 1
                    return max(total, 0)

        return self._run_txn_with_map_recovery(_do_count)

    def clear(self) -> None:
        """Delete all entries from database (including the TC-APT-008 lineage index)."""

        def _do_clear():
            with self._lock:
                with self.env.begin(write=True) as txn:
                    # Empty the lineage index first, then the main database.
                    txn.drop(self._lineage_db, delete=False)
                    txn.drop(self.env.open_db())

        self._run_txn_with_map_recovery(_do_clear)

    def export_all(
        self, site_id: str | None = None, tgt_lang: str | None = None
    ) -> list[TranslationEntry]:
        """
        Export all entries from L2 cache.

        Args:
            site_id: Filter by site (optional)
            tgt_lang: Filter by target language (optional)

        Returns:
            List of TranslationEntry objects
        """
        def _do_export():
            entries = []
            with self._lock:
                with self.env.begin() as txn:
                    cursor = txn.cursor()
                    for key, value in cursor:
                        try:
                            entry_dict = json.loads(value.decode("utf-8"))
                            entry = TranslationEntry.from_dict(entry_dict)

                            # Apply filters
                            if site_id and entry.site_id != site_id:
                                continue
                            if tgt_lang and entry.tgt_lang != tgt_lang:
                                continue

                            entries.append(entry)

                        except Exception as e:
                            logger.warning(f"Failed to parse entry {key[:20]!r}: {e}")
            return entries

        entries = self._run_txn_with_map_recovery(_do_export)
        logger.info(f"Exported {len(entries)} entries from L2")
        return entries

    def export_iter(
        self,
        site_id: str | None = None,
        tgt_lang: str | None = None,
    ):
        """Streaming generator — constant-memory alternative to export_all().

        TC-APT-096 known gap: same reasoning as iter_by_config_fingerprint --
        a generator holding its read transaction open across the caller's
        iteration cannot be safely wrapped in _run_txn_with_map_recovery.
        """
        with self._lock:
            with self.env.begin() as txn:
                cursor = txn.cursor()
                for _key_bytes, value_bytes in cursor.iternext():
                    if _key_bytes == LINEAGE_DB_NAME:
                        continue  # TC-APT-008: sub-db name key, not a TM entry
                    try:
                        entry = TranslationEntry.from_dict(json.loads(value_bytes.decode("utf-8")))
                        if site_id and entry.site_id != site_id:
                            continue
                        if tgt_lang and entry.tgt_lang != tgt_lang:
                            continue
                        yield entry
                    except Exception:
                        continue

    def stats_by_dimension(self, dimension: str = "tgt_lang") -> dict[str, int]:
        """Count entries grouped by a field: 'tgt_lang', 'site_id', or 'src_lang'."""
        counts: dict[str, int] = {}
        for entry in self.export_iter():
            key = getattr(entry, dimension, "unknown")
            counts[key] = counts.get(key, 0) + 1
        return counts

    def get_stats(self) -> dict:
        """
        Return LMDB utilization stats (readonly, side-effect-free).

        Returns:
            dict with keys:
                map_size_mb  – total allocated map size in MiB
                used_mb      – estimated used space in MiB (live data pages only)
                used_pct     – used_mb / map_size_mb * 100
                entries      – number of stored key/value pairs
        """
        with self._lock:
            info = self.env.info()
            stat = self.env.stat()
            map_size_bytes = info["map_size"]
            page_size = stat["psize"]
            used_pages = stat["branch_pages"] + stat["leaf_pages"] + stat["overflow_pages"]
            used_bytes = used_pages * page_size
            map_size_mb = map_size_bytes / 1024 / 1024
            used_mb = used_bytes / 1024 / 1024
            return {
                "map_size_mb": map_size_mb,
                "used_mb": used_mb,
                "used_pct": (used_mb / map_size_mb * 100) if map_size_mb > 0 else 0.0,
                "entries": stat["entries"],
            }

    def close(self) -> None:
        """Close database connection."""
        if self.env:
            self.env.close()
        lease = getattr(self, "_environment_lease", None)
        if lease is not None:
            lease.close()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()

    def __len__(self) -> int:
        """Return number of entries."""
        return self.count()
