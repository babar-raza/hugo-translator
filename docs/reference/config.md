# Configuration Reference

Source of truth: `src/utils/config_loader.py`, `src/utils/models.py`, `config/*.yaml`

Complete reference for all configuration files in the Hugo Translation System.

## Table of Contents

- [Overview](#overview)
- [validation.yaml](#validationyaml)
- [terminology.yaml](#terminologyyaml)
- [Site Profile Validation](#site-profile-validation)
- [Examples and Defaults](#examples-and-defaults)

## Overview

The Hugo Translation System uses layered configuration:

1. **global.yaml**: System-wide defaults and paths
2. **validation.yaml**: Validation behavior and decision rules
3. **terminology.yaml**: Protected terminology patterns
4. **model_registry.yaml**: Available translation models
5. **site_profiles/*.yaml**: Site-specific overrides

**Configuration Priority** (highest to lowest):
1. CLI flags
2. Site profile settings
3. Global configuration
4. System defaults

**Locations**:
- `config/global.yaml` - System defaults
- `config/validation.yaml` - Validation rules
- `config/terminology.yaml` - Terminology protection
- `config/model_registry.yaml` - Model catalog
- `config/site_profiles/*.yaml` - Per-site settings

## global.yaml

System-wide defaults and configuration.

**Location**: `config/global.yaml`

### Complete Schema

```yaml
# System identification
system:
  name: "Hugo Translation System"
  version: "1.0.0"
  environment: "production"

# Translation Memory defaults
tm_defaults:
  use_semantic_tm: true
  semantic_threshold: 0.80
  fallback_exact_only: false
  l1_cache_size: 10000
  l2_max_size_mb: 1024
  l3_embedding_model: "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
  l3_index_type: "IVFFlat"

# Model defaults
model_defaults:
  fallback_model: "m2m100_418m"
  device: "auto"
  batch_size: 32
  cache_models: true
  max_cached_models: 2

# Hardware configuration
hardware:
  enable_gpu: true
  max_gpu_memory_mb: 6144
  gpu_device_id: -1
  allow_cpu_fallback: true
  clear_cache_after_batch: true

# Orchestrator settings
orchestrator:
  mode: "auto"
  max_workers: 4
  job_queue_backend: "memory"
  sweep_interval_hours: 24
  file_watcher_debounce_seconds: 2.0
  enable_file_watcher: true
  enable_sweep_scheduler: true

# Performance tuning
performance:
  parallel_translation: true
  max_parallel_files: 8
  model_cache_size: 2
  enable_batch_optimization: true

# Observability
observability:
  log_level: "INFO"
  log_format: "json"
  flow_artifact_detail: "summary"
  flow_artifact_sample_rate: 0.05
  metrics_enabled: true
  metrics_port: 9090
  metrics_pushgateway: ""

# Telemetry
telemetry:
  validation_metrics: true

# Output layout defaults
default_output_layout:
  per_language_folders: true
  pattern: "{lang}/{path}"

# File system paths
paths:
  config_dir: "./config"
  content_root: "./content"
  output_dir: "./output"
  model_cache_dir: "./data/models"
  tm_data_dir: "./data/tm"
  l3_index_dir: "l3_faiss"
  artifacts_dir: "./data/artifacts"
  logs_dir: "./data/logs"
  backup_dir: "./backups"

# Validation top-level settings
validation:
  enabled: true
  config_file: "config/validation.yaml"
  mode: "normal"
  rules:
    - placeholder_integrity
    - yaml_validity
    - structure_preservation
    - link_validity

# Terminology top-level settings
terminology:
  enabled: true
  config_file: "config/terminology.yaml"
  preserve_mode: "BOTH"

# Security settings
security:
  enable_input_validation: true
  max_file_size_mb: 10
  allowed_extensions:
    - ".md"
    - ".markdown"
  sanitize_output: true

# Feature flags
features:
  enable_parallel_processing: true
  enable_semantic_tm: true
  enable_model_benchmarking: false
  enable_auto_model_selection: true
  enable_quality_scoring: false

# L4 LLM adaptation (experimental)
l4_llm:
  enabled: false
  provider: "ollama"
  model: "llama2"
  api_key: null
  base_url: "http://localhost:11434"
  min_similarity: 0.75
  max_similarity: 0.95
  timeout_seconds: 30
  max_latency_ms: 500
  cache_adaptations: true

# Validation defaults
validation_defaults:
  mode: "normal"
  decision_rules:
    reject_on_error_count: 3
    max_retry_attempts: 2
    accept_warnings: true
  post_write:
    enabled: true
    delete_on_failure: false
    halt_on_failure: false
  validators:
    completeness:
      enabled: true
    language_consistency:
      enabled: true
      confidence_threshold: 0.85
```

### Key Sections

#### TM Defaults
Translation Memory configuration applied to all sites unless overridden.

#### Model Defaults
Default model and hardware settings.

#### Hardware
GPU memory limits and device selection.

#### Orchestrator
Background job processing and file watching.

#### Performance
Parallel processing and batch optimization.

#### Observability
Logging, metrics, and telemetry settings.

#### Feature Flags
Runtime feature toggles for experimental or optional functionality.

| Flag | Default | Description |
|------|---------|-------------|
| enable_parallel_processing | `true` | Enable parallel file translation processing |
| enable_semantic_tm | `true` | Enable L3 semantic translation memory matching |
| enable_model_benchmarking | `false` | Enable model performance benchmarking features (CLI, DB storage) |
| enable_auto_model_selection | `true` | Automatically select best model based on content |
| enable_quality_scoring | `false` | Enable translation quality scoring (experimental) |

**Important**: `enable_model_benchmarking` defaults to `false` for production safety. Enable explicitly to access benchmarking commands (`python -m src.benchmarking.cli`).

#### Paths
File system locations for data and artifacts.

## validation.yaml

Main configuration file for the validation engine.

**Location**: `config/validation.yaml`

### Schema

```yaml
version: "1.0"

decision_rules:
  # Rejection thresholds
  reject_on_error_count: <integer>
  reject_on_placeholder_error: <boolean>
  reject_on_code_block_error: <boolean>
  reject_on_link_error: <boolean>

  # Retry configuration
  max_retry_attempts: <integer>
  retry_on_structure_error: <boolean>
  retry_on_terminology_warning: <boolean>

  # Acceptance thresholds
  accept_warnings: <boolean>
  accept_after_max_retries: <boolean>

retry_strategy:
  feedback_mode: <string: "brief" | "detailed" | "examples">
  vary_temperature: <boolean>
  temperature_increment: <float>
  max_temperature: <float>

validation_modes:
  strict:
    accept_warnings: <boolean>
    reject_on_error_count: <integer>
    max_retry_attempts: <integer>

  normal:
    accept_warnings: <boolean>
    reject_on_error_count: <integer>
    max_retry_attempts: <integer>

  lenient:
    accept_warnings: <boolean>
    reject_on_error_count: <integer>
    max_retry_attempts: <integer>

validators:
  yaml:
    enabled: <boolean>
    description: <string>

  placeholder:
    enabled: <boolean>
    description: <string>

  structure:
    enabled: <boolean>
    description: <string>

  link:
    enabled: <boolean>
    description: <string>

  completeness:
    enabled: <boolean>
    description: <string>

  language_consistency:
    enabled: <boolean>
    confidence_threshold: <float>
    description: <string>

  shortcode_preservation:
    enabled: <boolean>
    description: <string>

  frontmatter_protection:
    enabled: <boolean>
    description: <string>

  terminology_preservation:
    enabled: <boolean>
    validation_mode: <string: "strict" | "normal" | "lenient">
    description: <string>

  file_placement:
    enabled: <boolean>
    description: <string>
```

### Field Reference

#### version

**Type**: String
**Required**: Yes
**Default**: "1.0"
**Description**: Configuration file version for compatibility checking
**Example**: `version: "1.0"`

---

#### decision_rules

Container for decision engine configuration.

##### reject_on_error_count

**Type**: Integer
**Required**: No
**Default**: 3
**Range**: 1-10 (recommended)
**Description**: Reject translation if this many validation errors are detected
**Example**: `reject_on_error_count: 3`

**Tuning**:
- `1`: Strict, reject on first error
- `3`: Balanced (default)
- `5+`: Lenient, tolerate multiple errors

##### reject_on_placeholder_error

**Type**: Boolean
**Required**: No
**Default**: true
**Description**: Reject immediately if placeholder integrity fails (critical)
**Example**: `reject_on_placeholder_error: true`

**Note**: Recommended to keep `true` - placeholder corruption is unrecoverable

##### reject_on_code_block_error

**Type**: Boolean
**Required**: No
**Default**: true
**Description**: Reject immediately if code blocks are corrupted
**Example**: `reject_on_code_block_error: true`

##### reject_on_link_error

**Type**: Boolean
**Required**: No
**Default**: true
**Description**: Reject immediately if links are broken or corrupted
**Example**: `reject_on_link_error: true`

##### max_retry_attempts

**Type**: Integer
**Required**: No
**Default**: 2
**Range**: 0-5 (recommended)
**Description**: Maximum number of retry attempts before accepting or rejecting
**Example**: `max_retry_attempts: 2`

**Total attempts**: 1 initial + N retries (e.g., max_retry_attempts=2 means 3 total attempts)

##### retry_on_structure_error

**Type**: Boolean
**Required**: No
**Default**: true
**Description**: Retry translation if markdown structure errors are detected
**Example**: `retry_on_structure_error: true`

##### retry_on_terminology_warning

**Type**: Boolean
**Required**: No
**Default**: true
**Description**: Retry translation if terminology warnings are detected
**Example**: `retry_on_terminology_warning: true`

##### accept_warnings

**Type**: Boolean
**Required**: No
**Default**: true
**Description**: Accept translations with warnings (non-critical issues)
**Example**: `accept_warnings: true`

**Impact**:
- `true`: Warnings are acceptable, only errors block acceptance
- `false`: Both errors and warnings block acceptance

##### accept_after_max_retries

**Type**: Boolean
**Required**: No
**Default**: true
**Description**: Accept translation after exhausting retries (best effort) or reject
**Example**: `accept_after_max_retries: true`

**Impact**:
- `true`: Accept best effort after max retries
- `false`: Reject if issues remain after max retries

---

#### retry_strategy

Container for retry behavior configuration.

##### feedback_mode

**Type**: String
**Required**: No
**Default**: "detailed"
**Values**: "brief", "detailed", "examples"
**Description**: Detail level for retry feedback messages
**Example**: `feedback_mode: "detailed"`

**Options**:
- `brief`: Short error messages only
- `detailed`: Error messages with locations and suggestions
- `examples`: Detailed messages with code examples (future)

##### vary_temperature

**Type**: Boolean
**Required**: No
**Default**: true
**Description**: Vary LLM temperature on retry attempts
**Example**: `vary_temperature: true`

**Impact**:
- `true`: Increase temperature on each retry (more creative)
- `false`: Keep temperature constant

##### temperature_increment

**Type**: Float
**Required**: No
**Default**: 0.1
**Range**: 0.0-0.5 (recommended)
**Description**: How much to increase temperature per retry
**Example**: `temperature_increment: 0.1`

**Used only if**: `vary_temperature: true`

##### max_temperature

**Type**: Float
**Required**: No
**Default**: 1.0
**Range**: 0.0-2.0
**Description**: Maximum temperature to use (ceiling)
**Example**: `max_temperature: 1.0`

---

#### validation_modes

Predefined validation mode profiles. Users can select via CLI `--validation-mode`.

Each mode contains the same fields as `decision_rules`:
- `accept_warnings`: Boolean
- `reject_on_error_count`: Integer
- `max_retry_attempts`: Integer

##### strict

**Description**: Zero tolerance for errors, minimal retries
**Use case**: Production translation, critical content, API documentation

**Default values**:
```yaml
strict:
  accept_warnings: false
  reject_on_error_count: 1
  max_retry_attempts: 1
```

##### normal

**Description**: Balanced validation (default)
**Use case**: General content translation, blog posts, marketing pages

**Default values**:
```yaml
normal:
  accept_warnings: true
  reject_on_error_count: 3
  max_retry_attempts: 2
```

##### lenient

**Description**: Tolerant of issues, more retries
**Use case**: Quick drafts, internal documentation, testing

**Default values**:
```yaml
lenient:
  accept_warnings: true
  reject_on_error_count: 5
  max_retry_attempts: 2
```

---

#### validators

Container for individual validator configuration.

Each validator has:
- `enabled`: Boolean - Enable/disable this validator
- `description`: String - Human-readable description
- (Optional) Validator-specific settings

##### yaml

**Description**: Validates YAML frontmatter syntax

**Fields**:
```yaml
yaml:
  enabled: true
  description: "Validates YAML frontmatter syntax"
```

##### placeholder

**Description**: Validates placeholder integrity

**Fields**:
```yaml
placeholder:
  enabled: true
  description: "Validates placeholder integrity"
```

**Note**: Critical validator - errors trigger immediate REJECT

##### structure

**Description**: Validates markdown structure preservation

**Fields**:
```yaml
structure:
  enabled: true
  description: "Validates markdown structure preservation"
```

##### link

**Description**: Validates link integrity

**Fields**:
```yaml
link:
  enabled: true
  description: "Validates link integrity"
```

**Note**: Critical validator - errors trigger immediate REJECT

##### completeness

**Description**: Validates 100% segment coverage

**Fields**:
```yaml
completeness:
  enabled: true
  description: "Validates 100% segment coverage"
```

##### language_consistency

**Description**: Validates target language consistency using langdetect

**Fields**:
```yaml
language_consistency:
  enabled: true
  confidence_threshold: 0.85
  description: "Validates target language consistency using langdetect"
```

**confidence_threshold**:
- **Type**: Float
- **Range**: 0.0-1.0
- **Default**: 0.85
- **Description**: Minimum confidence for language detection

**Tuning**:
- `0.95`: Very strict, high confidence required
- `0.85`: Balanced (default)
- `0.70`: Lenient, accept lower confidence

##### shortcode_preservation

**Description**: Validates Hugo shortcode preservation

**Fields**:
```yaml
shortcode_preservation:
  enabled: true
  description: "Validates Hugo shortcode preservation"
```

##### frontmatter_protection

**Description**: Validates frontmatter field protection rules

**Fields**:
```yaml
frontmatter_protection:
  enabled: true
  description: "Validates frontmatter field protection rules"
```

**Dependencies**: Requires site profile for frontmatter rules

##### terminology_preservation

**Description**: Validates terminology preservation (Aspose, .NET, etc.)

**Fields**:
```yaml
terminology_preservation:
  enabled: true
  validation_mode: "strict"
  description: "Validates terminology preservation (Aspose, .NET, etc.)"
```

**validation_mode**:
- **Type**: String
- **Values**: "strict", "normal", "lenient"
- **Default**: "strict"
- **Description**: How strictly to validate terminology

**Modes**:
- `strict`: Any missing term = ERROR, frequency mismatch = ERROR
- `normal`: Missing term = ERROR, frequency mismatch = WARNING (default)
- `lenient`: Missing critical terms = WARNING, frequency mismatch = INFO

##### file_placement

**Description**: Validates file placement and directory structure

**Fields**:
```yaml
file_placement:
  enabled: true
  description: "Validates file placement and directory structure"
```

**Dependencies**: Requires config service for output layout rules

---

## terminology.yaml

Defines protected terminology for translation preservation.

**Location**: `config/terminology.yaml`

### Schema

```yaml
version: "1.0"

global:
  exact_matches:
    - term: <string>
      category: <string>
      case_sensitive: <boolean>
      preserve_mode: <string: "protect" | "validate" | "both" | "none">
      severity: <string: "error" | "warning" | "info">

  patterns:
    - pattern: <regex_string>
      category: <string>
      description: <string>
      preserve_mode: <string: "protect" | "validate" | "both" | "none">
      severity: <string: "error" | "warning" | "info">

site_overrides:
  <site_id>:
    inherit_global: <boolean>
    exact_matches: [...]
    patterns: [...]

auto_discovery:
  enabled: <boolean>
  min_frequency: <integer>
  confidence_threshold: <float>
```

### Field Reference

#### version

**Type**: String
**Required**: Yes
**Default**: "1.0"
**Description**: Configuration file version
**Example**: `version: "1.0"`

---

#### global

Container for global terminology rules applied to all sites.

##### exact_matches

Array of exact match term definitions.

###### term

**Type**: String
**Required**: Yes
**Description**: Exact string to match and preserve
**Example**: `term: "Aspose"`

###### category

**Type**: String
**Required**: Yes
**Description**: Category for grouping and reporting
**Example**: `category: "company_name"`

**Common categories**:
- `company_name`: Company names (Aspose)
- `product_family`: Product names (Aspose.Words)
- `platform`: Platform names (.NET, Java)
- `plugin_name`: Plugin/extension names

###### case_sensitive

**Type**: Boolean
**Required**: Yes
**Description**: Whether matching is case-sensitive
**Example**: `case_sensitive: true`

**Guidelines**:
- `true`: Proper nouns, API names, acronyms
- `false`: Generic technical terms (use sparingly)

###### preserve_mode

**Type**: String
**Required**: Yes
**Values**: "protect", "validate", "both", "none"
**Description**: How to preserve this term
**Example**: `preserve_mode: "both"`

**Options**:
- `protect`: Replace with placeholder before translation
- `validate`: Check term preservation after translation
- `both`: Protect AND validate (recommended)
- `none`: No protection

###### severity

**Type**: String
**Required**: Yes
**Values**: "error", "warning", "info"
**Description**: Severity level for validation issues
**Example**: `severity: "error"`

**Levels**:
- `error`: Critical, blocks acceptance
- `warning`: Important, alerts but doesn't block
- `info`: Informational, tracking only

---

##### patterns

Array of pattern-based term definitions.

###### pattern

**Type**: String (regex)
**Required**: Yes
**Description**: Regular expression to match terms
**Example**: `pattern: "Aspose\\.[A-Z][a-z]+"`

**Syntax**: Python regular expression (re module)

###### category

**Type**: String
**Required**: Yes
**Description**: Category for grouping and reporting
**Example**: `category: "product_family"`

###### description

**Type**: String
**Required**: No
**Description**: Human-readable explanation of pattern
**Example**: `description: "Aspose product families (Aspose.Words, Aspose.Cells, etc.)"`

###### preserve_mode

**Type**: String
**Required**: Yes
**Values**: "protect", "validate", "both", "none"
**Description**: How to preserve matched terms
**Example**: `preserve_mode: "protect"`

###### severity

**Type**: String
**Required**: Yes
**Values**: "error", "warning", "info"
**Description**: Severity level for validation issues
**Example**: `severity: "error"`

---

#### site_overrides

Container for site-specific terminology overrides.

##### <site_id>

Key is the site ID (e.g., "reference.aspose.net").

###### inherit_global

**Type**: Boolean
**Required**: No
**Default**: false
**Description**: Whether to inherit all global terminology rules
**Example**: `inherit_global: true`

**Impact**:
- `true`: Include all global rules + site-specific rules
- `false`: Only use site-specific rules

###### exact_matches

Same structure as `global.exact_matches`.
Additional exact matches for this site.

###### patterns

Same structure as `global.patterns`.
Additional patterns for this site.

---

#### auto_discovery

Configuration for automatic terminology discovery (future feature).

##### enabled

**Type**: Boolean
**Required**: No
**Default**: false
**Description**: Enable automatic terminology discovery
**Example**: `enabled: false`

**Status**: Currently disabled, will be enabled in future iterations

##### min_frequency

**Type**: Integer
**Required**: No
**Default**: 3
**Description**: Minimum occurrences to consider as terminology candidate
**Example**: `min_frequency: 3`

##### confidence_threshold

**Type**: Float
**Required**: No
**Default**: 0.8
**Range**: 0.0-1.0
**Description**: Minimum confidence score to auto-add term
**Example**: `confidence_threshold: 0.8`

---

## Site Profile Validation

Site profiles (`config/site_profiles/*.yaml`) include validation and frontmatter protection settings.

### Validation Section

```yaml
validation:
  check_placeholders: <boolean>
  check_links: <boolean>
  check_yaml_structure: <boolean>
  fail_on_error: <boolean>
```

#### check_placeholders

**Type**: Boolean
**Default**: true
**Description**: Enable placeholder validation for this site
**Example**: `check_placeholders: true`

#### check_links

**Type**: Boolean
**Default**: true
**Description**: Enable link validation for this site
**Example**: `check_links: true`

#### check_yaml_structure

**Type**: Boolean
**Default**: true
**Description**: Enable YAML structure validation for this site
**Example**: `check_yaml_structure: true`

#### fail_on_error

**Type**: Boolean
**Default**: false
**Description**: Fail translation immediately on validation error (legacy, superseded by decision engine)
**Example**: `fail_on_error: false`

---

### Frontmatter Section

Defines frontmatter field protection rules.

```yaml
frontmatter:
  <field_name>:
    mode: <string: "translate" | "keep" | "remove">
```

#### mode

**Type**: String
**Values**: "translate", "keep", "remove"
**Description**: How to handle this frontmatter field

**Options**:
- `translate`: Translate field value to target language
- `keep`: Keep field value unchanged
- `remove`: Remove field from translation (rare)

**Examples**:
```yaml
frontmatter:
  title:
    mode: "translate"    # Translate page title
  description:
    mode: "translate"    # Translate meta description
  date:
    mode: "keep"         # Keep date unchanged
  draft:
    mode: "keep"         # Keep draft status unchanged
  tags:
    mode: "keep"         # Keep tags unchanged (or "translate" to translate tag names)
```

---

## Examples and Defaults

### Default validation.yaml

```yaml
version: "1.0"

decision_rules:
  reject_on_error_count: 3
  reject_on_placeholder_error: true
  reject_on_code_block_error: true
  reject_on_link_error: true
  max_retry_attempts: 2
  retry_on_structure_error: true
  retry_on_terminology_warning: true
  accept_warnings: true
  accept_after_max_retries: true

retry_strategy:
  feedback_mode: "detailed"
  vary_temperature: true
  temperature_increment: 0.1
  max_temperature: 1.0

validation_modes:
  strict:
    accept_warnings: false
    reject_on_error_count: 1
    max_retry_attempts: 1

  normal:
    accept_warnings: true
    reject_on_error_count: 3
    max_retry_attempts: 2

  lenient:
    accept_warnings: true
    reject_on_error_count: 5
    max_retry_attempts: 2

validators:
  yaml:
    enabled: true
    description: "Validates YAML frontmatter syntax"

  placeholder:
    enabled: true
    description: "Validates placeholder integrity"

  structure:
    enabled: true
    description: "Validates markdown structure preservation"

  link:
    enabled: true
    description: "Validates link integrity"

  completeness:
    enabled: true
    description: "Validates 100% segment coverage"

  language_consistency:
    enabled: true
    confidence_threshold: 0.85
    description: "Validates target language consistency using langdetect"

  shortcode_preservation:
    enabled: true
    description: "Validates Hugo shortcode preservation"

  frontmatter_protection:
    enabled: true
    description: "Validates frontmatter field protection rules"

  terminology_preservation:
    enabled: true
    validation_mode: "strict"
    description: "Validates terminology preservation (Aspose, .NET, etc.)"

  file_placement:
    enabled: true
    description: "Validates file placement and directory structure"
```

### Default terminology.yaml

```yaml
version: "1.0"

global:
  exact_matches:
    - term: "Aspose"
      category: company_name
      case_sensitive: true
      preserve_mode: both
      severity: error

    - term: ".NET"
      category: platform
      case_sensitive: true
      preserve_mode: both
      severity: error

    - term: "Java"
      category: platform
      case_sensitive: true
      preserve_mode: both
      severity: error

    - term: "Python"
      category: platform
      case_sensitive: true
      preserve_mode: both
      severity: error

  patterns:
    - pattern: "Aspose\\.[A-Z][a-z]+"
      category: product_family
      description: "Aspose product families (Aspose.Words, Aspose.Cells, etc.)"
      preserve_mode: protect
      severity: error

    - pattern: "\\bLINQ Engine\\b"
      category: plugin_name
      description: "LINQ Engine plugin"
      preserve_mode: both
      severity: error

site_overrides:
  reference.aspose.net:
    inherit_global: true
    patterns:
      - pattern: "\\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\\b"
        category: pascal_case_identifier
        description: "PascalCase API identifiers"
        preserve_mode: protect
        severity: error

      - pattern: "\\b[A-Z_]+\\b"
        category: constant_name
        description: "UPPER_CASE constants"
        preserve_mode: protect
        severity: warning

auto_discovery:
  enabled: false
  min_frequency: 3
  confidence_threshold: 0.8
```

### Example Site Profile (products.aspose.net)

```yaml
site_id: "products.aspose.net"

content_roots:
  - "/content"

default_source_lang: "en"

target_langs:
  - "de"
  - "fr"
  - "es"
  - "ja"

frontmatter:
  title:
    mode: "translate"
  description:
    mode: "translate"
  date:
    mode: "keep"
  draft:
    mode: "keep"
  tags:
    mode: "keep"

validation:
  check_placeholders: true
  check_links: true
  check_yaml_structure: true
  fail_on_error: false
```

---

## Environment Variables

Environment variables provide runtime configuration options that can override defaults or enable deployment-specific behavior.

### TELEMETRY_SRC_PATH

**Purpose**: Override the default path to the local-telemetry source directory.

**Default**: None (set `TELEMETRY_SRC_PATH` env var to your local-telemetry checkout's `src/` directory)

**When to use**:
- **Development**: Point to a local checkout of local-telemetry for debugging or testing changes
- **Production**: Set if telemetry module is installed in a non-standard location
- **Docker/Containers**: Set to match volume mount paths or container-specific locations
- **CI/CD**: Configure per environment (dev/staging/prod) with different telemetry installations

**Configuration**:

Add to `.env` file or set in shell:

```bash
# Windows
set TELEMETRY_SRC_PATH=C:\custom\path\to\local-telemetry\src

# Linux/Mac
export TELEMETRY_SRC_PATH=/opt/local-telemetry/src

# Docker
TELEMETRY_SRC_PATH=/app/telemetry/src
```

**Path format**:
- Windows: Use single backslashes (raw string) or forward slashes
- Linux/Mac: Use forward slashes
- Must point to directory containing `telemetry/` package

**Behavior**:
- If path exists and is not in `sys.path`: Added to Python path, telemetry enabled
- If path doesn't exist: Warning logged, telemetry disabled (graceful degradation)
- If path already in `sys.path`: No action taken (debug log only)

**Verification**:

Check which path is being used:

```bash
# View logs during startup
python scripts/verify_telemetry.py --latest

# Test with custom path
set TELEMETRY_SRC_PATH=C:\custom\path
python -c "from src.observability.telemetry_integration import TELEMETRY_SRC_PATH; print(TELEMETRY_SRC_PATH)"
```

**Troubleshooting**:
- If telemetry is unavailable, check logs for WARNING messages about path
- Verify path exists and contains `telemetry/client.py` and `telemetry/config.py`
- On Windows, avoid trailing backslashes in path

---

## Related Documentation

- [Validation Guide](./validation_guide.md) - How validators work and decision logic
- [Terminology Pattern Syntax](./terminology-pattern-syntax.md) - Regex patterns for terminology protection
- [Troubleshooting](./troubleshooting.md) - Common configuration errors and fixes
