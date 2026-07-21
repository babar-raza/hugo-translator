"""Regression tests for the Aspose brand-name preserve_pattern gap found
2026-07-19: docs.aspose.org and products.aspose.org had NO brand-protection
pattern at all, and kb.aspose.org/blog.aspose.org's existing patterns didn't
match bare "Aspose" or digit-led product names (Aspose.3D), so the brand
token could get translated, dropped, or corrupted (e.g. "Aspose.3D FOSS" ->
"3D FOSS -tuotanto", "Aspose FOSS Knowledge Base" left fully unprotected).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parent.parent.parent.parent
SITE_PROFILES_DIR = ROOT / "config" / "site_profiles"

SITES_REQUIRING_BRAND_PROTECTION = [
    "docs.aspose.org",
    "products.aspose.org",
    "kb.aspose.org",
    "reference.aspose.org",
    "blog.aspose.org",
]

BRAND_TEST_CASES = [
    ("Aspose.Note FOSS for Python", "Aspose.Note"),
    ("Aspose FOSS Knowledge Base", "Aspose"),
    ("Aspose.ZIP FOSS", "Aspose.ZIP"),
    ("Aspose.3D FOSS", "Aspose.3D"),
    ("Aspose.PDF FOSS", "Aspose.PDF"),
    ("Aspose.Cells FOSS for .NET", "Aspose.Cells"),
]


def _load_preserve_patterns(site_id: str) -> list[str]:
    path = SITE_PROFILES_DIR / f"{site_id}.yaml"
    with open(path, encoding="utf-8") as fh:
        profile = yaml.safe_load(fh)
    return profile.get("body", {}).get("preserve_patterns", [])


@pytest.mark.parametrize("site_id", SITES_REQUIRING_BRAND_PROTECTION)
def test_site_profile_has_brand_preserve_pattern(site_id: str) -> None:
    patterns = _load_preserve_patterns(site_id)
    assert any("Aspose" in p for p in patterns), (
        f"{site_id}.yaml has no Aspose brand-name preserve_pattern"
    )


@pytest.mark.parametrize("site_id", SITES_REQUIRING_BRAND_PROTECTION)
@pytest.mark.parametrize("text,expected_match", BRAND_TEST_CASES)
def test_brand_pattern_protects_full_token(
    site_id: str, text: str, expected_match: str
) -> None:
    patterns = [p for p in _load_preserve_patterns(site_id) if "Aspose" in p]
    assert patterns, f"{site_id}.yaml has no Aspose pattern to test"

    matched_spans = []
    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            matched_spans.append(m.group(0))

    assert matched_spans, f"{site_id}: no Aspose pattern matched {text!r}"
    # The longest match across all Aspose-related patterns should cover the
    # full expected brand token (not just bare "Aspose" when a dotted
    # product name like "Aspose.3D" is present).
    longest = max(matched_spans, key=len)
    assert longest == expected_match, (
        f"{site_id}: expected full token {expected_match!r}, "
        f"only matched {longest!r} in {text!r}"
    )
