# Stage 2 — Quality Scoring Rubric (for Stage 3)

Each of the 11 mission taskcards plus 2 closed follow-ups will be scored in
Stage 3 across these dimensions, 1-5 each (5 = best), matching this repo's
existing "Self-review (12 dimensions >=4/5)" convention referenced in
project memory, extended to the 15-dimension form this governance framework
expects:

1. Correctness of implementation
2. Test coverage adequacy
3. Real-data proof (vs synthetic-only)
4. Regression safety (scoped + full-suite)
5. Disclosure of deviations from spec
6. Root-cause vs symptom fix
7. Blast-radius containment
8. Evidence traceability (commit/log/file)
9. Safety-critical correctness (for TC-HT-002/004/006/007 especially)
10. Idempotency / no side effects on re-run
11. Documentation of known limitations
12. Consistency with existing codebase conventions
13. No unauthorized scope expansion
14. No unauthorized scope contraction (silently dropping brief requirements)
15. Reviewer-independent verifiability (could another agent re-check this from disk alone?)

**Acceptance bar:** every dimension >= 4/5 for a taskcard to count as
`completed_verified`. Any dimension scoring below 4 triggers the reroute
rule in `stage2-reroute-rules.md` rather than being averaged away.
