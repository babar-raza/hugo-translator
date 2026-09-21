# TC-APT-046: schema-ceiling raise + max_parallel_jobs throughput A/B measurement

**Taskcard:** TC-APT-046 ("Concurrency rollout"), plan
`hugo-translator-aspose-org-partitioned-kahn.md` (revision 13).
**Depends on evidence from:** TC-APT-064 (sustained-load calibration) and the
wave23-cells-go canary (concurrency-safety, recorded in TC-APT-046's own
taskcard note).
**Date:** 2026-09-09.

This document is the human-readable writeup of the raw evidence in
`data/summaries/tc-apt-046-throughput-measurement-*.json`. Nothing here is
estimated except the deliberately-scaled simulated latency, which is called
out explicitly below.

## 1. What TC-APT-046 still had open

Per the taskcard's own plan text, two things remained after TC-APT-064 and
the wave23 canary landed:

1. **The schema-ceiling raise itself** -- `src/workers/llm_slot_semaphore.py`'s
   `DEFAULT_CAPACITY` and `src/workers/campaign_manifest.py`'s validated
   `max_parallel_jobs` range were both still gated on "until TC-APT-064
   proves a higher sustained ceiling," which it has now done (64, clean).
2. **The throughput half of the max_parallel_jobs canary.** wave23 proved
   concurrency is *safe* at `max_parallel_jobs=4` but explicitly could not
   measure a throughput benefit: real campaign shard/job structure meant only
   one locale shard ran roughly every ~8 minutes through 22 total --
   sequential SHARD cadence swamped any in-shard THREAD-parallelism signal.
   Nobody had cleanly isolated whether `max_parallel_jobs > 1` gives a real
   wall-clock speedup through the real `CampaignRunner` path.

## 2. Ceiling raise applied

| Location | Old | New | Evidence cited in code |
|---|---|---|---|
| `src/workers/llm_slot_semaphore.py:36` `DEFAULT_CAPACITY` | `8` | `64` | TC-APT-064 sustained probe, see module docstring |
| `src/workers/campaign_manifest.py` `max_parallel_jobs` validated range | `1..4` | `1..64` | Same evidence, cited inline above the check |

Both changes point at
`data/benchmark_corpus/results/professionalize_llm_calibration_tc064_sustained_20260906.json`:
16/32/48/64 concurrent `professionalize_llm` calls held 450s each (3611 calls
total), 0 errors and 0 rate-limited at every level. `sustained_safe_ceiling=64`
is documented as a floor, not a measured max -- the probe did not find a
ceiling within the tested range.

**Important gap found while applying this, flagged for the orchestrating
session:** `config/global.yaml`'s `translation_engine.llm_slot_semaphore.capacity`
is still hardcoded to `8`, and both call sites that actually size an
`LLMSlot` in production (`src/model_runtime/llm_backend.py:211` and
`src/workers/llm_slot_semaphore.py:54`'s `slot_from_config()`) read that
config value FIRST, falling back to `DEFAULT_CAPACITY` only when the config
key is absent. **Raising `DEFAULT_CAPACITY` in code therefore has zero effect
on production behavior until `config/global.yaml`'s `capacity: 8` is also
raised** -- that file was outside this task's allowed-paths list
(`src/workers/`, `scripts/benchmarking/`, `tests/`, `data/summaries/`,
`docs/operations/`, one taskcard-status JSON), so it was deliberately left
untouched here. The orchestrating session should update
`config/global.yaml`'s `translation_engine.llm_slot_semaphore.capacity` (and
review its neighboring comment, currently "capacity stays at 8 until
TC-APT-064's sustained-load calibration proves a higher ceiling") to actually
realize this ceiling raise.

A second, unrelated boundary was found and deliberately NOT touched:
`scripts/campaign/launch_parallel_campaign_shards.py:411` enforces its own
separate `--max-workers must be 1..4` (process-level shard-launcher
parallelism, TC-APT-047's lever). This task's evidence and scope are about
`max_parallel_jobs` (in-process thread-level job parallelism inside one
`CampaignRunner`) and the LLM slot semaphore only -- the plan text names
`campaign_manifest.py`'s `max_parallel_jobs` range specifically as "the
schema ceiling," not the shard-launcher's process count, and TC-APT-064's
calibration was against in-flight API call concurrency, not OS process count.

No test hardcoded the old `1..4` / `DEFAULT_CAPACITY=8` boundary as an
expected value (searched `tests/` for `max_parallel_jobs.*4`, `1\.\.4`,
`DEFAULT_CAPACITY`, `capacity=8`, `!= 8`) -- the two source locations above
were the only places the ceiling was enforced.

## 3. Throughput measurement

**Method:** `scripts/benchmarking/tc046_throughput_ab_benchmark.py` builds a
disposable synthetic git repo (never the real content repo, never
`data/campaigns/`) with 16 synthetic source pages, each targeting 2 locales
(es, fr) -- 32 total jobs, grouped by `CampaignManifest.shards()` into 2
shards of 16 jobs each (same wave/site/family/platform, one shard per
locale). This is the "genuinely multiple jobs per shard" condition wave23
lacked. A `FakeLLMEngine` stands in for the real translation engine's
`translate_file()` -- the one call `CampaignRunner` threads across a shard's
jobs -- sleeping a simulated latency and returning a valid accepted
translation on the first attempt (no network, no real model). The manifest's
`retry_policy.primary_model` is `professionalize_llm` so that single
successful call is explicitly the one whose latency TC-APT-064 measured.
Each level runs through the REAL `CampaignRunner.run()` -> `_run_locked()` ->
`ThreadPoolExecutor(max_workers=min(max_parallel_jobs, len(shard["jobs"])))`
-> `_run_campaign_job()` path; only `verify()` (git/environment fingerprint
checks) and `_commit_verified_outputs` (git staging/commit) are stubbed,
exactly as the repo's own existing regression test for job overlap
(`test_campaign_parallel_jobs_share_engine_without_cross_job_state` in
`tests/unit/workers/test_campaign_manifest.py`) already does -- this
benchmark's subject is the scheduler, not environment verification or git
plumbing. **No git commit is ever made by this benchmark.**

**Simulated latency and scaling:** TC-APT-064 measured p95 latency
26.2-28.7s across concurrency levels 16-48 (28.7s at 64). This benchmark uses
a representative p95 of **27.5s** (the midpoint) scaled by a documented
factor of **0.1**, i.e. each simulated call sleeps **2.75s**. The absolute
number does not matter for this measurement -- only the RATIO between
`max_parallel_jobs` levels does, and every level uses the identical scale
factor so that ratio is preserved. A shorter latency keeps the full sweep
under two minutes instead of the many-minutes-to-hours a real 27.5s/call x 32
calls at `max_parallel_jobs=1` would take.

**Result** (`data/summaries/tc-apt-046-throughput-measurement-20260909T215652.json`):

| `max_parallel_jobs` | `force_serialize` | Jobs accepted | Peak observed concurrency | Wall-clock | Speedup vs serial |
|---:|:---:|---:|---:|---:|---:|
| 1 | true (today's default) | 32/32 | 1 | 88.907s | 1.000x |
| 4 | false | 32/32 | 4 | 22.405s | 3.968x |
| 8 | false | 32/32 | 8 | 11.535s | 7.708x |
| 16 | false | 32/32 | 16 | 6.070s | 14.647x |

Every level completed all 32 jobs with `campaign_status: COMPLETE` and zero
failures. `peak_observed_concurrency` (an independent counter inside
`FakeLLMEngine`, not the configured input) exactly matched the configured
`max_parallel_jobs` at every level, confirming the `ThreadPoolExecutor` is
actually scheduling that many concurrent calls, not merely accepting the
config value. Speedup tracks very close to the ideal linear ratio (4x, 8x,
16x) with only a few percent of overhead at the higher levels (thread
startup, per-job file I/O, ledger locking) -- there is no sign of contention
or diminishing returns within this range.

**Conclusion: `max_parallel_jobs > 1` gives a genuine, large wall-clock
speedup through the real `CampaignRunner` path when a shard actually has
multiple jobs.** wave23's inability to observe a benefit was a property of
the specific campaign it ran (single-source-per-locale manifests degenerate
to one job per shard), not evidence that in-process concurrency is
ineffective. Realizing this benefit in production requires either
multi-source manifests (several pages queued together per locale) or relying
on TC-APT-047's process-level shard launcher instead/in addition, as that
taskcard's own closure note already concluded.

A permanent, CI-fast regression test
(`tests/integration/test_campaign_runner_max_parallel_jobs_throughput.py`,
4 tests) pins the same mechanism at a much smaller scale (0.05s simulated
latency, 8 sources x 2 locales) so this conclusion cannot silently regress:
it asserts real wall-clock speedup >= 2x at `max_parallel_jobs=4` vs. `=1`,
that `peak_observed_concurrency` reaches the configured level exactly, and
that the serial baseline never overlaps calls.

## 4. Confirmation of constraints

- **No real network call was made.** `FakeLLMEngine` is a pure in-process
  Python object; nothing in the benchmark or its test imports an HTTP client
  or any real LLM provider/backend.
- **No real content repo or `data/campaigns/` was touched.** The benchmark
  only ever writes under `.local/tc046_throughput_bench/` (gitignored,
  matching the existing `scripts/benchmarking/gpu_concurrency_bench.py`
  convention) or, for the pytest test, `tmp_path`.
- **No git commit was made anywhere in this task's work**, per the hard
  constraint -- the benchmark's own scratch git repos only ever receive one
  `git commit` of the synthetic baseline content (needed so `sha256_file()`
  has real bytes to hash); `_commit_verified_outputs` is stubbed to a no-op
  so `CampaignRunner` itself never invokes git.
- `config/global.yaml`'s `translation_engine.concurrency.force_serialize_all_backends`
  was not touched, and is not read directly by the benchmark -- `run_one_level`
  sets `CampaignRunner._force_serialize` directly per level instead (`True`
  for `max_parallel_jobs=1`, matching that flag's shipped default; `False`
  otherwise, matching the wave23 canary's `--no-force-serialize`), exactly
  the same pattern the repo's own `test_campaign_parallel_jobs_share_engine_without_cross_job_state`
  test already uses to isolate this from the real config file.

## 5. Test results

```
.venv\Scripts\python.exe -m pytest tests/unit/workers/test_campaign_manifest.py tests/unit/workers/test_llm_slot_semaphore.py tests/unit/workers/test_llm_preflight_calibration.py tests/regression/test_backend_generation_concurrency.py tests/unit/workers/test_campaign_replace_existing_and_dirty_scope.py tests/regression/test_nllb_permanent_non_use.py -q
114 passed in 33.92s

.venv\Scripts\python.exe -m pytest tests/integration/test_campaign_runner_max_parallel_jobs_throughput.py -v
4 passed in 16.17s

.venv\Scripts\python.exe -m pytest tests/unit/workers/ -q
759 passed, 1 skipped in 164.66s
```

## 6. Recommendation

- Apply the `config/global.yaml` `llm_slot_semaphore.capacity` fix noted in
  Section 2 before considering this ceiling raise fully live in production --
  the code-level `DEFAULT_CAPACITY=64` change alone does not change runtime
  behavior while that config key still says `8`.
- The throughput evidence in Section 3 supports raising `max_parallel_jobs`
  above 1 in any manifest whose shards genuinely batch multiple sources per
  locale; it says nothing new about single-source-per-locale campaigns, which
  should keep relying on TC-APT-047's process-level shard launcher for
  throughput instead.
- This task did not re-verify concurrency SAFETY (cross-contamination,
  frontmatter integrity) at any level above 4 -- that evidence is wave23's
  (max_parallel_jobs=4 only) and TC-APT-064's (raw API concurrency, not
  through `CampaignRunner`). Whoever raises a live manifest's
  `max_parallel_jobs` above 4 should treat that as a still-open safety
  question, separate from the throughput question this document answers.
