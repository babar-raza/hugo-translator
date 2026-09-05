"""Launch a bounded set of isolated zero-defect campaign shard workers.

Each child owns its model runtime and an exact manifest shard.  CampaignRunner
uses shard locks plus an inter-process ledger lock, so workers can never write
the same output or corrupt receipt/failure metadata.

TC-APT-047 (plan revision 13, §0.3 / G-32) makes this launcher the process-level
complement to the in-process concurrency work: because ``CampaignManifest.shards()``
already partitions strictly per locale, the GPU-bound locales (``hu``/``ja``/``ro``,
the three the plan's §6.1 model policy keeps on ``m2m100_418m``) are separable from
the API-bound ones by construction.  At most ONE GPU-bound shard is ever launched
per wave, so two children never contend for the same VRAM, independent of whether
TC-APT-043-046's in-process fix fully succeeds.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from src.utils.file_lock import FileLock, LockError
from src.workers.campaign_manifest import CampaignManifest
from src.workers.campaign_runner import CampaignLedger

# Plan §6.1: the locales TC-APT-006 measured `m2m100_418m` better in.  These run
# on the local GPU; every other locale is API-bound (`professionalize_llm`).
GPU_PRIMARY_LOCALES = ("hu", "ja", "ro")

# CampaignRunner.__init__'s own default; the legacy worker child cannot be told
# anything else, so a non-default root is only valid for the gate5 child.
DEFAULT_LEDGER_ROOT = Path("data/campaigns")


def pending_shards(manifest: CampaignManifest, ledger_root: Path) -> list[dict[str, Any]]:
    """Return every deterministic, receipt-incomplete shard of the manifest."""
    ledger = CampaignLedger(ledger_root, manifest.campaign_id)
    receipts = set(ledger.receipts())
    return list(
        manifest.shards(
            resume_receipts=receipts,
            max_outputs=int(manifest.commit_policy.get("max_outputs_per_commit", 250)),
        )
    )


def partition_by_device(
    shards: list[dict[str, Any]], gpu_locales: tuple[str, ...]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split shards into (gpu_bound, api_bound) by their single locale."""
    gpu_bound = [shard for shard in shards if str(shard["locale"]) in gpu_locales]
    api_bound = [shard for shard in shards if str(shard["locale"]) not in gpu_locales]
    return gpu_bound, api_bound


def select_pending_shards(
    manifest: CampaignManifest,
    ledger_root: Path,
    max_workers: int,
    gpu_locales: tuple[str, ...] = GPU_PRIMARY_LOCALES,
) -> list[dict[str, Any]]:
    """Return the next wave of shards: at most one GPU-bound shard, rest API-bound.

    Selection stays deterministic (``manifest.shards()`` yields sorted keys); the
    only reordering is that the single admissible GPU-bound shard leads the wave,
    which is what keeps GPU shards from ever overlapping each other.
    """
    gpu_bound, api_bound = partition_by_device(pending_shards(manifest, ledger_root), gpu_locales)
    return (gpu_bound[:1] + api_bound)[:max_workers]


def assign_shard_groups(
    shards: list[dict[str, Any]],
    max_workers: int,
    gpu_locales: tuple[str, ...] = GPU_PRIMARY_LOCALES,
) -> list[list[dict[str, Any]]]:
    """Split every pending shard across ``max_workers`` child processes, once.

    One shard per child would be correct but slow: each child pays the model/TM
    import before its first cell (measured at 1-3 minutes on this host), so a
    wave-per-shard launcher pays that cost 25 times for a 25-locale page and ends
    up slower than running sequentially in one process. Handing each child a whole
    group of shards up front pays startup ``max_workers`` times in total.

    Every GPU-bound shard goes to the same group, which is what keeps two GPU
    shards from ever running at once: same process means sequential by construction.
    API-bound shards are dealt round-robin starting after that group, so the group
    carrying the slower GPU work is not also given the largest API share.
    """
    if max_workers < 1:
        raise ValueError("max_workers must be >= 1")
    gpu_bound, api_bound = partition_by_device(shards, gpu_locales)
    groups: list[list[dict[str, Any]]] = [[] for _ in range(max_workers)]
    groups[0].extend(gpu_bound)
    start = 1 if (gpu_bound and max_workers > 1) else 0
    for offset, shard in enumerate(api_bound):
        groups[(start + offset) % max_workers].append(shard)
    return [group for group in groups if group]


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


def duplicate_receipts(ledger_root: Path, campaign_id: str) -> dict[str, int]:
    """Return output paths that appear more than once in the acceptance ledger.

    TC-APT-047's acceptance proof.  ``CampaignLedger.append_receipt`` dedups under
    an inter-process ``FileLock``, so a non-empty result here means the cross-process
    guarantee actually broke — read the raw rows rather than the deduped index.
    """
    receipts_path = ledger_root / campaign_id / "acceptance_receipts.jsonl"
    if not receipts_path.is_file():
        return {}
    counts: dict[str, int] = {}
    for line in receipts_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        output = str(json.loads(line).get("output_path") or "")
        if output:
            counts[output] = counts.get(output, 0) + 1
    return {output: count for output, count in counts.items() if count > 1}


def _child_command(
    *,
    shards: list[dict[str, Any]],
    config_root: Path,
    campaign_manifest: Path,
    ledger_root: Path,
    device: str,
    max_gpu_memory_percent: int,
    gpu_shard_memory_percent: int,
    gpu_locales: tuple[str, ...],
    child: str = "gate5",
) -> list[str]:
    """Build one child's argv for a whole GROUP of shards, VRAM-budgeted if it holds GPU work.

    The default ``gate5`` child is ``run_gate5_batch.py``, the same entry point every
    committed cell of this mission has come through.  It matters that both children
    are not merely "a campaign runner": the legacy worker builds its own
    ``TranslationEngine`` and never receives ``--ledger-root`` (it has no such flag),
    so a non-default ledger root would leave the parent verifying receipts in a
    directory its children never wrote to.  ``gate5`` takes the flag and shares one
    engine construction path, so process sharding changes only *where* a job runs.
    """
    if not shards:
        raise ValueError("a shard child needs at least one shard")
    holds_gpu_work = any(str(shard["locale"]) in gpu_locales for shard in shards)
    memory_percent = gpu_shard_memory_percent if holds_gpu_work else max_gpu_memory_percent
    shard_ids = [str(shard["shard_id"]) for shard in shards]
    if child == "gate5":
        command = [
            sys.executable,
            "scripts/campaign/run_gate5_batch.py",
            "--manifest",
            str(campaign_manifest),
            "--ledger-root",
            str(ledger_root),
            "--resume",
            "--max-gpu-memory-percent",
            str(memory_percent),
        ]
        for shard_id in shard_ids:
            command += ["--shard-id", shard_id]
        return command
    if len(shard_ids) > 1:
        # The legacy worker takes a single --campaign-shard, so it cannot amortise
        # startup across a group. Fail closed rather than silently drop shards.
        raise ValueError("--child worker accepts one shard per process; use --child gate5")
    return [
        sys.executable,
        "-m",
        "src.workers.autonomous_content_translation_worker",
        "--config-root",
        str(config_root),
        "--mode",
        "oneshot",
        "--campaign-manifest",
        str(campaign_manifest),
        "--campaign-shard",
        shard_ids[0],
        "--resume",
        "--validation-policy",
        "zero-defect",
        "--device",
        device,
        "--max-gpu-memory-percent",
        str(memory_percent),
        "--log-level",
        "INFO",
    ]


def _run_wave(
    *,
    groups: list[list[dict[str, Any]]],
    manifest: CampaignManifest,
    args: argparse.Namespace,
    gpu_locales: tuple[str, ...],
    translator_repo: Path,
    config_root: Path,
) -> int:
    """Launch one child per shard group and wait for all of them.

    Each child's stdout/stderr goes to its own log, and a failing child's tail is
    printed here. Without that, a failed wave reported only "Incomplete campaign
    shards" and the real cause had to be reproduced by hand -- three separate launch
    failures on 2026-09-05 (an LMDB map-size mismatch, then a dirty unreceipted
    output) were each diagnosed that way, at one wake apiece.
    """
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    children: list[subprocess.Popen] = []
    child_logs: list[Path] = []
    handles: list[Any] = []
    for index, group in enumerate(groups):
        command = _child_command(
            shards=group,
            config_root=config_root,
            campaign_manifest=args.campaign_manifest,
            ledger_root=args.ledger_root,
            device=args.device,
            max_gpu_memory_percent=args.max_gpu_memory_percent,
            gpu_shard_memory_percent=args.gpu_shard_memory_percent,
            gpu_locales=gpu_locales,
            child=args.child,
        )
        log_path = log_dir / f"{manifest.campaign_id}_child{index}.log"
        handle = log_path.open("w", encoding="utf-8")
        handles.append(handle)
        child_logs.append(log_path)
        children.append(
            subprocess.Popen(
                command,
                cwd=translator_repo,
                creationflags=flags,
                stdout=handle,
                stderr=subprocess.STDOUT,
            )
        )
    try:
        exit_codes = [child.wait() for child in children]
    finally:
        for handle in handles:
            handle.close()

    for index, (code, log_path) in enumerate(zip(exit_codes, child_logs)):
        if code == 0:
            continue
        print(f"child {index} exited {code}; tail of {log_path}:", file=sys.stderr)
        try:
            tail = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-15:]
        except OSError as exc:  # pragma: no cover - unreadable log is itself the report
            tail = [f"(could not read child log: {exc})"]
        for line in tail:
            print(f"  | {line}", file=sys.stderr)

    launched = [str(shard["shard_id"]) for group in groups for shard in group]
    # Child process status is necessary but insufficient: a child can exit
    # cleanly after a fail-closed preflight abort, and a zero-defect campaign
    # legitimately leaves a rejected cell unreceipted. Report both signals
    # rather than collapsing them into one exit code.
    incomplete = incomplete_shards(manifest, args.ledger_root, launched)
    if incomplete:
        print(f"Incomplete campaign shards: {', '.join(incomplete)}", file=sys.stderr)
        print(f"child logs: {', '.join(str(p) for p in child_logs)}", file=sys.stderr)
    if any(code != 0 for code in exit_codes):
        return 1
    return 1 if incomplete else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-manifest", required=True, type=Path)
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--max-gpu-memory-percent", type=int, default=90)
    parser.add_argument(
        "--gpu-shard-memory-percent",
        type=int,
        default=None,
        help=(
            "VRAM budget for the single GPU-bound (hu/ja/ro) shard only; "
            "defaults to --max-gpu-memory-percent so behaviour is unchanged unless asked"
        ),
    )
    parser.add_argument(
        "--gpu-locales",
        nargs="*",
        default=list(GPU_PRIMARY_LOCALES),
        help="Locales treated as GPU-bound; at most one such shard runs at a time",
    )
    parser.add_argument("--ledger-root", type=Path, default=Path("data/campaigns"))
    parser.add_argument(
        "--child",
        choices=("gate5", "worker"),
        default="gate5",
        help=(
            "Shard child entry point. 'gate5' (default) is run_gate5_batch.py -- the same "
            "engine every committed cell of this mission came through, and the only one that "
            "accepts --ledger-root. 'worker' is the legacy autonomous worker."
        ),
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--drain",
        action="store_true",
        help="After a pass, launch another for any shard still receipt-incomplete "
        "(a retry pass; each pass already hands every pending shard to a child)",
    )
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
    if args.child == "worker" and args.ledger_root != DEFAULT_LEDGER_ROOT:
        # The legacy worker has no --ledger-root flag, so its CampaignRunner would
        # silently fall back to the default while this parent verified receipts
        # somewhere else.  Fail closed rather than report a phantom incomplete shard.
        raise SystemExit("--ledger-root cannot reach the 'worker' child; use --child gate5")
    if args.gpu_shard_memory_percent is None:
        args.gpu_shard_memory_percent = args.max_gpu_memory_percent
    gpu_locales = tuple(str(locale) for locale in args.gpu_locales)

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
        launched_any = False
        while True:
            pending = pending_shards(manifest, args.ledger_root)
            if not pending:
                if not launched_any:
                    print("No pending campaign shards")
                break
            groups = assign_shard_groups(pending, args.max_workers, gpu_locales)
            for index, group in enumerate(groups):
                print(f"child {index}: {', '.join(str(s['shard_id']) for s in group)}")
            if args.dry_run:
                return 0
            launched_any = True
            wave_status = _run_wave(
                groups=groups,
                manifest=manifest,
                args=args,
                gpu_locales=gpu_locales,
                translator_repo=translator_repo,
                config_root=config_root,
            )
            if wave_status != 0:
                return wave_status
            if not args.drain:
                break

        duplicates = duplicate_receipts(args.ledger_root, manifest.campaign_id)
        if duplicates:
            print(f"Duplicate acceptance receipts: {sorted(duplicates)}", file=sys.stderr)
            return 1
        return 0
    finally:
        launcher_lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
