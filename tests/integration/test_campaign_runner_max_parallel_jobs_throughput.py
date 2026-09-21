"""TC-APT-046 "step 4" throughput half: a permanent, CI-fast regression proof that
``max_parallel_jobs > 1`` gives a genuine wall-clock speedup through the REAL
``CampaignRunner._run_locked`` -> ``ThreadPoolExecutor`` -> ``_run_campaign_job`` path,
not just raw API throughput (TC-APT-064 already measured that separately against the
live ``professionalize_llm`` endpoint).

This reuses the exact same synthetic-manifest/fake-engine machinery as
``scripts/benchmarking/tc046_throughput_ab_benchmark.py`` (that script is the
re-runnable, realistically-scaled-latency measurement whose results are written to
``data/summaries/tc-apt-046-throughput-measurement-*.json``; this test is the fast,
small-margin correctness check that belongs in the permanent suite). No real network
call, no real content repo, no ``data/campaigns/``, no git commit.

Context: a peer session's wave23-cells-go canary proved max_parallel_jobs=4 is SAFE
(zero cross-contamination, zero empty frontmatter) but could not prove a throughput
benefit, because the real campaign's shard/job structure gave it only one job per
shard -- sequential SHARD cadence swamped any in-shard THREAD-parallelism signal. This
test isolates the missing half of that measurement with a manifest sized so each shard
genuinely has many jobs (the condition wave23 lacked).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.benchmarking.tc046_throughput_ab_benchmark import run_one_level  # noqa: E402

# Small latency and job count keep this test fast (well under a second of real sleep
# per level) while still being long enough, relative to thread/ledger-I/O overhead,
# that a genuine speedup signal is measurable and not noise. This test asserts the
# RATIO holds; scripts/benchmarking/tc046_throughput_ab_benchmark.py is the
# realistically-scaled-latency measurement (TC-APT-064 p95 x 0.1) whose actual numbers
# are reported separately.
_TEST_LATENCY_SECONDS = 0.05
_SOURCES_PER_LOCALE = 8
_LOCALES = ("es", "fr")


def test_max_parallel_jobs_4_is_faster_than_serial_through_real_campaign_runner(tmp_path):
    serial = run_one_level(
        level=1,
        latency_seconds=_TEST_LATENCY_SECONDS,
        sources_per_locale=_SOURCES_PER_LOCALE,
        locales=_LOCALES,
        scratch_root=tmp_path,
    )
    parallel = run_one_level(
        level=4,
        latency_seconds=_TEST_LATENCY_SECONDS,
        sources_per_locale=_SOURCES_PER_LOCALE,
        locales=_LOCALES,
        scratch_root=tmp_path,
    )

    # Every job must have actually run and been accepted at both levels -- a
    # "speedup" from dropped or failed work would be worthless.
    assert serial["jobs_accepted"] == serial["total_jobs"] == 16
    assert parallel["jobs_accepted"] == parallel["total_jobs"] == 16
    assert serial["campaign_status"] == "COMPLETE"
    assert parallel["campaign_status"] == "COMPLETE"

    # The rollback switch (TC-APT-046 step 1) is exercised on the correct side at
    # each level: level 1 matches today's shipped serialized default, level 4
    # matches the wave23 canary's --no-force-serialize.
    assert serial["force_serialize"] is True
    assert parallel["force_serialize"] is False

    # The engine must have actually SEEN overlapping calls at level 4 (proves the
    # ThreadPoolExecutor really ran jobs concurrently, not just that the config
    # value was accepted) and must NOT have overlapped at level 1 (proves the
    # serial baseline is genuinely serial, not accidentally already parallel).
    assert serial["peak_observed_concurrency"] == 1
    assert parallel["peak_observed_concurrency"] == 4

    # The actual throughput claim: real wall-clock time dropped by a comfortable
    # margin. Ideal would be ~4x; require at least 2x so ordinary CI machine jitter
    # can never flake this, while still being far outside the "no benefit" wave23
    # found when jobs-per-shard was 1.
    speedup = serial["wall_clock_seconds"] / parallel["wall_clock_seconds"]
    assert parallel["wall_clock_seconds"] < serial["wall_clock_seconds"] / 2
    assert speedup >= 2.0


def test_max_parallel_jobs_1_never_overlaps_calls(tmp_path):
    """The serial baseline itself must be genuinely serial -- the control for the
    speedup claim above."""
    result = run_one_level(
        level=1,
        latency_seconds=_TEST_LATENCY_SECONDS,
        sources_per_locale=_SOURCES_PER_LOCALE,
        locales=_LOCALES,
        scratch_root=tmp_path,
    )
    assert result["peak_observed_concurrency"] == 1
    assert result["engine_call_count"] == result["total_jobs"]


@pytest.mark.parametrize("level", [4, 8])
def test_higher_max_parallel_jobs_achieves_full_configured_overlap(tmp_path, level):
    """Peak observed concurrency must reach the configured level exactly (not less --
    that would mean the ThreadPoolExecutor sizing is wrong -- and not more, which
    would be a correctness bug), given a shard large enough to accommodate it."""
    result = run_one_level(
        level=level,
        latency_seconds=_TEST_LATENCY_SECONDS,
        sources_per_locale=_SOURCES_PER_LOCALE,
        locales=_LOCALES,
        scratch_root=tmp_path,
    )
    assert result["peak_observed_concurrency"] == level
    assert result["jobs_accepted"] == result["total_jobs"]
