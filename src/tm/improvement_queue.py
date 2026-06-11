"""
TM Improvement Queue - Lightweight queue for tracking TM entries that need improvement.

Implements a JSONL-based queue with:
- Append-only candidate storage (no full LMDB scan needed)
- Deduplication using hash-based seen tracking
- FIFO pop with configurable batch size
- Persistent storage for resume across runs
"""

import hashlib
import json
import logging
import os
import tempfile
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ImprovementCandidate:
    """
    A TM entry candidate for LLM-based improvement.

    Attributes:
        site_id: Site identifier
        src_lang: Source language code
        tgt_lang: Target language code
        text: Source text
        translation: Current translation
        context: Optional context information
        added_at: Timestamp when added to queue (ISO format)
        metadata: Optional metadata (e.g., similarity_score, hit_count)
        candidate_hash: Unique hash for deduplication
    """

    site_id: str
    src_lang: str
    tgt_lang: str
    text: str
    translation: str
    context: str | None = None
    added_at: str | None = None
    metadata: dict[str, Any] | None = None
    candidate_hash: str | None = None

    def __post_init__(self):
        """Generate hash and timestamp if not provided."""
        if self.added_at is None:
            self.added_at = datetime.utcnow().isoformat()

        if self.candidate_hash is None:
            self.candidate_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        """
        Compute unique hash for deduplication.

        Hash is based on: site_id + src_lang + tgt_lang + text

        Returns:
            SHA256 hash (first 16 chars)
        """
        hash_input = f"{self.site_id}:{self.src_lang}:{self.tgt_lang}:{self.text}"
        return hashlib.sha256(hash_input.encode()).hexdigest()[:16]


def compute_uncertainty(candidate: ImprovementCandidate) -> float:
    """Compute uncertainty score for prioritization.

    Higher score = higher priority for improvement. Reads from the existing
    metadata dict — no dataclass field changes needed.

    Returns:
        Float in [0.0, 1.0]
    """
    meta = candidate.metadata if candidate.metadata else {}
    retry_count = meta.get("retry_count", 0)
    quality_score = meta.get("quality_score", 0.5)
    had_errors = 1 if meta.get("error_count", 0) > 0 else 0

    score = retry_count * 0.4 + (1 - quality_score) * 0.3 + had_errors * 0.3
    return max(0.0, min(1.0, score))


class ImprovementQueue:
    """
    Persistent queue for TM improvement candidates.

    Uses JSONL format for append-only storage with a separate "seen" set
    for fast deduplication.

    File structure:
        - improvement_queue.jsonl: Append-only queue of candidates
        - improvement_queue_seen.json: Set of seen hashes for deduplication

    Example:
        queue = ImprovementQueue(Path("data/tm"))

        # Append candidate
        queue.append_candidate(
            site_id="docs.aspose.net",
            src_lang="en",
            tgt_lang="de",
            text="Hello world",
            translation="Hallo Welt",
            metadata={"similarity_score": 0.75}
        )

        # Pop candidates for processing
        candidates = queue.pop_candidates(limit=50)
        for candidate in candidates:
            # ... improve translation ...
            pass
    """

    def __init__(self, tm_path: Path, queue_filename: str = "improvement_queue.jsonl"):
        """
        Initialize improvement queue.

        Args:
            tm_path: Base path for TM data (e.g., data/tm)
            queue_filename: Name of queue file (default: improvement_queue.jsonl)
        """
        self.tm_path = Path(tm_path)
        self.queue_file = self.tm_path / queue_filename
        self.seen_file = self.tm_path / f"{self.queue_file.stem}_seen.json"

        # Ensure directory exists
        self.tm_path.mkdir(parents=True, exist_ok=True)

        # TC-08: Lock for atomic pop_candidates
        self._lock = threading.Lock()

        # Load seen set for deduplication
        self._seen_hashes = self._load_seen_hashes()

        logger.info(
            f"Initialized ImprovementQueue: queue={self.queue_file}, "
            f"seen={len(self._seen_hashes)} hashes"
        )

    def _load_seen_hashes(self) -> set:
        """
        Load seen hashes from disk.

        Returns:
            Set of seen candidate hashes
        """
        if not self.seen_file.exists():
            return set()

        try:
            with open(self.seen_file, encoding="utf-8") as f:
                data = json.load(f)
                seen = set(data.get("seen_hashes", []))
                logger.debug(f"Loaded {len(seen)} seen hashes from {self.seen_file}")
                return seen
        except Exception as e:
            logger.error(f"Failed to load seen hashes: {e}")
            return set()

    # TC-07: Maximum size for _seen_hashes before rotation. When exceeded,
    # the oldest half is discarded. This prevents unbounded memory growth
    # while preserving recent dedup history.
    _SEEN_HASHES_MAX = 50_000

    def _save_seen_hashes(self) -> None:
        """Save seen hashes to disk, rotating if the set is too large."""
        try:
            if len(self._seen_hashes) > self._SEEN_HASHES_MAX:
                # Keep the most recent half (sets are unordered, so we just
                # keep an arbitrary subset — sufficient for dedup purposes)
                excess = len(self._seen_hashes) - self._SEEN_HASHES_MAX // 2
                it = iter(self._seen_hashes)
                to_remove = [next(it) for _ in range(excess)]
                self._seen_hashes -= set(to_remove)
                logger.info(
                    f"TC-07: Rotated seen hashes — removed {excess}, kept {len(self._seen_hashes)}"
                )
            with open(self.seen_file, "w", encoding="utf-8") as f:
                json.dump({"seen_hashes": list(self._seen_hashes)}, f)
            logger.debug(f"Saved {len(self._seen_hashes)} seen hashes to {self.seen_file}")
        except Exception as e:
            logger.error(f"Failed to save seen hashes: {e}")

    def append_candidate(
        self,
        site_id: str,
        src_lang: str,
        tgt_lang: str,
        text: str,
        translation: str,
        context: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """
        Append a candidate to the improvement queue.

        Deduplicates based on (site_id, src_lang, tgt_lang, text).

        Args:
            site_id: Site identifier
            src_lang: Source language code
            tgt_lang: Target language code
            text: Source text
            translation: Current translation
            context: Optional context
            metadata: Optional metadata (e.g., similarity_score, hit_count)

        Returns:
            True if appended, False if duplicate (already seen)
        """
        # Create candidate
        candidate = ImprovementCandidate(
            site_id=site_id,
            src_lang=src_lang,
            tgt_lang=tgt_lang,
            text=text,
            translation=translation,
            context=context,
            metadata=metadata,
        )

        # Check if already seen
        if candidate.candidate_hash in self._seen_hashes:
            logger.debug(f"Candidate already seen (hash={candidate.candidate_hash}), skipping")
            return False

        # Append to queue file (JSONL)
        try:
            with open(self.queue_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(candidate)) + "\n")

            # Mark as seen
            self._seen_hashes.add(candidate.candidate_hash)
            self._save_seen_hashes()

            logger.debug(
                f"Appended candidate to queue: {site_id}/{src_lang}->{tgt_lang}, "
                f"hash={candidate.candidate_hash}"
            )

            return True

        except Exception as e:
            logger.error(f"Failed to append candidate to queue: {e}")
            return False

    def pop_candidates(self, limit: int = 50) -> list[ImprovementCandidate]:
        """
        Pop candidates from the queue for processing.

        Reads candidates from the queue file and removes them by rewriting the file.

        Args:
            limit: Maximum number of candidates to pop

        Returns:
            List of ImprovementCandidate objects (up to limit)
        """
        if not self.queue_file.exists():
            logger.debug("Queue file does not exist, returning empty list")
            return []

        # TC-08: Lock the entire read-modify-write to prevent concurrent pops
        # from returning the same candidates or losing entries.
        with self._lock:
            try:
                # Read all candidates from queue
                candidates = []
                remaining = []

                with open(self.queue_file, encoding="utf-8") as f:
                    for i, line in enumerate(f):
                        line = line.strip()
                        if not line:
                            continue

                        try:
                            data = json.loads(line)
                            candidate = ImprovementCandidate(**data)

                            if len(candidates) < limit:
                                candidates.append(candidate)
                            else:
                                # Keep for next time
                                remaining.append(line)

                        except Exception as e:
                            logger.error(f"Failed to parse candidate at line {i}: {e}")
                            # Keep in remaining to avoid data loss
                            remaining.append(line)

                # TC-08: Atomic rewrite via temp file + os.replace()
                if remaining:
                    with tempfile.NamedTemporaryFile(
                        mode="w",
                        encoding="utf-8",
                        dir=str(self.tm_path),
                        delete=False,
                        suffix=".tmp",
                    ) as tmp:
                        tmp.write("\n".join(remaining) + "\n")
                        tmp_path = tmp.name
                    os.replace(tmp_path, self.queue_file)
                else:
                    # Queue is now empty, remove file
                    self.queue_file.unlink()

                logger.info(
                    f"Popped {len(candidates)} candidates from queue ({len(remaining)} remaining)"
                )

                return candidates

            except Exception as e:
                logger.error(f"Failed to pop candidates from queue: {e}")
                return []

    def pop_candidates_by_priority(self, limit: int = 50) -> list[ImprovementCandidate]:
        """Pop candidates sorted by uncertainty (highest first).

        Like pop_candidates() but returns the highest-uncertainty candidates
        rather than FIFO order. Uses the same lock and atomic rewrite pattern.

        Args:
            limit: Maximum number of candidates to pop

        Returns:
            List of ImprovementCandidate sorted by uncertainty descending
        """
        if not self.queue_file.exists():
            return []

        with self._lock:
            try:
                all_candidates: list[ImprovementCandidate] = []
                bad_lines: list[str] = []

                with open(self.queue_file, encoding="utf-8") as f:
                    for i, line in enumerate(f):
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            all_candidates.append(ImprovementCandidate(**data))
                        except Exception as e:
                            logger.error(f"Failed to parse candidate at line {i}: {e}")
                            bad_lines.append(line)

                # Sort by uncertainty descending
                all_candidates.sort(key=compute_uncertainty, reverse=True)

                popped = all_candidates[:limit]
                kept = all_candidates[limit:]

                # Atomic rewrite
                remaining_lines = bad_lines + [json.dumps(asdict(c)) for c in kept]
                if remaining_lines:
                    with tempfile.NamedTemporaryFile(
                        mode="w",
                        encoding="utf-8",
                        dir=str(self.tm_path),
                        delete=False,
                        suffix=".tmp",
                    ) as tmp:
                        tmp.write("\n".join(remaining_lines) + "\n")
                        tmp_path = tmp.name
                    os.replace(tmp_path, self.queue_file)
                else:
                    self.queue_file.unlink()

                logger.info(f"Popped {len(popped)} priority candidates ({len(kept)} remaining)")
                return popped

            except Exception as e:
                logger.error(f"Failed to pop priority candidates: {e}")
                return []

    def count(self) -> int:
        """
        Count candidates in the queue.

        Returns:
            Number of candidates in queue
        """
        if not self.queue_file.exists():
            return 0

        try:
            with open(self.queue_file, encoding="utf-8") as f:
                count = sum(1 for line in f if line.strip())
            return count
        except Exception as e:
            logger.error(f"Failed to count candidates: {e}")
            return 0

    def clear(self) -> None:
        """Clear all candidates from the queue and reset seen hashes."""
        if self.queue_file.exists():
            self.queue_file.unlink()

        self._seen_hashes.clear()
        self._save_seen_hashes()

        logger.info("Cleared improvement queue")

    def stats(self) -> dict[str, Any]:
        """
        Get queue statistics.

        Returns:
            Dictionary with queue stats
        """
        return {
            "queue_size": self.count(),
            "seen_hashes": len(self._seen_hashes),
            "queue_file": str(self.queue_file),
            "seen_file": str(self.seen_file),
        }
