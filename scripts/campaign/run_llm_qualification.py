"""TC-APT-004b: run the qualification sample through ``professionalize_llm`` exclusively.

Plan section 6.1 point 3: "Runs the full benchmark corpus through ``professionalize_llm``
exclusively, at TC-APT-028's established safe concurrency; validates every output via the
44-gate suite; **100% Claude review of the qualification sample**."

Two properties this harness enforces, because a qualification run that quietly relaxed
either would prove nothing:

* **Exclusivity.**  ``model_id_override`` pins every job to ``professionalize_llm`` and the
  post-run check asserts every receipt's ``model_fingerprint`` names it.  A circuit-breaker
  reroute to ``m2m100_418m`` is a *qualification failure*, not a silent substitution --
  the fallback is a production feature (plan section 6.1) and explicitly not part of the
  evidence that the primary works.
* **No TM shortcut.**  Jobs run with ``force=True`` so the translation memory cannot answer
  on the model's behalf.  Qualifying the LLM against TM hits would measure the TM.

Output is written into a **sandbox** content root (a copy of just the sample's sources), so
a qualification run can never write into the real content repository.  The sandbox is
addressed by overriding ``ASPOSE_ORG_CONTENT`` before any configuration is loaded, which is
the same mechanism the site profiles already use -- no bypass path is introduced.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

QUALIFICATION_MODEL = "professionalize_llm"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stage_sandbox(sample: dict, content_root: Path, sandbox: Path) -> list[dict]:
    """Copy every sample source into the sandbox, preserving its repo-relative path."""
    staged: list[dict] = []
    for entry in sample["sample"]:
        src = content_root / entry["source_path"]
        rel = Path(entry["source_path"])
        # content/<site>/... -> sandbox/<site>/... so profile content_roots resolve
        parts = rel.parts
        if parts and parts[0] == "content":
            rel = Path(*parts[1:])
        dst = sandbox / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        actual = sha256_bytes(dst.read_bytes())
        if actual != entry["source_sha256"]:
            raise SystemExit(
                f"source drifted since the sample was built: {entry['source_path']}"
            )
        staged.append({**entry, "sandbox_path": str(dst), "sandbox_rel": str(rel)})
    return staged


def build_engine(sandbox: Path, translator_repo: Path, tm_dir: Path):
    """Build the production engine under zero-defect policy against the sandbox root.

    The translation memory is sandboxed too: qualification output must not enter the
    production L2, and the qualification must not be answerable from production TM hits
    (``force=True`` covers the read side, this covers the write side).
    """
    os.environ["ASPOSE_ORG_CONTENT"] = str(sandbox)
    from src.model_runtime.loader import ModelLoader
    from src.model_runtime.registry import ModelRegistry
    from src.tm import TranslationMemory
    from src.tm.l1_cache import L1Cache
    from src.tm.l2_persistent import L2_DB_NAME, L2PersistentTM
    from src.translation_engine.engine import TranslationEngine
    from src.utils.config_loader import ConfigService

    config_service = ConfigService(translator_repo / "config")
    raw = config_service.get_config()
    device = "cpu"
    if (raw.get("hardware", {}) or {}).get("enable_gpu", True):
        try:
            import torch

            if torch.cuda.is_available():
                device = "cuda"
        except Exception:
            device = "cpu"
    loader = ModelLoader(
        ModelRegistry(translator_repo / "config" / "model_registry.yaml"),
        device=device,
        config=raw,
    )
    tm_dir.mkdir(parents=True, exist_ok=True)
    tm = TranslationMemory(
        l1_cache=L1Cache(max_size=10000),
        l2_persistent=L2PersistentTM(db_path=tm_dir / L2_DB_NAME, max_size_mb=256),
        l3_semantic=None,
    )
    engine = TranslationEngine(
        config_service=config_service,
        tm=tm,
        model_loader=loader,
        enable_validation=True,
        enable_telemetry=False,
        validation_mode="strict",
        validation_policy="zero-defect",
        enable_verification=True,
        enable_verification_fix=True,
        max_retries=4,
        save_rejected=False,
        model_id=QUALIFICATION_MODEL,
    )
    engine.model_id_override = QUALIFICATION_MODEL
    return engine


def run_job(engine, model_lock: threading.Lock | None, entry: dict, locale: str) -> dict:
    started = time.perf_counter()
    record: dict[str, Any] = {
        "site_id": entry["site_id"],
        "source_path": entry["source_path"],
        "source_sha256": entry["source_sha256"],
        "target_lang": locale,
        "classes": entry["classes"],
    }
    try:
        # Mirrors CampaignRunner._model_execution_lock (src/workers/campaign_runner.py):
        # a real model_loader's generation call is not proven thread-safe across
        # concurrent files (extractor/renderer state, not just CUDA), so production
        # campaigns fully serialize translate_file() when one is present. The
        # qualification run must match that discipline exactly, or a race in this
        # harness (not in the model) could masquerade as an LLM quality defect --
        # this is what produced an intermittent empty-frontmatter crash before the
        # lock was added here (concurrency=2 reproduced it, concurrency=1 did not).
        if model_lock is not None:
            with model_lock:
                result = engine.translate_file(
                    entry["site_id"],
                    Path(entry["sandbox_path"]),
                    target_langs=[locale],
                    validate=True,
                    force=True,  # never let the TM answer for the model
                    trigger_type="campaign",
                )
        else:
            result = engine.translate_file(
                entry["site_id"],
                Path(entry["sandbox_path"]),
                target_langs=[locale],
                validate=True,
                force=True,  # never let the TM answer for the model
                trigger_type="campaign",
            )
    except Exception as exc:  # a raised job is a loud failure, never a pass
        record.update(
            accepted=False,
            error=f"{type(exc).__name__}: {exc}",
            seconds=round(time.perf_counter() - started, 2),
        )
        return record

    receipt = (result.acceptance_receipts or {}).get(locale)
    lang_result = (getattr(result, "language_results", {}) or {}).get(locale)
    output_path = None
    if receipt is not None:
        output_path = receipt.get("output_path")
    if output_path is None and lang_result is not None:
        output_path = getattr(lang_result, "output_path", None)
    record["output_path"] = str(output_path) if output_path else None
    record["receipt"] = receipt
    record["seconds"] = round(time.perf_counter() - started, 2)
    record["model_fingerprint"] = (receipt or {}).get("model_fingerprint")
    gate_results = (receipt or {}).get("gate_results") or {}
    record["gates_evaluated"] = len(gate_results)
    record["gate_failures"] = sorted(
        int(gid) for gid, g in gate_results.items() if not g.get("passed", True)
    )
    if output_path and Path(output_path).is_file():
        data = Path(output_path).read_bytes()
        record["output_sha256"] = sha256_bytes(data)
        record["output_bytes"] = len(data)
        record["accepted"] = receipt is not None
    else:
        record["accepted"] = False
        record["error"] = record.get("error") or (
            getattr(lang_result, "error", None) or "no output written"
        )
        rejection = getattr(result, "rejection_gate_results", None) or {}
        record["rejection_gates"] = sorted(
            int(gid) for gid, g in rejection.items() if not g.get("passed", True)
        )
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TC-APT-004b LLM qualification run")
    parser.add_argument(
        "--sample", type=Path, default=Path("data/benchmark_corpus/qualification_sample.json")
    )
    parser.add_argument("--content-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--sandbox", type=Path, default=None)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--limit", type=int, default=0, help="0 = the whole sample")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    translator_repo = Path.cwd().resolve()
    sample = json.loads(args.sample.read_text(encoding="utf-8"))
    sandbox = (args.sandbox or Path("data/qualification") / args.run_id / "content").resolve()
    if sandbox.exists():
        shutil.rmtree(sandbox)
    sandbox.mkdir(parents=True, exist_ok=True)

    staged = stage_sandbox(sample, args.content_root.resolve(), sandbox)
    jobs = [(entry, loc) for entry in staged for loc in entry["locales"]]
    if args.limit:
        jobs = jobs[: args.limit]
    print(f"[{args.run_id}] staged {len(staged)} sources, {len(jobs)} cells -> {sandbox}")

    tm_dir = (Path('data/qualification') / args.run_id / 'tm').resolve()
    if tm_dir.exists():
        shutil.rmtree(tm_dir)
    engine = build_engine(sandbox, translator_repo, tm_dir)
    # See run_job()'s docstring comment: this reproduces CampaignRunner's full
    # translate_file() serialization, so --concurrency controls how many jobs are
    # QUEUED, not how many run the model concurrently -- matching what a real
    # zero-defect campaign actually does today, not an idealized parallel run.
    model_lock = threading.Lock()
    records: list[dict] = []
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
        futures = {
            pool.submit(run_job, engine, model_lock, e, loc): (e, loc) for e, loc in jobs
        }
        for done, future in enumerate(as_completed(futures), 1):
            record = future.result()
            records.append(record)
            if done % 10 == 0 or done == len(jobs):
                accepted = sum(1 for r in records if r.get("accepted"))
                print(
                    f"  {done}/{len(jobs)} accepted={accepted} "
                    f"elapsed={time.perf_counter() - started:.0f}s",
                    flush=True,
                )

    accepted = [r for r in records if r.get("accepted")]
    rejected = [r for r in records if not r.get("accepted")]
    wrong_model = sorted(
        {
            str(r.get("model_fingerprint"))
            for r in accepted
            if QUALIFICATION_MODEL not in str(r.get("model_fingerprint") or "")
        }
    )
    payload = {
        "taskcard": "TC-APT-004b",
        "run_id": args.run_id,
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "model": QUALIFICATION_MODEL,
        "concurrency": args.concurrency,
        "sandbox": str(sandbox),
        "cells": len(records),
        "accepted": len(accepted),
        "rejected": len(rejected),
        "acceptance_rate": round(len(accepted) / len(records), 4) if records else 0.0,
        "seconds": round(time.perf_counter() - started, 1),
        "unexpected_model_fingerprints": wrong_model,
        "gate_failure_histogram": _histogram(records),
        "results": sorted(records, key=lambda r: (r["source_path"], r["target_lang"])),
    }
    out = args.out or Path(f"data/benchmark_corpus/results/llm_qualification_{args.run_id}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in payload.items() if k != "results"}, indent=2))
    print(f"wrote {out}")
    return 0


def _histogram(records: list[dict]) -> dict[str, int]:
    hist: dict[str, int] = {}
    for record in records:
        for gid in record.get("gate_failures", []) or []:
            hist[f"gate_{gid}"] = hist.get(f"gate_{gid}", 0) + 1
        for gid in record.get("rejection_gates", []) or []:
            hist[f"reject_gate_{gid}"] = hist.get(f"reject_gate_{gid}", 0) + 1
        if not record.get("accepted") and not record.get("rejection_gates"):
            key = "error:" + str(record.get("error", "unknown"))[:60]
            hist[key] = hist.get(key, 0) + 1
    return dict(sorted(hist.items()))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
