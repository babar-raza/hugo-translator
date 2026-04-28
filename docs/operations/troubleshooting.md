# Troubleshooting Guide

This guide helps you diagnose and fix common validation errors, tune validation thresholds, optimize performance, and resolve frequently encountered issues.

## Table of Contents

- [Common Validation Errors](#common-validation-errors)
- [How to Fix Rejection Issues](#how-to-fix-rejection-issues)
- [How to Tune Thresholds](#how-to-tune-thresholds)
- [Performance Optimization](#performance-optimization)
- [FAQ](#faq)

## Common Validation Errors

### CompletenessValidator Errors

#### Error: "Segment X not translated"

**Symptom**:
```
[ERROR] CompletenessValidator: Segment 12 not translated
Location: segment_12
```

**Cause**: Translation map is missing a segment ID, typically due to:
- LLM skipped a segment in output
- Segmentation mismatch between source and translation
- Empty line handling issue

**Fix**:
1. Check segment extraction logic for edge cases
2. Verify all segments are passed to LLM
3. Enable retry - often fixes itself on second attempt
4. If persistent, check for unusual formatting in source segment

**Prevention**:
```yaml
# Enable completeness validator
validators:
  completeness:
    enabled: true
```

---

#### Error: "Found N untranslated placeholders"

**Symptom**:
```
[ERROR] CompletenessValidator: Found 3 untranslated placeholders
Location: translation_output
Suggestion: Placeholders must be restored: ['{PLACEHOLDER_5}', '{TERM_2}', '{SHORTCODE_1}']
```

**Cause**: Placeholders were not restored after translation:
- Placeholder restoration logic failed
- LLM corrupted placeholder syntax
- Mismatch between placeholder IDs

**Fix**:
1. Check placeholder restoration code for bugs
2. Verify placeholder map is correct
3. Inspect LLM output for malformed placeholders (e.g., `{PLACEHOLDER_5` missing `}`)
4. Enable placeholder validation before translation

**Prevention**:
```yaml
# Ensure placeholder validator is enabled
validators:
  placeholder:
    enabled: true
```

---

### LanguageConsistencyValidator Errors

#### Error: "Wrong language detected: en (expected de)"

**Symptom**:
```
[ERROR] LanguageConsistencyValidator: Wrong language detected: en (expected de)
Location: translation
```

**Cause**: Translation is in wrong language:
- LLM generated English instead of target language
- Translation prompt unclear about target language
- Insufficient target language examples in prompt

**Fix**:
1. Review translation prompt - ensure target language is explicit
2. Add target language examples to prompt
3. Check LLM model selection - some models are better for certain languages
4. Retry translation - temperature variation may help

**Prevention**:
```python
# Ensure target_lang is passed in validation context
context = {
    'target_lang': 'de',  # ISO 639-1 code
    # ...
}
```

---

#### Error: "Low detection confidence: 0.72 < 0.85"

**Symptom**:
```
[WARNING] LanguageConsistencyValidator: Low detection confidence: 0.72 < 0.85
Location: translation
```

**Cause**: Language detection is uncertain:
- Text too short for reliable detection
- Mixed language content
- Heavy use of technical terms/code
- Translation is poor quality

**Fix**:
1. If text is very short (<20 chars), ignore this warning
2. If text is technical, lower confidence threshold
3. If translation is actually good, lower threshold
4. If translation is poor, investigate quality issues

**Threshold tuning**:
```yaml
validators:
  language_consistency:
    enabled: true
    confidence_threshold: 0.75  # Lower for technical content
```

---

### ShortcodePreservationValidator Errors

#### Error: "Shortcode missing in translation: {{< youtube ... >}}"

**Symptom**:
```
[ERROR] ShortcodePreservationValidator: Shortcode missing in translation: {{< youtube dQw4w9WgXcQ >}}
Location: shortcodes
```

**Cause**: Hugo shortcode was lost or corrupted:
- LLM translated shortcode name
- Shortcode syntax corrupted
- Placeholder protection failed

**Fix**:
1. Verify shortcode protection is enabled
2. Check placeholder replacement logic
3. Add explicit instruction in prompt: "Preserve Hugo shortcodes {{< ... >}} exactly"
4. Retry translation with feedback

**Prevention**:
```yaml
# Enable shortcode preservation
validators:
  shortcode_preservation:
    enabled: true
```

---

### TerminologyPreservationValidator Errors

#### Error: "Term 'Aspose' appears N times in source but is missing from translation"

**Symptom**:
```
[ERROR] TerminologyPreservationValidator: Term 'Aspose' (company_name) appears 3 time(s) in source but is missing from translation
Location: terminology.company_name
```

**Cause**: Protected term was not preserved:
- Terminology protection disabled or misconfigured
- LLM translated the term despite protection
- Placeholder restoration failed

**Fix**:
1. Verify term is in `terminology.yaml`
2. Check `preserve_mode` is set to `protect` or `both`
3. Verify placeholder protection is working
4. Add term to retry feedback for emphasis

**Config check**:
```yaml
global:
  exact_matches:
    - term: "Aspose"
      category: company_name
      case_sensitive: true
      preserve_mode: both  # Must be "protect" or "both"
      severity: error
```

---

#### Error: "Pattern-matched term 'DocumentBuilder' missing from translation"

**Symptom**:
```
[ERROR] TerminologyPreservationValidator: Pattern-matched term 'DocumentBuilder' (pascal_case_identifier) missing from translation
Location: terminology.pascal_case_identifier
```

**Cause**: Pattern-matched term was not preserved:
- Pattern not matching correctly
- Term protection failed
- LLM translated despite protection

**Fix**:
1. Test pattern in Python to verify it matches:
   ```python
   import re
   pattern = r"\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b"
   text = "Use DocumentBuilder class"
   matches = re.findall(pattern, text)
   print(matches)  # ['DocumentBuilder']
   ```
2. Verify pattern is in correct site override
3. Check preserve_mode setting
4. Add site-specific override if needed

---

### StructureValidator Errors

#### Error: "Heading count mismatch: source has 5, translation has 4"

**Symptom**:
```
[ERROR] StructureValidator: Heading count mismatch: source has 5, translation has 4
Location: structure
```

**Cause**: Markdown structure not preserved:
- LLM merged or split headings
- Heading level changed
- Heading removed

**Fix**:
1. Retry translation - usually fixes on second attempt
2. Add explicit instruction: "Preserve all markdown headings exactly"
3. Review source for unusual heading patterns
4. If persistent, check if heading is in code block (should be protected)

**Prevention**:
```yaml
decision_rules:
  retry_on_structure_error: true  # Enable retry on structure errors
```

---

### PlaceholderValidator Errors

#### Error: "Missing placeholder {PLACEHOLDER_5} in translation"

**Symptom**:
```
[ERROR] PlaceholderValidator: Missing placeholder {PLACEHOLDER_5} in translation
```

**Cause**: Placeholder was lost or corrupted:
- LLM removed placeholder
- Placeholder syntax corrupted (e.g., missing `}`)
- Placeholder ID changed

**Fix**:
**CRITICAL**: Placeholder errors trigger immediate REJECT (no retry)

1. Check placeholder replacement logic for bugs
2. Verify all placeholders are in translation prompt
3. Inspect LLM output for malformed placeholders
4. This is a critical error - fix the root cause, don't suppress

**Config**:
```yaml
decision_rules:
  reject_on_placeholder_error: true  # Keep this enabled
```

---

### LinkValidator Errors

#### Error: "Link missing in translation: [Text](./docs/README.md)"

**Symptom**:
```
[ERROR] LinkValidator: Link missing in translation: [Documentation](./docs/README.md)
Location: links
```

**Cause**: Markdown link was lost or corrupted:
- LLM corrupted link syntax
- Link URL changed
- Link removed

**Fix**:
**CRITICAL**: Link errors trigger immediate REJECT (no retry)

1. Verify link protection is enabled
2. Check placeholder replacement for links
3. Inspect LLM output for malformed links
4. Fix root cause - don't suppress link errors

**Config**:
```yaml
decision_rules:
  reject_on_link_error: true  # Keep this enabled
```

---

## How to Fix Rejection Issues

### Issue: Too Many Rejections

**Symptom**: High rejection rate (>10% of translations rejected)

**Diagnosis**:
1. Check telemetry metrics for rejection reasons
2. Identify most common validation errors
3. Review decision rules configuration

**Fix Strategy**:

**Option 1: Tune Thresholds** (if errors are acceptable)
```yaml
decision_rules:
  reject_on_error_count: 5  # Increase from 3 to 5
  accept_after_max_retries: true  # Accept best effort
```

**Option 2: Add Retry Attempts** (if errors are fixable)
```yaml
decision_rules:
  max_retry_attempts: 3  # Increase from 2 to 3
  retry_on_structure_error: true
  retry_on_terminology_warning: true
```

**Option 3: Disable Problematic Validators** (temporary, not recommended)
```yaml
validators:
  structure:
    enabled: false  # Disable if structure errors are common but acceptable
```

**Option 4: Improve Translation Prompt**
- Add explicit preservation instructions
- Provide examples of correct output
- Emphasize critical requirements (terminology, shortcodes)

---

### Issue: Rejections on First Error

**Symptom**: Translations rejected on first minor error

**Diagnosis**:
```yaml
# Check if strict mode is enabled
validation_modes:
  strict:
    reject_on_error_count: 1  # Rejects on first error
```

**Fix**:
```bash
# Use normal mode instead
translate-hugo --site products.aspose.net --validation-mode normal
```

Or adjust strict mode threshold:
```yaml
validation_modes:
  strict:
    reject_on_error_count: 2  # Allow one error before rejecting
```

---

### Issue: Critical Validators Too Strict

**Symptom**: Placeholder/link errors causing rejections for acceptable translations

**Diagnosis**:
```yaml
decision_rules:
  reject_on_placeholder_error: true
  reject_on_link_error: true
```

**Fix**:
**WARNING**: Only disable if you understand the risks

```yaml
decision_rules:
  reject_on_placeholder_error: false  # Allow retry on placeholder errors
  reject_on_link_error: false  # Allow retry on link errors
```

**Better alternative**: Fix root cause of placeholder/link corruption

---

## How to Tune Thresholds

### Tuning reject_on_error_count

**Goal**: Balance quality vs. acceptance rate

**Current value**: 3 (default)

**Tuning guide**:

| Value | Behavior | Use Case |
|-------|----------|----------|
| 1 | Reject on first error | Production, critical content |
| 2 | Tolerate one error | High-quality content |
| 3 | Tolerate multiple errors | General content (default) |
| 5 | Lenient | Draft content, testing |
| 10 | Very lenient | Exploratory translation |

**Decision**:
- **Decrease** (1-2) if quality is critical
- **Increase** (5+) if acceptance rate is too low
- **Keep default** (3) for balanced approach

**Monitoring**:
```bash
# Check rejection rate in telemetry
# Target: <5% rejection rate for general content
```

---

### Tuning max_retry_attempts

**Goal**: Balance retry cost vs. quality improvement

**Current value**: 2 (default, means 3 total attempts)

**Tuning guide**:

| Value | Total Attempts | Use Case |
|-------|----------------|----------|
| 0 | 1 (no retries) | Fast translation, testing |
| 1 | 2 | Quick turnaround |
| 2 | 3 | Balanced (default) |
| 3 | 4 | High-quality content |
| 5 | 6 | Critical content (expensive) |

**Cost analysis**:
- Each retry = 1 additional LLM call
- 2 retries = 3x LLM cost in worst case
- Most translations succeed on first or second attempt

**Decision**:
- **Decrease** (0-1) to reduce cost and latency
- **Increase** (3-5) for critical content
- **Keep default** (2) for balanced approach

---

### Tuning confidence_threshold (Language Consistency)

**Goal**: Balance detection accuracy vs. false positives

**Current value**: 0.85 (default)

**Tuning guide**:

| Value | Behavior | Use Case |
|-------|----------|----------|
| 0.95 | Very strict | Pure prose, marketing content |
| 0.85 | Balanced | General content (default) |
| 0.75 | Lenient | Technical content with code |
| 0.65 | Very lenient | Mixed content, short snippets |

**Factors to consider**:
- **Text length**: Short text (<50 chars) has lower confidence
- **Technical content**: Code/APIs lower confidence
- **Language difficulty**: Some languages harder to detect

**Decision**:
- **Increase** (0.90-0.95) for pure prose
- **Decrease** (0.70-0.80) for technical docs
- **Keep default** (0.85) for general content

---

### Tuning temperature_increment

**Goal**: Control retry creativity vs. consistency

**Current value**: 0.1 (default)

**Tuning guide**:

| Value | Behavior | Use Case |
|-------|----------|----------|
| 0.0 | No temperature change | Deterministic retries |
| 0.05 | Small increase | Subtle variation |
| 0.1 | Moderate increase | Balanced (default) |
| 0.2 | Large increase | Creative retries |

**Temperature progression** (default):
- Attempt 1: 0.7 (base)
- Retry 1: 0.8 (base + 0.1)
- Retry 2: 0.9 (base + 0.2)

**Decision**:
- **Set to 0.0** if you want consistent retries
- **Decrease** (0.05) for subtle variation
- **Increase** (0.2) if retries aren't helping
- **Keep default** (0.1) for balanced approach

---

## Performance Optimization

### Issue: Validation is Slow

**Symptom**: Validation takes >2 seconds per document

**Diagnosis**:
1. Profile validation time by validator
2. Identify slowest validators

**Fix**:

**Option 1: Disable Expensive Validators**
```yaml
validators:
  language_consistency:
    enabled: false  # Language detection can be slow
```

**Option 2: Optimize LanguageConsistencyValidator**
```yaml
validators:
  language_consistency:
    enabled: true
    confidence_threshold: 0.70  # Lower threshold = faster exit
```

**Option 3: Batch Processing**
- Validate multiple documents in parallel
- Use async validation if available

---

### Issue: Too Many Retries

**Symptom**: Many translations require 2-3 retries, slowing throughput

**Diagnosis**:
```bash
# Check retry rate in telemetry
# Target: <20% retry rate
```

**Fix**:

**Option 1: Improve Initial Translation Quality**
- Better translation prompt
- Add examples to prompt
- Use better LLM model

**Option 2: Reduce Retry Triggers**
```yaml
decision_rules:
  retry_on_terminology_warning: false  # Don't retry on warnings
```

**Option 3: Lower Thresholds**
```yaml
decision_rules:
  accept_warnings: true  # Accept translations with warnings
  reject_on_error_count: 5  # Higher tolerance
```

---

### Issue: High LLM Cost

**Symptom**: Validation retries increasing LLM costs

**Diagnosis**:
1. Calculate retry rate: `retries / total_translations`
2. Estimate cost: `retry_rate * avg_retries_per_doc * cost_per_call`

**Fix**:

**Option 1: Reduce Max Retries**
```yaml
decision_rules:
  max_retry_attempts: 1  # Reduce from 2 to 1
```

**Option 2: Use Cheaper Model for Retries**
- Use expensive model for initial translation
- Use cheaper model for retries
- (Requires code modification)

**Option 3: Aggressive Acceptance**
```yaml
decision_rules:
  accept_warnings: true
  accept_after_max_retries: true  # Always accept after retries
  reject_on_error_count: 5  # Higher tolerance
```

---

## FAQ

### Q: Why are my translations being rejected with "placeholder error"?

**A**: Placeholder errors are critical and trigger immediate rejection. This happens when:
1. LLM removes or corrupts a placeholder (e.g., `{PLACEHOLDER_5}` becomes `{PLACEHOLDER5}`)
2. Placeholder restoration fails due to bugs
3. Placeholder IDs don't match between source and translation

**Fix**: Check placeholder replacement/restoration code for bugs. This is a code-level issue, not a configuration issue.

---

### Q: How do I disable validation for testing?

**A**: Use one of these CLI flags:
```bash
# Disable all validation
translate-hugo --site products.aspose.net --disable-validation

# Or use validation mode "off"
translate-hugo --site products.aspose.net --validation-mode off

# Or force accept all translations
translate-hugo --site products.aspose.net --force-accept
```

---

### Q: Can I retry more than 2 times?

**A**: Yes, increase `max_retry_attempts`:
```yaml
decision_rules:
  max_retry_attempts: 3  # Allow 3 retries (4 total attempts)
```

**Warning**: Each retry = 1 additional LLM call. Be mindful of cost.

---

### Q: Why is language consistency validator failing on technical docs?

**A**: Technical documentation contains code, API names, and technical terms that lower language detection confidence.

**Fix**: Lower confidence threshold:
```yaml
validators:
  language_consistency:
    enabled: true
    confidence_threshold: 0.75  # Lower from 0.85 to 0.75
```

Or disable for technical sites:
```yaml
validators:
  language_consistency:
    enabled: false  # Disable for reference.aspose.net
```

---

### Q: How do I add a new term to terminology protection?

**A**: Edit `config/terminology.yaml`:

**For exact match**:
```yaml
global:
  exact_matches:
    - term: "MyProduct"
      category: product_name
      case_sensitive: true
      preserve_mode: both
      severity: error
```

**For pattern match**:
```yaml
global:
  patterns:
    - pattern: "MyProduct\\.[A-Z][a-z]+"
      category: product_family
      preserve_mode: protect
      severity: error
```

See [Terminology Pattern Syntax](../reference/terminology-pattern-syntax.md) for details.

---

### Q: What's the difference between "protect" and "validate" preserve modes?

**A**:
- **protect**: Replace term with placeholder before translation (prevents LLM from seeing/translating it)
- **validate**: Check term is preserved after translation (relies on LLM to preserve it)
- **both**: Protect AND validate (recommended for critical terms)
- **none**: No protection or validation

**Recommendation**: Use `both` for critical terms, `protect` for API identifiers, `validate` for testing.

---

### Q: Can I customize validation per site?

**A**: Yes, use site profile `validation` section:

```yaml
# config/site_profiles/reference.aspose.net.yaml
site_id: "reference.aspose.net"

validation:
  check_placeholders: true
  check_links: true
  check_yaml_structure: true
```

For terminology, use site overrides in `terminology.yaml`:
```yaml
site_overrides:
  reference.aspose.net:
    inherit_global: true
    patterns:
      - pattern: "\\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\\b"
        category: api_identifier
        preserve_mode: protect
        severity: error
```

---

### Q: What validation mode should I use?

**A**:

| Mode | Use Case |
|------|----------|
| **strict** | Production, API docs, critical content |
| **normal** | General content, blog posts (default) |
| **lenient** | Draft content, testing, high volume |

Command:
```bash
translate-hugo --site products.aspose.net --validation-mode normal
```

---

### Q: How do I preview validation decisions without writing files?

**A**: Use `--dry-run` flag:
```bash
translate-hugo --site products.aspose.net --dry-run --validation-mode strict
```

This shows what would happen without actually writing translated files.

---

### Q: Why are structure errors causing retries but not rejections?

**A**: Structure errors are considered fixable (retryable), unlike placeholder/link errors which are critical.

**Config**:
```yaml
decision_rules:
  retry_on_structure_error: true  # Retry on structure errors
  reject_on_placeholder_error: true  # Reject immediately on placeholder errors
```

**Rationale**: LLM can fix structure issues with feedback, but placeholder corruption is usually a bug.

---

### Q: Can I see validation feedback in the logs?

**A**: Yes, validation feedback is logged at INFO level:
```
INFO: VALIDATION FEEDBACK - Please address the following issues:
INFO: ERRORS (must fix):
INFO: 1. Shortcode missing in translation: {{< youtube ... >}}
```

Set log level to INFO or DEBUG:
```bash
translate-hugo --site products.aspose.net --log-level INFO
```

---

### Q: What happens after max retries are exhausted?

**A**: Depends on `accept_after_max_retries`:

**If true** (default):
```yaml
decision_rules:
  accept_after_max_retries: true
```
Result: ACCEPT best effort translation, log warnings

**If false**:
```yaml
decision_rules:
  accept_after_max_retries: false
```
Result: REJECT translation, discard

**Recommendation**: Keep `true` unless quality is absolutely critical.

---

### Q: How do I know which validator is causing rejections?

**A**: Check telemetry metrics or logs:

**Logs**:
```
[ERROR] TerminologyPreservationValidator: Term 'Aspose' missing from translation
Decision: REJECT (critical validator failed: TerminologyPreservationValidator)
```

**Telemetry** (if enabled):
- Track rejection reasons
- Count failures per validator
- Analyze trends over time

---

### Q: Can I use different validation configs for different sites?

**A**: Partially. You can:
1. Use site-specific terminology overrides in `terminology.yaml`
2. Use CLI `--validation-config` to specify custom validation file
3. Use site profile `validation` section for basic settings

**Example**:
```bash
# Use custom validation for reference docs
translate-hugo --site reference.aspose.net --validation-config ./reference-validation.yaml
```

**Future**: Per-site validation config in site profiles (not yet implemented).

---

## Related Documentation

- [Validation Guide](./validation_guide.md) - How validators work and decision logic
- [Terminology Pattern Syntax](../reference/terminology-pattern-syntax.md) - Regex patterns for terminology protection
- [Configuration Reference](./configuration_reference.md) - Complete config file reference

## Update — 2026-02-16 22:36 PKT

### Worker Verification Delta (SR-03)

- `TranslationEngine` now resolves language detector via `_get_language_detector()` and initializes backward-compatible `self.detector` alias.
- This removes the prior runtime crash path (`'TranslationEngine' object has no attribute 'detector'`) in current oneshot worker output.
- New blocker observed during manual oneshot: repeated `FINAL PURITY CHECK FAILED` loops on `file1.md`, then timeout (`translate_directory(...) timed out after 60s`) and `[Errno 22] Invalid argument` for fixture files.

Evidence:
- `reports/agents/Agent_B/ORCH-AW-002/run_20260216_223609/artifacts/git_diff.txt`
- `reports/agents/Agent_C/ORCH-AW-003/run_20260216_223609/artifacts/pytest_worker_slice.txt`
- `reports/agents/Agent_C/ORCH-AW-003/run_20260216_223609/artifacts/content_worker_oneshot.txt`
- `reports/agents/Agent_C/ORCH-AW-003/run_20260216_223609/artifacts/content_worker_new_blockers.txt`
