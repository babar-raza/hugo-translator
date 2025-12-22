# Post-Translation Verification (VA-03)

**Status**: Experimental feature - requires `langdetect` dependency

## Overview

Post-translation verification detects quality issues that occur after the main translation process but before files are written to disk. Unlike validation (which checks structure and terminology), verification focuses on content quality issues like:

- **Mixed-language content**: When translation contains text in the wrong language
- **Untranslated segments**: When parts of the content remain in the source language
- **Language consistency**: Ensuring the entire document is in the target language

## How It Works

### Verification Pipeline

```
Translation Complete
        ↓
Verification Agent (VA-03)
        ↓
Language Detection Check
        ↓
[Issues Found] → Retry with feedback
[Clean] → Write files
```

### Key Differences from Validation

| Aspect | Validation | Verification |
|--------|------------|---------------|
| **Timing** | Pre-write | Post-translation |
| **Focus** | Structure/terminology | Content language |
| **Method** | Rule-based checks | ML language detection |
| **Dependencies** | None | `langdetect` library |
| **False Positives** | Low | Medium (configurable) |

## Setup

### Install Dependencies

```bash
pip install langdetect
# or
pip install -e ".[quality]"
```

### Enable Verification

**CLI Flags**:
```bash
# Enable verification
translate-hugo --verify

# Enable verification with automatic retry on failure
translate-hugo --verify --fix
```

**Configuration** (future):
```yaml
# config/global.yaml
validation_defaults:
  post_write:
    verification:
      enabled: true
      auto_fix: true
```

## What Gets Checked

### Language Detection

The system uses `langdetect` to analyze text and determine its language. It checks:

- **Frontmatter fields**: Title, description, tags, categories
- **Body content**: Main article text
- **Minimum length**: Only checks text ≥20 characters (configurable)
- **Confidence threshold**: Requires ≥85% confidence (configurable)

### Content Filtering

To avoid false positives, verification skips:

- **Technical content**: Code blocks, URLs, file paths
- **Hugo syntax**: Shortcodes `{{< ... >}}`, templates `{{ ... }}`
- **API references**: Terms like "API", "HTTP", "JSON"
- **Short strings**: Text under minimum length threshold

### Example Detection

**Source (English)**:
```yaml
---
title: "Getting Started with Hugo"
---

This guide shows how to install Hugo.
```

**Bad Translation (Mixed)**:
```yaml
---
title: "Getting Started with Hugo"  # ← Still English!
---

Ce guide montre comment installer Hugo.
```

**Detection Result**:
```
ERROR: Expected fr, detected en (confidence: 0.92)
Location: frontmatter.title
```

## Configuration Options

### LanguageDetectionCheck Parameters

```python
from src.verification.checks import LanguageDetectionCheck

check = LanguageDetectionCheck(
    min_text_length=20,      # Minimum characters to check
    confidence_threshold=0.85,  # Minimum confidence (0.0-1.0)
    check_frontmatter=True,  # Check frontmatter fields
    check_body=True          # Check body content
)
```

### CLI Overrides

```bash
# Adjust confidence threshold
translate-hugo --verify --verification-confidence 0.9

# Change minimum text length
translate-hugo --verify --verification-min-length 30
```

## Handling Verification Failures

### Automatic Retry (--fix)

When `--fix` is enabled, verification failures trigger retry with feedback:

```bash
translate-hugo --site myblog --verify --fix
```

**Retry Process**:
1. Translation completes
2. Verification detects issues
3. Model receives feedback: *"Previous translation had language detection errors"*
4. Translation retries with improved prompts
5. Process repeats up to max retries

### Manual Review

Without `--fix`, verification failures are logged but don't block:

```bash
translate-hugo --site myblog --verify
# Translation succeeds, but warnings logged
```

**Log Output**:
```
WARNING: Verification failed for content/post.md to fr:
- Expected fr, detected en (confidence: 0.91) at frontmatter.title
- Expected fr, detected en (confidence: 0.88) at body
```

## Common Issues and Solutions

### False Positives

**Issue**: Technical terms flagged as wrong language
```
ERROR: Expected de, detected en at frontmatter.tags[0]: "API"
```

**Solutions**:
- Increase `min_text_length` to skip short technical terms
- Add technical patterns to skip list
- Lower `confidence_threshold` if too strict

**Issue**: Proper nouns detected as source language
```
ERROR: Expected es, detected en at frontmatter.title: "John Smith"
```

**Solutions**:
- Use terminology protection for names
- Adjust confidence threshold
- Skip frontmatter fields with `--verification-skip-frontmatter`

### Detection Failures

**Issue**: `langdetect` import error

**Solution**:
```bash
pip install langdetect
```

**Issue**: Low confidence scores

**Cause**: Short text, mixed content, or ambiguous language

**Solutions**:
- Increase `min_text_length`
- Use higher `confidence_threshold`
- Review content for clarity

### Performance Impact

**Issue**: Verification slows down translation

**Impact**: ~10-20% slower due to language detection

**Solutions**:
- Run verification only on final translations
- Use batch processing to amortize overhead
- Disable for development/testing: `--no-verify`

## Integration with Validation

### Pipeline Order

1. **Translation**: Generate candidate translation
2. **Validation**: Check structure, terminology, completeness
3. **Verification**: Check language consistency
4. **Decision**: ACCEPT/RETRY/REJECT based on all results

### Combined Results

```python
result = engine.translate_file(site_id, file_path, target_langs)

# Check all result types
if result.validation_result:
    print(f"Validation: {result.validation_result.error_count} errors")

if result.verification_result:
    print(f"Verification: {result.verification_result.error_count} errors")
```

## Best Practices

### When to Use

**✅ Recommended for**:
- Production translations
- Multi-language sites
- Content with mixed technical/user text
- High-quality requirements

**❌ Skip for**:
- Development/testing (use `--no-verify`)
- Single-language content
- Technical documentation only
- Performance-critical batch processing

### Configuration Tuning

**Conservative Settings** (catch more issues):
```python
LanguageDetectionCheck(
    min_text_length=10,
    confidence_threshold=0.9,
    check_frontmatter=True,
    check_body=True
)
```

**Permissive Settings** (fewer false positives):
```python
LanguageDetectionCheck(
    min_text_length=50,
    confidence_threshold=0.7,
    check_frontmatter=False,  # Skip titles with proper nouns
    check_body=True
)
```

### Monitoring

**Track Verification Metrics**:
- Success rate: Translations passing verification
- Common failure patterns
- False positive rate
- Performance impact

**Grafana Dashboard**:
- Verification error rate over time
- Most common failure locations
- Language detection confidence distribution

## Troubleshooting

### Debug Mode

Enable detailed logging:
```bash
translate-hugo --verify --log-level DEBUG
```

**Log Output**:
```
DEBUG: Running verification check: language_detection
DEBUG: Checking frontmatter.title: "Getting Started" -> detected: en, confidence: 0.95
DEBUG: Language mismatch: expected fr, got en
```

### Manual Testing

Test verification independently:
```python
from src.verification import VerificationAgent
from src.verification.checks import LanguageDetectionCheck

agent = VerificationAgent([LanguageDetectionCheck()])
result = agent.verify(source_doc, translated_doc, "fr")

for issue in result.issues:
    print(f"{issue.severity}: {issue.location} - {issue.message}")
```

### Common Error Messages

| Error | Cause | Solution |
|-------|-------|----------|
| `langdetect not installed` | Missing dependency | `pip install langdetect` |
| `Low confidence detection` | Ambiguous text | Increase `min_text_length` |
| `False positive on technical terms` | Code/URLs flagged | Adjust skip patterns |
| `Performance degradation` | Language detection overhead | Disable for batch processing |

## Future Enhancements

- **Additional checks**: Grammar, fluency, cultural adaptation
- **Model-based verification**: Use LLM to detect translation quality
- **Batch optimization**: Process multiple files together
- **Custom checks**: Pluggable verification framework
- **Training data**: Improve detection for domain-specific content

## Related Documentation

- [Validation Guide](validation-guide.md) - Pre-write validation
- [Terminology Pattern Syntax](../reference/terminology-pattern-syntax.md) - Regex patterns for terminology protection
- [CLI Reference](../reference/cli.md) - Verification flags
- [API Reference](../reference/api.md) - VerificationAgent class
