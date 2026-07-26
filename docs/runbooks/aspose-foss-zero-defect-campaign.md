# Aspose FOSS zero-defect campaign

> **Authoritative execution plan — version 2.0.0.** This document supersedes
> the earlier worktree-only handoff for this pilot. Its normalized-content
> SHA-256 (with the value in this field replaced by `<self>`) is recorded in
> `data/campaigns/aspose-foss-25-locales-v1/plan-binding.yaml`. Execution must
> bind to that record before it starts or resumes.

This runbook is the autonomous handoff for the 1,213-source, 25-locale Aspose
FOSS pilot. The campaign is fail-closed: a rejected candidate remains
memory-only, and the runner stops a shard when any job is not accepted.

## Immutable preparation

Use dedicated clean worktrees. Commit the intended translator hardening and
Aspose campaign tooling separately; do not include unrelated changes. Record
both resulting `HEAD` SHAs.

From the clean translator worktree:

```powershell
python scripts/campaign/build_aspose_foss_pilot_manifest.py `
  --content-repo D:/onedrive/Documents/GitHub/aspose.org-pilot `
  --translator-repo . `
  --output config/campaigns/aspose-foss-25-locales.yaml
```

The builder must report exactly 1,213 sources and 30,325 outputs. It refuses a
dirty repository, denominator drift, or missing TM/model fingerprint input.
Do not hand-edit the generated source matrix.

Run the read-only pinned-environment check:

```powershell
python -m src.workers.autonomous_content_translation_worker `
  --mode oneshot `
  --campaign-manifest config/campaigns/aspose-foss-25-locales.yaml `
  --validation-policy zero-defect `
  --verify-only
```

Any existing unreceipted locale output, source hash drift, SHA drift,
configuration/model drift, baseline TM drift, or dirty path is a hard stop.

## Qualification

Before production, run the full translator suite and Aspose focused suite.
Run the fault-injection fixtures for language, fidelity, placeholders, YAML,
shortcodes, code, headings, links, scripts, SEO, homoglyphs, TM collisions,
model failure, crash boundaries, and storage failure. For every rejected case,
assert that no output, quarantine payload, log payload, or TM record exists.

Aspose launch and coverage checks must use strict mode:

```powershell
python scripts/pipeline/commands/launch/launch_gate.py words net --strict
python scripts/pipeline/commands/launch/launch_gate.py html python --strict
python scripts/pipeline/commands/launch/launch_gate.py cells rust --strict
python scripts/pipeline/commands/ops/translation_coverage.py `
  --campaign-manifest <absolute-manifest-path> --strict
```

`WARN` and `SKIP` are failures in strict launch mode.

## Run and resume

The runner orders work by wave, then processes one
`(surface, product, platform, locale)` shard at a time. Shards contain at most
250 outputs and are lexically deterministic.

```powershell
python -m src.workers.autonomous_content_translation_worker `
  --mode oneshot `
  --campaign-manifest config/campaigns/aspose-foss-25-locales.yaml `
  --validation-policy zero-defect
```

After a crash or qualified pipeline fix:

```powershell
python -m src.workers.autonomous_content_translation_worker `
  --mode oneshot `
  --campaign-manifest config/campaigns/aspose-foss-25-locales.yaml `
  --validation-policy zero-defect `
  --resume
```

Resume accepts only an output whose read-back hash matches a metadata-only
receipt containing all 44 passing gates. A campaign lock excludes concurrent
runners. Failure ledgers contain identifiers, gate/reason, attempt, and hashes,
never candidate text.

## Acceptance boundary

The write path is:

1. Serialize candidate bytes in memory.
2. Run verification and all 44 gates under `zero-defect`.
3. Apply auto-cleaning to a fixed point and rerun the entire gate registry.
4. Validate parsing and expected placement against the candidate bytes.
5. Construct an immutable `AcceptedTranslation`.
6. Atomically write its exact bytes with `fsync`.
7. Read back and compare SHA-256.
8. Persist the acceptance receipt.
9. Flush campaign-namespaced TM entries.

Receipt persistence failure or read-back mismatch removes the new output and
stops the job. There is no force-accept or validator-skip route.

The handoff ends on the local
`pilot/foss-localization-zero-defect` branch. Never push from the autonomous
campaign.

## Mission binding and governed baseline

**Mission:** translate the 1,213 pinned English Aspose FOSS sources for
`words/net`, `html/python`, and `cells/rust` on docs, KB, products, blog, and
reference into the 25 profile locales. The mandatory outcome is exactly 30,325
accepted locale files, each backed by an all-44-gates receipt and an
independent fidelity PASS.

**Authoritative content destination:**
`D:\onedrive\Documents\GitHub\aspose.org`. Accepted bytes are written there
directly. A clean output worktree is no longer an execution destination.
The legacy pilot worktree is evidence-only and is never used for new output.

The destination is intentionally dirty with unrelated user work. Before a
campaign run, capture a versioned *frozen dirty baseline* containing every
pre-existing staged, unstaged, and untracked path and its content hash. The
runner must then:

1. allow only manifest-listed, initially absent locale output paths to change;
2. reject a changed baseline path, a changed English source, or an existing
   unreceipted output;
3. never stage, reset, clean, modify, or commit an unrelated baseline path;
4. perform raw-byte atomic write, fsync, read-back SHA-256 verification, and
   receipt persistence on the authoritative destination; and
5. remove a just-created output and hard-stop on storage, checksum, or receipt
   persistence failure.

Existing accepted legacy outputs may be copied only by a receipt-directed
reconciliation: source hash must match, destination must be absent, candidate
bytes must equal the receipt output hash, and the destination read-back hash
must match. Copying is not translation and does not create a second receipt.

## Throughput amendment: shard-local bounded concurrency

The old runner invoked the complete campaign setup per `(source, locale)` job.
That was safe but operationally unacceptable. The replacement preserves the
same per-candidate acceptance boundary while changing scheduling only:

1. select one deterministic `(wave, surface, product, locale, part)` shard;
2. keep reference parts at no more than 250 outputs, with every other shard
   containing all of its eligible sources for that locale;
3. process up to four independent candidates concurrently in the shard;
4. give each candidate isolated parsed state, retry feedback, TM buffer,
   candidate bytes, all 44 gates, independent fidelity judge, and receipt;
5. serialize only the authoritative writer, receipt ledger, and TM flush;
6. run strict coverage, topology, content audit, link checks, Hugo build,
   receipt reconciliation, source-hash check, and path-allowlist check once
   after the shard; and
7. commit only the verified output paths when the user-authorized commit policy
   applies; never push.

Concurrency is a throughput setting, not a quality setting. Start at four
workers only after qualification proves memory headroom, concurrent-worker
exclusion, deterministic receipts, and a no-change resume. On OOM, validator
outage, or an integrity failure, stop the shard, retain metadata-only failure
evidence, reduce to the last qualified capacity, fix the root cause, rerun its
regression and qualification tests, and resume. No candidate text from a
rejected attempt may be logged, quarantined, materialized in a temp file, or
stored in TM.

## Requirement and task register

| ID | Requirement / finding | Owner | Proof target | State |
|---|---|---|---:|---|
| R1 | Bind the source/output matrix and pins to the real Aspose repository. | campaign runner | 5 | IN_PROGRESS |
| R2 | Preserve the pre-existing dirty destination while allowing only accepted outputs. | campaign runner | 5 | TODO |
| R3 | Keep every rejected candidate memory-only and require an immutable all-pass receipt before any write/TM flush. | translation engine | 5 | IMPLEMENTED_UNVERIFIED |
| R4 | Replace per-job campaign startup with bounded shard-local concurrency. | campaign runner | 4 | TODO |
| R5 | Requalify fault injection, direct write, resume, topology, and all 25 locales. | verification | 5 | TODO |
| R6 | Run canary, production waves, closure, reconciliation, and adversarial review. | campaign coordinator | 5 | TODO |

Task transitions are `TODO → READY → IN_PROGRESS → IMPLEMENTED → VERIFIED →
REVIEWED → CLOSED`. A task cannot close on implementation or a focused unit
test alone. Every task retains its raw command output and current plan binding
in the campaign evidence directory. There are no waiver, force-accept,
validator-disable, manual-spot-check, or warning-accept paths.

## Execution sequence and recovery

1. Write `plan-binding.yaml`, frozen-dirty-baseline metadata, the direct-repo
   manifest, and an exact source/output/receipt reconciliation for the 36
   legacy accepted outputs.
2. Implement and unit-test destination-baseline protection and direct receipt
   reconciliation before enabling any new write against the real repository.
3. Implement and unit-test bounded worker scheduling. Tests must prove one
   writer, no shared mutable candidate/TM state, manifest ordering, resume
   idempotency, and a hard failure on a second runner.
4. Run the full relevant translator baseline and Aspose strict checks; execute
   the declared fault-injection suite, including storage and crash boundaries.
5. Rebuild and pin the v2 manifest from the authoritative repository. It must
   contain exactly 1,213 sources and 30,325 outputs, the 25 declared locales,
   model/config/TM/knowledge fingerprints, output allowlist, direct-destination
   baseline fingerprint, retry policy, and wave/commit partitioning.
6. Run the all-surface stratified canary under the new runner. Continue only if
   all receipts pass, every strict post-shard gate passes, and direct-repository
   reconciliation is exact.
7. Run the five production waves; a persistent failure triggers reproduce →
   regression fixture → root-cause repair → qualification → resume. It never
   becomes an accepted output or a waived job.
8. Independently enumerate the matrix and run final all-locale builds, strict
   links/coverage/topology/content checks, fallback-English detection, receipt
   one-to-one reconciliation, dirty-baseline integrity, and fresh adversarial
   review. Only then write the `PUBLISH` evidence verdict; do not publish.

The only terminal success condition is `ACCEPTED_VERIFIED`: 1,213 unchanged
sources, 30,325 expected and accepted outputs, zero failed/blocked/warned/
waived/stale/unexpected jobs, zero unaccepted TM entries, no destination
baseline drift, and all declared consumer checks passing. A blocked outcome is
permitted only after three materially distinct safe recovery paths have been
exhausted and the exact external dependency and resume condition are recorded.
