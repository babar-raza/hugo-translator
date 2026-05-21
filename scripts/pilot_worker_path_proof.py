"""
Real worker-path pilot for family-aware scope verification.

Sprint: family-scope-closure-20260521
Challenge requirement: prove the REAL chain fires:
  _process_site -> _expand_family_content_roots -> _translate_content_root
  -> MetricsRunContext(family_scope, profile_filename, display_name)
  -> ScopeResolver -> dry-run sidecar

This script does NOT call discover_family_subdirs() or MetricsRunContext() directly.
It calls _process_site() on a real AutonomousContentTranslationWorker instance with:
  - MockConfigService  (returns SiteProfile with family_scope: multi)
  - MockTranslationEngine  (zero-result, no translation performed)
  - SpyMetricsRunContext  (wraps real MetricsRunContext, records all __init__ kwargs)
  - agent_metrics.dry_run: true (no HTTP POST)

Usage:
    PYTHONPATH="C:/Users/prora/AppData/Roaming/Python/Python313/site-packages" ^
    python scripts/pilot_worker_path_proof.py

Exit code: 0 = PASS, 1 = FAIL
"""
from __future__ import annotations

import json
import os
import sys
import time
import unittest.mock as mock
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------
FIXTURE_ROOT = Path("C:/Users/prora/AppData/Local/Temp/pilot_fixture")
EVIDENCE_DIR = "C:/Users/prora/AppData/Local/Temp/pilot_evidence/worker_path"
SIDECAR_OUT = Path("reports/family-scope-closure-20260521/pilot-sidecars/worker-path")

SITE_ID = "products.aspose.org"
CONTENT_ROOT = str(FIXTURE_ROOT / "products.aspose.org")


# ---------------------------------------------------------------------------
# Fixtures: ensure pilot_fixture tree exists
# ---------------------------------------------------------------------------

def ensure_fixture_tree():
    """Create fixture directory structure if not present."""
    families = ["font", "cells", "words"]
    root = FIXTURE_ROOT / "products.aspose.org" / "en"
    for fam in families:
        fam_dir = root / fam
        fam_dir.mkdir(parents=True, exist_ok=True)
        # Create a minimal .md file so the dir is non-empty (translate_directory would find it)
        md_file = fam_dir / "_index.md"
        if not md_file.exists():
            md_file.write_text(
                "---\ntitle: Test\n---\nPlaceholder.\n",
                encoding="utf-8",
            )
    print(f"Fixture tree ready: {FIXTURE_ROOT / 'products.aspose.org'}")
    for fam in families:
        fam_dir = root / fam
        print(f"  {fam_dir}")


# ---------------------------------------------------------------------------
# MockConfigService
# ---------------------------------------------------------------------------

class MockConfigService:
    """Minimal config service that returns a multi-family profile."""

    def get_site_profile(self, site_id: str):
        from src.utils.models import BodyRules, SiteProfile
        if site_id != SITE_ID:
            raise ValueError(f"Unknown site: {site_id}")
        return SiteProfile(
            site_id=SITE_ID,
            display_name="Product Pages",
            content_roots=[CONTENT_ROOT],
            default_source_lang="en",
            target_langs=["de"],
            body=BodyRules(translate_markdown=True),
            family_scope="multi",
        )

    def resolve_content_root(self, content_root: str) -> Path:
        return Path(content_root)

    def get_config(self) -> dict:
        return {
            "agent_metrics": {
                "enabled": True,
                "dry_run": True,
                "evidence_dir": EVIDENCE_DIR,
            },
            "git_commit": {
                "files_per_commit": 0,  # single-pass mode
            },
            "metrics": {
                "enabled": True,
                "write_per_run_summary": False,  # skip DB writes
            },
            # Disable contamination scan (would try to run scan script)
            "auto_scan_contamination": False,
            "autonomous_content_translation": {
                "execution": {
                    "per_site_limits": {},
                }
            },
        }

    def list_sites(self):
        return [SITE_ID]


# ---------------------------------------------------------------------------
# MockTranslationResult
# ---------------------------------------------------------------------------

class MockTranslationResult:
    """Zero-translation result — no files created or modified."""
    successful_files = 0
    total_files = 0
    failed_files = 0
    file_results = []
    aggregate_stats = None
    completion_filter_skipped = 0


class MockTranslationEngine:
    """Returns zero-result for every translate_directory call."""

    def translate_directory(self, **kwargs):
        return MockTranslationResult()


# ---------------------------------------------------------------------------
# MetricsRunContext spy
# ---------------------------------------------------------------------------

# Captures all MetricsRunContext.__init__ kwargs across all instances created
_metrics_ctx_calls: list[dict] = []
_real_MetricsRunContext = None  # set once we import it


def _make_spy_class():
    """Create a SpyMetricsRunContext class wrapping the real one."""
    from src.observability.agent_metrics_integration import MetricsRunContext as _Real
    global _real_MetricsRunContext
    _real_MetricsRunContext = _Real

    class SpyMetricsRunContext(_Real):
        def __init__(self, **kwargs):
            _metrics_ctx_calls.append(dict(kwargs))
            super().__init__(**kwargs)

    return SpyMetricsRunContext


# ---------------------------------------------------------------------------
# Pilot assertions
# ---------------------------------------------------------------------------

def check_sidecar(evidence_base: Path, expected_family: str, expected_product: str,
                  expected_confidence: str, label: str) -> tuple[bool, dict | None]:
    """Find most recent sidecar and verify scope fields."""
    sidecars = sorted(
        evidence_base.rglob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not sidecars:
        print(f"  FAIL {label}: no sidecar found in {evidence_base}")
        return False, None

    with open(sidecars[0], encoding="utf-8") as f:
        ev = json.load(f)
    scope = ev.get("scope", {})

    actual_family = scope.get("product_family_token", "?")
    actual_product = scope.get("product", "?")
    actual_confidence = scope.get("reporting_confidence", "?")
    dry_run = ev.get("posting", {}).get("dry_run", "?")
    response_code = ev.get("posting", {}).get("response_code", "?")

    ok = (
        actual_family == expected_family
        and actual_product == expected_product
        and actual_confidence == expected_confidence
        and dry_run is True
        and response_code is None
    )
    status = "PASS" if ok else "FAIL"
    print(f"  {status} {label}")
    print(f"    product_family_token: {actual_family!r}  (expected: {expected_family!r})")
    print(f"    product:              {actual_product!r}  (expected: {expected_product!r})")
    print(f"    reporting_confidence: {actual_confidence!r}  (expected: {expected_confidence!r})")
    print(f"    dry_run:              {dry_run!r}  (expected: True)")
    print(f"    response_code:        {response_code!r}  (expected: None)")
    print(f"    sidecar path:         {sidecars[0]}")

    return ok, ev


# ---------------------------------------------------------------------------
# Main pilot
# ---------------------------------------------------------------------------

def main() -> int:
    print("=" * 70)
    print("REAL WORKER-PATH PILOT -- family-scope-closure-20260521")
    print(f"Fixture root:  {FIXTURE_ROOT}")
    print(f"Evidence dir:  {EVIDENCE_DIR}")
    print(f"Site:          {SITE_ID}")
    print("=" * 70)

    # 1. Ensure fixture tree
    ensure_fixture_tree()

    # 2. Clear evidence dir so sidecars from this run are unambiguous
    evidence_path = Path(EVIDENCE_DIR)
    if evidence_path.exists():
        import shutil
        shutil.rmtree(evidence_path)
    evidence_path.mkdir(parents=True, exist_ok=True)

    SIDECAR_OUT.mkdir(parents=True, exist_ok=True)

    # 3. Import worker classes
    from src.workers.autonomous_content_translation_worker import (
        AutonomousContentTranslationWorker,
        AutonomousWorkerConfig,
    )

    # 4. Build worker WITHOUT calling setup() — inject mocks directly
    worker_config = AutonomousWorkerConfig(
        site=SITE_ID,
        mode="oneshot",
        file_timeout_seconds=300,
    )
    worker = AutonomousContentTranslationWorker(worker_config)
    worker.config_service = MockConfigService()
    worker.translation_engine = MockTranslationEngine()
    worker._run_start = time.time()

    # 5. Patch MetricsRunContext with spy
    SpyMetrics = _make_spy_class()

    print("\n-- Calling _process_site (real worker path) --")
    # MetricsRunContext is imported lazily inside _translate_content_root via:
    #   from src.observability.agent_metrics_integration import MetricsRunContext
    # Patching the class on the source module redirects that local import to SpyMetrics.
    with mock.patch(
        "src.observability.agent_metrics_integration.MetricsRunContext",
        new=SpyMetrics,
    ):
        worker._process_site(SITE_ID)

    print(f"\n-- MetricsRunContext spy captured {len(_metrics_ctx_calls)} constructor call(s) --")
    for i, call_kwargs in enumerate(_metrics_ctx_calls):
        print(f"\n  Call #{i+1}:")
        for k, v in call_kwargs.items():
            print(f"    {k}: {v!r}")

    # 6. Verify spy captured correct forwarding from _process_site -> _translate_content_root
    print("\n" + "=" * 70)
    print("ASSERTION: MetricsRunContext constructor received family_scope + profile_filename")
    print("=" * 70)

    all_pass = True

    # We expect 3 calls (font, cells, words) because _expand_family_content_roots partitions
    expected_families = {"font", "cells", "words"}
    if len(_metrics_ctx_calls) == 0:
        print("FAIL: No MetricsRunContext calls captured — _process_site chain did not fire")
        all_pass = False
    else:
        # Check that every call forwarded profile_filename and family_scope
        for i, call_kwargs in enumerate(_metrics_ctx_calls):
            profile_filename = call_kwargs.get("profile_filename", "")
            family_scope = call_kwargs.get("family_scope", None)
            display_name = call_kwargs.get("display_name", None)

            pf_ok = profile_filename == f"{SITE_ID}.yaml"
            fs_ok = family_scope == "multi"
            dn_ok = display_name == "Product Pages"

            status = "PASS" if (pf_ok and fs_ok and dn_ok) else "FAIL"
            print(f"  {status} Call #{i+1} forwarding check:")
            print(f"    profile_filename: {profile_filename!r}  (expected: {SITE_ID+'.yaml'!r}) {'OK' if pf_ok else 'WRONG'}")
            print(f"    family_scope:     {family_scope!r}  (expected: 'multi') {'OK' if fs_ok else 'WRONG'}")
            print(f"    display_name:     {display_name!r}  (expected: 'Product Pages') {'OK' if dn_ok else 'WRONG'}")

            if not (pf_ok and fs_ok and dn_ok):
                all_pass = False

    # 7. Verify sidecar count = 3 (one per family, because _expand_family_content_roots fired)
    print("\n" + "=" * 70)
    print("ASSERTION: 3 MetricsRunContext calls fired (one per family batch)")
    print("=" * 70)
    n_calls = len(_metrics_ctx_calls)
    if n_calls == 3:
        print(f"PASS: {n_calls} calls = 3 family batches (font, cells, words)")
    elif n_calls == 1:
        print(f"FAIL: {n_calls} call — partitioning did NOT fire (expected 3)")
        all_pass = False
    else:
        # Could be more if fixture has additional families — check what was captured
        captured_roots = [c.get("content_root_raw", "") for c in _metrics_ctx_calls]
        print(f"INFO: {n_calls} calls captured with roots: {captured_roots}")
        # Still verify >= 2 (multi-family expansion fired)
        if n_calls >= 2:
            print("PASS: >= 2 calls = multi-family expansion fired")
        else:
            print("FAIL: < 2 calls = expansion may not have fired")
            all_pass = False

    # 8. Verify per-family sidecars
    print("\n" + "=" * 70)
    print("ASSERTION: Per-family sidecars have correct scope data")
    print("=" * 70)

    sidecars_all = sorted(
        evidence_path.rglob("*.json"),
        key=lambda p: p.stat().st_mtime,
    )

    print(f"Total sidecars generated: {len(sidecars_all)}")
    for s in sidecars_all:
        print(f"  {s}")

    # Gather scope data from sidecars and check family coverage
    sidecar_families: set[str] = set()
    sidecar_products: set[str] = set()
    all_dry_run = True
    sidecar_data: list[dict] = []

    for s in sidecars_all:
        with open(s, encoding="utf-8") as f:
            ev = json.load(f)
        scope = ev.get("scope", {})
        posting = ev.get("posting", {})
        fam = scope.get("product_family_token", "?")
        prod = scope.get("product", "?")
        sidecar_families.add(fam)
        sidecar_products.add(prod)
        if posting.get("dry_run") is not True:
            all_dry_run = False
        if posting.get("response_code") is not None:
            print(f"  FAIL: HTTP POST was made for {s.name} (response_code={posting.get('response_code')})")
            all_pass = False
        sidecar_data.append({
            "file": s.name,
            "product_family_token": fam,
            "product": prod,
            "reporting_confidence": scope.get("reporting_confidence"),
            "dry_run": posting.get("dry_run"),
            "response_code": posting.get("response_code"),
        })

    expected_family_tokens = {"font", "cells", "words"}
    expected_products = {"Aspose.Font", "Aspose.Cells", "Aspose.Words"}

    families_ok = expected_family_tokens.issubset(sidecar_families)
    products_ok = expected_products.issubset(sidecar_products)

    print(f"\n  Expected family tokens:  {expected_family_tokens}")
    print(f"  Actual family tokens:    {sidecar_families}")
    print(f"  {'PASS' if families_ok else 'FAIL'}: family token coverage")
    if not families_ok:
        all_pass = False

    print(f"\n  Expected products:       {expected_products}")
    print(f"  Actual products:         {sidecar_products}")
    print(f"  {'PASS' if products_ok else 'FAIL'}: product coverage")
    if not products_ok:
        all_pass = False

    print(f"\n  All sidecars dry_run=True: {'PASS' if all_dry_run else 'FAIL'}")
    if not all_dry_run:
        all_pass = False

    # 9. Copy sidecars to evidence bundle
    import shutil
    for s in sidecars_all:
        dest = SIDECAR_OUT / s.name
        shutil.copy2(s, dest)
        print(f"  Bundled sidecar: {dest}")

    # 10. Write aggregate report
    report = {
        "pilot_id": "worker-path-proof-20260521",
        "fixture_root": str(FIXTURE_ROOT),
        "evidence_dir": EVIDENCE_DIR,
        "site_id": SITE_ID,
        "metrics_ctx_calls": len(_metrics_ctx_calls),
        "metrics_ctx_kwargs": [
            {k: repr(v) if not isinstance(v, (str, int, float, bool, type(None))) else v
             for k, v in call.items()}
            for call in _metrics_ctx_calls
        ],
        "sidecars_generated": len(sidecars_all),
        "sidecar_data": sidecar_data,
        "assertions": {
            "calls_forwarded_family_scope": all(
                c.get("family_scope") == "multi" for c in _metrics_ctx_calls
            ) if _metrics_ctx_calls else False,
            "calls_forwarded_profile_filename": all(
                c.get("profile_filename") == f"{SITE_ID}.yaml"
                for c in _metrics_ctx_calls
            ) if _metrics_ctx_calls else False,
            "calls_forwarded_display_name": all(
                c.get("display_name") == "Product Pages" for c in _metrics_ctx_calls
            ) if _metrics_ctx_calls else False,
            "multi_family_expansion_fired": len(_metrics_ctx_calls) >= 2,
            "three_family_batches": len(_metrics_ctx_calls) == 3,
            "all_families_covered": families_ok,
            "all_products_covered": products_ok,
            "all_sidecars_dry_run": all_dry_run,
            "no_http_post": all(
                s.get("response_code") is None for s in sidecar_data
            ),
        },
        "verdict": "PASS" if all_pass else "FAIL",
    }

    report_path = SIDECAR_OUT / "worker-path-aggregate-report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"\nAggregate report: {report_path}")

    print("\n" + "=" * 70)
    verdict = "PILOT PASS" if all_pass else "PILOT FAIL"
    print(f"FINAL VERDICT: {verdict}")
    print("=" * 70)

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
