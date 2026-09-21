"""Bounded single-writer entrypoint for durable TM intents.

Reader workers append to ``TMIntentSpool``.  This module is the explicit
operator/worker entrypoint that alone opens canonical L2 in write mode and,
when enabled, persists L3 after a batch.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from src.tm.intent_spool import TMIntentSpool, TMIntentWriter
from src.tm.l2_persistent import L2_DB_NAME, L2PersistentTM
from src.tm.lmdb_registry import set_project_root


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply bounded TM intents through the single writer.")
    parser.add_argument("--repository-root", required=True)
    parser.add_argument("--config-root", default="config")
    parser.add_argument("--spool-path", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--owner", default=None)
    parser.add_argument("--no-l3", action="store_true", help="Apply only L2; intended for recovery/testing.")
    parser.add_argument(
        "--reconcile",
        action="store_true",
        help=(
            "Repair L3 entries for intents already marked APPLIED instead of "
            "draining PENDING/expired-CLAIMED work. Recovers from a prior "
            "writer crash between spool.complete() and the batch's trailing "
            "save_index() call, without duplicating entries L3 already has."
        ),
    )
    return parser.parse_args(argv)


def load_tm_writer_config(config_root: Path) -> dict:
    defaults = {
        "enabled": False,
        "intent_spool_path": "data/tm/intent_spool.sqlite3",
        "l3_enabled": True,
        "batch_limit": 50,
        "lease_seconds": 300.0,
    }
    path = Path(config_root) / "global.yaml"
    if not path.is_file():
        raise ValueError(f"TM writer config missing: {path}")
    configured = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("tm_writer", {})
    if not isinstance(configured, dict):
        raise ValueError("tm_writer must be a mapping")
    result = {**defaults, **configured}
    if not isinstance(result["l3_enabled"], bool) or int(result["batch_limit"]) < 1:
        raise ValueError("tm_writer.l3_enabled must be boolean and batch_limit positive")
    if float(result["lease_seconds"]) <= 0:
        raise ValueError("tm_writer.lease_seconds must be positive")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = load_tm_writer_config(Path(args.config_root))
    limit = args.limit if args.limit is not None else int(config["batch_limit"])
    if limit < 1:
        raise ValueError("--limit must be positive")
    root = Path(args.repository_root).resolve()
    set_project_root(root)
    spool = TMIntentSpool(Path(args.spool_path or config["intent_spool_path"]))
    l2 = L2PersistentTM(root / "data" / "tm" / L2_DB_NAME)
    l3 = None
    try:
        if not args.no_l3 and config["l3_enabled"]:
            from src.tm.l3_semantic import L3SemanticTM

            l3 = L3SemanticTM(index_path=root / "data" / "tm" / "l3_index", use_gpu=False)
        writer = TMIntentWriter(spool, l2, l3)
        result = (
            writer.reconcile_l3(limit=limit if args.limit is not None else None)
            if args.reconcile
            else writer.run_once(limit=limit, owner=args.owner, lease_seconds=float(config["lease_seconds"]))
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    finally:
        l2.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
