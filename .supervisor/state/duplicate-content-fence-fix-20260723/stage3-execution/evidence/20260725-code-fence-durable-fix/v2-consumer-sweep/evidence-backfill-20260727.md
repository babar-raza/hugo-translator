# TC-DCF-020 evidence backfill (2026-07-27)

`taskcard-status.yaml` cites this directory as TC-DCF-020's evidence path, but
it did not exist on disk as of 2026-07-27 (verified: directory absent before
this file was written). The underlying work is real and independently
reverified this session rather than taken on trust — see below.

## What was independently verified

`tests/unit/quality/test_audit_all_content_code_regions.py` exists and covers
exactly TC-DCF-020's stated acceptance check ("each detector has code-only
negative and prose-positive coverage"):

- `test_artifact_is_ignored_in_code_but_detected_in_prose`
- `test_shortcode_is_ignored_in_code_but_detected_in_prose`
- `test_eu_phrase_is_ignored_in_code_but_detected_in_prose`
- `test_relative_link_is_ignored_in_code_but_detected_in_prose`

`tests/unit/quality/test_audit_all_content_inline_code.py` exists and verifies
`inline_code_translated` behavior was left intact by this mission (not
migrated here by design — owned by a separate, concurrent shared-primitive
effort).

Rerun this session, together with the rest of the v2 focused suite:
`.venv/Scripts/python.exe -m pytest tests/unit/quality/test_fence_spans.py
tests/unit/translation_engine/test_fence_spans.py
tests/unit/quality/test_audit_all_content_check_purity.py
tests/unit/quality/test_audit_all_content_duplicate_content.py
tests/unit/quality/test_audit_all_content_english_headings.py
tests/unit/quality/test_audit_all_content_gate26.py
tests/unit/quality/test_audit_all_content_registry_gates.py
tests/unit/quality/test_audit_all_content_code_regions.py
tests/unit/quality/test_audit_all_content_inline_code.py
tests/unit/quality/test_audit_all_content_reproducibility.py -q`
→ **57 passed**, only the 3 pre-existing external `SwigPy*` deprecation
warnings.

`git diff --stat 1261521 -- scripts/quality/audit_all_content.py` confirms the
migration code for `artifact_corruption`/`shortcode_leak`/`eu_hallucination`/
`link_path_corrupted` is present in the working tree (+219/-36 lines total
across all v2 changes to this file, uncommitted at verification time).

## Disposition

Treat this directory's absence as a governance-bookkeeping gap in the
original v2 session, not a code gap. No further implementation action
required for TC-DCF-020.
