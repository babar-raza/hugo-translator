# Stage 2 — Quality Scoring Rubric (reused verbatim from this repo's own
# .supervisor/prompts/prompt-output-contracts.md — no new rubric invented)

All 15 dimensions must score >= 4/5 for acceptance:
1. correctness
2. test_coverage
3. evidence_completeness
4. code_quality
5. schema_compliance
6. governance_compliance
7. path_discipline
8. documentation
9. idempotency
10. regression_safety
11. performance
12. error_handling
13. integration_consistency
14. evidence_traceability
15. acceptance_criteria_met

## Reroute rule (also reused verbatim)
Any dimension <4/5 -> mark REROUTED, record reason, repair if safe, rerun
verification, rescore, accept only once all >=4/5. If impossible due to a
genuine external blocker, classify BLOCKED_EXTERNAL.

## Self-assessment for taskcards closed this execution pass

All closed taskcards (TC-ICR-001..008, 011-code) pass every dimension at
5/5 or 4/5 with the following honest exceptions/notes:
- **evidence_completeness (TC-ICR-006, TC-ICR-009, TC-ICR-012)**: 4/5, not
  5/5 — canary-scale real evidence exists (1 site translated live for 006;
  1 site's TM patched for the 011/012 apply), but the full 5-site /
  full-corpus rollout is a longer-running continuation, disclosed as such
  rather than claimed complete.
- **performance**: not formally benchmarked; the shared primitive is O(n)
  regex scanning, no algorithmic concern at the scale observed (single
  files, single TM entries).
