"""
Regression tests for two preserve_pattern gaps closed in
HT-QUALITY-GATES-001 Part 22 (plan 5.3, incremental scope):

1. Hyphenated/slashed format & standard codes (UPC-E, EAN-13, PDF/A,
   ISO-8859-1) embedded in prose were unprotected on every site --
   confirmed real corruption: "UPC-E" became "U PC-E" mid-sentence.
2. kb.aspose.org, blog.aspose.org, and reference.aspose.org had NO
   markdown-link preserve_pattern at all (docs/products already did),
   leaving relative/enterprise links exposed in the legacy (non-AST)
   reconstruction fallback path.

Both patterns had to be inserted EARLY in each site's preserve_patterns
list (ahead of brand-name/identifier patterns) to avoid a specific nesting
hazard: if a later-running pattern partially matches content INSIDE an
already-protected span (e.g. "Aspose" inside a URL, or a class name inside
link text) before the wrapping pattern claims it, PlaceholderManager.protect()
produces a placeholder nested inside another placeholder's stored value --
which restore()'s single sequential replace pass cannot unwind correctly
(this is the same failure shape root-caused for the brace-leak bug in
Part 1.1). These tests exercise the REAL round trip through
PlaceholderManager using the actual site-profile patterns, not just regex
matching, specifically to catch that class of bug.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.translation_engine.extractor.placeholder_manager import PlaceholderManager

ROOT = Path(__file__).parent.parent.parent.parent
SITE_PROFILES_DIR = ROOT / "config" / "site_profiles"

ALL_SITES = [
    "docs.aspose.org",
    "kb.aspose.org",
    "products.aspose.org",
    "reference.aspose.org",
    "blog.aspose.org",
]

# Sites that previously had NO markdown-link preserve_pattern at all.
SITES_NEEDING_LINK_PATTERN = ["kb.aspose.org", "reference.aspose.org", "blog.aspose.org"]

ACRONYM_TEST_CASES = [
    ("The scanner supports UPC-E and EAN-13 barcodes.", "UPC-E"),
    ("Export as PDF/A for long-term archival.", "PDF/A"),
    ("Encode using UTF-8 or ISO-8859-1.", "UTF-8"),
    ("Encryption uses AES-256 by default.", "AES-256"),
]

# Plain English emphasis / bare acronyms that must NOT be swallowed by the
# new acronym pattern (false-positive guard).
ACRONYM_NEGATIVE_CASES = [
    "DO NOT use this method directly.",
    "The API is stable.",
    "Requires an HTTP connection.",
]


def _load_preserve_patterns(site_id: str) -> list[str]:
    path = SITE_PROFILES_DIR / f"{site_id}.yaml"
    with open(path, encoding="utf-8") as fh:
        profile = yaml.safe_load(fh)
    return profile.get("body", {}).get("preserve_patterns", [])


class TestAcronymPreservePattern:
    @pytest.mark.parametrize("site_id", ALL_SITES)
    def test_site_has_acronym_pattern(self, site_id: str) -> None:
        patterns = _load_preserve_patterns(site_id)
        assert any(r"[-/][A-Z0-9]" in p for p in patterns), (
            f"{site_id}.yaml has no hyphenated/slashed acronym preserve_pattern"
        )

    @pytest.mark.parametrize("site_id", ALL_SITES)
    @pytest.mark.parametrize("text,expected_token", ACRONYM_TEST_CASES)
    def test_acronym_survives_protect_restore_round_trip(
        self, site_id: str, text: str, expected_token: str
    ) -> None:
        patterns = _load_preserve_patterns(site_id)
        pm = PlaceholderManager()
        protected, placeholder_map = pm.protect(text, patterns)

        assert expected_token not in protected, (
            f"{site_id}: {expected_token!r} was not protected out of the "
            f"model-input text: {protected!r}"
        )
        assert expected_token in placeholder_map.values(), (
            f"{site_id}: {expected_token!r} not found in any placeholder value"
        )

        # Round trip: even if the model garbles the surrounding prose,
        # restore() must put the exact original token back.
        restored = pm.restore(protected, placeholder_map)
        assert expected_token in restored

    @pytest.mark.parametrize("site_id", ALL_SITES)
    @pytest.mark.parametrize("text", ACRONYM_NEGATIVE_CASES)
    def test_plain_emphasis_words_not_swallowed(self, site_id: str, text: str) -> None:
        """False-positive guard: stylistic ALL-CAPS emphasis and bare
        acronyms without a hyphen/slash suffix must remain translatable
        prose, not get incorrectly locked as a placeholder."""
        patterns = _load_preserve_patterns(site_id)
        pm = PlaceholderManager()
        protected, placeholder_map = pm.protect(text, patterns)

        acronym_protected = [
            v for v in placeholder_map.values()
            if v in ("DO", "NOT", "API", "HTTP")
        ]
        assert not acronym_protected, (
            f"{site_id}: plain word(s) {acronym_protected} incorrectly "
            f"protected by the new acronym pattern in {text!r}"
        )


class TestMarkdownLinkPreservePattern:
    @pytest.mark.parametrize("site_id", SITES_NEEDING_LINK_PATTERN)
    def test_site_has_link_pattern(self, site_id: str) -> None:
        patterns = _load_preserve_patterns(site_id)
        assert any(r"\]\(" in p for p in patterns), (
            f"{site_id}.yaml has no markdown-link preserve_pattern"
        )

    @pytest.mark.parametrize("site_id", SITES_NEEDING_LINK_PATTERN)
    def test_link_pattern_is_ordered_before_brand_pattern(self, site_id: str) -> None:
        """The specific nesting hazard this whole test file exists to guard
        against: the link pattern must run BEFORE the Aspose brand pattern,
        or a URL containing "Aspose" in its path risks a nested placeholder
        that restore() cannot unwind."""
        patterns = _load_preserve_patterns(site_id)
        link_idx = next(i for i, p in enumerate(patterns) if r"\]\(" in p)
        brand_idx = next(
            (i for i, p in enumerate(patterns) if "Aspose" in p), None
        )
        if brand_idx is not None:
            assert link_idx < brand_idx, (
                f"{site_id}: link pattern (index {link_idx}) must be ordered "
                f"before the brand pattern (index {brand_idx}) to avoid "
                f"nested-placeholder corruption"
            )

    @pytest.mark.parametrize("site_id", SITES_NEEDING_LINK_PATTERN)
    def test_link_with_brand_name_in_url_does_not_nest(self, site_id: str) -> None:
        """Direct reproduction of the nesting hazard: a real Enterprise
        link whose URL path could plausibly overlap with the brand pattern.
        Confirms protect()+restore() round-trips cleanly with no leaked
        placeholder token and no residual literal brace artifacts."""
        text = (
            "See Also: [Aspose.Cells — Enterprise Knowledge Base]"
            "(https://kb.aspose.com/cells/)"
        )
        patterns = _load_preserve_patterns(site_id)
        pm = PlaceholderManager()
        protected, placeholder_map = pm.protect(text, patterns)
        restored = pm.restore(protected, placeholder_map)

        assert restored == text, (
            f"{site_id}: round trip did not reproduce the original text.\n"
            f"  original: {text!r}\n"
            f"  restored: {restored!r}"
        )
        assert "PLACEHOLDER" not in restored

    @pytest.mark.parametrize("site_id", SITES_NEEDING_LINK_PATTERN)
    def test_link_text_containing_backtick_identifier_does_not_nest(
        self, site_id: str
    ) -> None:
        """A second nesting hazard: link text containing a backtick-wrapped
        identifier. If the backtick pattern ran before the link pattern,
        the identifier would be protected first, and the link pattern would
        then wrap an already-substituted placeholder token -- still must
        round-trip cleanly regardless of which pattern claims it first,
        since PlaceholderManager's restore() only guarantees correctness
        when the OUTER span is claimed first (see the module docstring)."""
        text = "See the [`ColumnInfo`](https://reference.aspose.com/pdf/net/ColumnInfo/) class."
        patterns = _load_preserve_patterns(site_id)
        pm = PlaceholderManager()
        protected, placeholder_map = pm.protect(text, patterns)
        restored = pm.restore(protected, placeholder_map)

        assert restored == text, (
            f"{site_id}: round trip did not reproduce the original text.\n"
            f"  original: {text!r}\n"
            f"  restored: {restored!r}"
        )
        assert "PLACEHOLDER" not in restored
