"""
Aspose.org's locale-contract data — a thin business-requirement snapshot.

This is pure data assertion against the real profile YAMLs, not a test of
the enforcement mechanism itself (see test_strict_locale_allowlist_policy.py
for that — the mechanism is generic and has no knowledge of Aspose.org).
This file exists only to catch accidental drift in Aspose.org's *own*
locale-set decision: the 7 profiles below are expected to declare exactly
this 25-target-locale set with strict enforcement turned on.

`bg` is the explicit negative control: a real, previously-active
Aspose.org locale, now retired.
"""
from __future__ import annotations

import pytest

from src.utils.config_loader import ConfigService

ASPOSE_ORG_SITE_IDS = [
    "docs.aspose.org",
    "kb.aspose.org",
    "products.aspose.org",
    "reference.aspose.org",
    "blog.aspose.org",
    "websites.aspose.org",
    "www.aspose.org",
]

EXPECTED_TARGET_LANGS = {
    "ar", "cs", "de", "el", "es", "fa", "fr", "he", "hi", "hu",
    "id", "it", "ja", "ko", "nl", "pl", "pt", "ro", "ru", "sv",
    "th", "tr", "uk", "vi", "zh",
}

NEGATIVE_CONTROL_LOCALE = "bg"


@pytest.fixture
def config_service() -> ConfigService:
    return ConfigService("config")


@pytest.mark.parametrize("site_id", ASPOSE_ORG_SITE_IDS)
def test_profile_declares_exact_25_target_langs(config_service, site_id):
    profile = config_service.get_site_profile(site_id)
    assert set(profile.target_langs) == EXPECTED_TARGET_LANGS, (
        f"{site_id}: target_langs drifted from the expected 25-code set"
    )
    assert NEGATIVE_CONTROL_LOCALE not in profile.target_langs


@pytest.mark.parametrize("site_id", ASPOSE_ORG_SITE_IDS)
def test_profile_has_strict_enforcement_enabled(config_service, site_id):
    profile = config_service.get_site_profile(site_id)
    assert profile.strict_locale_allowlist is True, (
        f"{site_id}: strict_locale_allowlist must be true for this contract to be enforced"
    )


@pytest.mark.parametrize("site_id", ASPOSE_ORG_SITE_IDS)
def test_profile_resolves_to_exactly_26_locales(config_service, site_id):
    profile = config_service.get_site_profile(site_id)
    resolved = {profile.default_source_lang, *profile.target_langs}
    assert len(resolved) == 26
