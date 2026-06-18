# Governance Documentation

**Audience:** System Contributors, Governance Operators  
**Last Updated:** 2026-06-17

---

## Overview

This directory contains governance policies, sprint loop documentation, and prompt templates that control autonomous agent behavior and sprint quality enforcement.

## Contents

### Policies

| Document | Purpose |
|----------|---------|
| [Local Data Policy](local-data-policy.md) | `.local/` directory retention rules, TTL per subdirectory, git tracking policy |

### Sprint Loop Governance

The post-sprint autonomy loop is a 10-state machine that governs structured sprint execution. See [Sprint Loop Governance](sprint-loop-governance.md) for the operator guide.

**Key components:**
- `scripts/ops/sprint_loop_controller.py` — state machine controller
- `scripts/ops/sprint_quality_scorer.py` — 15-dimension quality scorer
- `schemas/` — 6 JSON schemas enforcing output contracts

### Prompts (`prompts/`)

Governance prompt templates used by the sprint loop controller:

| Prompt | Purpose |
|--------|---------|
| [prompt-loop-controller.md](prompts/prompt-loop-controller.md) | Sprint loop state machine prompt and logic |
| [prompt1-post-sprint-audit.md](prompts/prompt1-post-sprint-audit.md) | Stage 1: Post-sprint audit prompt |
| [prompt2-plan-hardening.md](prompts/prompt2-plan-hardening.md) | Stage 2: Plan hardening prompt |
| [prompt3-controlled-execution.md](prompts/prompt3-controlled-execution.md) | Stage 3: Controlled execution prompt |
| [prompt-output-contracts.md](prompts/prompt-output-contracts.md) | Output contract specifications |
| [project-adapter-template.md](prompts/project-adapter-template.md) | Project-specific adapter template |
| [prompt-registry.yaml](prompts/prompt-registry.yaml) | Machine-readable prompt registry |

## Related Documentation

- [Documentation Standards](../development/docs-standards.md) — Standards for all documentation in this repository
- [JSON Schemas Reference](../reference/schemas.md) — All 6 sprint governance JSON schemas
- [Autonomous Operation Guide](../guides/autonomous-operation.md) — Agentic workflow module reference
