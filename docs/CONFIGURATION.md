# Hugo Translation System - Configuration Reference

**Version:** 1.0.0
**Last Updated:** 2025-11-21

---

## Table of Contents

1. [Overview](#overview)
2. [Global Configuration](#global-configuration)
3. [Site Profiles](#site-profiles)
4. [Model Registry](#model-registry)
5. [Environment Variables](#environment-variables)
6. [Translation Memory Configuration](#translation-memory-configuration)
7. [Configuration Examples](#configuration-examples)
8. [Validation and Best Practices](#validation-and-best-practices)

---

## Overview

The Hugo Translation System uses a layered configuration approach:

1. **Global Configuration** (`config/global.yaml`) - System-wide defaults
2. **Site Profiles** (`config/site_profiles/*.yaml`) - Per-site translation rules
3. **Model Registry** (`config/model_registry.yaml`) - Available translation models
4. **Environment Variables** (`.env.production`) - Runtime configuration and secrets

Configuration Priority (highest to lowest):
1. Environment variables
2. Site profile settings
3. Global configuration
4. System defaults

---

## Global Configuration

### File Location

`config/global.yaml`

### Complete Schema

```yaml
# System identification
system:
  name: "Hugo Translation System"
  version: "1.0.0"
  environment: "production"  # development, staging, production

# Default Translation Memory settings (overridable per site)
tm_defaults:
  # Enable semantic (fuzzy) matching
  use_semantic_tm: true

  # Similarity threshold for semantic matches (0.0-1.0)
  # 0.80 = 80% similar
  semantic_threshold: 0.80

  # Fall back to exact-only matching if semantic TM unavailable
  fallback_exact_only: false

  # L1 in-memory cache size (number of entries)
  l1_cache_size: 10000

  # L2 persistent TM maximum size (MB)
  l2_max_size_mb: 1024

  # L3 semantic embedding model
  l3_embedding_model: "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"

  # L3 index type: Flat, IVFFlat, HNSW
  l3_index_type: "IVFFlat"

# Default model preferences
model_defaults:
  # Fallback model if none specified
  fallback_model: "m2m100_418m"

  # Device selection: auto, cpu, cuda, mps
  device: "auto"

  # Translation batch size
  batch_size: 32

  # Enable model caching
  cache_models: true

  # Maximum models to keep in memory
  max_cached_models: 2

# Orchestrator settings
orchestrator:
  # Mode: auto (watching + sweeps) or manual (on-demand only)
  mode: "auto"

  # Maximum concurrent workers
  max_workers: 4

  # Job queue backend: memory (default) or redis (distributed)
  job_queue_backend: "memory"

  # Full sweep interval (hours)
  sweep_interval_hours: 24

  # File watcher debounce (seconds)
  file_watcher_debounce_seconds: 2.0

  # Enable file watching
  enable_file_watcher: true

  # Enable periodic sweeps
  enable_sweep_scheduler: true

# Performance tuning
performance:
  # Enable parallel file translation
  parallel_translation: true

  # Maximum files to translate in parallel
  max_parallel_files: 8

  # Number of models to cache in memory
  model_cache_size: 2

  # Enable batch optimization
  enable_batch_optimization: true

# Observability configuration
observability:
  # Log level: DEBUG, INFO, WARNING, ERROR, CRITICAL
  log_level: "INFO"

  # Log format: text or json
  log_format: "json"

  # Flow artifact detail level:
  # - none: No artifacts
  # - summary: High-level statistics only
  # - sampled: Sample of segments (see sample_rate)
  # - full: All segments (verbose, for debugging)
  flow_artifact_detail: "summary"

  # Sample rate when flow_artifact_detail=sampled (0.0-1.0)
  flow_artifact_sample_rate: 0.05  # 5%

  # Enable Prometheus metrics
  metrics_enabled: true

  # Metrics server port
  metrics_port: 9090

  # Prometheus Pushgateway URL (optional)
  metrics_pushgateway: ""

# Default output layout
default_output_layout:
  # Use per-language folders
  per_language_folders: true

  # Output path pattern
  # Available variables: {lang}, {path}, {filename}, {ext}
  pattern: "{lang}/{path}"

# File system paths (can be overridden by environment variables)
paths:
  # Configuration directory
  config_dir: "./config"

  # Content root directory
  content_root: "./content"

  # Output directory for translations
  output_dir: "./output"

  # Model cache directory
  model_cache_dir: "./data/models"

  # Translation Memory data directory
  tm_data_dir: "./data/tm"

  # Flow artifacts directory
  artifacts_dir: "./data/artifacts"

  # Logs directory
  logs_dir: "./data/logs"

  # Backup directory
  backup_dir: "./backups"

# Validation settings
validation:
  # Enable validation
  enabled: true

  # Validation rules to apply
  rules:
    - placeholder_integrity
    - yaml_validity
    - structure_preservation
    - link_validity

  # Fail translation on validation errors
  strict_mode: false

# Security settings
security:
  # Enable input validation
  enable_input_validation: true

  # Maximum file size to process (MB)
  max_file_size_mb: 10

  # Allowed file extensions
  allowed_extensions:
    - ".md"
    - ".markdown"

  # Sanitize output
  sanitize_output: true

# Feature flags
features:
  # Enable parallel processing
  enable_parallel_processing: true

  # Enable semantic Translation Memory
  enable_semantic_tm: true

  # Enable model benchmarking tools
  enable_model_benchmarking: false

  # Enable automatic model selection
  enable_auto_model_selection: true

  # Enable quality scoring
  enable_quality_scoring: false
```

### Configuration Sections Explained

#### System Section

Identifies the system and environment:

```yaml
system:
  name: "Hugo Translation System"
  version: "1.0.0"
  environment: "production"  # Used for environment-specific behavior
```

#### TM Defaults Section

Controls Translation Memory behavior:

```yaml
tm_defaults:
  use_semantic_tm: true           # Enable fuzzy matching
  semantic_threshold: 0.80        # Require 80% similarity
  l1_cache_size: 10000           # Cache 10,000 recent translations
  l2_max_size_mb: 1024           # 1GB max persistent TM
  l3_embedding_model: "..."       # Model for semantic search
```

**Tuning Guidelines:**
- **semantic_threshold:**
  - `0.90+`: Very strict, fewer false positives
  - `0.80-0.90`: Balanced (recommended)
  - `0.70-0.80`: More lenient, may have false positives
  - `<0.70`: Too lenient, not recommended

- **l1_cache_size:**
  - Small sites (1k files): 5,000
  - Medium sites (10k files): 10,000
  - Large sites (100k+ files): 50,000+
  - Memory impact: ~100 bytes per entry

#### Model Defaults Section

Default model configuration:

```yaml
model_defaults:
  fallback_model: "m2m100_418m"  # Default if no model specified
  device: "auto"                 # auto-detect best device
  batch_size: 32                 # Larger = faster but more memory
  max_cached_models: 2           # Keep 2 models in memory
```

**Device Options:**
- `auto`: Automatically select best available device
- `cpu`: Force CPU usage
- `cuda`: Force NVIDIA GPU (if available)
- `mps`: Force Apple Metal (macOS only)

**Batch Size Guidelines:**
- CPU: 16-32
- GPU (8GB): 32-64
- GPU (16GB+): 64-128

#### Orchestrator Section

Controls job orchestration:

```yaml
orchestrator:
  mode: "auto"                    # auto or manual
  max_workers: 4                  # Concurrent workers
  sweep_interval_hours: 24        # How often to sweep all content
  file_watcher_debounce_seconds: 2.0  # Wait before processing changes
```

**Mode Selection:**
- `auto`: Continuous watching + periodic sweeps (production)
- `manual`: On-demand only (development, controlled environments)

---

## Site Profiles

### File Location

`config/site_profiles/<site-id>.yaml`

### Complete Site Profile Schema

```yaml
# Unique site identifier
site_id: "mysite"

# Description (optional)
description: "My Hugo blog"

# Content source directories
content_roots:
  - /data/content/mysite/en

# Source language
default_source_lang: en

# Target languages
target_langs:
  - fr
  - de
  - es
  - ja

# Frontmatter translation rules
frontmatter:
  # Field: { mode, [strategy], [options] }

  title:
    mode: translate
    # Translate the field value

  description:
    mode: translate

  slug:
    mode: computed
    strategy: slugify_title
    # Generate from translated title

  date:
    mode: passthrough
    # Copy as-is without translation

  draft:
    mode: passthrough

  author:
    mode: passthrough

  tags:
    mode: translate_list
    # Translate each item in the list

  categories:
    mode: translate_list

  layout:
    mode: passthrough

  type:
    mode: passthrough

  url:
    mode: computed
    strategy: from_slug

  aliases:
    mode: ignore
    # Do not include in output

  weight:
    mode: passthrough

  series:
    mode: translate_list

  menu:
    mode: copy_structure
    # Copy structure, translate nested strings

  params:
    mode: copy_structure
    translate_keys:
      - title
      - description
      - summary

# Body content translation rules
body:
  # Enable Markdown translation
  translate_markdown: true

  # Blocks to preserve (not translate)
  preserve_blocks:
    - code_blocks        # ```code```
    - inline_code        # `code`
    - fenced_mermaid     # ```mermaid
    - math_blocks        # $$math$$
    - html_comments      # <!-- comment -->

  # Patterns to preserve
  preserve_patterns:
    - "http://"
    - "https://"
    - "ftp://"
    - "{{"              # Hugo templates
    - "{{<"             # Hugo shortcodes
    - "{{%"             # Hugo shortcodes
    - "{{-"             # Hugo whitespace control
    - "{0}"             # Format placeholders
    - "{1}"
    - "\\$"             # LaTeX math

  # HTML handling
  translate_html: true
  preserve_html_tags: true

  # Tables
  translate_tables: true
  preserve_table_structure: true

  # Lists
  translate_lists: true

# Output configuration
output_layout:
  # Use per-language folders
  per_language_folders: true

  # Output path pattern
  # Variables: {lang}, {path}, {filename}, {ext}, {dir}
  pattern: "{lang}/{path}"

  # Alternative patterns:
  # pattern: "{path}.{lang}{ext}"           # file.fr.md
  # pattern: "{lang}/{dir}/{filename}.html" # Custom extension
  # pattern: "i18n/{lang}/{path}"           # Different root

# Translation Memory preferences (overrides global)
tm_prefs:
  # Enable semantic TM for this site
  use_semantic_tm: true

  # Similarity threshold
  semantic_threshold: 0.85

  # Fall back to exact-only if semantic unavailable
  fallback_exact_only: false

  # Domain-specific settings
  domain: "technical"  # Used for TM segmentation

# Model preferences (overrides global)
model_prefs:
  # Preferred model for this site
  preferred_model: "m2m100_1.2b"

  # Per-language-pair overrides
  lang_pair_models:
    en-fr: "opus_en_fr"      # Use specialized model
    en-de: "opus_en_de"
    en-ja: "m2m100_1.2b"     # Use larger model for difficult pairs

  # Model parameters
  batch_size: 64
  device: "cuda"

# Validation overrides
validation:
  # Additional site-specific validators
  custom_validators:
    - hugo_shortcode_balance
    - internal_link_resolution

  # Strict mode for this site
  strict_mode: true

# Site-specific features
features:
  # Enable draft translation
  translate_drafts: false

  # Preserve original files
  keep_originals: true

  # Generate translation report
  generate_report: true
```

### Frontmatter Mode Reference

| Mode | Description | Example |
|------|-------------|---------|
| `translate` | Translate the field value | `title: "Hello" -> "Bonjour"` |
| `passthrough` | Copy as-is | `date: 2024-01-01` (unchanged) |
| `computed` | Generate from another field | `slug: hello-world` (from title) |
| `translate_list` | Translate each list item | `tags: [tech, blog]` |
| `copy_structure` | Copy structure, translate strings | Complex nested objects |
| `ignore` | Omit from output | Field not included |

### Computed Strategies

| Strategy | Input | Output |
|----------|-------|--------|
| `slugify_title` | Translated title | URL-safe slug |
| `from_slug` | Slug | Full URL path |
| `translate_slug` | Original slug | Translated slug |
| `copy_from_source` | Source field | Copy source value |

---

## Model Registry

### File Location

`config/model_registry.yaml`

### Model Entry Schema

```yaml
models:
  - model_id: unique_identifier
    name: "Display Name"
    backend: huggingface | ctranslate2 | custom
    supported_pairs: all | [[src, tgt], ...]
    model_size_mb: 1600
    min_ram_gb: 4
    optimal_device: cpu | cuda | mps
    parameters: 418000000
    license: "MIT"
    hf_model_id: "org/model-name"  # For HuggingFace
    local_path: "/models/path"      # For local models
    description: "Model description"

    # Optional metadata
    quality_score: 0.85
    speed_score: 0.90
    recommended_for:
      - technical
      - general

    # Backend-specific config
    backend_config:
      compute_type: int8
      inter_threads: 4
      intra_threads: 4
```

### Example Models

```yaml
models:
  # Multilingual model (100 languages)
  - model_id: m2m100_418m
    name: "Facebook M2M100 (418M)"
    backend: huggingface
    supported_pairs: all
    model_size_mb: 1600
    min_ram_gb: 4
    optimal_device: cuda
    hf_model_id: facebook/m2m100_418M
    description: "Good all-around multilingual model"

  # CPU-optimized version
  - model_id: m2m100_418m_ct2
    name: "Facebook M2M100 (418M, CTranslate2)"
    backend: ctranslate2
    supported_pairs: all
    model_size_mb: 800
    min_ram_gb: 2
    optimal_device: cpu
    description: "2x faster, 50% less memory than HuggingFace version"

  # Specialized bilingual model
  - model_id: opus_en_fr
    name: "Opus-MT English-French"
    backend: huggingface
    supported_pairs:
      - ["en", "fr"]
      - ["fr", "en"]
    model_size_mb: 300
    min_ram_gb: 1
    optimal_device: cpu
    hf_model_id: Helsinki-NLP/opus-mt-en-fr
    description: "Fast, lightweight, high-quality for EN-FR"
```

### Supported Pairs Format

```yaml
# All language pairs supported
supported_pairs: all

# Specific pairs
supported_pairs:
  - ["en", "fr"]
  - ["en", "de"]
  - ["fr", "en"]

# One-way only
supported_pairs:
  - ["en", "fr"]  # EN to FR only
```

---

## Environment Variables

### Complete Reference

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| **System** |
| `ENVIRONMENT` | string | development | Environment name |
| `LOG_LEVEL` | string | INFO | Logging level |
| `FLOW_ARTIFACT_DETAIL` | string | summary | Flow artifact detail level |
| **Paths** |
| `CONFIG_PATH` | path | ./config | Configuration directory |
| `CONTENT_ROOT` | path | ./content | Content root directory |
| `TM_DATA_PATH` | path | ./data/tm | Translation Memory data |
| `MODEL_CACHE_PATH` | path | ./data/models | Model cache directory |
| `ARTIFACTS_PATH` | path | ./data/artifacts | Artifacts directory |
| `LOGS_PATH` | path | ./data/logs | Logs directory |
| **Translation Memory** |
| `TM_L1_CACHE_SIZE` | int | 10000 | L1 cache size |
| `TM_L2_MAX_SIZE_MB` | int | 1024 | L2 max size (MB) |
| `TM_L3_EMBEDDING_MODEL` | string | (see below) | Embedding model |
| `TM_SEMANTIC_THRESHOLD` | float | 0.80 | Similarity threshold |
| `TM_USE_SEMANTIC` | bool | true | Enable semantic TM |
| **Model Runtime** |
| `DEFAULT_MODEL` | string | m2m100_418m | Default model |
| `DEVICE` | string | auto | Compute device |
| `MODEL_BATCH_SIZE` | int | 32 | Translation batch size |
| `MAX_CACHED_MODELS` | int | 2 | Models to cache |
| **Orchestrator** |
| `ORCHESTRATOR_MODE` | string | manual | Orchestrator mode |
| `MAX_WORKERS` | int | 4 | Max concurrent workers |
| `SWEEP_INTERVAL_HOURS` | int | 24 | Sweep interval |
| `FILE_WATCHER_ENABLED` | bool | false | Enable file watching |
| **Performance** |
| `PARALLEL_TRANSLATION` | bool | true | Enable parallel processing |
| `MAX_PARALLEL_FILES` | int | 4 | Max parallel files |
| **Observability** |
| `METRICS_ENABLED` | bool | true | Enable metrics |
| `METRICS_PORT` | int | 9090 | Metrics server port |
| `PROMETHEUS_PUSHGATEWAY` | string | | Pushgateway URL |
| **Security** |
| `MAX_FILE_SIZE_MB` | int | 10 | Max file size |
| `ENABLE_INPUT_VALIDATION` | bool | true | Validate inputs |

### Environment Variable Priority

Configuration resolution order:

1. **Environment variable** (highest priority)
2. **Site profile** setting
3. **Global config** setting
4. **System default** (lowest priority)

Example:
```yaml
# global.yaml
tm_defaults:
  semantic_threshold: 0.80

# site_profiles/myblog.yaml
tm_prefs:
  semantic_threshold: 0.85

# .env
TM_SEMANTIC_THRESHOLD=0.90

# Result: 0.90 (from environment variable)
```

---

## Translation Memory Configuration

### L1 Cache Configuration

In-memory cache (fastest):

```yaml
tm_defaults:
  l1_cache_size: 10000  # Number of entries
```

**Memory usage:** ~100 bytes per entry
- 10,000 entries ≈ 1MB
- 100,000 entries ≈ 10MB

### L2 Persistent TM Configuration

LMDB-based persistent storage:

```yaml
tm_defaults:
  l2_max_size_mb: 1024  # 1GB max database size
```

**Storage guidelines:**
- Small sites (1k segments): 10MB
- Medium sites (100k segments): 100MB
- Large sites (1M+ segments): 1GB+

### L3 Semantic TM Configuration

Vector-based semantic search:

```yaml
tm_defaults:
  l3_embedding_model: "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
  l3_index_type: "IVFFlat"
  semantic_threshold: 0.80
```

**Embedding Model Options:**

| Model | Size | Speed | Quality | Languages |
|-------|------|-------|---------|-----------|
| `all-MiniLM-L6-v2` | 80MB | Fast | Good | English |
| `paraphrase-multilingual-mpnet-base-v2` | 420MB | Medium | Excellent | 50+ |
| `LaBSE` | 470MB | Slow | Excellent | 100+ |

**Index Type Options:**

| Type | Speed | Memory | Accuracy | Best For |
|------|-------|--------|----------|----------|
| `Flat` | Slow | High | Perfect | <10k entries |
| `IVFFlat` | Fast | Medium | ~95% | 10k-1M entries |
| `HNSW` | Very Fast | High | ~99% | 100k+ entries |

---

## Configuration Examples

### Example 1: Simple Blog

```yaml
# site_profiles/personal-blog.yaml
site_id: personal-blog
content_roots:
  - /content/blog
default_source_lang: en
target_langs:
  - fr
  - es

frontmatter:
  title: { mode: translate }
  description: { mode: translate }
  date: { mode: passthrough }
  tags: { mode: translate_list }

body:
  translate_markdown: true
  preserve_blocks:
    - code_blocks
  preserve_patterns:
    - "http://"

output_layout:
  per_language_folders: true
  pattern: "{lang}/{path}"

tm_prefs:
  use_semantic_tm: true
  semantic_threshold: 0.80
```

### Example 2: Technical Documentation

```yaml
# site_profiles/tech-docs.yaml
site_id: tech-docs
content_roots:
  - /content/docs
  - /content/api
default_source_lang: en
target_langs:
  - ja
  - de
  - zh

frontmatter:
  title: { mode: translate }
  description: { mode: translate }
  weight: { mode: passthrough }
  api_version: { mode: passthrough }
  code_samples: { mode: ignore }

body:
  translate_markdown: true
  preserve_blocks:
    - code_blocks
    - inline_code
    - fenced_mermaid
  preserve_patterns:
    - "http://"
    - "API_"
    - "{{<"

output_layout:
  per_language_folders: true
  pattern: "{lang}/docs/{path}"

tm_prefs:
  use_semantic_tm: true
  semantic_threshold: 0.85
  domain: "technical"

model_prefs:
  preferred_model: "m2m100_1.2b"
  lang_pair_models:
    en-ja: "m2m100_1.2b"
  batch_size: 64
```

### Example 3: E-commerce Site

```yaml
# site_profiles/shop.yaml
site_id: shop
content_roots:
  - /content/products
  - /content/blog
default_source_lang: en
target_langs:
  - fr
  - de
  - es
  - it

frontmatter:
  title: { mode: translate }
  description: { mode: translate }
  price: { mode: passthrough }
  sku: { mode: passthrough }
  categories: { mode: translate_list }
  features: { mode: translate_list }
  specs:
    mode: copy_structure
    translate_keys:
      - description
      - details

body:
  translate_markdown: true
  translate_html: true

output_layout:
  per_language_folders: true
  pattern: "{lang}/{path}"

tm_prefs:
  use_semantic_tm: true
  semantic_threshold: 0.80
  domain: "ecommerce"

validation:
  strict_mode: true
  custom_validators:
    - product_field_completeness
```

---

## Validation and Best Practices

### Configuration Validation

Validate configuration before deployment:

```bash
# Validate global config
python -c "
from pathlib import Path
from src.utils.config_loader import ConfigService

config = ConfigService(Path('config'))
print('✓ Configuration valid')
"

# Validate specific site profile
python -c "
from pathlib import Path
from src.utils.config_loader import ConfigService

config = ConfigService(Path('config'))
profile = config.get_site_profile('mysite')
assert profile is not None
print('✓ Site profile valid')
"
```

### Best Practices

1. **Start Simple:**
   ```yaml
   # Begin with basic configuration
   frontmatter:
     title: { mode: translate }
     date: { mode: passthrough }

   # Add complexity incrementally
   ```

2. **Use Semantic TM:**
   ```yaml
   tm_prefs:
     use_semantic_tm: true
     semantic_threshold: 0.80  # Good starting point
   ```

3. **Configure Per Environment:**
   ```yaml
   # Development
   observability:
     log_level: DEBUG
     flow_artifact_detail: full

   # Production
   observability:
     log_level: INFO
     flow_artifact_detail: summary
   ```

4. **Document Site Profiles:**
   ```yaml
   # Add comments explaining decisions
   site_id: mysite
   description: "Corporate blog - technical content"

   frontmatter:
     # Don't translate author names
     author: { mode: passthrough }

     # Compute slugs from translated titles
     slug: { mode: computed, strategy: slugify_title }
   ```

5. **Version Configuration:**
   ```bash
   # Track configuration in git
   git add config/
   git commit -m "Update site profile for X"
   ```

### Common Mistakes

1. **Wrong mode for lists:**
   ```yaml
   # WRONG
   tags: { mode: translate }

   # CORRECT
   tags: { mode: translate_list }
   ```

2. **Forgetting to preserve Hugo syntax:**
   ```yaml
   # WRONG
   preserve_patterns:
     - "http://"

   # CORRECT
   preserve_patterns:
     - "http://"
     - "{{<"   # Hugo shortcodes
     - "{{%"
   ```

3. **Semantic threshold too high:**
   ```yaml
   # May miss good matches
   semantic_threshold: 0.95

   # Better starting point
   semantic_threshold: 0.80
   ```

4. **Not considering output structure:**
   ```yaml
   # May conflict with Hugo's i18n
   pattern: "{lang}/{path}"

   # Verify with Hugo's expected structure
   ```

---

## Troubleshooting Configuration

### Verify Configuration Loading

```python
from pathlib import Path
from src.utils.config_loader import ConfigService

config = ConfigService(Path('config'))

# List all sites
sites = config.list_sites()
print(f"Sites: {sites}")

# Get site profile
profile = config.get_site_profile('mysite')
print(f"Target languages: {profile.target_langs}")

# Check global settings
print(f"TM threshold: {config.global_config.tm_defaults.semantic_threshold}")
```

### Common Issues

**Configuration not found:**
```bash
# Check file exists
ls -l config/global.yaml
ls -l config/site_profiles/mysite.yaml

# Check permissions
chmod 644 config/*.yaml
```

**Invalid YAML:**
```bash
# Validate YAML syntax
python -c "import yaml; yaml.safe_load(open('config/global.yaml'))"
```

**Environment variable not applied:**
```bash
# Verify environment variable is set
echo $TM_SEMANTIC_THRESHOLD

# Check loading order
export DEBUG=1
python -m src.orchestrator.orchestrator
```

---

## Next Steps

- See [User Guide](USER_GUIDE.md) for usage examples
- Review [Deployment Guide](DEPLOYMENT.md) for production setup
- Check [Operations Manual](OPERATIONS.md) for maintenance

---

**Documentation Version:** 1.0.0
**Last Updated:** 2025-11-21
