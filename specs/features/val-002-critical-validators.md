# VAL-002: Critical Validators

**Feature:** Non-negotiable validators that always cause REJECT
**Status:** 🔍 EVIDENCE_ONLY
**Last Updated:** 2025-12-26

---

## Summary

Critical validators enforce syntactic integrity rules that are never relaxed regardless of validation mode (strict/normal/lenient). Any error from a critical validator causes immediate REJECT decision, bypassing retry logic and error thresholds. The three critical validators protect placeholders, code blocks, and links from corruption.

---

## Entry Points

**Configuration Site:**
- File: `src/translation_engine/validation/decision_engine.py`
- Lines: 59-63 (CRITICAL_VALIDATORS set)
- Symbol: `ValidationDecisionEngine.CRITICAL_VALIDATORS`

**Enforcement Site:**
- Lines: 196-210 (critical failure check method)
- Symbol: `ValidationDecisionEngine._check_critical_failure()`

**Individual Validators:**
- `src/translation_engine/validation/placeholder_validator.py` (PlaceholderValidator)
- `src/translation_engine/validation/link_validator.py` (LinkValidator)
- Code block validation (likely in structure_validator.py or separate file)

---

## Critical Validator List

### 1. PlaceholderValidator

**Purpose:** Ensure placeholder integrity

**Checks:**
- All source placeholders appear in translation
- No extra placeholders in translation
- Placeholder syntax is valid (`{{TYPE_NUM}}` format)
- Optional: Placeholder order preservation

**Error Examples:**
- `ERROR: Missing placeholders in translation: {{CODE_1}}, {{LINK_2}}`
- `ERROR: Extra placeholders in translation: {{CODE_99}}`

**Evidence:** Lines 1-150 in `src/translation_engine/validation/placeholder_validator.py`

### 2. CodeBlockValidator

**Purpose:** Preserve code block integrity

**Checks:**
- Code fence markers preserved (`` ``` `` or `~~~`)
- Code language tags unchanged
- Indented code blocks preserved
- Code block count matches
- Code content not translated (except comments if configured)

**Error Examples:**
- `ERROR: Code block count mismatch: source has 3, translation has 2`
- `ERROR: Code fence not properly closed`
- `ERROR: Code language changed from 'python' to 'none'`

**Evidence:** Inferred from decision_engine.py CRITICAL_VALIDATORS line 61, validator implementation in structure_validator or separate file

### 3. LinkValidator

**Purpose:** Maintain link validity

**Checks:**
- Link count matches (source vs translation)
- Link syntax valid (`[text](url)`, `![alt](url)`)
- URLs preserved (unless allow_url_translation=True)
- Anchor links maintained

**Error Examples:**
- `ERROR: Invalid link syntax: unclosed bracket`
- `WARNING: Link count mismatch: source has 5, translation has 4`
- `ERROR: URL changed without permission`

**Evidence:** Lines 1-100 in `src/translation_engine/validation/link_validator.py`

---

## Invariants

### Must (Critical)

1. **Hardcoded critical validator set:**
   - CRITICAL_VALIDATORS set MUST be defined as class constant
   - Cannot be modified via configuration
   - Evidence: Lines 59-63
   ```python
   CRITICAL_VALIDATORS = {
       "PlaceholderValidator",
       "CodeBlockValidator",
       "LinkValidator",
   }
   ```

2. **Always REJECT on critical error:**
   - IF any critical validator has ERROR severity → REJECT
   - Bypasses error threshold check
   - Bypasses retry logic
   - Evidence: Lines 9, 196-210
   ```python
   # Decision Rules:
   # 1. REJECT if critical validator failed (placeholder, code block, link errors)
   ```

3. **Check before retry:**
   - Critical failure check MUST happen before retry decision
   - Prevents wasting retry attempts on non-retryable errors
   - Evidence: Decision flow in VAL-001 spec

4. **Mode-independent:**
   - Critical validators enforced in ALL modes (strict, normal, lenient)
   - Even lenient mode MUST REJECT critical failures
   - Evidence: No mode bypass in critical check logic

### Should (Important)

5. **Descriptive reject reason:**
   - SHOULD include validator name in reject reason
   - Example: `"Critical PlaceholderValidator failed, rejecting"`
   - Evidence: Inferred from decision engine implementation

6. **Log critical failures:**
   - SHOULD log at ERROR level when critical validator fails
   - Helps debugging translation quality issues

### Never (Prohibited)

7. **NEVER allow configuration override:**
   - Critical validator list CANNOT be modified via site profile
   - CANNOT be disabled via CLI flags
   - Evidence: Hardcoded set (no config parameter)

8. **NEVER retry critical failures:**
   - No automatic retry for critical errors
   - Retrying won't fix syntactic corruption
   - Evidence: REJECT decision bypasses retry logic

9. **NEVER ACCEPT after retries:**
   - Even if `accept_after_max_retries=True`, critical failures REJECT
   - Evidence: Critical check happens first in decision flow

---

## Decision Flow Integration

```
ValidationDecisionEngine.decide(validation_result, retry_count):
  ┌─────────────────────────────────┐
  │ 1. Check critical validators     │
  └────┬────────────────────────────┘
       │
       ├─ _check_critical_failure(validation_result)
       │  ├─ For each issue with ERROR severity:
       │  │  └─ If issue.validator in CRITICAL_VALIDATORS:
       │  │     └─→ REJECT ("Critical {validator} failed")
       │
  ┌────▼────────────────────────────┐
  │ 2. Count non-critical errors     │
  └────┬────────────────────────────┘
       │
       ├─ error_count = count(issues with severity=ERROR, validator NOT in CRITICAL)
       │
  ┌────▼────────────────────────────┐
  │ 3. Standard decision logic       │
  └────┬────────────────────────────┘
       │
       ├─ error_count == 0? → ACCEPT
       ├─ error_count >= threshold? → REJECT
       └─ retry_count < max? → RETRY
       │
       ▼
     Return (decision, reason)
```

**Evidence:** Flow from VAL-001 spec + critical validator check method

---

## Rationale

### Why PlaceholderValidator is Critical

**Problem:** Corrupted placeholders break reconstructed output

**Example:**
```markdown
Source: Visit our {{LINK_1}} for more information.
Translation (bad): Visitez notre site pour plus d'informations.
```

**Impact:**
- Placeholder replacement fails
- Final output has no link
- Silent data loss

**Why critical:** Syntactic correctness is non-negotiable (can't guess replacement)

### Why CodeBlockValidator is Critical

**Problem:** Broken code blocks corrupt technical documentation

**Example:**
```markdown
Source:
```python
def hello():
    print("Hello")
```

Translation (bad):
``python
def hello():
    print("Bonjour")
```

**Impact:**
- Code fence not closed
- Markdown rendering breaks
- Code content translated (wrong!)

**Why critical:** Code must remain executable and unchanged

### Why LinkValidator is Critical

**Problem:** Broken links destroy navigation and references

**Example:**
```markdown
Source: See [documentation](https://example.com/docs)
Translation (bad): Voir documentation(https://example.com/docs
```

**Impact:**
- Link syntax invalid
- Markdown parser fails
- Navigation broken

**Why critical:** Links are structural elements, not just content

---

## Validation Suite Integration

### Validator Registration

**ValidationSuite class** (inferred):
```python
class ValidationSuite:
    def __init__(self):
        self.validators = [
            PlaceholderValidator(),     # Critical
            CodeBlockValidator(),        # Critical
            LinkValidator(),             # Critical
            StructureValidator(),        # Non-critical
            TerminologyValidator(),      # Non-critical
            CompletenessValidator(),     # Non-critical
            # ... 4 more non-critical validators
        ]
```

**Evidence:** 10 validators mentioned in surface inventory, 3 critical validators in decision engine

### Validator Naming Convention

**Decision engine expects class names:**
- Validator issues include `validator_name` field
- Decision engine matches against `CRITICAL_VALIDATORS` set
- Example: Issue from PlaceholderValidator has `validator_name="PlaceholderValidator"`

**Evidence:** String matching in `_check_critical_failure` method

---

## Configuration

### Critical Validators (Immutable)

```python
# Hardcoded in decision_engine.py
CRITICAL_VALIDATORS = {
    "PlaceholderValidator",
    "CodeBlockValidator",
    "LinkValidator",
}
```

**Evidence:** Lines 59-63

**No config file:**
- Cannot be changed via YAML
- Cannot be disabled via CLI
- Cannot be modified at runtime

### Validator-Specific Configuration

**PlaceholderValidator:**
```python
PlaceholderValidator(
    placeholder_pattern=r"\{\{([A-Z_]+)_(\d+)\}\}",
    strict_order=False,  # Optional: enforce placeholder order
)
```

**LinkValidator:**
```python
LinkValidator(
    check_url_changes=True,           # Flag URL changes
    allow_url_translation=False,      # Reject URL changes
)
```

**Evidence:** Validator initialization parameters in respective files

---

## Errors and Edge Cases

### Edge Cases

**Validator issue without validator_name field:**
- Behavior: Not recognized as critical
- Risk: Critical error treated as non-critical
- Mitigation: Ensure all validators populate validator_name

**Multiple critical validators fail:**
- Behavior: First critical error triggers REJECT
- Reason string mentions first detected critical validator

**Warning from critical validator:**
- Behavior: NOT treated as critical failure
- Only ERROR severity from critical validators causes REJECT
- Example: LinkValidator link count mismatch is WARNING, not ERROR

**Critical validator disabled in ValidationSuite:**
- Behavior: Decision engine still expects it in results
- Risk: If removed from suite, can't fail → silently disabled
- Mitigation: Contract test ensures all critical validators registered

**Typo in validator name:**
- Example: "PlaceHolderValidator" vs "PlaceholderValidator"
- Behavior: Not matched in CRITICAL_VALIDATORS set
- Risk: Treated as non-critical
- Mitigation: Contract test validates validator name consistency

---

## Side Effects

### Logging

**Critical failure detection:**
```python
logger.error(f"Critical validator {validator_name} failed: {reason}")
```

**REJECT decision:**
```python
logger.info(f"Validation decision: REJECT, reason: Critical {validator_name} failed")
```

**Evidence:** Inferred from decision engine logging pattern

### No Direct Side Effects

- Decision engine is pure logic
- No file writes
- No cache updates
- No metrics (decision engine is stateless)

---

## Evidence

### Code Locations

| Component | File | Lines | Symbol |
|-----------|------|-------|--------|
| Critical validator set | src/translation_engine/validation/decision_engine.py | 59-63 | CRITICAL_VALIDATORS |
| Critical failure check | Same | 196-210 | _check_critical_failure() |
| Decision rules comment | Same | 9 | Comment documenting rule #1 |
| PlaceholderValidator | src/translation_engine/validation/placeholder_validator.py | 1-150 | PlaceholderValidator |
| LinkValidator | src/translation_engine/validation/link_validator.py | 1-100 | LinkValidator |

### Dependencies

| Dependency | Purpose | Evidence |
|------------|---------|----------|
| ValidationResult | Contains issues list | src/translation_engine/validation/base.py |
| ValidationSeverity | ERROR vs WARNING | src/translation_engine/validation/base.py |
| Validator (base class) | Common interface | src/translation_engine/validation/base.py |

### Test Evidence

**Existing Tests:**
- `tests/unit/validation/test_decision_engine.py` - Decision engine tests
- `tests/integration/test_e2e_validation.py` - E2E validation tests
- Likely: `tests/unit/validation/test_placeholder_validator.py`
- Likely: `tests/unit/validation/test_link_validator.py`

**Missing Contract Tests:**
- Critical validators always REJECT (regardless of mode)
- Critical failure bypasses retry logic
- Critical failure bypasses error threshold
- All critical validators registered in ValidationSuite
- Validator name consistency (no typos)

---

## Verification Status

🔍 **EVIDENCE_ONLY**

**Verification Steps Required:**

1. **Create contract test:** `tests/contract/test_val_critical_validators.py`
2. **Test critical invariants:**
   - Critical validators always REJECT on ERROR
   - Mode-independent enforcement (strict/normal/lenient)
   - Bypass retry logic (immediate REJECT)
   - Bypass error threshold
   - Cannot be disabled via configuration
3. **Test each critical validator:**
   - PlaceholderValidator errors → REJECT
   - CodeBlockValidator errors → REJECT
   - LinkValidator errors → REJECT
4. **Test edge cases:**
   - Warnings from critical validators (should not REJECT)
   - Multiple critical validators fail (first triggers REJECT)
   - Validator name typo (should be caught)
5. **Test ValidationSuite integration:**
   - All critical validators registered
   - Validator names match CRITICAL_VALIDATORS set
6. **Link to spec:** Add docstring `CONTRACT: specs/features/val-002-critical-validators.md`

**Blockers:** None

---

## Related Specs

- [VAL-001: Validation Decision Engine](val-001-decision-engine.md) - Decision logic implementation
- [CLI-002: Validation Control](cli-002-validation-control.md) - Mode configuration (but critical validators bypass mode)
- [API-001: translate_file Method](api-001-translate-file.md) - Validation enforcement
- [SYS-004: Validation Pipeline](sys-004-validation-pipeline.md) - All 10 validators
