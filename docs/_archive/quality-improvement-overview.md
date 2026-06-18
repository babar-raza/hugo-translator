# Quality Improvement Guide

**Status**: Core system feature - validation, terminology, and quality assurance

## Overview

The Hugo Translation System implements comprehensive quality assurance through multiple layers:

- **Validation Pipeline**: 10 validators check translation quality before writing files
- **Terminology Protection**: Preserves critical terms like company names, product names, and technical identifiers
- **Decision Engine**: Automated ACCEPT/RETRY/REJECT decisions based on configurable rules
- **Post-Translation Verification**: Detects language contamination and untranslated content

## Validation System

### How Validation Works

The validation engine runs multiple checks on each translated document:

```
Source Document
    ↓
Translation (LLM)
    ↓
Validation Suite (10 validators)
    ↓
Decision Engine (ACCEPT/RETRY/REJECT)
    ↓
[ACCEPT] → Write to disk
[RETRY]  → Retry with feedback (up to 2 times)
[REJECT] → Discard, log error
```

### Available Validators

#### Pre-Translation Validators

These run before translation to ensure source documents are valid:

- **YAMLValidator**: Validates YAML frontmatter syntax
- **PlaceholderValidator**: Validates placeholder integrity during translation
- **StructureValidator**: Validates markdown structure preservation
- **LinkValidator**: Validates link integrity

#### Post-Translation Validators

These run after translation to ensure quality:

- **CompletenessValidator**: Validates 100% segment coverage
- **LanguageConsistencyValidator**: Validates target language consistency using langdetect
- **ShortcodePreservationValidator**: Validates Hugo shortcode preservation
- **FrontmatterProtectionValidator**: Validates frontmatter field protection rules
- **TerminologyPreservationValidator**: Validates terminology preservation
- **FilePlacementValidator**: Validates file placement and directory structure

### Decision Matrix

| Priority | Condition | Decision | Reason |
|----------|-----------|----------|--------|
| 1 | Critical validator failed | **REJECT** | PlaceholderValidator, LinkValidator errors |
| 2 | Error count ≥ threshold | **REJECT** | Too many errors (default: 3) |
| 3 | No errors, warnings OK | **ACCEPT** | Translation is acceptable |
| 4 | Errors + retries available | **RETRY** | Issues are fixable, retry with feedback |
| 5 | Exhausted retries + accept_after_max_retries=true | **ACCEPT** | Best effort after retries |
| 6 | Exhausted retries + accept_after_max_retries=false | **REJECT** | Failed after all retries |

### Validation Modes

**Strict Mode**: Zero tolerance, minimal retries
```yaml
strict:
  accept_warnings: false
  reject_on_error_count: 1
  max_retry_attempts: 1
```

**Normal Mode**: Balanced validation (default)
```yaml
normal:
  accept_warnings: true
  reject_on_error_count: 3
  max_retry_attempts: 2
```

**Lenient Mode**: Tolerant of issues, more retries
```yaml
lenient:
  accept_warnings: true
  reject_on_error_count: 5
  max_retry_attempts: 2
```

### CLI Usage

```bash
# Use strict validation mode
translate-hugo --site products.aspose.net --validation-mode strict

# Disable validation completely
translate-hugo --site products.aspose.net --disable-validation

# Use custom validation config
translate-hugo --site products.aspose.net --validation-config ./custom-validation.yaml

# Preview validation decisions without writing files
translate-hugo --site products.aspose.net --dry-run
```

## Terminology Protection

### How Terminology Protection Works

Terminology protection ensures critical terms are preserved during translation:

1. **Protection Phase**: Terms replaced with placeholders before translation
2. **Translation Phase**: LLM translates with placeholders intact
3. **Restoration Phase**: Original terms restored from placeholders
4. **Validation Phase**: Ensures all terms present in final translation

### Configuration Structure

Terminology configuration in `config/terminology.yaml`:

```yaml
version: "1.0"

global:
  exact_matches:
    - term: "Aspose"
      category: company_name
      case_sensitive: true
      preserve_mode: both
      severity: error

  patterns:
    - pattern: "Aspose\\.[A-Z][a-z]+"
      category: product_family
      preserve_mode: protect
      severity: error

site_overrides:
  reference.aspose.net:
    inherit_global: true
    patterns:
      - pattern: "\\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\\b"
        category: pascal_case_identifier
        preserve_mode: protect
        severity: error
```

### Preserve Modes

- **protect**: Replace with placeholders, skip validation
- **validate**: Allow LLM to handle, validate after translation
- **both**: Full protection + validation (recommended)
- **none**: No protection

### Pattern Syntax

Terminology patterns use Python regular expressions:

```yaml
# Product family pattern
pattern: "Aspose\\.[A-Z][a-z]+"

# PascalCase identifiers
pattern: "\\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\\b"

# UPPER_CASE constants
pattern: "\\b[A-Z_]+\\b"
```

### Site-Specific Overrides

Different sites can customize terminology rules:

```yaml
site_overrides:
  reference.aspose.net:
    inherit_global: true
    patterns:
      - pattern: "\\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\\b"
        category: pascal_case_identifier
        preserve_mode: protect
        severity: error
```

## Post-Translation Verification

### Overview

Post-translation verification detects quality issues after the main translation process using ML language detection. Requires `langdetect` dependency.

### What Gets Checked

- **Language Detection**: Ensures translation is in target language (≥85% confidence)
- **Content Filtering**: Skips technical content (code, URLs, shortcodes)
- **Frontmatter & Body**: Checks all text fields for language consistency

### Setup

```bash
pip install langdetect
# or
pip install -e ".[quality]"
```

### Usage

```bash
# Enable verification
translate-hugo --verify

# Enable with automatic retry on failure
translate-hugo --verify --fix
```

### Common Issues

- **False Positives**: Technical terms flagged as wrong language
- **Detection Failures**: Low confidence on short/ambiguous text
- **Performance Impact**: ~10-20% slower due to language analysis

## Quality Improvement Strategies

### Phase 1: Quick Wins (1-3 Days)

#### 1. Terminology Protection System
- **Impact**: Fixes 40% of terminology issues
- **Effort**: 4-6 hours
- Pre-translation term protection with placeholder replacement

#### 2. Post-Processing Language Filters
- **Impact**: Fixes 80% of language contamination
- **Effort**: 3-4 hours
- Language-specific correction patterns (e.g., Portuguese → Spanish)

#### 3. Quality Scoring Gate
- **Impact**: Catches 70% of quality issues automatically
- **Effort**: 4-5 hours
- Automated quality scoring with configurable thresholds

### Phase 2: Medium-Term (1-2 Weeks)

#### 1. Model Upgrade
- **Current**: M2M100-418M
- **Recommended**: M2M100-1.2B (3x larger, better quality)
- **Impact**: +13% quality improvement

#### 2. Human-in-the-Loop Review
- Flag low-quality translations for human review
- Build correction database for continuous improvement
- Integrate with CI/CD pipelines

#### 3. Context-Aware Translation
- Provide document context to improve coherence
- Better pronoun resolution and terminology consistency

### Phase 3: Long-Term (1+ Months)

#### 1. Model Fine-Tuning
- Fine-tune on technical documentation corpus
- Adapt to domain-specific terminology and style
- **Impact**: +10-15% quality on technical content

#### 2. Active Learning Loop
- Learn from human corrections
- Automatically update terminology and filters
- Continuous quality improvement

#### 3. Translation Memory System
- Reuse high-quality translations
- Semantic matching for similar content
- Consistency across documents

## Best Practices

### Configuration Tuning

**Conservative Settings** (catch more issues):
```yaml
validation:
  decision_rules:
    reject_on_error_count: 1
    max_retry_attempts: 3
    accept_after_max_retries: false

terminology:
  validation_mode: "strict"
```

**Permissive Settings** (fewer false positives):
```yaml
validation:
  decision_rules:
    reject_on_error_count: 5
    max_retry_attempts: 2
    accept_warnings: true

terminology:
  validation_mode: "lenient"
```

### Monitoring Quality

Track these metrics:
- **Validation Success Rate**: Translations passing validation
- **Terminology Accuracy**: Correct preservation of protected terms
- **Language Consistency**: Proper target language detection
- **Human Review Rate**: Translations requiring manual review

### Common Issues and Solutions

| Issue | Symptom | Solution |
|-------|---------|----------|
| **False terminology rejections** | Valid translations rejected | Adjust severity levels, review patterns |
| **Language detection failures** | Low confidence scores | Increase `min_text_length`, adjust thresholds |
| **Performance degradation** | Slow translation with verification | Disable for batch processing, use sampling |
| **Inconsistent terminology** | Same term translated differently | Add to global terminology, use `both` mode |

## Integration Examples

### Programmatic Quality Checking

```python
from src.translation_engine.engine import TranslationEngine

engine = TranslationEngine(config_service, tm, model_loader)

result = engine.translate_file(
    site_id="myblog",
    file_path=Path("content/post.md"),
    target_langs=["fr"]
)

# Check validation results
if result.validation_result:
    print(f"Validation: {result.validation_result.error_count} errors")

# Check verification results
if result.verification_result:
    print(f"Verification: {result.verification_result.error_count} errors")
```

### Custom Quality Gates

```python
def custom_quality_gate(result: TranslationResult) -> bool:
    """Custom quality gate logic."""

    # Must pass validation
    if result.validation_result and result.validation_result.error_count > 0:
        return False

    # Must pass verification if enabled
    if result.verification_result and not result.verification_result.passed:
        return False

    # Custom checks
    if len(result.errors) > 0:
        return False

    return True
```

## Troubleshooting

### Validation Issues

**High rejection rate**:
- Review validation mode settings
- Check for over-strict thresholds
- Validate terminology patterns

**False positives**:
- Adjust confidence thresholds
- Review skip patterns for technical content
- Tune minimum text lengths

### Terminology Issues

**Terms not protected**:
- Verify pattern syntax
- Check case sensitivity settings
- Review site-specific overrides

**Validation failures**:
- Check term frequency in source vs translation
- Review placeholder restoration
- Validate pattern matching

### Performance Issues

**Slow validation**:
- Disable verification for batch processing
- Use sampling for large document sets
- Optimize terminology pattern matching

## Related Documentation

- [Validation Guide](../guides/validation-guide.md) - Detailed validator documentation
- [Terminology Pattern Syntax](../reference/terminology-pattern-syntax.md) - Regex patterns for terminology protection
- [CLI Reference](../reference/cli.md) - Quality-related command flags
- [Configuration Reference](../reference/config.md) - Quality configuration options
