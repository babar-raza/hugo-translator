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

TC-APT-094 (plan SS0.10, BLITZ critical path 3 of 3) extends this to K
INDEPENDENT launcher processes, one per product family (campaign_id = family),
running concurrently against DIFFERENT campaign manifests. The GPU exclusivity
above only ever covered shards within ONE launcher's own manifest -- two such
launchers, each unaware of the other, could each decide to run their own
hu/ja/ro shard on the same GPU at once. `try_acquire_gpu_lane` closes that gap
with one lock file shared by every campaign under `ledger_root` (not
per-campaign), so at most one launcher process anywhere holds GPU-bound work
at a time; a launcher that cannot get the lane defers its GPU-bound shards
to whichever launcher does hold it, rather than blocking or running anyway.
This also wires `work_claims.py` (TC-APT-056) for real: a launcher refuses to
start without first holding the `family:<campaign_id>` claim, renewed every
wave so a long `--drain` run does not let the 45-minute TTL lapse mid-campaign.

This-task follow-up (2026-09-09, VR-01's explicit deferred integration):
`try_acquire_gpu_lane`'s one-GPU-shard-fleet-wide-at-a-time mutex is far more
conservative than the hardware needs -- VR-01 (`src/hardware/gpu_admission.py`)
measured 6 concurrent `m2m100_418m` processes running cleanly on this
machine's RTX 4090. `config/global.yaml`'s `gpu_admission.enabled` flag
(default ``false``, unchanged by this work) now actually gates something:
``False`` keeps this launcher on the exact `try_acquire_gpu_lane` path it has
always used; ``True`` switches the same call site to
`try_acquire_gpu_admission`, a drop-in that asks `GPUAdmissionController` for
a real-telemetry (nvidia-smi VRAM + temperature) admission slot instead of
the single mutex, so more than one GPU-bound shard can run fleet-wide at
once when the measured evidence says there is room. Flipping the flag live
is deliberately left to the orchestrating session.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from src.hardware.gpu_admission import GPUAdmissionController, make_admission_controller
from src.utils.file_lock import FileLock, LockError
from src.workers import work_claims
from src.workers.campaign_manifest import CampaignManifest
from src.workers.campaign_runner import CampaignLedger

# Plan §6.1: the locales TC-APT-006 measured `m2m100_418m` better in.  These run
# on the local GPU; every other locale is API-bound (`professionalize_llm`).
GPU_PRIMARY_LOCALES = ("hu", "ja", "ro")

# CampaignRunner.__init__'s own default; the legacy worker child cannot be told
# anything else, so a non-default root is only valid for the gate5 child.
DEFAULT_LEDGER_ROOT = Path("data/campaigns")

# TC-APT-094: one lock shared by every campaign under a ledger root -- NOT
# per-campaign like `parallel-launcher.lock` -- so it actually serializes GPU
# access across independent launcher processes running different manifests.
GPU_LANE_LOCK_NAME = "gpu_lane.lock"


class TerminalProgressDeadline:
    """Expire only when no accepted/rejected job completes during the interval."""

    def __init__(self, now: float, counts: tuple[int, int]):
        self.last_progress = now
        self.counts = counts

    def expired(self, now: float, counts: tuple[int, int], seconds: int) -> bool:
        if counts != self.counts:
            self.last_progress = now
            self.counts = counts
        return seconds > 0 and now - self.last_progress >= seconds


class TerminalLedgerTail:
    """Read appended complete records only; never parse a writer's partial row."""

    def __init__(self, path: Path):
        self.path = path
        self.offset = 0
        self.count = 0

    def poll(self) -> list[dict[str, Any]]:
        rows = []
        try:
            with self.path.open("rb") as stream:
                if self.path.stat().st_size < self.offset:
                    raise RuntimeError("terminal ledger truncated during active wave")
                stream.seek(self.offset)
                while True:
                    line = stream.readline()
                    if not line.endswith(b"\n"):
                        break
                    if line.strip():
                        rows.append(json.loads(line))
                        self.count += 1
                    self.offset = stream.tell()
        except FileNotFoundError:
            if self.offset:
                raise RuntimeError("terminal ledger removed during active wave")
        return rows


def checkpoint_wave(args: argparse.Namespace, manifest: CampaignManifest, translator_repo: Path) -> bool:
    """Drain TM, then attempt a governed checkpoint commit.

    A TM drain is a correctness boundary: starting a new wave while its single
    writer is unhealthy can lose or reorder learning, so its failures still
    propagate to the controller.  A content commit is deliberately different:
    every candidate is already receipt/hash backed and remains in the durable
    pending-commit ledger.  A transient Git/governance failure must therefore
    become a retryable commit backlog, never terminate a 100k-output
    translation run.

    Returns ``True`` when reconciliation completed, ``False`` when it was
    safely deferred.  It never treats a failed commit as completed.
    """
    from src.tm.intent_spool import TMIntentSpool

    spool = TMIntentSpool(args.tm_intent_spool_path)
    while True:
        before = spool.stats()
        if before.get("CLAIMED", 0):
            raise RuntimeError("checkpoint refuses claimed TM intents")
        if before.get("FAILED", 0):
            raise RuntimeError("checkpoint refuses failed TM intents")
        if not before.get("PENDING", 0):
            break
        subprocess.run([
            sys.executable, "-m", "src.workers.tm_intent_writer",
            "--repository-root", str(args.tm_repository_root),
            "--spool-path", str(args.tm_intent_spool_path), "--no-l3", "--limit", "500",
            "--owner", f"{manifest.campaign_id}-wave-writer",
        ], check=True, timeout=600)
        if spool.stats().get("PENDING", 0) >= before["PENDING"]:
            raise RuntimeError("TM checkpoint writer made no progress")
    try:
        subprocess.run([
            sys.executable, str(translator_repo / "scripts/campaign/reconcile_receipted_commits.py"),
            "--manifest", str(args.campaign_manifest), "--content-repo", str(manifest.content_repo),
            "--ledger-root", str(args.ledger_root), "--min-batch-size", "5", "--execute",
        ], check=True, timeout=900)
    except (subprocess.SubprocessError, OSError) as exc:
        checkpoint_path = args.ledger_root / manifest.campaign_id / "checkpoint_backlog.jsonl"
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "at": time.time(),
            "kind": "receipt_commit_deferred",
            "reason": str(exc),
            "wave_shards": int(args.checkpoint_wave_shards),
        }
        with checkpoint_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        print(
            "CHECKPOINT COMMIT DEFERRED: receipts remain hash-backed and will be retried "
            "after the next wave; continuing translation.",
            file=sys.stderr,
            flush=True,
        )
        return False
    return True


def stop_children(children: list[subprocess.Popen]) -> None:
    """Terminate owned process trees, including Windows venv redirector children."""
    for child in children:
        if child.poll() is not None:
            continue
        if sys.platform == "win32":
            result = subprocess.run(["taskkill.exe", "/PID", str(child.pid), "/T", "/F"],
                                    capture_output=True, timeout=30)
            if result.returncode and child.poll() is None:
                raise RuntimeError(f"cannot terminate owned child tree {child.pid}")
        else:
            child.terminate()
        try:
            child.wait(timeout=30)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=30)


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


def gpu_lane_lock_path(ledger_root: Path) -> Path:
    return ledger_root / GPU_LANE_LOCK_NAME


def try_acquire_gpu_lane(ledger_root: Path) -> FileLock | None:
    """Non-blocking attempt at the one global GPU lane (TC-APT-094).

    Returns the held `FileLock` (caller must `.release()` it when done with
    GPU-bound work) if acquired, or None if another launcher process anywhere
    already holds it -- the caller must defer its GPU-bound shards, never run
    them anyway.
    """
    lock = FileLock(gpu_lane_lock_path(ledger_root), timeout=0)
    return lock if lock.acquire(blocking=False) else None


def is_gpu_admission_enabled(translator_repo: Path) -> bool:
    """Read `gpu_admission.enabled` from `config/global.yaml` (default False on any error).

    This is the ONE switch between `try_acquire_gpu_lane`'s conservative
    single-mutex behaviour (default, unchanged) and `try_acquire_gpu_admission`'s
    real-telemetry admission path (VR-01). Any read/parse problem -- missing
    file, malformed YAML, missing key -- resolves to False, matching this
    launcher's existing fail-closed-to-today's-behaviour stance: a config
    problem must never silently unlock a code path nobody asked for.

    A module-level function (not inlined in `main()`) purely so tests can
    monkeypatch it directly to exercise both branches without needing to
    write to, or depend on the contents of, the real `config/global.yaml`.
    """
    cfg_path = translator_repo / "config" / "global.yaml"
    try:
        import yaml  # local import: mirrors make_admission_controller()'s own tolerance

        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        gpu_cfg = raw.get("gpu_admission") or {}
        return bool(gpu_cfg.get("enabled", False))
    except Exception:
        return False


def try_acquire_gpu_admission(
    ledger_root: Path,
    shard_id: str,
    model_id: str = "m2m100_418m",
) -> GPUAdmissionController | None:
    """Non-blocking real-telemetry admission attempt -- the `gpu_admission.enabled: true` path.

    Drop-in alternative to `try_acquire_gpu_lane` for a launcher that has
    opted into VR-01's `GPUAdmissionController` (measured on this machine's
    RTX 4090 to run up to 6 concurrent `m2m100_418m` processes cleanly --
    see `config/global.yaml`'s `gpu_admission` block) instead of the older
    one-GPU-shard-fleet-wide-at-a-time `gpu_lane.lock` mutex.

    Returns the controller itself, already holding a registered admission
    slot, on success -- the caller's existing `is not None` check needs no
    change, only its release call becomes `.release_admission()` instead of
    `FileLock.release()`. Returns None on denial (VRAM, thermal, or lock
    contention) so the caller defers this wave's GPU-bound shards exactly as
    it does today when the old lane is held by another launcher.

    `ledger_root` is accepted for call-site symmetry with
    `try_acquire_gpu_lane(ledger_root)` but does not choose where the
    admission registry lives: `GPUAdmissionController`'s registry is a fixed
    repo-relative path (`.local/gpu_admission_registry.json`) by design (see
    `make_admission_controller()`), so every launcher instance/campaign on
    this machine shares one real-telemetry view regardless of which ledger
    root or manifest it is running -- unlike the per-`ledger_root`
    `gpu_lane.lock`, which does need the path to be shared explicitly.
    """
    del ledger_root  # kept for call-site symmetry only; see docstring above
    controller = make_admission_controller()
    granted, _reason, _telemetry = controller.request_admission(shard_id, model_id)
    return controller if granted else None


def partition_for_wave(
    pending: list[dict[str, Any]],
    gpu_locales: tuple[str, ...],
    *,
    gpu_lane_available: bool,
) -> list[dict[str, Any]]:
    """Drop GPU-bound shards from this wave when the GPU lane is not ours.

    TC-APT-094: without this, K concurrent launcher processes each partition
    and schedule GPU-bound shards from their OWN manifest, with no shared view
    of whether another process already has one running -- two hu/ja/ro shards
    can land on the GPU at once. Excluded shards simply stay pending; whichever
    launcher does hold the lane picks them up on its own next wave.
    """
    if gpu_lane_available:
        return pending
    _gpu_bound, api_bound = partition_by_device(pending, gpu_locales)
    return api_bound


def select_pending_shards(
    manifest: CampaignManifest,
    ledger_root: Path,
    max_workers: int,
    gpu_locales: tuple[str, ...] = GPU_PRIMARY_LOCALES,
    *,
    gpu_lane_available: bool = True,
) -> list[dict[str, Any]]:
    """Return the next wave of shards: at most one GPU-bound shard, rest API-bound.

    Selection stays deterministic (``manifest.shards()`` yields sorted keys); the
    only reordering is that the single admissible GPU-bound shard leads the wave,
    which is what keeps GPU shards from ever overlapping each other.
    """
    pending = partition_for_wave(
        pending_shards(manifest, ledger_root), gpu_locales, gpu_lane_available=gpu_lane_available
    )
    gpu_bound, api_bound = partition_by_device(pending, gpu_locales)
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


def group_status_line(index: int, group: list[dict[str, Any]]) -> str:
    """Return bounded launcher telemetry for one child group.

    A full-portfolio group can contain tens of thousands of shards. Rendering
    every id into stdout can fill a supervised launcher's pipe before it calls
    ``Popen``, leaving a live but childless coordinator. Count plus a short
    deterministic preview is sufficient for operator correlation; the full
    assignment remains recoverable from the manifest and child log.
    """
    shard_ids = [str(shard["shard_id"]) for shard in group]
    preview = ", ".join(shard_ids[:3])
    suffix = ", ..." if len(shard_ids) > 3 else ""
    return f"child {index}: shard_count={len(shard_ids)} preview={preview}{suffix}"


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
    shard_list_path: Path | None = None,
    tm_intent_spool_path: Path | None = None,
    no_force_serialize: bool = False,
    recovery_qualification: bool = False,
    child: str = "gate5",
    translator_repo: Path | None = None,
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
            "-u",
            "scripts/campaign/run_gate5_batch.py",
            "--manifest",
            str(campaign_manifest),
            "--ledger-root",
            str(ledger_root),
            "--resume",
            "--max-gpu-memory-percent",
            str(memory_percent),
        ]
        if translator_repo is not None:
            # Interpreter switches must precede the script; script arguments
            # must follow it.  Inserting at index 2 became invalid once ``-u``
            # was added (``python -u --translator-repo ... script``).
            command[3:3] = ["--translator-repo", str(translator_repo)]
        if shard_list_path is not None:
            command += ["--shard-list", str(shard_list_path)]
        else:
            for shard_id in shard_ids:
                command += ["--shard-id", shard_id]
        if tm_intent_spool_path:
            command += ["--tm-intent-spool-path", str(tm_intent_spool_path)]
        if no_force_serialize:
            command.append("--no-force-serialize")
        if recovery_qualification:
            command.append("--recovery-qualification")
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
    # Keep children attached to the persistent controller host.  DETACHED_PROCESS
    # caused Intel/Fortran-backed runtimes to receive a window-close event and
    # abort (forrtl error 200) even while the controller itself remained live.
    # The production controller owns the console lifetime and waits for every
    # child, so inheriting it is the safe unattended behaviour.
    #
    # TC-PORT-LLM-012: that comment's diagnosis was incomplete. The crash
    # recurred under every console-creation configuration tried (shared,
    # detached, and a separate minimized console -- see
    # start_portfolio_missing_sweep_autonomous.ps1 and the taskcard evidence),
    # because none of them addressed the real cause: SetConsoleCtrlHandler
    # (NULL, TRUE) only suppresses CTRL_C_EVENT/CTRL_BREAK_EVENT, never
    # CTRL_CLOSE_EVENT/CTRL_LOGOFF_EVENT/CTRL_SHUTDOWN_EVENT -- exactly the
    # event class the Fortran runtime's own message names. run_gate5_batch.py
    # now installs a real handler for all five event types at process start,
    # so the worker itself is immune to this regardless of console
    # configuration; that is the actual fix. CREATE_NEW_PROCESS_GROUP is kept
    # here only as defense in depth (isolates the worker's signal group from
    # the controller's own console without detaching it) -- it does not
    # create a new console and does not reintroduce the DETACHED_PROCESS
    # failure mode.
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    children: list[subprocess.Popen] = []
    child_logs: list[Path] = []
    handles: list[Any] = []
    receipt_path = args.ledger_root / manifest.campaign_id / "acceptance_receipts.jsonl"
    failure_path = args.ledger_root / manifest.campaign_id / "failure_metadata.jsonl"
    receipt_tail = TerminalLedgerTail(receipt_path)
    failure_tail = TerminalLedgerTail(failure_path)
    receipt_tail.poll()
    failure_tail.poll()
    fresh_failures: list[dict[str, Any]] = []

    def line_count(path: Path) -> int:
        return receipt_tail.count if path == receipt_path else failure_tail.count

    accepted_at_start = line_count(receipt_path)
    failed_at_start = line_count(failure_path)
    for index, group in enumerate(groups):
        shard_list_path = (log_dir / f"{manifest.campaign_id}_child{index}.shards.txt").resolve()
        shard_list_path.write_text(
            "\n".join(str(shard["shard_id"]) for shard in group) + "\n",
            encoding="utf-8",
        )
        command = _child_command(
            shards=group,
            config_root=config_root,
            translator_repo=translator_repo,
            campaign_manifest=args.campaign_manifest,
            ledger_root=args.ledger_root,
            device=args.device,
            max_gpu_memory_percent=args.max_gpu_memory_percent,
            gpu_shard_memory_percent=args.gpu_shard_memory_percent,
            gpu_locales=gpu_locales,
            shard_list_path=shard_list_path,
            tm_intent_spool_path=args.tm_intent_spool_path,
            no_force_serialize=args.no_force_serialize,
            recovery_qualification=args.recovery_qualification,
            child=args.child,
        )
        log_path = log_dir / f"{manifest.campaign_id}_child{index}.log"
        handle = log_path.open("w", encoding="utf-8")
        handles.append(handle)
        child_logs.append(log_path)
        try:
            child = subprocess.Popen(
                command,
                # Keep mutable progress/model-cache state in the accessible
                # control workspace; --translator-repo still pins code/config.
                cwd=Path.cwd(),
                creationflags=flags,
                stdout=handle,
                stderr=subprocess.STDOUT,
            )
        except BaseException:
            stop_children(children)
            for opened in handles:
                opened.close()
            raise
        children.append(child)
    started = time.monotonic()
    started_at = time.time()
    deadline = TerminalProgressDeadline(started, (accepted_at_start, failed_at_start))
    # Terminal receipts alone are not a liveness signal for a large page: one
    # bounded Professionalize call can be healthy for minutes before it
    # produces an accept/reject row.  Gate5 emits an unbuffered, candidate-free
    # heartbeat every 30 seconds; only declare infrastructure timeout when
    # both terminal progress *and* every worker heartbeat have gone silent.
    child_activity: dict[Path, tuple[int, int] | None] = {}
    for log_path in child_logs:
        try:
            stat = log_path.stat()
            child_activity[log_path] = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            child_activity[log_path] = None
    last_worker_activity = started
    last_report = 0.0
    exit_codes: list[int] = []
    try:
        # A silent wait made a healthy Professionalize batch look hung.  Emit
        # bounded, receipt-backed progress on the launcher's own console.
        while True:
            receipt_tail.poll()
            fresh_failures.extend(failure_tail.poll())
            now = time.monotonic()
            child_timeout_seconds = int(getattr(args, "child_timeout_seconds", 900))
            for log_path in child_logs:
                try:
                    stat = log_path.stat()
                    snapshot: tuple[int, int] | None = (stat.st_mtime_ns, stat.st_size)
                except OSError:
                    snapshot = None
                if snapshot is not None and snapshot != child_activity.get(log_path):
                    child_activity[log_path] = snapshot
                    last_worker_activity = now
            terminal_stalled = deadline.expired(
                now, (line_count(receipt_path), line_count(failure_path)), child_timeout_seconds
            )
            worker_stalled = now - last_worker_activity >= child_timeout_seconds
            if terminal_stalled and worker_stalled:
                state = {
                    "status": "PAUSED_INFRASTRUCTURE_TIMEOUT",
                    "reason": (
                        f"no_terminal_progress_or_worker_heartbeat_seconds="
                        f"{child_timeout_seconds}"
                    ),
                    "accepted_current_run": line_count(receipt_path) - accepted_at_start,
                    "rejected_current_run": max(line_count(failure_path) - failed_at_start, 0),
                }
                if getattr(args, "watchdog_state", None):
                    args.watchdog_state.parent.mkdir(parents=True, exist_ok=True)
                    args.watchdog_state.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
                print("INFRASTRUCTURE TIMEOUT: terminating child workers", file=sys.stderr, flush=True)
                stop_children(children)
                return 2
            if now - last_report >= args.progress_interval_seconds:
                if getattr(args, "session_id", None) and not work_claims.acquire_claim(
                    f"family:{manifest.campaign_id}", args.session_id,
                    purpose="active campaign wave heartbeat",
                    claims_path=args.ledger_root / "claims.jsonl",
                ):
                    raise RuntimeError("campaign family claim lost during active wave")
                accepted = line_count(receipt_path)
                failed = line_count(failure_path)
                elapsed = max(now - started, 0.001)
                rate = (accepted - accepted_at_start) * 60.0 / elapsed
                remaining = max(manifest.expected_output_count - accepted, 0)
                eta = "n/a" if rate <= 0 else f"{remaining / rate / 60.0:.1f}h"
                live = sum(child.poll() is None for child in children)
                print(
                    f"progress accepted={accepted}/{manifest.expected_output_count} "
                    f"accepted_current={accepted - accepted_at_start} "
                    f"failed_current={max(failed - failed_at_start, 0)} "
                    f"failed={failed} rate={rate:.2f}/min remaining={remaining} "
                    f"eta={eta} live_children={live}/{len(children)}",
                    flush=True,
                )
                # Keep the authoritative watchdog state live during healthy
                # execution as well as on pause/exit.  The controller creates
                # the RUNNING marker, but without this refresh it cannot
                # distinguish a live wave from a hung or abandoned process.
                if getattr(args, "watchdog_state", None):
                    args.watchdog_state.parent.mkdir(parents=True, exist_ok=True)
                    args.watchdog_state.write_text(
                        json.dumps(
                            {
                                "status": "RUNNING",
                                "session_id": getattr(args, "session_id", None),
                                "started_at_epoch": started_at,
                                "reason": None,
                                "accepted_current_run": accepted - accepted_at_start,
                                "rejected_current_run": max(failed - failed_at_start, 0),
                                "accepted_total": accepted,
                                "rejected_total": failed,
                                "elapsed_seconds": elapsed,
                                "rate_per_minute": rate,
                                "updated_at": time.time(),
                            },
                            indent=2,
                            sort_keys=True,
                        ),
                        encoding="utf-8",
                    )
                last_report = now
            # TC-PS-04: evaluate only rows created by this wave, never stale history.
            roots = [str(row.get("gate") or row.get("root_cause_class") or "pipeline") for row in fresh_failures]
            provider_error = any("provider" in root.lower() or "rate_limit" in root.lower() or "ratelimit" in root.lower() for root in roots)
            # Typed zero-defect outcomes are expected data backlog, not
            # controller failures.  Only repeated unknown/infrastructure
            # roots may pause the wave; otherwise a bad source would stop a
            # 100K-page campaign indefinitely on the same validator ticket.
            data_root_tokens = (
                "gate", "validator", "language", "frontmatter", "repetition",
                "fidelity", "translation_rejected", "placeholder", "markdown",
            )
            infrastructure_roots = [
                root for root in roots
                if not any(token in root.lower() for token in data_root_tokens)
            ]
            identical = len(infrastructure_roots) >= 3 and len(set(infrastructure_roots[-3:])) == 1
            zero_accepts = (
                len(fresh_failures) >= 5
                and line_count(receipt_path) == accepted_at_start
                and bool(infrastructure_roots)
            )
            if provider_error or identical or zero_accepts:
                reason = ("provider_or_rate_limit" if provider_error else
                          "three_consecutive_identical_root_cause" if identical else
                          "zero_accepted_after_five_terminal_jobs")
                state = {"status": "PAUSED_VALIDATION_REGRESSION", "reason": reason,
                         "accepted_current_run": line_count(receipt_path) - accepted_at_start,
                         "rejected_current_run": len(fresh_failures), "root_causes": roots}
                if getattr(args, "watchdog_state", None):
                    args.watchdog_state.parent.mkdir(parents=True, exist_ok=True)
                    args.watchdog_state.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
                print(f"WATCHDOG PAUSE: {reason}; terminating children", file=sys.stderr, flush=True)
                stop_children(children)
                return 2
            if all(child.poll() is not None for child in children):
                exit_codes = [child.wait() for child in children]
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        state = {
            "status": "PAUSED_INTERRUPTED",
            "reason": "controller_interrupt",
            "accepted_current_run": line_count(receipt_path) - accepted_at_start,
            "rejected_current_run": max(line_count(failure_path) - failed_at_start, 0),
        }
        if getattr(args, "watchdog_state", None):
            args.watchdog_state.parent.mkdir(parents=True, exist_ok=True)
            args.watchdog_state.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        print("INTERRUPTED: terminating child workers", file=sys.stderr, flush=True)
        stop_children(children)
        return 2
    finally:
        # Parsing/I/O errors must not leave detached writers running after
        # the coordinator releases its campaign claim.
        stop_children(children)
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
    # A zero exit from run_gate5 means the worker completed its assigned
    # inputs safely.  A shard can still be incomplete because one or more
    # candidates were rejected by a zero-defect validator; those cells are
    # deliberately represented in failure_metadata/heal backlog and must not
    # turn a healthy campaign controller into a launcher failure.  Only a
    # non-zero child exit is an orchestration/infrastructure error.
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-manifest", required=True, type=Path)
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--checkpoint-wave-shards", type=int, default=0,
                        help="Bound each wave to this many shards; drain TM and commit before continuing.")
    parser.add_argument("--tm-repository-root", type=Path,
                        help="Repository containing the canonical TM store used by workers.")
    parser.add_argument("--progress-interval-seconds", type=int, default=30)
    parser.add_argument(
        "--child-timeout-seconds",
        type=int,
        default=900,
            help="Maximum time without accepted/rejected job progress; zero disables the inactivity timeout.",
    )
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
    parser.add_argument("--shard-list", type=Path, help="Restrict this pass to explicit shard IDs.")
    parser.add_argument(
        "--tm-intent-spool-path",
        type=Path,
        default=None,
        help="Campaign-scoped TM intent spool required for parallel gate5 children.",
    )
    parser.add_argument(
        "--no-force-serialize",
        action="store_true",
        help="Disable process-local serialization for governed API-only canaries only.",
    )
    parser.add_argument(
        "--recovery-qualification",
        action="store_true",
        help="Permit only an explicitly sharded recovery canary to retry known rejected cells.",
    )
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
    parser.add_argument(
        "--session-id",
        default=None,
        help=(
            "Fleet session id for the family work claim (TC-APT-056/094). Defaults to "
            "$AGENT_SESSION_ID, then a pid-derived id."
        ),
    )
    parser.add_argument(
        "--watchdog-state", type=Path,
        help="Write PAUSED_VALIDATION_REGRESSION state before stopping a bad wave.",
    )
    args = parser.parse_args(argv)
    if args.checkpoint_wave_shards < 0:
        parser.error("--checkpoint-wave-shards must be nonnegative")
    if args.checkpoint_wave_shards and (not args.tm_repository_root or not args.tm_intent_spool_path):
        parser.error("checkpoint waves require --tm-repository-root and --tm-intent-spool-path")
    if args.progress_interval_seconds < 5:
        raise SystemExit("--progress-interval-seconds must be at least 5")
    if not 1 <= args.max_workers <= 8:
        raise SystemExit("--max-workers must be 1..8")
    if not args.wait:
        raise SystemExit("--wait is required for governed campaign launches")
    if args.recovery_qualification and (args.child != "gate5" or args.shard_list is None):
        raise SystemExit("--recovery-qualification requires --child gate5 and an explicit --shard-list")
    if args.child == "worker" and args.ledger_root != DEFAULT_LEDGER_ROOT:
        # The legacy worker has no --ledger-root flag, so its CampaignRunner would
        # silently fall back to the default while this parent verified receipts
        # somewhere else.  Fail closed rather than report a phantom incomplete shard.
        raise SystemExit("--ledger-root cannot reach the 'worker' child; use --child gate5")
    if args.gpu_shard_memory_percent is None:
        args.gpu_shard_memory_percent = args.max_gpu_memory_percent
    gpu_locales = tuple(str(locale) for locale in args.gpu_locales)

    manifest = CampaignManifest.load(args.campaign_manifest)
    # Persist watchdog state by default so unattended launches cannot lose the
    # pause reason merely because a caller omitted the optional flag.
    if args.watchdog_state is None:
        args.watchdog_state = (
            args.ledger_root / manifest.campaign_id / "watchdog_state.json"
        )
    # Eight is permitted only after the bounded Professionalize probe has
    # demonstrated zero provider/rate-limit errors and p95 no worse than
    # 1.5x the four-worker baseline.  Keep 16 out of this launcher until its
    # separate qualification exists; this is a real ceiling, not a hint.
    if args.max_workers > 4:
        calibration_path = (
            Path("reports/campaigns")
            / manifest.campaign_id
            / "evidence/professionalize-concurrency-calibration.json"
        )
        try:
            evidence = json.loads(calibration_path.read_text(encoding="utf-8"))
            ramp = (evidence.get("calibration") or {}).get("concurrency_ramp") or []
            baseline = next(item for item in ramp if int(item.get("level", 0)) == 4)
            target = next(item for item in ramp if int(item.get("level", 0)) == args.max_workers)
            qualified = (
                int(target.get("errors", 1)) == 0
                and int(target.get("rate_limited", 1)) == 0
                and float(target.get("p95", float("inf"))) <= 1.5 * float(baseline["p95"])
            )
        except (OSError, ValueError, KeyError, StopIteration, TypeError, json.JSONDecodeError):
            qualified = False
        if not qualified:
            raise SystemExit(
                f"--max-workers {args.max_workers} lacks qualified Professionalize concurrency evidence"
            )
    professionalize_only = bool(manifest.retry_policy.get("professionalize_only", False))
    if args.no_force_serialize and not professionalize_only:
        raise SystemExit("--no-force-serialize requires retry_policy.professionalize_only=true")
    if args.max_workers > 1 and args.child == "gate5" and not args.tm_intent_spool_path and not args.dry_run:
        raise SystemExit("parallel gate5 launches require --tm-intent-spool-path")
    if professionalize_only:
        # There is no local-model work in this campaign; treating hu/ja/ro as
        # GPU-bound would serialize API calls for no safety benefit.
        gpu_locales = ()
    translator_repo = Path(__file__).resolve().parents[2]
    config_root = translator_repo / "config"
    # TC-APT-047/094 follow-up: read once, not per-wave -- config/global.yaml's
    # gpu_admission.enabled (default False, unchanged by this task) is the one
    # switch between try_acquire_gpu_lane (today's behaviour) and
    # try_acquire_gpu_admission (VR-01's real-telemetry admission controller).
    gpu_admission_on = is_gpu_admission_enabled(translator_repo)

    # TC-APT-094: refuse to start without holding this family's fleet-visible
    # claim -- unlike the per-campaign parallel-launcher.lock below (a bare OS
    # mutex no other session can see), claims.jsonl lets peer sessions across
    # the fleet know this campaign is already being worked before they try it.
    session_id = args.session_id or os.environ.get("AGENT_SESSION_ID") or f"launcher-pid{os.getpid()}"
    args.session_id = session_id
    family_key = f"family:{manifest.campaign_id}"
    claims_path = args.ledger_root / "claims.jsonl"
    if not work_claims.acquire_claim(
        family_key,
        session_id,
        purpose=f"K-launcher fan-out for {manifest.campaign_id}",
        claims_path=claims_path,
    ):
        print(f"Another session holds the family claim for {family_key}", file=sys.stderr)
        return 1

    lock_path = args.ledger_root / manifest.campaign_id / "parallel-launcher.lock"
    try:
        launcher_lock = FileLock(lock_path, timeout=1)
        launcher_lock.acquire()
    except LockError:
        print("A governed campaign launcher is already active", file=sys.stderr)
        work_claims.release_claim(family_key, session_id, claims_path=claims_path)
        return 1
    try:
        launched_any = False
        completed_waves_path = args.ledger_root / manifest.campaign_id / "completed_wave_shards.json"
        manifest_digest = hashlib.sha256(args.campaign_manifest.read_bytes()).hexdigest()
        visited: set[str] = set()
        if args.checkpoint_wave_shards and completed_waves_path.exists():
            saved = json.loads(completed_waves_path.read_text(encoding="utf-8"))
            if saved.get("manifest_sha256") == manifest_digest:
                visited = set(saved["shards"])
        while True:
            # Renew every pass: a long --drain run must not let the 45-minute
            # claim TTL lapse mid-campaign and let another session start in.
            work_claims.acquire_claim(
                family_key,
                session_id,
                purpose=f"K-launcher fan-out for {manifest.campaign_id}",
                claims_path=claims_path,
            )

            pending_all = pending_shards(manifest, args.ledger_root)
            if args.checkpoint_wave_shards:
                pending_all = [s for s in pending_all if str(s["shard_id"]) not in visited]
            if args.shard_list:
                allowed = {line.strip() for line in args.shard_list.read_text(encoding="utf-8").splitlines() if line.strip()}
                pending_all = [s for s in pending_all if str(s["shard_id"]) in allowed]
            if args.checkpoint_wave_shards:
                pending_all = pending_all[:args.checkpoint_wave_shards]
            gpu_bound, _api_bound = partition_by_device(pending_all, gpu_locales)
            if gpu_admission_on and gpu_bound:
                # VR-01 path: real-telemetry admission instead of the single
                # fleet-wide mutex. shard_id is this launcher's own manifest
                # plus the lead GPU-bound shard, so a denial/registry dump is
                # attributable to a specific campaign+shard for debugging.
                admission_shard_id = f"{manifest.campaign_id}:{gpu_bound[0]['shard_id']}"
                gpu_lane_lock = try_acquire_gpu_admission(args.ledger_root, admission_shard_id)
            else:
                # Unchanged: today's exact single-mutex behaviour.
                gpu_lane_lock = try_acquire_gpu_lane(args.ledger_root) if gpu_bound else None
            try:
                pending = partition_for_wave(
                    pending_all, gpu_locales, gpu_lane_available=gpu_lane_lock is not None
                )
                if gpu_bound and gpu_lane_lock is None:
                    print(
                        f"GPU lane held by another launcher; deferring "
                        f"{len(gpu_bound)} GPU-bound shard(s)"
                    )
                if not pending:
                    if not launched_any:
                        print("No pending campaign shards")
                    break
                groups = assign_shard_groups(pending, args.max_workers, gpu_locales)
                for index, group in enumerate(groups):
                    print(group_status_line(index, group))
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
            finally:
                if gpu_lane_lock is not None:
                    if isinstance(gpu_lane_lock, GPUAdmissionController):
                        gpu_lane_lock.release_admission()
                    else:
                        gpu_lane_lock.release()
            if wave_status != 0:
                return wave_status
            if args.checkpoint_wave_shards:
                try:
                    checkpoint_committed = checkpoint_wave(args, manifest, translator_repo)
                except (RuntimeError, subprocess.SubprocessError, OSError) as exc:
                    args.watchdog_state.write_text(json.dumps({
                        # Only the TM drain reaches this path.  It is a
                        # correctness boundary and must pause before another
                        # wave is permitted.  Receipt-commit failures are
                        # handled inside checkpoint_wave as durable backlog.
                        "status": "PAUSED_TM_CHECKPOINT_FAILURE", "reason": str(exc),
                        "session_id": session_id, "updated_at": time.time(),
                    }, sort_keys=True), encoding="utf-8")
                    return 2
                if not checkpoint_committed:
                    print(
                        "checkpoint commit deferred; advancing with receipt-backed commit backlog",
                        file=sys.stderr,
                        flush=True,
                    )
                visited.update(str(shard["shard_id"]) for group in groups for shard in group)
                temporary = completed_waves_path.with_suffix(".tmp")
                temporary.write_text(json.dumps({"schema_version": 1, "manifest_sha256": manifest_digest,
                                                "shards": sorted(visited)}, sort_keys=True), encoding="utf-8")
                temporary.replace(completed_waves_path)
                continue
            if not args.drain:
                break

        duplicates = duplicate_receipts(args.ledger_root, manifest.campaign_id)
        if duplicates:
            print(f"Duplicate acceptance receipts: {sorted(duplicates)}", file=sys.stderr)
            return 1
        if getattr(args, "watchdog_state", None):
            receipt_path = args.ledger_root / manifest.campaign_id / "acceptance_receipts.jsonl"
            failure_path = args.ledger_root / manifest.campaign_id / "failure_metadata.jsonl"
            count_lines = lambda path: sum(1 for _ in path.open("rb")) if path.exists() else 0
            args.watchdog_state.write_text(
                json.dumps(
                    {
                        "status": "COMPLETED_WITH_BACKLOG",
                        "reason": "validator_rejections_remain_in_backlog",
                        "accepted_total": count_lines(receipt_path),
                        "rejected_total": count_lines(failure_path),
                        "updated_at": time.time(),
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
        return 0
    finally:
        launcher_lock.release()
        work_claims.release_claim(family_key, session_id, claims_path=claims_path)


if __name__ == "__main__":
    raise SystemExit(main())
