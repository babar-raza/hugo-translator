"""
Translation Memory module.
"""
from .l1_cache import L1Cache
from .l2_persistent import L2PersistentTM, TranslationEntry
try:
    from .l3_semantic import L3SemanticTM, SemanticMatch
except Exception:
    # FAISS may be unavailable; allow L1/L2-only operation
    L3SemanticTM = None
    SemanticMatch = None
from .models import LookupRequest, LookupResult, TMStats
from .translation_memory import TranslationMemory

__all__ = [
    "L1Cache",
    "L2PersistentTM",
    "TranslationEntry",
    "L3SemanticTM",
    "SemanticMatch",
    "LookupRequest",
    "LookupResult",
    "TMStats",
    "TranslationMemory",
]
