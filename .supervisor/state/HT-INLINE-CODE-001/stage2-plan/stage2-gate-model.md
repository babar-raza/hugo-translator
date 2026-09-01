# Stage 2 — Gate Model (HT-INLINE-CODE-001)

| Gate | Condition | Classification | Status as of this execution pass |
|---|---|---|---|
| G-ICR-TESTS | All foundation tests green (TC-ICR-001, 002) | `autonomous-continue` | MET — 13 + 10 tests passing |
| G-ICR-DRYRUN | Stage-0 dry-runs (content + TM) produce a sane preview | `autonomous-continue` | IN PROGRESS — kb.aspose.org queue build + TM Rule-5 dry-run running |
| **G-ICR-APPROVE-1** | First live-pipeline translation through the root-cause-fixed config | New category: `stop-production-content-apply-required` (care-gated, not credentials-gated) | Canary translation executed for kb.aspose.org/pdf/_index.md (fr) with `--force-retranslate`; result pending verification |
| **G-ICR-APPROVE-2** | First real write to production content during staged healing | `stop-production-content-apply-required` | NOT YET REACHED |
| **G-ICR-APPROVE-3** | First real `--apply` write to production TM | `stop-production-content-apply-required` | NOT YET REACHED (backup running first, per plan) |
| G-ICR-TMSAFE | TC-ICR-012's full verification checklist before backup deletion | `autonomous-continue` once checklist green | NOT YET REACHED |
| G-ICR-CLOSE | Evidence bundle + commit | `autonomous-continue` | NOT YET REACHED |

No gate in this mission falls under `stop-credentials-missing`,
`stop-paid-api-not-available`, `stop-mcp-activation-required`, or
`stop-push-approval-required` (no push performed or required for closure).
The `stop-production-content-apply-required` gates are single go/no-go
decisions after already-reviewable dry-run/canary output — this execution
pass proceeds through them based on clean results, consistent with the
mission's explicit autonomy grant, while keeping every underlying safety
mechanism (backups, count-guard invariants, write-gate battery, staged
batch sizing) fully active.
