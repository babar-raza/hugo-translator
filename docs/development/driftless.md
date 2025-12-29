# Test Governance for LLM-Assisted “Vibe Coding”

*(Prevent semantic drift, recursive regression, and “green-by-cheating”)*

This document hardens the plan you pasted by turning it into an enforceable governance system with clear ownership boundaries, operating modes, and automation gates. It builds directly on the “three-layer architecture + locked vs fluid tests + fail-explain-modify + golden files” foundation in your pasted draft.

---

## 0) Goal and Non-Goals

### Goal

Keep **intent** stable while allowing code to evolve, even when multiple LLMs touch the repo over time.

### Non-Goals

* Perfect upfront specs for everything.
* Preventing all regressions (instead, make regressions **hard to introduce** and **easy to detect**).
* Replacing human product decisions. Humans still bless behavior changes.

---

## 1) Core Problem: Two Mutable Anchors

If both **code** and **tests** are treated as fully editable, the system loses its anchor and drifts toward “whatever makes CI green.” This creates:

* **Semantic Drift**: intent slowly mutates over iterations.
* **Recursive Regression**: LLM alternates between changing tests and changing code until the original intent is gone.

**Fix:** introduce an explicit hierarchy of truth and enforce it mechanically.

---

## 2) The Hierarchy of Truth (Anchor of Truth)

Truth hierarchy (highest to lowest):

1. **Specification (Spec)**: what the system must do (human-owned)
2. **Contract Tests**: executable verification of the spec (locked)
3. **Regression Tests**: “never again” bugs (semi-locked)
4. **Implementation Tests**: internal details (flexible)
5. **Code**: implementation (most fluid)

If contract tests fail, the default assumption is: **the code is wrong**, not the test.

---

## 3) Repository Structure (Required)

```
docs/
  spec/
    index.md                 # top-level product/system contracts
    <area>/*.md              # feature contracts and invariants
  decisions/
    YYYY-MM-DD_<slug>.md     # behavior-change decision logs
tests/
  contract/                  # locked tests: spec-level behavior
  regression/                # semi-locked tests: past bugs
  integration/               # integration tests
  unit/                      # flexible tests
golden/
  <area>/                    # golden inputs/outputs for stable behavior
llm/
  sessions/
    YYYY-MM-DD_<slug>/
      charter.yml            # operating mode + boundaries
      notes.md               # fail-explain-modify logs
      diffs/                 # optional captured diffs or outputs
```

---

## 4) Definitions (Make the Repo Speak One Language)

### Spec

Human-readable requirement with stable identifiers.

**Rule:** every contract test must point to a spec section like:

* `docs/spec/index.md#contracts`
* `docs/spec/auth.md#login-contract`

### Contract test

A test asserting user-visible or externally consumed behavior:

* CLI output contract
* API response schema and invariants
* file formats and serialization rules
* translation invariants (brands not translated, code blocks untouched, etc.)

### Regression test

A test that reproduces a previously fixed bug. It should not be weakened without explicit approval.

### Implementation test

Tests internal choices that may change during refactors.

---

## 5) Test Taxonomy and Ownership (Enforced Rules)

| Category    | Folder               | Ownership                         | When it can change          | Typical failures mean               |
| ----------- | -------------------- | --------------------------------- | --------------------------- | ----------------------------------- |
| Contract    | `tests/contract/`    | Human approval required           | Only when spec changes      | code violated spec                  |
| Regression  | `tests/regression/`  | Human approval required to weaken | Rarely; only with rationale | bug returned or assumptions changed |
| Integration | `tests/integration/` | Flexible with discipline          | refactors, infra changes    | integration broke                   |
| Unit        | `tests/unit/`        | Flexible                          | anytime                     | internals changed                   |

**Hard rule:** In normal work, LLM may not modify `tests/contract/**` or `docs/spec/**`.

---

## 6) Two Operating Modes (Mandatory)

### Mode A: BUGFIX (Default)

Allowed:

* modify code
* modify unit/integration tests (only to reduce brittleness or match internal refactor)
  Not allowed:
* modify spec
* modify contract tests
* weaken regression tests

**Interpretation:** if a contract test fails, fix the code.

### Mode B: BEHAVIOR_CHANGE (Explicit, Human-Blessed)

Allowed:

* modify spec and contract tests
  Required:
* decision log in `docs/decisions/`
* spec updated first
* golden files updated only with explicit approval (see below)

---

## 7) The “Fail → Explain → Decide → Modify” Protocol (Required)

Whenever any test fails, the agent must produce a short evidence packet in `llm/sessions/.../notes.md`:

1. **Fail**

   * failing test name(s)
   * failure message snippet
2. **Explain**

   * what changed in code (files + summary)
   * why the failure happened (hypothesis)
3. **Decide**
   Choose one:

   * `CODE_BUG`: spec and contract test are correct, fix code
   * `TEST_BRITTLE`: expectation unchanged, make test less brittle
   * `BEHAVIOR_CHANGE_NEEDED`: spec is outdated or intent changed (stop unless in behavior-change mode)
4. **Modify**

   * apply minimal change
   * rerun relevant tests
   * record result

**If the agent cannot justify the change in writing, it cannot make the change.**

---

## 8) Contract Tests Must Be “Behavioral,” Not “Structural”

Contract tests should avoid asserting:

* internal function calls
* private method names
* exact log strings (unless logs are part of the contract)
* ordering when ordering is not part of the contract
* huge snapshots with no scoping

Prefer:

* schema validation
* invariants (idempotent behavior, roundtrips)
* golden file comparisons for complex outputs
* “Given input X, output must satisfy properties P1..Pn”

---

## 9) Golden Files and Snapshot Testing (Controlled Updates)

### Golden Files (Strongly recommended for complex outputs)

* Store `input.*` and `expected_output.*` under `golden/<area>/`.
* Contract tests compare actual output to the golden expected output.

**Golden update rule:**

* CI must **reject** commits that change golden outputs unless the PR is labeled/flagged as behavior change and includes a decision log.

### Snapshot Testing (Only for “vibe surfaces”)

Use snapshots for:

* UI markup
* formatting outputs that are not semantically critical

**Snapshot update rule:**

* snapshots must only update via an explicit command or env var (example below)
* CI never allows auto-regeneration

---

## 10) Mechanical Enforcement (No Trust, Only Gates)

### A) Pytest markers

Add markers and use them in CI gates.

**`pytest.ini`**

```ini
[pytest]
markers =
  contract: locked contract test, must match docs/spec
  regression: semi-locked bug prevention test
  integration: integration test
  unit: unit test
```

### B) Locked test decorators (optional but useful)

Add a convention for docstrings:

```py
@pytest.mark.contract
def test_xyz():
    """
    CONTRACT: <what behavior>
    SPEC: docs/spec/<file>.md#<anchor>
    RATIONALE: <why it exists>
    """
```

### C) Pre-commit hook (local gate)

Block changes to contract tests unless the commit includes a spec change indicator.

**`.git/hooks/pre-commit` (example)**

```bash
#!/usr/bin/env bash
set -e

CHANGED_CONTRACT=$(git diff --cached --name-only | grep -E '^tests/contract/' || true)
CHANGED_SPEC=$(git diff --cached --name-only | grep -E '^docs/spec/' || true)
CHANGED_GOLDEN=$(git diff --cached --name-only | grep -E '^golden/' || true)

if [ -n "$CHANGED_CONTRACT" ] && [ -z "$CHANGED_SPEC" ]; then
  echo "❌ Contract tests changed without a spec update."
  echo "   If this is a behavior change, update docs/spec and add a decision log."
  exit 1
fi

if [ -n "$CHANGED_GOLDEN" ] && [ -z "$CHANGED_SPEC" ]; then
  echo "❌ Golden files changed without a spec update."
  exit 1
fi
```

### D) CI gate (required)

CI should fail PRs that:

* change `tests/contract/**` without a spec change and decision log
* change `golden/**` without explicit behavior-change indicator
* weaken regression tests without explicit approval indicator

**Minimal CI logic:**

* Detect changed files in those paths
* Require presence of `docs/decisions/YYYY-MM-DD_*.md` in same PR
* Require a “BEHAVIOR_CHANGE” label or a `SPEC_CHANGE:` token in PR body

---

## 11) LLM Session Charter (Prevents Context Loss)

Each LLM run must create:

`llm/sessions/YYYY-MM-DD_<slug>/charter.yml`

Example:

```yaml
mode: BUGFIX
scope:
  allowed_paths:
    - src/
    - tests/unit/
    - tests/integration/
  forbidden_paths:
    - docs/spec/
    - tests/contract/
    - tests/regression/
    - golden/
intent:
  - "Fix failing translation cache tests without changing behavior."
rules:
  - "If contract fails, fix code."
  - "Do not weaken regression assertions."
```

If the run needs to switch to behavior change:

* stop
* write a proposal in `docs/decisions/`
* change `mode: BEHAVIOR_CHANGE`
* proceed

---

## 12) Regression Test Policy (Anti-Backslide)

For regression tests:

* If the test fails, assume the bug is back.
* If the test is truly obsolete, you must:

  * document why in a decision log
  * replace it with an updated regression that preserves the underlying “never again” intent

**Never delete a regression test without replacing it.**

---

## 13) Practical Workflow (What You Actually Do Day to Day)

### Step 1: Triage

Run:

* unit + integration first
* contract suite next
* regression suite always before merge

### Step 2: If failures exist

Follow Fail → Explain → Decide → Modify.
Log notes in the session folder.

### Step 3: Merge rules

* BUGFIX PR: cannot touch spec/contract/golden/regression
* BEHAVIOR_CHANGE PR: must include spec + decision log + contract/golden updates

---

## 14) PR Checklist (Copy into your PR template)

* [ ] Session charter created under `llm/sessions/.../charter.yml`
* [ ] Failure analysis notes recorded (if any test failed)
* [ ] No changes to `docs/spec/`, `tests/contract/`, `golden/`, `tests/regression/` (BUGFIX mode)
* [ ] If behavior change:

  * [ ] decision log added under `docs/decisions/`
  * [ ] spec updated first
  * [ ] contract tests updated to match spec
  * [ ] golden updates explicitly approved
* [ ] Regression tests not weakened (or approved with rationale)

---

## 15) The Five Non-Negotiables (Print These in the Repo)

1. **Spec is the anchor of truth.**
2. **Contract tests are locked and reflect the spec.**
3. **Default is BUGFIX mode: fix code, not contract tests.**
4. **Behavior changes require a decision log and spec update.**
5. **All test fixes must include Fail → Explain → Decide in session notes.**

---

## 16) Recommended “Next 60 Minutes” Adoption Plan

1. Create `docs/spec/index.md` with 10–30 lines of core contracts.
2. Move your most important “golden path” tests into `tests/contract/` and mark them.
3. Add `pytest.ini` markers.
4. Add the pre-commit hook and a CI check for contract/spec/golden changes.
5. Add `llm/sessions/` and require a session charter per LLM run.

