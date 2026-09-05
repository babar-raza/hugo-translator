"""One-off debug harness (loop-prompt.md SS4 item 4): translate a single
file/language in-session, outside any campaign, so the actual candidate
text and a validator's exact complaint can be inspected before deciding
whether to quarantine further attempts on the same page. Never persists
candidate text to any tracked file -- prints to stdout only.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def build_real_engine(translator_repo: Path):
    from src.model_runtime.loader import ModelLoader
    from src.model_runtime.registry import ModelRegistry
    from src.tm import TranslationMemory
    from src.tm.l1_cache import L1Cache
    from src.tm.l2_persistent import L2_DB_NAME, L2PersistentTM
    from src.translation_engine.engine import TranslationEngine
    from src.utils.config_loader import ConfigService, get_global_config

    config_service = ConfigService(translator_repo / "config")
    raw = get_global_config()
    device = "cpu"
    if (raw.get("hardware", {}) or {}).get("enable_gpu", True):
        try:
            import torch

            if torch.cuda.is_available():
                device = "cuda"
        except Exception:
            device = "cpu"
    loader = ModelLoader(
        ModelRegistry(translator_repo / "config" / "model_registry.yaml"),
        device=device,
        config=raw,
    )
    tm_data_dir = Path(raw.get("paths", {}).get("tm_data_dir", "data/tm"))
    l2_max_size_mb = raw.get("tm_defaults", {}).get("l2_max_size_mb", 1536)
    tm = TranslationMemory(
        l1_cache=L1Cache(max_size=10000),
        l2_persistent=L2PersistentTM(
            db_path=tm_data_dir / L2_DB_NAME, max_size_mb=l2_max_size_mb
        ),
        l3_semantic=None,
    )
    engine = TranslationEngine(
        config_service=config_service,
        tm=tm,
        model_loader=loader,
        enable_validation=True,
        enable_telemetry=False,
        validation_mode="strict",
        validation_policy="zero-defect",
        enable_verification=True,
        enable_verification_fix=True,
        max_retries=4,
        save_rejected=False,
    )
    return engine


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Debug harness: translate one file/lang")
    parser.add_argument("--site-id", required=True)
    parser.add_argument("--source-path", required=True, help="content-repo-relative path")
    parser.add_argument("--target-lang", required=True)
    parser.add_argument(
        "--primary-model",
        default=None,
        help="sets engine.model_id_override, matching CampaignRunner's own "
        "primary-phase behavior (e.g. professionalize_llm, m2m100_418m). "
        "Without this, the engine falls back to its own default selector, "
        "which does NOT match what a real campaign run would have tried first.",
    )
    args = parser.parse_args(argv)

    translator_repo = Path.cwd().resolve()
    engine = build_real_engine(translator_repo)
    if args.primary_model:
        engine.model_id_override = args.primary_model

    result = engine.translate_file(
        args.site_id,
        Path(args.source_path),
        target_langs=[args.target_lang],
        force=False,
        force_overwrite=False,
        validate=True,
        trigger_type="debug_harness",
    )

    print("=== TranslationResult ===")
    print("success:", result.success)
    print("errors:", result.errors)
    print("warnings:", result.warnings)
    print("validation_decision:", result.validation_decision)
    print("decision_reason:", result.decision_reason)
    print("retry_attempts:", result.retry_attempts)
    vr = result.validation_result
    if vr is not None:
        print("=== ValidationResult.issues ===")
        for issue in getattr(vr, "issues", []):
            print(f"- [{issue.severity}] {issue.validator}: {issue.message}")
            if getattr(issue, "details", None):
                print(f"    details: {issue.details}")
    else:
        print("validation_result: None")
    return 0


if __name__ == "__main__":
    sys.exit(main())
