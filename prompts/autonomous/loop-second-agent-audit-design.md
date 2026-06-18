# Second-Agent Audit Gate — Architecture Design
# TC-LOOP-13 | Date: 2026-06-18 | Status: DESIGN_COMPLETE

---

## Problem

The current autonomous green loop uses a single agent for all stages:
HARDEN → EXECUTE → AUDIT → EXPAND → re-EXECUTE.

The AUDIT stage is performed by the same agent that executed the plan.
This is a structural authority conflict:
- The agent cannot be fully objective about its own work
- If the executing agent made a wrong assumption, the auditing agent
  inherits that assumption
- The loop-audit-contract.md acknowledges this as a known limitation

The governance loop (`docs/governance/prompts/`) partially addresses this with
a distinct ADVERSARIAL_REVIEW stage run before TERMINATED. The development loop
has no equivalent.

---

## Design Options

### Option A: Separate Session Review (Human-in-the-Loop)

**Mechanism:** After AUDIT produces `audit-report-iter<N>.md`, halt the loop
and require a human to review the audit report before setting
`next_action: GREEN_STOP` or `next_action: EXPAND`.

**Pros:**
- Eliminates the authority conflict entirely
- Humans can catch systemic errors the agent missed

**Cons:**
- Defeats the autonomous operation goal
- Latency: human review adds hours/days
- Not scalable

**Verdict:** Suitable only for high-stakes production deploys. Not for
development loop.

### Option B: Second Agent Session (Independent Instance)

**Mechanism:** The orchestrator, after AUDIT writes audit-report-iter<N>.md,
initiates a NEW agent session. The new session reads:
1. `loop-audit-contract.md`
2. `audit-report-iter<N>.md`
3. `taskcard-registry.yaml`

The second agent's only job: re-evaluate the audit findings and produce a
`second-audit-verdict-iter<N>.yaml` with:
```yaml
reviewer: second-agent
reviewed_audit: audit-report-iter<N>.md
agreement: AGREE | DISAGREE | PARTIAL
disputed_findings: []  # list of finding IDs with justification
final_blocking_gaps: <integer>
confirmed_next_action: GREEN_STOP | EXPAND | BLOCKED_EXTERNAL
```

The orchestrator uses `confirmed_next_action` (from second agent) rather than
`next_action` (from first agent) to make the stop decision.

**Pros:**
- True independent review — second agent has no memory of execution
- Catches systematic errors (e.g., first agent accepting weak evidence)
- Machine-readable output allows automation

**Cons:**
- Requires multi-session orchestration (not supported in current loop design)
- Second agent reads only the audit report, not the raw evidence — may be
  fooled by a dishonest first-agent audit
- Doubles token cost for every iteration

**Verdict:** Best option for production use. Requires orchestration extension.

### Option C: Adversarial Reviewer Prompt (Same Session)

**Mechanism:** After AUDIT completes, the same session is instructed to
re-read the audit report with a different persona: "Act as an adversarial
reviewer who is skeptical of every ACCEPTED finding."

A new section in `sprint-audit.md` or a separate `sprint-adversarial-review.md`
prompt performs this re-review and produces a `adversarial-review-iter<N>.md`.

**Pros:**
- No second session required
- Catches obvious acceptance of weak evidence
- Low implementation cost

**Cons:**
- Same session = same context, so inherits the same biases
- Improvement over baseline but not a true independent review
- Vulnerable to context contamination

**Verdict:** Cheap improvement over current state. Implement first. Step up to
Option B when production stakes justify it.

### Option D: Governance Loop Integration

**Mechanism:** After the development loop reaches GREEN_STOP, trigger the
existing governance loop (`docs/governance/prompts/`) to perform adversarial
review. The governance loop already has:
- ADVERSARIAL_REVIEW stage
- Independent scoring (sprint_quality_scorer.py)
- Schema-validated output contracts

The governance loop would run against the development loop's evidence bundle
as a post-completion gate.

**Pros:**
- Leverages existing, proven machinery
- No new architecture needed
- The governance loop's ADVERSARIAL_REVIEW is already calibrated for this

**Cons:**
- Governance loop expects schema-bound stage outputs — development loop uses
  plain YAML/markdown
- Would require adapters
- Governance loop is for the translation sprint, not development sprints (may
  be a semantic mismatch)

**Verdict:** Promising long-term, but requires adapter work.

---

## Recommended Implementation Path

**Phase 1 (now — Option C):** Add adversarial reviewer step to sprint-audit.md
AUTONOMOUS LOOP OPERATION section. After writing audit-report-iter<N>.md, the
agent re-reads it adversarially and appends a `## ADVERSARIAL REVIEW` section.
Any finding accepted with evidence_level < 3 must be re-scrutinized.

**Phase 2 (next sprint — Option B):** Add a `loop-second-agent-audit.md` prompt
that:
1. Is invoked by the orchestrator after AUDIT
2. Reads only `loop-audit-contract.md` + `audit-report-iter<N>.md`
3. Produces `second-audit-verdict-iter<N>.yaml`
4. Orchestrator uses `confirmed_next_action` as the authoritative stop criterion

**Phase 3 (production scale — Option D):** Route post-GREEN_STOP development
loop evidence bundles through the governance loop for final independent scoring.

---

## Phase 1 Implementation Spec (Ready to Execute)

**File to modify:** `prompts/autonomous/sprint-audit.md`

Add to AUTONOMOUS LOOP OPERATION section, after STRUCTURED OUTPUT:

```
ADVERSARIAL RE-REVIEW (anti-self-audit mitigation):

After writing audit-report-iter<N>.md, perform the following re-review:

1. Adopt the persona: "I am a skeptical external reviewer. I did not run this
   plan. I am reading the audit report cold."

2. For each finding classified ACCEPTED or PARTIAL:
   - Ask: "What is the weakest part of the evidence for this finding?"
   - Ask: "If the executing agent was wrong, what would that look like in this evidence?"
   - If evidence_level < 3 (no runtime subprocess or test result): downgrade to PARTIAL

3. Append a `## ADVERSARIAL REVIEW` section to audit-report-iter<N>.md:
   - List any findings you would downgrade and why
   - State whether your adversarial review changes the blocking_gaps count
   - If blocking_gaps count changes: update loop-signal.yaml accordingly

4. If adversarial review finds no downgrades: state "ADVERSARIAL REVIEW: No
   additional blocking gaps identified."

This does not eliminate the self-audit conflict — it mitigates it by forcing
an explicit skeptical pass over every ACCEPTED finding.
```

---

## Phase 2 File Schema

`second-audit-verdict-iter<N>.yaml`:
```yaml
reviewer_session: second-agent
reviewed_iteration: <N>
reviewed_audit_file: audit-report-iter<N>.md
agreement: AGREE | DISAGREE | PARTIAL
disputed_findings:
  - finding_id: <string>
    original_classification: ACCEPTED
    proposed_classification: PARTIAL | FAILED | UNVERIFIED
    justification: <string>
confirmed_blocking_gaps: <integer>
confirmed_next_action: GREEN_STOP | EXPAND | BLOCKED_EXTERNAL
reviewer_confidence: HIGH | MEDIUM | LOW
```

---

## Tradeoffs

| Tradeoff | Phase 1 | Phase 2 | Phase 3 |
|----------|---------|---------|---------|
| True independence | No | Yes (new session) | Yes (governance loop) |
| Implementation cost | Low (1 prompt section) | Medium (new file + orchestrator change) | High (adapter layer) |
| Token cost increase | ~20% | ~100% per iter | ~200% total |
| Suitable for | Development iterations | Pre-production | Production only |

---

## Status

TC-LOOP-13: DESIGN_COMPLETE

Phase 1 (adversarial re-review prompt section) is ready to implement in a
follow-up sprint. Phase 2 and Phase 3 are designed but not yet scoped as
taskcards.

This document is the TC-LOOP-13 deliverable.
