"""Render receipt-backed portfolio progress for launcher and PowerShell watch."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from src.workers.campaign_manifest import CampaignManifest


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--ledger-root", type=Path, default=Path("data/campaigns"))
    parser.add_argument("--spool", type=Path)
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
        with sqlite3.connect(args.spool) as conn:
            for state, count in conn.execute("select state, count(*) from tm_intents group by state"):
                spool[str(state)] = count
    remaining = max(0, manifest.expected_output_count - accepted)
    payload = {"campaign": manifest.campaign_id, "accepted": accepted, "failures": len(failures), "rate_per_minute": round(rate, 3), "remaining": remaining, "eta_minutes": round(remaining / rate, 1) if rate else None, "committed": committed, "pending_commit": max(0, accepted-committed), "spool": spool, "metrics": metrics}
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
