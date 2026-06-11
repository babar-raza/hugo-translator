"""Profile-driven scope resolution and ID generation for Agent Metrics API.

ScopeResolver derives website, section, product, platform, and item_name
from profile data at runtime using a 4-level priority cascade.
No static inventory assumptions — works with any profile configuration.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .gitlab_context import GitLabContext, collect_gitlab_context

logger = logging.getLogger(__name__)

# UUID5 namespace for deterministic ID generation
_NAMESPACE = uuid.NAMESPACE_URL


# ---------------------------------------------------------------------------
# Default mappings — overridden by global.yaml agent_metrics config
# ---------------------------------------------------------------------------

# Website is the source domain the user navigates to — no cross-TLD normalization.
# Empty by default so domain passes through as-is (aspose.net, aspose.org, etc.).
DEFAULT_WEBSITE_MAPPING: dict[str, str] = {}

DEFAULT_SECTION_MAPPING: dict[str, str] = {
    # By subsystem prefix
    "docs": "Docs",
    "kb": "KB",
    "blog": "Blog",
    "products": "Product Pages",
    "reference": "API Reference",
    "websites": "Product Pages",
    "www": "Product Pages",
    "about": "About",
    # By display_name
    "Documentation": "Docs",
    "Landing Pages": "Product Pages",
    "blog posts": "Blog",
    "knowledge base articles": "KB",
    "API References": "API Reference",
    "files": "Product Pages",
}

DEFAULT_BRAND_MAPPING: dict[str, str] = {
    "aspose.com": "Aspose",
    "aspose.net": "Aspose",
    "aspose.org": "Aspose",
    "groupdocs.com": "GroupDocs",
    "groupdocs.net": "GroupDocs",
    "groupdocs.org": "GroupDocs",
    "conholdate.com": "Conholdate",
    "conholdate.net": "Conholdate",
    "conholdate.org": "Conholdate",
}

# Domain-based platform fallback: aspose.net always means .NET (no platform segment in paths).
# For aspose.org, platform is encoded in content path hierarchy — handled by Level 3 path-scan.
DEFAULT_DOMAIN_PLATFORM_MAPPING: dict[str, str] = {
    "aspose.net": "net",
}

DEFAULT_PRODUCT_DISPLAY_MAPPING: dict[str, str] = {
    "words": "Aspose.Words",
    "cells": "Aspose.Cells",
    "pdf": "Aspose.PDF",
    "slides": "Aspose.Slides",
    "email": "Aspose.Email",
    "imaging": "Aspose.Imaging",
    "3d": "Aspose.3D",
    "barcode": "Aspose.BarCode",
    "cad": "Aspose.CAD",
    "diagram": "Aspose.Diagram",
    "html": "Aspose.HTML",
    "ocr": "Aspose.OCR",
    "psd": "Aspose.PSD",
    "zip": "Aspose.ZIP",
    "tasks": "Aspose.Tasks",
    "note": "Aspose.Note",
    "font": "Aspose.Font",
    "tex": "Aspose.TeX",
    "page": "Aspose.Page",
    "svg": "Aspose.SVG",
    "gis": "Aspose.GIS",
    "total": "Aspose.Total",
    "conversion": "GroupDocs.Conversion",
    "signature": "GroupDocs.Signature",
    "viewer": "GroupDocs.Viewer",
    "editor": "GroupDocs.Editor",
    "merger": "GroupDocs.Merger",
    "annotation": "GroupDocs.Annotation",
    "comparison": "GroupDocs.Comparison",
    "metadata": "GroupDocs.Metadata",
    "parser": "GroupDocs.Parser",
    "watermark": "GroupDocs.Watermark",
}

DEFAULT_PLATFORM_DISPLAY_MAPPING: dict[str, str] = {
    "net": ".NET",
    "java": "Java",
    "python": "Python",
    "cpp": "C++",
    "nodejs": "Node.js",
    "php": "PHP",
    "android": "Android",
    "go": "Go",
    "cloud": "Cloud",
    "all": "All",
}

DEFAULT_KNOWN_FAMILIES: list[str] = list(DEFAULT_PRODUCT_DISPLAY_MAPPING.keys())

DEFAULT_KNOWN_PLATFORMS: list[str] = list(DEFAULT_PLATFORM_DISPLAY_MAPPING.keys())

DEFAULT_EXCLUDED_PREFIXES: list[str] = [
    "blog-test",
    "products-test",
    "golden-test",
    "e2e-reference",
    "stage-b-canary",
    "ws5-test",
    "nested-list-test",
    "realworld",
    "example",
    "default",
]


@dataclass
class ScopeInput:
    site_id: str
    content_root_raw: str
    profile_filename: str
    display_name: str | None = None
    metrics_hints: dict | None = None
    cli_overrides: dict | None = None
    operation_type: str = "content_translation"
    is_test: bool = False
    # family_scope declares the scope intent when it cannot be auto-detected from paths.
    # Values: "single" | "multi" | "total" | None (auto-detect).
    # "total" is the ONLY way to legitimately resolve to Aspose.Total.
    family_scope: str | None = None
    # file_path: path of the source file relative to the content root.
    # When provided, family is extracted from file path first (strongest path evidence).
    file_path: str | None = None


@dataclass
class ResolvedScope:
    # Posted to API
    website: str = ""
    website_section: str = ""
    product: str = ""
    platform: str = ""
    item_name: str = ""
    content_root_id: str = ""

    # Evidence only
    site_id: str = ""
    source_site_domain: str = ""
    # product_family_token values:
    #   "words", "cells", ... — a resolved single family
    #   "total"               — explicitly declared Aspose.Total (family_scope: total)
    #   "unknown"             — multi-family or unresolved; callers should partition
    product_family_token: str = ""
    operation_type: str = "content_translation"
    locale_grain: str = "all"

    # Diagnostics
    detection_method: str = ""
    fallback_used: bool = False
    reporting_confidence: str = "high"
    warnings: list[str] = field(default_factory=list)


class ScopeResolver:
    """Generic profile-driven scope resolution."""

    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config or {}
        self.website_mapping = cfg.get("metrics_website_mapping", DEFAULT_WEBSITE_MAPPING)
        self.section_mapping = cfg.get("metrics_section_mapping", DEFAULT_SECTION_MAPPING)
        self.brand_mapping = cfg.get("metrics_brand_mapping", DEFAULT_BRAND_MAPPING)
        self.product_display_mapping = cfg.get(
            "product_display_mapping", DEFAULT_PRODUCT_DISPLAY_MAPPING
        )
        self.platform_display_mapping = cfg.get(
            "platform_display_mapping", DEFAULT_PLATFORM_DISPLAY_MAPPING
        )
        self.domain_platform_mapping = cfg.get(
            "metrics_domain_platform_mapping", DEFAULT_DOMAIN_PLATFORM_MAPPING
        )
        self.known_families = cfg.get("known_product_families", DEFAULT_KNOWN_FAMILIES)
        self.known_platforms = cfg.get("known_platforms", DEFAULT_KNOWN_PLATFORMS)
        self.excluded_prefixes = cfg.get("excluded_site_id_prefixes", DEFAULT_EXCLUDED_PREFIXES)

    # --- Private resolution methods ---

    _detection_method: str = "profile_field_derivation"

    def _resolve_website(self, inp: ScopeInput, domain: str) -> str:
        # Level 1: CLI overrides
        if inp.cli_overrides and inp.cli_overrides.get("website"):
            self._detection_method = "cli_override"
            return inp.cli_overrides["website"]
        # Level 2: metrics_hints
        if inp.metrics_hints and inp.metrics_hints.get("website"):
            self._detection_method = "metrics_hints"
            return inp.metrics_hints["website"]
        # Level 3: mapping
        mapped = self.website_mapping.get(domain)
        if mapped:
            self._detection_method = "profile_field_derivation"
            return mapped
        # Level 4: fallback to domain as-is
        return domain

    def _resolve_section(self, inp: ScopeInput, subsystem: str) -> str:
        # Level 1: CLI
        if inp.cli_overrides and inp.cli_overrides.get("website_section"):
            return inp.cli_overrides["website_section"]
        # Level 2: hints
        if inp.metrics_hints and inp.metrics_hints.get("website_section"):
            return inp.metrics_hints["website_section"]
        # Level 3: subsystem mapping
        section = self.section_mapping.get(subsystem)
        if section:
            return section
        # Level 3b: display_name mapping
        if inp.display_name:
            section = self.section_mapping.get(inp.display_name)
            if section:
                return section
            return inp.display_name  # use display_name as-is
        # Level 4: fallback
        return "Unknown"

    def _resolve_family(self, inp: ScopeInput, content_root_id: str) -> str | None:
        # Level 1: CLI override (highest authority)
        if inp.cli_overrides and inp.cli_overrides.get("product_family"):
            return inp.cli_overrides["product_family"]

        # Level 2: per-file path evidence (stronger than content_root — handles mixed roots)
        if inp.file_path:
            from .family_extraction import extract_family_from_path

            fam = extract_family_from_path(inp.file_path, self.known_families)
            if fam:
                return fam

        # Level 3: content_root_id path segments (e.g. "kb.aspose.net/words" → "words")
        segments = content_root_id.split("/")
        for seg in reversed(segments):
            if seg in self.known_families:
                return seg

        # Level 3b: profile filename parts (e.g. "docs.aspose.net.words.yaml" → "words")
        parts = inp.profile_filename.replace(".yaml", "").replace(".yml", "").split(".")
        for part in reversed(parts):
            if part in self.known_families:
                return part

        # Level 4: explicit profile-level family_scope == "total"
        # This is the ONLY legitimate path to returning "total" when no family token is
        # present in the path.  All other missing-family cases → None (unknown/multi).
        if inp.family_scope == "total":
            return "total"

        # Level 5: metrics_hints (weakest — explicit override only, never auto-fallback)
        if inp.metrics_hints and inp.metrics_hints.get("product_family"):
            hint_fam = inp.metrics_hints["product_family"]
            # Only accept "total" from hints when family_scope == "total" is also set;
            # otherwise hints can override to a specific family but not to "total".
            if hint_fam == "total" and inp.family_scope != "total":
                logger.warning(
                    "metrics_hints.product_family='total' ignored — "
                    "set family_scope: total in profile to explicitly declare Total scope."
                )
            else:
                return hint_fam

        # Not found — caller must handle None; must NOT substitute "total"
        return None

    def _resolve_platform(self, inp: ScopeInput, content_root_id: str, domain: str = "") -> str:
        # Level 1: CLI
        if inp.cli_overrides and inp.cli_overrides.get("platform"):
            return inp.cli_overrides["platform"]
        # Level 2: hints
        if inp.metrics_hints and inp.metrics_hints.get("platform"):
            return inp.metrics_hints["platform"]
        # Level 3: content_root_id path segments (covers aspose.org where platform is in path)
        segments = content_root_id.split("/")
        for seg in reversed(segments):
            if seg in self.known_platforms and seg != "all":
                return seg
        # Level 3b: domain-based mapping (covers aspose.net where platform is not in path)
        if domain and domain in self.domain_platform_mapping:
            return self.domain_platform_mapping[domain]
        return "all"

    def _resolve_product_display(
        self, inp: ScopeInput, website: str, family_token: str | None
    ) -> str:
        # Level 1: CLI direct product name
        if inp.cli_overrides and inp.cli_overrides.get("product"):
            return inp.cli_overrides["product"]
        # Level 2: hints direct product name
        if inp.metrics_hints and inp.metrics_hints.get("product"):
            return inp.metrics_hints["product"]
        # Look up display mapping (covers "total" → "Aspose.Total" when legitimately set)
        if family_token and family_token in self.product_display_mapping:
            return self.product_display_mapping[family_token]
        # Build from brand + family
        brand = self._get_brand(website)
        if not family_token:
            # No family resolved — content root covers multiple families or is unknown.
            # Use ".Mixed" to signal this accurately; never emit ".Total" here.
            return f"{brand}.Mixed"
        # Unknown family token — warn but produce a name
        self.warnings_buffer.append(f"Unknown product family token: {family_token}")
        return f"{brand}.{family_token.capitalize()}"

    def _resolve_platform_display(self, platform_token: str) -> str:
        return self.platform_display_mapping.get(platform_token, platform_token)

    def _get_brand(self, website: str) -> str:
        brand = self.brand_mapping.get(website)
        if brand:
            return brand
        # Fallback: capitalize first segment
        return website.split(".")[0].capitalize()

    @property
    def warnings_buffer(self) -> list[str]:
        if not hasattr(self, "_warnings"):
            self._warnings: list[str] = []
        return self._warnings

    def resolve(self, inp: ScopeInput) -> ResolvedScope:
        self._warnings = []
        self._detection_method = "profile_field_derivation"
        scope = ResolvedScope()
        scope.operation_type = inp.operation_type
        scope.content_root_id = derive_content_root_id(inp.content_root_raw)

        # Derive canonical site_id from the content_root_id's first path segment.
        # The content_root_id is always derived from the profile's content_roots entry
        # (never from the CLI --site argument), so its first segment is the true site
        # domain without any family/platform suffix.
        # Example: content_root_id="docs.aspose.net/words" → "docs.aspose.net"
        # This fixes cases where the CLI passes "docs.aspose.net.words" (filename stem)
        # but the profile's site_id field is "docs.aspose.net".
        first_segment = scope.content_root_id.split("/")[0]
        canonical_site_id = first_segment if "." in first_segment else inp.site_id
        scope.site_id = canonical_site_id

        domain = self._extract_domain(canonical_site_id)
        subsystem = self._extract_subsystem(canonical_site_id)
        scope.source_site_domain = domain

        scope.website = self._resolve_website(inp, domain)
        scope.website_section = self._resolve_section(inp, subsystem)

        family_token = self._resolve_family(inp, scope.content_root_id)
        if family_token:
            scope.product_family_token = family_token
        else:
            # Could not resolve a single family — content root is multi-family or unknown.
            # Use "unknown" sentinel; callers should partition by family before calling resolve().
            scope.product_family_token = "unknown"
        scope.product = self._resolve_product_display(inp, scope.website, family_token)

        platform_token = self._resolve_platform(inp, scope.content_root_id, domain)
        scope.platform = self._resolve_platform_display(platform_token)

        # item_name is built in MetricsRunContext.finish() after file counts are known.

        scope.detection_method = self._detection_method
        scope.warnings = list(self._warnings)

        # Determine fallback and confidence
        if not family_token:
            # Multi-family or unknown content root — mark as low-confidence fallback
            # so that callers (audit gate, validation) can detect and escalate.
            scope.fallback_used = True
            scope.reporting_confidence = "low"
            scope.warnings.append(
                "product_family_token could not be resolved — content root may cover "
                "multiple product families. Partition by family before translation."
            )
        else:
            scope.reporting_confidence = "high"

        # Check for blank fields (item_name is built in integration layer, not here)
        for f in ["website", "website_section", "product", "platform"]:
            if not getattr(scope, f):
                scope.warnings.append(f"Blank field: {f}")
                scope.fallback_used = True
                scope.reporting_confidence = "low"

        return scope

    # Known TLDs used to detect the brand.tld boundary in site_id strings.
    _KNOWN_TLDS: frozenset[str] = frozenset({"com", "net", "org", "io", "co"})

    @staticmethod
    def _extract_domain(site_id: str) -> str:
        """Extract base domain from site_id, ignoring subsystem prefix and family/platform suffixes.

        Scans left-to-right for the first known TLD segment; the part immediately
        before it is the brand name.  This correctly handles site_ids that carry a
        family/platform token after the TLD (e.g. 'docs.aspose.net.words' -> 'aspose.net').

        Examples:
            'docs.aspose.net'            -> 'aspose.net'
            'docs.aspose.net.words'      -> 'aspose.net'   (was 'net.words' — fixed)
            'blog.aspose.com'            -> 'aspose.com'
            'docs.groupdocs.net.viewer'  -> 'groupdocs.net'
            'blog-test'                  -> 'blog-test'    (no TLD, fallback)
        """
        parts = site_id.split(".")
        known_tlds = ScopeResolver._KNOWN_TLDS
        for i, part in enumerate(parts):
            if part in known_tlds and i > 0:
                return f"{parts[i - 1]}.{part}"
        # Fallback: last two parts (preserves old behaviour for unknown TLDs)
        if len(parts) >= 2:
            return ".".join(parts[-2:])
        return site_id

    @staticmethod
    def _extract_subsystem(site_id: str) -> str:
        """Extract subsystem prefix (e.g., 'docs.aspose.net' -> 'docs')."""
        return site_id.split(".")[0] if "." in site_id else site_id

    def is_test_profile(self, site_id: str) -> bool:
        return any(site_id.startswith(prefix) for prefix in self.excluded_prefixes)


# ---------------------------------------------------------------------------
# content_root_id derivation
# ---------------------------------------------------------------------------


def derive_content_root_id(content_root_raw: str) -> str:
    """Strip env-var prefix, normalize to forward-slash repo-relative path."""
    # Normalize backslashes first so regex can match either separator
    stripped = content_root_raw.replace("\\", "/")
    stripped = re.sub(r"^\$\{[^}]+\}/", "", stripped)
    stripped = stripped.rstrip("/")
    # Reject absolute paths
    if stripped.startswith("/") or (len(stripped) >= 2 and stripped[1] == ":"):
        logger.warning("Absolute path in content_root_id: %s — extracting suffix", stripped)
        # Try to find a known domain pattern
        for pattern in [r"([\w-]+\.[\w-]+\.[\w]+(?:/\w+)*)", r"([\w-]+\.[\w-]+\.[\w]+)"]:
            match = re.search(pattern, stripped)
            if match:
                stripped = match.group(1)
                break
        else:
            parts = stripped.replace("\\", "/").split("/")
            stripped = "/".join(parts[-2:]) if len(parts) >= 2 else parts[-1]
    return stripped


# ---------------------------------------------------------------------------
# ID generation
# ---------------------------------------------------------------------------


def _get_repo_identifier() -> str:
    """Get repo identifier from git remote or env var."""
    env_val = os.environ.get("HUGO_REPO_ID")
    if env_val:
        return env_val
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            url = result.stdout.strip()
            # Extract repo name from URL
            name = url.rstrip("/").split("/")[-1]
            if name.endswith(".git"):
                name = name[:-4]
            return name
    except Exception:
        pass
    return "hugo-translator"


def _get_source_commit_sha() -> str:
    """Get current git HEAD SHA."""
    ci_sha = os.environ.get("CI_COMMIT_SHA")
    if ci_sha:
        return ci_sha
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


def generate_stable_work_slice_id(
    site_id: str,
    content_root_id: str,
    product_family_token: str,
    platform: str,
    operation_type: str,
    retry_group: str = "initial",
) -> uuid.UUID:
    repo_id = _get_repo_identifier()
    commit_sha = _get_source_commit_sha()
    dimensions = "|".join(
        [
            repo_id,
            commit_sha,
            site_id,
            content_root_id,
            product_family_token,
            platform,
            "all",  # locale grain
            operation_type,
            retry_group,
        ]
    )
    return uuid.uuid5(_NAMESPACE, dimensions)


def generate_execution_attempt_id(
    parent_run_id: str,
    gitlab_ctx: GitLabContext | None = None,
) -> uuid.UUID:
    if gitlab_ctx is None:
        gitlab_ctx = collect_gitlab_context()
    dimensions = "|".join(
        [
            parent_run_id,
            gitlab_ctx.ci_pipeline_id or "local",
            gitlab_ctx.ci_job_id or "none",
            gitlab_ctx.hostname,
        ]
    )
    return uuid.uuid5(_NAMESPACE, dimensions)


def generate_segment_run_id(
    stable_work_slice_id: uuid.UUID,
    execution_attempt_id: uuid.UUID,
) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, f"{stable_work_slice_id}:{execution_attempt_id}")


# ---------------------------------------------------------------------------
# Scope audit CLI
# ---------------------------------------------------------------------------


def run_scope_audit(
    profiles_dir: str = "config/site_profiles", output_path: str | None = None
) -> list[dict]:
    """Run scope audit over all profiles, classify each."""
    resolver = ScopeResolver()
    results = []
    profiles_path = Path(profiles_dir)

    for profile_file in sorted(profiles_path.glob("*.yaml")):
        try:
            with open(profile_file, encoding="utf-8") as f:
                profile = yaml.safe_load(f) or {}
        except Exception as e:
            results.append(
                {
                    "profile": profile_file.name,
                    "error": str(e),
                    "classification": "ambiguous",
                }
            )
            continue

        site_id = profile.get("site_id", "")
        is_test = resolver.is_test_profile(site_id)
        content_roots = profile.get("content_roots", [])

        if not content_roots:
            content_roots = [site_id]

        for root in content_roots:
            inp = ScopeInput(
                site_id=site_id,
                content_root_raw=root,
                profile_filename=profile_file.name,
                display_name=profile.get("display_name"),
                metrics_hints=profile.get("metrics_hints"),
                family_scope=profile.get("family_scope"),
            )
            scope = resolver.resolve(inp)

            # Classify
            if is_test:
                classification = "fixture_excluded"
            elif scope.product_family_token == "unknown":
                # Multi-family or unresolved — requires family-aware partitioning
                classification = "multi_family_unresolved"
            elif scope.warnings and not scope.product_family_token == "total":
                classification = "ambiguous"
            elif scope.product_family_token == "total":
                classification = "explicit_total"
            elif scope.fallback_used:
                classification = "fallback_accepted"
            else:
                classification = "exact"

            results.append(
                {
                    "profile": profile_file.name,
                    "site_id": site_id,
                    "content_root_id": scope.content_root_id,
                    "resolved": {
                        "website": scope.website,
                        "website_section": scope.website_section,
                        "product": scope.product,
                        "platform": scope.platform,
                    },
                    "classification": classification,
                    "detection_method": scope.detection_method,
                    "fallback_used": scope.fallback_used,
                    "reporting_confidence": scope.reporting_confidence,
                    "warnings": scope.warnings,
                    "is_test_profile": is_test,
                }
            )

    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        logger.info("Scope audit written to %s", out)

    return results


def check_audit_gate(results: list[dict]) -> tuple[bool, list[str]]:
    """Check if scope audit passes the hard gate.

    Returns (passed, blocking_reasons).
    """
    blockers: list[str] = []
    for row in results:
        if row.get("is_test_profile"):
            continue
        classification = row.get("classification", "ambiguous")
        if classification == "ambiguous":
            blockers.append(
                f"AMBIGUOUS: {row.get('profile')} / {row.get('content_root_id')} "
                f"— warnings: {row.get('warnings')}"
            )
        resolved = row.get("resolved", {})
        for field_name in ["website", "website_section", "product", "platform"]:
            if not resolved.get(field_name):
                blockers.append(f"BLANK FIELD: {row.get('profile')} / {field_name} is empty")
    return (len(blockers) == 0, blockers)


if __name__ == "__main__":
    import sys

    if "--audit" in sys.argv:
        output = "data/metrics/scope_audit.json"
        results = run_scope_audit(output_path=output)
        passed, blockers = check_audit_gate(results)

        print(f"\nScope Audit: {len(results)} entries")
        for r in results:
            status = r.get("classification", "?")
            print(
                f"  [{status:>18}] {r.get('profile', '?'):40} -> {r.get('resolved', {}).get('product', '?')}"
            )

        if blockers:
            print(f"\nGATE BLOCKED — {len(blockers)} issue(s):")
            for b in blockers:
                print(f"  - {b}")
            sys.exit(1)
        else:
            print("\nGATE PASSED — all production profiles resolved cleanly.")
            sys.exit(0)
    else:
        print("Usage: python -m src.observability.metrics_scope --audit")
        sys.exit(1)
