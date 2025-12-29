# VAL-001: Validation Decision Engine

**Feature:** ACCEPT/RETRY/REJECT decision logic
**Status:** 🔍 EVIDENCE_ONLY
**Last Updated:** 2025-12-26

---

## Summary

Automated decision engine that analyzes validation results and determines whether to ACCEPT, RETRY, or REJECT a translation. Enforces critical validator rules, error thresholds, and retry limits.

---

## Entry Points

**API Method:**
```python
decision_engine.decide(
    validation_result: ValidationResult,
    retry_count: int = 0
) -> Tuple[ValidationDecision, str]
```

**Registration Site:**
- File: `src/translation_engine/validation/decision_engine.py`
- Symbol: `ValidationDecisionEngine.decide()`

---

## Inputs/Outputs

### Input: ValidationResult

```python
@dataclass
class ValidationResult:
    valid: bool                                # Overall validity
    issues: List[ValidationIssue]             # All issues found

    @property
    def errors(self) -> List[ValidationIssue]  # Severity.ERROR
    @property
    def warnings(self) -> List[ValidationIssue]  # Severity.WARNING
    @property
    def info(self) -> List[ValidationIssue]  # Severity.INFO
```

### Input: retry_count

- Type: `int`
- Default: 0
- Range: 0 to max_retry_attempts (configurable, default 2)

### Output: Tuple[ValidationDecision, str]

**ValidationDecision Enum:**
```python
class ValidationDecision(IntEnum):
    ACCEPT = 0   # Translation acceptable, write to disk
    RETRY = 1    # Issues found, retry with feedback
    REJECT = 2   # Critical errors, do not use translation
```

**Decision Reason (str):**
- Human-readable explanation
- Examples:
  - "No validation errors, accepted"
  - "Structure issues found, retrying with feedback (attempt 1/2)"
  - "Critical placeholder validation failed, rejecting"
  - "Max retries reached, best effort acceptance"

**Evidence:** Return type in `decide()` method signature

---

## Invariants

### Must (Critical)

1. **Critical validators always REJECT:**
   - IF PlaceholderValidator has errors → REJECT
   - IF CodeBlockValidator has errors → REJECT
   - IF LinkValidator has errors → REJECT
   - Evidence: Decision engine critical validator list
   - Rationale: Syntactic integrity non-negotiable (shortcodes, code blocks, links)

2. **Error threshold enforcement:**
   - IF error_count >= reject_on_error_count → REJECT
   - Evidence: Configuration-based threshold check
   - Default thresholds:
     - strict: 1 error
     - normal: 3 errors
     - lenient: 5 errors

3. **Retry budget enforcement:**
   - IF retry_count >= max_retry_attempts → no more RETRY decisions
   - Evidence: Retry count comparison
   - Default: max_retry_attempts = 2

4. **Zero errors → ACCEPT:**
   - IF no errors AND (accept_warnings OR no warnings) → ACCEPT
   - Evidence: Early return path for error_count == 0
   - Exception: May RETRY if retryable warnings exist and feedback enabled

### Should (Important)

5. **Retry with feedback:**
   - SHOULD include validation feedback in retry prompt
   - Evidence: Feedback string generation in retry logic

6. **Decision reason logging:**
   - SHOULD provide clear explanation for each decision
   - Evidence: Reason string construction

### Never (Prohibited)

7. **NEVER ACCEPT critical validator failures:**
   - Even in lenient mode, critical validators must pass
   - Even after max retries, if critical failures exist → REJECT (not ACCEPT)

8. **NEVER exceed retry limit:**
   - After max_retry_attempts, only ACCEPT or REJECT allowed
   - No silent retry extension

---

## Decision Logic Flow

```
decide(validation_result, retry_count):
  ┌─────────────────────────────────┐
  │ 1. Check critical validators     │
  └────┬────────────────────────────┘
       │
       ├─ Critical validator failed?
       │  └─→ REJECT ("Critical {validator} failed")
       │
  ┌────▼────────────────────────────┐
  │ 2. Count errors                  │
  └────┬────────────────────────────┘
       │
       ├─ error_count == 0?
       │  └─→ ACCEPT ("No errors")
       │
  ┌────▼────────────────────────────┐
  │ 3. Check error threshold         │
  └────┬────────────────────────────┘
       │
       ├─ error_count >= reject_on_error_count?
       │  └─→ REJECT ("Error threshold exceeded")
       │
  ┌────▼────────────────────────────┐
  │ 4. Check retry budget            │
  └────┬────────────────────────────┘
       │
       ├─ retry_count < max_retry_attempts?
       │  └─→ RETRY ("Retrying with feedback")
       │
  ┌────▼────────────────────────────┐
  │ 5. Max retries reached           │
  └────┬────────────────────────────┘
       │
       ├─ accept_after_max_retries?
       │  ├─→ True: ACCEPT ("Best effort")
       │  └─→ False: REJECT ("Max retries, quality insufficient")
       │
       ▼
     Return (decision, reason)
```

**Evidence:** Decision flow implemented in `decide()` method

---

## Configuration

### Decision Engine Configuration

```python
ValidationDecisionEngine(
    mode: str = "normal",                      # strict/normal/lenient
    max_retry_attempts: int = 2,              # Max retries
    accept_warnings: bool = True,             # Allow warnings in ACCEPT
    accept_after_max_retries: bool = True,    # Best effort after max retries
    critical_validators: List[str] = [        # Always REJECT on failure
        "PlaceholderValidator",
        "CodeBlockValidator",
        "LinkValidator"
    ],
    reject_on_error_count: int = 3,           # Error threshold (mode-dependent)
)
```

### Mode-Specific Defaults

| Mode | reject_on_error_count | accept_warnings | accept_after_max_retries |
|------|----------------------|-----------------|--------------------------|
| strict | 1 | False | False |
| normal | 3 | True | True |
| lenient | 5 | True | True |

**Evidence:** Mode-based configuration in `__init__()` or config loading

---

## Errors and Edge Cases

### Edge Cases

**All warnings, no errors:**
- Behavior: ACCEPT (if accept_warnings=True)
- Evidence: error_count == 0 check

**Critical validator + retryable errors:**
- Behavior: REJECT (critical takes precedence)
- Evidence: Critical validator check before error count

**Exactly at error threshold:**
- Behavior: REJECT (>= comparison)
- Example: reject_on_error_count=3, error_count=3 → REJECT

**Retry count exactly at limit:**
- Behavior: No more RETRY, proceed to ACCEPT/REJECT logic
- Example: max_retry_attempts=2, retry_count=2 → check accept_after_max_retries

**Empty validation result (no issues):**
- Behavior: ACCEPT ("No validation issues")
- Evidence: error_count == 0 path

**Null/None validation result:**
- Behavior: Likely exception or default ACCEPT (needs verification)
- Risk: Should be validated

---

## Side Effects

### Logging

**Decision logging:**
```python
logger.info(f"Validation decision: {decision.name}, reason: {reason}")
```

**Feedback generation:**
- On RETRY: Generates feedback string with error descriptions
- Evidence: Feedback string construction in retry path

### No Direct Side Effects

Decision engine is **pure logic** - no file writes, no cache updates, no metrics.

**Caller Responsibilities:**
- Log decision
- Update metrics (validation_decisions_total{decision=accept|retry|reject})
- Execute retry or write based on decision
- Update TranslationResult with decision and reason

---

## Evidence

### Code Locations

| Component | File | Estimated Lines | Symbol |
|-----------|------|-----------------|--------|
| Decision engine class | src/translation_engine/validation/decision_engine.py | ~50-150 | ValidationDecisionEngine |
| decide() method | Same | ~80-130 | decide() |
| Configuration | Same | ~20-50 | __init__() |
| ValidationDecision enum | src/translation_engine/models.py | ~20-30 | ValidationDecision |

### Configuration Evidence

| Setting | File | Description |
|---------|------|-------------|
| Validation mode | config/site_profiles/*.yaml | Per-site override |
| Global validation config | config/validation.yaml | System-wide defaults (optional) |
| Critical validators | Hardcoded in decision_engine.py | Non-configurable (safety) |

### Test Evidence

**Existing Tests:**
- `tests/unit/test_decision_engine.py` (likely) - Unit tests for decision logic
- `tests/integration/test_e2e_validation.py` - E2E validation flow

**Missing Contract Tests:**
- Critical validator enforcement (must always REJECT)
- Error threshold enforcement (all modes)
- Retry limit enforcement
- accept_after_max_retries behavior
- Mode-specific configuration application

---

## Verification Status

🔍 **EVIDENCE_ONLY**

**Verification Steps Required:**

1. **Create contract test:** `tests/contract/test_val_decision_engine.py`
2. **Test critical invariants:**
   - Critical validators → REJECT (always)
   - Error threshold enforcement (all modes)
   - Retry limit enforcement (no silent extension)
   - Zero errors → ACCEPT
3. **Test edge cases:**
   - Exactly at threshold
   - All warnings, no errors
   - Critical + retryable errors
   - Max retries with accept_after_max_retries=True/False
4. **Test all modes:**
   - strict, normal, lenient configurations
5. **Link to spec:** Add docstring `CONTRACT: specs/features/val-001-decision-engine.md`

**Blockers:** None

---

## Related Specs

- [API-001: translate_file Method](api-001-translate-file.md) - Uses decision engine
- [VAL-002: Critical Validators](val-002-critical-validators.md) - Validator specifications
- [CLI-002: Validation Control](cli-002-validation-control.md) - CLI configuration flags
