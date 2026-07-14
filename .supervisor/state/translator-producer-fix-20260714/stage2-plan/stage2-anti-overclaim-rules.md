# Stage 2 — Anti-Overclaim Rules

Binding for Stage 3/4 of this convergence session:

1. Do not claim `SPRINT_ALL_GREEN_VERIFIED` if any taskcard's evidence is
   synthetic-only where real-data proof was achievable and not attempted.
2. Do not claim a full-suite regression run is clean without disclosing the
   AUDIT-004 non-determinism finding alongside any full-suite number cited.
3. Do not claim the mission is fully closed if the two operator-owned items
   (push, aspose.org session) are conflated with this repo's own closure —
   they must always be reported as separate, explicitly open items.
4. Do not claim TC-HT-003's LLM-echo validation is proven beyond
   mocked-provider level — this is a standing, disclosed limitation, not
   something Stage 3 scoring should silently upgrade.
5. Do not claim TC-HT-011 achieved full E2E proof — it achieved pilot_proof
   scoped to a temp directory; the aspose.org write-and-commit-gate step is
   explicitly not part of this claim.
6. Do not present this convergence session's retroactive audit trail as
   though it were a real-time audit that gated the original implementation
   work — it is an honest after-the-fact evidence reconstruction, per the
   user's own explicit choice to onboard the work retroactively. This
   framing must be stated plainly in the final closure report, not
   obscured.
7. Every quantitative claim (test counts, file counts, commit counts) must
   be traceable to a specific command output already captured in this
   session's artifacts — no rounding up, no "approximately," no invented
   numbers.
