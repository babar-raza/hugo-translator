# Prompt Output Contracts
# Reference document for all stage output formats in the Post-Sprint Autonomy Loop

---

## Schema Registry

| Stage | Schema | Location |
|-------|--------|----------|
| Stage 1 (Audit) | Issue Model | `.supervisor/schemas/stage1-issue-model.schema.json` |
| Stage 2 (Harden) | Taskcard Contract | `.supervisor/schemas/stage2-taskcard-contract.schema.json` |
| Stage 3 (Execute) | Quality Scoring Rubric | `.supervisor/schemas/stage3-quality-scoring-rubric.schema.json` |
| Summary Classifier | Parser Contract | `.supervisor/schemas/summary-parser-contract.schema.json` |
| Loop Controller | Decision State Machine | `.supervisor/schemas/loop-decision-state-machine.schema.json` |
| Taskcard States | State Machine | `.supervisor/schemas/taskcard-state-machine.schema.json` |
| Evidence Bundle | Bundle Contract | `.supervisor/schemas/evidence-bundle-contract.schema.json` |
| Project Adapter | Adapter Contract | `.supervisor/schemas/project-adapter-contract.schema.json` |
| Governance | Governance Contract | `.supervisor/schemas/governance-contract.schema.json` |

## Stage 1 Output Requirements

The audit MUST produce a JSON object conforming to `stage1-issue-model.schema.json`:
- `sprint_id`: string
- `timestamp`: ISO 8601
- `audit_summary.what_achieved`: array of achievements with proof_level
- `issues`: array of L1/L2/L3 issues each with root_cause (MANDATORY)
- `claim_classification_matrix`: every major claim classified
- `evidence_quality_verdict`: STRONG through MISLEADING
- `final_verdict`: one of 7 verdict enums
- `next_stage_recommendation.stage`: which prompt to run next

**Rejection criteria:**
- Issue without root_cause -> REJECTED
- Achievement without proof_level -> REJECTED
- Missing claim_classification_matrix -> REJECTED

## Stage 2 Output Requirements

The hardening MUST produce a JSON object conforming to `stage2-taskcard-contract.schema.json`:
- `taskcards`: array, each with taskcard_id, acceptance_criteria, validation_commands
- `plan_verdict`: one of 6 verdict enums
- `hardening_score.achieved` >= 18 for execution readiness

**Rejection criteria:**
- Actionable issue without taskcard -> REJECTED
- Prose recommendation without taskcard -> REJECTED
- Plan delta without linked issue IDs -> REJECTED

## Stage 3 Output Requirements

The execution MUST produce a JSON object conforming to `stage3-quality-scoring-rubric.schema.json`:
- `execution_results`: array, each with quality_scores (15 dimensions, 1-5)
- `all_green`: boolean (true only if ALL dimensions >= 4 on ALL taskcards)
- `overall_verdict`: one of 8 verdict enums
- `self_review`: L1/L2/L3 issues (Prompt 1-style)
- `evidence_bundle_path`: string (MANDATORY)

**Rejection criteria:**
- Missing self_review -> REJECTED (prose-only)
- Missing quality_scores -> REJECTED (scores missing)
- Missing evidence_bundle_path -> REJECTED (evidence missing)
- Taskcard without quality_scores -> acceptance blocked
- Rerouted item accepted without rescoring -> acceptance blocked

## Classifier Output Requirements

Conforming to `summary-parser-contract.schema.json`:
- `classification`: one of 9 enums
- `confidence`: 0.0 to 1.0
- `next_stage_recommendation`: one of 8 actions

## Evidence Quality Score (Supervisor Pipeline)

The `evidence_quality_score` in supervisor review output is calculated as:

    evidence_quality_score = ACCEPTED_VERIFIED count / total accepted count

This is a **deep verification ratio**, not an overall quality score. A sprint that
accepts 17 items but only 3 achieve ACCEPTED_VERIFIED will score 3/17 = 0.18, even
though all 17 items are legitimately accepted. This is by design: ACCEPTED_WITH_LIMITATIONS
items have path-only evidence (no test content verification), which dilutes the ratio.

Complementary metric: `semantic_quality_score` from LLM assessment measures adequacy
independent of the VERIFIED/LIMITATIONS distinction.

A low evidence_quality_score does NOT block continuation (only exact 0.0 triggers
the `evidence_quality_zero` hard stop). It is a quality signal for improvement, not a gate.

## Quality Score Threshold

All 15 dimensions must score >= 4/5 for acceptance. Dimensions:
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
