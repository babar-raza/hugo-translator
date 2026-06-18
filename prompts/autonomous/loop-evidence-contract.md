# Autonomous Green Loop — Evidence Contract
Version: 1.0 | System: autonomous-green-loop

---

## Purpose

Defines what evidence is required after each stage of the loop, where it lives,
what format it must be in, and what counts as proof vs claim.

---

## Evidence Hierarchy

Evidence is ranked from strongest to weakest:

| Level | Type | Example |
|-------|------|---------|
| 5 | Runtime artifact with observable behavior | Test output showing pass/fail |
| 4 | Generated file with verifiable content | Changed source file + passing test |
| 3 | Script or validator exit code | `validate_autonomous_loop.py` exits 0 |
| 2 | Existence of expected file | File exists at expected path |
| 1 | Agent's claim or summary | "I completed the task" |

Evidence Level 1 alone is NEVER sufficient to classify a finding as ACCEPTED.
Evidence Level 2 is sufficient only for file-existence checks, not behavioral claims.
Evidence Level 3+ is required for any functional claim.

---

## Required Artifacts Per Stage

### HARDEN Stage (iteration 1 only)

| Artifact | Location | Required | Level |
|----------|----------|----------|-------|
| `gap-register.md` | run dir | YES | 2 |
| `stage-1-harden-handoff.yaml` | run dir | YES | 2 |
| Initial `taskcard-registry.yaml` | run dir | YES | 2+ |

`stage-1-harden-handoff.yaml` minimum fields:
```yaml
stage: HARDEN
iteration: 1
status: COMPLETE
gap_count: integer              # number of gaps identified
taskcard_count: integer         # number of OPEN tasks initialized in registry
evidence_artifact: gap-register.md
```

---

### EXECUTE Stage (every iteration)

| Artifact | Location | Required | Level |
|----------|----------|----------|-------|
| `changed-files-iter<N>.txt` | run dir | YES | 2 |
| `stage-<N>-execute-handoff.yaml` | run dir | YES | 2 |
| Test output recorded in handoff | handoff yaml | YES | 3-5 |
| Updated `taskcard-registry.yaml` | run dir | YES | 2 |

`stage-<N>-execute-handoff.yaml` minimum fields:
```yaml
stage: EXECUTE
iteration: integer
status: COMPLETE
tests_passed: boolean
test_command: string            # exact command run
test_result_summary: string     # e.g., "47 passed, 0 failed" or "no tests run"
changed_files_count: integer
evidence_artifact: changed-files-iter<N>.txt
open_tasks_remaining: integer   # should be 0 after successful execution
```

`changed-files-iter<N>.txt` format: one line per file, relative to repo root:
```
prompts/autonomous/loop-state-machine.md  CREATED
prompts/autonomous/loop-audit-contract.md CREATED
scripts/quality/validate_autonomous_loop.py CREATED
```

---

### AUDIT Stage (every iteration)

| Artifact | Location | Required | Level |
|----------|----------|----------|-------|
| `audit-report-iter<N>.md` | run dir | YES | 2 |
| `stage-<N>-audit-handoff.yaml` | run dir | YES | 2 |
| `loop-signal.yaml` | run dir | YES | 2 |

`stage-<N>-audit-handoff.yaml` minimum fields:
```yaml
stage: AUDIT
iteration: integer
status: COMPLETE
audit_verdict: string           # sprint-audit.md verdict vocabulary
blocking_gaps: integer
next_action: string             # GREEN_STOP | EXPAND | BLOCKED_EXTERNAL
evidence_artifact: audit-report-iter<N>.md
```

`audit-report-iter<N>.md` required sections (minimum):
1. Taskcards reviewed (list with status)
2. Evidence reviewed (specific files/outputs read)
3. Findings (each with classification)
4. Blocking gaps count
5. Self-audit caveat

---

### EXPAND Stage (when blocking_gaps > 0)

| Artifact | Location | Required | Level |
|----------|----------|----------|-------|
| `expansion-delta-iter<N>.md` | run dir | YES | 2 |
| Updated `taskcard-registry.yaml` | run dir | YES | 2 |
| `stage-<N>-expand-handoff.yaml` | run dir | YES | 2 |

`stage-<N>-expand-handoff.yaml` minimum fields:
```yaml
stage: EXPAND
iteration: integer
status: COMPLETE
new_tasks_added: integer        # new OPEN entries in registry
evidence_artifact: expansion-delta-iter<N>.md
```

`expansion-delta-iter<N>.md` required sections:
1. Audit findings that triggered expansion (list with IDs)
2. New taskcards added (with acceptance criteria)
3. Plan file amendments made

---

### FINAL Evidence Bundle (GREEN_STOP only)

At GREEN_STOP, the evidence bundle is written to:
`.local/autonomous-loop/evidence/<RUN_ID>/`

Required files:
1. `discovery.md` — what existed before the loop started
2. `gap-analysis.md` — root causes addressed
3. `implementation-summary.md` — what was built, by stage
4. `changed-files.txt` — all files modified across all iterations
5. `state-machine-check.md` — verify loop-state-machine.md completeness
6. `taskcard-contract-check.md` — verify taskcard-registry.yaml schema coverage
7. `idempotency-check.md` — verify idempotency rules are documented
8. `pilot-report.md` — result of the controlled pilot run
9. `verification-commands.log` — output of validate_autonomous_loop.py
10. `audit-report.md` — final audit findings (copy of last audit-report-iter<N>.md)
11. `final-green-report.md` — final verdict with evidence references

---

## Evidence Retention Rules

Within a run directory:
- All per-iteration files are retained indefinitely (append-only)
- `loop-signal.yaml` is the exception: it is overwritten by each AUDIT stage
  because it represents the current signal. Full history is in `loop-state.yaml`

The evidence bundle (`.local/autonomous-loop/evidence/`) follows:
- **Indefinite retention** — treated as formal deliverable (same policy as
  `.local/evidences/` per `docs/governance/local-data-policy.md`)
- **Selective commit** — commit `final-green-report.md` and `discovery.md`;
  do not commit large run artifacts unless they are needed as governance evidence

---

## What Does NOT Count as Evidence

- An agent's description of what it intended to do
- A file path reference without confirming the file exists and has correct content
- A test count without the actual test names and outcomes
- A claim that "tests pass" without the test command and result recorded
- A summary produced by the same agent that ran the stage (unless backed by
  observable artifacts)
