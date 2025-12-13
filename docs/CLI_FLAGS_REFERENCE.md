# CLI Flags Quick Reference

## Overview

The `translate-hugo` command-line tool provides comprehensive control over validation and terminology settings through CLI flags that override configuration file values.

## Quick Start

```bash
# Basic usage
translate-hugo --site <site-id>

# With validation control
translate-hugo --site <site-id> --validation-mode strict

# Disable validation
translate-hugo --site <site-id> --disable-validation

# Enable terminology
translate-hugo --site <site-id> --enable-terminology --terminology-mode both

# Dry run (preview only)
translate-hugo --site <site-id> --dry-run
```

## Required Arguments

| Flag | Description | Example |
|------|-------------|---------|
| `--site SITE` | Site identifier (required) | `--site products.aspose.net` |

## Validation Control Flags

| Flag | Type | Choices | Description |
|------|------|---------|-------------|
| `--validation-mode MODE` | Choice | strict, normal, lenient, off | Validation strictness level |
| `--disable-validation` | Boolean | - | Quick disable of all validation |
| `--validation-config PATH` | Path | - | Custom validation.yaml path |
| `--max-retries N` | Integer | 0-5 | Override max retry attempts |

### Validation Modes Explained

#### strict
- Rejects on first error
- Does not accept warnings
- Best for: Production releases, critical content

#### normal (default)
- Rejects after 3 errors
- Accepts warnings
- Best for: Regular translation workflow

#### lenient
- Rejects after 5 errors
- Accepts warnings
- Accepts after max retries
- Best for: Draft translations, iterative work

#### off
- Disables all validation
- Same as `--disable-validation`
- Best for: Testing, development

## Terminology Control Flags

| Flag | Type | Choices | Description |
|------|------|---------|-------------|
| `--enable-terminology` | Boolean | - | Enable terminology handling |
| `--disable-terminology` | Boolean | - | Disable terminology handling |
| `--terminology-mode MODE` | Choice | protect, validate, both, none | Preservation mode |
| `--terminology-config PATH` | Path | - | Custom terminology.yaml path |

### Terminology Modes Explained

#### protect
- Wrap terminology terms as placeholders during translation
- Prevents model from translating protected terms
- Best for: Brand names, product names, technical terms

#### validate
- Check translated output for terminology violations
- Flags issues where terms were incorrectly translated
- Best for: Quality assurance

#### both (recommended)
- Both protect and validate
- Most comprehensive approach
- Best for: Production use

#### none
- No terminology handling
- Best for: Testing, simple content

## Output Control Flags

| Flag | Type | Description |
|------|------|-------------|
| `--dry-run` | Boolean | Preview decisions without writing files |
| `--save-rejected` | Boolean | Save rejected translations for debugging |
| `--output DIR` | Path | Output directory (overrides site profile) |

## Input/Output Flags

| Flag | Type | Description |
|------|------|-------------|
| `--input PATH` | Path | Input file or directory (defaults to site content_roots) |
| `--target-langs LANG [LANG ...]` | List | Target languages (overrides site profile) |

## Logging Flags

| Flag | Type | Choices | Default | Description |
|------|------|---------|---------|-------------|
| `--log-level LEVEL` | Choice | DEBUG, INFO, WARNING, ERROR | INFO | Logging verbosity |
| `--log-file FILE` | Path | - | stdout | Write logs to file |

## Configuration Flags

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--config-root DIR` | Path | ./config | Configuration root directory |

## Usage Examples

### Example 1: Strict Validation for Production
```bash
translate-hugo \
  --site products.aspose.net \
  --validation-mode strict \
  --enable-terminology \
  --terminology-mode both \
  --log-level INFO
```

### Example 2: Development with Validation Disabled
```bash
translate-hugo \
  --site products.aspose.net \
  --disable-validation \
  --log-level DEBUG
```

### Example 3: Custom Configs with Lenient Validation
```bash
translate-hugo \
  --site products.aspose.net \
  --validation-mode lenient \
  --validation-config ./configs/custom-validation.yaml \
  --terminology-config ./configs/custom-terminology.yaml
```

### Example 4: Dry Run Preview
```bash
translate-hugo \
  --site products.aspose.net \
  --validation-mode strict \
  --dry-run
```

### Example 5: Specific Files with More Retries
```bash
translate-hugo \
  --site products.aspose.net \
  --input ./content/blog/important-post.md \
  --max-retries 5 \
  --save-rejected
```

### Example 6: Multiple Target Languages
```bash
translate-hugo \
  --site products.aspose.net \
  --target-langs de es fr ja \
  --validation-mode normal
```

## Override Priority

Configuration values are applied in this order (highest to lowest priority):

1. **CLI flags** ← Highest priority
2. Environment variables
3. Site profile configuration
4. Global configuration
5. Default values ← Lowest priority

## Common Flag Combinations

### Quality Assurance Mode
```bash
--validation-mode strict --enable-terminology --terminology-mode both --save-rejected
```

### Quick Testing Mode
```bash
--disable-validation --log-level DEBUG
```

### Production Release Mode
```bash
--validation-mode strict --enable-terminology --terminology-mode both --max-retries 3
```

### Preview Mode
```bash
--dry-run --log-level INFO
```

## Troubleshooting

### Issue: Too Many Rejections
**Solution**: Use lenient mode or increase max-retries
```bash
--validation-mode lenient --max-retries 5
```

### Issue: Need to Debug Validation
**Solution**: Enable debug logging and save rejected
```bash
--log-level DEBUG --save-rejected
```

### Issue: Testing Without Validation
**Solution**: Disable validation temporarily
```bash
--disable-validation
```

### Issue: Custom Terminology Rules
**Solution**: Use custom terminology config
```bash
--terminology-config ./my-terminology.yaml --terminology-mode both
```

## Best Practices

1. **Use strict mode for production**: `--validation-mode strict`
2. **Enable terminology for branded content**: `--enable-terminology --terminology-mode both`
3. **Preview before committing**: Use `--dry-run` first
4. **Save rejected for analysis**: `--save-rejected` when debugging
5. **Log to file for long runs**: `--log-file translation.log`
6. **Start lenient, then tighten**: Begin with lenient, move to strict as quality improves

## Integration with CI/CD

### GitHub Actions Example
```yaml
- name: Translate Content
  run: |
    translate-hugo \
      --site ${{ matrix.site }} \
      --validation-mode strict \
      --enable-terminology \
      --terminology-mode both \
      --log-file translation-${{ matrix.site }}.log
```

### GitLab CI Example
```yaml
translate:
  script:
    - translate-hugo
        --site ${SITE_ID}
        --validation-mode strict
        --log-level INFO
```

## See Also

- [Configuration Guide](./CONFIGURATION.md)
- [Validation Reference](./VALIDATION.md)
- [Terminology Guide](./TERMINOLOGY.md)
- [Taskcard CFG-03](../plans/healing/integration_and_configuration_taskcards.md)
