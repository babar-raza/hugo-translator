"""
HT-QUALITY-GATES-001 RC1: regression test for the real glue code that decides
whether `title` is protected from translation on family/platform index pages.

Root cause: `segment_translator.py`'s inline computation read
`getattr(doc, "file_path", None)` -- `HugoDocument` has no `file_path`
attribute (only `source_path`), so this always evaluated to `None`,
`is_family_platform_index(None, ...)` always returned `False`, and title
protection never activated for any file, ever. Confirmed via a real
products.aspose.org retranslation: 92.9% of family/platform titles came back
not matching English, many hallucinated ("Je suis désolé.", "De
plaatshouder.") rather than merely mistranslated.

`tests/unit/translation_engine/extractor/test_index_title_passthrough.py`
already tested `is_family_platform_index()` in isolation and
`TextUnitExtractor(force_protected_fields={"title"})` with the flag
hand-set -- neither exercises this glue, which is exactly why the bug went
uncaught through that suite. This test uses a REAL `HugoDocument` (not a
MagicMock, which would silently return a truthy mock for `doc.file_path`
and never have caught this) to drive the actual production code path,
`compute_force_protected_fields()` (extracted from inline `_translate_body_ast`
logic specifically for this testability).
"""
from pathlib import Path
from types import SimpleNamespace

from src.translation_engine.parser.hugo_parser import HugoDocument
from src.translation_engine.segment_translator import compute_force_protected_fields


def _real_doc(source_path: Path | None) -> HugoDocument:
    return HugoDocument(frontmatter={"title": "Aspose.3D FOSS"}, ast=[], source_path=source_path)


def _site_profile(default_source_lang: str = "en", site_id: str = "products.aspose.org") -> SimpleNamespace:
    return SimpleNamespace(default_source_lang=default_source_lang, site_id=site_id)


class TestComputeForceProtectedFields:
    def test_family_root_index_protects_title_on_products_aspose_org(self):
        """The most important regression case: a family-ROOT page (2-level,
        no platform segment) on products.aspose.org — e.g. psd/_index.md,
        one of the 15 root-only families. This exact page shape carried the
        audit's single most severe finding (title corrupted to the Serbian
        word for "Death"). is_family_platform_index() alone (without
        include_family_root) does NOT match this shape — this test would
        fail if that opt-in wiring regressed."""
        doc = _real_doc(Path("D:/content/products.aspose.org/en/psd/_index.md"))
        assert compute_force_protected_fields(doc, _site_profile()) == {"title"}

    def test_platform_subpage_index_protects_title(self):
        doc = _real_doc(Path("D:/content/products.aspose.org/en/cells/net/_index.md"))
        assert compute_force_protected_fields(doc, _site_profile()) == {"title"}

    def test_leaf_content_page_does_not_protect_title(self):
        """Leaf pages (e.g. tutorials) legitimately translate their title —
        must not be swept into protection by this check."""
        doc = _real_doc(
            Path("D:/content/products.aspose.org/en/cells/net/getting-started/installation.md")
        )
        assert compute_force_protected_fields(doc, _site_profile()) == set()

    def test_nested_index_does_not_protect_title(self):
        doc = _real_doc(
            Path("D:/content/products.aspose.org/en/cells/net/getting-started/_index.md")
        )
        assert compute_force_protected_fields(doc, _site_profile()) == set()

    def test_none_source_path_does_not_protect_title(self):
        """doc.source_path can genuinely be None (e.g. parse_string() without
        a file). Must degrade to "not protected", not raise."""
        doc = _real_doc(None)
        assert compute_force_protected_fields(doc, _site_profile()) == set()

    def test_respects_custom_source_lang(self):
        doc = _real_doc(Path("D:/content/products.aspose.org/de/3d/_index.md"))
        assert compute_force_protected_fields(doc, _site_profile("de")) == {"title"}

    def test_doc_without_source_path_attribute_does_not_crash(self):
        """Defensive: an object with no source_path at all (not a real
        HugoDocument) must degrade gracefully, not raise AttributeError."""
        doc = SimpleNamespace(frontmatter={"title": "x"}, ast=[])
        assert compute_force_protected_fields(doc, _site_profile()) == set()

    def test_family_root_on_unconfirmed_site_is_not_protected(self):
        """include_family_root is deliberately scoped to sites directly
        confirmed to need it (products.aspose.org, kb.aspose.org,
        docs.aspose.org -- Part 22). blog.aspose.org has a structurally
        different layout (per_language_folders: false) never investigated
        for this requirement -- its pre-existing (narrower) behavior must be
        unchanged. A regression here would mean this scoping silently
        widened to a site it was never verified for."""
        doc = _real_doc(Path("D:/content/blog.aspose.org/en/slides/_index.md"))
        assert compute_force_protected_fields(doc, _site_profile(site_id="blog.aspose.org")) == set()

    def test_platform_page_on_unconfirmed_site_still_protected(self):
        """The narrower, pre-existing (platform-only) behavior must still
        work for sites not in the family-root set -- only the family-root
        broadening is scoped."""
        doc = _real_doc(Path("D:/content/blog.aspose.org/en/slides/cpp/_index.md"))
        assert compute_force_protected_fields(doc, _site_profile(site_id="blog.aspose.org")) == {"title"}

    def test_family_root_on_kb_aspose_org_is_protected(self):
        """HT-QUALITY-GATES-001 Part 22: kb.aspose.org confirmed (direct
        sampling of real content) to share the identical defect --
        kb hr/cells/_index.md's title corrupted to "Sljedeći članakFOSS"
        ("Next article" + "FOSS", a leaked UI string), same failure class as
        products.aspose.org's original findings, not a different policy."""
        doc = _real_doc(Path("D:/content/kb.aspose.org/en/cells/_index.md"))
        assert compute_force_protected_fields(doc, _site_profile(site_id="kb.aspose.org")) == {"title"}

    def test_family_root_on_docs_aspose_org_is_protected(self):
        """HT-QUALITY-GATES-001 Part 22: docs.aspose.org confirmed the same
        way (e.g. fr/cells/_index.md's title corrupted to "[Résumé] FOSS",
        a leaked UI string)."""
        doc = _real_doc(Path("D:/content/docs.aspose.org/en/cells/_index.md"))
        assert compute_force_protected_fields(doc, _site_profile(site_id="docs.aspose.org")) == {"title"}
