"""
Generic per-site locale-allowlist enforcement.

A site profile that sets `strict_locale_allowlist: true` gets its
`target_langs` enforced as an exact allowlist everywhere a target locale
can be determined — CLI overrides, the translation engine, and
quality-script directory auto-discovery all reject or filter out any
locale not in `target_langs`. Sites that leave the flag false (the
default) are unaffected — lenient behavior (any format-valid locale may
be requested regardless of `target_langs`) is preserved for them.

This module has no knowledge of any specific site or brand — it operates
purely on whatever profile object it's given (duck-typed: `.target_langs`,
`.default_source_lang`, `.strict_locale_allowlist`). A new site adopts the
same enforcement purely by setting these fields in its own profile YAML —
no code changes anywhere in this module or its callers are required.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any


class LocalePolicyViolation(ValueError):
    """Raised when a locale request violates a site's strict allowlist."""


def _is_strict(site_profile: Any) -> bool:
    return bool(getattr(site_profile, "strict_locale_allowlist", False))


def _allowed_locales(site_profile: Any) -> set[str]:
    return set(site_profile.target_langs) | {site_profile.default_source_lang}


def validate_requested_locales(site_profile: Any, requested: Iterable[str]) -> None:
    """Raise LocalePolicyViolation if any requested locale isn't allowed.

    No-op unless `site_profile.strict_locale_allowlist` is True.
    """
    if not _is_strict(site_profile):
        return
    allowed = _allowed_locales(site_profile)
    disallowed = sorted(set(requested) - allowed)
    if disallowed:
        raise LocalePolicyViolation(
            f"Locale(s) {disallowed} are not in the allowed locale set for "
            f"site '{getattr(site_profile, 'site_id', '?')}'. "
            f"Approved: {sorted(allowed)}."
        )


def filter_to_allowed_locales(site_profile: Any, candidates: Iterable[str]) -> list[str]:
    """Drop any candidate locale not in the site's allowlist.

    No-op (returns candidates unchanged) unless
    `site_profile.strict_locale_allowlist` is True. Intended for
    auto-discovery contexts (directory scans) where an out-of-policy
    locale simply existing isn't an error — unlike
    `validate_requested_locales`.
    """
    candidates = list(candidates)
    if not _is_strict(site_profile):
        return candidates
    allowed = _allowed_locales(site_profile)
    return [lang for lang in candidates if lang in allowed]
