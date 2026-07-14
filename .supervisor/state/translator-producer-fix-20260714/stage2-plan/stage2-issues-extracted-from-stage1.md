# Stage 2 — Issues Extracted From Stage 1

Source: `stage1-audit/issues.json` (5 issues). Each mapped to one of prompt2's
required disposition categories.

| Issue | Level | Severity | Disposition | Notes |
|---|---|---|---|---|
| AUDIT-001 | L2_INTEGRATION | MEDIUM | `updated_plan_item_required` — **DONE** | Master plan hardened this session (all taskcard statuses, Gate Contract, Closeout Criteria, new closeout section). No taskcard needed; this *is* the fix, applied directly as the prior stage's output. |
| AUDIT-002 | L1_EXECUTION | LOW | `taskcard_required` — **DONE, closed** | Taskcarded as `TC-HT-002-A` (see `stage2-taskcards/TC-HT-002-A.yaml`). Closed this session via real `process_file()` proof against real content in an isolated tempdir (see `stage1-audit/evidence/audit-002-safe-io-proof.md`). |
| AUDIT-003 | L1_EXECUTION | LOW | `taskcard_required` — **DONE, closed** | Taskcarded as `TC-HT-006-A` (see `stage2-taskcards/TC-HT-006-A.yaml`). Closed this session via `python -m py_compile` → SYNTAX OK. |
| AUDIT-004 | L3_SYSTEM_WEAKNESS | MEDIUM | `governance_change_required` — **deferred, not this mission** | Taskcarded as a proposed future item `TC-HT-INFRA-001` (status: `proposed`, not `open`) — explicitly out of this mission's scope per Stage 1's own recommendation. Recorded so it is not lost, not so it blocks this mission's closure. |
| AUDIT-005 | L1_EXECUTION | LOW | `rejected_with_reason` | Disclosed, reasoned engineering deviation (rewrite vs delete of read-only detector functions). No corrective action needed — confirmed functionally safer than the literal brief text. Not taskcarded; recorded for audit completeness only, per the original Stage 1 disposition. |

## No orphaned actionable items

Every issue from Stage 1 now maps to a disposition. None are left as
prose-only recommendations: AUDIT-001 was executed directly (plan edit),
AUDIT-002/003 became taskcards and were closed with evidence, AUDIT-004 is
explicitly deferred to a named future taskcard rather than silently dropped,
and AUDIT-005 is a reasoned rejection, not a gap.
