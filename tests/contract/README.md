# Contract Tests

**Purpose:** Verify system invariants and user-visible behavior contracts
**Status:** Phase 1 - Critical Invariants
**Created:** 2025-12-26

---

## Overview

Contract tests are **locked** tests that verify the system's core invariants and user-visible behavior. Unlike unit tests (which test implementation details) or integration tests (which test component interactions), contract tests verify the **promises** the system makes to users.

### Hierarchy of Truth (Driftless Governance)

```
1. Specification (Spec)     ← Human-owned, defines WHAT must be true
2. Contract Tests (This)    ← Locked, verifies spec promises
3. Regression Tests          ← Semi-locked, "never again" bugs
4. Implementation Tests      ← Flexible, internal details
5. Code                      ← Most fluid, implementation
```

**Contract tests anchor the spec** - they prevent semantic drift by making behavioral promises executable and verifiable.

---

## Writing Contract Tests

### Test Structure

Every contract test MUST follow this structure:

```python
"""
CONTRACT: specs/features/{feature-spec}.md

Brief summary of the contract being verified.
Cross-reference to specific invariant if applicable.
"""

import pytest


@pytest.mark.contract
def test_invariant_name():
    """
    Test description: what this test verifies.

    CONTRACT: {SPEC-ID} Invariant #{N}
    Evidence: {file.py} lines {X-Y}
    """
    # Arrange: Set up test conditions
    # Act: Execute the behavior under test
    # Assert: Verify the contract holds
```

### Required Elements

1. **Module docstring** with `CONTRACT:` reference to spec file
2. **@pytest.mark.contract** decorator on every test function
3. **Test docstring** with:
   - Clear description of what's being tested
   - `CONTRACT:` reference to spec ID and invariant number
   - `Evidence:` citation to code location
4. **AAA pattern** (Arrange, Act, Assert) in test body

---

## Contract Test Principles

### 1. Test User-Visible Behavior, Not Implementation

**GOOD:**
```python
def test_multi_language_subprocess_isolation():
    """Verify each target language runs in separate subprocess."""
    result = run_cli(["--site", "test", "--langs", "fr,de,es"])

    # Verify observable behavior: 3 subprocesses spawned
    assert result.subprocess_count == 3
    assert "fr" in result.subprocess_1_output
    assert "de" in result.subprocess_2_output
    assert "es" in result.subprocess_3_output
```

**BAD:**
```python
def test_subprocess_manager_calls_spawn():
    """Test internal implementation detail."""
    manager = SubprocessManager()
    manager.spawn(...)  # Testing internal API, not user contract
```

### 2. Test Invariants, Not Features

Contract tests verify **must always be true** conditions, not feature functionality.

**GOOD:**
```python
def test_critical_validator_always_rejects():
    """PlaceholderValidator ERROR always causes REJECT, even in lenient mode."""
    # Tests invariant: critical validators bypass mode
```

**BAD:**
```python
def test_placeholder_validator_detects_missing_placeholder():
    """PlaceholderValidator detects missing {{CODE_1}}."""
    # Tests validator logic, not the decision engine contract
```

### 3. Test Black-Box, Not White-Box

Contract tests should work if implementation changes, as long as behavior doesn't.

**GOOD:**
```python
def test_atomic_writes_prevent_corruption():
    """Interrupted write leaves file uncorrupted (old or new, never partial)."""
    # Test observable outcome, not implementation (temp file, rename, etc.)
```

**BAD:**
```python
def test_atomic_write_creates_temp_file():
    """atomic_write() creates .tmp.{pid} file."""
    # Tests implementation detail, not the atomic guarantee
```

### 4. Contracts Are Locked

**PROHIBITED:**
- ❌ Modifying contract test without spec update
- ❌ Removing contract tests
- ❌ Commenting out failing contract tests
- ❌ Adding `@pytest.mark.xfail` without spec approval

**ALLOWED:**
- ✅ Adding new contract tests for unspecified invariants
- ✅ Improving test clarity or performance (same behavior)
- ✅ Fixing test bugs (false positives/negatives)

**REQUIRED FOR CHANGES:**
1. Update spec first with new invariant or clarification
2. Update contract test to match spec
3. Link PR to spec change
4. Get spec review approval

---

## Running Contract Tests

### Run All Contract Tests

```bash
pytest tests/contract/ -m contract -v
```

### Run Specific Contract Test

```bash
pytest tests/contract/test_validation_critical.py::test_placeholder_validator_always_rejects -v
```

### Run Contract Tests in CI

```bash
pytest tests/contract/ -m contract --strict-markers
```

**Exit code 0:** All contracts verified ✅
**Exit code 1:** Contract violation detected ❌

---

## Contract Test Categories

### Phase 1: Critical Invariants (MUST IMPLEMENT)

| Test File | Contract | Status | Priority |
|-----------|----------|--------|----------|
| test_validation_critical.py | CONTRACT-004 | ready_to_run | CRITICAL |
| test_cli_subprocess_isolation.py | CONTRACT-001 | scaffolded | CRITICAL |
| test_atomic_writes.py | CONTRACT-002 | scaffolded | CRITICAL |
| test_tm_lookup_order.py | CONTRACT-003 | scaffolded | CRITICAL |

**Phase 1 Goal:** Verify all 4 critical invariants

### Phase 2: High Priority (Deferred)

| Test File | Contract | Status | Priority |
|-----------|----------|--------|----------|
| test_validation_modes.py | CONTRACT-005 | scaffolded | HIGH |
| test_file_locking.py | CONTRACT-006 | deferred | HIGH |
| test_resume_skip_completed.py | CONTRACT-007 | deferred | HIGH |
| test_tm_l2_corruption.py | CONTRACT-008 | deferred | HIGH |
| test_tm_l3_periodic_save.py | CONTRACT-009 | deferred | MEDIUM |

---

## Fixtures and Helpers

### Common Fixtures (conftest.py)

```python
@pytest.fixture
def temp_test_dir(tmp_path):
    """Temporary directory for test artifacts."""
    return tmp_path

@pytest.fixture
def site_profile_fixture(temp_test_dir):
    """Minimal test site profile."""
    # ...

@pytest.fixture
def translation_engine_fixture():
    """Pre-configured TranslationEngine for testing."""
    # ...
```

### Test Helpers

Create `tests/contract/helpers.py` for shared utilities:

```python
def create_test_markdown(content: str, frontmatter: dict = None) -> Path:
    """Create test markdown file with frontmatter."""
    # ...

def assert_file_atomic(file_path: Path, expected_content: str):
    """Assert file is exactly expected content (old or new, never partial)."""
    # ...
```

---

## Golden Files

Contract tests may use golden files for deterministic testing.

**Golden File Structure:**
```
tests/contract/golden/
  cli_subprocess/
    input.md                # Test input
    expected_output_fr.md   # Expected French translation
    site_profile.yaml       # Test site profile
  validation_critical/
    broken_placeholder.md   # Input with {{CODE_1}} missing
    expected_rejection.json # Expected validation result
```

**Golden File Rules:**
1. Check into git (stable, versioned)
2. Update only with spec changes
3. Document changes in commit message
4. Keep minimal (one golden per test scenario)

---

## Debugging Failed Contract Tests

### Step 1: Understand the Failure

```bash
pytest tests/contract/ -m contract -vv --tb=long
```

**Questions:**
- What contract is being violated?
- Is the test correct or is the code wrong?
- Did the spec change?

### Step 2: Check the Spec

Read the spec file referenced in `CONTRACT:` comment:

```python
"""
CONTRACT: specs/features/val-002-critical-validators.md
"""
```

Verify the invariant is still valid and matches the test.

### Step 3: Decide on Action

**If code violates spec:**
→ Fix the code to match the spec (spec is truth)

**If spec changed:**
→ Update contract test + link to spec change PR

**If test is wrong:**
→ Fix test (but verify it still tests the same invariant)

**If spec is wrong:**
→ Spec review process, update spec FIRST, then test

---

## Contract Test Checklist

Before submitting a contract test, verify:

- ✅ Module docstring with `CONTRACT: specs/...` reference
- ✅ All test functions have `@pytest.mark.contract`
- ✅ Test docstrings include CONTRACT and Evidence
- ✅ Tests follow AAA pattern (Arrange, Act, Assert)
- ✅ Tests verify user-visible behavior (not implementation)
- ✅ Tests are deterministic (no flakiness)
- ✅ Tests have clear failure messages
- ✅ Fixtures are in conftest.py (if shared)
- ✅ Golden files checked into git (if used)
- ✅ Test passes locally: `pytest path/to/test.py -m contract -v`

---

## Examples

### Example 1: Critical Validator Contract

```python
"""
CONTRACT: specs/features/val-002-critical-validators.md

Verifies that critical validators (Placeholder, CodeBlock, Link) always
cause REJECT decision, bypassing retry logic and error thresholds.
"""

import pytest
from src.translation_engine.validation.decision_engine import (
    ValidationDecisionEngine,
    ValidationDecision,
)
from src.translation_engine.validation.base import (
    ValidationResult,
    ValidationIssue,
    ValidationSeverity,
)


@pytest.mark.contract
def test_placeholder_validator_error_always_rejects():
    """
    Verify PlaceholderValidator ERROR causes REJECT in all modes.

    CONTRACT: VAL-002 Invariant #2
    Evidence: decision_engine.py CRITICAL_VALIDATORS lines 59-63
    """
    # Arrange
    config = {"decision_rules": {"reject_on_error_count": 5}}
    engine = ValidationDecisionEngine(config)

    result = ValidationResult(success=False)
    result.issues.append(
        ValidationIssue(
            severity=ValidationSeverity.ERROR,
            message="Missing placeholder: {{CODE_1}}",
            validator_name="PlaceholderValidator",
        )
    )

    # Act
    decision, reason = engine.decide(result, retry_count=0)

    # Assert
    assert decision == ValidationDecision.REJECT
    assert "Critical" in reason or "PlaceholderValidator" in reason
```

### Example 2: TM Lookup Order Contract

```python
"""
CONTRACT: specs/features/tm-001-l1-cache.md, tm-002-l2-persistent-store.md, tm-003-l3-semantic-search.md

Verifies Translation Memory lookup follows L1 → L2 → L3 cascade order,
stopping at first hit.
"""

import pytest
from unittest.mock import Mock, call
from src.tm import TranslationMemory


@pytest.mark.contract
def test_tm_lookup_order_l1_hit_skips_l2_l3():
    """
    Verify L1 hit skips L2/L3 lookups (performance contract).

    CONTRACT: INV-003 (Core Invariants)
    Evidence: src/tm/__init__.py lookup() method
    """
    # Arrange
    l1 = Mock()
    l1.exact_lookup.return_value = {"translation": "Bonjour"}  # L1 hit

    l2 = Mock()
    l3 = Mock()

    tm = TranslationMemory(l1_cache=l1, l2_persistent=l2, l3_semantic=l3)

    # Act
    result = tm.lookup("test_site", "en", "fr", "Hello")

    # Assert
    assert result == {"translation": "Bonjour"}
    l1.exact_lookup.assert_called_once()
    l2.exact_lookup.assert_not_called()  # L2 skipped
    l3.semantic_search.assert_not_called()  # L3 skipped
```

---

## Related Documentation

- [Driftless Governance](../../docs/development/driftless.md) - Full governance system
- [Core Invariants](../../specs/core_invariants.md) - System-wide invariants
- [Contract Seed Plan](../../reports/driftless/13_contract_seed_plan.md) - Implementation plan
- [Traceability Matrix](../../reports/driftless/15_traceability_matrix.yml) - Spec ↔ Contract mapping

---

## Status

**Phase 1 (Critical):** In Progress
**Tests Ready:** 1 (CONTRACT-004)
**Tests Scaffolded:** 3 (CONTRACT-001/002/003)
**Tests Deferred:** 5 (CONTRACT-005/006/007/008/009)

**Next Steps:**
1. ✅ Create infrastructure (this README, conftest.py, pytest.ini)
2. ✅ Implement CONTRACT-004 (validation critical - ready to run)
3. ⏸️ Implement CONTRACT-001 (subprocess isolation - needs fixtures)
4. ⏸️ Implement CONTRACT-002 (atomic writes - needs interruption simulation)
5. ⏸️ Implement CONTRACT-003 (TM lookup order - needs mocking)

---

**Principle:** If a contract test fails, either the code is wrong or the spec changed. The spec is the source of truth.
