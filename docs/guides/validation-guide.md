# Validation Guide

This guide explains how the Hugo Translation System's validation engine works, including validators, decision logic, retry mechanisms, and CLI usage.

## Table of Contents

- [Overview](#overview)
- [How Validation Works](#how-validation-works)
- [Available Validators](#available-validators)
- [Decision Matrix](#decision-matrix)
- [Retry Logic](#retry-logic)
- [CLI Usage](#cli-usage)
- [Validation Modes](#validation-modes)
- [Examples](#examples)

## Overview

The validation engine ensures translation quality by running multiple validators on each translated document. Based on the validation results, the decision engine determines whether to:

- **ACCEPT**: Translation meets quality standards, write to disk
- **RETRY**: Translation has fixable issues, retry with feedback
- **REJECT**: Translation has critical errors, discard

This automated quality control prevents low-quality translations from polluting your Hugo site.

## How Validation Works

### Validation Pipeline

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

### Validation Phases

1. **Pre-translation validation**: Validates source document structure (YAML, placeholders)
2. **Post-translation validation**: Validates translation quality against source
3. **Decision-making**: Automated ACCEPT/RETRY/REJECT decision based on configurable rules

## Available Validators

The validation engine includes 10 validators organized into two categories:

### Legacy Validators (Pre-translation)

These validators run before translation to ensure source documents are valid:

#### 1. YAMLValidator

**Purpose**: Validates YAML frontmatter syntax

**Checks**:
- YAML frontmatter is valid syntax
- No duplicate keys
- Proper formatting

**Example issue**:
```
[ERROR] YAMLValidator: Invalid YAML syntax at frontmatter: mapping values are not allowed here
```

**Config**: `validators.yaml.enabled`

---

#### 2. PlaceholderValidator

**Purpose**: Validates placeholder integrity during translation

**Checks**:
- All placeholders in source appear in translation
- No corrupted placeholder syntax
- Placeholder IDs match

**Example issue**:
```
[ERROR] PlaceholderValidator: Missing placeholder {PLACEHOLDER_5} in translation
```

**Config**: `validators.placeholder.enabled`

**Decision impact**: Critical validator - errors trigger immediate REJECT

---

#### 3. StructureValidator

**Purpose**: Validates markdown structure preservation

**Checks**:
- Heading count matches source
- List structure preserved
- Code block count matches
- Blockquote count matches

**Example issue**:
```
[ERROR] StructureValidator: Heading count mismatch: source has 5, translation has 4
```

**Config**: `validators.structure.enabled`

**Decision impact**: Errors are retryable

---

#### 4. LinkValidator

**Purpose**: Validates link integrity

**Checks**:
- All source links present in translation
- Link URLs not corrupted
- Relative links preserved

**Example issue**:
```
[ERROR] LinkValidator: Link missing in translation: [Documentation](./docs/README.md)
```

**Config**: `validators.link.enabled`

**Decision impact**: Critical validator - errors trigger immediate REJECT

---

### Post-Translation Validators (VAL-01 through VAL-06)

These validators run after translation to ensure quality:

#### 5. CompletenessValidator (VAL-01)

**Purpose**: Validates 100% segment coverage

**Checks**:
- All source segments have translations
- No empty translations
- No untranslated placeholders

**Example issue**:
```
[ERROR] CompletenessValidator: Segment 12 not translated
```

**Config**: `validators.completeness.enabled`

**Retry feedback**: "COMPLETENESS: Ensure ALL source segments are translated. No segments should be skipped."

---

#### 6. LanguageConsistencyValidator (VAL-02)

**Purpose**: Validates target language consistency using langdetect

**Checks**:
- Detected language matches target language (e.g., 'de' for German)
- Confidence >= threshold (default 0.85)
- Code blocks/URLs/shortcodes ignored

**Example issue**:
```
[ERROR] LanguageConsistencyValidator: Wrong language detected: en (expected de)
```

**Config**:
- `validators.language_consistency.enabled`
- `validators.language_consistency.confidence_threshold` (default: 0.85)

**Context required**: `target_lang` must be provided in validation context

---

#### 7. ShortcodePreservationValidator (VAL-03)

**Purpose**: Validates Hugo shortcode preservation

**Checks**:
- All source shortcodes present in translation
- Shortcode count matches
- No corrupted shortcode syntax
- Supported forms: `{{< ... >}}`, `{{% ... %}}`, `{{/* ... */}}`

**Example issue**:
```
[ERROR] ShortcodePreservationValidator: Shortcode missing in translation: {{< youtube dQw4w9WgXcQ >}}
```

**Config**: `validators.shortcode_preservation.enabled`

**Retry feedback**: "SHORTCODES: Hugo shortcodes ({{< ... >}}) must be preserved EXACTLY. Do not translate shortcode names or parameters."

---

#### 8. FrontmatterProtectionValidator (VAL-04)

**Purpose**: Validates frontmatter field protection rules

**Checks**:
- Fields marked as "keep" are unchanged
- Fields marked as "translate" are translated
- Required fields present

**Example issue**:
```
[ERROR] FrontmatterProtectionValidator: Field 'date' should be kept but was modified
```

**Config**: `validators.frontmatter_protection.enabled`

**Dependencies**: Requires site profile for frontmatter rules

---

#### 9. TerminologyPreservationValidator (VAL-05)

**Purpose**: Validates terminology preservation (Aspose, .NET, product names, etc.)

**Checks**:
- Exact match preservation (Aspose, .NET, Java, Python)
- Pattern-based matching (Aspose.Words, Aspose.Cells, etc.)
- Frequency validation (term count in source vs translation)
- Case sensitivity support

**Example issue**:
```
[ERROR] TerminologyPreservationValidator: Term 'Aspose' (company_name) appears 3 time(s) in source but is missing from translation
```

**Config**:
- `validators.terminology_preservation.enabled`
- `validators.terminology_preservation.validation_mode` (strict/normal/lenient)

**Retry feedback**: "TERMINOLOGY: Preserve company names (Aspose), product names (Aspose.Words), and platform names (.NET) EXACTLY as they appear in source."

---

#### 10. FilePlacementValidator (VAL-06)

**Purpose**: Validates file placement and directory structure

**Checks**:
- Output path matches expected structure
- Language folder correct (e.g., `/de/`, `/fr/`)
- File extension preserved
- Relative paths maintained

**Example issue**:
```
[ERROR] FilePlacementValidator: File should be in /de/docs/ but is in /docs/de/
```

**Config**: `validators.file_placement.enabled`

**Dependencies**: Requires config service for output layout rules

---

## Decision Matrix

The decision engine uses the following rules to make ACCEPT/RETRY/REJECT decisions:

### Decision Rules (Priority Order)

| Priority | Condition | Decision | Reason |
|----------|-----------|----------|--------|
| 1 | Critical validator failed | **REJECT** | PlaceholderValidator, CodeBlockValidator, or LinkValidator error |
| 2 | Error count >= threshold | **REJECT** | Too many errors (default: 3) |
| 3 | No errors, warnings OK | **ACCEPT** | Translation is acceptable |
| 4 | Errors + retries available | **RETRY** | Issues are fixable, retry with feedback |
| 5 | Exhausted retries + accept_after_max_retries=true | **ACCEPT** | Best effort after retries |
| 6 | Exhausted retries + accept_after_max_retries=false | **REJECT** | Failed after all retries |

### Critical Validators

These validators always trigger **REJECT** on error (no retry):

- **PlaceholderValidator**: Placeholder integrity is critical
- **LinkValidator**: Broken links are unacceptable
- Code block errors (via `reject_on_code_block_error`)

### Configurable Thresholds

Configure decision rules in `config/validation.yaml`:

```yaml
decision_rules:
  # Rejection thresholds
  reject_on_error_count: 3          # Reject if this many errors
  reject_on_placeholder_error: true # Reject on placeholder errors
  reject_on_code_block_error: true  # Reject on code block errors
  reject_on_link_error: true        # Reject on link errors

  # Retry configuration
  max_retry_attempts: 2             # Maximum retry attempts
  retry_on_structure_error: true    # Retry on structure errors
  retry_on_terminology_warning: true # Retry on terminology warnings

  # Acceptance thresholds
  accept_warnings: true             # Accept with warnings
  accept_after_max_retries: true    # Accept after max retries
```

## Retry Logic

### How Retries Work

When the decision engine returns **RETRY**, the system:

1. Generates feedback based on validation issues
2. Increments retry counter
3. Optionally increases LLM temperature (controlled by `retry_strategy.vary_temperature`)
4. Re-translates with feedback in prompt
5. Validates again

### Retry Budget

- Default: 2 retry attempts (configurable via `max_retry_attempts`)
- Total translation attempts: 1 initial + 2 retries = 3 attempts max
- After exhausting retries: ACCEPT (if `accept_after_max_retries=true`) or REJECT

### Feedback Escalation

Feedback becomes more explicit with each retry:

**Attempt 1 (First retry)**: Brief summary
```
VALIDATION FEEDBACK - Please address the following issues:

ERRORS (must fix):
1. Shortcode missing in translation: {{< youtube dQw4w9WgXcQ >}}
2. Term 'Aspose.Words' (product_family) appears 2 time(s) in source but is missing from translation
```

**Attempt 2 (Second retry)**: Detailed with locations
```
CRITICAL VALIDATION FEEDBACK - Previous translation had issues. Pay close attention:

ERRORS (must fix):
1. [ShortcodePreservationValidator] Shortcode missing in translation: {{< youtube dQw4w9WgXcQ >}}
   Location: shortcodes
   Fix: Preserve all Hugo shortcodes exactly
2. [TerminologyPreservationValidator] Term 'Aspose.Words' (product_family) appears 2 time(s) in source but is missing from translation
   Location: terminology.product_family
   Fix: Preserve product names exactly as they appear in source
```

**Attempt 3 (Final retry)**: Explicit with critical warnings
```
FINAL ATTEMPT - This is the last retry. You MUST fix these issues:

ERRORS (must fix):
1. [ShortcodePreservationValidator] Shortcode missing in translation: {{< youtube dQw4w9WgXcQ >}}
   Location: shortcodes
   REQUIRED ACTION: Preserve all Hugo shortcodes exactly
   This is CRITICAL - translation will be REJECTED if not fixed.
```

### Temperature Variation

Configure temperature changes per retry:

```yaml
retry_strategy:
  vary_temperature: true        # Enable temperature variation
  temperature_increment: 0.1    # Increase by 0.1 per retry
  max_temperature: 1.0          # Maximum temperature
```

Example progression:
- Initial: temperature = 0.7
- Retry 1: temperature = 0.8
- Retry 2: temperature = 0.9

## CLI Usage

### Validation Mode Control

Control validation strictness via CLI:

```bash
# Use strict validation mode
translate-hugo --site products.aspose.net --validation-mode strict

# Use normal validation mode (default)
translate-hugo --site products.aspose.net --validation-mode normal

# Use lenient validation mode
translate-hugo --site products.aspose.net --validation-mode lenient

# Disable validation completely
translate-hugo --site products.aspose.net --disable-validation
# OR
translate-hugo --site products.aspose.net --validation-mode off
```

### Force Accept/Reject

Override decision engine for testing:

```bash
# Accept all translations without validation
translate-hugo --site products.aspose.net --force-accept

# Reject on any validation issue (fail fast, no retries)
translate-hugo --site products.aspose.net --strict-reject
```

### Custom Validation Config

Use custom validation configuration:

```bash
# Use custom validation.yaml
translate-hugo --site products.aspose.net --validation-config ./custom-validation.yaml
```

### Terminology Control

Enable/disable terminology validation:

```bash
# Enable terminology preservation
translate-hugo --site products.aspose.net --enable-terminology

# Disable terminology preservation
translate-hugo --site products.aspose.net --disable-terminology
```

### Preview Mode

Preview validation decisions without writing files:

```bash
# Preview what would happen without writing
translate-hugo --site products.aspose.net --dry-run --validation-mode strict
```

## Validation Modes

The Hugo Translation System provides three pre-configured validation modes that balance quality control with translation throughput. Choose the appropriate mode based on your content type, audience, and quality requirements.

### Decision Guide: When to Use Each Mode

Use this decision tree to select the right validation mode:

#### 1. Content Criticality Assessment
- **High criticality** (API docs, legal content, product specs) → **Strict Mode**
- **Medium criticality** (blogs, marketing, general docs) → **Normal Mode**
- **Low criticality** (drafts, internal docs, testing) → **Lenient Mode**

#### 2. Translation Volume Considerations
- **High volume** (1000+ pages) → **Lenient Mode** (fewer rejections)
- **Medium volume** (100-1000 pages) → **Normal Mode** (balanced)
- **Low volume** (<100 pages) → **Strict Mode** (maximum quality)

#### 3. Time vs Quality Trade-off
- **Quality over speed** → **Strict Mode**
- **Balanced approach** → **Normal Mode**
- **Speed over quality** → **Lenient Mode**

#### 4. Target Audience
- **Technical users/developers** → **Strict Mode** (expect perfection)
- **General business users** → **Normal Mode** (tolerate minor issues)
- **Internal stakeholders** → **Lenient Mode** (focus on getting content)

### Mode Comparison

| Aspect | Strict Mode | Normal Mode | Lenient Mode |
|--------|-------------|-------------|--------------|
| **Error Tolerance** | 0 errors | Up to 3 errors | Up to 5 errors |
| **Warning Handling** | Reject all | Accept with warnings | Accept with warnings |
| **Retry Attempts** | 1 retry | 2 retries | 2 retries |
| **Translation Speed** | Slowest | Medium | Fastest |
| **Quality Assurance** | Highest | Balanced | Lowest |
| **Failure Rate** | Highest | Medium | Lowest |

### Detailed Mode Configurations

#### Strict Mode

**Configuration**:
```yaml
strict:
  accept_warnings: false          # Do not accept warnings
  reject_on_error_count: 1        # Reject on first error
  max_retry_attempts: 1           # Only one retry
```

**Behavior**:
- Rejects translations with any validation errors
- Does not accept translations with warnings
- Limited retry attempts (1 additional try)
- Best for: Production deployments, API documentation, legal content

**Decision Logic**:
- ✅ ACCEPT: No errors, no warnings
- 🔄 RETRY: Errors present, retries available (1 attempt)
- ❌ REJECT: Any errors after retry OR warnings present

#### Normal Mode (Default)

**Configuration**:
```yaml
normal:
  accept_warnings: true           # Accept warnings
  reject_on_error_count: 3        # Reject after 3 errors
  max_retry_attempts: 2           # Two retries
```

**Behavior**:
- Accepts translations with warnings (non-critical issues)
- Allows up to 3 validation errors before rejection
- Two retry attempts for error correction
- Best for: General content, blogs, marketing materials

**Decision Logic**:
- ✅ ACCEPT: No errors OR warnings only (if accept_warnings=true)
- 🔄 RETRY: 1-3 errors, retries available
- ❌ REJECT: 4+ errors OR critical validator failures

#### Lenient Mode

**Configuration**:
```yaml
lenient:
  accept_warnings: true           # Accept warnings
  reject_on_error_count: 5        # Reject after 5 errors
  max_retry_attempts: 2           # Two retries
```

**Behavior**:
- Highly tolerant of validation issues
- Accepts translations with up to 5 errors
- Maximum retry attempts for difficult content
- Best for: Drafts, internal documentation, bulk translation

**Decision Logic**:
- ✅ ACCEPT: ≤5 errors OR warnings only
- 🔄 RETRY: Errors present, retries available
- ❌ REJECT: 6+ errors OR critical validator failures

### Use Case Examples

#### Example 1: API Documentation (Strict Mode)

**Scenario**: Translating technical API reference documentation for developers.

**Why Strict Mode**:
- Developers expect perfect accuracy
- Broken links or incorrect terminology can break code
- Zero tolerance for placeholder corruption

**Expected Outcomes**:
```bash
# Translation with 1 terminology error
[STRICT] Decision: RETRY (1 retry available)
# After retry fixes the issue
[STRICT] Decision: ACCEPT

# Translation with warning only
[STRICT] Decision: REJECT (warnings not accepted)
```

#### Example 2: Marketing Blog Posts (Normal Mode)

**Scenario**: Translating company blog posts for international marketing campaigns.

**Why Normal Mode**:
- Content is informational, not critical
- Minor terminology variations acceptable
- Balance between quality and translation speed needed

**Expected Outcomes**:
```bash
# Translation with 2 structure warnings
[NORMAL] Decision: ACCEPT (warnings accepted)

# Translation with 1 error, 2 warnings
[NORMAL] Decision: RETRY (within error threshold)

# Translation with 4 errors
[NORMAL] Decision: REJECT (exceeds error threshold)
```

#### Example 3: Internal Knowledge Base (Lenient Mode)

**Scenario**: Bulk translation of internal documentation for global teams.

**Why Lenient Mode**:
- Speed more important than perfection
- Internal users can handle minor issues
- High volume requires tolerant validation

**Expected Outcomes**:
```bash
# Translation with 3 errors, multiple warnings
[LENIENT] Decision: ACCEPT (within thresholds)

# Translation with 6 errors
[LENIENT] Decision: REJECT (exceeds 5 error limit)

# Translation with critical placeholder error
[LENIENT] Decision: REJECT (critical validator failure)
```

#### Example 4: Product Release Notes (Strict Mode)

**Scenario**: Translating release notes for software products.

**Why Strict Mode**:
- Release content must be accurate
- Version numbers and technical terms critical
- Customer-facing content requires perfection

**Expected Outcomes**:
```bash
# Perfect translation
[STRICT] Decision: ACCEPT

# Translation missing one shortcode
[STRICT] Decision: RETRY
# Retry successful
[STRICT] Decision: ACCEPT

# Translation with terminology warning
[STRICT] Decision: REJECT (warnings not accepted)
```

#### Example 5: Quick Draft Translation (Lenient Mode)

**Scenario**: Rapid translation of draft content for review purposes.

**Why Lenient Mode**:
- Draft quality, not final publication
- Speed prioritized over accuracy
- Reviewers can identify and fix issues

**Expected Outcomes**:
```bash
# Translation with multiple issues
[LENIENT] Decision: ACCEPT (tolerant of errors)

# Only critical failures rejected
[LENIENT] Decision: REJECT (placeholder corruption)
```

### Mode Selection CLI Examples

```bash
# Production API docs - strict quality control
translate-hugo --site reference.aspose.net --validation-mode strict

# Marketing content - balanced approach
translate-hugo --site blog.aspose.net --validation-mode normal

# Internal docs - prioritize speed
translate-hugo --site kb.aspose.net --validation-mode lenient

# Override for testing
translate-hugo --site docs.aspose.net --validation-mode lenient --dry-run
```

## Examples

### Example 1: Successful Translation (ACCEPT)

**Scenario**: Translation has no errors

```
Translation Attempt 1:
  Validators: ✓ Completeness, ✓ LanguageConsistency, ✓ ShortcodePreservation, ...
  Issues: None
  Decision: ACCEPT
  Result: Write to disk
```

### Example 2: Retry and Accept

**Scenario**: Translation has terminology warning, retry and succeed

```
Translation Attempt 1:
  Validators: ✓ Completeness, ✓ LanguageConsistency, ⚠ TerminologyPreservation
  Issues: 1 warning (terminology frequency mismatch)
  Decision: RETRY (retry_on_terminology_warning=true)
  Feedback: "TERMINOLOGY: Preserve product names exactly..."

Translation Attempt 2:
  Validators: ✓ Completeness, ✓ LanguageConsistency, ✓ TerminologyPreservation
  Issues: None
  Decision: ACCEPT
  Result: Write to disk
```

### Example 3: Critical Failure (REJECT)

**Scenario**: Translation has placeholder error (critical)

```
Translation Attempt 1:
  Validators: ✓ Completeness, ✗ PlaceholderValidator, ✓ ShortcodePreservation
  Issues: 1 error (missing placeholder {PLACEHOLDER_3})
  Decision: REJECT (critical validator failed)
  Result: Discard, log error
```

### Example 4: Exhausted Retries (ACCEPT)

**Scenario**: Translation has errors but exhausted retries, accept best effort

```
Translation Attempt 1:
  Validators: ✓ Completeness, ✗ StructureValidator (2 errors)
  Decision: RETRY

Translation Attempt 2:
  Validators: ✓ Completeness, ✗ StructureValidator (1 error)
  Decision: RETRY

Translation Attempt 3:
  Validators: ✓ Completeness, ✗ StructureValidator (1 error)
  Decision: ACCEPT (best effort after 2 retries, accept_after_max_retries=true)
  Result: Write to disk with warnings
```

### Example 5: Custom Validation Config

**Scenario**: Use custom thresholds for high-quality translation

**File**: `custom-validation.yaml`
```yaml
version: "1.0"

decision_rules:
  reject_on_error_count: 1        # Reject on first error
  max_retry_attempts: 3           # Three retries
  accept_after_max_retries: false # Reject if not perfect after retries

validators:
  completeness:
    enabled: true
  language_consistency:
    enabled: true
    confidence_threshold: 0.95    # Higher confidence required
  terminology_preservation:
    enabled: true
    validation_mode: "strict"
```

**Command**:
```bash
translate-hugo --site reference.aspose.net --validation-config ./custom-validation.yaml
```

## Related Documentation

- [Terminology Pattern Syntax](../reference/terminology-pattern-syntax.md) - Regex patterns for terminology protection
- [Configuration Reference](./configuration_reference.md) - Complete config file reference
- [Troubleshooting](./troubleshooting.md) - Common validation errors and fixes
