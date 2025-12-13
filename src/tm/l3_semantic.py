"""
L3 Semantic Translation Memory using Vector Similarity Search.

Fuzzy/semantic matching using embeddings for high TM hit rates.
"""
import json
import pickle
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer


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
    ):
        """
        Initialize L3 semantic TM.

        Args:
            index_path: Directory to store index and metadata
            embedding_model: Sentence transformer model name
            use_gpu: Whether to use GPU for embeddings (if available)
            use_faiss_gpu: Whether to use FAISS GPU index (requires faiss-gpu)
        """
        self.index_path = Path(index_path)
        self.index_path.mkdir(parents=True, exist_ok=True)

        # Store model name for config
        self.embedding_model_name = embedding_model

        # Determine device for embeddings
        if use_gpu:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
            if device == "cpu":
                import logging
                logger = logging.getLogger(__name__)
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

        # Try to load existing index
        if (self.index_path / "index.faiss").exists():
            self.load_index()
        else:
            self._create_index()

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
        Embed source text and add to index.

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
        if self.index is None or self.index.ntotal == 0:
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

        return len(entries)

    def save_index(self) -> None:
        """Persist index and metadata to disk."""
        with self._lock:
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

            faiss.write_index(index_to_save, str(index_file))

            # Save metadata
            metadata_file = self.index_path / "metadata.pkl"
            with open(metadata_file, "wb") as f:
                pickle.dump(self.metadata, f)

            # Save config
            config_file = self.index_path / "config.json"
            config = {
                "embedding_dim": self.embedding_dim,
                "num_entries": self.index.ntotal,
                "embedding_model": self.embedding_model_name,
            }
            with open(config_file, "w") as f:
                json.dump(config, f, indent=2)

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
        """Context manager exit - save index."""
        self.save_index()
