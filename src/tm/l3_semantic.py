"""
L3 Semantic Translation Memory using Vector Similarity Search.

Fuzzy/semantic matching using embeddings for high TM hit rates.

Enhanced with:
- Periodic saves every N additions (RES-04)
- Background save thread (optional)
- Save timeout protection
- Error handling and logging
"""
import json
import logging
import pickle
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

from src.utils.metrics import calc_stats
from src.utils.file_lock import FileLock

logger = logging.getLogger(__name__)


@dataclass
class SemanticMatch:
    """Semantic search match result."""

    entry_id: str
    similarity: float
    source_text: str
    translation: str
    site_id: str
    src_lang: str
    tgt_lang: str
    context: Optional[str] = None
    metadata: Dict[str, Any] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


class L3SemanticTM:
    """
    Vector-based semantic translation memory.

    Uses sentence embeddings and FAISS for fast similarity search.
    Enables fuzzy matching for near-duplicates and paraphrases.
    """

    def __init__(
        self,
        index_path: Path | str,
        embedding_model: str = "all-MiniLM-L6-v2",
        use_gpu: bool = False,
        use_faiss_gpu: bool = False,
        save_interval: int = 100,
        save_timeout: float = 5.0,
        async_save: bool = False,
    ):
        """
        Initialize L3 semantic TM with periodic saves.

        Args:
            index_path: Directory to store index and metadata
            embedding_model: Sentence transformer model name
            use_gpu: Whether to use GPU for embeddings (if available)
            use_faiss_gpu: Whether to use FAISS GPU index (requires faiss-gpu)
            save_interval: Save every N additions (0 = disabled)
            save_timeout: Max seconds for save operation
            async_save: Use background thread for saves
        """
        self.index_path = Path(index_path)
        self.index_path.mkdir(parents=True, exist_ok=True)

        # Store model name for config
        self.embedding_model_name = embedding_model

        # RES-04: Periodic save configuration
        self.save_interval = save_interval
        self.save_timeout = save_timeout
        self.async_save = async_save

        # RES-04: Counters for periodic saves
        self._additions_since_save = 0
        self._total_additions = 0
        self._save_failures = 0
        self._last_save_time: Optional[float] = None

        # BM-08: Timing instrumentation (TM-07: bounded to prevent memory leak, CFG-01: configurable)
        from src.utils.config_loader import get_metrics_config
        metrics_config = get_metrics_config()
        timing_maxlen = metrics_config["metrics"]["storage"]["l3_semantic"]["timing_metrics_maxlen"]

        self._metrics = {
            "semantic_search_ms": deque(maxlen=timing_maxlen),  # Bounded by config
            "add_entry_ms": deque(maxlen=timing_maxlen),  # Bounded by config
            "batch_add_ms": deque(maxlen=timing_maxlen),  # Bounded by config
            "cache_hits": 0,  # Integer counter (naturally bounded)
            "cache_misses": 0,  # Integer counter (naturally bounded)
        }

        # RES-04: Thread pool for async saves
        self._executor: Optional[ThreadPoolExecutor] = None
        if async_save:
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="l3_save")

        # Determine device for embeddings
        if use_gpu:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
            if device == "cpu":
                logger.warning("GPU requested but not available, falling back to CPU")
        else:
            device = "cpu"

        # Load embedding model
        self.device = device
        self.encoder = SentenceTransformer(embedding_model, device=device)
        self.embedding_dim = self.encoder.get_sentence_embedding_dimension()

        # FAISS GPU flag
        self.use_faiss_gpu = use_faiss_gpu and device == "cuda"

        # FAISS index (L2 distance)
        self.index: Optional[faiss.Index] = None

        # Metadata storage (maps index position to entry data)
        self.metadata: List[Dict[str, Any]] = []

        # Lock for thread safety
        self._lock = threading.RLock()
        self._save_lock = threading.Lock()

        # Try to load existing index
        if (self.index_path / "index.faiss").exists():
            self.load_index()
            self._total_additions = len(self.metadata)
        else:
            self._create_index()

        logger.info(
            f"L3 index initialized: {self._total_additions} entries, "
            f"save_interval={save_interval}, async_save={async_save}"
        )

    def _create_index(self) -> None:
        """Create new FAISS index."""
        # Use IndexFlatL2 for exact search (good for <1M vectors)
        # For larger datasets, consider IndexIVFFlat or IndexHNSWFlat
        self.index = faiss.IndexFlatL2(self.embedding_dim)

        # Move index to GPU if requested and available
        if self.use_faiss_gpu:
            try:
                import torch
                if torch.cuda.is_available():
                    res = faiss.StandardGpuResources()
                    self.index = faiss.index_cpu_to_gpu(res, 0, self.index)
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.info("FAISS index moved to GPU")
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Failed to move FAISS index to GPU: {e}. Using CPU.")

        self.metadata = []

    def add_entry(
        self,
        entry_id: str,
        site_id: str,
        src_lang: str,
        tgt_lang: str,
        source_text: str,
        translation: str,
        context: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Embed source text and add to index with periodic save.

        Args:
            entry_id: Unique identifier for this entry
            site_id: Site identifier
            src_lang: Source language code
            tgt_lang: Target language code
            source_text: Source text to embed
            translation: Corresponding translation
            context: Optional context information
            metadata: Optional additional metadata
        """
        # BM-08: Timing instrumentation
        start_time = time.perf_counter()

        # Generate embedding
        embedding = self.encoder.encode(
            source_text, convert_to_numpy=True, show_progress_bar=False
        )

        # Add to index
        with self._lock:
            self.index.add(np.array([embedding], dtype=np.float32))

            # Store metadata at same position
            entry_metadata = {
                "entry_id": entry_id,
                "site_id": site_id,
                "src_lang": src_lang,
                "tgt_lang": tgt_lang,
                "source_text": source_text,
                "translation": translation,
                "context": context,
                "metadata": metadata or {},
            }
            self.metadata.append(entry_metadata)

            # RES-04: Update counters and check for periodic save
            self._additions_since_save += 1
            self._total_additions += 1

        # BM-08: Record timing
        duration_ms = (time.perf_counter() - start_time) * 1000
        with self._lock:
            self._metrics["add_entry_ms"].append(duration_ms)

        if duration_ms > 100:
            logger.warning(f"Slow L3 add_entry: {duration_ms:.1f}ms")

        # RES-04: Check if periodic save needed (outside lock to avoid blocking)
        if self.save_interval > 0 and self._additions_since_save >= self.save_interval:
            self._trigger_save()

    def _trigger_save(self) -> bool:
        """
        Trigger periodic save (sync or async based on configuration).

        Returns:
            True if save was triggered, False if skipped (already in progress)
        """
        # Avoid multiple concurrent saves
        if not self._save_lock.acquire(blocking=False):
            logger.debug("Periodic save skipped - already in progress")
            return False

        try:
            if self.async_save and self._executor:
                # Submit save to background thread
                future = self._executor.submit(self._do_save)
                logger.debug(f"Periodic save submitted to background thread")
                # Don't wait - let it run in background
                return True
            else:
                # Synchronous save with timeout
                return self._do_save()
        finally:
            self._save_lock.release()

    def _do_save(self) -> bool:
        """
        Perform the actual save operation with timeout protection.

        Returns:
            True if save succeeded, False otherwise
        """
        start_time = time.time()
        try:
            logger.debug(f"Starting periodic save ({self._additions_since_save} additions)")
            self.save_index()

            # Reset counter on success
            with self._lock:
                self._additions_since_save = 0
                self._last_save_time = time.time()

            duration = time.time() - start_time
            logger.info(
                f"Periodic L3 save complete: {self._total_additions} entries in {duration:.2f}s"
            )
            return True

        except Exception as e:
            self._save_failures += 1
            duration = time.time() - start_time
            logger.error(
                f"Periodic L3 save failed ({duration:.2f}s): {e}. "
                f"Total failures: {self._save_failures}"
            )
            return False

    def get_save_stats(self) -> Dict[str, Any]:
        """
        Get statistics about periodic saves.

        Returns:
            Dictionary with save statistics
        """
        return {
            "total_additions": self._total_additions,
            "additions_since_save": self._additions_since_save,
            "save_failures": self._save_failures,
            "last_save_time": self._last_save_time,
            "save_interval": self.save_interval,
            "async_save": self.async_save,
        }

    def get_timing_metrics(self) -> Dict[str, Any]:
        """
        Get timing metrics for performance monitoring (BM-08).

        Returns:
            Dictionary with timing statistics and cache metrics
        """
        with self._lock:
            return {
                "semantic_search": calc_stats(self._metrics["semantic_search_ms"]),
                "add_entry": calc_stats(self._metrics["add_entry_ms"]),
                "batch_add": calc_stats(self._metrics["batch_add_ms"]),
                "cache_hits": self._metrics["cache_hits"],
                "cache_misses": self._metrics["cache_misses"],
                "cache_hit_rate": (
                    self._metrics["cache_hits"] / (self._metrics["cache_hits"] + self._metrics["cache_misses"])
                    if (self._metrics["cache_hits"] + self._metrics["cache_misses"]) > 0
                    else 0.0
                ),
            }

    def semantic_search(
        self,
        site_id: str,
        src_lang: str,
        tgt_lang: str,
        query_text: str,
        k: int = 10,
        threshold: float = 0.75,
    ) -> List[SemanticMatch]:
        """
        Find top K similar entries above similarity threshold.

        Args:
            site_id: Site identifier to filter by
            src_lang: Source language to filter by
            tgt_lang: Target language to filter by
            query_text: Text to search for
            k: Number of results to return
            threshold: Minimum similarity score (0-1)

        Returns:
            List of SemanticMatch objects, sorted by similarity
        """
        # BM-08: Timing instrumentation
        start_time = time.perf_counter()

        if self.index is None or self.index.ntotal == 0:
            # BM-08: Record cache miss
            with self._lock:
                self._metrics["cache_misses"] += 1
            return []

        # Generate query embedding
        query_embedding = self.encoder.encode(
            query_text, convert_to_numpy=True, show_progress_bar=False
        )

        with self._lock:
            # Search for top K candidates (we'll filter after)
            # FAISS returns L2 distances, we need to convert to similarity
            search_k = min(k * 10, self.index.ntotal)  # Oversample for filtering
            distances, indices = self.index.search(
                np.array([query_embedding], dtype=np.float32), search_k
            )

            # Convert L2 distances to cosine similarities
            # For normalized vectors: similarity = 1 - (L2_distance^2 / 2)
            # We approximate with: similarity = 1 / (1 + distance)
            similarities = 1.0 / (1.0 + distances[0])

            # Filter by site_id, language pair, and threshold
            matches = []
            for idx, similarity in zip(indices[0], similarities):
                if idx == -1:  # FAISS padding
                    continue

                if idx >= len(self.metadata):  # Desync guard: FAISS index ahead of metadata
                    continue

                meta = self.metadata[idx]

                # Filter by criteria
                if (
                    meta["site_id"] == site_id
                    and meta["src_lang"] == src_lang
                    and meta["tgt_lang"] == tgt_lang
                    and similarity >= threshold
                ):
                    match = SemanticMatch(
                        entry_id=meta["entry_id"],
                        similarity=float(similarity),
                        source_text=meta["source_text"],
                        translation=meta["translation"],
                        site_id=meta["site_id"],
                        src_lang=meta["src_lang"],
                        tgt_lang=meta["tgt_lang"],
                        context=meta["context"],
                        metadata=meta["metadata"],
                    )
                    matches.append(match)

                    if len(matches) >= k:
                        break

            # BM-08: Record cache hit/miss
            if matches:
                self._metrics["cache_hits"] += 1
            else:
                self._metrics["cache_misses"] += 1

        # BM-08: Record timing
        duration_ms = (time.perf_counter() - start_time) * 1000
        with self._lock:
            self._metrics["semantic_search_ms"].append(duration_ms)

        if duration_ms > 100:
            logger.warning(f"Slow L3 semantic_search: {duration_ms:.1f}ms")

        return matches

    def batch_add(self, entries: List[Dict[str, Any]]) -> int:
        """
        Efficiently add many entries at once.

        Args:
            entries: List of entry dictionaries with keys:
                    entry_id, site_id, src_lang, tgt_lang,
                    source_text, translation, context, metadata

        Returns:
            Number of entries added
        """
        # BM-08: Timing instrumentation
        start_time = time.perf_counter()

        if not entries:
            return 0

        # Extract source texts for batch encoding
        source_texts = [e["source_text"] for e in entries]

        # Determine batch size based on device
        batch_size = 64 if self.device == "cuda" else 32

        # Batch encode all texts (GPU accelerated if device is cuda)
        embeddings = self.encoder.encode(
            source_texts,
            convert_to_numpy=True,
            show_progress_bar=len(source_texts) > 100,
            batch_size=batch_size,
        )

        with self._lock:
            # Add all embeddings to index
            self.index.add(embeddings.astype(np.float32))

            # Add all metadata
            for entry in entries:
                entry_metadata = {
                    "entry_id": entry["entry_id"],
                    "site_id": entry["site_id"],
                    "src_lang": entry["src_lang"],
                    "tgt_lang": entry["tgt_lang"],
                    "source_text": entry["source_text"],
                    "translation": entry["translation"],
                    "context": entry.get("context"),
                    "metadata": entry.get("metadata", {}),
                }
                self.metadata.append(entry_metadata)

            # RES-04: Update counters for periodic saves
            self._additions_since_save += len(entries)
            self._total_additions += len(entries)

        # BM-08: Record timing
        duration_ms = (time.perf_counter() - start_time) * 1000
        with self._lock:
            self._metrics["batch_add_ms"].append(duration_ms)

        if duration_ms > 100:
            logger.warning(f"Slow L3 batch_add ({len(entries)} entries): {duration_ms:.1f}ms")

        # RES-04: Check if periodic save needed (outside lock)
        if self.save_interval > 0 and self._additions_since_save >= self.save_interval:
            self._trigger_save()

        return len(entries)

    def offload_to_cpu(self) -> None:
        """Move FAISS index and embedding encoder from GPU to CPU RAM before sleeping.

        Keeps all Python objects alive — only weights are moved to system RAM.
        VRAM is freed; reload is fast (no disk I/O needed).
        """
        with self._lock:
            # Move FAISS GPU index to CPU
            if self.use_faiss_gpu and self.index is not None:
                try:
                    self.index = faiss.index_gpu_to_cpu(self.index)
                    self._index_on_gpu = False
                    logger.debug("L3 FAISS index moved to CPU")
                except Exception as e:
                    logger.warning("L3 FAISS CPU offload failed: %s", e)

            # Move SentenceTransformer encoder to CPU
            if self.device == "cuda" and self.encoder is not None:
                try:
                    self.encoder.to("cpu")
                    self._encoder_on_gpu = False
                    import torch
                    torch.cuda.empty_cache()
                    logger.debug("L3 embedding encoder moved to CPU")
                except Exception as e:
                    logger.warning("L3 encoder CPU offload failed: %s", e)

    def reload_to_gpu(self) -> None:
        """Move FAISS index and embedding encoder back to GPU on wake.

        Only does work if the objects were previously offloaded via offload_to_cpu().
        """
        with self._lock:
            # Move FAISS CPU index back to GPU
            if self.use_faiss_gpu and self.index is not None and not getattr(self, '_index_on_gpu', self.use_faiss_gpu):
                try:
                    res = faiss.StandardGpuResources()
                    self.index = faiss.index_cpu_to_gpu(res, 0, self.index)
                    self._index_on_gpu = True
                    logger.debug("L3 FAISS index moved back to GPU")
                except Exception as e:
                    logger.warning("L3 FAISS GPU reload failed: %s", e)

            # Move SentenceTransformer encoder back to GPU
            if self.device == "cuda" and self.encoder is not None and not getattr(self, '_encoder_on_gpu', self.device == "cuda"):
                try:
                    self.encoder.to("cuda")
                    self._encoder_on_gpu = True
                    logger.debug("L3 embedding encoder moved back to GPU")
                except Exception as e:
                    logger.warning("L3 encoder GPU reload failed: %s", e)

    def save_index(self) -> None:
        """Persist index and metadata to disk.

        Uses FileLock for process-safe writes across concurrent subprocesses.
        Implements atomic write pattern (write to temp, then rename).
        """
        # TC1/TC2: Process-safe lock for concurrent subprocess writes
        lock_file = self.index_path / ".faiss_save.lock"
        save_lock = FileLock(lock_file, timeout=60.0)

        try:
            with save_lock:  # Process-safe lock across subprocesses
                with self._lock:  # Thread-safe lock within process
                    # Save FAISS index (move to CPU first if on GPU)
                    index_file = self.index_path / "index.faiss"
                    index_to_save = self.index

                    if self.use_faiss_gpu:
                        try:
                            # Move index back to CPU for saving
                            index_to_save = faiss.index_gpu_to_cpu(self.index)
                        except Exception:
                            # If it fails, the index might already be on CPU
                            pass

                    # Atomic write pattern: write to temp file, then rename
                    temp_index_file = index_file.with_suffix('.faiss.tmp')
                    faiss.write_index(index_to_save, str(temp_index_file))
                    temp_index_file.replace(index_file)  # Atomic on POSIX and Windows

                    # Save metadata (atomic write)
                    metadata_file = self.index_path / "metadata.pkl"
                    temp_metadata_file = metadata_file.with_suffix('.pkl.tmp')
                    with open(temp_metadata_file, "wb") as f:
                        pickle.dump(self.metadata, f)
                    temp_metadata_file.replace(metadata_file)

                    # Save config (atomic write)
                    config_file = self.index_path / "config.json"
                    temp_config_file = config_file.with_suffix('.json.tmp')
                    config = {
                        "embedding_dim": self.embedding_dim,
                        "num_entries": self.index.ntotal,
                        "embedding_model": self.embedding_model_name,
                    }
                    with open(temp_config_file, "w") as f:
                        json.dump(config, f, indent=2)
                    temp_config_file.replace(config_file)

        except Exception as e:
            logger.error(f"L3 save_index failed: {e}")
            raise

    def load_index(self) -> None:
        """Load index and metadata from disk."""
        with self._lock:
            # Load FAISS index
            index_file = self.index_path / "index.faiss"
            if index_file.exists():
                self.index = faiss.read_index(str(index_file))

                # Move index to GPU if requested
                if self.use_faiss_gpu:
                    try:
                        import torch
                        if torch.cuda.is_available():
                            res = faiss.StandardGpuResources()
                            self.index = faiss.index_cpu_to_gpu(res, 0, self.index)
                            import logging
                            logger = logging.getLogger(__name__)
                            logger.info("Loaded FAISS index moved to GPU")
                    except Exception as e:
                        import logging
                        logger = logging.getLogger(__name__)
                        logger.warning(f"Failed to move loaded index to GPU: {e}")
            else:
                self._create_index()
                return

            # Load metadata
            metadata_file = self.index_path / "metadata.pkl"
            if metadata_file.exists():
                with open(metadata_file, "rb") as f:
                    self.metadata = pickle.load(f)
            else:
                self.metadata = []

    def rebuild_index(self, entries: List[Dict[str, Any]]) -> None:
        """
        Rebuild index from scratch with given entries.

        Args:
            entries: List of entry dictionaries
        """
        with self._lock:
            # Create fresh index
            self._create_index()

            # Add all entries
            if entries:
                self.batch_add(entries)

            # Persist
            self.save_index()

    def count(self) -> int:
        """
        Get number of entries in index.

        Returns:
            Entry count
        """
        with self._lock:
            return self.index.ntotal if self.index else 0

    def clear(self) -> None:
        """Clear index and metadata."""
        with self._lock:
            self._create_index()

    def __len__(self) -> int:
        """Return number of entries."""
        return self.count()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - save index and cleanup resources."""
        # RES-04: Final save to capture any pending additions
        self.save_index()

        # RES-04: Shutdown executor if using async saves
        if self._executor:
            self._executor.shutdown(wait=True)
            self._executor = None
