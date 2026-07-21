"""
Shared data models for Translation Memory system.
"""
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

try:
    from .l3_semantic import SemanticMatch  # type: ignore
except Exception:
    SemanticMatch = None  # type: ignore


@dataclass
class LookupRequest:
    """Request for TM lookup."""

    site_id: str
    src_lang: str
    tgt_lang: str
    text: str
    context: str | None = None
    field_name: str = ""


@dataclass
class LookupResult:
    """Result of TM lookup with provenance."""

    hit: bool
    translation: str | None = None
    source: Literal["l1_cache", "l2_exact", "l3_semantic", "none"] = "none"
    confidence: float = 0.0  # 1.0 for exact, <1.0 for semantic
    candidates: list[SemanticMatch] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        result = asdict(self)
        # Convert SemanticMatch objects to dicts
        result["candidates"] = [c.to_dict() for c in self.candidates]
        return result


@dataclass
class TMResult:
    """Simplified TM result for L4 LLM adaptation."""

    hit: bool
    translation: str | None = None
    source: str = "none"
    similarity_score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class TMStats:
    """Aggregated statistics from all TM layers."""

    # L1 Cache stats
    l1_size: int
    l1_max_size: int
    l1_hits: int
    l1_misses: int
    l1_evictions: int
    l1_hit_rate: float

    # L2 Persistent stats
    l2_size: int

    # L3 Semantic stats
    l3_size: int
    l3_hits: int

    # Combined stats
    total_lookups: int
    total_hits: int
    overall_hit_rate: float

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)
