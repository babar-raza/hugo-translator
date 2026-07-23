"""Fence-aware line segmentation for scripts/quality repair functions.

HT-QUALITY-GATES-001 Phase 8 (F2): this module is now a thin re-export of
the canonical implementation in src/translation_engine/fence_spans.py, so
write_gate.py's new gates and scripts/quality's repair functions share one
fence-boundary primitive instead of two independently-drifting copies.
Existing imports (``from fence_spans import split_fenced_segments`` etc.)
keep working unchanged.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.translation_engine.fence_spans import (  # noqa: E402,F401
    count_fence_open_reopens,
    fenced_line_mask,
    get_fence_char_spans,
    is_in_fence,
    split_fenced_segments,
    strip_fenced,
)
