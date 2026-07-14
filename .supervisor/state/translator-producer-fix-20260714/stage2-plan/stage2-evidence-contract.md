# Stage 2 — Evidence Contract

Every claim closed in this mission or this convergence session must trace to
one of:
1. A git commit hash with a message disclosing scope/deviations (mission
   taskcards TC-HT-001..011 — see master plan for the 9 hashes).
2. A real command output captured verbatim in an evidence file (this
   session's TC-HT-002-A, TC-HT-006-A — see `stage1-audit/evidence/`).
3. Direct filesystem/git inspection with the inspected paths/SHAs recorded
   (TC-HT-009).

## Binding rule for this mission's remaining lifecycle
No claim in Stage 3 or Stage 4 of this convergence pass may assert a
taskcard is "done," "verified," or "closed" without one of the above three
evidence forms already existing on disk at the time the claim is made. If
Stage 3 scoring encounters any claim lacking such evidence, it must be
scored per the reroute rules (`stage2-reroute-rules.md`), not accepted on
narrative alone.

## Known accepted evidence limitations (disclosed, not hidden)
- TC-HT-003: mocked-provider tests only — pre-accepted in the master plan's
  "Remaining True Blockers" before this session began; not reopened.
- The original full-suite baseline's itemized failure list was lost to an
  early `tail -n 40` truncation — compensated for via isolated-rerun
  verification of the final delta (see AUDIT-004), not treated as resolved
  by narrative alone.
