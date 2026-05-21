"""Family token extraction from file/directory paths.

Supports both aspose.org (en/{family}/...) and aspose.net ({family}/{lang}/...)
content path conventions.

Invariant:
    Unknown family returns None — never falls back to "total".
    Callers must handle None explicitly as multi-family or unknown scope.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# ISO 639-1 + common extended codes used in content paths.
# When scanning a path for a family token, these segments are skipped.
KNOWN_LANG_CODES: frozenset[str] = frozenset({
    "en", "ar", "bg", "ca", "cs", "da", "de", "el", "es", "fa", "fi",
    "fr", "he", "hi", "hr", "hu", "id", "it", "ja", "ko", "lt", "lv",
    "ms", "nl", "no", "pl", "pt", "ro", "ru", "sk", "sr", "sv", "th",
    "tr", "uk", "vi", "zh",
})


def extract_family_from_path(rel_path: str, known_families: list[str]) -> str | None:
    """Extract product family token from a file path relative to a content root.

    Handles both path conventions:

    - aspose.org style: ``en/{family}/...``
      Example: ``en/words/getting-started/intro.md`` → ``"words"``

    - aspose.net style: ``{family}/{lang}/...``
      Example: ``words/en/getting-started/intro.md`` → ``"words"``

    Algorithm:
        1. Split path into segments.
        2. Skip segments that are known language codes.
        3. Skip segments that look like filenames (contain a dot).
        4. Return the first remaining segment that is in *known_families*.
        5. Return ``None`` if no family is found — callers must not substitute "total".

    Args:
        rel_path: Path relative to the content root.  May use ``/`` or ``\\``.
        known_families: Ordered list of known family tokens (lowercase, e.g. ``["words", "cells"]``).

    Returns:
        Lowercase family token, or ``None``.
    """
    if not rel_path:
        return None

    known_set = {f.lower() for f in known_families}
    # Normalize separators and split
    parts = Path(rel_path.replace("\\", "/")).parts

    for part in parts:
        p = part.lower()
        # Skip language codes
        if p in KNOWN_LANG_CODES:
            continue
        # Skip filename-like segments (contain a non-leading dot)
        if "." in part and not part.startswith("."):
            continue
        # Return first family match
        if p in known_set:
            return p

    return None


def discover_family_subdirs(
    content_root_dir: Path,
    known_families: list[str],
) -> list[tuple[str, Path]]:
    """Discover product-family-scoped subdirectories within a multi-family content root.

    Two path conventions are probed in order:

    1. **aspose.org style** — ``{content_root}/en/{family}/``
       If ``{content_root}/en/`` exists and contains known-family subdirs,
       return those dirs (the actual file roots for English source content).

    2. **aspose.net style** — ``{content_root}/{family}/``
       If root-level dirs are known families, return them directly.

    Args:
        content_root_dir: Absolute path to the content root directory.
        known_families: List of known family tokens.

    Returns:
        Sorted list of ``(family_token, subdir_path)`` tuples.
        Returns ``[]`` if the directory does not exist or no family dirs are found.
    """
    if not content_root_dir.is_dir():
        logger.debug("discover_family_subdirs: %s does not exist", content_root_dir)
        return []

    known_set = {f.lower() for f in known_families}
    results: list[tuple[str, Path]] = []

    # Strategy 1: aspose.org convention — {content_root}/en/{family}/
    en_dir = content_root_dir / "en"
    if en_dir.is_dir():
        for child in sorted(en_dir.iterdir()):
            if child.is_dir() and child.name.lower() in known_set:
                results.append((child.name.lower(), child))
        if results:
            logger.debug(
                "discover_family_subdirs: org-style found %d families under %s/en/",
                len(results), content_root_dir.name,
            )
            return results

    # Strategy 2: aspose.net convention — {content_root}/{family}/
    for child in sorted(content_root_dir.iterdir()):
        if child.is_dir() and child.name.lower() in known_set:
            results.append((child.name.lower(), child))

    if results:
        logger.debug(
            "discover_family_subdirs: net-style found %d families under %s/",
            len(results), content_root_dir.name,
        )

    return results


def is_multi_family(content_root_dir: Path, known_families: list[str]) -> bool:
    """Return ``True`` if *content_root_dir* contains multiple product families.

    A content root is multi-family when ``discover_family_subdirs`` returns more
    than one entry.  This is used by the worker to decide whether to partition
    translation work by family.
    """
    return len(discover_family_subdirs(content_root_dir, known_families)) > 1
