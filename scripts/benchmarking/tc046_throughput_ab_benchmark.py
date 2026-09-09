#!/usr/bin/env python
"""TC-APT-046 "step 4" throughput half: does ``max_parallel_jobs > 1`` actually
speed up a realistic campaign workload end-to-end through the real
``CampaignRunner`` (not just raw API throughput -- TC-APT-064 already measured
that separately against the live ``professionalize_llm`` endpoint)?

Context
-------
TC-APT-064's sustained-load calibration proved ``professionalize_llm`` itself
tolerates 64 concurrent in-flight calls cleanly (0 errors, 0 rate-limited,
3611 calls, see
``data/benchmark_corpus/results/professionalize_llm_calibration_tc064_sustained_20260906.json``).
Separately, a peer session's wave23-cells-go canary proved ``max_parallel_jobs=4``
is SAFE inside ``CampaignRunner`` (zero cross-contamination, zero empty
frontmatter) but could not measure a throughput benefit, because real
campaign shard/job structure meant only one locale shard ran roughly every
~8 minutes through 22 total -- sequential SHARD cadence swamped any
in-shard THREAD-parallelism signal (see TC-APT-046's taskcard note,
2026-09-09T14:15Z entry).

This script isolates that missing measurement: a synthetic multi-source
manifest with genuinely many jobs per shard (the condition wave23 lacked),
run through the real ``CampaignRunner._run_locked`` -> ``ThreadPoolExecutor``
-> ``_run_campaign_job`` path at several ``max_parallel_jobs`` levels, with a
FAKE engine standing in for the translation engine's ``translate_file()`` --
the one call ``CampaignRunner`` threads across a shard's jobs -- so NO real
network call is ever made and NO real content repo or ``data/campaigns/`` is
ever touched.

Simulated latency and scaling
------------------------------
TC-APT-064 measured p95 latency 26.2-28.7s across concurrency levels 16-48
(28.7s at 64). This script uses a representative p95 of 27.5s (the midpoint
of that range) and a documented ``LATENCY_SCALE_FACTOR`` of 0.1, i.e. each
simulated call sleeps ``SIMULATED_CALL_LATENCY_SECONDS = 2.75s``. The
absolute number does not matter for this measurement -- only the RATIO
between ``max_parallel_jobs`` levels does, and that ratio is preserved by
scaling every level identically. Job count is sized so the highest tested
level has room to show a full effect: ``SOURCES_PER_LOCALE`` (default 16)
equals the highest default level (16), and total jobs (32, two locale
shards of 16 each) is >= 2x that level, per this taskcard's own acceptance
bar.

Output
------
Raw per-level results (level, job count, wall-clock seconds, computed
speedup ratio vs the serial ``max_parallel_jobs=1`` baseline) are written to
``data/summaries/tc-apt-046-throughput-measurement-<run_tag>.json``
(gitignored).

Example
-------
    .venv\\Scripts\\python.exe scripts/benchmarking/tc046_throughput_ab_benchmark.py \\
        --levels 1,4,8,16
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SUMMARIES_DIR = REPO_ROOT / "data" / "summaries"
BENCH_SCRATCH_DIR = REPO_ROOT / ".local" / "tc046_throughput_bench"

sys.path.insert(0, str(REPO_ROOT))

from src.workers.campaign_manifest import CampaignManifest, sha256_file  # noqa: E402
from src.workers.campaign_runner import CampaignRunner  # noqa: E402

# --- TC-APT-064 evidence-derived simulated latency ---------------------------------
# data/benchmark_corpus/results/professionalize_llm_calibration_tc064_sustained_20260906.json
MEASURED_TC064_P95_LATENCY_RANGE_SECONDS = (26.2, 28.7)
REPRESENTATIVE_P95_LATENCY_SECONDS = 27.5  # midpoint of the range above
LATENCY_SCALE_FACTOR = 0.1
SIMULATED_CALL_LATENCY_SECONDS = round(REPRESENTATIVE_P95_LATENCY_SECONDS * LATENCY_SCALE_FACTOR, 3)

# --- Synthetic workload sizing -------------------------------------------------------
DEFAULT_LEVELS = (1, 4, 8, 16)
DEFAULT_SOURCES_PER_LOCALE = 16  # >= max(DEFAULT_LEVELS): the top level gets a full shard to itself
DEFAULT_LOCALES = ("es", "fr")  # 2 locale shards (same wave/site/family/platform)


class FakeLLMEngine:
    """Stands in for the real translation engine's ``translate_file()`` -- the ONE
    call ``CampaignRunner._run_campaign_job`` threads across a shard's jobs via
    ``ThreadPoolExecutor(max_workers=min(max_parallel_jobs, len(shard["jobs"])))``.

    Simulates a ``professionalize_llm`` ``generate()`` call by sleeping
    ``latency_seconds`` and then returning a valid, well-formed accepted
    translation on the FIRST attempt (so exactly one call is made per job,
    matching a single successful LLM call) -- no network, no subprocess, no
    real model load. Tracks live/peak concurrent calls so the benchmark can
    report the REAL overlap achieved, not just the configured level.
    """

    def __init__(self, outputs: dict[tuple[str, str], Path], latency_seconds: float):
        self.campaign_context: dict[str, Any] = {}
        self.config = SimpleNamespace(get_site_profile=lambda _site: SimpleNamespace())
        self._outputs = outputs
        self._latency = latency_seconds
        self._lock = threading.Lock()
        self._active = 0
        self.peak_active = 0
        self.call_count = 0

    def _get_output_path(self, source_path: Path, locale: str, _profile: Any) -> Path:
        return self._outputs[(str(source_path), locale)]

    def translate_file(
        self, _site_id: str, source_path: Path, target_langs: list[str], **_kwargs: Any
    ) -> SimpleNamespace:
        locale = target_langs[0]
        with self._lock:
            self._active += 1
            self.peak_active = max(self.peak_active, self._active)
            self.call_count += 1
        try:
            time.sleep(self._latency)
            output = self._outputs[(str(source_path), locale)]
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(f"translated-{locale}-{source_path.name}", encoding="utf-8")
            receipt = {
                "campaign_id": "tc046-throughput-bench",
                "source_path": str(source_path.resolve()),
                "output_path": str(output.resolve()),
                "source_sha256": sha256_file(source_path),
                "output_sha256": sha256_file(output),
                "target_lang": locale,
                "validation_policy": "zero-defect",
                "config_fingerprint": "bench",
                "model_fingerprint": "fake-llm-engine",
                "gate_results": {i: {"passed": True} for i in range(1, 45)},
            }
            self.campaign_context["receipt_sink"](receipt)
            return SimpleNamespace(success=True, acceptance_receipts={locale: receipt}, errors=[])
        finally:
            with self._lock:
                self._active -= 1


def _rmtree_windows_safe(path: Path) -> None:
    """``shutil.rmtree`` chokes on git's read-only ``.git/objects/*`` files on
    Windows -- clear the read-only bit on failure and retry."""

    def _on_rm_error(func, target, _exc_info) -> None:
        os.chmod(target, stat.S_IWRITE)
        func(target)

    try:
        shutil.rmtree(path, onexc=_on_rm_error)  # Python >= 3.12
    except TypeError:
        shutil.rmtree(path, onerror=_on_rm_error)  # Python < 3.12


def _run_git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def build_scratch_content_repo(
    root: Path, *, sources_per_locale: int, locales: tuple[str, ...]
) -> tuple[Path, list[dict[str, Any]], dict[tuple[str, str], Path]]:
    """A disposable git repo (same ``tmp_path`` + ``git init`` convention used in
    ``tests/unit/workers/test_campaign_manifest.py``), never the real content repo.

    All ``sources_per_locale`` sources share one (wave, site_id, family, platform)
    key and target every locale in ``locales``, so ``CampaignManifest.shards()``
    groups them into ``len(locales)`` shards of ``sources_per_locale`` jobs each --
    the "genuinely multiple jobs per shard" condition the wave23 canary lacked.
    """
    content_repo = root / "content-repo"
    content_repo.mkdir(parents=True, exist_ok=True)
    _run_git(["init", "-b", "bench"], content_repo)
    _run_git(["config", "user.email", "tc046-bench@example.invalid"], content_repo)
    _run_git(["config", "user.name", "TC-APT-046 Throughput Bench"], content_repo)

    sources: list[dict[str, Any]] = []
    output_paths: dict[tuple[str, str], Path] = {}
    for i in range(sources_per_locale):
        rel_source = f"content/docs.aspose.org/en/words/net/synthetic-page-{i:03d}.md"
        source_path = content_repo / rel_source
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(
            f"# Synthetic page {i}\n\nThis is disposable benchmark content, page {i}.\n",
            encoding="utf-8",
        )
        outputs = {}
        for locale in locales:
            rel_output = f"content/docs.aspose.org/{locale}/words/net/synthetic-page-{i:03d}.md"
            outputs[locale] = rel_output
            output_paths[(str(source_path), locale)] = content_repo / rel_output
        sources.append(
            {
                "site_id": "docs.aspose.org",
                "family": "words",
                "platform": "net",
                "source_path": rel_source,
                "source_sha256": sha256_file(source_path),
                "wave": 1,
                "outputs": outputs,
            }
        )
    _run_git(["add", "."], content_repo)
    _run_git(["commit", "-m", "synthetic baseline"], content_repo)
    return content_repo, sources, output_paths


def build_manifest_payload(
    *, content_repo: Path, sources: list[dict[str, Any]], locales: tuple[str, ...], max_parallel_jobs: int
) -> dict[str, Any]:
    total_outputs = len(sources) * len(locales)
    return {
        "schema_version": 1,
        "campaign_id": "tc046-throughput-bench",
        "validation_policy": "zero-defect",
        "content_repo": str(content_repo),
        "content_repo_sha": "a" * 40,
        "translator_repo_sha": "b" * 40,
        "config_fingerprint": "c" * 64,
        "model_fingerprints": {"model_registry": "e" * 64},
        "tm_fingerprint": "f" * 64,
        "knowledge_fingerprints": {},
        "target_locales": list(locales),
        "expected_source_count": len(sources),
        "expected_output_count": total_outputs,
        "retry_policy": {
            # professionalize_llm primary so the ONE call every job makes (it always
            # succeeds first try -- see FakeLLMEngine) is explicitly the LLM call
            # whose latency TC-APT-064 measured. Valid inverse pair per
            # CampaignManifest.validate_schema()'s _valid_pairs.
            "primary_model": "professionalize_llm",
            "primary_attempts": 3,
            "llm_escalation_attempts": 2,
            "llm_model": "m2m100_418m",
        },
        "commit_policy": {
            "branch": "bench",
            "max_outputs_per_commit": 250,
            "push": False,
        },
        "execution_policy": {
            "max_parallel_jobs": max_parallel_jobs,
            "model_sharing": "single_shared_instance",
        },
        "sources": sources,
    }


def run_one_level(
    *,
    level: int,
    latency_seconds: float,
    sources_per_locale: int,
    locales: tuple[str, ...],
    scratch_root: Path,
) -> dict[str, Any]:
    """Build a FRESH scratch content repo + ledger for this level (so no receipt/
    resume state leaks between levels) and time a real ``CampaignRunner.run()``.

    ``verify()`` (git/environment fingerprint checks) and ``_commit_verified_outputs``
    (git staging/commit) are stubbed exactly as
    ``test_campaign_parallel_jobs_share_engine_without_cross_job_state`` does in
    ``tests/unit/workers/test_campaign_manifest.py`` -- this benchmark's subject is
    ``_run_locked``'s shard/job/``ThreadPoolExecutor`` scheduling, not environment
    verification or git plumbing, and stubbing them keeps the run hermetic (no git
    commit is ever made, satisfying the "never git commit" / "never touch the content
    repo for real" constraints).
    """
    level_dir = scratch_root / f"level_{level:03d}"
    if level_dir.exists():
        _rmtree_windows_safe(level_dir)
    level_dir.mkdir(parents=True)

    content_repo, sources, output_paths = build_scratch_content_repo(
        level_dir, sources_per_locale=sources_per_locale, locales=locales
    )
    ledger_root = level_dir / "ledger"
    translator_repo = level_dir / "translator-repo-stub"
    translator_repo.mkdir(parents=True, exist_ok=True)

    payload = build_manifest_payload(
        content_repo=content_repo, sources=sources, locales=locales, max_parallel_jobs=level
    )
    manifest_path = level_dir / "manifest.yaml"
    import yaml

    manifest_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    manifest = CampaignManifest.load(manifest_path)

    engine = FakeLLMEngine(output_paths, latency_seconds)
    runner = CampaignRunner(
        manifest=manifest,
        translation_engine=engine,
        translator_repo=translator_repo,
        ledger_root=ledger_root,
    )
    # Bypass git/environment verification (no real baseline commit to check
    # against) and git commit staging (this benchmark never commits) --
    # see the docstring above for why this is the same stub the repo's own
    # regression test for job overlap already uses.
    runner.verify = lambda **_kwargs: {**manifest.to_summary(), "accepted": 0, "remaining": len(sources) * len(locales)}
    runner._commit_verified_outputs = lambda _shard_id: None
    # TC-APT-046 step 1's rollback switch: level 1 runs with it effectively ON
    # (matching today's shipped default, config/global.yaml
    # translation_engine.concurrency.force_serialize_all_backends: true), every
    # level > 1 runs with it OFF (matching the wave23 canary's --no-force-serialize).
    runner._force_serialize = level == 1

    start = time.perf_counter()
    summary = runner.run()
    wall_clock_seconds = time.perf_counter() - start

    total_jobs = len(sources) * len(locales)
    receipts = runner.ledger.receipts()
    return {
        "max_parallel_jobs": level,
        "force_serialize": runner._force_serialize,
        "total_jobs": total_jobs,
        "shards": len(locales),
        "jobs_per_shard": sources_per_locale,
        "jobs_accepted": summary.get("accepted"),
        "jobs_failed": summary.get("failed"),
        "receipts_recorded": len(receipts),
        "engine_call_count": engine.call_count,
        "peak_observed_concurrency": engine.peak_active,
        "campaign_status": summary.get("status"),
        "wall_clock_seconds": round(wall_clock_seconds, 3),
    }


def measure_levels(
    *,
    levels: list[int],
    latency_seconds: float,
    sources_per_locale: int,
    locales: tuple[str, ...],
    scratch_root: Path,
) -> dict[str, Any]:
    scratch_root.mkdir(parents=True, exist_ok=True)
    results = []
    baseline_seconds: float | None = None
    for level in levels:
        print(f"[tc046-throughput-bench] running level max_parallel_jobs={level} ...")
        result = run_one_level(
            level=level,
            latency_seconds=latency_seconds,
            sources_per_locale=sources_per_locale,
            locales=locales,
            scratch_root=scratch_root,
        )
        if level == 1 or baseline_seconds is None:
            baseline_seconds = result["wall_clock_seconds"]
        result["speedup_vs_serial_baseline"] = (
            round(baseline_seconds / result["wall_clock_seconds"], 3)
            if result["wall_clock_seconds"] > 0
            else None
        )
        print(
            f"[tc046-throughput-bench] level={level} wall_clock={result['wall_clock_seconds']}s "
            f"accepted={result['jobs_accepted']}/{result['total_jobs']} "
            f"peak_observed_concurrency={result['peak_observed_concurrency']} "
            f"speedup={result['speedup_vs_serial_baseline']}x"
        )
        results.append(result)

    return {
        "taskcard": "TC-APT-046",
        "purpose": (
            "Isolate whether max_parallel_jobs > 1 gives a genuine wall-clock "
            "speedup for realistic campaign work through the real CampaignRunner "
            "path, using a synthetic multi-source manifest with many jobs per "
            "shard (the condition the wave23-cells-go canary lacked) and a fake, "
            "network-free LLM engine sleeping a latency derived from TC-APT-064's "
            "sustained-load measurement."
        ),
        "generated_at_epoch": time.time(),
        "generated_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "simulated_latency": {
            "source": (
                "data/benchmark_corpus/results/"
                "professionalize_llm_calibration_tc064_sustained_20260906.json"
            ),
            "measured_tc064_p95_latency_range_seconds": list(MEASURED_TC064_P95_LATENCY_RANGE_SECONDS),
            "representative_p95_latency_seconds": REPRESENTATIVE_P95_LATENCY_SECONDS,
            "scale_factor": LATENCY_SCALE_FACTOR,
            "simulated_call_latency_seconds": latency_seconds,
            "rationale": (
                "Absolute latency does not matter for this measurement, only the "
                "RATIO between max_parallel_jobs levels; every level uses the same "
                "scaled latency so that ratio is preserved."
            ),
        },
        "workload": {
            "sources_per_locale": sources_per_locale,
            "locales": list(locales),
            "total_jobs": sources_per_locale * len(locales),
            "shards": len(locales),
            "jobs_per_shard": sources_per_locale,
        },
        "network_calls_made": 0,
        "real_content_repo_touched": False,
        "real_data_campaigns_touched": False,
        "git_commits_made": 0,
        "levels": results,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--levels",
        default=",".join(str(x) for x in DEFAULT_LEVELS),
        help="Comma-separated max_parallel_jobs levels to measure (first is treated as the serial baseline)",
    )
    parser.add_argument(
        "--latency-seconds",
        type=float,
        default=SIMULATED_CALL_LATENCY_SECONDS,
        help="Simulated per-call latency in seconds (default: TC-APT-064's p95 scaled by 0.1)",
    )
    parser.add_argument("--sources-per-locale", type=int, default=DEFAULT_SOURCES_PER_LOCALE)
    parser.add_argument("--locales", default=",".join(DEFAULT_LOCALES))
    parser.add_argument(
        "--scratch-root",
        default=str(BENCH_SCRATCH_DIR),
        help="Disposable scratch directory for the synthetic git repo + ledger (never data/campaigns/)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    levels = [int(x) for x in args.levels.split(",") if x.strip()]
    locales = tuple(x for x in args.locales.split(",") if x.strip())

    print(
        f"[tc046-throughput-bench] levels={levels} latency_seconds={args.latency_seconds} "
        f"sources_per_locale={args.sources_per_locale} locales={locales}"
    )
    summary = measure_levels(
        levels=levels,
        latency_seconds=args.latency_seconds,
        sources_per_locale=args.sources_per_locale,
        locales=locales,
        scratch_root=Path(args.scratch_root),
    )

    SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)
    run_tag = time.strftime("%Y%m%dT%H%M%S")
    out_path = SUMMARIES_DIR / f"tc-apt-046-throughput-measurement-{run_tag}.json"
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"[tc046-throughput-bench] summary written to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
