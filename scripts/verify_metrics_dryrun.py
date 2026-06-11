"""TC-V2-02: Verify metrics dry-run payload shape.

Exercises MetricsRunContext directly (no full worker needed).
Simulates a completed translation run and captures the evidence sidecar.
"""

import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.observability.agent_metrics_integration import MetricsRunContext


class FakeConfigService:
    """Minimal config service returning agent_metrics with dry_run=true."""

    def __init__(self, cfg: dict):
        self._cfg = cfg

    def get_config(self) -> dict:
        return self._cfg


def main():
    cfg = {
        "agent_metrics": {
            "enabled": True,
            "dry_run": True,
            "fire_and_forget": False,
            "evidence_dir": "data/metrics/agent_evidence",
            "ledger_file": "data/metrics/agent_evidence/metrics_ledger.jsonl",
            "endpoint_env": "AGENT_METRICS_ENDPOINT",
            "token_env": "AGENT_METRICS_TOKEN",
            "post_timeout_seconds": 15,
            "excluded_site_id_prefixes": [],
            "metrics_website_mapping": {},
        }
    }
    config_service = FakeConfigService(cfg)

    ctx = MetricsRunContext(
        site_id="docs.aspose.net.words",
        content_root_raw="/tmp/p3_test_content/docs.aspose.net/words",
        config_service=config_service,
        job_type="Content Translation",
        profile_filename="docs.aspose.net.words.yaml",
        display_name="Aspose.Words for .NET Docs",
        family_scope="single",
    )

    print(f"enabled={ctx.enabled}")
    if not ctx.enabled:
        print("ERROR: MetricsRunContext not enabled. Check config.")
        return 1

    # Simulate LLM usage by recording some calls
    ctx.start()
    if ctx._llm_ctx:
        ctx._llm_ctx.record_attempted()
        ctx._llm_ctx.record_completed(input_tokens=1200, output_tokens=350)
        ctx._llm_ctx.record_attempted()
        ctx._llm_ctx.record_completed(input_tokens=800, output_tokens=250)
        print("Recorded 2 simulated LLM calls (2000 input, 600 output tokens)")
    else:
        print("WARNING: LLMRunContext not started")

    # Simulate a successful translation of 3 files
    result = ctx.finish(
        items_discovered=3,
        items_succeeded=3,
        items_failed=0,
    )

    if result is None:
        print("ERROR: finish() returned None")
        return 1

    print(f"\nResult action: {result.get('action')}")
    sidecar_path = result.get("sidecar_path")
    if sidecar_path and Path(sidecar_path).exists():
        sidecar = json.loads(Path(sidecar_path).read_text(encoding="utf-8"))
        print(f"\n{'=' * 60}")
        print("EVIDENCE SIDECAR CAPTURED")
        print(f"{'=' * 60}")
        print(f"Path: {sidecar_path}")
        print("\n--- posted_payload (17 fields) ---")
        pp = sidecar.get("posted_payload", {})
        for k, v in pp.items():
            print(f"  {k}: {v!r}")
        print(f"\n  Field count: {len(pp)}")
        print("\n--- posting status ---")
        posting = sidecar.get("posting", {})
        for k, v in posting.items():
            print(f"  {k}: {v!r}")
        print("\n--- call_accounting ---")
        ca = sidecar.get("call_accounting", {})
        for k, v in ca.items():
            print(f"  {k}: {v!r}")
        print("\n--- scope ---")
        scope = sidecar.get("scope", {})
        for k, v in scope.items():
            print(f"  {k}: {v!r}")

        # Automated verification
        print(f"\n{'=' * 60}")
        print("AUTOMATED FIELD VERIFICATION")
        print(f"{'=' * 60}")
        checks = [
            (
                "agent_name",
                pp.get("agent_name") == "Hugo Translator",
                "Hugo Translator",
                pp.get("agent_name"),
            ),
            (
                "agent_owner",
                pp.get("agent_owner") == "Babar Raza",
                "Babar Raza",
                pp.get("agent_owner"),
            ),
            (
                "job_type",
                pp.get("job_type") == "Content Translation",
                "Content Translation",
                pp.get("job_type"),
            ),
            (
                "status",
                pp.get("status") in {"success", "partial_success", "failure"},
                "success|partial_success|failure",
                pp.get("status"),
            ),
            (
                "website",
                pp.get("website") and "aspose" in pp.get("website", ""),
                "contains 'aspose'",
                pp.get("website"),
            ),
            (
                "website_section",
                bool(pp.get("website_section")),
                "non-empty",
                pp.get("website_section"),
            ),
            ("item_name", bool(pp.get("item_name")), "non-empty", pp.get("item_name")),
            ("items_discovered", pp.get("items_discovered") == 3, "3", pp.get("items_discovered")),
            ("items_succeeded", pp.get("items_succeeded") == 3, "3", pp.get("items_succeeded")),
            ("items_failed", pp.get("items_failed") == 0, "0", pp.get("items_failed")),
            (
                "run_duration_ms",
                (pp.get("run_duration_ms") or 0) >= 0,
                ">= 0",
                pp.get("run_duration_ms"),
            ),
            ("token_usage", (pp.get("token_usage") or 0) > 0, "> 0", pp.get("token_usage")),
            (
                "api_calls_count",
                (pp.get("api_calls_count") or 0) > 0,
                "> 0",
                pp.get("api_calls_count"),
            ),
            ("timestamp", bool(pp.get("timestamp")), "non-empty ISO", pp.get("timestamp")),
            ("run_id", bool(pp.get("run_id")), "non-empty UUID", pp.get("run_id")),
            ("field_count", len(pp) == 17, "17", len(pp)),
            ("posting.dry_run", posting.get("dry_run") is True, "True", posting.get("dry_run")),
            (
                "posting.status",
                posting.get("status") == "dry_run",
                "dry_run",
                posting.get("status"),
            ),
            (
                "posting.response_code",
                posting.get("response_code") is None,
                "None",
                posting.get("response_code"),
            ),
        ]
        all_pass = True
        for name, passed, expected, actual in checks:
            mark = "PASS" if passed else "FAIL"
            if not passed:
                all_pass = False
            print(f"  [{mark}] {name}: expected={expected}, actual={actual!r}")

        print(f"\n{'=' * 60}")
        if all_pass:
            print("ALL CHECKS PASSED — payload matches v1.1 schema")
        else:
            print("SOME CHECKS FAILED — review above")
        print(f"{'=' * 60}")
        return 0 if all_pass else 1
    else:
        print(f"No sidecar found at: {sidecar_path}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
