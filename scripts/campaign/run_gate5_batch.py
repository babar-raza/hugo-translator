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


def build_real_engine(
    translator_repo: Path,
    max_gpu_memory_percent: int | None = None,
    tm_intent_spool_path: Path | None = None,
):
    from src.model_runtime.loader import ModelLoader
    from src.model_runtime.registry import ModelRegistry
    from src.tm import TranslationMemory
    from src.tm.intent_spool import TMIntentSpool
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
    # TC-APT-047/065: a dedicated GPU shard process needs its own VRAM budget.
    # Resolved percent -> MB exactly the way the legacy worker does it
    # (autonomous_content_translation_worker.py:410-420) so both entry points
    # enforce the same budget.  None keeps config/global.yaml's own default.
    max_memory_mb = None
    if max_gpu_memory_percent is not None and device.startswith("cuda"):
        from src.hardware.vram_enforcer import VRAMEnforcer

        max_memory_mb, budget = VRAMEnforcer().enforce_from_config(
            {"enable_gpu": True, "max_gpu_memory_percent": max_gpu_memory_percent},
            device=device,
        )
        if budget:
            print(f"VRAM budget enforced: {max_memory_mb}MB ({budget.percent:.1f}% of total)")
    loader = ModelLoader(
        ModelRegistry(translator_repo / "config" / "model_registry.yaml"),
        device=device,
        max_memory_mb=max_memory_mb,
        config=raw,
    )
    tm_data_dir = Path(raw.get("paths", {}).get("tm_data_dir", "data/tm"))
    l2_max_size_mb = raw.get("tm_defaults", {}).get("l2_max_size_mb", 1536)
    # Parallel campaign children must never write canonical LMDB directly.
    # A campaign-scoped durable spool leaves read lookup behaviour unchanged,
    # while exactly one separately supervised writer owns L2 mutation.
    intent_spool = TMIntentSpool(tm_intent_spool_path) if tm_intent_spool_path else None
    tm = TranslationMemory(
        l1_cache=L1Cache(max_size=10000),
        l2_persistent=L2PersistentTM(
            db_path=tm_data_dir / L2_DB_NAME, max_size_mb=l2_max_size_mb
        ),
        l3_semantic=None,  # L3 FAISS index absent on this host (verified, plan section 0)
        intent_spool=intent_spool,
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
    parser.add_argument(
        "--shard-id",
        action="append",
        default=None,
        help="run only this shard (repeatable) -- isolates one cell's failure from "
        "others in the same manifest; see data/summaries/fp-gate4-canary-TC-APT-013.json",
    )
    parser.add_argument(
        "--shard-list",
        type=Path,
        help="File containing one shard id per line; avoids Windows command-line limits for large waves.",
    )
    parser.add_argument(
        "--max-gpu-memory-percent",
        type=int,
        default=None,
        help="VRAM budget for this process (TC-APT-047 dedicated GPU shard); "
        "omit to use config/global.yaml's hardware.max_gpu_memory_percent",
    )
    parser.add_argument(
        "--no-force-serialize",
        action="store_true",
        help="TC-APT-046 step 2 canary only: turn off the force_serialize_all_backends "
        "rollback for THIS process, without flipping the shipped config for every other "
        "session sharing this working tree",
    )
    parser.add_argument(
        "--tm-intent-spool-path",
        type=Path,
        default=None,
        help=(
            "Campaign-scoped SQLite intent spool. When supplied, this process only enqueues "
            "TM writes; a separately supervised single writer applies them to canonical LMDB."
        ),
    )
    parser.add_argument(
        "--diagnostic-quarantine-root", type=Path,
        help="Protected local recovery evidence root; candidate text never enters ledgers.",
    )
    parser.add_argument(
        "--diagnostic-no-write", action="store_true",
        help="Exercise translation/gates but refuse content, receipt, and TM writes.",
    )
    parser.add_argument(
        "--max-parallel-jobs", type=int,
        help="Narrow process-local cap; recovery diagnosis must use one worker.",
    )
    args = parser.parse_args(argv)

    translator_repo = Path.cwd().resolve()

    from src.workers.campaign_manifest import CampaignManifest, CampaignManifestError
    from src.workers.campaign_runner import CampaignRunner

    manifest = CampaignManifest.load(args.manifest)
    print(
        f"[{manifest.campaign_id}] {len(manifest.sources)} sources, "
        f"{sum(len(s.outputs) for s in manifest.sources)} cells, "
        f"primary={manifest.retry_policy['primary_model']}"
    )

    engine = build_real_engine(
        translator_repo,
        args.max_gpu_memory_percent,
        args.tm_intent_spool_path,
    )
    if args.diagnostic_no_write and not args.diagnostic_quarantine_root:
        parser.error("--diagnostic-no-write requires --diagnostic-quarantine-root")
    if args.diagnostic_quarantine_root:
        root = args.diagnostic_quarantine_root.resolve()
        if ".local/rating-cause-analysis-runs" not in root.as_posix():
            parser.error("diagnostic quarantine must be below .local/rating-cause-analysis-runs")
        engine.diagnostic_quarantine_root = root
        engine.diagnostic_no_write = args.diagnostic_no_write
    if args.tm_intent_spool_path:
        print(f"[{manifest.campaign_id}] TM writes spool to {args.tm_intent_spool_path}")
    runner = CampaignRunner(
        manifest=manifest,
        translation_engine=engine,
        translator_repo=translator_repo,
        ledger_root=args.ledger_root,
    )
    if args.max_parallel_jobs is not None:
        if args.max_parallel_jobs < 1:
            parser.error("--max-parallel-jobs must be positive")
        if not args.diagnostic_no_write:
            parser.error("--max-parallel-jobs is reserved for diagnostic no-write runs")
        runner.manifest.execution_policy["max_parallel_jobs"] = args.max_parallel_jobs
    if args.no_force_serialize:
        # Process-scoped, so a canary never changes what any concurrently running
        # session sees. The shipped default stays the safe one (TC-APT-046 step 1).
        runner._force_serialize = False
        print(
            f"[{manifest.campaign_id}] force_serialize_all_backends OFF for this process; "
            f"max_parallel_jobs={manifest.execution_policy.get('max_parallel_jobs', 1)}"
        )
    listed_shards: list[str] = []
    if args.shard_list:
        listed_shards = [
            line.strip()
            for line in args.shard_list.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if not listed_shards:
            parser.error("--shard-list contains no shard ids")
    shard_ids = set((args.shard_id or []) + listed_shards) or None
    try:
        result = runner.run(resume=args.resume, shard_ids=shard_ids)
    except CampaignManifestError as exc:
        # TC-APT-041: a partial-failure run still commits every shard's
        # receipted outputs (see CampaignRunner._run_locked); print the
        # attached summary instead of losing it to a bare traceback.
        summary = getattr(exc, "summary", None)
        if summary is not None:
            print(json.dumps(summary, indent=2, default=str))
        else:
            print(json.dumps({"error": str(exc)}, indent=2, default=str))
        return 1
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
