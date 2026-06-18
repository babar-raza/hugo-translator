# Agent Guardrails for Hugo Translator

This document defines rules that autonomous agents **MUST** follow when working on this codebase.

## Critical Rules

### 1. Never Edit Content Outputs to Pass Tests

**DO NOT** modify translated output files to make them pass quality checks.

- If translations fail analysis, investigate and fix the **translation pipeline**
- Never "clean up" output files to hide issues
- The goal is to improve translation quality, not to game metrics

### 2. Always Run Release Gate Before Declaring PASS

Before declaring any translation fix or feature as complete:

```powershell
# Windows
.\scripts\release_gate.ps1

# Linux/CI
./scripts/release_gate.sh
```

A fix is only valid if:
- Problem Rate ≤ 2%
- All unit tests pass
- No signature preservation failures
- No batch recovery failures

### 3. Never Broaden Preserve Patterns Without Tests

The `PRESERVE_PATTERNS` list in the AST renderer controls what content is not translated (code signatures, API references, etc.).

**Before adding new patterns:**
1. Write a test that demonstrates the pattern should be preserved
2. Add the test to `tests/regression/`
3. Only then add the pattern
4. Verify the pattern doesn't break existing translations

### 4. Signature-Like Tokens Are Non-Translatable By Design

Method signatures, class names, and API references like:
- `BarCodeReader(string)`
- `Aspose.BarCode.Recognition.BarCodeReader`
- `System.Exception(string message)`

These **MUST** remain in English. They are code identifiers, not prose.

### 5. Batch Recovery Must Increase Batch Size When Headroom Returns

When the batch processing system detects available VRAM headroom after a successful batch:
- It **MUST** attempt to increase batch size
- The increase formula should result in at least +1 for small batches
- This prevents the system from getting "stuck" at small batch sizes

See `test_batch_size_recovery.py` for the contract.

## Quality Thresholds

| Metric | Threshold | Action if Exceeded |
|--------|-----------|-------------------|
| Problem Rate | ≤ 2% | Investigate failing files |
| Signature Preservation | 100% | Fix pattern matching |
| Link Preservation | 100% | Check AST renderer |
| Markdown Structure | 100% | Validate reconstructor |

## Running Verification

### Quick Check (Unit Tests Only)
```powershell
pytest tests/contract/ tests/unit/phase-0 tests/unit/phase-1 -v
```

### Full Gate (Fixture Translation + Analysis)
```powershell
.\scripts\release_gate.ps1
```

### Specific Regression Tests
```powershell
pytest tests/regression/test_signature_preservation.py -v
pytest tests/regression/test_batch_size_recovery.py -v
```

## Common Mistakes to Avoid

1. **Editing score.md to change metrics** - This hides bugs
2. **Removing failing test assertions** - Tests exist for a reason
3. **Hardcoding expected values** - Use dynamic calculations
4. **Skipping validation mode** - Always validate translations
5. **Force-accepting translations** - Only do this if explicitly requested

## Evidence Requirements

When claiming a fix is complete, provide:
1. Run ID with timestamps
2. Score reports (score.md, score.json)
3. Git diff of changes
4. Test results log
5. Problem rate comparison (before/after)

## Contact

If these guardrails seem to block legitimate work, document the situation and escalate. Never bypass guardrails silently.
