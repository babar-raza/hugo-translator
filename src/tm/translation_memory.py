"""
Unified Translation Memory Interface.

Coordinates L1 (cache), L2 (persistent), and L3 (semantic) layers.
"""
from typing import Any, Dict, List, Optional

from .l1_cache import L1Cache
from .l2_persistent import L2PersistentTM, TranslationEntry
try:
    from .l3_semantic import L3SemanticTM
except Exception:
    L3SemanticTM = None  # type: ignore
from .models import LookupRequest, LookupResult, TMStats
from .override_controller import OverrideController, OverrideConfig, OverrideMode
from .improvement_queue import ImprovementQueue


class TranslationMemory:
    """
    Unified interface over L1/L2/L3 TM layers.

    Implements intelligent layered lookup strategy:
    1. Check L1 cache (fastest, in-memory)
    2. Check L2 persistent (exact match, durable)
    3. Check L3 semantic (fuzzy match, optional)
    4. Update L1 cache with hits

    All writes go to L2 (and optionally L3).

    Override modes allow selective cache bypass/refresh:
    - NORMAL: Standard cache behavior
    - BYPASS: Skip cache lookup entirely
    - REFRESH: Skip cache, force retranslation, update cache
    - VALIDATE: Use cache but also translate for comparison
    """

    def __init__(
        self,
        l1_cache: L1Cache,
        l2_persistent: L2PersistentTM,
        l3_semantic: Optional[L3SemanticTM] = None,
        override_controller: Optional[OverrideController] = None,
        improvement_queue: Optional[ImprovementQueue] = None,
    ):
        """
        Initialize unified TM.

        Args:
            l1_cache: In-memory LRU cache
            l2_persistent: LMDB persistent storage
            l3_semantic: Optional semantic search index
            override_controller: Optional override controller for cache bypass
            improvement_queue: Optional improvement queue for LLM-based improvements
        """
        self.l1 = l1_cache
        self.l2 = l2_persistent
        self.l3 = l3_semantic
        self.override = override_controller or OverrideController()
        self.improvement_queue = improvement_queue

        # Statistics
        self._total_lookups = 0
        self._total_hits = 0
        self._override_bypasses = 0

    def lookup(
        self,
        site_id: str,
        src_lang: str,
        tgt_lang: str,
        text: str,
        context: Optional[str] = None,
        use_semantic: bool = True,
        semantic_threshold: float = 0.80,
        lookup_context: Optional[Dict[str, Any]] = None,
    ) -> LookupResult:
        """
        Unified lookup across all TM layers.

        Args:
            site_id: Site identifier
            src_lang: Source language
            tgt_lang: Target language
            text: Text to look up
            context: Optional context for disambiguation
            use_semantic: Whether to use L3 semantic search
            semantic_threshold: Minimum similarity for L3 matches
            lookup_context: Optional context for override filtering (e.g., frontmatter_key)

        Returns:
            LookupResult with translation and provenance
        """
        self._total_lookups += 1

        # Check override controller - should we bypass cache entirely?
        if self.override.should_bypass_lookup(text, tgt_lang, lookup_context):
            self._override_bypasses += 1
            return LookupResult(
                hit=False,
                source="override_bypass",
                confidence=0.0,
            )

        # Layer 1: Check cache
        cached = self.l1.get(site_id, src_lang, tgt_lang, text)
        if cached:
            self._total_hits += 1
            return LookupResult(
                hit=True,
                translation=cached,
                source="l1_cache",
                confidence=1.0,
            )

        # Layer 2: Check persistent exact match
        entry = self.l2.exact_lookup(site_id, src_lang, tgt_lang, text, context)
        if entry:
            # Populate L1 cache
            self.l1.put(site_id, src_lang, tgt_lang, text, entry.translation)
            self._total_hits += 1
            return LookupResult(
                hit=True,
                translation=entry.translation,
                source="l2_exact",
                confidence=1.0,
                metadata=entry.metadata,
            )

        # Layer 3: Try semantic search (if enabled)
        if use_semantic and self.l3 is not None:
            matches = self.l3.semantic_search(
                site_id=site_id,
                src_lang=src_lang,
                tgt_lang=tgt_lang,
                query_text=text,
                k=5,
                threshold=semantic_threshold,
            )

            if matches:
                best_match = matches[0]

                # Populate L1 cache with best match
                self.l1.put(
                    site_id, src_lang, tgt_lang, text, best_match.translation
                )
                self._total_hits += 1

                return LookupResult(
                    hit=True,
                    translation=best_match.translation,
                    source="l3_semantic",
                    confidence=best_match.similarity,
                    candidates=matches,
                    metadata=best_match.metadata,
                )

        # No hit
        return LookupResult(
            hit=False,
            source="none",
            confidence=0.0,
        )

    def store(
        self,
        site_id: str,
        src_lang: str,
        tgt_lang: str,
        text: str,
        translation: str,
        context: Optional[str] = None,
        metadata: Optional[Dict] = None,
        store_context: Optional[Dict[str, Any]] = None,
        force_update: bool = False,
    ) -> bool:
        """
        Store translation in all applicable layers.

        Args:
            site_id: Site identifier
            src_lang: Source language
            tgt_lang: Target language
            text: Source text
            translation: Translated text
            context: Optional context
            metadata: Optional metadata
            store_context: Optional context for override filtering (e.g., frontmatter_key)
            force_update: If True, overwrite existing entries; if False, skip existing

        Returns:
            True if stored, False if skipped (entry exists and not force_update)
        """
        # Check override controller for update permission
        should_update = force_update or self.override.should_update_cache(
            text, tgt_lang, store_context
        )

        # Store in L1 cache (always update L1 - it's just a cache)
        self.l1.put(site_id, src_lang, tgt_lang, text, translation)

        # Store in L2 persistent (respect overwrite setting)
        stored = self.l2.store(
            site_id=site_id,
            src_lang=src_lang,
            tgt_lang=tgt_lang,
            text=text,
            translation=translation,
            context=context,
            metadata=metadata,
            overwrite=should_update,
        )

        # Store in L3 semantic (if available and L2 was stored)
        if stored and self.l3 is not None:
            # Generate entry_id for L3 (same format as batch_store)
            entry_id = f"{site_id}:{src_lang}:{tgt_lang}:{hash(text)}"
            self.l3.add_entry(
                entry_id=entry_id,
                site_id=site_id,
                src_lang=src_lang,
                tgt_lang=tgt_lang,
                source_text=text,
                translation=translation,
                context=context,
                metadata=metadata,
            )

        # Append to improvement queue (if enabled and L2 was stored)
        # This allows the TM improvement worker to enhance translations later
        if stored and self.improvement_queue is not None:
            # Extract similarity score from metadata if available (from L3 semantic match)
            similarity_score = None
            if metadata and "similarity_score" in metadata:
                similarity_score = metadata["similarity_score"]

            # Queue candidate with metadata for improvement worker
            queue_metadata = metadata.copy() if metadata else {}
            if similarity_score is not None:
                queue_metadata["similarity_score"] = similarity_score

            self.improvement_queue.append_candidate(
                site_id=site_id,
                src_lang=src_lang,
                tgt_lang=tgt_lang,
                text=text,
                translation=translation,
                context=context,
                metadata=queue_metadata,
            )

        return stored

    def batch_lookup(
        self,
        requests: List[LookupRequest],
        use_semantic: bool = True,
        semantic_threshold: float = 0.80,
    ) -> List[LookupResult]:
        """
        Optimize bulk lookups.

        Args:
            requests: List of lookup requests
            use_semantic: Whether to use L3 semantic search
            semantic_threshold: Minimum similarity for L3 matches

        Returns:
            List of lookup results in same order as requests
        """
        results = []

        for req in requests:
            result = self.lookup(
                site_id=req.site_id,
                src_lang=req.src_lang,
                tgt_lang=req.tgt_lang,
                text=req.text,
                context=req.context,
                use_semantic=use_semantic,
                semantic_threshold=semantic_threshold,
            )
            results.append(result)

        return results

    def batch_store(self, entries: List[TranslationEntry]) -> int:
        """
        Efficiently store many entries at once.

        Args:
            entries: List of TranslationEntry objects

        Returns:
            Number of entries stored
        """
        # Store in L2 persistent (batch)
        count = self.l2.batch_store(entries)

        # Store in L3 semantic (batch)
        if self.l3 is not None:
            l3_entries = [
                {
                    "entry_id": f"{e.site_id}:{e.src_lang}:{e.tgt_lang}:{hash(e.source_text)}",
                    "site_id": e.site_id,
                    "src_lang": e.src_lang,
                    "tgt_lang": e.tgt_lang,
                    "source_text": e.source_text,
                    "translation": e.translation,
                    "context": e.context,
                    "metadata": e.metadata,
                }
                for e in entries
            ]
            self.l3.batch_add(l3_entries)

        # Note: L1 cache not populated in batch (only populated on lookup)

        return count

    def stats(self) -> TMStats:
        """
        Aggregate stats from all layers.

        Returns:
            TMStats with combined statistics
        """
        # L1 stats
        l1_stats = self.l1.stats()

        # L2 stats
        l2_size = len(self.l2)

        # L3 stats
        l3_size = len(self.l3) if self.l3 is not None else 0

        # Calculate overall hit rate
        overall_hit_rate = (
            self._total_hits / self._total_lookups if self._total_lookups > 0 else 0.0
        )

        return TMStats(
            # L1 Cache
            l1_size=l1_stats["size"],
            l1_max_size=l1_stats["max_size"],
            l1_hits=l1_stats["hits"],
            l1_misses=l1_stats["misses"],
            l1_evictions=l1_stats["evictions"],
            l1_hit_rate=l1_stats["hit_rate"],
            # L2 Persistent
            l2_size=l2_size,
            # L3 Semantic
            l3_size=l3_size,
            # Combined
            total_lookups=self._total_lookups,
            total_hits=self._total_hits,
            overall_hit_rate=overall_hit_rate,
        )

    def clear(self) -> None:
        """Clear all TM layers."""
        self.l1.clear()
        self.l2.clear()
        if self.l3 is not None:
            self.l3.clear()

        # Reset stats
        self._total_lookups = 0
        self._total_hits = 0
        self._override_bypasses = 0

    def close(self) -> None:
        """Close all resources."""
        self.l2.close()
        if self.l3 is not None:
            self.l3.save_index()

    def set_override_mode(
        self,
        mode: OverrideMode,
        filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Set the override mode for TM operations.

        Args:
            mode: Override mode (NORMAL, BYPASS, REFRESH, VALIDATE)
            filters: Optional filter configuration dict with keys:
                - source_patterns: List of regex patterns to match source text
                - target_langs: List of target language codes
                - frontmatter_keys: List of frontmatter keys to match
        """
        from .override_controller import OverrideConfig, OverrideFilter

        config = OverrideConfig(mode=mode)

        if filters:
            config.filters = OverrideFilter(
                source_patterns=filters.get("source_patterns"),
                target_langs=filters.get("target_langs"),
                frontmatter_keys=filters.get("frontmatter_keys"),
            )

        self.override = OverrideController(config)

    def get_override_stats(self) -> Dict[str, Any]:
        """
        Get override-related statistics.

        Returns:
            Dict with override stats including mode, bypasses, and filter info
        """
        stats = self.override.get_stats()
        stats["override_bypasses"] = self._override_bypasses
        return stats
