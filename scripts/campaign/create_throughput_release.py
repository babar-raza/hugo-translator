"""Create a reviewable, immutable throughput-release artifact.

This command creates the artifact only; approval must cite a completed evidence
bundle and is deliberately an explicit operator action.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from src.workers.throughput_release import _PHASES, manifest_sha256


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--runtime-sha", required=True)
    parser.add_argument("--phase", choices=sorted(_PHASES), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--approve", action="store_true")
    parser.add_argument("--evidence-path")
    args = parser.parse_args()
    if args.approve != bool(args.evidence_path):
        parser.error("--approve and --evidence-path must be supplied together")
    limits = _PHASES[args.phase]
    payload = {
        "schema_version": 1, "campaign_id": args.campaign_id, "phase": args.phase,
        "runtime_sha": args.runtime_sha, "manifest_sha256": manifest_sha256(args.manifest),
        **limits, "approved": args.approve, "evidence_path": args.evidence_path or "",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
