"""TC-APT-013 (Gate 4): the mission's first real campaign run against the
real content repository.

Plan section 21, Track A step 2: "Run campaign_runner.py against exactly
that scope. It writes receipt-backed files directly into
content/<site>/<lang>/...; nothing else writes there." This script builds
the REAL production TranslationEngine (persistent TM, no sandbox override --
ASPOSE_ORG_CONTENT resolves to the real content repo from .env) and hands it
to CampaignRunner against the tiny 2-cell manifest
data/campaigns/gate4-canary/manifest.yaml.

Deliberately does NOT set model_id_override or force=True: CampaignRunner's
own per-phase logic (primary_model=m2m100_418m, escalation=professionalize_llm
per the manifest's retry_policy) owns model routing, and normal TM lookups
should apply exactly as they would in any real campaign.

Never commits anything itself -- campaign_runner.py writes receipt-backed
files only (per its own design, confirmed in this plan's section 19.2); the
governed content-repo commit is a separate, explicit step this session
performs after Claude review, following section 19.2's procedure exactly.
"""

from __future__ import annotations

import argparse
import json
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
        l3_semantic=None,  # L3 FAISS index absent on this host (verified, plan section 0)
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
    parser = argparse.ArgumentParser(description="TC-APT-013 Gate 4 canary run")
    parser.add_argument(
        "--manifest", type=Path, default=Path("data/campaigns/gate4-canary/manifest.yaml")
    )
    parser.add_argument("--ledger-root", type=Path, default=Path("data/campaigns"))
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)

    translator_repo = Path.cwd().resolve()

    from src.workers.campaign_manifest import CampaignManifest
    from src.workers.campaign_runner import CampaignRunner

    manifest = CampaignManifest.load(args.manifest)
    print(
        f"[{manifest.campaign_id}] {len(manifest.sources)} sources, "
        f"{sum(len(s.outputs) for s in manifest.sources)} cells, "
        f"primary={manifest.retry_policy['primary_model']}"
    )

    engine = build_real_engine(translator_repo)
    runner = CampaignRunner(
        manifest=manifest,
        translation_engine=engine,
        translator_repo=translator_repo,
        ledger_root=args.ledger_root,
    )
    result = runner.run(resume=args.resume)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
