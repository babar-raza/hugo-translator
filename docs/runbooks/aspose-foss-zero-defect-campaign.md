# Aspose FOSS zero-defect campaign

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
