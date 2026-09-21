"""Render receipt-backed portfolio progress for launcher and PowerShell watch."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from src.workers.campaign_manifest import CampaignManifest

try:  # Package execution (`python -m`) and direct script execution are both supported.
    from scripts.campaign.throughput_slo import ThroughputPolicy, evaluate_throughput
except ModuleNotFoundError:  # pragma: no cover - exercised by the CLI smoke command
    from throughput_slo import ThroughputPolicy, evaluate_throughput


def rows(path: Path):
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def receipt_digest(receipt: dict) -> str:
    return str(
        receipt.get("receipt_sha256")
        or hashlib.sha256(
            json.dumps(receipt, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
    )


def current_run_progress(state: dict, now: float, remaining: int) -> dict:
    elapsed = float(state.get("elapsed_seconds") or 0)
    accepted = int(state.get("accepted_current_run") or 0)
    updated = float(state.get("updated_at") or 0)
    fresh = state.get("status") == "RUNNING" and 0 <= now - updated <= 120
    rate = accepted * 60 / elapsed if fresh and elapsed > 0 else None
    return {"session_id": state.get("session_id"), "status": state.get("status", "UNKNOWN"),
            "accepted": accepted, "rejected": int(state.get("rejected_current_run") or 0),
            "fresh": fresh, "rate_per_minute": rate,
            "eta_minutes": remaining / rate if rate else None,
            "pause_reason": state.get("reason")}


def rolling_receipt_rate(receipts: list[dict], *, now: float, window_seconds: int = 900) -> dict:
    """Compute a current-window rate; never let historical downtime inflate ETA."""
    cutoff = now - window_seconds
    recent = []
    for receipt in receipts:
        value = receipt.get("accepted_at")
        if not value:
            continue
        try:
            stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
        if stamp >= cutoff:
            recent.append(stamp)
    rate = len(recent) * 60.0 / window_seconds
    return {"window_seconds": window_seconds, "accepted": len(recent), "rate_per_minute": round(rate, 3)}


def live_llm_slots(path: Path, capacity: int = 0) -> dict[str, int]:
    """Read slot occupancy without mutating the shared semaphore file."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"active": 0, "capacity": capacity}
    now = datetime.now(timezone.utc).timestamp()
    slots = payload.get("slots", {}) or {}
    active = 0
    for slot in slots.values():
        try:
            expires = datetime.fromisoformat(str(slot.get("expires_at", "")).replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
        if expires > now:
            active += 1
    return {"active": active, "capacity": int(payload.get("capacity", 0) or capacity)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--ledger-root", type=Path, default=Path("data/campaigns"))
    parser.add_argument("--spool", type=Path)
    parser.add_argument("--llm-slots", type=Path, default=Path("data/campaigns/llm_slots.json"))
    parser.add_argument("--llm-slot-capacity", type=int, default=0)
    parser.add_argument("--slo-target-per-hour", type=float, default=600.0)
    parser.add_argument("--slo-max-eta-minutes", type=float, default=1440.0)
    parser.add_argument("--slo-max-provider-calls-per-hour", type=float, default=3600.0)
    parser.add_argument("--slo-min-rate-per-hour", type=float, default=60.0)
    args = parser.parse_args()
    manifest = CampaignManifest.load(args.manifest)
    root = args.ledger_root / manifest.campaign_id
    receipts = {str(row.get("output_path")): row for row in rows(root / "acceptance_receipts.jsonl")}
    failures = rows(root / "failure_metadata.jsonl")
    committed_receipts: set[tuple[str, str]] = set()
    for batch in rows(root / "commit_batches.jsonl"):
        if batch.get("status") == "COMMITTED":
            committed_receipts.update(
                zip(
                    (str(path) for path in batch.get("outputs", [])),
                    (str(value) for value in batch.get("receipt_hashes", [])),
                )
            )
    committed = sum(
        (output, receipt_digest(receipt)) in committed_receipts
        for output, receipt in receipts.items()
    )
    metrics = {key: 0 for key in ("i18n_hits", "tm_hits", "l1_hits", "l2_hits", "semantic_tm_hits", "professionalize_calls", "ast_batches", "individual_fallback_batches", "validation_retries")}
    for receipt in receipts.values():
        for key in metrics:
            metrics[key] += int((receipt.get("translation_stats") or {}).get(key, 0) or 0)
    accepted = len(receipts)
    accepted_times = sorted(str(r.get("accepted_at")) for r in receipts.values() if r.get("accepted_at"))
    rate = 0.0
    if len(accepted_times) > 1:
        start = datetime.fromisoformat(accepted_times[0].replace("Z", "+00:00"))
        end = datetime.fromisoformat(accepted_times[-1].replace("Z", "+00:00"))
        minutes = (end - start).total_seconds() / 60
        if minutes > 0:
            rate = accepted / minutes
    spool = {"PENDING": None, "CLAIMED": None, "APPLIED": None, "FAILED": None}
    if args.spool and args.spool.is_file():
        spool = dict.fromkeys(spool, 0)
        with sqlite3.connect(args.spool) as conn:
            for state, count in conn.execute("select state, count(*) from tm_intents group by state"):
                spool[str(state)] = count
    remaining = max(0, manifest.expected_output_count - accepted)
    elapsed_seconds = 0.0
    if len(accepted_times) > 1:
        elapsed_seconds = max((end - start).total_seconds(), 0.0)
    throughput = evaluate_throughput(
        accepted=accepted,
        remaining=remaining,
        elapsed_seconds=elapsed_seconds,
        provider_calls=metrics["professionalize_calls"],
        policy=ThroughputPolicy(
            target_outputs_per_hour=args.slo_target_per_hour,
            max_eta_minutes=args.slo_max_eta_minutes,
            max_provider_calls_per_hour=args.slo_max_provider_calls_per_hour,
            min_rate_per_hour=args.slo_min_rate_per_hour,
        ),
    )
    payload = {"campaign": manifest.campaign_id, "accepted": accepted, "failures": len(failures), "rate_per_minute": round(rate, 3), "remaining": remaining, "eta_minutes": round(remaining / rate, 1) if rate else None, "committed": committed, "pending_commit": max(0, accepted-committed), "spool": spool, "metrics": metrics, "throughput": throughput}
    payload["rolling_15m"] = rolling_receipt_rate(receipts.values(), now=time.time())
    payload["llm_slots"] = live_llm_slots(args.llm_slots, args.llm_slot_capacity)
    state_path = root / "watchdog_state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        state = {}
    current = current_run_progress(state, time.time(), remaining)
    payload["schema_version"] = 2
    payload["historical_rate_per_minute"] = payload["rate_per_minute"]
    payload["rate_per_minute"] = current["rate_per_minute"]
    payload["eta_minutes"] = current["eta_minutes"]
    payload["current_run"] = current
    throughput["measurement_scope"] = "historical_receipts_only_includes_downtime_excludes_rejected_calls"
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
