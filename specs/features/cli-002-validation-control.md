# CLI-002: Validation Control Flags

**Feature:** CLI flags for validation mode configuration
**Status:** 🔍 EVIDENCE_ONLY
**Last Updated:** 2025-12-26

---

## Summary

Command-line flags that control validation behavior: `--validation-mode`, `--no-validation`, `--strict-reject`, and related flags. Enables users to tune validation strictness from command line without modifying site profiles.

---

## Entry Points

**CLI Flags:**
```bash
translate-hugo --site SITE --validation-mode {strict|normal|lenient|off}
translate-hugo --site SITE --no-validation
translate-hugo --site SITE --strict-reject
```

**Parser Registration:**
- File: `src/cli.py`
- Lines: 290-298 (validation mode group)
- Lines: 153 (strict-reject flag)
- Argument group: "Validation Control"

**Usage Site:**
- Lines: 1187-1188 (logging validation mode override)
- Lines: 66 (storing validation_mode in overrides)
- Lines: 148-149 (passing to engine)

---

## Inputs/Outputs

### Input: --validation-mode

```bash
--validation-mode {strict|normal|lenient|off}
```

**Choices:**
- `strict`: Minimal error tolerance (reject_on_error_count=1, accept_warnings=False)
- `normal`: Balanced validation (reject_on_error_count=3, accept_warnings=True) [DEFAULT]
- `lenient`: Permissive validation (reject_on_error_count=5, accept_warnings=True)
- `off`: Disable all validation (same as --no-validation)

**Evidence:** Line 291 choices list

### Input: --no-validation

```bash
--no-validation
```

**Behavior:**
- Equivalent to `--validation-mode off`
- Quick disable without typing full flag
- Evidence: Line 298 help text

### Input: --strict-reject

```bash
--strict-reject
```

**Behavior:**
- Sets validation mode to `strict`
- Sets max retries to 0 (no automatic retries)
- Use case: Production deployments requiring high quality
- Evidence: Lines 153, 1187

**Implementation:**
```python
if overrides.strict_reject:
    overrides.validation_mode = "strict"
    overrides.max_retries = 0
```

### Output: Engine Configuration

**Passed to TranslationEngine:**
```python
TranslationEngine(
    validation_mode=args.validation_mode,  # strict/normal/lenient/None
    max_retries=args.max_retries,          # Override from strict-reject
    ...
)
```

**Evidence:** Lines 148-149 (CLI override passing)

---

## Invariants

### Must (Critical)

1. **CLI overrides site profile:**
   - IF --validation-mode specified → override site profile setting
   - Evidence: Lines 148-149, 1187-1188
   ```python
   if self.validation_mode and self.validation_mode != "off":
       overrides["validation_mode"] = self.validation_mode
   ```

2. **"off" disables validation:**
   - IF validation_mode == "off" → enable_validation=False
   - Evidence: Lines 142
   ```python
   elif self.validation_mode == "off":
       enable_validation = False
   ```

3. **strict-reject sets strict mode + zero retries:**
   - MUST set validation_mode="strict"
   - MUST set max_retries=0
   - Evidence: Lines 153 (strict-reject parsing)

4. **Mutually exclusive with --validation-mode:**
   - Cannot use both --strict-reject and --validation-mode
   - (No explicit validation, but documentation implies this)

### Should (Important)

5. **Log validation mode override:**
   - SHOULD log when CLI overrides site profile validation mode
   - Evidence: Lines 1187-1188
   ```python
   elif overrides.validation_mode:
       logger.info(f"Validation mode: {overrides.validation_mode} (CLI override)")
   ```

6. **Default to site profile:**
   - If no CLI flag specified, use site profile setting
   - Site profile defaults to "normal" if not specified

### Never (Prohibited)

7. **NEVER ignore critical validators in lenient mode:**
   - Even lenient mode MUST enforce critical validators (placeholders, code blocks, links)
   - Evidence: Decision engine critical validator enforcement (separate spec)

---

## Configuration Flow

```
CLI Argument Parsing:
  ┌─────────────────────────────────┐
  │ 1. Parse --validation-mode arg  │
  └────┬────────────────────────────┘
       │
       ├─ --validation-mode=strict? → validation_mode="strict"
       ├─ --validation-mode=normal? → validation_mode="normal"
       ├─ --validation-mode=lenient? → validation_mode="lenient"
       ├─ --validation-mode=off? → validation_mode="off", enable_validation=False
       └─ --no-validation? → validation_mode="off", enable_validation=False
       │
  ┌────▼────────────────────────────┐
  │ 2. Check --strict-reject         │
  └────┬────────────────────────────┘
       │
       ├─ --strict-reject? → validation_mode="strict", max_retries=0
       │
  ┌────▼────────────────────────────┐
  │ 3. Store in CLIOverrides         │
  └────┬────────────────────────────┘
       │
       ├─ overrides.validation_mode = validation_mode
       ├─ overrides.max_retries = max_retries (if strict-reject)
       │
  ┌────▼────────────────────────────┐
  │ 4. Pass to TranslationEngine     │
  └────┬────────────────────────────┘
       │
       ├─ TranslationEngine(validation_mode=..., max_retries=...)
       │
  ┌────▼────────────────────────────┐
  │ 5. Engine applies to decision    │
  │    engine configuration          │
  └────┬────────────────────────────┘
       │
       ▼
     Validation Decision Engine configured
```

**Evidence:** Flow implemented across cli.py lines 66, 142, 148-149, 290-298, 1187-1188

---

## Validation Modes Specification

### Strict Mode

**Configuration:**
```python
{
    "reject_on_error_count": 1,      # Reject on first error
    "accept_warnings": False,         # Warnings also block acceptance
    "accept_after_max_retries": False # Reject if retries exhausted
}
```

**Use case:** Production deployments, critical content

**Behavior:**
- Single error → REJECT
- Warnings → REJECT (unless auto-fixable)
- No "best effort" acceptance after retries

### Normal Mode (Default)

**Configuration:**
```python
{
    "reject_on_error_count": 3,       # Tolerate 2 errors
    "accept_warnings": True,          # Warnings allowed
    "accept_after_max_retries": True  # Best effort after retries
}
```

**Use case:** General translation, balanced quality

**Behavior:**
- Up to 2 errors → RETRY
- 3+ errors → REJECT
- Warnings → ACCEPT
- After max retries → ACCEPT (best effort)

### Lenient Mode

**Configuration:**
```python
{
    "reject_on_error_count": 5,       # Tolerate 4 errors
    "accept_warnings": True,          # Warnings allowed
    "accept_after_max_retries": True  # Best effort after retries
}
```

**Use case:** Exploratory translation, low-priority content

**Behavior:**
- Up to 4 errors → RETRY
- 5+ errors → REJECT
- Critical validators still enforced (placeholders, code blocks, links)

### Off Mode

**Configuration:**
```python
enable_validation = False  # Skip validation entirely
```

**Use case:** Testing, debugging, trusted sources

**Behavior:**
- No validation runs
- All translations accepted
- Performance improvement (~10-15% faster)

**Evidence:** Mode configurations in decision engine initialization (engine.py lines 286-298)

---

## Examples

### Example 1: Strict Validation for Production

```bash
translate-hugo \
  --site products.aspose.net \
  --validation-mode strict \
  --langs fr de es
```

**Behavior:**
- Reject on first error
- No warnings accepted
- High quality guarantee

### Example 2: Quick Disable for Testing

```bash
translate-hugo \
  --site test.local \
  --no-validation \
  --langs fr
```

**Behavior:**
- Validation skipped
- All translations accepted
- Faster execution

### Example 3: Strict Reject (Zero Retries)

```bash
translate-hugo \
  --site products.aspose.net \
  --strict-reject \
  --langs fr
```

**Behavior:**
- Validation mode: strict
- Max retries: 0
- Fail fast on first error (no automatic retry)

### Example 4: Lenient Mode for Bulk Translation

```bash
translate-hugo \
  --site blog.example.com \
  --validation-mode lenient \
  --langs fr de es it pt
```

**Behavior:**
- Tolerate up to 4 errors
- Best effort acceptance
- Maximize translation coverage

---

## Errors and Edge Cases

### Edge Cases

**Both --validation-mode and --strict-reject:**
- Behavior: Last flag wins (argparse behavior)
- Recommendation: Document as mutually exclusive

**validation_mode="off" vs enable_validation=False:**
- Behavior: Equivalent
- Evidence: Line 142 maps "off" to enable_validation=False

**Invalid mode string:**
- Behavior: argparse rejects with error (choices validation)
- Evidence: Line 291 choices constraint

**Site profile has validation_mode, CLI overrides:**
- Behavior: CLI takes precedence
- Evidence: Lines 148-149, 1187-1188

---

## Side Effects

### Logging

**Validation mode override:**
```python
logger.info(f"Validation mode: {overrides.validation_mode} (CLI override)")
```

**Evidence:** Lines 1187-1188

### Engine Configuration

**Decision engine:**
- Receives validation_mode during initialization
- Applies mode-specific thresholds
- Evidence: engine.py lines 286-298

### No Direct Side Effects

- No file writes
- No cache modifications
- Configuration only

---

## Evidence

### Code Locations

| Component | File | Lines | Symbol |
|-----------|------|-------|--------|
| Argument definition | src/cli.py | 290-298 | --validation-mode parser |
| No-validation flag | src/cli.py | 295-298 | --no-validation parser |
| Strict-reject flag | src/cli.py | 153 | --strict-reject parser |
| Storage in overrides | src/cli.py | 66 | self.validation_mode |
| Mode-to-bool conversion | src/cli.py | 142 | "off" → enable_validation=False |
| Engine override passing | src/cli.py | 148-149 | overrides dict construction |
| Logging override | src/cli.py | 1187-1188 | logger.info |

### Dependencies

| Dependency | Purpose | Evidence |
|------------|---------|----------|
| argparse | Flag parsing | Standard library |
| ValidationDecisionEngine | Decision config | src/translation_engine/validation/decision_engine.py |
| TranslationEngine | Receives override | src/translation_engine/engine.py |

### Test Evidence

**Existing Tests:**
- `tests/integration/test_cli.py` - CLI argument parsing tests

**Missing Contract Tests:**
- Validation mode override enforcement
- Strict mode rejects on first error
- Lenient mode accepts more errors
- Off mode skips validation entirely
- strict-reject sets max_retries=0

---

## Verification Status

🔍 **EVIDENCE_ONLY**

**Verification Steps Required:**

1. **Create contract test:** `tests/contract/test_cli_validation_control.py`
2. **Test invariants:**
   - CLI overrides site profile
   - "off" disables validation
   - strict-reject sets strict + zero retries
3. **Test modes:**
   - Strict: reject on 1 error
   - Normal: accept up to 2 errors
   - Lenient: accept up to 4 errors
   - Off: skip validation
4. **Test edge cases:**
   - Both --validation-mode and --strict-reject
   - Invalid mode string (argparse validation)
5. **Link to spec:** Add docstring `CONTRACT: specs/features/cli-002-validation-control.md`

**Blockers:** None

---

## Related Specs

- [VAL-001: Validation Decision Engine](val-001-decision-engine.md) - Decision logic implementation
- [CLI-001: Main Translation Command](cli-001-main-translate.md) - Main CLI entry point
- [API-001: translate_file Method](api-001-translate-file.md) - Validation enforcement
