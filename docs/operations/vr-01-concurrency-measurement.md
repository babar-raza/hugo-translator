# VR-01: Multi-process m2m100_418M CUDA concurrency measurement

**Taskcard:** VR-01, `plans/healing/campaign-tm-concurrency-operations-healing-20260908.md`
**Gap:** CO-04 -- "One 418M process uses far less than the 80% VRAM budget;
multiple model processes need a measured, claimed, safe parallel design."
**Date:** 2026-09-09. **Hardware:** RTX 4090 Laptop GPU, 16,376 MiB total,
Windows/WDDM driver 616.56, torch 2.7.1+cu118 (CUDA 11.8), Alienware m18 R2.

This document is the human-readable writeup of the raw evidence in
`data/summaries/vr-01-concurrency-measurement-*.json`. Nothing here is
estimated -- every number was read from a real subprocess measurement on
this machine.

## 1. Probe visibility experiment: nvidia-smi vs `torch.cuda.mem_get_info()`

Before building the admission controller, the two candidate live-VRAM
signals were compared for whether either actually reflects a **different
process's** allocation (both are nominally "device-wide" by API contract,
but that had to be checked, not assumed).

Method: an unrelated "holder" process allocates a real CUDA tensor and
sleeps; a separate "observer" process (no allocation of its own) queries
both signals.

| Holder's real allocation | `nvidia-smi` used (observer's view) | `torch.cuda.mem_get_info()` implied used (observer's view) |
|---|---|---|
| 0 MiB (holder not running) | 0 MiB | 1301.5 MiB |
| ~512 MiB | 967 MiB (760 MiB holder + 208 MiB observer's own context) | 1301.5 MiB |
| ~4096 MiB | 4551 MiB (4344 MiB holder + ~208 MiB observer's own context) | 1301.5 MiB |

`nvidia-smi` tracked the holder's allocation exactly and returned to ~0 the
moment the holder exited. `torch.cuda.mem_get_info()` returned the **identical**
`free_mib=15074.0` / `total_mib=16375.5` in all three cases -- it did not move
at all in response to a sibling process consuming up to 4 GiB. This was
reconfirmed a fourth and fifth time under real (not synthetic) concurrent
m2m100 load, mid-benchmark (see `mid_run_cross_check_mem_get_info_vs_nvidia_smi`
in the level-6 and level-8 summary files): `nvidia-smi` read 1452 MiB and then
1866 MiB as more real model processes came up, while `mem_get_info()` read the
same static 1301.5 MiB both times.

**Conclusion, used to drive the admission controller's design:** on this
machine's Windows/WDDM driver, `torch.cuda.mem_get_info()` is **not** a
reliable cross-process signal despite wrapping the device-wide
`cudaMemGetInfo` CUDA API -- it appears to return a fixed/cached figure that
does not track sibling processes' real usage. `nvidia-smi` is accurate,
device-wide, and immediate. **`src/hardware/gpu_admission.py` therefore uses
`nvidia-smi` as the primary VRAM probe**, with `mem_get_info()` retained only
as a last-resort fallback (explicitly labelled `"torch.cuda.mem_get_info
(UNVERIFIED cross-process visibility)"` in telemetry) for the case where
`nvidia-smi` itself cannot be invoked at all.

This reversed the initial design assumption stated in VR-01's brief (that
`mem_get_info()` might be the "truer" figure) -- the empirical check the
brief asked for was necessary and changed the outcome.

## 2. Admission controller

New module: `src/hardware/gpu_admission.py` (`GPUAdmissionController`,
factory `make_admission_controller()`). Deliberately a sibling to
`src/hardware/resource_governor.py`, not an extension of it -- see the
module's own docstring for the full rationale. Summary:

- Reuses `ResourceGovernor`'s proven file-lock (`portalocker`) + JSON
  registry + PID-validated stale-cleanup pattern, in its own registry/lock
  files (`.local/gpu_admission_registry.json` by default) so the two
  controllers never race each other.
- Two independent denial checks, either can refuse admission:
  1. **Thermal**: current `nvidia-smi` temperature >= configured ceiling.
  2. **VRAM**, checked two ways so neither signal is trusted alone:
     - Reservation ledger (sum of every registered process's declared
       per-model MiB reservation) -- protects against the TOCTOU race where
       a sibling has been granted a slot but hasn't finished loading its
       model yet, so a live probe can't yet see its footprint.
     - Live `nvidia-smi` probe -- catches VRAM used by anything **not**
       going through this controller.
- Config: new `gpu_admission:` block in `config/global.yaml` (`enabled:
  false` -- advisory only; nothing reads this controller in production yet).
- Tests: `tests/unit/hardware/test_gpu_admission.py`, 25 tests, all using
  dependency-injected fake probes (no GPU/nvidia-smi needed in CI). **Result:
  `25 passed` (see Section 5).**

## 3. Real concurrency measurement

Benchmark: `scripts/benchmarking/gpu_concurrency_bench.py`. Synthetic input
only: `tests/fixtures/gpu_bench/synthetic_en.md` (10 short dummy English
sentences, invented for this benchmark, never `data/campaigns/` or the
content repo). Each worker is an independent OS process: it optionally goes
through `GPUAdmissionController.request_admission()` against a shared
registry, loads `m2m100_418m` from the locally cached weights
(`models/m2m100_418m`, no network), applies the same 40%/6,550 MiB
`VRAMEnforcer` per-process cap used in VR-01's prior manual rehearsal,
translates the fixture (en->es, 10 sentences/batch x 5 iterations = 50
translations/worker, `max_new_tokens=40`, greedy decoding), unloads, and
exits. The orchestrator samples `nvidia-smi` once/second throughout and
enforces a 240-300s per-level timeout with a kill fallback (never triggered).

| Concurrency N | Peak `nvidia-smi` VRAM (device-wide) | Peak temp | Per-process `torch.cuda.memory_allocated` after load | Workers OK / failed | Accepted translations | Aggregate translations/sec |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 1,274 MiB | 61 C | 927.0 MB | 1 / 0 | 50 | 11.25 |
| 2 | 2,547 MiB | 63 C | 927.0 MB | 2 / 0 | 100 | 20.75 |
| 3 | 3,820 MiB | 65 C | 927.0 MB | 3 / 0 | 150 | 28.70 |
| 4 | 5,094 MiB | 65 C | 927.0 MB | 4 / 0 | 200 | 33.81 |
| 6 | 7,640 MiB | 66 C | 927.0 MB | 6 / 0 | 300 | 43.98 |
| 8 | 8,914 MiB | 67 C | 927.0 MB | **7 / 1** | 350 | 42.89 |

VRAM scales almost perfectly linearly at **~1,273 MiB per process** as seen
by `nvidia-smi` (927 MB is PyTorch's own `memory_allocated()` figure for that
process; the remainder is CUDA context + reserved-but-unallocated overhead,
consistent with the ~208-346 MiB single-context overhead measured in Section
1). Temperature rose only 61 C -> 67 C across the whole 1..8 sweep -- nowhere
near the existing `resource_governance.temperature_warn_celsius: 78` /
`temperature_kill_celsius: 83` thresholds. Throughput scaled positively
through 6 concurrent processes (diminishing marginal return per added
process, as expected from shared SM contention on one physical GPU) and
essentially plateaued/regressed slightly at 8 -- consistent with the failure
below rather than a real compute ceiling.

### The one real failure: level 8, one worker

At N=8, worker `L8-W4` failed during model load with:

```
RuntimeError: Failed to load HuggingFace model m2m100_418m: The paging file
is too small for this operation to complete. (os error 1455)
```

This is a **Windows host-memory/pagefile** failure, not a GPU VRAM or
thermal one -- 8 simultaneous cold-start model loads (each doing CPU-side
tensor materialization, tokenizer loading, etc. before `.to("cuda")`) spiked
committed virtual memory past what the pagefile could satisfy at that
instant. The other 7 workers loaded and completed normally; GPU VRAM
returned to 0 MiB and no process was left orphaned (verified below). Two
relevant caveats for interpreting this number:

1. This machine was **not idle** at the time -- unrelated peer-fleet
   `pytest` processes (a different mission session, per this mission's
   documented multi-session-fleet operating model) and an unrelated
   `repository-presenter` test suite were running concurrently on the same
   host, each consuming their own host RAM. This makes the level-8 failure
   arguably **more**, not less, representative of real production
   conditions, where this host is never expected to run only one campaign
   process in isolation.
2. It is a load-time (transient, "thundering herd") failure, not a
   steady-state one -- once loaded, each process only holds ~927 MB
   resident. A staggered/ramped launch (rather than 8 simultaneous cold
   starts) would likely avoid it at the same eventual concurrency, but that
   was not tested here and should not be assumed without evidence.

No further levels (10+) were attempted once this failure surfaced, both
because it is a real fault on a shared machine (unwise to keep escalating
host-memory pressure against a live fleet) and because it already gives a
clear, evidence-based boundary.

## 4. Admission-controller deny/grant smoke test (real telemetry, real hardware)

Run automatically at the start of every benchmark invocation
(`admission_controller_smoke_test` in each summary JSON), using **real**
`nvidia-smi`/temperature readings both times -- only the configured ceiling
differs:

- Tiny fake budget (0.5% of 16,376 MiB = ~82 MiB): a 1,100 MiB reservation
  request was **denied** -- `"reservation ledger 1100MiB exceeds budget
  82MiB (0% of 16376MiB)"`.
- Real production-scale budget (80% = ~13,101 MiB): the same request was
  **granted** -- `"granted (reserved 1100MiB / live 1100MiB <= budget
  13101MiB)"`.

`deny_grant_behavior_confirmed: true` in every run. This was also exercised
per-worker at every concurrency level via a shared registry file per level
(`admission_used: true`), and no real worker was ever denied by VRAM/thermal
in the 1..8 sweep -- consistent with the measured numbers above (even 8
processes only claim ~68% of the 80% VRAM budget, and temperature stayed
~13-19 C under the thermal ceiling).

## 5. Test results

```
.venv\Scripts\python.exe -m pytest tests/unit/hardware/test_gpu_admission.py -q
25 passed in 3.44s

.venv\Scripts\python.exe -m pytest tests/unit/hardware/ -q
60 passed in 4.02s   (includes the pre-existing ResourceGovernor and VRAMEnforcer suites -- no regressions)
```

## 6. Recommendation

- **VRAM is not the binding constraint** for `m2m100_418m` concurrency on
  this GPU: at ~1,273 MiB/process, the 80% (13,101 MiB) budget has room for
  roughly 10 processes before VRAM itself would deny admission.
- **Thermal is not the binding constraint** either in this range: 67 C peak
  at N=8 is far below both the admission ceiling (80 C) and the existing
  `resource_governance` kill threshold (83 C).
- **The real, measured ceiling in this experiment is host-memory
  (pagefile) pressure during simultaneous cold-start model loading**,
  observed once at N=8 and not at N=6. This is a different failure mode
  from anything `ResourceGovernor`'s SM-weight design or this VRAM/thermal
  admission controller currently protect against.
- **Recommendation:** treat **N=6 concurrent `m2m100_418m` processes** as
  the evidence-backed safe ceiling from this measurement (clean at 1, 2, 3,
  4, and 6; one real failure at 8; 5 and 7 were not tested). Confidence is
  moderate-high for the GPU-side numbers (VRAM/thermal scaling was
  clean, linear, and repeatable) and lower for exactly where between 6 and 8
  the host-memory ceiling actually sits, since only two points bracket it
  and the host was shared with unrelated concurrent load at the time.
- Before raising real concurrency in production, whoever wires this in
  should additionally consider staggering cold starts (to blunt the
  load-time pagefile spike) rather than relying on VRAM/thermal admission
  alone -- this controller does not currently gate on host memory at all,
  which is an explicit gap, not an oversight.
- Per VR-01's scope boundary, **none of this has been wired into
  `scripts/campaign/launch_parallel_campaign_shards.py`, and
  `max_parallel_jobs` / `concurrency.force_serialize_all_backends` were not
  touched** -- that integration decision belongs to the orchestrating
  session reviewing this evidence.

## 7. Cleanup confirmation

After every level, GPU memory was confirmed back at 0 MiB before starting
the next (`cooldown_gpu_state_after_2s` in each level's JSON). After the
full sweep (including the level-8 failure), `nvidia-smi` showed 0 MiB used
and a process listing showed no `hugo-translator` Python process remaining
-- the only Python processes present were unrelated peer-fleet /
other-repository processes already running before this benchmark started.
No orphaned GPU-holding process was left behind at any point.
