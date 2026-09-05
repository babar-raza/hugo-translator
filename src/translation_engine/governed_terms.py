"""One source of truth for governed multi-word terminology.

TC-APT-079. The same governed term has to be honoured by four independent
inventories:

  1. a site profile's ``preserve_patterns``            -- masking during translation
  2. ``engine.py``'s ``_FRONTMATTER_TECHNICAL_SIGNAL_RE`` -- frontmatter gate signal
  3. ``config/terminology.yaml``                        -- the terminology validator
  4. ``language_check.py``'s ``TECHNICAL_SIGNAL_RE``     -- write-time verification signal

Governing ONE term took four commits across three iterations because each list
was edited by hand, and every miss produced a distinct live failure -- the last
of them made ``seoTitle`` the single most frequent failure on words-document-net.

Inventories 2 and 4 are near-copies serving the same purpose: strip text that is
governed terminology rather than prose, so it cannot be counted as evidence of
which language a short field is written in. Those two are derived here from
inventory 3, which removes the hand-copying between them.

The scale of the drift when this was written: terminology.yaml carried 15
multi-word governed terms and the two regexes contained exactly one of them, so
``API Reference``, ``REST API``, ``QR Code``, ``Data Matrix`` and the barcode
symbology names were all still being counted as prose.

Inventories 1 and 3 are NOT merged: masking and validation are different jobs,
and a term can legitimately be validated without being masked. A test asserts
they agree on governed terms rather than forcing them into one list.
"""

from __future__ import annotations

import functools
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Behaviour floor. If the config cannot be read, fall back to what the two
# regexes contained by hand, so a missing or malformed file can never silently
# regress below the previously shipped behaviour.
_FALLBACK_TERMS: tuple[str, ...] = ("Document Object Model",)


def _terminology_path() -> Path:
    """Resolve config/terminology.yaml, cwd first then package-relative.

    Mirrors the resolution already used by llm_backend and mt_backend so this
    module behaves the same way under both a repo-root cwd and an installed
    layout.
    """
    candidate = Path("config/terminology.yaml")
    if candidate.exists():
        return candidate
    return Path(__file__).resolve().parent.parent.parent / "config" / "terminology.yaml"


@functools.lru_cache(maxsize=1)
def governed_multiword_terms() -> tuple[str, ...]:
    """Multi-word governed terms, longest first.

    Longest-first matters: ``API Reference Guide`` must claim its span before
    ``API Reference`` can match a prefix of it, exactly like the ordering rule
    the site profiles' preserve_patterns already follow.

    Single-token terms are deliberately excluded. The signal regexes already
    cover that shape generically (all-caps runs, dotted identifiers, CamelCase),
    and pulling in every single-token entry would strip ordinary words such as
    "Java" or "Office" from prose where they are being used as prose.
    """
    try:
        import yaml

        with open(_terminology_path(), encoding="utf-8") as handle:
            config = yaml.safe_load(handle) or {}
        entries = (config.get("global") or {}).get("exact_matches") or []
        terms = {
            str(entry["term"]).strip()
            for entry in entries
            if isinstance(entry, dict) and " " in str(entry.get("term", "")).strip()
        }
        if not terms:
            return _FALLBACK_TERMS
        return tuple(sorted(terms, key=lambda term: (-len(term), term)))
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(
            "governed terminology unavailable (%s); falling back to the built-in list",
            type(exc).__name__,
        )
        return _FALLBACK_TERMS


def governed_signal_alternation() -> str:
    """Regex alternation for the governed terms, ready to embed in a signal regex.

    Returns an empty string when there are no terms, so callers can concatenate
    it unconditionally without producing an empty alternative (``(?:|foo)``),
    which would match at every position.
    """
    terms = governed_multiword_terms()
    if not terms:
        return ""
    return "".join(f"{re.escape(term)}|" for term in terms)
