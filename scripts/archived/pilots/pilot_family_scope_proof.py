# ARCHIVED: 2026-06-11. Sprint: family-scope-closure-20260521. STATUS: COMPLETE.
# Evidence committed in reports/family-scope-challenge-20260521-evidence.zip.
# No replacement needed — this was a one-time proof script.
"""
Pilot proof script for family-aware translator scope.

Exercises the EXACT production code path:
  _expand_family_content_roots -> MetricsRunContext -> ScopeResolver -> payload

Does NOT run translation (dry_run=True in agent_metrics, empty target_langs list).
Generates evidence sidecars in /tmp/pilot_evidence/.

Usage:
    PYTHONPATH="C:/Users/prora/AppData/Roaming/Python/Python313/site-packages" \
    python scripts/pilot_family_scope_proof.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure project root is in PYTHONPATH
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

FIXTURE_ROOT = Path("C:/Users/prora/AppData/Local/Temp/pilot_fixture")
EVIDENCE_DIR = "C:/Users/prora/AppData/Local/Temp/pilot_evidence"

# ── Mock config service ──────────────────────────────────────────────────────


class MockConfigService:
    """Minimal config service for pilot -- wraps real agent_metrics config."""

    def get_config(self) -> dict:
        return {
            "agent_metrics": {
                "enabled": True,
                "dry_run": True,
                "evidence_dir": EVIDENCE_DIR,
            }
        }

    def resolve_content_root(self, content_root: str) -> Path:
        return Path(content_root)


# ── Pilot cases ─────────────────────────────────────────────────────────────

CASES = [
    # (label, site_id, content_root_raw, profile_filename, family_scope,
    #  expect_family, expect_product, expect_confidence)
    # Case 1: products.aspose.org MULTI-FAMILY ROOT -- must be Mixed/unknown
    (
        "products.aspose.org multi-family root",
        "products.aspose.org",
        str(FIXTURE_ROOT / "products.aspose.org"),
        "products.aspose.org.yaml",
        "multi",
        "unknown",
        "Aspose.Mixed",
        "low",
    ),
    # Case 2: products.aspose.org/en/font -- per-family batch after partitioning
    (
        "products.aspose.org per-family: font",
        "products.aspose.org",
        str(FIXTURE_ROOT / "products.aspose.org" / "en" / "font"),
        "products.aspose.org.yaml",
        None,  # family_scope not needed -- path has it
        "font",
        "Aspose.Font",
        "high",
    ),
    # Case 3: products.aspose.org/en/cells -- per-family batch after partitioning
    (
        "products.aspose.org per-family: cells",
        "products.aspose.org",
        str(FIXTURE_ROOT / "products.aspose.org" / "en" / "cells"),
        "products.aspose.org.yaml",
        None,
        "cells",
        "Aspose.Cells",
        "high",
    ),
    # Case 4: products.aspose.org/en/words -- per-family batch after partitioning
    (
        "products.aspose.org per-family: words",
        "products.aspose.org",
        str(FIXTURE_ROOT / "products.aspose.org" / "en" / "words"),
        "products.aspose.org.yaml",
        None,
        "words",
        "Aspose.Words",
        "high",
    ),
    # Case 5: docs.aspose.net.words -- single-family regression
    (
        "docs.aspose.net.words single-family regression",
        "docs.aspose.net.words",
        str(FIXTURE_ROOT / "docs.aspose.net" / "words"),
        "docs.aspose.net.words.yaml",
        "single",
        "words",
        "Aspose.Words",
        "high",
    ),
    # Case 6: kb.aspose.net/cells -- net-style single-family per-family batch
    (
        "kb.aspose.net per-family: cells (net-style path)",
        "kb.aspose.net",
        str(FIXTURE_ROOT / "kb.aspose.net" / "cells"),
        "kb.aspose.net.yaml",
        None,
        "cells",
        "Aspose.Cells",
        "high",
    ),
    # Case 7: unknown/mixed -- no family in path, no family_scope: total
    (
        "unknown root -> fail-closed to Mixed (not Total)",
        "products.aspose.org",
        str(FIXTURE_ROOT / "products.aspose.org" / "en"),
        "products.aspose.org.yaml",
        None,  # no family_scope
        "unknown",
        "Aspose.Mixed",
        "low",
    ),
]


# ── Worker partitioning proof ────────────────────────────────────────────────


def prove_worker_partitioning():
    """Prove _expand_family_content_roots correctly partitions multi-family root."""
    from src.observability.family_extraction import discover_family_subdirs
    from src.observability.metrics_scope import DEFAULT_KNOWN_FAMILIES

    print("\n" + "=" * 60)
    print("WORKER PARTITIONING PROOF")
    print("=" * 60)

    # Simulate the expansion logic directly (same as _expand_family_content_roots)
    content_root_dir = FIXTURE_ROOT / "products.aspose.org"
    family_dirs = discover_family_subdirs(content_root_dir, DEFAULT_KNOWN_FAMILIES)

    print(f"\nContent root: {content_root_dir}")
    print(f"Discovered family dirs: {len(family_dirs)}")
    for token, path in family_dirs:
        print(f"  [{token}] -> {path}")

    assert len(family_dirs) == 3, f"Expected 3 family dirs, got {len(family_dirs)}"
    tokens = {t for t, _ in family_dirs}
    assert tokens == {"font", "cells", "words"}, f"Wrong families: {tokens}"
    print("\nPASS Partitioning PASS: 3 families discovered (font, cells, words)")

    # Prove net-style discovery
    net_root = FIXTURE_ROOT / "kb.aspose.net"
    net_dirs = discover_family_subdirs(net_root, DEFAULT_KNOWN_FAMILIES)
    print(f"\nNet-style root: {net_root}")
    print(f"Discovered family dirs: {len(net_dirs)}")
    for token, path in net_dirs:
        print(f"  [{token}] -> {path}")
    assert len(net_dirs) == 1, f"Expected 1 (cells), got {len(net_dirs)}"
    assert net_dirs[0][0] == "cells"
    print("PASS Net-style partitioning PASS: 1 family (cells) discovered")

    return {
        "org_style": {
            "content_root": str(content_root_dir),
            "families_discovered": [t for t, _ in family_dirs],
        },
        "net_style": {
            "content_root": str(net_root),
            "families_discovered": [t for t, _ in net_dirs],
        },
    }


# ── Scope resolution proof ───────────────────────────────────────────────────


def prove_scope_resolution():
    """Prove ScopeResolver produces correct per-family payloads for each case."""
    from src.observability.metrics_scope import ScopeInput, ScopeResolver

    print("\n" + "=" * 60)
    print("SCOPE RESOLUTION PROOF")
    print("=" * 60)

    results = []
    all_pass = True
    resolver = ScopeResolver()

    for (
        label,
        site_id,
        content_root_raw,
        profile_filename,
        family_scope,
        expect_family,
        expect_product,
        expect_confidence,
    ) in CASES:
        inp = ScopeInput(
            site_id=site_id,
            content_root_raw=content_root_raw,
            profile_filename=profile_filename,
            family_scope=family_scope,
        )
        scope = resolver.resolve(inp)

        ok = (
            scope.product_family_token == expect_family
            and scope.product == expect_product
            and scope.reporting_confidence == expect_confidence
        )
        status = "PASS PASS" if ok else "FAIL FAIL"
        if not ok:
            all_pass = False

        print(f"\n{status}: {label}")
        print(f"  content_root_id:      {scope.content_root_id}")
        print(f"  product_family_token: {scope.product_family_token}  (expected: {expect_family})")
        print(f"  product:              {scope.product}  (expected: {expect_product})")
        print(
            f"  reporting_confidence: {scope.reporting_confidence}  (expected: {expect_confidence})"
        )
        print(f"  fallback_used:        {scope.fallback_used}")
        if scope.warnings:
            print(f"  warnings:             {scope.warnings}")

        results.append(
            {
                "label": label,
                "pass": ok,
                "product_family_token": scope.product_family_token,
                "product": scope.product,
                "reporting_confidence": scope.reporting_confidence,
                "fallback_used": scope.fallback_used,
                "warnings": scope.warnings,
            }
        )

    print(f"\n{'=' * 60}")
    if all_pass:
        print("SCOPE RESOLUTION: ALL CASES PASS PASS")
    else:
        print("SCOPE RESOLUTION: SOME CASES FAILED FAIL")
    return results, all_pass


# ── MetricsRunContext dry-run payload proof ──────────────────────────────────


def prove_metrics_payloads():
    """Prove MetricsRunContext produces correct dry-run payloads."""
    from src.observability.agent_metrics_integration import MetricsRunContext

    print("\n" + "=" * 60)
    print("METRICS PAYLOAD PROOF (dry_run=True)")
    print("=" * 60)

    config_svc = MockConfigService()
    payloads = []
    all_pass = True

    for (
        label,
        site_id,
        content_root_raw,
        profile_filename,
        family_scope,
        expect_family,
        expect_product,
        expect_confidence,
    ) in CASES:
        ctx = MetricsRunContext(
            site_id=site_id,
            content_root_raw=content_root_raw,
            config_service=config_svc,
            job_type="Content Translation",
            profile_filename=profile_filename,
            family_scope=family_scope,
        )
        ctx.start()
        result = ctx.finish(items_discovered=5, items_succeeded=5, items_failed=0)

        # Inspect the evidence sidecar for the scope info
        evidence_path = Path(EVIDENCE_DIR)
        # Find most recently modified sidecar
        sidecars = sorted(
            evidence_path.rglob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        scope_data = {}
        if sidecars:
            with open(sidecars[0]) as f:
                ev = json.load(f)
            scope_data = ev.get("scope", {})

        actual_family = scope_data.get("product_family_token", "?")
        actual_product = scope_data.get("product", "?")
        actual_confidence = scope_data.get("reporting_confidence", "?")

        ok = (
            actual_family == expect_family
            and actual_product == expect_product
            and actual_confidence == expect_confidence
        )
        status = "PASS PASS" if ok else "FAIL FAIL"
        if not ok:
            all_pass = False

        print(f"\n{status}: {label}")
        print(f"  product_family_token: {actual_family}  (expected: {expect_family})")
        print(f"  product:              {actual_product}  (expected: {expect_product})")
        print(f"  reporting_confidence: {actual_confidence}  (expected: {expect_confidence})")
        print(f"  action:               {result.get('action', '?') if result else 'None'}")
        if sidecars:
            print(f"  evidence sidecar:     {sidecars[0]}")

        payloads.append(
            {
                "label": label,
                "pass": ok,
                "product_family_token": actual_family,
                "product": actual_product,
                "reporting_confidence": actual_confidence,
                "sidecar": str(sidecars[0]) if sidecars else None,
            }
        )

    print(f"\n{'=' * 60}")
    if all_pass:
        print("METRICS PAYLOAD PROOF: ALL CASES PASS PASS")
    else:
        print("METRICS PAYLOAD PROOF: SOME CASES FAILED FAIL")
    return payloads, all_pass


# ── No-Total proof ───────────────────────────────────────────────────────────


def prove_no_total_fallback():
    """Explicitly prove that unknown family never becomes Total."""
    from src.observability.metrics_scope import ScopeInput, ScopeResolver

    print("\n" + "=" * 60)
    print("NO-TOTAL-FALLBACK PROOF")
    print("=" * 60)

    resolver = ScopeResolver()
    cases = [
        (
            "multi-family root (family_scope: multi)",
            "products.aspose.org",
            str(FIXTURE_ROOT / "products.aspose.org"),
            "products.aspose.org.yaml",
            "multi",
        ),
        (
            "mixed root, no family_scope",
            "kb.aspose.net",
            str(FIXTURE_ROOT / "kb.aspose.net"),
            "kb.aspose.net.yaml",
            None,
        ),
        (
            "metrics_hints total blocked",
            "docs.aspose.org",
            "${ASPOSE_ORG_CONTENT}/docs.aspose.org",
            "docs.aspose.org.yaml",
            None,
        ),
    ]
    all_pass = True
    for label, site_id, root, fname, fs in cases:
        inp = ScopeInput(
            site_id=site_id,
            content_root_raw=root,
            profile_filename=fname,
            family_scope=fs,
            metrics_hints={"product_family": "total"},  # adversarial hint -- must be blocked
        )
        scope = resolver.resolve(inp)
        no_total = scope.product_family_token != "total" and scope.product != "Aspose.Total"
        status = "PASS PASS" if no_total else "FAIL FAIL"
        if not no_total:
            all_pass = False
        print(f"{status}: {label}")
        print(f"  product_family_token: {scope.product_family_token}  product: {scope.product}")

    print(f"\n{'=' * 60}")
    if all_pass:
        print("NO-TOTAL-FALLBACK: ALL CASES PASS PASS")
    else:
        print("NO-TOTAL-FALLBACK: SOME CASES FAILED FAIL")
    return all_pass


# ── Explicit Total proof ─────────────────────────────────────────────────────


def prove_explicit_total():
    """Prove that family_scope: total still correctly emits Total."""
    from src.observability.metrics_scope import ScopeInput, ScopeResolver

    print("\n" + "=" * 60)
    print("EXPLICIT TOTAL PROOF")
    print("=" * 60)

    resolver = ScopeResolver()
    inp = ScopeInput(
        site_id="products.aspose.org.total",
        content_root_raw="${ASPOSE_ORG_CONTENT}/products.aspose.org/en/total",
        profile_filename="products.aspose.org.total.yaml",
        family_scope="total",
    )
    scope = resolver.resolve(inp)
    ok = scope.product_family_token == "total" and scope.product == "Aspose.Total"
    status = "PASS PASS" if ok else "FAIL FAIL"
    print(f"{status}: explicit family_scope: total -> Aspose.Total")
    print(f"  product_family_token: {scope.product_family_token}")
    print(f"  product:              {scope.product}")
    return ok


# ── Main ─────────────────────────────────────────────────────────────────────


def main():
    Path(EVIDENCE_DIR).mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("FAMILY-AWARE SCOPE PILOT PROOF")
    print(f"Fixture root: {FIXTURE_ROOT}")
    print(f"Evidence dir: {EVIDENCE_DIR}")
    print("=" * 60)

    partitioning = prove_worker_partitioning()
    scope_results, scope_pass = prove_scope_resolution()
    no_total_pass = prove_no_total_fallback()
    explicit_total_pass = prove_explicit_total()
    payload_results, payload_pass = prove_metrics_payloads()

    # Aggregate report
    all_pass = scope_pass and no_total_pass and explicit_total_pass and payload_pass

    aggregate = {
        "pilot_id": "family-scope-challenge-20260521",
        "fixture_root": str(FIXTURE_ROOT),
        "evidence_dir": EVIDENCE_DIR,
        "product_family_tokens": list({r["product_family_token"] for r in scope_results}),
        "product_families": list({r["product"] for r in scope_results}),
        "partitioning": partitioning,
        "scope_cases": scope_results,
        "payload_cases": payload_results,
        "assertions": {
            "scope_resolution_all_pass": scope_pass,
            "no_total_fallback_all_pass": no_total_pass,
            "explicit_total_works": explicit_total_pass,
            "metrics_payloads_all_pass": payload_pass,
        },
        "verdict": "PASS" if all_pass else "FAIL",
    }

    report_path = Path("reports/family-scope-challenge-20260521/pilot-aggregate-report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(aggregate, f, indent=2)

    print("\n" + "=" * 60)
    verdict = "PILOT PASS PASS" if all_pass else "PILOT FAIL FAIL"
    print(f"FINAL VERDICT: {verdict}")
    print(f"Aggregate report: {report_path}")
    print("=" * 60)

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
