# Local Data Retention Policy

**Audience:** System Contributors, Operators
**Last Updated:** 2026-06-17
**Status:** ✅ Active Policy

---

## Overview

The `.local/` directory contains agent-generated working state, evidence files, and analysis artifacts. This policy defines what lives there, how long it is retained, and how cleanup is performed.

`.local/` content is **not tracked in `.gitignore` as a whole** but individual subdirectories containing personal credentials, secrets, or binary artifacts should remain untracked. Evidence files may be committed when they constitute formal sprint deliverables (as recorded in commit messages and memory files).

---

## Directory Structure and TTL

| Subdirectory | Content | Owner | TTL | Cleanup |
|-------------|---------|-------|-----|---------|
| `.local/evidences/` | Sprint evidence declarations (`evidence-declaration.yaml` + audit files) | Sprint executor | **Indefinite** (formal deliverables) | Manual review before deletion; must preserve for active sprint reference |
| `.local/rating-healing-runs/` | Agent self-healing session outputs | Autonomous agent | **3 months** | Delete after rating has stabilized; do not delete during active healing |
| `.local/rating-cause-analysis-runs/` | Root cause analysis session outputs | Autonomous agent | **3 months** | Delete after fixes are committed; keep if referenced in open taskcards |
| `.local/doc-audit/` | Documentation audit inventory and analysis | Docs architect | **Active duration of audit sprint** | Delete after documentation consolidation plan is fully executed |

---

## Rules

### What Belongs in `.local/`

- Agent working state that is session-specific and not needed after the sprint concludes
- Evidence sidecars that accompany sprint deliverables (evidence-declaration.yaml)
- Analysis artifacts produced during planning sprints (inventories, link graphs)
- Rating and scoring outputs from autonomous review runs

### What Does NOT Belong in `.local/`

- Active documentation (belongs in `docs/`)
- Policy documents (belongs in `docs/governance/`)
- Historical sprint reports (belongs in `reports/` or `archive/`)
- Production configuration
- Credentials or API keys

### Cleanup Protocol

1. Before deleting any `.local/evidences/<sprint>/` directory, verify:
   - The sprint is listed as CLOSED in the active plan file
   - No open taskcards reference files in that directory
   - The commit that completed the sprint includes a reference to the evidence

2. Before deleting `.local/rating-*/` directories, verify:
   - The rating score is stabilized and recorded in MEMORY.md
   - No repair loop is currently active for the rated run

3. Before deleting `.local/doc-audit/`, verify:
   - The documentation consolidation plan is marked EXECUTED
   - All taskcards referencing inventory files are CLOSED

### Git Tracking

- `.local/evidences/` — **commit selectively**: only `evidence-declaration.yaml` and formal evidence artifacts when they are part of a sprint deliverable
- `.local/rating-*/` — **do not commit**: session-local state, not repo artifacts
- `.local/doc-audit/` — **do not commit**: planning-sprint working state only; outcomes are recorded in plan files and MEMORY.md
- `.local/.runner_system_id` — **do not commit**: machine-specific identifier

---

## Evidence Files (`.local/evidences/`)

Evidence declarations follow the [evidence-declaration.schema.json](../reference/schemas.md#6-evidence-declarationschemajson) schema.

**Committed evidence directories** (as of 2026-06-17):

| Directory | Sprint | Status |
|-----------|--------|--------|
| `.local/evidences/cicd-hooks-healing-20260610-wWm/` | CI/CD Hardening Sprint 1 | COMMITTED — preserve |
| `.local/evidences/agentic-maturity-deepdive-20260613-d9e45cd/` | Agentic Maturity Deep Dive | COMMITTED — preserve |
| `.local/evidences/post-sprint-autonomy-loop-20260615/` | Post-Sprint Autonomy Loop | COMMITTED — preserve |

---

## Related Documentation

- [Schemas Reference](../reference/schemas.md) — Evidence declaration schema definition
- [Sprint Loop Governance Prompts](sprint-loop-governance.md) — How the sprint loop controller uses evidence files
- [Source: evidence_declaration.py](../../src/observability/evidence_declaration.py)
