#!/usr/bin/env python
"""
VR-01 (gap CO-04): real-hardware measurement of safe multi-process m2m100_418m
CUDA concurrency on this machine's RTX 4090 Laptop GPU, plus a live smoke test
of GPUAdmissionController's deny/grant behaviour against real telemetry.

Uses ONLY synthetic dummy content (tests/fixtures/gpu_bench/synthetic_en.md) --
never data/campaigns/ or the content repo. Never commits, never deletes
anything outside the benchmark's own scratch/output paths.

Two roles
---------
--role worker (internal, spawned by the orchestrator, one per concurrent
    process): optionally requests admission from GPUAdmissionController,
    loads m2m100_418m on CUDA (from the locally cached weights under
    models/m2m100_418m -- no network), translates the synthetic fixture for
    N iterations, records VRAM/timing, unloads, writes a per-worker result
    JSON, exits.

--role orchestrator (default): for each requested concurrency level, spawns
    that many worker subprocesses, samples nvidia-smi throughout the run,
    waits for every worker (with a hard per-level timeout and a kill
    fallback so nothing is ever left orphaned holding VRAM), aggregates
    results, runs the admission-controller smoke test (tiny fake budget ->
    deny, real 16GB-scale budget -> grant, both against REAL current
    telemetry), and writes the combined summary to
    data/summaries/vr-01-concurrency-measurement-<timestamp>.json.

Example
-------
    .venv\\Scripts\\python.exe scripts/benchmarking/gpu_concurrency_bench.py \\
        --levels 1,2,3,4 --iterations 5
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "gpu_bench" / "synthetic_en.md"
SUMMARIES_DIR = REPO_ROOT / "data" / "summaries"
BENCH_SCRATCH_DIR = REPO_ROOT / ".local" / "gpu_bench"

sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _load_synthetic_sentences() -> list[str]:
    lines = []
    for raw in FIXTURE_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("---") or line.startswith("title:"):
            continue
        lines.append(line)
    if not lines:
        raise RuntimeError(f"No usable synthetic sentences found in {FIXTURE_PATH}")
    return lines


def _nvidia_smi_sample() -> dict[str, float] | None:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used,memory.total,temperature.gpu,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        used, total, temp, util = [p.strip() for p in result.stdout.strip().split("\n")[0].split(",")]
        return {
            "used_mib": float(used),
            "total_mib": float(total),
            "temp_c": float(temp),
            "util_pct": float(util),
        }
    except Exception:
        return None


class GpuSampler:
    """Background thread polling nvidia-smi at a fixed interval (fleet-wide, not per-process)."""

    def __init__(self, interval_sec: float = 1.0):
        self.interval_sec = interval_sec
        self._samples: list[dict[str, Any]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _run(self) -> None:
        while not self._stop.is_set():
            sample = _nvidia_smi_sample()
            if sample is not None:
                sample["t"] = time.time()
                self._samples.append(sample)
            self._stop.wait(self.interval_sec)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> list[dict[str, Any]]:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        return list(self._samples)


def _write_result(path: Path, result: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")


def _probe_subprocess_snapshot() -> dict:
    """One-shot cross-check of torch.cuda.mem_get_info() vs nvidia-smi from a
    disposable subprocess, so the comparison itself never leaves a lingering
    CUDA context (and its ~hundreds-of-MB context overhead) behind in the
    orchestrator process. Used to reconfirm, under REAL concurrent m2m100
    load, the same visibility finding established by the standalone
    two-process rehearsal documented in docs/operations/vr-01-concurrency-measurement.md.
    """
    code = (
        "import json,subprocess,torch\n"
        "torch.cuda.init()\n"
        "free_b,total_b=torch.cuda.mem_get_info(0)\n"
        "r=subprocess.run(['nvidia-smi','--query-gpu=memory.used,memory.total,temperature.gpu',"
        "'--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=10)\n"
        "u,t,c=[p.strip() for p in r.stdout.strip().split(',')]\n"
        "print(json.dumps({'mem_get_info_used_mib': round((total_b-free_b)/1024**2,1),"
        "'mem_get_info_total_mib': round(total_b/1024**2,1),"
        "'nvidia_smi_used_mib': float(u), 'nvidia_smi_total_mib': float(t),"
        "'nvidia_smi_temp_c': float(c)}))\n"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, timeout=30, cwd=str(REPO_ROOT)
        )
        return json.loads(result.stdout.strip().splitlines()[-1])
    except Exception as exc:  # pragma: no cover - diagnostic only
        return {"error": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# Worker role
# ---------------------------------------------------------------------------


def _worker_main(args: argparse.Namespace) -> int:
    result: dict[str, Any] = {
        "worker_id": args.worker_id,
        "pid": os.getpid(),
        "model_id": "m2m100_418m",
    }
    try:
        import torch

        from src.hardware.gpu_admission import GPUAdmissionController
        from src.hardware.vram_enforcer import VRAMEnforcer
        from src.model_runtime.loader import HuggingFaceBackend
        from src.model_runtime.registry import ModelRegistry

        controller = None
        if args.use_admission:
            controller = GPUAdmissionController(
                registry_path=args.admission_registry,
                vram_budget_percent=args.vram_budget_percent,
                thermal_ceiling_c=args.thermal_ceiling_c,
                wait_interval_sec=0,
                max_wait_attempts=1,
                root=REPO_ROOT,
                per_process_vram_mib={"m2m100_418m": args.reserve_vram_mib},
            )
            granted, reason, telemetry = controller.request_admission(args.worker_id, "m2m100_418m")
            result["admission"] = {"granted": granted, "reason": reason, **telemetry}
            if not granted:
                result["status"] = "denied_admission"
                _write_result(Path(args.output_json), result)
                return 0  # denial is an expected, valid outcome here -- not a script failure

        registry = ModelRegistry(str(REPO_ROOT / "config" / "model_registry.yaml"))
        model_info = registry.get_model("m2m100_418m")

        enforcer = VRAMEnforcer()
        applied_mb, _budget = enforcer.enforce_from_config(
            {"enable_gpu": True, "max_gpu_memory_percent": args.max_gpu_memory_percent},
            device="cuda:0",
        )
        result["vram_cap_mb"] = applied_mb

        backend = HuggingFaceBackend(model_info, device="cuda", max_memory_mb=applied_mb, use_fp16=True)

        load_start = time.perf_counter()
        backend.load()
        load_s = time.perf_counter() - load_start
        allocated_after_load_mb = torch.cuda.memory_allocated(0) / (1024**2)
        reserved_after_load_mb = torch.cuda.memory_reserved(0) / (1024**2)

        sentences = _load_synthetic_sentences()
        batch = sentences[: args.batch_size] if args.batch_size else sentences

        translated_count = 0
        gen_start = time.perf_counter()
        for _ in range(args.iterations):
            backend.translate(
                batch, src_lang="en", tgt_lang=args.tgt_lang, max_new_tokens=args.max_new_tokens
            )
            translated_count += len(batch)
        gen_elapsed_s = time.perf_counter() - gen_start

        peak_allocated_mb = torch.cuda.max_memory_allocated(0) / (1024**2)
        peak_reserved_mb = torch.cuda.max_memory_reserved(0) / (1024**2)

        backend.unload()
        torch.cuda.synchronize()
        allocated_after_unload_mb = torch.cuda.memory_allocated(0) / (1024**2)

        if controller is not None:
            controller.release_admission()

        result.update(
            {
                "status": "ok",
                "load_s": load_s,
                "allocated_after_load_mb": allocated_after_load_mb,
                "reserved_after_load_mb": reserved_after_load_mb,
                "peak_allocated_mb": peak_allocated_mb,
                "peak_reserved_mb": peak_reserved_mb,
                "allocated_after_unload_mb": allocated_after_unload_mb,
                "iterations": args.iterations,
                "batch_size": len(batch),
                "translated_count": translated_count,
                "gen_elapsed_s": gen_elapsed_s,
                "translations_per_sec": (translated_count / gen_elapsed_s) if gen_elapsed_s > 0 else None,
            }
        )
    except Exception as exc:  # noqa: BLE001 - real hardware run: always emit a JSON result
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["traceback"] = traceback.format_exc()

    _write_result(Path(args.output_json), result)
    return 0


# ---------------------------------------------------------------------------
# Orchestrator role
# ---------------------------------------------------------------------------


def _run_level(
    concurrency: int,
    args: argparse.Namespace,
    run_tag: str,
) -> dict[str, Any]:
    level_dir = BENCH_SCRATCH_DIR / run_tag / f"level{concurrency}"
    level_dir.mkdir(parents=True, exist_ok=True)
    admission_registry = f".local/gpu_bench/{run_tag}/level{concurrency}/admission_registry.json"

    sampler = GpuSampler(interval_sec=1.0)
    sampler.start()
    baseline = _nvidia_smi_sample()

    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    log_dir = level_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    children: list[subprocess.Popen] = []
    handles: list[Any] = []
    output_paths: list[Path] = []
    for i in range(concurrency):
        worker_id = f"{run_tag}-L{concurrency}-W{i}"
        output_json = level_dir / f"worker{i}.json"
        output_paths.append(output_json)
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--role",
            "worker",
            "--worker-id",
            worker_id,
            "--output-json",
            str(output_json),
            "--iterations",
            str(args.iterations),
            "--batch-size",
            str(args.batch_size),
            "--max-new-tokens",
            str(args.max_new_tokens),
            "--tgt-lang",
            args.tgt_lang,
            "--max-gpu-memory-percent",
            str(args.max_gpu_memory_percent),
            "--reserve-vram-mib",
            str(args.reserve_vram_mib),
            "--vram-budget-percent",
            str(args.vram_budget_percent),
            "--thermal-ceiling-c",
            str(args.thermal_ceiling_c),
        ]
        if not args.no_admission:
            command += ["--use-admission", "--admission-registry", admission_registry]
        log_path = log_dir / f"worker{i}.log"
        handle = log_path.open("w", encoding="utf-8")
        handles.append(handle)
        children.append(
            subprocess.Popen(
                command,
                cwd=str(REPO_ROOT),
                creationflags=flags,
                stdout=handle,
                stderr=subprocess.STDOUT,
            )
        )

    mid_run_cross_check: dict[str, Any] | None = None
    deadline = time.time() + args.worker_timeout_sec
    exit_codes: list[int | None] = [None] * concurrency
    cross_check_taken = False
    while time.time() < deadline and any(code is None for code in exit_codes):
        for i, child in enumerate(children):
            if exit_codes[i] is None:
                code = child.poll()
                if code is not None:
                    exit_codes[i] = code
        if not cross_check_taken and concurrency == args.cross_check_at_level and time.time() > deadline - args.worker_timeout_sec + 5:
            # Give workers ~5s to get past model load before sampling, so the
            # cross-check happens while GPU work is actually in flight.
            mid_run_cross_check = _probe_subprocess_snapshot()
            cross_check_taken = True
        time.sleep(0.5)

    timed_out = [i for i, code in enumerate(exit_codes) if code is None]
    for i in timed_out:
        children[i].kill()
        children[i].wait(timeout=10)
        exit_codes[i] = -9

    for handle in handles:
        handle.close()

    gpu_samples = sampler.stop()
    final_state = _nvidia_smi_sample()

    worker_results = []
    for path in output_paths:
        if path.exists():
            try:
                worker_results.append(json.loads(path.read_text(encoding="utf-8")))
            except Exception as exc:
                worker_results.append({"status": "unreadable_result", "error": str(exc), "path": str(path)})
        else:
            worker_results.append({"status": "no_result_file", "path": str(path)})

    peak_used_mib = max((s["used_mib"] for s in gpu_samples), default=None)
    peak_temp_c = max((s["temp_c"] for s in gpu_samples), default=None)

    ok_results = [w for w in worker_results if w.get("status") == "ok"]
    total_translations = sum(w.get("translated_count", 0) for w in ok_results)
    wall_clock_s = max((w.get("gen_elapsed_s", 0) for w in ok_results), default=0)

    return {
        "concurrency": concurrency,
        "baseline_gpu_state": baseline,
        "final_gpu_state": final_state,
        "exit_codes": exit_codes,
        "timed_out_worker_indices": timed_out,
        "worker_results": worker_results,
        "gpu_samples": gpu_samples,
        "peak_used_mib": peak_used_mib,
        "peak_temp_c": peak_temp_c,
        "total_accepted_translations": total_translations,
        "aggregate_translations_per_sec": (total_translations / wall_clock_s) if wall_clock_s else None,
        "mid_run_cross_check_mem_get_info_vs_nvidia_smi": mid_run_cross_check,
        "admission_used": not args.no_admission,
    }


def _admission_smoke_test(args: argparse.Namespace) -> dict[str, Any]:
    """Prove GPUAdmissionController denies on a deliberately tiny fake budget
    and grants on the real ~16GB-scale production budget -- both checks read
    REAL current nvidia-smi/torch telemetry; only the configured ceiling
    differs between the two calls."""
    from src.hardware.gpu_admission import GPUAdmissionController, query_vram_mib_nvidia_smi_only

    # The orchestrator process never loads a model itself, so it must not use
    # the default probe (which would prefer torch.cuda.mem_get_info() and
    # initialize a CUDA context here that then persists for the rest of this
    # process's life, inflating every later nvidia-smi reading it takes).
    tiny = GPUAdmissionController(
        registry_path=f".local/gpu_bench/admission_smoke_tiny_{int(time.time())}.json",
        vram_budget_percent=args.low_budget_percent,
        thermal_ceiling_c=args.thermal_ceiling_c,
        wait_interval_sec=0,
        max_wait_attempts=1,
        root=REPO_ROOT,
        vram_probe=query_vram_mib_nvidia_smi_only,
        per_process_vram_mib={"m2m100_418m": args.reserve_vram_mib},
    )
    tiny_granted, tiny_reason, tiny_telemetry = tiny.request_admission("smoke-tiny-budget", "m2m100_418m")
    if tiny_granted:
        tiny.release_admission()

    real = GPUAdmissionController(
        registry_path=f".local/gpu_bench/admission_smoke_real_{int(time.time())}.json",
        vram_budget_percent=args.vram_budget_percent,
        thermal_ceiling_c=args.thermal_ceiling_c,
        wait_interval_sec=0,
        max_wait_attempts=1,
        root=REPO_ROOT,
        vram_probe=query_vram_mib_nvidia_smi_only,
        per_process_vram_mib={"m2m100_418m": args.reserve_vram_mib},
    )
    real_granted, real_reason, real_telemetry = real.request_admission("smoke-real-budget", "m2m100_418m")
    if real_granted:
        real.release_admission()

    return {
        "tiny_budget_percent": args.low_budget_percent,
        "tiny_budget_granted": tiny_granted,
        "tiny_budget_reason": tiny_reason,
        "tiny_budget_telemetry": tiny_telemetry,
        "real_budget_percent": args.vram_budget_percent,
        "real_budget_granted": real_granted,
        "real_budget_reason": real_reason,
        "real_budget_telemetry": real_telemetry,
        "deny_grant_behavior_confirmed": (tiny_granted is False) and (real_granted is True),
    }


def _orchestrator_main(args: argparse.Namespace) -> int:
    run_tag = time.strftime("%Y%m%dT%H%M%S")
    levels = [int(x) for x in args.levels.split(",") if x.strip()]

    print(f"[vr-01-bench] run_tag={run_tag} levels={levels} iterations={args.iterations}")

    smoke = _admission_smoke_test(args)
    print(
        f"[vr-01-bench] admission smoke test: tiny_budget_granted={smoke['tiny_budget_granted']} "
        f"real_budget_granted={smoke['real_budget_granted']}"
    )

    level_reports = []
    for concurrency in levels:
        print(f"[vr-01-bench] launching concurrency level {concurrency}...")
        report = _run_level(concurrency, args, run_tag)
        print(
            f"[vr-01-bench] level {concurrency} done: "
            f"peak_used_mib={report['peak_used_mib']} peak_temp_c={report['peak_temp_c']} "
            f"accepted_translations={report['total_accepted_translations']} "
            f"tr/s={report['aggregate_translations_per_sec']}"
        )
        level_reports.append(report)

        # Safety: confirm GPU returned to (near) idle before starting the next
        # level, so levels don't contaminate each other's measurements.
        time.sleep(2)
        cooldown = _nvidia_smi_sample()
        report["cooldown_gpu_state_after_2s"] = cooldown

    summary = {
        "taskcard": "VR-01",
        "gap_linkage": "CO-04",
        "run_tag": run_tag,
        "generated_at_epoch": time.time(),
        "generated_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "config": {
            "iterations": args.iterations,
            "batch_size": args.batch_size,
            "max_new_tokens": args.max_new_tokens,
            "tgt_lang": args.tgt_lang,
            "max_gpu_memory_percent_per_process": args.max_gpu_memory_percent,
            "admission_vram_budget_percent": args.vram_budget_percent,
            "admission_thermal_ceiling_c": args.thermal_ceiling_c,
            "admission_reserve_vram_mib_per_process": args.reserve_vram_mib,
            "admission_enabled_in_levels": not args.no_admission,
            "fixture": str(FIXTURE_PATH.relative_to(REPO_ROOT)),
        },
        "admission_controller_smoke_test": smoke,
        "levels": level_reports,
    }

    SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)
    out_path = SUMMARIES_DIR / f"vr-01-concurrency-measurement-{run_tag}.json"
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"[vr-01-bench] summary written to {out_path}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=("orchestrator", "worker"), default="orchestrator")

    # Orchestrator-only
    parser.add_argument("--levels", default="1,2,3,4", help="Comma-separated concurrency levels to try")
    parser.add_argument("--worker-timeout-sec", type=int, default=300)
    parser.add_argument("--no-admission", action="store_true", help="Skip admission control during levels (raw capacity probe)")
    parser.add_argument("--low-budget-percent", type=float, default=0.5, help="Deliberately tiny VRAM budget %% for the deny smoke test")
    parser.add_argument("--cross-check-at-level", type=int, default=2, help="Concurrency level at which to take the mid-run mem_get_info-vs-nvidia-smi cross-check")

    # Worker-only
    parser.add_argument("--worker-id", default=None)
    parser.add_argument("--output-json", default=None)
    parser.add_argument("--use-admission", action="store_true")
    parser.add_argument("--admission-registry", default=".local/gpu_admission_registry.json")

    # Shared
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--max-new-tokens", type=int, default=40)
    parser.add_argument("--tgt-lang", default="es")
    parser.add_argument("--max-gpu-memory-percent", type=int, default=40, help="Per-process VRAMEnforcer cap (matches VR-01's prior manual rehearsal)")
    parser.add_argument("--reserve-vram-mib", type=float, default=1100.0, help="Admission controller's declared per-process VRAM reservation")
    parser.add_argument("--vram-budget-percent", type=float, default=80.0, help="Admission controller's fleet-wide VRAM budget (%% of total)")
    parser.add_argument("--thermal-ceiling-c", type=float, default=80.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.role == "worker":
        if not args.worker_id or not args.output_json:
            raise SystemExit("--worker-id and --output-json are required for --role worker")
        return _worker_main(args)
    return _orchestrator_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
