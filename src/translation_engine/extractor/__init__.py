"""
Segment extraction module.
"""
from .segment_extractor import (
    Segment,
    SegmentContext,
    SegmentContextType,
    SegmentExtractor,
)
from .placeholder_manager import PlaceholderManager

__all__ = [
    "Segment",
    "SegmentContext",
    "SegmentContextType",
    "SegmentExtractor",
    "PlaceholderManager",
]
