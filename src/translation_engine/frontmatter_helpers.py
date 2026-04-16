"""
Shared helpers for nested frontmatter path resolution.

Used by TextUnitExtractor, ASTRenderer, and engine.py to traverse and
mutate nested YAML frontmatter structures via dot-separated key paths
(e.g. ``overview.content``, ``body.block[0].title_left``).
"""

import re
from typing import Any, Dict, List, Tuple

_BRACKET_RE = re.compile(r'^(.+?)\[(\d+)\]$')


def get_all_nested_values(
    data: Dict[str, Any], key_pattern: str
) -> List[Tuple[str, Any]]:
    """
    Resolve a dot-separated key pattern through nested dicts/lists.

    When the path crosses a list, every item is visited and the index is
    recorded in the returned key so the caller can write back later.

    Example::

        key_pattern = "body.block.title_left"
        data = {"body": {"block": [{"title_left": "A"}, {"title_left": "B"}]}}
        returns [("body.block[0].title_left", "A"),
                 ("body.block[1].title_left", "B")]
    """
    parts = key_pattern.split(".")
    results: List[Tuple[str, Any]] = []

    def _traverse(current: Any, remaining: List[str], path: str) -> None:
        if not remaining:
            if current is not None:
                results.append((path, current))
            return
        part = remaining[0]
        rest = remaining[1:]
        if isinstance(current, dict):
            nxt = current.get(part)
            if nxt is not None:
                nxt_path = f"{path}.{part}" if path else part
                _traverse(nxt, rest, nxt_path)
        elif isinstance(current, list):
            for idx, item in enumerate(current):
                indexed = f"{path}[{idx}]"
                if isinstance(item, dict):
                    nxt = item.get(part)
                    if nxt is not None:
                        _traverse(nxt, rest, f"{indexed}.{part}")

    _traverse(data, parts, "")
    return results


def set_nested_value(
    data: Dict[str, Any], indexed_key: str, value: Any
) -> None:
    """
    Write *value* into *data* at the dot/bracket path *indexed_key*.

    Handles paths like ``overview.content`` and
    ``body.block[0].title_left``.

    Raises KeyError/IndexError if an intermediate path segment is missing.
    """
    tokens = indexed_key.split('.')
    current = data
    for token in tokens[:-1]:
        m = _BRACKET_RE.match(token)
        if m:
            current = current[m.group(1)][int(m.group(2))]
        else:
            current = current[token]
    last = tokens[-1]
    m = _BRACKET_RE.match(last)
    if m:
        current[m.group(1)][int(m.group(2))] = value
    else:
        current[last] = value
