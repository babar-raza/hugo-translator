# TC-DCF-021 evidence backfill (2026-07-27)

`taskcard-status.yaml` cites this directory as TC-DCF-021's evidence path, but
it did not exist on disk as of 2026-07-27 (verified: directory absent before
this file was written). The underlying work is real and independently
reverified this session rather than taken on trust — see below.

## What was independently verified

`scripts/quality/audit_all_content.py:144-198` (`_git_fingerprint`,
`audit_run_metadata`) is present in the working tree and implements exactly
what TC-DCF-021 describes: live purity-threshold resolution
(`get_purity_threshold(lang)` per `NON_LATIN` language, matching the write
gate's own default/override semantics) and a metadata sidecar carrying
resolved config SHA-256, this repo's git fingerprint, each content root's git
fingerprint (bounded 5s `rev-parse`/`status --porcelain`, falling back to
`dirty: None` + an explicit `status_error` rather than guessing when the
bound is exceeded — deliberately conservative, not a defect), and the cached
FastText model's SHA-256 when present.

`tests/unit/quality/test_audit_all_content_reproducibility.py` exists and
covers exactly this:

- `test_audit_thresholds_match_live_gate_default_and_override`
- `test_metadata_contains_resolved_inputs_and_model_hash_field`
- `test_default_threshold_surfaces_a_ten_percent_purity_issue_but_lt_override_does_not`
- `test_content_sha_survives_a_bounded_dirty_status_timeout` — this is the
  specific regression guard for the "large content checkout makes `git
  status` exceed the bound" case; it proves the fallback path (SHA retained,
  `dirty` explicitly unknown) rather than a crash or a guessed value.

Rerun this session as part of the full 10-file / 57-test v2 focused suite
(see the sibling `v2-consumer-sweep` backfill note for the exact command and
result). `git diff --stat 1261521 -- tests/unit/quality/test_audit_all_content_reproducibility.py`
confirms +53 lines, uncommitted at verification time.

## Note on the content-repo dirty flag specifically

A bounded 50-second `git status --porcelain` against the live content
checkout completed this session (~50s), whereas the code's own bound is a
much tighter 5 seconds (`audit_all_content.py:154-156`). This does **not**
mean the 5-second bound is wrong or should be widened: a 5s cap keeps a
routine audit run fast on every site's content root, and the fallback
behavior (retain the SHA, mark `dirty` as explicitly unknown with a recorded
`status_error`) is the correct, already-tested design for a large,
occasionally-slow checkout — not a gap to close. No code change made or
recommended here.

## Disposition

Treat this directory's absence as a governance-bookkeeping gap in the
original v2 session, not a code gap. No further implementation action
required for TC-DCF-021.
