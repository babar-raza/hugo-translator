"""OP-01: run a campaign under CampaignSupervisor -- durable, restart-safe, heartbeat-emitting.

Mirrors ``run_gate5_batch.py``'s CLI shape (manifest/ledger-root/max-gpu-memory-percent/
no-force-serialize) and reuses its real-engine construction unchanged; the only new flags
are supervisor-specific (heartbeat/state paths, heartbeat interval, and an optional
adoption-check command). Unlike ``run_gate5_batch.py``, this entrypoint drives every
remaining shard to completion itself (CampaignSupervisor's own resume/reconciliation loop)
rather than running exactly one ``CampaignRunner.run()`` call -- no ``--resume``/``--shard-id``
flags are needed because a restart of this script always reconciles and continues on its own.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OP-01 supervised campaign runner")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--ledger-root", type=Path, default=Path("data/campaigns"))
    parser.add_argument(
        "--heartbeat-path",
        type=Path,
        default=None,
        help="Defaults to config/global.yaml's campaign_supervisor.heartbeat_path.",
    )
    parser.add_argument(
        "--state-path",
        type=Path,
        default=None,
        help="Defaults next to the heartbeat path if omitted.",
    )
    parser.add_argument("--heartbeat-interval", type=float, default=None)
    parser.add_argument(
        "--adoption-check-command",
        nargs="+",
        default=None,
        help="Subprocess argv for the content repo's session_ledger.py candidates check "
        "(e.g. D:/onedrive/Documents/GitHub/aspose.org/.venv/Scripts/python.exe "
        "scripts/pipeline/commands/ops/session_ledger.py candidates --session-id {shard_id} "
        "--format json). '{shard_id}' is substituted. Omit to leave adoption a no-op "
        "(safe default -- this taskcard does not require a live content repo).",
    )
    parser.add_argument(
        "--max-gpu-memory-percent",
        type=int,
        default=None,
        help="VRAM budget for this process; omit to use config/global.yaml's default.",
    )
    args = parser.parse_args(argv)

    translator_repo = Path.cwd().resolve()

    from src.utils.config_loader import get_global_config
    from src.workers.campaign_manifest import CampaignManifest
    from src.workers.campaign_runner import CampaignRunner
    from src.workers.campaign_supervisor import CampaignSupervisor

    from scripts.campaign.run_gate5_batch import build_real_engine

    manifest = CampaignManifest.load(args.manifest)
    print(
        f"[{manifest.campaign_id}] {len(manifest.sources)} sources, "
        f"{sum(len(s.outputs) for s in manifest.sources)} cells, "
        f"primary={manifest.retry_policy['primary_model']}"
    )

    raw = get_global_config() or {}
    supervisor_cfg = raw.get("campaign_supervisor", {}) or {}
    heartbeat_path = args.heartbeat_path or Path(
        supervisor_cfg.get("heartbeat_path", "data/logs/campaign_supervisor.heartbeat")
    )
    state_path = args.state_path
    if state_path is None and supervisor_cfg.get("state_path"):
        state_path = Path(supervisor_cfg["state_path"])
    heartbeat_interval = (
        args.heartbeat_interval
        if args.heartbeat_interval is not None
        else float(supervisor_cfg.get("heartbeat_interval_seconds", 30))
    )

    engine = build_real_engine(translator_repo, args.max_gpu_memory_percent)
    runner = CampaignRunner(
        manifest=manifest,
        translation_engine=engine,
        translator_repo=translator_repo,
        ledger_root=args.ledger_root,
    )
    supervisor = CampaignSupervisor(
        runner=runner,
        heartbeat_path=heartbeat_path,
        state_path=state_path,
        heartbeat_interval=heartbeat_interval,
        adoption_check=args.adoption_check_command,
    )
    result = supervisor.run()
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
