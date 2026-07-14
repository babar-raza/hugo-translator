# Stage 2 — Verification Matrix

| Taskcard | Verification type | Real data? | Command/proof | Result |
|---|---|---|---|---|
| TC-HT-001 | integration_validation | Yes — real wave-3 pair | golden-corpus test | PASS |
| TC-HT-002 | focused_validation → integration_validation (upgraded this session) | Yes (this session's AUDIT-002 proof) | see TC-HT-002-A | PASS |
| TC-HT-003 | focused_validation (mocked provider — accepted limitation) | No | unit tests | PASS |
| TC-HT-004 | end_to_end_proof | Yes — live pilot | TC-HT-011 pilot exercised AST path on all 15 files | PASS |
| TC-HT-005 | integration_validation | Yes — real wave-3 pairs | golden-corpus test | PASS |
| TC-HT-006 | end_to_end_proof (CLI) + this session's AUDIT-003 syntax check for the .local script half | Yes | real CLI invocation + py_compile | PASS |
| TC-HT-007 | integration_validation | Yes — real wave-3 pair | golden-corpus test | PASS |
| TC-HT-009 | focused_validation (read-only, as scoped) | Yes — direct filesystem/git inspection | N/A | PASS |
| TC-HT-010 | end_to_end_proof | Yes — real historical damage + adversarial resurrection | golden-corpus + resurrection test | PASS |
| TC-HT-011 | pilot_proof (scoped to temp-dir) | Yes — real GPU translation, real gates, real aspose.org comparison | pilot run + pilot_report.py | PASS (within declared scope) |
| TC-HT-002-A | integration_validation (this session) | Yes — real content, isolated tempdir | process_file() real-content run | PASS — closed |
| TC-HT-006-A | implementation_only (syntax check) | N/A | py_compile | PASS — closed |

## Summary
11/11 original taskcards verified at or above their pre-accepted proof-level
bar. 2/2 follow-up taskcards closed with genuine, non-fabricated evidence.
0 taskcards remain at claimed_but_unproven or below-bar verification.
