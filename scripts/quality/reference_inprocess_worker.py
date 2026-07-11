#!/usr/bin/env python3
"""
In-process reference.aspose.org retranslation worker.

Loads NLLB-200-1.3B ONCE, keeps it in VRAM between files.
~15x faster than subprocess-per-file governed retranslate.

Reads MISSING_TARGET items from the main checkpoint (or per-locale shard checkpoints),
calls engine.translate_file() directly, runs verify_pair() inline, and writes results
to a new shard checkpoint.

Usage:
    python scripts/quality/reference_inprocess_worker.py
    python scripts/quality/reference_inprocess_worker.py --locales bg,ca
    python scripts/quality/reference_inprocess_worker.py --locales de --shard-id latin-de
    python scripts/quality/reference_inprocess_worker.py --retry-failed

Locales handled by default: bg, ca, cs, da, de
(ar is handled by the running latin-a campaign)
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import logging
import os
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
HUGO_DIR     = ROOT
ASPOSE_DIR   = Path("C:/Users/prora/OneDrive/Documents/GitHub/aspose.org")
CONTENT_ROOT = ASPOSE_DIR / "content" / "reference.aspose.org"
SITE_ID      = "reference.aspose.org"
RUN_ID       = "aspose_org_multisite_20260704_012331"
MODEL_ID     = "nllb_200_1.3b"
DEVICE       = "cuda"
DEFAULT_LOCALES = ["bg", "ca", "cs", "da", "de"]

LOG_DIR = HUGO_DIR / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            LOG_DIR / "reference_inprocess.log", encoding="utf-8", errors="replace"
        ),
    ],
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lazy imports (heavy deps loaded after argument parsing)
# ---------------------------------------------------------------------------
def _load_governed_imports():
    """Import governed-retranslate helpers."""
    from scripts.quality.aspose_org_governed_retranslate import (
        build_inventory_for_site,
        verify_pair,
        write_acceptance,
        write_failure,
        normalize_failed_checkpoint,
        repair_target,
        VERIFIER_POLICY_VERSION,
        policy_document,
        sort_items_for_work_order,
        count_failure_types,
        empty_run_stats,
        note_run_accept,
        note_run_failure,
    )
    from scripts.quality.products_org_governed_retranslate import (
        checkpoint_file,
        load_checkpoint,
        overlay_main_checkpoint_for_items,
        write_json,
        safe_shard_id,
        parse_locale_filter,
    )
    from src.translation_engine.parser.hugo_parser import HugoParser
    return {
        "build_inventory_for_site": build_inventory_for_site,
        "verify_pair": verify_pair,
        "write_acceptance": write_acceptance,
        "write_failure": write_failure,
        "normalize_failed_checkpoint": normalize_failed_checkpoint,
        "repair_target": repair_target,
        "VERIFIER_POLICY_VERSION": VERIFIER_POLICY_VERSION,
        "policy_document": policy_document,
        "sort_items_for_work_order": sort_items_for_work_order,
        "count_failure_types": count_failure_types,
        "empty_run_stats": empty_run_stats,
        "note_run_accept": note_run_accept,
        "note_run_failure": note_run_failure,
        "checkpoint_file": checkpoint_file,
        "load_checkpoint": load_checkpoint,
        "overlay_main_checkpoint_for_items": overlay_main_checkpoint_for_items,
        "write_json": write_json,
        "safe_shard_id": safe_shard_id,
        "parse_locale_filter": parse_locale_filter,
        "HugoParser": HugoParser,
    }


def _build_engine(config_service):
    """Build TranslationEngine with NLLB loaded in VRAM."""
    from src.model_runtime import ModelLoader
    from src.model_runtime.registry import ModelRegistry
    from src.tm import TranslationMemory
    from src.tm.l1_cache import L1Cache
    from src.tm.l2_persistent import L2PersistentTM
    from src.translation_engine import TranslationEngine

    registry = ModelRegistry(registry_path=ROOT / "config" / "model_registry.yaml")
    model_loader = ModelLoader(registry=registry, device=DEVICE)

    logger.info(f"Loading {MODEL_ID} onto {DEVICE} ...")
    t0 = time.monotonic()
    model_loader.load_model(MODEL_ID)
    elapsed = time.monotonic() - t0
    logger.info(f"Model loaded in {elapsed:.1f}s")

    l1 = L1Cache()
    try:
        from src.tm.l2_persistent import L2_DB_NAME
        l2 = L2PersistentTM(db_path=ROOT / "data" / "tm" / L2_DB_NAME)
    except Exception as e:
        logger.warning(f"L2 TM init failed (non-fatal): {e}")
        l2 = None

    tm = TranslationMemory(l1_cache=l1, l2_persistent=l2)

    engine = TranslationEngine(
        config_service=config_service,
        tm=tm,
        model_loader=model_loader,
        enable_validation=False,      # governed retranslate does its own verification
        enable_telemetry=False,
        dry_run=False,
        save_rejected=False,
        batch_size=16,
        enable_verification=False,
        enable_verification_fix=False,
        # Force NLLB 1.3B and bypass write-gate quality checks
        model_id=MODEL_ID,
        force_accept=True,
    )
    logger.info("TranslationEngine ready.")
    return engine, model_loader


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(args: argparse.Namespace) -> int:
    from scripts.quality.products_org_governed_retranslate import load_dotenv
    load_dotenv(ROOT / ".env")

    G = _load_governed_imports()
    from src.utils.config_loader import ConfigService

    config_service = ConfigService(config_root=ROOT / "config")
    profile = config_service.get_site_profile(SITE_ID)
    if profile is None:
        raise SystemExit(f"{SITE_ID} profile not found")

    content_root = CONTENT_ROOT
    locales = G["parse_locale_filter"](args.locales, list(profile.target_langs))
    shard_id = G["safe_shard_id"](args.shard_id) if args.shard_id else G["safe_shard_id"](
        "inproc-" + "-".join(locales[:3])
    )

    evidence_root = ROOT / ".local" / "evidences" / SITE_ID / RUN_ID
    checkpoint_dir = evidence_root / "checkpoints"
    checkpoint_path = G["checkpoint_file"](checkpoint_dir, shard_id)

    # Load or create checkpoint
    if args.resume and checkpoint_path.exists():
        checkpoint = G["load_checkpoint"](checkpoint_path)
    else:
        checkpoint = {"accepted": {}, "failed": {}}
    checkpoint["run_id"] = RUN_ID
    checkpoint["site_id"] = SITE_ID
    G["normalize_failed_checkpoint"](checkpoint)

    # Overlay from main checkpoint so we skip already-accepted items
    main_cp_path = G["checkpoint_file"](checkpoint_dir, None)
    items = G["build_inventory_for_site"](profile, content_root, locales)
    scoped_ids = {item.work_item_id for item in items}
    if args.resume and main_cp_path.exists():
        G["overlay_main_checkpoint_for_items"](
            checkpoint,
            G["load_checkpoint"](main_cp_path),
            scoped_ids,
        )
        G["write_json"](checkpoint_path, checkpoint)

    accepted = checkpoint.setdefault("accepted", {})
    failed   = checkpoint.setdefault("failed", {})

    # Select work items
    eligible = []
    for item in items:
        if item.work_item_id in accepted:
            continue
        if item.work_item_id in failed and not args.retry_failed:
            continue
        eligible.append(item)

    eligible = G["sort_items_for_work_order"](
        eligible, failed=failed, accepted=accepted,
        failed_first=True, work_order="failed-first",
    )

    n_total = len(eligible)
    n_missing = sum(
        1 for it in eligible
        if not Path(it.target_path).exists()
    )
    logger.info(
        f"Shard {shard_id}: {n_total} work items ({n_missing} MISSING_TARGET), "
        f"locales={locales}"
    )

    if n_total == 0:
        logger.info("Nothing to do.")
        return 0

    # ---------------------------------------------------------------------------
    # Build engine (loads NLLB once)
    # ---------------------------------------------------------------------------
    engine, model_loader = _build_engine(config_service)
    parser_obj = G["HugoParser"]()

    policy = G["policy_document"](profile, content_root, locales)
    policy_hash = hashlib.sha256(
        json.dumps(policy, sort_keys=True).encode("utf-8")
    ).hexdigest()

    run_stats = G["empty_run_stats"]()
    t_run_start = time.monotonic()

    for idx, item in enumerate(eligible, 1):
        if item.work_item_id in accepted:
            continue
        if item.work_item_id in failed and not args.retry_failed:
            continue

        source = Path(item.source_path)
        target = Path(item.target_path)
        elapsed_total = time.monotonic() - t_run_start
        rate = idx / elapsed_total if elapsed_total > 0 else 0
        eta_s  = (n_total - idx) / rate if rate > 0 else 0
        logger.info(
            f"[{idx}/{n_total}] {item.locale} {item.relative_path}  "
            f"rate={rate:.2f}/s  ETA={eta_s/60:.1f}m"
        )

        run_stats["attempted_pairs"] = int(run_stats.get("attempted_pairs", 0) or 0) + 1

        # Pre-check: if target exists, verify it first
        if target.exists():
            try:
                repairs = G["repair_target"](profile, parser_obj, source, target)
                comparison = G["verify_pair"](profile, parser_obj, source, target, item.locale)
                if comparison["verdict"] == "VERIFIED_ACCEPT":
                    G["write_acceptance"](
                        evidence_root, checkpoint_path, checkpoint, item,
                        comparison, policy_hash, "existing_translation_verified_pre_translate",
                    )
                    G["note_run_accept"](run_stats)
                    logger.info(f"  ACCEPT (pre-existing): {item.locale} {item.relative_path}")
                    continue
            except Exception as exc:
                logger.warning(f"  Pre-verify exception: {exc}")

        # Translate in-process
        try:
            result = engine.translate_file(
                site_id=SITE_ID,
                file_path=source,
                target_langs=[item.locale],
                force=True,
                validate=False,
                trigger_type="inprocess_worker",
            )
        except Exception as exc:
            logger.error(f"  translate_file exception: {exc}")
            G["write_failure"](
                evidence_root, checkpoint_path, checkpoint, item,
                "TRANSLATOR_REJECTED_OR_NO_TARGET",
                {"exception": repr(exc)},
            )
            G["note_run_failure"](run_stats, "TRANSLATOR_REJECTED_OR_NO_TARGET")
            continue

        # Check if target was written
        if not target.exists():
            logger.warning(f"  No target written for {item.locale} {item.relative_path}")
            G["write_failure"](
                evidence_root, checkpoint_path, checkpoint, item,
                "TRANSLATOR_REJECTED_OR_NO_TARGET",
                {"reason": "target_file_not_written"},
            )
            G["note_run_failure"](run_stats, "TRANSLATOR_REJECTED_OR_NO_TARGET")
            continue

        # Verify
        try:
            repairs = G["repair_target"](profile, parser_obj, source, target)
            log_path = (
                evidence_root / "per-file" / item.locale
                / item.relative_path.replace("/", "__")
            ).with_suffix(".inproc.log")
            log_path.parent.mkdir(parents=True, exist_ok=True)
            comparison = G["verify_pair"](profile, parser_obj, source, target, item.locale)
            G["write_json"](
                evidence_root / "per-file" / item.locale / f"{item.work_item_id}.comparison.json",
                comparison,
            )
        except Exception as exc:
            G["write_failure"](
                evidence_root, checkpoint_path, checkpoint, item,
                "VERIFY_EXCEPTION", {"exception": repr(exc)},
            )
            G["note_run_failure"](run_stats, "VERIFY_EXCEPTION")
            logger.warning(f"  VERIFY_EXCEPTION: {exc}")
            continue

        if comparison["verdict"] == "VERIFIED_ACCEPT":
            G["write_acceptance"](
                evidence_root, checkpoint_path, checkpoint, item,
                comparison, policy_hash, "new_translation_written",
            )
            G["note_run_accept"](run_stats)
            logger.info(f"  ACCEPT: {item.locale} {item.relative_path}")
        else:
            G["write_failure"](
                evidence_root, checkpoint_path, checkpoint, item,
                comparison["verdict"], {"comparison": comparison},
            )
            G["note_run_failure"](run_stats, comparison["verdict"])
            logger.info(f"  FAIL ({comparison['verdict']}): {item.locale} {item.relative_path}")

    # Summary
    elapsed_total = time.monotonic() - t_run_start
    n_acc = len(accepted)
    n_fail = len(failed)
    n_missing_after = G["count_failure_types"](checkpoint, scoped_ids).get("MISSING_TARGET", 0)
    logger.info(
        f"\n=== Run complete ===\n"
        f"  Elapsed: {elapsed_total/60:.1f}m\n"
        f"  Accepted: {n_acc}  Failed: {n_fail}  MISSING_TARGET: {n_missing_after}\n"
        f"  Run accepted: {run_stats.get('accepted_pairs', 0)}  "
        f"Run failed: {run_stats.get('failed_pairs', 0)}\n"
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="In-process reference retranslation worker")
    parser.add_argument(
        "--locales", default=",".join(DEFAULT_LOCALES),
        help="Comma-separated locale codes to process (default: bg,ca,cs,da,de)",
    )
    parser.add_argument(
        "--shard-id", default=None,
        help="Shard ID for checkpoint file (auto-derived from locales if not given)",
    )
    parser.add_argument(
        "--resume", action="store_true", default=True,
        help="Resume from existing shard checkpoint (default: True)",
    )
    parser.add_argument(
        "--no-resume", dest="resume", action="store_false",
        help="Start fresh (ignore existing shard checkpoint)",
    )
    parser.add_argument(
        "--retry-failed", action="store_true", default=False,
        help="Retry items currently in the failed dict",
    )
    args = parser.parse_args()
    sys.exit(run(args))


if __name__ == "__main__":
    main()
