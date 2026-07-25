#!/usr/bin/env python3
"""Repeatable wrapper for governed Aspose.org multi-subdomain campaigns."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
GOVERNED_RUNNER = ROOT / "scripts" / "quality" / "aspose_org_governed_retranslate.py"
DEFAULT_CONTENT = Path(r"C:\Users\prora\OneDrive\Documents\GitHub\aspose.org\content")
SITES = ["kb.aspose.org", "blog.aspose.org", "docs.aspose.org", "reference.aspose.org"]
_N_LOCALE_SHARDS = 6


def compute_locale_shards(site_id: str, n_shards: int = _N_LOCALE_SHARDS) -> list[tuple[str, str]]:
    """Partition site_id's live target_langs into n_shards work-distribution
    groups, computed fresh from its site profile every call. Shard names
    stay stable ("latin-a".."latin-f") since checkpoint files are keyed by
    shard_id, but membership auto-adapts whenever target_langs changes --
    no code edit required for a locale-set change to take effect here.
    """
    from src.utils.config_loader import ConfigService

    config_service = ConfigService(str(ROOT / "config"))
    profile = config_service.get_site_profile(site_id)
    locales = sorted(profile.target_langs)
    shard_names = [f"latin-{chr(ord('a') + i)}" for i in range(n_shards)]
    shards = [locales[i::n_shards] for i in range(n_shards)]
    return [
        (name, ",".join(group))
        for name, group in zip(shard_names, shards)
        if group
    ]


HUGO_CONFIGS = {
    "kb.aspose.org": "configs/kb.aspose.org.toml",
    "blog.aspose.org": "configs/blog.aspose.org.yml",
    "docs.aspose.org": "configs/docs.aspose.org.toml",
    "reference.aspose.org": "configs/reference.aspose.org.toml",
}
PROFILE_MODEL_BATCH_SIZE = {
    "safe": 0,
    "fast": 128,
    "max-vram": 256,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def query_vram_snapshot() -> dict[str, Any]:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=timestamp,name,utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
        )
    except Exception as exc:
        return {"available": False, "error": repr(exc), "captured_at": utc_now()}
    if result.returncode != 0:
        return {
            "available": False,
            "error": result.stderr.strip(),
            "captured_at": utc_now(),
        }
    line = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
    parts = [part.strip() for part in line.split(",")]
    if len(parts) < 5:
        return {"available": False, "error": f"unexpected nvidia-smi output: {line}", "captured_at": utc_now()}
    try:
        used_mb = int(parts[3])
        total_mb = int(parts[4])
    except ValueError:
        return {"available": False, "error": f"unexpected nvidia-smi numbers: {line}", "captured_at": utc_now()}
    return {
        "available": True,
        "timestamp": parts[0],
        "name": parts[1],
        "utilization_gpu_percent": int(parts[2]),
        "memory_used_mb": used_mb,
        "memory_total_mb": total_mb,
        "memory_used_percent": round((used_mb / total_mb) * 100, 2) if total_mb else None,
        "captured_at": utc_now(),
    }


def wait_for_vram_below(target_percent: int, log_path: Path, max_wait_seconds: int = 900) -> dict[str, Any]:
    start = time.monotonic()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    while True:
        snapshot = query_vram_snapshot()
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"## VRAM {json.dumps(snapshot, ensure_ascii=False)}\n")
        if not snapshot.get("available"):
            return snapshot | {"waited_seconds": round(time.monotonic() - start, 2), "decision": "proceed_no_vram_data"}
        used_percent = float(snapshot.get("memory_used_percent") or 0)
        if used_percent < target_percent:
            return snapshot | {"waited_seconds": round(time.monotonic() - start, 2), "decision": "proceed_below_target"}
        if time.monotonic() - start >= max_wait_seconds:
            return snapshot | {"waited_seconds": round(time.monotonic() - start, 2), "decision": "proceed_after_wait_timeout"}
        time.sleep(30)


def log_contains_cuda_oom(log_path: Path) -> bool:
    if not log_path.exists():
        return False
    text = log_path.read_text(encoding="utf-8", errors="replace").lower()
    return "cuda out of memory" in text or "outofmemoryerror" in text


def find_python(explicit: str | None) -> Path:
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    candidates.extend([ROOT / ".venv" / "Scripts" / "python.exe", Path(sys.executable)])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise SystemExit("No usable Python interpreter found. Provide --python.")


def run_cmd(cmd: list[str], log_path: Path, cwd: Path = ROOT, timeout: int | None = None) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\n## START {utc_now()}\n")
        log.write(" ".join(cmd) + "\n")
        log.flush()
        try:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                env=os.environ.copy(),
                text=True,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout,
            )
            code = result.returncode
        except subprocess.TimeoutExpired as exc:
            log.write(f"## TIMEOUT {utc_now()} {exc!r}\n")
            code = 124
        log.write(f"## END {utc_now()} exit={code}\n")
    return code


def site_summary(run_id: str, site: str) -> dict[str, Any]:
    final_dir = ROOT / ".local" / "evidences" / site / run_id / "final"
    summary = final_dir / "summary.json"
    direct = read_json(summary, {})
    shard_summaries = [
        read_json(path, {})
        for path in sorted(final_dir.glob("summary.*.json"))
        if path.name != "summary.json"
    ]
    shard_summaries = [summary for summary in shard_summaries if summary]
    if not shard_summaries:
        return direct
    required_pairs = sum(int(summary.get("required_pairs", 0)) for summary in shard_summaries)
    accepted_pairs = sum(int(summary.get("accepted_pairs", 0)) for summary in shard_summaries)
    failed_pairs = sum(int(summary.get("failed_pairs", 0)) for summary in shard_summaries)
    source_mutation_count = sum(int(summary.get("source_mutation_count", 0)) for summary in shard_summaries)
    language_mixing_failure_count = sum(
        int(summary.get("language_mixing_failure_count", 0)) for summary in shard_summaries
    )
    failure_type_counts: dict[str, int] = {}
    for summary in shard_summaries:
        for failure_type, count in (summary.get("failure_type_counts") or {}).items():
            failure_type_counts[failure_type] = failure_type_counts.get(failure_type, 0) + int(count)
    return {
        "run_id": run_id,
        "site_id": site,
        "summary_kind": "aggregated_shards",
        "shard_count": len(shard_summaries),
        "required_pairs": required_pairs,
        "accepted_pairs": accepted_pairs,
        "failed_pairs": failed_pairs,
        "source_mutation_count": source_mutation_count,
        "language_mixing_failure_count": language_mixing_failure_count,
        "failure_type_counts": failure_type_counts,
        "updated_at": utc_now(),
    }


def pair_delta(before: dict[str, Any], after: dict[str, Any], key: str) -> int:
    return int(after.get(key, 0) or 0) - int(before.get(key, 0) or 0)


def cycle_throughput(before: dict[str, Any], after: dict[str, Any], started: float, finished: float) -> dict[str, Any]:
    elapsed_seconds = max(finished - started, 0.001)
    accepted_delta = pair_delta(before, after, "accepted_pairs")
    failed_delta = pair_delta(before, after, "failed_pairs")
    return {
        "cycle_elapsed_seconds": round(elapsed_seconds, 2),
        "cycle_accepted_delta": accepted_delta,
        "cycle_failed_delta": failed_delta,
        "cycle_accepted_per_hour": round((accepted_delta / elapsed_seconds) * 3600, 2),
        "cycle_failed_per_hour": round((failed_delta / elapsed_seconds) * 3600, 2),
        "cumulative_accepted_pairs": int(after.get("accepted_pairs", 0) or 0),
        "cumulative_failed_pairs": int(after.get("failed_pairs", 0) or 0),
        "cumulative_required_pairs": int(after.get("required_pairs", 0) or 0),
    }


def cycle_throughput_from_results(
    after: dict[str, Any],
    cycle_results: list[dict[str, Any]],
    started: float,
    finished: float,
) -> dict[str, Any]:
    elapsed_seconds = max(finished - started, 0.001)
    accepted_delta = sum(
        int(result.get("run_accepted_pairs", 0) or 0) for result in cycle_results
    )
    failed_delta = sum(int(result.get("run_failed_pairs", 0) or 0) for result in cycle_results)
    attempted_delta = sum(
        int(result.get("run_attempted_pairs", 0) or 0) for result in cycle_results
    )
    return {
        "cycle_elapsed_seconds": round(elapsed_seconds, 2),
        "cycle_attempted_delta": attempted_delta,
        "cycle_accepted_delta": accepted_delta,
        "cycle_failed_delta": failed_delta,
        "cycle_accepted_per_hour": round((accepted_delta / elapsed_seconds) * 3600, 2),
        "cycle_failed_per_hour": round((failed_delta / elapsed_seconds) * 3600, 2),
        "cycle_attempted_per_hour": round((attempted_delta / elapsed_seconds) * 3600, 2),
        "cumulative_accepted_pairs": int(after.get("accepted_pairs", 0) or 0),
        "cumulative_failed_pairs": int(after.get("failed_pairs", 0) or 0),
        "cumulative_required_pairs": int(after.get("required_pairs", 0) or 0),
    }


def speed_stoplight(summary: dict[str, Any], cycle_results: list[dict[str, Any]]) -> str:
    if int(summary.get("source_mutation_count", 0) or 0) > 0:
        return "RED_STOP_REQUIRED"
    current_language_mixing = sum(
        int(result.get("language_mixing_failure_delta", 0) or 0) for result in cycle_results
    )
    if current_language_mixing > 0:
        return "YELLOW_BACKOFF"
    if any(result.get("backoff") for result in cycle_results):
        return "YELLOW_BACKOFF"
    if int(summary.get("failed_pairs", 0) or 0) > 0 and all(
        int(result.get("summary", {}).get("accepted_pairs", 0) or 0) == 0 for result in cycle_results
    ):
        return "YELLOW_BACKOFF"
    return "GREEN"


def write_live_speed_report(
    campaign_root: Path,
    site: str,
    cycle: int,
    summary: dict[str, Any],
    throughput: dict[str, Any],
    cycle_results: list[dict[str, Any]],
) -> dict[str, Any]:
    report = {
        "site_id": site,
        "cycle": cycle,
        "updated_at": utc_now(),
        "stoplight": speed_stoplight(summary, cycle_results),
        "summary": summary,
        "throughput": throughput,
        "language_mixing_failure_count": summary.get("language_mixing_failure_count", 0),
        "cycle_language_mixing_failure_delta": sum(
            int(result.get("language_mixing_failure_delta", 0) or 0) for result in cycle_results
        ),
        "cycle_attempted_delta": sum(
            int(result.get("run_attempted_pairs", 0) or 0) for result in cycle_results
        ),
        "cycle_run_failure_type_counts": aggregate_run_failure_type_counts(cycle_results),
        "failure_type_counts": summary.get("failure_type_counts", {}),
        "source_mutation_count": summary.get("source_mutation_count", 0),
        "latest_vram": [result.get("vram_after") for result in cycle_results],
        "backoff_events": [result.get("backoff") for result in cycle_results if result.get("backoff")],
    }
    write_json(campaign_root / "final" / f"live-speed-report.{site}.json", report)
    return report


def aggregate_run_failure_type_counts(cycle_results: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in cycle_results:
        for failure_type, count in (result.get("run_failure_type_counts") or {}).items():
            counts[failure_type] = counts.get(failure_type, 0) + int(count)
    return counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="aspose_org_multisite_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    parser.add_argument("--python")
    parser.add_argument("--content-root", type=Path, default=DEFAULT_CONTENT)
    parser.add_argument("--device", default="cuda", choices=["cuda", "cpu", "auto"])
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--model-batch-size", type=int, default=0)
    parser.add_argument("--throughput-profile", choices=["safe", "fast", "max-vram"], default="safe")
    parser.add_argument("--target-vram-percent", type=int, default=80)
    parser.add_argument("--max-concurrent-site-workers", type=int, default=1)
    parser.add_argument("--work-order", choices=["failed-first", "short-first", "balanced"], default="failed-first")
    parser.add_argument("--max-cycles", type=int, default=200)
    parser.add_argument("--timeout-seconds", type=int, default=1200)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--sample-only", action="store_true")
    parser.add_argument("--pilot-mode", action="store_true")
    parser.add_argument("--shard-locales", action="store_true")
    parser.add_argument("--skip-baseline", action="store_true")
    parser.add_argument("--only-site", choices=SITES)
    parser.add_argument("--skip-hugo-build", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--model", default="m2m100_418m")
    args = parser.parse_args()
    if args.target_vram_percent <= 0 or args.target_vram_percent > 100:
        raise SystemExit("--target-vram-percent must be between 1 and 100")
    if args.max_concurrent_site_workers < 1:
        raise SystemExit("--max-concurrent-site-workers must be at least 1")

    if not GOVERNED_RUNNER.exists():
        raise SystemExit(f"Governed runner missing: {GOVERNED_RUNNER}")
    python = find_python(args.python)
    os.environ["ASPOSE_ORG_CONTENT"] = str(args.content_root)
    campaign_root = ROOT / ".local" / "evidences" / "aspose-org-multisite" / args.run_id
    logs = campaign_root / "logs"
    report_path = campaign_root / "final" / "campaign-report.json"

    report: dict[str, Any] = {
        "run_id": args.run_id,
        "started_at": utc_now(),
        "sites": {},
        "device": args.device,
        "throughput_profile": args.throughput_profile,
        "target_vram_percent": args.target_vram_percent,
        "max_concurrent_site_workers": args.max_concurrent_site_workers,
        "work_order": args.work_order,
        "content_root": str(args.content_root),
        "final_verdict": "RUNNING",
    }
    write_json(report_path, report)

    selected_sites = [args.only_site] if args.only_site else SITES
    for site in selected_sites:
        base = [
            str(python),
            str(GOVERNED_RUNNER),
            "--site",
            site,
            "--run-id",
            args.run_id,
            "--content-root",
            str(args.content_root / site),
            "--device",
            args.device,
            "--python",
            str(python),
            "--timeout-seconds",
            str(args.timeout_seconds),
        ]
        if args.resume:
            base.append("--resume")
        if args.model and args.model != "m2m100_418m":
            base.extend(["--model", args.model])
        selected_model_batch_size = args.model_batch_size or PROFILE_MODEL_BATCH_SIZE[args.throughput_profile]
        if selected_model_batch_size:
            base.extend(["--model-batch-size", str(selected_model_batch_size)])
        base.extend(["--work-order", args.work_order])

        if args.skip_baseline:
            summary = site_summary(args.run_id, site)
            report["sites"][site] = {
                "validate_exit_code": "SKIPPED_EXISTING_BASELINE",
                "validate_summary": summary,
            }
            write_json(report_path, report)
            if args.validate_only:
                continue
        else:
            validate_cmd = base + ["--validate-only", "--sample-plan"]
            code = run_cmd(validate_cmd, logs / site / "validate-only.log", timeout=args.timeout_seconds)
            summary = site_summary(args.run_id, site)
            report["sites"][site] = {"validate_exit_code": code, "validate_summary": summary}
            write_json(report_path, report)
            if code != 0:
                report["final_verdict"] = "REJECTED"
                report["blocker"] = f"{site} validate-only failed"
                report["finished_at"] = utc_now()
                write_json(report_path, report)
                return code
            if args.validate_only:
                continue

        if args.sample_only:
            code = run_cmd(
                base
                + [
                    "--resume",
                    "--retry-failed",
                    "--failed-first",
                    "--sample-only",
                    "--sample-plan",
                ],
                logs / site / "sample-only.log",
                timeout=None,
            )
            summary = site_summary(args.run_id, site)
            report["sites"][site]["sample_only_exit_code"] = code
            report["sites"][site]["sample_only_summary"] = summary
            write_json(report_path, report)
            if code != 0:
                report["final_verdict"] = "REJECTED"
                report["blocker"] = f"{site} sample-only run failed"
                report["finished_at"] = utc_now()
                write_json(report_path, report)
                return code
        else:
            stagnant = 0
            last_counts = (summary.get("accepted_pairs"), summary.get("failed_pairs"))
            locale_shards = compute_locale_shards(site)
            shard_model_batches = {
                shard_id: selected_model_batch_size for shard_id, _locales in locale_shards
            }
            for cycle in range(1, args.max_cycles + 1):
                cycle_started = time.monotonic()
                before_summary = site_summary(args.run_id, site)
                if args.shard_locales:
                    cycle_results = []
                    for shard_id, locales in locale_shards:
                        shard_batch = shard_model_batches.get(shard_id, selected_model_batch_size)
                        shard_summary_path = (
                            ROOT / ".local" / "evidences" / site / args.run_id / "final" / f"summary.{shard_id}.json"
                        )
                        shard_before_summary = read_json(shard_summary_path, {})
                        cycle_cmd = base + [
                            "--resume",
                            "--retry-failed",
                            "--failed-first",
                            "--max-work-items",
                            str(args.batch_size),
                            "--only-locales",
                            locales,
                            "--shard-id",
                            shard_id,
                            "--sample-plan",
                        ]
                        if shard_batch and "--model-batch-size" not in cycle_cmd:
                            cycle_cmd.extend(["--model-batch-size", str(shard_batch)])
                        elif shard_batch and "--model-batch-size" in cycle_cmd:
                            idx = cycle_cmd.index("--model-batch-size")
                            cycle_cmd[idx + 1] = str(shard_batch)
                        log_path = logs / site / f"cycle-{cycle:04d}-{shard_id}.log"
                        vram_before = wait_for_vram_below(args.target_vram_percent, log_path)
                        code = run_cmd(
                            cycle_cmd,
                            log_path,
                            timeout=None,
                        )
                        shard_summary = read_json(
                            shard_summary_path,
                            {},
                        )
                        language_mixing_delta = int(
                            shard_summary.get("run_language_mixing_failure_count", 0) or 0
                        )
                        vram_after = query_vram_snapshot()
                        backoff = None
                        if log_contains_cuda_oom(log_path) and shard_batch and shard_batch > 1:
                            new_batch = max(1, shard_batch // 2)
                            shard_model_batches[shard_id] = new_batch
                            backoff = {
                                "reason": "CUDA_OOM",
                                "old_model_batch_size": shard_batch,
                                "new_model_batch_size": new_batch,
                            }
                        elif language_mixing_delta > 3 and shard_batch and shard_batch > 1:
                            new_batch = max(1, shard_batch // 2)
                            shard_model_batches[shard_id] = new_batch
                            backoff = {
                                "reason": "LANGUAGE_MIXING_FAILURES",
                                "old_model_batch_size": shard_batch,
                                "new_model_batch_size": new_batch,
                                "language_mixing_failure_delta": language_mixing_delta,
                                "language_mixing_failure_count": shard_summary.get("language_mixing_failure_count"),
                            }
                        cycle_results.append(
                            {
                                "shard_id": shard_id,
                                "locales": locales,
                                "exit_code": code,
                                "model_batch_size": shard_batch,
                                "vram_before": vram_before,
                                "vram_after": vram_after,
                                "backoff": backoff,
                                "language_mixing_failure_delta": language_mixing_delta,
                                "run_attempted_pairs": shard_summary.get("run_attempted_pairs", 0),
                                "run_accepted_pairs": shard_summary.get("run_accepted_pairs", 0),
                                "run_failed_pairs": shard_summary.get("run_failed_pairs", 0),
                                "run_failure_type_counts": shard_summary.get("run_failure_type_counts", {}),
                                "summary": shard_summary,
                            }
                        )
                        if code != 0:
                            break
                    code = max(result["exit_code"] for result in cycle_results)
                else:
                    cycle_results = []
                    cycle_cmd = base + [
                        "--resume",
                        "--retry-failed",
                        "--failed-first",
                        "--max-work-items",
                        str(args.batch_size),
                        "--sample-plan",
                    ]
                    log_path = logs / site / f"cycle-{cycle:04d}.log"
                    vram_before = wait_for_vram_below(args.target_vram_percent, log_path)
                    code = run_cmd(cycle_cmd, log_path, timeout=None)
                    run_summary = site_summary(args.run_id, site)
                    cycle_results.append(
                        {
                            "exit_code": code,
                            "model_batch_size": selected_model_batch_size,
                            "vram_before": vram_before,
                            "vram_after": query_vram_snapshot(),
                            "language_mixing_failure_delta": run_summary.get(
                                "run_language_mixing_failure_count", 0
                            ),
                            "run_attempted_pairs": run_summary.get("run_attempted_pairs", 0),
                            "run_accepted_pairs": run_summary.get("run_accepted_pairs", 0),
                            "run_failed_pairs": run_summary.get("run_failed_pairs", 0),
                            "run_failure_type_counts": run_summary.get(
                                "run_failure_type_counts", {}
                            ),
                        }
                    )
                cycle_finished = time.monotonic()
                summary = site_summary(args.run_id, site)
                throughput = cycle_throughput_from_results(
                    summary, cycle_results, cycle_started, cycle_finished
                )
                live_report = write_live_speed_report(
                    campaign_root,
                    site,
                    cycle,
                    summary,
                    throughput,
                    cycle_results,
                )
                report["sites"][site].setdefault("cycles", []).append(
                    {
                        "cycle": cycle,
                        "exit_code": code,
                        "shards": cycle_results,
                        "summary": summary,
                        "throughput": throughput,
                        "stoplight": live_report["stoplight"],
                        "at": utc_now(),
                    }
                )
                write_json(report_path, report)
                if code != 0:
                    report["final_verdict"] = "REJECTED"
                    report["blocker"] = f"{site} cycle {cycle} failed"
                    report["finished_at"] = utc_now()
                    write_json(report_path, report)
                    return code
                counts = (summary.get("accepted_pairs"), summary.get("failed_pairs"))
                if counts == last_counts:
                    stagnant += 1
                else:
                    stagnant = 0
                last_counts = counts
                if summary.get("accepted_pairs") == summary.get("required_pairs") and summary.get("failed_pairs") == 0:
                    break
                if stagnant >= 3:
                    report["final_verdict"] = "ACCEPTED_WITH_KNOWN_BLOCKERS"
                    report["blocker"] = f"{site} made no checkpoint progress for three consecutive cycles"
                    report["finished_at"] = utc_now()
                    write_json(report_path, report)
                    return 2

        if args.shard_locales:
            reverify_results = []
            for shard_id, locales in compute_locale_shards(site):
                reverify_cmd = base + [
                    "--resume",
                    "--reverify-accepted",
                    "--reverify-dry-run",
                    "--only-locales",
                    locales,
                    "--shard-id",
                    shard_id,
                ]
                shard_code = run_cmd(
                    reverify_cmd,
                    logs / site / f"accepted-reverify-dry-run-{shard_id}.log",
                    timeout=args.timeout_seconds,
                )
                shard_report_path = (
                    ROOT
                    / ".local"
                    / "evidences"
                    / site
                    / args.run_id
                    / "final"
                    / f"accepted-reverification.{shard_id}.json"
                )
                reverify_results.append(
                    {
                        "shard_id": shard_id,
                        "locales": locales,
                        "exit_code": shard_code,
                        "report": read_json(shard_report_path, {}),
                    }
                )
            code = max(result["exit_code"] for result in reverify_results)
            report["sites"][site]["reverify_exit_code"] = code
            report["sites"][site]["reverify_results"] = reverify_results
        else:
            reverify_cmd = base + ["--resume", "--reverify-accepted", "--reverify-dry-run"]
            code = run_cmd(reverify_cmd, logs / site / "accepted-reverify-dry-run.log", timeout=args.timeout_seconds)
            report["sites"][site]["reverify_exit_code"] = code
            report["sites"][site]["reverify_report"] = read_json(
                ROOT / ".local" / "evidences" / site / args.run_id / "final" / "accepted-reverification.json",
                {},
            )
        write_json(report_path, report)
        if code != 0:
            report["final_verdict"] = "REJECTED"
            report["blocker"] = f"{site} accepted reverify failed"
            report["finished_at"] = utc_now()
            write_json(report_path, report)
            return code

    if not args.skip_hugo_build:
        content_repo = args.content_root.parent
        for site, config in HUGO_CONFIGS.items():
            code = run_cmd(["hugo", "--config", config], logs / site / "hugo-build.log", cwd=content_repo, timeout=args.timeout_seconds)
            report["sites"].setdefault(site, {})["hugo_build_exit_code"] = code
            write_json(report_path, report)
            if code != 0:
                report["final_verdict"] = "REJECTED"
                report["blocker"] = f"{site} Hugo build failed"
                report["finished_at"] = utc_now()
                write_json(report_path, report)
                return code

    if args.validate_only:
        report["final_verdict"] = "VALIDATION_BASELINE_COMPLETE"
    elif args.pilot_mode:
        pilot_ok = all(
            bool(report["sites"].get(site, {}).get("cycles"))
            and site_summary(args.run_id, site).get("failed_pairs") == 0
            and site_summary(args.run_id, site).get("source_mutation_count") == 0
            and site_summary(args.run_id, site).get("language_mixing_failure_count", 0) == 0
            for site in selected_sites
        )
        report["final_verdict"] = "PILOT_ACCEPTED" if pilot_ok else "PILOT_REJECTED"
    else:
        accepted = all(
            site_summary(args.run_id, site).get("accepted_pairs")
            == site_summary(args.run_id, site).get("required_pairs")
            and site_summary(args.run_id, site).get("failed_pairs") == 0
            and site_summary(args.run_id, site).get("source_mutation_count") == 0
            for site in selected_sites
        )
        report["final_verdict"] = "ACCEPTED" if accepted else "REJECTED"
    report["finished_at"] = utc_now()
    write_json(report_path, report)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["final_verdict"] in {"ACCEPTED", "VALIDATION_BASELINE_COMPLETE", "PILOT_ACCEPTED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
