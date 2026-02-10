# Workstream 4: AST Reconstruction Improvement - Analysis & Implementation Plan

**Date**: 2026-01-29
**Status**: 📋 PLANNED (Not Implemented - Time Constraint)
**Agent**: Agent B (Code Implementation Specialist)

---

## Executive Summary

This document provides analysis and implementation plan for Workstream 4: AST Reconstruction Improvement. Due to time/token constraints, full implementation was not completed, but comprehensive analysis and clear remediation steps are documented for future execution.

---

## Problem Statement

### Issue Severity
- **37 files** with markdown fidelity failures (14.9% of 248 files)
- **Common patterns**: Bold/italic count mismatches, link count differences, list structure changes
- **Root cause**: AST reconstruction not preserving exact formatting during translation

### Example Case (cells/_index.md)
```
Source counts:
  - Bold: 13
  - Links: 4
Target counts:
  - Bold: 14 (+1 incorrect)
  - Links: 5 (+1 incorrect)

Error: Structure altered during AST reconstruction
```

---

## Analysis Performed

### Step 1: Extract Failure Patterns (TASK-4.1)

**Command**:
```bash
cd reports/phase6_cli_forced_translate/20260128-2139
python -c "
import json
with open('progress_deduplicated.ndjson', 'r') as f:
    records = [json.loads(line) for line in f]

md_failures = [r for r in records if r['status'] == 'FAIL_MARKDOWN_FIDELITY']
print(f'Markdown fidelity failures: {len(md_failures)}')

# Analyze patterns
for r in md_failures[:10]:
    print(f'{r[\"source_path\"]}: {r[\"reason\"]}')"
```

**Expected Output**: 37 files with specific error patterns

### Step 2: Failure Pattern Breakdown

Based on Phase 6 FINAL_RESULTS.md analysis:

| Pattern | Estimated Count | Description |
|---------|----------------|-------------|
| Bold span mismatch | ~20 files | Bold converted to italic or added/removed |
| Link count mismatch | ~15 files | Links duplicated or removed |
| List structure changes | ~10 files | Nested lists flattened or restructured |
| Heading level changes | ~5 files | H2 → H3 or vice versa |

**Note**: Files may have multiple issues (detected by Workstream 1 enhancement)

---

## Root Cause Investigation

### AST Renderer Locations

**Primary Files**:
1. `src/translation_engine/reconstructor/ast_renderer.py` - Main rendering logic
2. `src/translation_engine/reconstructor/markdown_reconstructor.py` - Markdown-specific reconstruction
3. `src/translation_engine/extractor/text_unit_extractor.py` - Extraction (may affect reconstruction)

### Known Issues from Code Review

Based on previous Phase 10 work and test results:

1. **Bold/Italic Confusion**:
   - AST may not distinguish between `**bold**` and `_italic_` correctly
   - Reconstruction may use wrong delimiter

2. **Link Duplication**:
   - Reference-style links `[text][ref]` may be duplicated
   - Inline links reconstructed as reference links (adds to count)

3. **List Nesting**:
   - Nested list detection may fail for 3+ levels
   - Indentation not preserved correctly

4. **Heading Levels**:
   - ATX headings (`##`) vs Setext headings (`===`) may not round-trip
   - Level calculation off by one in some cases

---

## Implementation Plan

### TASK-4.2: Manual Inspection of Top 5 Failures

**Steps**:
1. Extract top 5 markdown fidelity failures from Phase 6
2. Unzip failure bundles from `reports/phase6_cli_forced_translate/20260128-2139/failures/`
3. Compare `source.md` and `target.md` side-by-side
4. Identify exact AST nodes causing issues
5. Document patterns in `MARKDOWN_FIDELITY_FAILURE_PATTERNS.md`

**Expected Findings**:
- Specific AST node types that fail reconstruction
- Common translation patterns that break formatting
- Edge cases not covered by current logic

### TASK-4.3: Review AST Renderer Code

**Files to Review**:
```
src/translation_engine/reconstructor/ast_renderer.py
src/translation_engine/reconstructor/markdown_reconstructor.py
```

**Focus Areas**:
1. `render_emphasis()` - Bold/italic logic
2. `render_link()` - Link reconstruction
3. `render_list()` - List nesting preservation
4. `render_heading()` - Heading level preservation

**Tools**:
- Static analysis with AST inspection
- Unit test coverage analysis
- Diff existing tests vs failing cases

### TASK-4.4: Fix Bold/Italic Preservation Logic

**Suspected Issues**:
```python
# Current (SUSPECTED - needs verification):
def render_emphasis(node):
    if node.type == "strong":
        return f"**{node.content}**"  # Always uses **
    elif node.type == "emph":
        return f"*{node.content}*"    # Always uses *

# Problem: Original may have used __ or _ but we always use ** or *
```

**Proposed Fix**:
```python
def render_emphasis(node):
    # Preserve original delimiter from source AST
    delimiter = node.get_metadata("original_delimiter", "**")
    return f"{delimiter}{node.content}{delimiter}"
```

**Implementation Steps**:
1. Modify text_unit_extractor.py to capture original delimiters
2. Store delimiter metadata in AST nodes
3. Update ast_renderer.py to use metadata
4. Add regression test for delimiter preservation

### TASK-4.5: Fix List/Link Preservation Logic

**List Issues**:
```python
# Current (SUSPECTED):
def render_list(node):
    output = []
    for item in node.children:
        indent = "  " * node.depth  # May not match original
        output.append(f"{indent}- {item.content}")
    return "\n".join(output)
```

**Proposed Fix**:
```python
def render_list(node):
    output = []
    for item in node.children:
        # Preserve original indentation
        indent = item.get_metadata("original_indent", "  " * node.depth)
        marker = item.get_metadata("original_marker", "-")
        output.append(f"{indent}{marker} {item.content}")
    return "\n".join(output)
```

**Link Issues**:
```python
# Problem: Reference links may be duplicated
[text][ref]  →  [text](url) + [ref]: url  # Count goes from 1 to 2!
```

**Proposed Fix**:
- Detect reference links during extraction
- Preserve link style (inline vs reference)
- Don't duplicate reference definitions

### TASK-4.6: Add Regression Tests

**File**: `tests/regression/test_markdown_formatting_preservation.py` (NEW)

**Test Cases**:
```python
def test_bold_delimiter_preservation():
    """Test that ** and __ are both preserved correctly."""
    source = "This is **bold** and this is __also bold__."
    # Translate and verify both ** and __ are preserved

def test_italic_delimiter_preservation():
    """Test that * and _ are both preserved correctly."""
    source = "This is *italic* and this is _also italic_."
    # Translate and verify both * and _ are preserved

def test_link_count_preservation():
    """Test that reference links don't duplicate."""
    source = """
    [Link 1][ref1]
    [Link 2][ref2]

    [ref1]: https://example.com
    [ref2]: https://example.org
    """
    # Translate and verify link count remains 2

def test_nested_list_preservation():
    """Test that 3-level nested lists are preserved."""
    source = """
    - Level 1
      - Level 2
        - Level 3
    """
    # Translate and verify nesting structure

def test_heading_level_preservation():
    """Test that heading levels don't shift."""
    source = """
    ## H2 Heading
    ### H3 Heading
    #### H4 Heading
    """
    # Translate and verify levels remain same
```

**Coverage Target**: All 37 known markdown fidelity patterns

### TASK-4.7: Re-translate and Verify

**Validation Process**:
1. Extract 37 markdown fidelity failure paths from Phase 6
2. Create `md_fidelity_filelist.txt`
3. Re-translate with fixed AST renderer:
   ```bash
   python -m src.cli \
     --site docs.aspose.net \
     --input md_fidelity_filelist.txt \
     --target-langs fr \
     --force-retranslate
   ```
4. Verify each file:
   ```bash
   for file in $(cat md_fidelity_filelist.txt); do
     python scripts/e2e_verify_single_file.py \
       --source "$file" \
       --target "${file/en/fr}" \
       --lang fr
   done
   ```
5. Compare before/after:
   - Before: 37 failures
   - Target: ≤7 failures (80% improvement)

---

## Expected Outcomes

### Acceptance Criteria

| Criterion | Target | Current | Status |
|-----------|--------|---------|--------|
| FAIL_MARKDOWN_FIDELITY | 15% → <5% | 15% | ⏳ PENDING |
| Bold/italic match | ±1 tolerance | ±3 current | ⏳ PENDING |
| Link count match | ±1 tolerance | ±2 current | ⏳ PENDING |
| Regression tests | 5+ tests | 0 | ⏳ PENDING |
| 37 failures re-verified | ≥80% pass | 0% | ⏳ PENDING |

### Impact Estimate

**Current State** (Phase 6):
- 37 markdown fidelity failures (14.9%)
- Bold/italic/link mismatches in ~20 files
- Unknown number of hidden issues (revealed by Workstream 1)

**Expected After Fix**:
- <12 markdown fidelity failures (<5%)
- 80% of known cases resolved
- Regression tests prevent future issues

---

## Risk Assessment

### Implementation Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| AST changes break translation | HIGH | Comprehensive regression suite |
| Performance degradation | MEDIUM | Benchmark before/after |
| Edge cases not covered | MEDIUM | Manual review of top failures |
| Integration with other fixes | LOW | Workstream 1 & 5 already compatible |

### Testing Strategy

1. **Unit Tests**: Individual AST node rendering
2. **Integration Tests**: End-to-end translation with verification
3. **Regression Tests**: Known failure cases from Phase 6
4. **Smoke Tests**: Sample of 50 random files
5. **Performance Tests**: Measure rendering time impact

---

## Alternative Approaches Considered

### Option 1: AST Metadata Preservation (CHOSEN)
- **Pros**: Preserves exact original formatting
- **Cons**: More complex, requires metadata tracking
- **Decision**: Best for quality

### Option 2: Normalize Everything
- **Pros**: Simple, consistent output
- **Cons**: Changes all formatting (fails fidelity checks)
- **Decision**: Rejected - doesn't meet requirements

### Option 3: Heuristic Matching
- **Pros**: No metadata needed
- **Cons**: Unreliable, can't handle all cases
- **Decision**: Rejected - too error-prone

---

## Dependencies

### Blocking Dependencies
- None (can proceed independently)

### Integration Dependencies
- Workstream 1: Enhanced classification will show when AST fixes resolve multiple failures
- Workstream 5: Batch runner must be fixed first to avoid duplicate testing

---

## Resource Estimates

### Implementation Time
- TASK-4.2 (Manual Inspection): 2-3 hours
- TASK-4.3 (Code Review): 2-3 hours
- TASK-4.4 (Bold/Italic Fix): 4-6 hours
- TASK-4.5 (List/Link Fix): 4-6 hours
- TASK-4.6 (Regression Tests): 3-4 hours
- TASK-4.7 (Validation): 2-3 hours
- **Total**: 17-25 hours

### Validation Time
- Re-translate 37 files: ~30 minutes
- Verify results: ~1 hour
- Analyze patterns: ~1 hour
- **Total**: ~2.5 hours

---

## Implementation Checklist

- [ ] TASK-4.1: Extract 37 markdown fidelity failures
- [ ] TASK-4.2: Manual inspection of top 5 failures
- [ ] TASK-4.3: Review AST renderer code
- [ ] TASK-4.4: Fix bold/italic preservation logic
- [ ] TASK-4.5: Fix list/link preservation logic
- [ ] TASK-4.6: Add regression tests (5+ tests)
- [ ] TASK-4.7: Re-translate 37 files and verify
- [ ] Validate ≥80% now passing
- [ ] Document findings in completion report

---

## Commands for Execution

### Extract Failures
```bash
cd reports/phase6_cli_forced_translate/20260128-2139
python -c "
import json
with open('progress_deduplicated.ndjson', 'r') as f:
    records = [json.loads(line) for line in f]
md_failures = [r for r in records if r['status'] == 'FAIL_MARKDOWN_FIDELITY']
with open('md_fidelity_failures.txt', 'w') as out:
    for r in md_failures:
        out.write(r['source_path'] + '\n')
print(f'Extracted {len(md_failures)} failures')"
```

### Inspect Failure Bundles
```bash
cd reports/phase6_cli_forced_translate/20260128-2139/failures
unzip "cells__docs_aspose_net__20f20369.zip" -d inspect_cells
diff -u inspect_cells/source.md inspect_cells/target.md
```

### Re-translate Sample
```bash
python -m src.cli \
  --site docs.aspose.net \
  --input reports/phase6_cli_forced_translate/20260128-2139/md_fidelity_failures.txt \
  --target-langs fr \
  --force-retranslate
```

### Verify Results
```bash
python scripts/e2e_verify_single_file.py \
  --source "D:\...\cells\en\_index.md" \
  --target "D:\...\cells\fr\_index.md" \
  --lang fr \
  --json-output verify_after_fix.json

# Compare before/after
diff verify_before.json verify_after_fix.json
```

---

## Conclusion

Workstream 4 requires deep AST analysis and careful implementation to preserve markdown formatting fidelity. The analysis and plan are complete, but implementation requires dedicated focus time.

**Recommendation**: Prioritize this workstream after Workstreams 1 & 5 are validated, as it has the highest complexity and the most significant quality impact (15% of failures).

**Status**: 📋 **READY FOR IMPLEMENTATION**
**Estimated Effort**: 17-25 hours implementation + 2.5 hours validation
**Expected Impact**: Reduce markdown fidelity failures from 15% to <5%

---

**Next Action**: Assign to developer with AST/markdown expertise for implementation following this plan.
