# Invariant Checker CLI

## Purpose

Validates that all context protection invariants hold after translation. This tool ensures that critical structural elements (placeholders, code blocks, frontmatter, shortcodes) are preserved correctly through the translation pipeline.

Used in:
- **Phase 0**: Baseline validation
- **Phases 1-7**: Post-implementation verification
- **CI/CD**: Automated release gate
- **Development**: Quick validation during implementation

## Quick Start

### Basic Check
```bash
python scripts/check_invariants.py \
    --source data/golden_corpus/doc_001.md \
    --translated output/translated_doc_001.md
```

### Strict Mode (CI/CD)
```bash
python scripts/check_invariants.py \
    --source data/golden_corpus/doc_001.md \
    --translated output/translated_doc_001.md \
    --strict  # Exit code 1 if any check fails
```

### Quiet Mode (Only Failures)
```bash
python scripts/check_invariants.py \
    --source test.md \
    --translated test_trans.md \
    --quiet  # Only show failed checks
```

### JSON Output (Programmatic)
```bash
python scripts/check_invariants.py \
    --source test.md \
    --translated test_translated.md \
    --output results.json
```

## Invariant Categories

### 1. Placeholder Invariants (5 checks)

Validates that placeholder tokens (⟦P0_AST⟧, etc.) are preserved exactly:

- **Exact Count Match**: Same number of placeholders in source and translated
- **Set Equality**: Same placeholder IDs (order can differ)
- **No Duplicates (Source)**: No collision in source placeholders
- **No Duplicates (Translated)**: No collision in translated placeholders
- **Checksum Match**: SHA256 of sorted placeholder IDs must match

**Example Pass**:
```markdown
Source:      "This is ⟦P0_AST⟧ and ⟦P1_TERM⟧"
Translated:  "Ceci est ⟦P0_AST⟧ et ⟦P1_TERM⟧"
```

**Example Fail**:
```markdown
Source:      "This is ⟦P0_AST⟧ and ⟦P1_TERM⟧"
Translated:  "Ceci est ⟦P0_AST⟧"  # Missing P1_TERM
```

### 2. Boundary Invariants (2 checks)

Validates that placeholders are not concatenated with surrounding text:

- **Left Boundary**: Character before placeholder must not be alphanumeric
- **Right Boundary**: Character after placeholder must not be alphanumeric

**Valid Boundaries**: Space, punctuation (`.`, `,`, `!`, `?`), newline, start/end of line

**Invalid Boundaries**: Letters, digits, underscore, Unicode word characters (Greek, Cyrillic, etc.)

**Example Pass**:
```markdown
" ⟦P0_AST⟧ test"      # Space before/after
".⟦P0_AST⟧."          # Punctuation
```

**Example Fail**:
```markdown
"test⟦P0_AST⟧code"    # Letters adjacent
"λ⟦P0_AST⟧"           # Greek letter (word char)
```

### 3. Code Block Policy (1 check)

Validates that code in specific languages is not translated:

- **Full Bypass Languages**: Python, Java, C#, C, C++, Go, Rust, JavaScript, TypeScript
- **Requirement**: Code blocks in these languages must be byte-for-byte identical

**Example Pass**:
```markdown
Source:      ```python\ndef foo():\n    pass\n```
Translated:  ```python\ndef foo():\n    pass\n```
```

**Example Fail**:
```markdown
Source:      ```python\ndef foo():\n    pass\n```
Translated:  ```python\ndef bar():\n    pass\n```  # Modified!
```

### 4. Structural Integrity (2 checks)

Validates document structure preservation:

- **Frontmatter Keys Preserved**: YAML frontmatter keys must be identical (values can change)
- **Shortcode Syntax Valid**: No broken `{{<`, `{{% `, or `⟦` syntax

**Example Pass**:
```markdown
Source:      ---\ntitle: Test\ndate: 2025-01-01\n---\nContent
Translated:  ---\ntitle: Essai\ndate: 2025-01-01\n---\nContenu
```

**Example Fail**:
```markdown
Source:      ---\ntitle: Test\ndate: 2025-01-01\n---\nContent
Translated:  ---\ntitle: Essai\nauthor: New\n---\nContenu  # Different keys!
```

## Command-Line Options

| Option | Description | Default |
|--------|-------------|---------|
| `--source` | Path to source (original) document | Required |
| `--translated` | Path to translated document | Required |
| `--output` | Path to JSON output file | None (stdout only) |
| `--strict` | Exit with code 1 if any check fails | False |
| `--quiet` | Only show failures, suppress passing checks | False |

## Exit Codes

- **0**: All checks passed (or `--strict` not set)
- **1**: One or more checks failed (when `--strict` is set) OR file not found

## Output Format

### Human-Readable (Default)

```
============================================================
INVARIANT CHECK RESULTS
============================================================
Total Checks: 10
Passed: 9 [OK]
Failed: 1 [FAIL]
Pass Rate: 90.0%
============================================================

[OK]  PASS | placeholder_exact_count
       Expected 2 placeholders, found 2

[FAIL] FAIL | boundary_left
       Checked 2 placeholders, 1 left boundary violations
       violations: ['⟦P0_AST⟧ has invalid left boundary: 't'']

...
```

### JSON Output (`--output results.json`)

```json
{
  "summary": {
    "total_checks": 10,
    "passed": 9,
    "failed": 1,
    "pass_rate": 0.9
  },
  "results": [
    {
      "name": "placeholder_exact_count",
      "passed": true,
      "message": "Expected 2 placeholders, found 2",
      "details": {
        "expected_count": 2,
        "actual_count": 2,
        "missing": [],
        "extra": []
      }
    },
    ...
  ],
  "overall_pass": false
}
```

## Usage Patterns

### Batch Processing (All Corpus Files)

```bash
#!/bin/bash
# Check all files in golden corpus

CORPUS_DIR="data/golden_corpus"
OUTPUT_DIR="output/translated"

for file in "$CORPUS_DIR"/*.md; do
    base=$(basename "$file")
    echo "Checking: $base"

    python scripts/check_invariants.py \
        --source "$file" \
        --translated "$OUTPUT_DIR/$base" \
        --strict \
        || { echo "FAILED: $base"; exit 1; }
done

echo "All files passed!"
```

### CI/CD Integration

```yaml
# .github/workflows/test.yml

- name: Run Invariant Checks
  run: |
    python scripts/check_invariants.py \
      --source tests/fixtures/test_doc.md \
      --translated tests/fixtures/test_doc_translated.md \
      --strict \
      --output invariant_results.json

- name: Upload Results
  uses: actions/upload-artifact@v3
  with:
    name: invariant-check-results
    path: invariant_results.json
```

### Development Workflow

```bash
# Quick check during development
python scripts/check_invariants.py \
    --source tests/fixtures/example.md \
    --translated tests/work/example_translated.md \
    --quiet  # Only show failures
```

## Integration with Phases

### Phase 0: Baseline

After establishing baseline translation performance:

```bash
# Translate golden corpus with current system
python src/cli.py --input data/golden_corpus --output baseline_output

# Verify no invariants broken
for doc in data/golden_corpus/*.md; do
    python scripts/check_invariants.py \
        --source "$doc" \
        --translated "baseline_output/$(basename $doc)" \
        --strict
done
```

### Phase 6: Shadow Mode Testing

Compare old system vs new system outputs:

```bash
# Run both translation modes
python src/cli.py --input test_doc.md --output old_output.md
python src/cli.py --input test_doc.md --output new_output.md --use-ast-translation

# Verify new system preserves invariants
python scripts/check_invariants.py \
    --source test_doc.md \
    --translated new_output.md \
    --strict
```

### Phase 7: Release Gate

Final validation before production:

```bash
# Run full corpus through production candidate
python src/cli.py --input data/golden_corpus --output release_candidate

# Strict validation with JSON output
python scripts/check_invariants.py \
    --source data/golden_corpus/doc_001.md \
    --translated release_candidate/doc_001.md \
    --strict \
    --output release_gate.json

# Parse JSON for automated decision
python -c "
import json
with open('release_gate.json') as f:
    result = json.load(f)
    if not result['overall_pass']:
        print('RELEASE BLOCKED: Invariant violations detected')
        exit(1)
"
```

## Testing

Run the test suite:

```bash
# All tests
pytest tests/unit/test_invariant_checker.py -v

# Specific test class
pytest tests/unit/test_invariant_checker.py::TestPlaceholderInvariants -v

# Single test
pytest tests/unit/test_invariant_checker.py::TestPlaceholderInvariants::test_exact_count_pass -v
```

Expected coverage: >80% line coverage, all edge cases tested.

## Troubleshooting

### Issue: False Positives on Boundaries

**Symptom**: Legitimate placeholders flagged as boundary violations

**Solution**: Review boundary rules. If placeholders are inside code blocks, they should be exempt from boundary rules (not yet implemented, would require context-aware parsing).

### Issue: Unicode Normalization

**Symptom**: Checksums don't match due to NFC vs NFD normalization

**Solution**: Normalize all text with `unicodedata.normalize('NFC', text)` before hashing (currently not implemented).

### Issue: Performance on Large Corpus

**Symptom**: Slow when checking 1000+ documents

**Solution**: Use multiprocessing for parallel checking:

```python
from multiprocessing import Pool

def check_pair(source_translated_pair):
    source, translated = source_translated_pair
    return run_invariant_checks(source, translated)

with Pool(8) as pool:
    results = pool.map(check_pair, pairs)
```

### Issue: Regex Timeout on Deeply Nested Content

**Symptom**: Hangs on pathological cases (deeply nested structures)

**Solution**: Add timeout to regex searches with `concurrent.futures.TimeoutError`.

## Limitations

1. **Context-Agnostic Boundary Checks**: Does not distinguish placeholders inside code blocks (where boundaries don't matter) from those in prose
2. **Simple Frontmatter Parsing**: Only handles basic YAML keys, not nested structures
3. **No Unicode Normalization**: May produce false negatives if text uses different Unicode normalization forms
4. **Single-File Processing**: No batch mode built-in (use shell scripts for batching)

## Future Enhancements

- Context-aware boundary validation (exempt code blocks)
- Unicode normalization support
- Parallel processing for batch mode
- HTML report generation
- Statistical analysis across corpus
