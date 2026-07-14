"""Shared frontmatter field extraction for scripts/quality/*.

Replaces first-line-only regex extraction (``re.search(r"^field:\\s*(.+)$", ...,
re.MULTILINE)``) which truncates multi-line YAML scalars (folded ``>-``, literal
``|``, or multi-line quoted strings) to their first physical line — the root
cause of the 2026-07-12 wave-3 description-truncation corruption. Parses via
HugoParser/ruamel instead, so the full scalar value is returned regardless of
how many physical lines it spans.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROJ_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJ_ROOT not in sys.path:
    sys.path.insert(0, _PROJ_ROOT)

from src.translation_engine.parser.hugo_parser import HugoParser  # noqa: E402

_parser = HugoParser()


def get_frontmatter_field(content: str, field: str) -> str | None:
    """Return the full string value of a frontmatter field, or None.

    Correctly handles folded/literal/multi-line scalars since it parses the
    frontmatter YAML rather than regex-matching the first physical line.
    """
    split = _parser._split_frontmatter(content)
    if split is None:
        return None
    data = _parser._parse_yaml_content(split[0])
    if not isinstance(data, dict):
        return None
    value = data.get(field)
    return value if isinstance(value, str) else None
