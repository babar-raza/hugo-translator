"""
Generic, site-agnostic proof of the strict_locale_allowlist mechanism.

src/utils/locale_policy.py has zero knowledge of any specific site or
brand — it operates purely on whatever profile object it's given
(duck-typed: .target_langs, .default_source_lang, .strict_locale_allowlist).
These tests use entirely synthetic, non-Aspose site profiles to prove the
mechanism itself is generic: any site can adopt the same enforcement by
setting these two fields in its own profile YAML, with zero code changes.

`bg` is used as an example rejected locale throughout, consistent with the
negative-control locale used across the rest of the locale-policy suite.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.utils.locale_policy import (
    LocalePolicyViolation,
    filter_to_allowed_locales,
    validate_requested_locales,
)


def _profile(*, strict: bool, target_langs=("de", "fr", "ja"), source="en", site_id="newsite.example.org"):
    return SimpleNamespace(
        site_id=site_id,
        target_langs=list(target_langs),
        default_source_lang=source,
        strict_locale_allowlist=strict,
    )


# ---------------------------------------------------------------------------
# locale_policy.py has zero site-specific knowledge
# ---------------------------------------------------------------------------


def test_locale_policy_module_has_no_aspose_references():
    import inspect

    import src.utils.locale_policy as mod

    source = inspect.getsource(mod)
    assert "aspose" not in source.lower()


# ---------------------------------------------------------------------------
# Strict site: exact allowlist enforced
# ---------------------------------------------------------------------------


def test_strict_site_accepts_locales_in_target_langs():
    profile = _profile(strict=True)
    validate_requested_locales(profile, ["de", "fr"])  # must not raise


def test_strict_site_accepts_source_lang():
    profile = _profile(strict=True)
    validate_requested_locales(profile, ["en"])  # must not raise


def test_strict_site_rejects_locale_outside_target_langs():
    profile = _profile(strict=True)
    with pytest.raises(LocalePolicyViolation) as exc_info:
        validate_requested_locales(profile, ["bg"])
    assert "bg" in str(exc_info.value)
    assert profile.site_id in str(exc_info.value)


def test_strict_site_reports_every_disallowed_locale():
    profile = _profile(strict=True)
    with pytest.raises(LocalePolicyViolation) as exc_info:
        validate_requested_locales(profile, ["de", "bg", "zz"])
    msg = str(exc_info.value)
    assert "bg" in msg
    assert "zz" in msg


def test_strict_site_filter_drops_locales_outside_target_langs():
    profile = _profile(strict=True)
    result = filter_to_allowed_locales(profile, ["de", "bg", "fr", "zz"])
    assert result == ["de", "fr"]


# ---------------------------------------------------------------------------
# Non-strict (lenient, default) site: unaffected
# ---------------------------------------------------------------------------


def test_lenient_site_accepts_any_format_valid_locale():
    profile = _profile(strict=False)
    validate_requested_locales(profile, ["bg", "zz", "anything"])  # must not raise


def test_lenient_site_filter_is_a_noop():
    profile = _profile(strict=False)
    candidates = ["de", "bg", "fr", "zz"]
    assert filter_to_allowed_locales(profile, candidates) == candidates


def test_default_flag_value_is_lenient():
    # strict_locale_allowlist omitted entirely -- duck-typed default is False.
    profile = SimpleNamespace(
        site_id="no-flag.example.org",
        target_langs=["de"],
        default_source_lang="en",
    )
    validate_requested_locales(profile, ["bg"])  # must not raise: no-op


# ---------------------------------------------------------------------------
# A second, independent strict site does not interfere with the first --
# proves there is no shared/global state, only per-profile data.
# ---------------------------------------------------------------------------


def test_two_independent_strict_sites_do_not_interfere():
    site_a = _profile(strict=True, target_langs=["de"], site_id="site-a.example.org")
    site_b = _profile(strict=True, target_langs=["ja"], site_id="site-b.example.org")

    validate_requested_locales(site_a, ["de"])
    validate_requested_locales(site_b, ["ja"])

    with pytest.raises(LocalePolicyViolation):
        validate_requested_locales(site_a, ["ja"])  # not in site_a's own set
    with pytest.raises(LocalePolicyViolation):
        validate_requested_locales(site_b, ["de"])  # not in site_b's own set
