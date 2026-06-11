"""Unit tests for src.observability.family_extraction.

Covers:
- extract_family_from_path for both aspose.org (en/{family}/...) and aspose.net ({family}/{lang}/...)
- discover_family_subdirs for both conventions
- is_multi_family
- fail-closed: unknown paths must NOT return "total"
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.observability.family_extraction import (
    KNOWN_LANG_CODES,
    discover_family_subdirs,
    extract_family_from_path,
    is_multi_family,
)

KNOWN_FAMILIES = [
    "words",
    "cells",
    "pdf",
    "slides",
    "email",
    "imaging",
    "3d",
    "barcode",
    "cad",
    "diagram",
    "html",
    "ocr",
    "psd",
    "zip",
    "tasks",
    "note",
    "font",
    "tex",
    "page",
    "svg",
    "gis",
    "total",
]


class TestExtractFamilyFromPath:
    """extract_family_from_path: various path conventions."""

    # ── aspose.org convention: en/{family}/... ──────────────────────────────

    def test_org_products_font_python(self):
        assert extract_family_from_path("en/font/python/_index.md", KNOWN_FAMILIES) == "font"

    def test_org_products_cells_net(self):
        assert extract_family_from_path("en/cells/net/_index.md", KNOWN_FAMILIES) == "cells"

    def test_org_products_words(self):
        assert (
            extract_family_from_path("en/words/getting-started/intro.md", KNOWN_FAMILIES) == "words"
        )

    def test_org_docs_pdf(self):
        assert extract_family_from_path("en/pdf/api-reference.md", KNOWN_FAMILIES) == "pdf"

    def test_org_kb_slides(self):
        assert extract_family_from_path("en/slides/faq/_index.md", KNOWN_FAMILIES) == "slides"

    # ── aspose.net convention: {family}/{lang}/... ──────────────────────────

    def test_net_products_words_en(self):
        assert extract_family_from_path("words/en/_index.md", KNOWN_FAMILIES) == "words"

    def test_net_kb_barcode_de(self):
        assert (
            extract_family_from_path("barcode/de/1d-reader/_index.md", KNOWN_FAMILIES) == "barcode"
        )

    def test_net_reference_cells_fr(self):
        assert extract_family_from_path("cells/fr/namespace/_index.md", KNOWN_FAMILIES) == "cells"

    def test_net_products_pdf_ar(self):
        assert extract_family_from_path("pdf/ar/_index.md", KNOWN_FAMILIES) == "pdf"

    # ── backslash normalisation ──────────────────────────────────────────────

    def test_backslash_path(self):
        assert extract_family_from_path(r"en\words\intro.md", KNOWN_FAMILIES) == "words"

    # ── root-level _index.md (no family) ────────────────────────────────────

    def test_root_index_no_family(self):
        """Top-level _index.md has no family segment."""
        result = extract_family_from_path("en/_index.md", KNOWN_FAMILIES)
        assert result is None, "Root _index.md must not resolve to a family"

    def test_root_index_net_style_no_family(self):
        result = extract_family_from_path("_index.md", KNOWN_FAMILIES)
        assert result is None

    # ── unknown path must NOT return "total" ──────────────────────────────

    def test_unknown_path_not_total(self):
        result = extract_family_from_path("en/some-unknown-section/page.md", KNOWN_FAMILIES)
        assert result != "total", "Unknown family path must never resolve to 'total'"
        assert result is None

    def test_totally_unknown_path(self):
        result = extract_family_from_path("completely/unknown/path.md", KNOWN_FAMILIES)
        assert result is None

    # ── explicit total path ──────────────────────────────────────────────────

    def test_explicit_total_segment(self):
        """If there's a 'total' segment in the path and 'total' is in known_families."""
        result = extract_family_from_path("en/total/_index.md", KNOWN_FAMILIES)
        assert result == "total"

    # ── empty / edge cases ──────────────────────────────────────────────────

    def test_empty_path(self):
        assert extract_family_from_path("", KNOWN_FAMILIES) is None

    def test_only_lang_segments(self):
        assert extract_family_from_path("en/de/fr", KNOWN_FAMILIES) is None

    def test_filename_only(self):
        assert extract_family_from_path("_index.md", KNOWN_FAMILIES) is None


class TestDiscoveryFamilySubdirs:
    """discover_family_subdirs: org-style (en/{family}) and net-style ({family}) conventions."""

    def test_org_style_products(self, tmp_path):
        """aspose.org: content under en/{family}/"""
        en_dir = tmp_path / "en"
        en_dir.mkdir()
        (en_dir / "words").mkdir()
        (en_dir / "cells").mkdir()
        (en_dir / "font").mkdir()
        (en_dir / "_index.md").touch()  # file, not a dir — must be ignored

        result = discover_family_subdirs(tmp_path, KNOWN_FAMILIES)
        tokens = [t for t, _ in result]
        assert sorted(tokens) == ["cells", "font", "words"]

    def test_net_style_kb(self, tmp_path):
        """aspose.net: family at root level (no en/ dir)"""
        (tmp_path / "barcode").mkdir()
        (tmp_path / "cells").mkdir()
        (tmp_path / "words").mkdir()
        (tmp_path / "ar").mkdir()  # lang dir — must NOT be detected as family
        (tmp_path / "de").mkdir()  # lang dir — must NOT be detected as family
        (tmp_path / "home").mkdir()  # unknown dir — must NOT be detected as family

        result = discover_family_subdirs(tmp_path, KNOWN_FAMILIES)
        tokens = [t for t, _ in result]
        assert sorted(tokens) == ["barcode", "cells", "words"]
        assert "ar" not in tokens
        assert "de" not in tokens
        assert "home" not in tokens

    def test_org_style_preferred_over_net_when_en_exists(self, tmp_path):
        """If en/ dir exists with family children, use org-style."""
        en_dir = tmp_path / "en"
        en_dir.mkdir()
        (en_dir / "pdf").mkdir()
        # Also add top-level 'slides' dir — should NOT be returned if en/ has families
        (tmp_path / "slides").mkdir()

        result = discover_family_subdirs(tmp_path, KNOWN_FAMILIES)
        tokens = [t for t, _ in result]
        assert tokens == ["pdf"]
        assert "slides" not in tokens

    def test_empty_dir(self, tmp_path):
        result = discover_family_subdirs(tmp_path, KNOWN_FAMILIES)
        assert result == []

    def test_nonexistent_dir(self, tmp_path):
        result = discover_family_subdirs(tmp_path / "does_not_exist", KNOWN_FAMILIES)
        assert result == []

    def test_single_family_dir(self, tmp_path):
        """Single family — not multi-family."""
        (tmp_path / "words").mkdir()
        result = discover_family_subdirs(tmp_path, KNOWN_FAMILIES)
        assert result == [("words", tmp_path / "words")]

    def test_paths_are_absolute(self, tmp_path):
        en_dir = tmp_path / "en"
        en_dir.mkdir()
        (en_dir / "cells").mkdir()
        result = discover_family_subdirs(tmp_path, KNOWN_FAMILIES)
        assert len(result) == 1
        token, path = result[0]
        assert token == "cells"
        assert path.is_absolute()

    def test_no_total_returned_for_unknown_dirs(self, tmp_path):
        """Directories that are NOT in known_families must not be returned."""
        (tmp_path / "unknown-product").mkdir()
        (tmp_path / "marketing").mkdir()
        result = discover_family_subdirs(tmp_path, KNOWN_FAMILIES)
        assert result == []


class TestIsMultiFamily:
    """is_multi_family: returns True iff multiple family subdirs are found."""

    def test_multi_family(self, tmp_path):
        en_dir = tmp_path / "en"
        en_dir.mkdir()
        (en_dir / "words").mkdir()
        (en_dir / "cells").mkdir()
        assert is_multi_family(tmp_path, KNOWN_FAMILIES) is True

    def test_single_family(self, tmp_path):
        (tmp_path / "words").mkdir()
        assert is_multi_family(tmp_path, KNOWN_FAMILIES) is False

    def test_no_families(self, tmp_path):
        assert is_multi_family(tmp_path, KNOWN_FAMILIES) is False

    def test_nonexistent_dir(self, tmp_path):
        assert is_multi_family(tmp_path / "nope", KNOWN_FAMILIES) is False


class TestKnownLangCodes:
    """Ensure KNOWN_LANG_CODES covers all content-path language codes."""

    def test_english_in_known_langs(self):
        assert "en" in KNOWN_LANG_CODES

    def test_arabic_in_known_langs(self):
        assert "ar" in KNOWN_LANG_CODES

    def test_family_tokens_not_in_lang_codes(self):
        for family in ["words", "cells", "pdf", "font", "3d"]:
            assert family not in KNOWN_LANG_CODES, (
                f"Family token '{family}' should not be in KNOWN_LANG_CODES"
            )
