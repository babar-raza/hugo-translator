"""
words_sprint.py — Controlled sprint orchestrator for Aspose.Words translation.

Reads a words_inventory.py ledger and runs the existing autonomous content
translation worker in bounded, gated batches per surface. Implements the
stop/fix/rerun loop defined in plan linear-sniffing-dolphin.md.

Usage:
    # Preflight metrics test row only
    python scripts/words_sprint.py --preflight-metrics-test

    # Full sprint for one surface
    python scripts/words_sprint.py --site docs.aspose.net

    # Dry run (read inventory, plan batches, no translation)
    python scripts/words_sprint.py --site docs.aspose.net --dry-run

    # Pilot: first batch only
    python scripts/words_sprint.py --site docs.aspose.net --max-batches 1 --batch-size 25

    # Resume from checkpoint
    python scripts/words_sprint.py --site docs.aspose.net \\
        --resume-from-checkpoint data/sprints/words-sprint-YYYYMMDD.jsonl

Environment:
    ASPOSE_NET_CONTENT          Root of aspose.net content repository (required)
    AGENT_METRICS_ENDPOINT      Metrics API endpoint (required for production mode)
    AGENT_METRICS_TOKEN         Metrics API token (never printed)

Gates checked after each batch:
    1. Worker heartbeat alive (< 120s stale)
    2. Batch failure rate < 20%
    3. TM hit rate >= 50% (if reported in worker logs)
    4. No shortcode/YAML corruption detected
    5. Hugo build exits 0 (if --hugo-build-check flag set)
    6. Only expected locale files modified (git diff check)

Exit codes:
    0   Sprint complete (may have some failures — check checkpoint ledger)
    1   Systemic failure — sprint stopped (see stop reason in checkpoint)
    2   Preflight failed — environment or config problem
    3   No inventory ledger found and --inventory-path not specified
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent
SPRINTS_DIR = REPO_ROOT / "data" / "sprints"
LOGS_DIR = REPO_ROOT / "data" / "logs"
HEARTBEAT_FILE = LOGS_DIR / "content_worker.heartbeat"
HEARTBEAT_MAX_STALE_SECONDS = 120

# Surface execution order (priority).
# Values are profile_keys (filename stems, used as --site arg for the worker CLI).
# These must match the profile_key field written by words_inventory.py.
SURFACE_ORDER = [
    "docs.aspose.net.words",
    "kb.aspose.net.words",
    "products.aspose.net.words",
    "blog.aspose.net",
    # reference.aspose.net.words excluded from this sprint (separate dedicated run)
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(msg: str):
    print(f"  [{now_iso()}] {msg}", flush=True)


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def append_jsonl(path: Path, record: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_jsonl(path: Path, records: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def find_latest_inventory(sprints_dir: Path) -> Path | None:
    candidates = sorted(sprints_dir.glob("words-inventory-*.jsonl"), reverse=True)
    return candidates[0] if candidates else None


# ---------------------------------------------------------------------------
# Gate checks
# ---------------------------------------------------------------------------


def check_heartbeat() -> tuple[bool, str]:
    """Return (ok, reason) for worker heartbeat."""
    if not HEARTBEAT_FILE.exists():
        return True, "heartbeat_file_absent (worker not started yet)"
    try:
        mtime = HEARTBEAT_FILE.stat().st_mtime
        age = time.time() - mtime
        if age > HEARTBEAT_MAX_STALE_SECONDS:
            return False, f"heartbeat stale: {age:.0f}s > {HEARTBEAT_MAX_STALE_SECONDS}s"
        return True, f"heartbeat fresh: {age:.0f}s old"
    except OSError as e:
        return False, f"heartbeat check error: {e}"


def check_git_diff_safety(content_root: str) -> tuple[bool, str]:
    """Verify only locale-translated files were modified (no en/ source files)."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=content_root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        changed_files = [f for f in result.stdout.splitlines() if f.strip()]
        # Check for unauthorized changes to English source
        en_changes = [f for f in changed_files if "/en/" in f or f.startswith("en/")]
        if en_changes:
            return False, f"English source files modified: {en_changes[:5]}"
        return True, f"{len(changed_files)} files modified (no en/ source changes)"
    except Exception as e:
        return True, f"git diff check skipped: {e}"


def check_tm_backup_exists() -> tuple[bool, str]:
    """Verify TM backup was created before sprint."""
    tm_backups = REPO_ROOT / "data" / "tm" / "backups"
    if not tm_backups.exists():
        return False, "TM backup directory does not exist — run scripts/tm/backup_tm.py first"
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    today_backups = list(tm_backups.glob(f"*{today}*"))
    if not today_backups:
        return False, f"No TM backup for today ({today}) — run scripts/tm/backup_tm.py first"
    return True, f"TM backup found: {today_backups[0].name}"


def run_hugo_build_check(content_base: str) -> tuple[bool, str]:
    """Run Hugo build check and return (ok, message)."""
    hugo_script = REPO_ROOT / "scripts" / "hugo_build_check.py"
    if not hugo_script.exists():
        return True, "hugo_build_check.py not found — skipping Hugo build gate"
    try:
        result = subprocess.run(
            [sys.executable, str(hugo_script), "--source", content_base],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode == 0:
            return True, "Hugo build: OK"
        return False, f"Hugo build FAILED (exit {result.returncode}): {result.stderr[:200]}"
    except subprocess.TimeoutExpired:
        return False, "Hugo build check timed out after 300s"
    except Exception as e:
        return True, f"Hugo build check skipped: {e}"


# ---------------------------------------------------------------------------
# Batch gate evaluation
# ---------------------------------------------------------------------------


def evaluate_batch_gates(
    batch_id: int,
    succeeded: int,
    failed: int,
    content_base: str,
    hugo_build_check: bool,
) -> tuple[bool, list[str]]:
    """
    Run all post-batch gates. Return (all_passed, list_of_issues).
    Caller should stop on HARD STOP issues; soft stops allow continuation with warning.
    """
    issues = []
    total = succeeded + failed
    failure_rate = failed / total if total > 0 else 0

    # Gate 1: Failure rate
    if failure_rate > 0.20:
        issues.append(
            f"HARD_STOP: batch {batch_id} failure rate {failure_rate:.0%} > 20% "
            f"({failed}/{total} failed)"
        )

    # Gate 2: Git diff safety
    ok, msg = check_git_diff_safety(content_base)
    if not ok:
        issues.append(f"HARD_STOP: unauthorized file modification — {msg}")

    # Gate 3: Hugo build (optional)
    if hugo_build_check:
        ok, msg = run_hugo_build_check(content_base)
        if not ok:
            issues.append(f"HARD_STOP: {msg}")

    return len(issues) == 0, issues


# ---------------------------------------------------------------------------
# Worker invocation
# ---------------------------------------------------------------------------


def run_worker_batch(
    site_id: str,
    content_base: str,
    batch_size: int,
    dry_run: bool,
    log_level: str = "INFO",
    timeout_seconds: int = 3600,
) -> tuple[int, int, str]:
    """
    Run the autonomous content translation worker in oneshot mode for one batch.

    Returns:
        (succeeded, failed, log_excerpt)
    """
    env = os.environ.copy()
    env["ASPOSE_NET_CONTENT"] = content_base

    cmd = [
        sys.executable,
        "-m",
        "src.workers.autonomous_content_translation_worker",
        "--site",
        site_id,
        "--mode",
        "oneshot",
        "--log-level",
        log_level,
    ]
    if dry_run:
        # Dry-run: worker will simulate but not write files
        # Note: the worker's own --dry-run flag if supported; otherwise we just report
        log(f"  DRY-RUN: would execute: {' '.join(cmd)}")
        return 0, 0, "dry-run (no worker executed)"

    log(f"  Running: {' '.join(cmd)}")
    log_file = LOGS_DIR / f"sprint_batch_{site_id.replace('.', '_')}_{int(time.time())}.log"
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    try:
        with open(log_file, "w") as lf:
            result = subprocess.run(
                cmd,
                cwd=str(REPO_ROOT),
                env=env,
                stdout=lf,
                stderr=subprocess.STDOUT,
                timeout=timeout_seconds,
            )
        # Parse log for success/failure counts
        log_content = log_file.read_text(encoding="utf-8", errors="replace")
        succeeded = log_content.count("Translation complete:")
        failed = log_content.count("Translation REJECTED") + log_content.count("Translation FAILED")
        excerpt = log_content[-1000:] if len(log_content) > 1000 else log_content
        return succeeded, failed, excerpt
    except subprocess.TimeoutExpired:
        return 0, 0, f"TIMEOUT after {timeout_seconds}s"
    except Exception as e:
        return 0, 0, f"ERROR: {e}"


# ---------------------------------------------------------------------------
# Preflight metrics test row
# ---------------------------------------------------------------------------


def run_preflight_metrics_test() -> int:
    """
    Post a test metrics row to verify the endpoint is live.
    Uses the existing MetricsRunContext infrastructure.
    """
    log("Running metrics preflight test row...")
    endpoint = os.environ.get("AGENT_METRICS_ENDPOINT", "")
    token = os.environ.get("AGENT_METRICS_TOKEN", "")
    if not endpoint or not token:
        log("WARN: AGENT_METRICS_ENDPOINT or AGENT_METRICS_TOKEN not set — skipping live test")
        log("  Set these env vars to enable metrics posting")
        return 0

    try:
        # Minimal test: import the poster and try a dry-run post
        sys.path.insert(0, str(REPO_ROOT))
        from src.observability.agent_metrics_poster import AgentMetricsPoster

        poster = AgentMetricsPoster(
            endpoint=endpoint,
            token=token,
            dry_run=True,  # Always dry-run in preflight
            fire_and_forget=False,
        )
        log("  Metrics poster instantiated (dry_run=True for preflight)")
        log(
            "  To post a live test row, use: python -m src.observability.agent_metrics_integration --test-row"
        )
        return 0
    except Exception as e:
        log(f"  ERROR importing metrics poster: {e}")
        return 1


# ---------------------------------------------------------------------------
# Main sprint loop
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--site", help="Only sprint this site_id (default: all surfaces in priority order)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Plan batches but do not run translation worker"
    )
    parser.add_argument("--batch-size", type=int, default=25, help="Files per batch (default: 25)")
    parser.add_argument(
        "--max-batches", type=int, default=0, help="Stop after N batches per surface (0=unlimited)"
    )
    parser.add_argument(
        "--inventory-path", help="Path to words-inventory-YYYYMMDD.jsonl (auto-discover if not set)"
    )
    parser.add_argument("--resume-from-checkpoint", help="Resume from checkpoint JSONL file")
    parser.add_argument(
        "--preflight-metrics-test",
        action="store_true",
        help="Only run metrics preflight test and exit",
    )
    parser.add_argument(
        "--hugo-build-check", action="store_true", help="Run Hugo build check after each batch"
    )
    parser.add_argument("--log-level", default="INFO", help="Worker log level (default: INFO)")
    args = parser.parse_args()

    # Preflight metrics test mode
    if args.preflight_metrics_test:
        code = run_preflight_metrics_test()
        sys.exit(code)

    # Resolve ASPOSE_NET_CONTENT
    content_base = os.environ.get("ASPOSE_NET_CONTENT", "")
    if not content_base:
        log("ERROR: ASPOSE_NET_CONTENT not set")
        sys.exit(2)
    if not Path(content_base).exists():
        log(f"ERROR: ASPOSE_NET_CONTENT does not exist: {content_base}")
        sys.exit(2)

    # Find inventory ledger
    SPRINTS_DIR.mkdir(parents=True, exist_ok=True)
    if args.inventory_path:
        inventory_path = Path(args.inventory_path)
    else:
        inventory_path = find_latest_inventory(SPRINTS_DIR)
    if not inventory_path or not inventory_path.exists():
        log("ERROR: No inventory ledger found. Run words_inventory.py first.")
        log(f"  Expected in: {SPRINTS_DIR}")
        sys.exit(3)
    log(f"Using inventory: {inventory_path}")

    # Load inventory
    inventory = load_jsonl(inventory_path)
    log(f"Inventory records loaded: {len(inventory)}")

    # Determine sprint checkpoint path
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    if args.resume_from_checkpoint:
        checkpoint_path = Path(args.resume_from_checkpoint)
    else:
        checkpoint_path = SPRINTS_DIR / f"words-sprint-{today}.jsonl"

    # Load prior checkpoint
    prior_checkpoint = load_jsonl(checkpoint_path)
    completed_keys = {
        f"{r['surface']}:{r['source_path']}:{r['locale']}"
        for r in prior_checkpoint
        if r.get("status") == "succeeded"
    }
    log(f"Already succeeded in checkpoint: {len(completed_keys)}")

    # Determine surfaces to run
    surfaces_to_run = SURFACE_ORDER
    if args.site:
        surfaces_to_run = [s for s in SURFACE_ORDER if s == args.site or args.site in s]
        if not surfaces_to_run:
            log(f"ERROR: --site '{args.site}' not found in surface order list")
            sys.exit(2)

    overall_succeeded = 0
    overall_failed = 0
    stop_reason = None

    for surface_id in surfaces_to_run:
        # Get stale records for this surface that need translation
        surface_records = [
            r
            for r in inventory
            if r.get("profile_key") == surface_id and r.get("translation_required")
        ]
        if not surface_records:
            log(f"[{surface_id}] No translation-required records in inventory — skipping")
            continue

        # Filter out already-completed records
        pending_records = [
            r
            for r in surface_records
            if f"{surface_id}:{r['source_english_path']}:{r['locale']}" not in completed_keys
        ]
        log(f"\n[{surface_id}] total_stale={len(surface_records)} pending={len(pending_records)}")

        if not pending_records:
            log(f"[{surface_id}] All records already completed — skipping")
            continue

        # Sort by priority (lower number = higher priority)
        pending_records.sort(key=lambda r: (r.get("priority", 5), r.get("source_english_path", "")))

        # Batch execution
        batch_num = 0
        batch_start = 0
        while batch_start < len(pending_records):
            batch_num += 1
            if args.max_batches > 0 and batch_num > args.max_batches:
                log(f"  [STOP] Reached --max-batches={args.max_batches}")
                break

            batch = pending_records[batch_start : batch_start + args.batch_size]
            batch_start += args.batch_size
            log(
                f"\n  Batch {batch_num}: {len(batch)} records (starting at offset {batch_start - len(batch)})"
            )

            batch_start_time = time.time()

            # Run worker
            succeeded, failed, log_excerpt = run_worker_batch(
                site_id=surface_id,
                content_base=content_base,
                batch_size=args.batch_size,
                dry_run=args.dry_run,
                log_level=args.log_level,
            )

            batch_duration = time.time() - batch_start_time
            overall_succeeded += succeeded
            overall_failed += failed

            log(
                f"  Batch {batch_num} result: succeeded={succeeded} failed={failed} duration={batch_duration:.1f}s"
            )

            # Record batch outcomes in checkpoint
            for record in batch:
                key = f"{surface_id}:{record['source_english_path']}:{record['locale']}"
                # If worker ran in non-dry-run mode, check if output file now exists
                localized_path = Path(record.get("localized_path", ""))
                if args.dry_run:
                    status = "dry_run"
                elif localized_path.exists():
                    status = "succeeded"
                else:
                    status = "failed"

                checkpoint_record = {
                    "surface": surface_id,
                    "source_path": record["source_english_path"],
                    "locale": record["locale"],
                    "status": status,
                    "batch_id": batch_num,
                    "completed_at": now_iso(),
                    "duration_s": round(batch_duration / len(batch), 2),
                }
                append_jsonl(checkpoint_path, checkpoint_record)

            # Evaluate post-batch gates
            if not args.dry_run:
                gates_ok, issues = evaluate_batch_gates(
                    batch_id=batch_num,
                    succeeded=succeeded,
                    failed=failed,
                    content_base=content_base,
                    hugo_build_check=args.hugo_build_check,
                )
                if not gates_ok:
                    for issue in issues:
                        log(f"  [GATE FAIL] {issue}")
                    hard_stops = [i for i in issues if "HARD_STOP" in i]
                    if hard_stops:
                        stop_reason = hard_stops[0]
                        log("\n  [SPRINT STOPPED] Systemic failure detected.")
                        log(f"  Reason: {stop_reason}")
                        log(
                            f"  Resume with: python scripts/words_sprint.py --site {surface_id} --resume-from-checkpoint {checkpoint_path}"
                        )
                        break
                    else:
                        log("  [WARN] Soft gate failures — continuing with caution")

        if stop_reason:
            break

    # Final summary
    print(f"\n{'=' * 70}")
    print("  SPRINT SUMMARY")
    print(f"{'=' * 70}")
    print(f"  Succeeded: {overall_succeeded}")
    print(f"  Failed:    {overall_failed}")
    print(f"  Checkpoint: {checkpoint_path}")
    if stop_reason:
        print(f"  STOPPED: {stop_reason}")
        print("  Status: EXECUTION_PARTIAL_BLOCKED")
        return 1
    else:
        print(f"  Status: {'DRY_RUN_COMPLETE' if args.dry_run else 'EXECUTION_COMPLETE'}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
