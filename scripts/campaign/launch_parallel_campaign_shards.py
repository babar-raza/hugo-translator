"""Launch a bounded set of isolated zero-defect campaign shard workers.

Each child owns its model runtime and an exact manifest shard.  CampaignRunner
uses shard locks plus an inter-process ledger lock, so workers can never write
the same output or corrupt receipt/failure metadata.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from src.workers.campaign_manifest import CampaignManifest
from src.workers.campaign_runner import CampaignLedger


def select_pending_shards(
    manifest: CampaignManifest, ledger_root: Path, max_workers: int
) -> list[str]:
    """Return the next deterministic, receipt-incomplete shard IDs."""
    ledger = CampaignLedger(ledger_root, manifest.campaign_id)
    receipts = set(ledger.receipts())
    return [
        str(shard["shard_id"])
        for shard in manifest.shards(
            resume_receipts=receipts,
            max_outputs=int(manifest.commit_policy.get("max_outputs_per_commit", 250)),
        )
    ][:max_workers]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-manifest", required=True, type=Path)
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--max-gpu-memory-percent", type=int, default=90)
    parser.add_argument("--ledger-root", type=Path, default=Path("data/campaigns"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not 1 <= args.max_workers <= 4:
        raise SystemExit("--max-workers must be 1..4")

    manifest = CampaignManifest.load(args.campaign_manifest)
    shard_ids = select_pending_shards(manifest, args.ledger_root, args.max_workers)
    if not shard_ids:
        print("No pending campaign shards")
        return 0
    for shard_id in shard_ids:
        print(shard_id)
    if args.dry_run:
        return 0

    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NO_WINDOW
    for shard_id in shard_ids:
        command = [
            sys.executable,
            "-m",
            "src.workers.autonomous_content_translation_worker",
            "--mode",
            "oneshot",
            "--campaign-manifest",
            str(args.campaign_manifest),
            "--campaign-shard",
            shard_id,
            "--resume",
            "--validation-policy",
            "zero-defect",
            "--device",
            args.device,
            "--max-gpu-memory-percent",
            str(args.max_gpu_memory_percent),
            "--log-level",
            "INFO",
        ]
        subprocess.Popen(command, cwd=Path.cwd(), creationflags=flags)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
