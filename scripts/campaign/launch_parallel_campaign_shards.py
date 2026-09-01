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

from src.utils.file_lock import FileLock, LockError
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


def incomplete_shards(
    manifest: CampaignManifest,
    ledger_root: Path,
    shard_ids: list[str],
) -> list[str]:
    """Return launched shards that lack one or more final acceptance receipts."""
    receipt_paths = set(CampaignLedger(ledger_root, manifest.campaign_id).receipts())
    expected_by_id = {
        str(shard["shard_id"]): {output for _source, _locale, output in shard["jobs"]}
        for shard in manifest.shards(
            resume_receipts=set(),
            max_outputs=int(manifest.commit_policy.get("max_outputs_per_commit", 250)),
        )
    }
    return [
        shard_id
        for shard_id in shard_ids
        if not expected_by_id.get(shard_id, set()).issubset(receipt_paths)
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-manifest", required=True, type=Path)
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--max-gpu-memory-percent", type=int, default=90)
    parser.add_argument("--ledger-root", type=Path, default=Path("data/campaigns"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--wait",
        action="store_true",
        help="Wait for every isolated child and return nonzero if any shard fails",
    )
    args = parser.parse_args(argv)
    if not 1 <= args.max_workers <= 4:
        raise SystemExit("--max-workers must be 1..4")
    if not args.wait:
        raise SystemExit("--wait is required for governed campaign launches")

    manifest = CampaignManifest.load(args.campaign_manifest)
    translator_repo = Path(__file__).resolve().parents[2]
    config_root = translator_repo / "config"
    lock_path = args.ledger_root / manifest.campaign_id / "parallel-launcher.lock"
    try:
        launcher_lock = FileLock(lock_path, timeout=1)
        launcher_lock.acquire()
    except LockError:
        print("A governed campaign launcher is already active", file=sys.stderr)
        return 1
    try:
        shard_ids = select_pending_shards(manifest, args.ledger_root, args.max_workers)
        if not shard_ids:
            print("No pending campaign shards")
            return 0
        children: list[subprocess.Popen] = []
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
            "--config-root",
            str(config_root),
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
            children.append(subprocess.Popen(command, cwd=translator_repo, creationflags=flags))
        exit_codes = [child.wait() for child in children]
        if any(code != 0 for code in exit_codes):
            return 1
        # Child process status is necessary but insufficient: a legacy worker
        # could exit cleanly after a fail-closed preflight abort.  A supervised
        # batch is successful only when every exact shard output has a receipt.
        incomplete = incomplete_shards(manifest, args.ledger_root, shard_ids)
        if incomplete:
            print(f"Incomplete campaign shards: {', '.join(incomplete)}", file=sys.stderr)
            return 1
        return 0
    finally:
        launcher_lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
