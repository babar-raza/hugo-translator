#!/usr/bin/env python3
"""Unattended production wrapper for products.aspose.org governed retranslation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
GOVERNED_RUNNER = ROOT / "scripts" / "quality" / "products_org_governed_retranslate.py"
DEFAULT_CONTENT = Path(r"C:\Users\prora\OneDrive\Documents\GitHub\aspose.org\content")
SIBLING_PYTHON = Path(r"C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\.venv\Scripts\python.exe")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def acquire_lock(lock_path: Path) -> int:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(str(lock_path), flags)
    except FileExistsError as exc:
        existing = lock_path.read_text(encoding="utf-8", errors="replace") if lock_path.exists() else ""
        raise SystemExit(f"Run lock already exists: {lock_path}\n{existing}") from exc
    os.write(fd, f"pid={os.getpid()}\nstarted_at={utc_now()}\n".encode("utf-8"))
    os.fsync(fd)
    return fd


def release_lock(fd: int, lock_path: Path) -> None:
    try:
        os.close(fd)
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def find_python(explicit: str | None) -> Path:
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    candidates.extend(
        [
            ROOT / ".venv" / "Scripts" / "python.exe",
            SIBLING_PYTHON,
            Path(sys.executable),
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise SystemExit("No usable Python interpreter found. Provide --python.")


def ensure_content_root() -> Path:
    raw = os.environ.get("ASPOSE_ORG_CONTENT")
    content = Path(raw) if raw else DEFAULT_CONTENT
    products_root = content / "products.aspose.org"
    if not products_root.exists():
        raise SystemExit(
            "products.aspose.org content root not found. Set ASPOSE_ORG_CONTENT to the directory containing products.aspose.org."
        )
    os.environ["ASPOSE_ORG_CONTENT"] = str(content)
    return products_root


def source_hash_snapshot(products_root: Path) -> dict[str, str]:
    en_root = products_root / "en"
    if not en_root.exists():
        raise SystemExit(f"English source root not found: {en_root}")
    return {
        str(path.relative_to(products_root)).replace("\\", "/"): sha256_file(path)
        for path in sorted(en_root.rglob("*.md"))
    }


def run_cmd(cmd: list[str], log_path: Path, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = utc_now()
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\n## START {started}\n")
        log.write(" ".join(cmd) + "\n")
        log.flush()
        try:
            result = subprocess.run(
                cmd,
                cwd=ROOT,
                env=os.environ.copy(),
                text=True,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            log.write(f"## TIMEOUT {utc_now()} timeout={timeout} error={exc!r}\n")
            result = subprocess.CompletedProcess(cmd, 124)
        log.write(f"## END {utc_now()} exit={result.returncode}\n")
    return result


def checkpoint_counts(evidence_root: Path) -> dict[str, int]:
    checkpoint = read_json(evidence_root / "checkpoints" / "checkpoint.json", {"accepted": {}, "failed": {}})
    return {
        "accepted": len(checkpoint.get("accepted", {})),
        "failed": len(checkpoint.get("failed", {})),
    }


def latest_summary(evidence_root: Path) -> dict[str, Any]:
    summaries = sorted((evidence_root / "final").glob("summary*.json"))
    if not summaries:
        return {}
    return read_json(summaries[-1], {})


def required_pair_count(evidence_root: Path) -> int:
    inventory = read_json(evidence_root / "baseline" / "inventory.json", [])
    return len(inventory)


def governed_base(python: Path, args: argparse.Namespace) -> list[str]:
    return [
        str(python),
        str(GOVERNED_RUNNER),
        "--run-id",
        args.run_id,
        "--device",
        args.device,
        "--timeout-seconds",
        str(args.timeout_seconds),
        "--python",
        str(python),
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="products_org_unattended_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    parser.add_argument("--python")
    parser.add_argument("--device", default="cuda", choices=["cuda", "cpu", "auto"])
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--max-cycles", type=int, default=200)
    parser.add_argument("--timeout-seconds", type=int, default=1200)
    parser.add_argument("--sleep-seconds", type=int, default=5)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    if not GOVERNED_RUNNER.exists():
        raise SystemExit(f"Governed runner missing: {GOVERNED_RUNNER}")

    python = find_python(args.python)
    products_root = ensure_content_root()
    evidence_root = ROOT / ".local" / "evidences" / f"hugo-translator-retranslation-{args.run_id}"
    wrapper_logs = evidence_root / "logs" / "unattended"
    final_report = evidence_root / "final" / "unattended-report.json"
    lock_path = evidence_root / "locks" / "unattended.lock"
    lock_fd = acquire_lock(lock_path)

    try:
        before_hashes = source_hash_snapshot(products_root)
        write_json(evidence_root / "baseline" / "source-hashes-before.json", before_hashes)

        report: dict[str, Any] = {
            "run_id": args.run_id,
            "started_at": utc_now(),
            "repo_root": str(ROOT),
            "products_root": str(products_root),
            "python": str(python),
            "device": args.device,
            "batch_size": args.batch_size,
            "max_cycles": args.max_cycles,
            "events": [],
            "final_verdict": "RUNNING",
        }
        write_json(final_report, report)

        base = governed_base(python, args)
        steps = [
            ("plan", base + ["--plan-only"], not args.resume),
            ("reverify_accepted", base + ["--resume", "--reverify-accepted"], True),
        ]
        for name, cmd, should_run in steps:
            if not should_run:
                continue
            result = run_cmd(cmd, wrapper_logs / f"{name}.log", timeout=args.timeout_seconds)
            report["events"].append({"step": name, "exit_code": result.returncode, "at": utc_now()})
            write_json(final_report, report)
            if result.returncode != 0:
                report["final_verdict"] = "REJECTED"
                report["blocker"] = f"{name} failed; see {wrapper_logs / (name + '.log')}"
                report["finished_at"] = utc_now()
                write_json(final_report, report)
                return result.returncode

        total_required_pairs = required_pair_count(evidence_root)
        if total_required_pairs <= 0:
            report["final_verdict"] = "REJECTED"
            report["blocker"] = "Baseline inventory is missing or empty; cannot prove full products.org coverage."
            report["finished_at"] = utc_now()
            write_json(final_report, report)
            return 1
        report["total_required_pairs"] = total_required_pairs
        write_json(final_report, report)

        last_counts = checkpoint_counts(evidence_root)
        stagnant_cycles = 0
        for cycle in range(1, args.max_cycles + 1):
            cmd = base + [
                "--resume",
                "--retry-failed",
                "--failed-first",
                "--max-work-items",
                str(args.batch_size),
            ]
            result = run_cmd(cmd, wrapper_logs / f"cycle-{cycle:04d}.log", timeout=None)
            counts = checkpoint_counts(evidence_root)
            summary = latest_summary(evidence_root)
            report["events"].append(
                {
                    "step": "retry_cycle",
                    "cycle": cycle,
                    "exit_code": result.returncode,
                    "counts": counts,
                    "batch_remaining_pairs": summary.get("remaining_pairs"),
                    "campaign_remaining_pairs": max(total_required_pairs - counts["accepted"], 0),
                    "at": utc_now(),
                }
            )
            write_json(final_report, report)
            if result.returncode != 0:
                report["final_verdict"] = "REJECTED"
                report["blocker"] = f"retry cycle {cycle} failed; see {wrapper_logs / f'cycle-{cycle:04d}.log'}"
                report["finished_at"] = utc_now()
                write_json(final_report, report)
                return result.returncode

            if counts == last_counts:
                stagnant_cycles += 1
            else:
                stagnant_cycles = 0
            last_counts = counts

            if counts["accepted"] >= total_required_pairs and counts["failed"] == 0:
                break
            if stagnant_cycles >= 3:
                report["final_verdict"] = "ACCEPTED_WITH_KNOWN_BLOCKERS"
                report["blocker"] = "No checkpoint progress for three consecutive cycles."
                report["finished_at"] = utc_now()
                write_json(final_report, report)
                return 2
            time.sleep(args.sleep_seconds)

        dry = run_cmd(
            base + ["--resume", "--reverify-accepted", "--reverify-dry-run"],
            wrapper_logs / "final-reverify-dry-run.log",
            timeout=args.timeout_seconds,
        )
        after_hashes = source_hash_snapshot(products_root)
        write_json(evidence_root / "baseline" / "source-hashes-after.json", after_hashes)
        source_mutations = {
            path: {"before": before_hashes.get(path), "after": after_hashes.get(path)}
            for path in sorted(set(before_hashes) | set(after_hashes))
            if before_hashes.get(path) != after_hashes.get(path)
        }
        write_json(evidence_root / "final" / "source-mutations.json", source_mutations)

        counts = checkpoint_counts(evidence_root)
        reverify = read_json(evidence_root / "final" / "accepted-reverification.json", {})
        summary = latest_summary(evidence_root)
        report.update(
            {
                "finished_at": utc_now(),
                "final_counts": counts,
                "total_required_pairs": total_required_pairs,
                "campaign_remaining_pairs": max(total_required_pairs - counts["accepted"], 0),
                "latest_summary": summary,
                "accepted_reverification": {
                    "exit_code": dry.returncode,
                    "accepted_checked": reverify.get("accepted_checked"),
                    "accepted_after": reverify.get("accepted_after"),
                    "failed_after": reverify.get("failed_after"),
                    "quarantined_accepts": reverify.get("quarantined_accepts"),
                    "verification_exceptions": reverify.get("verification_exceptions"),
                    "verdict_counts": reverify.get("verdict_counts"),
                },
                "source_mutation_count": len(source_mutations),
            }
        )
        if (
            dry.returncode == 0
            and counts["failed"] == 0
            and counts["accepted"] >= total_required_pairs
            and not source_mutations
            and reverify.get("verdict_counts") == {"VERIFIED_ACCEPT": counts["accepted"]}
        ):
            report["final_verdict"] = "ACCEPTED"
        else:
            report["final_verdict"] = "REJECTED"
        write_json(final_report, report)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if report["final_verdict"] == "ACCEPTED" else 1
    finally:
        release_lock(lock_fd, lock_path)


if __name__ == "__main__":
    raise SystemExit(main())
