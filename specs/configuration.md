# Configuration Schema - Hugo Translation System

**Purpose:** Canonical documentation of all configuration options
**Status:** 🔍 EVIDENCE_ONLY
**Last Updated:** 2025-12-26

---

## Overview

This document defines all configuration knobs, environment variables, and their precedence order. The Hugo Translation System uses a hierarchical configuration system:

**Configuration Precedence (Highest → Lowest):**
```
1. CLI flags (--strict, --no-cache, etc.)
2. Environment variables (SITE_*_*, METRICS_API_URL, etc.)
3. Site profile config (config/site_profiles/{site_id}.yaml)
4. Global config (config/global.yaml)
5. Validation config (config/validation.yaml)
6. Code defaults (hardcoded fallbacks)
```

**Evidence:** [src/utils/config_loader.py](../src/utils/config_loader.py) lines 117-129 (env overrides), [src/cli.py](../src/cli.py) lines 148-202 (CLI overrides)

---

## Configuration Files

### Global Configuration

**File:** `config/global.yaml`
**Purpose:** System-wide defaults for all sites
**Evidence:** [config/global.yaml](../config/global.yaml)

**Structure:**
```yaml
system:
  name: string
  version: string
  environment: string  # development, staging, production

tm_defaults:
  use_semantic_tm: boolean
  semantic_threshold: float  # 0.0-1.0
  fallback_exact_only: boolean
  l1_cache_size: int
  l2_max_size_mb: int
  l3_embedding_model: string
  l3_index_type: string  # Flat, IVFFlat, HNSW

model_defaults:
  fallback_model: string
  device: string  # auto, cpu, cuda, mps
  batch_size: int
  cache_models: boolean
  max_cached_models: int

hardware:
  enable_gpu: boolean
  max_gpu_memory_mb: int
  gpu_device_id: int  # -1 = auto
  allow_cpu_fallback: boolean
  clear_cache_after_batch: boolean

orchestrator:
  mode: string  # auto, manual
  max_workers: int
  job_queue_backend: string  # memory, redis
  sweep_interval_hours: int
  file_watcher_debounce_seconds: float
  enable_file_watcher: boolean
  enable_sweep_scheduler: boolean

performance:
  parallel_translation: boolean
  max_parallel_files: int
  model_cache_size: int
  enable_batch_optimization: boolean

observability:
  log_level: string  # DEBUG, INFO, WARNING, ERROR, CRITICAL
  log_format: string  # text, json
  flow_artifact_detail: string  # none, summary, sampled, full
  flow_artifact_sample_rate: float
  metrics_enabled: boolean
  metrics_port: int
  metrics_pushgateway: string  # URL (optional)

telemetry:
  validation_metrics: boolean

default_output_layout:
  per_language_folders: boolean
  pattern: string  # {lang}/{path}

paths:
  config_dir: string
  content_root: string
  output_dir: string
  model_cache_dir: string
  tm_data_dir: string
  l3_index_dir: string
  artifacts_dir: string
  logs_dir: string
  backup_dir: string

validation:
  enabled: boolean
  config_file: string
  mode: string  # strict, normal, lenient
  rules: array
  strict_mode: boolean

terminology:
  enabled: boolean
  config_file: string
  preserve_mode: string  # PROTECT, VALIDATE, BOTH, NONE

security:
  enable_input_validation: boolean
  max_file_size_mb: int
  allowed_extensions: array
  sanitize_output: boolean

features:
  enable_parallel_processing: boolean
  enable_semantic_tm: boolean
  enable_model_benchmarking: boolean
  enable_auto_model_selection: boolean
  enable_quality_scoring: boolean

l4_llm:
  enabled: boolean
  provider: string  # ollama, openai, anthropic
  model: string
  api_key: string | null
  base_url: string
  min_similarity: float
  max_similarity: float
  timeout_seconds: int
  max_latency_ms: int
  cache_adaptations: boolean

validation_defaults:
  mode: string  # strict, normal, lenient
  decision_rules:
    reject_on_error_count: int
    max_retry_attempts: int
    accept_warnings: boolean
  post_write:
    enabled: boolean
    delete_on_failure: boolean
    halt_on_failure: boolean
  validators:
    completeness:
      enabled: boolean
    language_consistency:
      enabled: boolean
      confidence_threshold: float
    shortcode_preservation:
      enabled: boolean
    frontmatter_protection:
      enabled: boolean
    terminology_preservation:
      enabled: boolean
    file_placement:
      enabled: boolean
```

**Defaults:** Lines 1-161 in global.yaml

---

### Validation Configuration

**File:** `config/validation.yaml`
**Purpose:** Validation pipeline configuration
**Evidence:** [config/validation.yaml](../config/validation.yaml)

**Structure:**
```yaml
version: string

decision_rules:
  reject_on_error_count: int
  reject_on_placeholder_error: boolean
  reject_on_code_block_error: boolean
  reject_on_link_error: boolean
  max_retry_attempts: int
  retry_on_structure_error: boolean
  retry_on_terminology_warning: boolean
  accept_warnings: boolean
  accept_after_max_retries: boolean

retry_strategy:
  feedback_mode: string  # brief, detailed, examples
  vary_temperature: boolean
  temperature_increment: float
  max_temperature: float

validation_modes:
  strict:
    accept_warnings: boolean
    reject_on_error_count: int
    max_retry_attempts: int
  normal:
    accept_warnings: boolean
    reject_on_error_count: int
    max_retry_attempts: int
  lenient:
    accept_warnings: boolean
    reject_on_error_count: int
    max_retry_attempts: int

validators:
  yaml:
    enabled: boolean
    description: string
  placeholder:
    enabled: boolean
    description: string
  structure:
    enabled: boolean
    description: string
  link:
    enabled: boolean
    description: string
  completeness:
    enabled: boolean
    description: string
  language_consistency:
    enabled: boolean
    confidence_threshold: float
    description: string
  shortcode_preservation:
    enabled: boolean
    description: string
  frontmatter_protection:
    enabled: boolean
    description: string
  terminology_preservation:
    enabled: boolean
    validation_mode: string
    description: string
  file_placement:
    enabled: boolean
    description: string
```

**Mode Defaults:**
- **strict:** reject_on_error_count=1, max_retry_attempts=1, accept_warnings=false
- **normal:** reject_on_error_count=3, max_retry_attempts=2, accept_warnings=true
- **lenient:** reject_on_error_count=5, max_retry_attempts=2, accept_warnings=true

**Evidence:** Lines 1-98 in validation.yaml

---

### Site Profile Configuration

**File:** `config/site_profiles/{site_id}.yaml`
**Purpose:** Site-specific translation configuration
**Evidence:** [config/site_profiles/default.yaml](../config/site_profiles/default.yaml), [config/site_profiles/example.yaml](../config/site_profiles/example.yaml)

**Structure:**
```yaml
site_id: string  # REQUIRED - Unique identifier

content_roots: array  # REQUIRED - Root directories for content
default_source_lang: string  # REQUIRED - Source language code (ISO 639-1)
target_langs: array  # REQUIRED - Target language codes

frontmatter:
  {field_name}:
    mode: string  # translate, passthrough, keep, translate_list
    strategy: string | null  # custom, null

body:
  translate_markdown: boolean
  preserve_blocks: array  # block types to preserve
  preserve_patterns: array  # regex patterns
  placeholder_syntax: array  # shortcode patterns
  translate_image_alt: boolean  # optional
  translate_link_titles: boolean  # optional
  use_ast_body_reconstruction: boolean  # optional
  ast_segmentation_strategy: string  # optional: adaptive, leaf_only, sentence_only
  ast_batch_size: int  # optional

output_layout:
  per_language_folders: boolean
  pattern: string  # {lang}/{path}, {lang}/{relative_path}
  preserve_structure: boolean  # optional

tm_prefs:  # optional
  use_semantic_tm: boolean
  fallback_exact_only: boolean
  min_similarity_score: float  # 0.0-1.0
  semantic_threshold: float  # optional
  use_semantic: boolean  # optional
  use_context: boolean  # optional

default_model: string | null  # optional - model ID override

validation:  # optional
  enabled: boolean
  validation_mode: string  # strict, normal, lenient, off
  validators:
    completeness:
      enabled: boolean
    language_consistency:
      enabled: boolean
      confidence_threshold: float
    shortcode_preservation:
      enabled: boolean
    frontmatter_protection:
      enabled: boolean
    terminology_preservation:
      enabled: boolean
      validation_mode: string
    file_placement:
      enabled: boolean
  post_write_validation: boolean
  check_placeholders: boolean  # legacy
  check_links: boolean  # legacy
  check_yaml_structure: boolean  # legacy
  fail_on_error: boolean  # legacy

terminology:  # optional
  enabled: boolean
  preserve_mode: string  # PROTECT, VALIDATE, BOTH, NONE
  inherit_global: boolean
  custom_terms: array

model:  # optional (legacy)
  default: string
  overrides: object  # {lang_pair: model_id}

performance:  # optional
  batch_size: int
  enable_cache: boolean

logging:  # optional
  level: string  # DEBUG, INFO, WARNING, ERROR
  flow_artifacts: boolean
  artifact_detail: string  # NONE, SUMMARY, SAMPLED, FULL

metadata:  # optional
  add_translation_info: boolean
  custom_fields: object  # {key: value}

schema:  # documentation only (not used by system)
  version: string
  description: string
  fields: object
  examples: array
```

**Required Fields:**
- site_id
- content_roots
- default_source_lang
- target_langs
- frontmatter
- body
- output_layout

**Evidence:** Lines 1-275 in default.yaml (full schema with documentation)

---

## Environment Variables

### Site-Specific Overrides

**Pattern:** `SITE_{SITE_ID}_{SETTING}`

**Format:** Site ID uppercase, periods/hyphens replaced with underscores

**Examples:**
```bash
# Override default source language for products.aspose.net
export SITE_PRODUCTS_ASPOSE_NET_DEFAULT_SOURCE_LANG=en

# Override target languages for blog.aspose.net
export SITE_BLOG_ASPOSE_NET_TARGET_LANGS=fr,de,es
```

**Supported Overrides:**
- `SITE_{SITE_ID}_DEFAULT_SOURCE_LANG` → default_source_lang
- `SITE_{SITE_ID}_TARGET_LANGS` → target_langs (comma-separated)

**Evidence:** [src/utils/config_loader.py](../src/utils/config_loader.py) lines 117-129

---

### System-Wide Environment Variables

**Metrics:**
```bash
METRICS_API_URL=http://localhost:8765  # Metrics push endpoint
```
**Evidence:** [src/cli.py](../src/cli.py) line 988

**Paths (Inferred from global.yaml paths section):**
```bash
CONFIG_PATH=./config           # Config root override
TM_PATH=./data/tm              # TM data directory
L3_INDEX_PATH=./data/tm/l3_faiss  # L3 index directory
MODEL_CACHE=~/.cache/huggingface  # HuggingFace model cache
```
**Evidence:** global.yaml paths section (lines 71-80)

**Note:** These environment variables are referenced in code but not explicitly documented in config loader. Verification needed for exact variable names.

---

## CLI Flag Overrides

### Validation Mode Flags

**Flags:**
```bash
--strict          # Set validation_mode=strict, reject_on_error_count=1
--lenient         # Set validation_mode=lenient, reject_on_error_count=5
--no-validation   # Disable validation entirely
```

**Evidence:** [src/cli.py](../src/cli.py) lines 290-298

**Precedence:** CLI flags override site profile validation.mode

---

### Cache Control Flags

**Flags:**
```bash
--no-cache             # Bypass all TM layers
--cache-read-only      # Only read from TM, don't write
--cache-write-only     # Only write to TM, don't read (no effect)
```

**Evidence:** [src/cli.py](../src/cli.py) lines 532-546

---

### Model Control Flags

**Flags:**
```bash
--model MODEL_ID       # Override model selection
--use-gpu              # Enable GPU acceleration
--gpu-layers N         # Number of GPU layers
--batch-size N         # Translation batch size
--context-length N     # Model context length
```

**Evidence:** [src/cli.py](../src/cli.py) lines 327-381

---

### Resume Control Flags

**Flags:**
```bash
--resume               # Resume from progress checkpoint (default)
--no-resume            # Ignore progress, translate all
--force-restart        # Clear progress and start fresh
--clear-all-progress   # Clear all site progress (destructive)
```

**Evidence:** [src/cli.py](../src/cli.py) lines 500-525

---

### Output Control Flags

**Flags:**
```bash
--dry-run              # Preview mode, no writes
--save-rejected        # Save rejected translations
--output-dir PATH      # Override output directory
```

**Evidence:** [src/cli.py](../src/cli.py) lines 432-453

---

### Progress/Metrics Flags

**Flags:**
```bash
--metrics-file PATH    # Metrics output file
--metrics-interval N   # Metrics update interval (seconds)
--no-progress          # Disable progress tracking
```

**Evidence:** [src/cli.py](../src/cli.py) lines 471-497

---

## Configuration Merging Rules

### Site Profile Merging

**Override Order:**
```python
1. Load global.yaml defaults
2. Load site profile {site_id}.yaml
3. Merge site profile over global (site wins)
4. Apply environment variable overrides (env wins)
5. Apply CLI flag overrides (CLI wins)
```

**Merge Behavior:**
- **Scalar values:** Site profile overrides global
- **Arrays:** Site profile replaces global (no merge)
- **Objects:** Shallow merge (site fields override global fields)

**Example:**
```yaml
# global.yaml
validation:
  enabled: true
  mode: normal
  reject_on_error_count: 3

# site profile
validation:
  mode: strict  # Override mode

# Result after merge
validation:
  enabled: true           # From global
  mode: strict            # From site profile
  reject_on_error_count: 3  # From global
```

**Evidence:** [src/utils/config_loader.py](../src/utils/config_loader.py) Pydantic model merging

---

### Validation Mode Merging

**CLI Override Logic:**
```python
if args.no_validation:
    enable_validation = False
elif args.strict:
    validation_mode = "strict"
    reject_on_error_count = 1
elif args.lenient:
    validation_mode = "lenient"
    reject_on_error_count = 5
else:
    # Use merged site profile + global defaults
    validation_mode = merged_config.validation.mode
    reject_on_error_count = merged_config.validation.reject_on_error_count
```

**Evidence:** [src/cli.py](../src/cli.py) lines 148-149 (CLI override application)

---

## Configuration Validation

### Pydantic Models

**Models:**
- `GlobalConfig` - Global configuration schema
- `SiteProfile` - Site profile schema
- `ValidationConfig` - Validation configuration schema
- `TerminologyConfig` - Terminology configuration schema

**Evidence:** [src/utils/models.py](../src/utils/models.py) (inferred from imports in config_loader.py line 16-21)

**Validation Rules:**
- Required fields must be present
- Type checking (string, int, float, boolean, array, object)
- Enum validation (mode: strict|normal|lenient)
- Range validation (confidence_threshold: 0.0-1.0)

**Error Handling:**
```python
try:
    profile = SiteProfile(**data)
except ValidationError as e:
    raise ConfigValidationError(f"Invalid profile {site_id}: {e}")
```

**Evidence:** [src/utils/config_loader.py](../src/utils/config_loader.py) lines 111-115

---

## Configuration Caching

### Profile Cache

**Behavior:**
- Site profiles cached in memory after first load
- Cache key: site_id
- Cache bypass: `use_cache=False` parameter
- Cache invalidation: `reload_profile(site_id)`

**Evidence:** [src/utils/config_loader.py](../src/utils/config_loader.py) lines 49 (_profile_cache), lines 86-93 (cache check)

**Global Config:**
- Loaded once at service initialization
- Cached in `_global_config` attribute
- No reload mechanism (restart required)

**Evidence:** Lines 50, 57-69 (global config loading)

---

## Configuration Discovery

### Site Profile Discovery

**Method:** `list_sites() -> List[str]`

**Behavior:**
```python
# Glob for all .yaml files in site_profiles directory
site_ids = [f.stem for f in config/site_profiles/*.yaml]
return sorted(site_ids)
```

**Example:**
```
config/site_profiles/
  products.aspose.net.yaml  → site_id: products.aspose.net
  blog.aspose.net.yaml      → site_id: blog.aspose.net
  default.yaml              → site_id: default
```

**Evidence:** [src/utils/config_loader.py](../src/utils/config_loader.py) lines 131-135

---

## Default Values

### Translation Memory Defaults

**Source:** global.yaml tm_defaults section

| Setting | Default | Description |
|---------|---------|-------------|
| use_semantic_tm | true | Enable L3 semantic search |
| semantic_threshold | 0.80 | Min similarity for L3 matches (0.0-1.0) |
| fallback_exact_only | false | Fallback to L1/L2 only if L3 fails |
| l1_cache_size | 10000 | L1 LRU cache max entries |
| l2_max_size_mb | 1024 | L2 LMDB max database size (1 GB) |
| l3_embedding_model | paraphrase-multilingual-mpnet-base-v2 | Sentence transformer model |
| l3_index_type | IVFFlat | FAISS index type |

**Evidence:** global.yaml lines 8-16

---

### Model Defaults

**Source:** global.yaml model_defaults section

| Setting | Default | Description |
|---------|---------|-------------|
| fallback_model | m2m100_418m | Model if site profile doesn't specify |
| device | auto | Device selection (auto, cpu, cuda, mps) |
| batch_size | 32 | Default translation batch size |
| cache_models | true | Cache loaded models in memory |
| max_cached_models | 2 | Max models to keep in memory |

**Evidence:** global.yaml lines 19-24

---

### Validation Mode Defaults

**Source:** validation.yaml validation_modes section

| Mode | reject_on_error_count | max_retry_attempts | accept_warnings |
|------|----------------------|-------------------|----------------|
| strict | 1 | 1 | false |
| normal | 3 | 2 | true |
| lenient | 5 | 2 | true |

**Evidence:** validation.yaml lines 31-50

---

## Configuration Files Reference

**Directory Structure:**
```
config/
  global.yaml                   # System-wide defaults
  validation.yaml               # Validation pipeline config
  terminology.yaml              # Terminology preservation rules
  model_registry.yaml           # Model definitions (inferred)
  metrics.yaml                  # Metrics config (inferred)
  benchmarking.yaml             # Benchmarking config (inferred)
  quality_gates.yaml            # Quality gate thresholds (inferred)
  claims.yaml                   # Terminology claims (inferred)
  site_profiles/
    default.yaml                # Fallback profile
    example.yaml                # Example with all options
    {site_id}.yaml              # Site-specific profiles
```

**Evidence:** Glob results from config directory

---

## Example Configurations

### Example 1: Strict Technical Documentation Site

```yaml
site_id: docs.example.com
content_roots:
  - /docs/content
default_source_lang: en
target_langs: [fr, de, ja]

validation:
  enabled: true
  validation_mode: strict  # Reject on first error
  validators:
    yaml:
      enabled: true
    placeholder:
      enabled: true
    structure:
      enabled: true
    shortcode_preservation:
      enabled: true

frontmatter:
  title: { mode: translate }
  description: { mode: translate }
  date: { mode: passthrough }
  url: { mode: passthrough }
  api_version: { mode: passthrough }

tm_prefs:
  use_semantic_tm: true
  min_similarity_score: 0.90  # High threshold for technical content

default_model: m2m100_1.2b  # Larger model for better quality
```

---

### Example 2: Lenient Blog Site

```yaml
site_id: blog.example.com
content_roots:
  - /blog/posts
default_source_lang: en
target_langs: [es, pt, fr]

validation:
  enabled: true
  validation_mode: lenient  # More tolerant
  validators:
    completeness: { enabled: true }
    language_consistency: { enabled: true }

frontmatter:
  title: { mode: translate }
  summary: { mode: translate }
  tags: { mode: translate_list }  # Translate tag names
  date: { mode: passthrough }

tm_prefs:
  use_semantic_tm: true
  min_similarity_score: 0.75  # Lower threshold for blog content

default_model: m2m100_418m  # Smaller model, faster
```

---

### Example 3: CLI Override Examples

**Override validation mode to strict:**
```bash
translate-hugo --site blog.example.com --strict --langs fr de
# Overrides blog.example.com's lenient mode
```

**Disable validation entirely:**
```bash
translate-hugo --site docs.example.com --no-validation --langs ja
# Bypasses strict validation for testing
```

**Force fresh translation with no cache:**
```bash
translate-hugo --site products.example.com --no-cache --force-restart --langs zh
# Clears progress and bypasses TM
```

---

## Verification Status

🔍 **EVIDENCE_ONLY**

**Verification Steps Required:**

1. **Environment variable enumeration:**
   - Search all code for `os.getenv()` and `os.environ.get()`
   - Document all supported env vars with exact names
   - Verify TM_PATH, CONFIG_PATH, MODEL_CACHE variable names

2. **CLI flag documentation:**
   - Read complete argument parser in cli.py
   - Document all flags with exact names and descriptions
   - Verify flag precedence logic

3. **Configuration merging logic:**
   - Trace config merging in config_loader.py
   - Verify shallow vs deep merge behavior
   - Document array replacement vs merge

4. **Pydantic model schemas:**
   - Read complete models.py schemas
   - Document all required vs optional fields
   - Document validation rules and constraints

5. **Create contract test:** `tests/contract/test_configuration_schema.py`
   - Test CLI overrides site profile
   - Test env vars override site profile
   - Test default fallback values
   - Test invalid config rejection

**Blockers:** Need to locate and read models.py for complete schema validation rules

---

## Related Documents

- [Core Invariants](core_invariants.md#inv-005-validation-mode-cli-override) - Configuration precedence invariant
- [Driftless Governance](../docs/development/driftless.md)
- [Gap Closure Plan](../reports/driftless/16_gap_closure_plan.md#support-002-configuration-schema)
