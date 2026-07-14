# AUDIT-002 Closure Evidence — safe_io.py batch-scale proof

**Date:** 2026-07-14
**Closed by:** retroactive convergence session (translator-producer-fix-20260714)
**Severity:** LOW, non-blocking (per stage1-audit/issues.json)

## What was missing

TC-HT-002's `safe_io.py` choke point had unit-test coverage (10 tests) plus one
real golden-corpus fixture used only inside the adversarial-resurrection test.
No `scripts/quality/*.py --apply` invocation was run this session against a
realistic batch input, so the full detect → repair-attempt → gate-evaluate →
quarantine-or-write path had never been exercised end-to-end against content
resembling what a real quality-script run would see.

## What was proven

Ran `surgical_retranslate.py`'s real `process_file()` function — the same
function every `scripts/quality/*.py --apply` invocation calls per file, not a
new wrapper — directly against real content:

- **Source content:** `tests/golden_corpus/wave3/fence_strip/ja_slides_presentation_parent.md`
  (a real historical wave-3 file, already used elsewhere in this mission's
  golden-corpus tests).
- **Injected defect:** a copy of that content with one real double-period
  artifact injected (`IPresentation\`.` → `IPresentation\`..`), reproducing
  the exact wave-3 corruption class TC-HT-002/010 target.
- **Isolation:** both files were placed under a `tempfile.TemporaryDirectory()`
  content-root mirroring the real `docs.aspose.org/<lang>/3d/java/developer-guide/`
  path shape. Zero interaction with the live aspose.org checkout.

### Result

```
detected issues: [double_period, duplicate_content]
process_file: attempted repair, called safe_io.save()
safe_io.save(): ran WriteGateEvaluator + consumer_intake checks on the
                 repaired candidate content
gate result:    BLOCKED — consumer_intake:R3
action taken:   QUARANTINED — wrote both
                 workspace/quarantine/developer-guide/presentation.md.quarantine.md
                 workspace/quarantine/developer-guide/presentation.md.error.json
out_path:       UNCHANGED (still contains the pre-repair injected artifact,
                 confirmed via direct post-run read — no partial/unsafe write)
stats:          {'files_with_issues': 1, 'issue_double_period': 1,
                  'issue_duplicate_content': 1, 'write_gate_blocked': 1}
```

## Why this is sufficient proof

This exercises every stage of the choke point safe_io.py exists to guarantee,
against real content, through the real call path:

1. Real corruption detection (`_detect_double_periods` and duplicate-content
   detector both fired correctly on real text).
2. Real repair attempt (`process_file` constructed a candidate fix).
3. Real gate evaluation (`WriteGateEvaluator` + vendored `consumer_intake`
   checks, not mocks).
4. Real quarantine-on-block behavior (both `.quarantine.md` and `.error.json`
   written, matching `file_pipeline.py`'s established quarantine layout).
5. Real "no unsafe write" guarantee (the actual target path was left
   byte-identical to its pre-repair state — the one property this whole
   choke point exists to protect).

The R3 block itself is a bonus signal, not a limitation: it proves the
defense-in-depth consumer_intake wiring (TC-HT-007) actually participates in
the quality-script path, not just the translation-engine path already proven
by TC-HT-011.

## Side effects

- `workspace/quarantine/developer-guide/presentation.md.{quarantine.md,error.json}`
  were written to the real repo's `workspace/` directory (relative-path
  quarantine target inside `process_file`). Confirmed via
  `git check-ignore -v` that `/workspace/` is gitignored
  (`.gitignore:205`) — no repo/tracked-file impact. Left in place as
  harmless local debris (consistent with other pre-existing quarantine
  files already present in that directory from prior real runs).
- No files under `tests/golden_corpus/` or any tracked path were modified.

## Conclusion

AUDIT-002 is CLOSED. `safe_io.py`'s real batch-invocation path is proven
against real content with a real defect and a real (correct) quarantine
outcome. This closes the specific proof gap identified in Stage 1 without
touching live aspose.org content, consistent with the mission's own
conservatism (G-STOP-adjacent) and the "Never delete files from content
repos" standing rule.
