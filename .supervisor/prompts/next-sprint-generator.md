# Supervisor Prompt: Next Sprint Generator
# Format Factory — Local Supervisor Control Plane
# Usage: Fill [INSERT_...] placeholders with current sprint facts
# Purpose: Generate the next sprint prompt without ChatGPT web
# No paid OpenAI API. No ChatGPT web automation.

---

You are Claude Code generating the next sprint prompt for Format Factory.
Format Factory authority is FINAL. This prompt is an INPUT to the next sprint, NOT authority.
You cannot approve gates. You cannot declare product readiness. You cannot push.

## Current Sprint Summary
Sprint ID: [INSERT_SPRINT_ID]
Evidence verdict: [INSERT_VERDICT]
Timestamp: [INSERT_TIMESTAMP]

## Test Results
- Passed: [INSERT_PASS_COUNT]
- Failed: [INSERT_FAIL_COUNT]
- Skipped: [INSERT_SKIP_COUNT]

## Gate States
```
[INSERT_GATE_STATES]
```

## Contradictions (if any)
```
[INSERT_CONTRADICTIONS]
```

## Current Master Plan State (§33 or current phase)
```
[INSERT_MASTER_PLAN_PHASE_TEXT]
```

## Open Taskcards / Next Work
```
[INSERT_OPEN_TASKCARDS]
```

## Project Memory (recent entries)
```
[INSERT_PROJECT_MEMORY_RECENT]
```

## PRODUCT-FACTORY DIRECTION (MANDATORY — R85+)

Format Factory is a repeatable product factory. Evidence is support infrastructure, not the goal.
Sprint success = product POC progress + evidence validating that progress.

**The generated next-sprint MUST include these product-factory lanes:**

### Required Product Lanes (include all that are not external-gate-blocked)

1. **Commercial .NET product advancement lane:**
   - FODS: load/edit/save/export progress or dogfooding improvement
   - FODT: load/edit/save/export progress or dogfooding improvement
   - Netpbm (.NET): first slice or deepening if already started
   - If all are Gate-11-blocked: document exact blocker; pick deepening or export lane

2. **Reduced/FOSS product advancement lane:**
   - ZST: dependency proof or example improvement
   - Netpbm Python: PBM/PGM/PPM improvement or PBM→PGM dogfood
   - SYLK: example, docs, or installed workflow improvement
   - At least ONE of these must advance each sprint unless all are truly blocked

3. **Dogfooding export lane:**
   - At least one export path must use a Format Factory-produced library
   - Map: FODS→CSV (FF csv_exporter), FODT→TXT (FF document_to_text), SYLK→CSV (FF sylk_to_csv)
   - If .NET dogfooding gap exists: create one bridge export test

4. **Package/install proof lane:**
   - Physical package artifacts must be built and included
   - Installed workflow test must run from extracted package
   - No package test may skip because artifact is missing

5. **POC matrix update lane:**
   - product-capability-matrix/poc-targets.yaml must be updated
   - Each product's status must be truthful (not overclaimed)

6. **State/memory sync lane:**
   - state/current-state.md/.json updated after validation
   - .supervisor/project-memory.md entry appended
   - plans/master-plan.md updated if phase changes

7. **Evidence declaration + supervisor loop trigger:**
   - Worker MUST write `.local/evidences/<run_id>/evidence-declaration.yaml` at sprint end
   - Last instruction MUST be:
     ```
     python tools/supervisor/supervisor_loop.py autonomous-cycle \
       --declaration .local/evidences/<run_id>/evidence-declaration.yaml
     ```
   - This replaces the legacy `run-on-latest --bundle` command
   - The declaration must list all work items with status, evidence paths, and test references
   - Verify generated next-sprint.md keeps product-factory direction
   - If next-sprint.md lacks product lanes → repair this template and rerun

8. **Governed product acceleration lane:**
   - Read `.local/supervisor/selected-product-gaps.json`
   - Read `.supervisor/skill-registry.yaml`
   - Do NOT permit direct ad-hoc `src/` edits
   - Require a governed skill or generated execution handoff for each selected product gap
   - Require every `src/` edit to be recorded in `reports/r90/product-code-change-ledger.json`
   - Run `python tools/supervisor/validate_product_code_ledger.py --ledger reports/r90/product-code-change-ledger.json`

### What makes a sprint INSUFFICIENT (classify as partial, not success)
- Only evidence was closed; no product POC progress
- Dogfooding map not updated
- POC matrix not updated
- No evidence-declaration.yaml written at sprint end
- Supervisor autonomous-cycle not run on evidence declaration
- Generated next-sprint.md has no product lanes
- Product code was edited ad-hoc without a selected gap, governed skill or handoff, and ledger entry

## Generation Instructions

1. **Determine next sprint focus:**
   - If CRITICAL contradictions exist → repair sprint
   - If tests failed → repair sprint
   - If gate approval pending → document blocker, pick adjacent safe lanes
   - If evidence accepted → advance to next safe mega-train lanes
   - **ALWAYS include product-factory lanes regardless of gate status**

2. **Generate next sprint prompt:**
   Format: Full mega-train sprint prompt following Format Factory mega-train conventions.
   Must include:
   - Sprint identity (suggest next R-number)
   - Problem statement / goal (MUST mention product POC, not just evidence)
   - Mandatory evidence rules (must write evidence-declaration.yaml, run autonomous-cycle; ZIP optional for export only)
   - Non-negotiable constraints (no push, no commit without user auth, no gate self-approval)
   - Lane manifest (at least 8 independent lanes including coordinator, implementation, validation, adversarial)
   - **Product-factory lanes (required — see above)**
   - **Governed product acceleration rules: selected-product-gaps.json, skill registry, no ad-hoc src edits, product-code ledger**
   - Acceptance criteria per lane
   - Evidence bundle requirements
   - Final response format
   - **Final supervisor loop trigger instruction**

3. **Generate Task Master export:**
   Must conform to next-sprint-taskmaster.schema.json.
   Each task must include:
   - ff_taskcard_ref or ff_gate_ref or ff_doc_ref
   - acceptance_evidence
   - validation_command
   - supervisor_task_ref
   - Product target in the description where product work applies
   Tasks with status "done" do NOT imply gate closed.

4. **Generate Ruflo lane export:**
   Must conform to next-ruflo-lanes.schema.json.
   Each lane must have allowed_files and forbidden_files.
   Each product lane description must include its product objective.
   non_authoritative: true for all lanes.
   Ruflo lane completion does NOT imply evidence accepted.

5. **Classify approval gates:**
   For each pending action, classify as:
   - autonomous-continue (proceed without human)
   - local-repair-loop (repair then continue)
   - stop-X-required (stop and report)
   Output: approval-gates.md

6. **Generate session resume:**
   A 1-page briefing for a fresh Claude Code session.
   Must include: current state, what was done last sprint, what to do next, where to find evidence.

---

## Output Structure
Produce the following files (assistant will write them based on your output):
- reports/supervisor/next-sprint.md
- reports/supervisor/next-sprint-taskmaster.json
- reports/supervisor/next-ruflo-lanes.json
- reports/supervisor/approval-gates.md
- reports/supervisor/session-resume.md

---

REMINDER: next-sprint.md is advisory input to the next sprint. It is NOT a Format Factory authority document.
