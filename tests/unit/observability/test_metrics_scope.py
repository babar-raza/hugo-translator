"""Tests for ScopeResolver, content_root_id derivation, and ID generation."""
import uuid

import pytest

from src.observability.metrics_scope import (
    ScopeInput,
    ScopeResolver,
    derive_content_root_id,
    generate_execution_attempt_id,
    generate_segment_run_id,
    generate_stable_work_slice_id,
)
from src.observability.gitlab_context import GitLabContext


class TestContentRootIdDerivation:
    def test_strips_env_var_prefix(self):
        assert derive_content_root_id("${ASPOSE_NET_CONTENT}/docs.aspose.net/words") == "docs.aspose.net/words"

    def test_strips_different_env_var(self):
        assert derive_content_root_id("${ASPOSE_ORG_CONTENT}/products.aspose.org") == "products.aspose.org"

    def test_normalizes_backslashes(self):
        assert derive_content_root_id("${VAR}\\docs.aspose.net\\words") == "docs.aspose.net/words"

    def test_strips_trailing_slash(self):
        assert derive_content_root_id("${VAR}/docs.aspose.net/words/") == "docs.aspose.net/words"

    def test_no_env_var_prefix(self):
        assert derive_content_root_id("docs.aspose.net/words") == "docs.aspose.net/words"

    def test_absolute_windows_path_extracts_suffix(self):
        result = derive_content_root_id("C:\\Users\\prora\\content\\docs.aspose.net\\words")
        assert ":" not in result
        assert "\\" not in result

    def test_absolute_unix_path_extracts_suffix(self):
        result = derive_content_root_id("/builds/runner/content/docs.aspose.net/words")
        assert not result.startswith("/")


class TestScopeResolverLevel3:
    """Level 3 — Profile Field Derivation."""

    def setup_method(self):
        self.resolver = ScopeResolver()

    def test_docs_aspose_net_words(self):
        inp = ScopeInput(
            site_id="docs.aspose.net",
            content_root_raw="${ASPOSE_NET_CONTENT}/docs.aspose.net/words",
            profile_filename="docs.aspose.net.words.yaml",
            display_name="Documentation",
        )
        scope = self.resolver.resolve(inp)
        assert scope.website == "aspose.net"
        assert scope.website_section == "Docs"
        assert scope.product == "Aspose.Words"
        assert scope.platform == ".NET"
        assert scope.content_root_id == "docs.aspose.net/words"
        assert scope.source_site_domain == "aspose.net"
        assert scope.product_family_token == "words"
        assert scope.reporting_confidence == "high"
        assert scope.item_name == ""  # item_name is built in integration layer

    def test_products_aspose_net_words(self):
        inp = ScopeInput(
            site_id="products.aspose.net",
            content_root_raw="${ASPOSE_NET_CONTENT}/products.aspose.net/words",
            profile_filename="products.aspose.net.words.yaml",
            display_name="Landing Pages",
        )
        scope = self.resolver.resolve(inp)
        assert scope.website_section == "Product Pages"
        assert scope.product == "Aspose.Words"

    def test_kb_aspose_net(self):
        """Multi-family content root (no family in path) must resolve to 'unknown', not 'total'."""
        inp = ScopeInput(
            site_id="kb.aspose.net",
            content_root_raw="${ASPOSE_NET_CONTENT}/kb.aspose.net",
            profile_filename="kb.aspose.net.yaml",
            display_name="knowledge base articles",
        )
        scope = self.resolver.resolve(inp)
        assert scope.website_section == "KB"
        # family must be "unknown" (multi-family root) — never "total"
        assert scope.product_family_token == "unknown", (
            "Multi-family content root must not resolve to 'total'. "
            "Use family-aware partitioning instead."
        )
        assert scope.product == "Aspose.Mixed"
        # low confidence because family could not be resolved
        assert scope.reporting_confidence == "low"
        assert scope.fallback_used is True

    def test_blog_aspose_org(self):
        inp = ScopeInput(
            site_id="blog.aspose.org",
            content_root_raw="${ASPOSE_ORG_CONTENT}/blog.aspose.org",
            profile_filename="blog.aspose.org.yaml",
            display_name="blog posts",
        )
        scope = self.resolver.resolve(inp)
        assert scope.website == "aspose.org"
        assert scope.website_section == "Blog"

    def test_source_site_domain_preserved(self):
        inp = ScopeInput(
            site_id="docs.aspose.net",
            content_root_raw="${VAR}/docs.aspose.net/words",
            profile_filename="docs.aspose.net.words.yaml",
        )
        scope = self.resolver.resolve(inp)
        assert scope.source_site_domain == "aspose.net"
        assert scope.website == "aspose.net"
        assert scope.site_id == "docs.aspose.net"


class TestScopeResolverLevel1:
    """Level 1 — CLI Overrides."""

    def test_cli_overrides_all_fields(self):
        resolver = ScopeResolver()
        inp = ScopeInput(
            site_id="docs.aspose.net",
            content_root_raw="${VAR}/docs.aspose.net/words",
            profile_filename="docs.aspose.net.words.yaml",
            cli_overrides={
                "website": "custom.com",
                "website_section": "Custom",
                "product_family": "cells",
                "platform": "java",
            },
        )
        scope = resolver.resolve(inp)
        assert scope.website == "custom.com"
        assert scope.website_section == "Custom"
        assert scope.product_family_token == "cells"
        assert scope.platform == "Java"


class TestScopeResolverLevel2:
    """Level 2 — metrics_hints."""

    def test_hints_override_derivation(self):
        resolver = ScopeResolver()
        inp = ScopeInput(
            site_id="docs.aspose.net",
            content_root_raw="${VAR}/docs.aspose.net/words",
            profile_filename="docs.aspose.net.words.yaml",
            metrics_hints={
                "website": "special.com",
                "website_section": "Special Docs",
            },
        )
        scope = resolver.resolve(inp)
        assert scope.website == "special.com"
        assert scope.website_section == "Special Docs"


class TestScopeResolverFallback:
    """Level 4 — Controlled Fallback."""

    def test_unknown_domain_passes_through(self):
        resolver = ScopeResolver()
        inp = ScopeInput(
            site_id="docs.unknowndomain.xyz",
            content_root_raw="${VAR}/docs.unknowndomain.xyz",
            profile_filename="docs.unknowndomain.xyz.yaml",
            display_name="Some Docs",
        )
        scope = resolver.resolve(inp)
        assert scope.website == "unknowndomain.xyz"
        assert scope.website_section == "Docs"


class TestScopeResolverItemName:
    def test_item_name_empty_from_resolve(self):
        """item_name is always empty from resolve() — built in integration layer."""
        resolver = ScopeResolver()
        inp = ScopeInput(
            site_id="docs.aspose.net",
            content_root_raw="${VAR}/docs.aspose.net/words",
            profile_filename="docs.aspose.net.words.yaml",
        )
        scope = resolver.resolve(inp)
        assert scope.item_name == ""

    def test_item_name_empty_even_with_is_test(self):
        """is_test flag does not affect item_name from resolve()."""
        resolver = ScopeResolver()
        inp = ScopeInput(
            site_id="docs.aspose.net",
            content_root_raw="${VAR}/docs.aspose.net/words",
            profile_filename="docs.aspose.net.words.yaml",
            is_test=True,
        )
        scope = resolver.resolve(inp)
        assert scope.item_name == ""


class TestScopeResolverProductDisplay:
    """Product display names use configurable mapping, not simple capitalization."""

    def test_words_display_name(self):
        resolver = ScopeResolver()
        inp = ScopeInput(
            site_id="docs.aspose.net",
            content_root_raw="${VAR}/docs.aspose.net/words",
            profile_filename="docs.aspose.net.words.yaml",
        )
        scope = resolver.resolve(inp)
        assert scope.product == "Aspose.Words"

    def test_3d_display_name(self):
        resolver = ScopeResolver({"product_display_mapping": {"3d": "Aspose.3D"}})
        inp = ScopeInput(
            site_id="docs.aspose.net",
            content_root_raw="${VAR}/docs.aspose.net/3d",
            profile_filename="docs.aspose.net.3d.yaml",
        )
        scope = resolver.resolve(inp)
        assert scope.product == "Aspose.3D"  # Not "Aspose.3d" from simple capitalization


class TestScopeResolverPlatformDisplay:
    def test_net_display(self):
        resolver = ScopeResolver()
        inp = ScopeInput(
            site_id="docs.aspose.net",
            content_root_raw="${VAR}/docs.aspose.net/words/net",
            profile_filename="docs.aspose.net.words.yaml",
        )
        scope = resolver.resolve(inp)
        assert scope.platform == ".NET"  # Not "Net" from simple capitalization

    def test_cpp_display(self):
        resolver = ScopeResolver()
        inp = ScopeInput(
            site_id="docs.aspose.net",
            content_root_raw="${VAR}/docs.aspose.net/words/cpp",
            profile_filename="docs.aspose.net.words.yaml",
        )
        scope = resolver.resolve(inp)
        assert scope.platform == "C++"


class TestTestProfileExclusion:
    def test_test_profile_detected(self):
        resolver = ScopeResolver()
        assert resolver.is_test_profile("blog-test") is True
        assert resolver.is_test_profile("golden-test") is True
        assert resolver.is_test_profile("example.com") is True

    def test_production_profile_not_excluded(self):
        resolver = ScopeResolver()
        assert resolver.is_test_profile("docs.aspose.net") is False
        assert resolver.is_test_profile("blog.aspose.net") is False


class TestIDGeneration:
    def test_stable_work_slice_id_is_deterministic(self):
        id1 = generate_stable_work_slice_id(
            "docs.aspose.net", "docs.aspose.net/words", "words", "All", "content_translation"
        )
        id2 = generate_stable_work_slice_id(
            "docs.aspose.net", "docs.aspose.net/words", "words", "All", "content_translation"
        )
        assert id1 == id2

    def test_different_content_root_different_id(self):
        id1 = generate_stable_work_slice_id(
            "docs.aspose.net", "docs.aspose.net/words", "words", "All", "content_translation"
        )
        id2 = generate_stable_work_slice_id(
            "docs.aspose.net", "docs.aspose.net/cells", "cells", "All", "content_translation"
        )
        assert id1 != id2

    def test_execution_attempt_id_changes_with_parent_run_id(self):
        ctx = GitLabContext(hostname="test-host")
        id1 = generate_execution_attempt_id("parent-1", ctx)
        id2 = generate_execution_attempt_id("parent-2", ctx)
        assert id1 != id2

    def test_segment_run_id_combines_both(self):
        slice_id = uuid.uuid5(uuid.NAMESPACE_URL, "test-slice")
        attempt1 = uuid.uuid5(uuid.NAMESPACE_URL, "test-attempt-1")
        attempt2 = uuid.uuid5(uuid.NAMESPACE_URL, "test-attempt-2")
        seg1 = generate_segment_run_id(slice_id, attempt1)
        seg2 = generate_segment_run_id(slice_id, attempt2)
        assert seg1 != seg2

    def test_same_slice_same_attempt_same_segment(self):
        slice_id = uuid.uuid5(uuid.NAMESPACE_URL, "test-slice")
        attempt = uuid.uuid5(uuid.NAMESPACE_URL, "test-attempt")
        seg1 = generate_segment_run_id(slice_id, attempt)
        seg2 = generate_segment_run_id(slice_id, attempt)
        assert seg1 == seg2


class TestScopeResolverFamilySuffixBug:
    """SG-SCOPE-GAP: Regression tests for the family-token suffix bug.

    Previously, site_id="docs.aspose.net.words" (CLI arg style) caused
    _extract_domain to return "net.words" instead of "aspose.net", which
    then fell through to website="net.words" instead of "aspose.net".
    """

    def setup_method(self):
        self.resolver = ScopeResolver()

    def test_cli_site_id_with_words_suffix_resolves_website_correctly(self):
        """Core regression: website must be aspose.net, not net.words."""
        inp = ScopeInput(
            site_id="docs.aspose.net.words",
            content_root_raw="${ASPOSE_NET_CONTENT}/docs.aspose.net/words",
            profile_filename="docs.aspose.net.words.yaml",
            display_name="Documentation",
        )
        scope = self.resolver.resolve(inp)
        assert scope.website == "aspose.net", (
            f"website must be aspose.net, got {scope.website!r} — "
            "family token suffix must not corrupt domain extraction"
        )
        assert scope.source_site_domain == "aspose.net"
        assert scope.product == "Aspose.Words"
        assert scope.website_section == "Docs"
        assert scope.site_id == "docs.aspose.net"  # normalized
        assert scope.content_root_id == "docs.aspose.net/words"
        assert scope.item_name == ""  # item_name built in integration layer

    def test_cli_site_id_never_produces_net_words(self):
        """website must never be 'net.words' regardless of site_id input."""
        inp = ScopeInput(
            site_id="docs.aspose.net.words",
            content_root_raw="${X}/docs.aspose.net/words",
            profile_filename="",
        )
        scope = self.resolver.resolve(inp)
        assert scope.website != "net.words"
        assert scope.source_site_domain != "net.words"

    def test_cells_suffix_resolves_correctly(self):
        """docs.aspose.net.cells must produce website=aspose.net, product=Aspose.Cells."""
        inp = ScopeInput(
            site_id="docs.aspose.net.cells",
            content_root_raw="${X}/docs.aspose.net/cells",
            profile_filename="docs.aspose.net.cells.yaml",
            display_name="Documentation",
        )
        scope = self.resolver.resolve(inp)
        assert scope.website == "aspose.net"
        assert scope.product == "Aspose.Cells"
        assert scope.source_site_domain == "aspose.net"
        assert scope.site_id == "docs.aspose.net"

    def test_groupdocs_viewer_suffix_resolves_correctly(self):
        """docs.groupdocs.net.viewer must produce website=groupdocs.net, product=GroupDocs.Viewer."""
        inp = ScopeInput(
            site_id="docs.groupdocs.net.viewer",
            content_root_raw="${X}/docs.groupdocs.net/viewer",
            profile_filename="docs.groupdocs.net.viewer.yaml",
            display_name="Documentation",
        )
        scope = self.resolver.resolve(inp)
        assert scope.website == "groupdocs.net"
        assert scope.product == "GroupDocs.Viewer"
        assert scope.source_site_domain == "groupdocs.net"
        assert scope.site_id == "docs.groupdocs.net"

    def test_unknown_suffix_does_not_corrupt_website(self):
        """An unknown family suffix must not corrupt the website field."""
        inp = ScopeInput(
            site_id="docs.aspose.net.unknownfamily",
            content_root_raw="${X}/docs.aspose.net/unknownfamily",
            profile_filename="",
        )
        scope = self.resolver.resolve(inp)
        assert scope.website == "aspose.net"
        assert scope.source_site_domain == "aspose.net"
        assert scope.site_id == "docs.aspose.net"

    def test_audit_path_site_id_unchanged(self):
        """Scope audit path (site_id already correct from YAML) must still resolve same way."""
        inp = ScopeInput(
            site_id="docs.aspose.net",
            content_root_raw="${ASPOSE_NET_CONTENT}/docs.aspose.net/words",
            profile_filename="docs.aspose.net.words.yaml",
            display_name="Documentation",
        )
        scope = self.resolver.resolve(inp)
        assert scope.website == "aspose.net"
        assert scope.product == "Aspose.Words"
        assert scope.site_id == "docs.aspose.net"

    def test_runtime_and_audit_produce_identical_scope(self):
        """CLI arg style and YAML style site_id must produce identical scope."""
        resolver = ScopeResolver()
        content_root = "${ASPOSE_NET_CONTENT}/docs.aspose.net/words"

        runtime_inp = ScopeInput(
            site_id="docs.aspose.net.words",  # CLI arg style
            content_root_raw=content_root,
            profile_filename="docs.aspose.net.words.yaml",
            display_name="Documentation",
        )
        audit_inp = ScopeInput(
            site_id="docs.aspose.net",  # profile YAML style
            content_root_raw=content_root,
            profile_filename="docs.aspose.net.words.yaml",
            display_name="Documentation",
        )
        r1 = resolver.resolve(runtime_inp)
        r2 = resolver.resolve(audit_inp)

        assert r1.website == r2.website
        assert r1.website_section == r2.website_section
        assert r1.product == r2.product
        assert r1.product_family_token == r2.product_family_token
        assert r1.source_site_domain == r2.source_site_domain
        assert r1.site_id == r2.site_id
        assert r1.content_root_id == r2.content_root_id
        assert r1.item_name == r2.item_name

    def test_extract_domain_tld_aware(self):
        """_extract_domain must use TLD-aware parsing, not naive last-2-parts."""
        assert ScopeResolver._extract_domain("docs.aspose.net.words") == "aspose.net"
        assert ScopeResolver._extract_domain("docs.aspose.net") == "aspose.net"
        assert ScopeResolver._extract_domain("blog.aspose.com") == "aspose.com"
        assert ScopeResolver._extract_domain("docs.groupdocs.net.viewer") == "groupdocs.net"
        assert ScopeResolver._extract_domain("about.aspose.net") == "aspose.net"
        # Fallback for no-TLD site_ids
        assert ScopeResolver._extract_domain("blog-test") == "blog-test"


# ---------------------------------------------------------------------------
# Family-aware scope tests (new in family-aware-scope sprint)
# ---------------------------------------------------------------------------

class TestFamilyAwareScopeResolution:
    """Verify family-first scope resolution and fail-closed unknown behaviour."""

    def setup_method(self):
        self.resolver = ScopeResolver()

    # ── products.aspose.org: multi-family root ──────────────────────────────

    def test_products_aspose_org_multi_family_root_is_unknown(self):
        """products.aspose.org content_root has no family token → unknown, not total."""
        inp = ScopeInput(
            site_id="products.aspose.org",
            content_root_raw="${ASPOSE_ORG_CONTENT}/products.aspose.org",
            profile_filename="products.aspose.org.yaml",
            display_name="Landing Pages",
        )
        scope = self.resolver.resolve(inp)
        assert scope.product_family_token == "unknown", (
            "products.aspose.org root covers many families — must never say 'total'"
        )
        assert scope.product == "Aspose.Mixed"
        assert scope.fallback_used is True
        assert scope.reporting_confidence == "low"

    def test_products_aspose_org_family_path_resolves_font(self):
        """When file_path provides the family, scope resolves correctly."""
        inp = ScopeInput(
            site_id="products.aspose.org",
            content_root_raw="${ASPOSE_ORG_CONTENT}/products.aspose.org",
            profile_filename="products.aspose.org.yaml",
            file_path="en/font/python/_index.md",
        )
        scope = self.resolver.resolve(inp)
        assert scope.product_family_token == "font"
        assert scope.product == "Aspose.Font"
        assert scope.reporting_confidence == "high"
        assert scope.fallback_used is False

    def test_products_aspose_org_family_path_resolves_cells(self):
        inp = ScopeInput(
            site_id="products.aspose.org",
            content_root_raw="${ASPOSE_ORG_CONTENT}/products.aspose.org",
            profile_filename="products.aspose.org.yaml",
            file_path="en/cells/net/_index.md",
        )
        scope = self.resolver.resolve(inp)
        assert scope.product_family_token == "cells"
        assert scope.product == "Aspose.Cells"

    # ── aspose.net: {family}/{lang} convention ──────────────────────────────

    def test_kb_aspose_net_per_family_content_root(self):
        """When content_root already includes family (as from partitioning), scope is correct."""
        inp = ScopeInput(
            site_id="kb.aspose.net",
            content_root_raw="/abs/path/to/kb.aspose.net/words",
            profile_filename="kb.aspose.net.yaml",
        )
        scope = self.resolver.resolve(inp)
        assert scope.product_family_token == "words"
        assert scope.product == "Aspose.Words"
        assert scope.reporting_confidence == "high"

    def test_kb_aspose_net_file_path_barcode(self):
        """File path in aspose.net {family}/{lang}/... style resolves barcode."""
        inp = ScopeInput(
            site_id="kb.aspose.net",
            content_root_raw="${ASPOSE_NET_CONTENT}/kb.aspose.net",
            profile_filename="kb.aspose.net.yaml",
            file_path="barcode/de/1d-reader/_index.md",
        )
        scope = self.resolver.resolve(inp)
        assert scope.product_family_token == "barcode"
        assert scope.product == "Aspose.BarCode"

    # ── unknown must not become total ──────────────────────────────────────

    def test_unknown_content_root_is_not_total(self):
        """A completely unknown content root must resolve to 'unknown', not 'total'."""
        inp = ScopeInput(
            site_id="docs.aspose.net",
            content_root_raw="${ASPOSE_NET_CONTENT}/docs.aspose.net",
            profile_filename="docs.aspose.net.yaml",
        )
        scope = self.resolver.resolve(inp)
        assert scope.product_family_token != "total", (
            "Unknown content root must never resolve to 'total'"
        )
        assert scope.product_family_token == "unknown"

    def test_mixed_run_not_total(self):
        """A multi-family run root must produce 'unknown' not 'total'."""
        inp = ScopeInput(
            site_id="products.aspose.net",
            content_root_raw="${ASPOSE_NET_CONTENT}/products.aspose.net",
            profile_filename="products.aspose.net.yaml",
            display_name="Landing Pages",
        )
        scope = self.resolver.resolve(inp)
        assert scope.product_family_token == "unknown"
        assert scope.product != "Aspose.Total"

    # ── explicit total — only when family_scope="total" ────────────────────

    def test_explicit_total_via_family_scope(self):
        """family_scope='total' is the only way to legitimately get Aspose.Total."""
        inp = ScopeInput(
            site_id="products.aspose.org",
            content_root_raw="${ASPOSE_ORG_CONTENT}/products.aspose.org",
            profile_filename="products.aspose.org.yaml",
            family_scope="total",
        )
        scope = self.resolver.resolve(inp)
        assert scope.product_family_token == "total"
        assert scope.product == "Aspose.Total"

    def test_total_from_path_segment(self):
        """A file under en/total/ still resolves via path-scan before family_scope."""
        inp = ScopeInput(
            site_id="products.aspose.org",
            content_root_raw="${ASPOSE_ORG_CONTENT}/products.aspose.org",
            profile_filename="products.aspose.org.yaml",
            file_path="en/total/_index.md",
        )
        scope = self.resolver.resolve(inp)
        assert scope.product_family_token == "total"
        assert scope.product == "Aspose.Total"

    # ── single-family profiles remain unchanged ────────────────────────────

    def test_docs_aspose_net_words_still_resolves_correctly(self):
        """Single-family profile (words in content_root) must be unaffected."""
        inp = ScopeInput(
            site_id="docs.aspose.net",
            content_root_raw="${ASPOSE_NET_CONTENT}/docs.aspose.net/words",
            profile_filename="docs.aspose.net.words.yaml",
            display_name="Documentation",
        )
        scope = self.resolver.resolve(inp)
        assert scope.product_family_token == "words"
        assert scope.product == "Aspose.Words"
        assert scope.reporting_confidence == "high"
        assert scope.fallback_used is False

    def test_metrics_hints_total_blocked_without_family_scope(self):
        """metrics_hints.product_family='total' must be blocked without family_scope='total'."""
        inp = ScopeInput(
            site_id="products.aspose.org",
            content_root_raw="${ASPOSE_ORG_CONTENT}/products.aspose.org",
            profile_filename="products.aspose.org.yaml",
            metrics_hints={"product_family": "total"},
        )
        scope = self.resolver.resolve(inp)
        # Must NOT be "total" — hints cannot override to total without authority
        assert scope.product_family_token != "total", (
            "metrics_hints.product_family='total' must not be accepted without "
            "family_scope='total' in the profile"
        )

    def test_metrics_hints_specific_family_accepted(self):
        """metrics_hints.product_family='words' is still accepted as weak override."""
        inp = ScopeInput(
            site_id="products.aspose.org",
            content_root_raw="${ASPOSE_ORG_CONTENT}/products.aspose.org",
            profile_filename="products.aspose.org.yaml",
            metrics_hints={"product_family": "words"},
        )
        scope = self.resolver.resolve(inp)
        assert scope.product_family_token == "words"
        assert scope.product == "Aspose.Words"
