# Hugo Translation System - User Guide

**Version:** 1.0.0
**Last Updated:** 2025-11-21

---

## Table of Contents

1. [Introduction](#introduction)
2. [Installation and Setup](#installation-and-setup)
3. [Configuration](#configuration)
4. [Basic Usage](#basic-usage)
5. [Advanced Features](#advanced-features)
6. [Translation Memory Management](#translation-memory-management)
7. [Best Practices](#best-practices)
8. [Troubleshooting](#troubleshooting)

---

## Introduction

The Hugo Translation System is a production-ready translation platform designed specifically for Hugo static sites. It provides:

- **Multi-layer Translation Memory** with exact and semantic matching
- **Multi-model support** (HuggingFace, CTranslate2) with automatic hardware detection
- **Intelligent segmentation** preserving Hugo shortcodes, templates, and formatting
- **Automatic and manual translation modes** for flexible workflows
- **Full observability** with structured logging and metrics

### Key Features

- 3-layer Translation Memory (L1 cache + L2 LMDB + L3 semantic search)
- Support for multiple Hugo sites with different frontmatter schemas
- Parallel processing for high-throughput translation
- Docker-based deployment with container orchestration
- MCP server for programmatic access
- Production-grade validation and error handling

---

## Installation and Setup

### System Requirements

**Minimum:**
- CPU: 4+ cores
- RAM: 8GB
- Storage: 20GB for models and TM data
- OS: Linux, macOS, or Windows with WSL2

**Recommended:**
- CPU: 8+ cores
- RAM: 16GB+
- GPU: NVIDIA GPU with CUDA 11.0+ (optional but recommended)
- Storage: 50GB+ SSD

### Installation Methods

#### Method 1: Docker Deployment (Recommended)

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd hugo-translator
   ```

2. **Create environment configuration:**
   ```bash
   cp .env.example .env.production
   ```

3. **Edit `.env.production`** with your settings (see [Configuration](#configuration))

4. **Start services:**
   ```bash
   # CPU-only deployment
   docker-compose up -d

   # With GPU support
   docker-compose --profile gpu up -d

   # With monitoring (Grafana)
   docker-compose --profile gpu --profile monitoring up -d
   ```

5. **Verify deployment:**
   ```bash
   docker-compose ps
   # All services should show "Up (healthy)"

   docker-compose logs orchestrator
   # Check for "Orchestrator started successfully"
   ```

#### Method 2: Local Development Setup

1. **Create virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. **Install dependencies:**
   ```bash
   # For CPU-only
   pip install -r requirements/cpu.txt

   # For GPU support
   pip install -r requirements/gpu.txt
   ```

3. **Set up configuration:**
   ```bash
   cp .env.example .env
   # Edit .env with your settings
   ```

4. **Initialize data directories:**
   ```bash
   mkdir -p data/tm data/models data/artifacts data/logs
   ```

### Post-Installation Verification

1. **Test configuration loading:**
   ```python
   from pathlib import Path
   from src.utils.config_loader import ConfigService

   config = ConfigService(Path('config'))
   sites = config.list_sites()
   print(f"Available sites: {sites}")
   ```

2. **Check hardware detection:**
   ```python
   from src.model_runtime.hardware import HardwareDetector

   detector = HardwareDetector()
   hw_info = detector.detect()
   print(f"Detected device: {hw_info.recommended_device}")
   print(f"Available RAM: {hw_info.total_ram_gb}GB")
   ```

3. **Verify model registry:**
   ```python
   from pathlib import Path
   from src.model_runtime.registry import ModelRegistry

   registry = ModelRegistry(Path('config/model_registry.yaml'))
   models = registry.list_models()
   print(f"Available models: {len(models)}")
   ```

---

## Configuration

### Site Profiles

Site profiles define how each Hugo site should be translated. Create a profile in `config/site_profiles/<site-id>.yaml`:

```yaml
# config/site_profiles/myblog.yaml
site_id: myblog
content_roots:
  - /data/content/myblog

default_source_lang: en
target_langs:
  - fr
  - de
  - es

# Frontmatter translation rules
frontmatter:
  title:
    mode: translate
  description:
    mode: translate
  slug:
    mode: computed
    strategy: slugify_title
  date:
    mode: passthrough
  draft:
    mode: passthrough
  tags:
    mode: translate_list
  categories:
    mode: translate_list

# Body content rules
body:
  translate_markdown: true
  preserve_blocks:
    - code_blocks
    - inline_code
    - fenced_mermaid
  preserve_patterns:
    - "http://"
    - "https://"
    - "{{"  # Hugo templates

# Output configuration
output_layout:
  per_language_folders: true
  pattern: "{lang}/{path}"

# Translation Memory preferences
tm_prefs:
  use_semantic_tm: true
  semantic_threshold: 0.80
  fallback_exact_only: false
```

### Global Configuration

Edit `config/global.yaml` for system-wide settings:

```yaml
# TM settings
tm_defaults:
  use_semantic_tm: true
  semantic_threshold: 0.80
  l1_cache_size: 10000
  l2_max_size_mb: 1024

# Model settings
model_defaults:
  fallback_model: "m2m100_418m"
  device: "auto"  # auto, cpu, cuda, mps
  batch_size: 32

# Performance
performance:
  parallel_translation: true
  max_parallel_files: 8

# Observability
observability:
  log_level: "INFO"
  flow_artifact_detail: "summary"
```

### Environment Variables

Create `.env.production` from `.env.example`:

```bash
# Essential settings
ENVIRONMENT=production
LOG_LEVEL=INFO

# Paths
CONFIG_PATH=/app/config
CONTENT_ROOT=/data/content
TM_DATA_PATH=/data/tm
MODEL_CACHE_PATH=/data/models

# Translation Memory
TM_SEMANTIC_THRESHOLD=0.80
TM_L1_CACHE_SIZE=10000

# Model
DEFAULT_MODEL=m2m100_418m
DEVICE=auto
MODEL_BATCH_SIZE=32

# Orchestrator
ORCHESTRATOR_MODE=auto
MAX_WORKERS=4
FILE_WATCHER_ENABLED=true

# Metrics
METRICS_ENABLED=true
METRICS_PORT=9090
```

---

## Basic Usage

### Translating a Single File

**Using Docker:**
```bash
docker-compose exec orchestrator python -c "
from pathlib import Path
from src.translation_engine.engine import TranslationEngine
from src.utils.config_loader import ConfigService
from src.tm.translation_memory import create_translation_memory
from src.model_runtime.loader import create_model_loader

config = ConfigService(Path('/app/config'))
tm = create_translation_memory(Path('/data/tm'))
loader = create_model_loader(Path('/app/config'))
engine = TranslationEngine(config, tm, loader)

result = engine.translate_file(
    site_id='myblog',
    file_path=Path('/data/content/myblog/post.md'),
    target_langs=['fr', 'es']
)

print(f'Success: {result.success}')
print(f'Translations: {result.outputs}')
"
```

**Python API:**
```python
from pathlib import Path
from src.translation_engine.engine import TranslationEngine
from src.utils.config_loader import ConfigService
from src.tm.translation_memory import create_translation_memory
from src.model_runtime.loader import create_model_loader

# Initialize components
config = ConfigService(Path('config'))
tm = create_translation_memory(Path('data/tm'))
loader = create_model_loader(Path('config'))
engine = TranslationEngine(config, tm, loader)

# Translate file
result = engine.translate_file(
    site_id='myblog',
    file_path=Path('content/myblog/posts/hello-world.md'),
    target_langs=['fr', 'de', 'es']
)

# Check results
if result.success:
    for lang, output_path in result.outputs.items():
        print(f"{lang}: {output_path}")
    print(f"Stats: {result.stats.segments_translated} segments")
else:
    print(f"Errors: {result.errors}")
```

### Translating a Directory

**Sequential processing:**
```python
result = engine.translate_directory(
    site_id='myblog',
    directory=Path('content/myblog/posts'),
    target_langs=['fr', 'es'],
    recursive=True,
    parallel=False
)

print(f"Files translated: {result.files_translated}")
print(f"Total time: {result.total_time_seconds}s")
```

**Parallel processing (faster):**
```python
result = engine.translate_directory(
    site_id='myblog',
    directory=Path('content/myblog/posts'),
    target_langs=['fr', 'es'],
    recursive=True,
    parallel=True,
    max_workers=4
)

print(f"Files translated: {result.files_translated}")
print(f"Speedup: {result.files_translated / result.total_time_seconds:.2f} files/sec")
```

### MCP Server Usage

The translation worker exposes MCP tools for programmatic access:

```python
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def translate_via_mcp():
    server_params = StdioServerParameters(
        command="python",
        args=["-m", "src.workers.translation_worker"]
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Initialize
            await session.initialize()

            # Translate file
            result = await session.call_tool(
                "translate_hugo_file",
                arguments={
                    "site_id": "myblog",
                    "file_path": "/data/content/myblog/post.md",
                    "target_langs": ["fr", "es"]
                }
            )

            print(result)

asyncio.run(translate_via_mcp())
```

---

## Advanced Features

### Parallel Processing

For large translation jobs, enable parallel processing:

```python
# Configure in global.yaml
performance:
  parallel_translation: true
  max_parallel_files: 8

# Or override programmatically
result = engine.translate_directory(
    site_id='myblog',
    directory=Path('content/myblog'),
    target_langs=['fr', 'es'],
    parallel=True,
    max_workers=8  # Adjust based on CPU cores
)
```

**Performance tips:**
- Start with `max_workers = cpu_count - 1`
- Monitor memory usage with many workers
- GPU models may not benefit from high parallelism
- Use parallel processing for 10+ files

### Semantic Translation Memory

Semantic TM finds similar translations even when exact matches don't exist:

```python
# Enable in site profile
tm_prefs:
  use_semantic_tm: true
  semantic_threshold: 0.80  # 80% similarity required

# Query semantic TM
from src.tm.translation_memory import create_translation_memory

tm = create_translation_memory(Path('data/tm'))

# Find similar translations
candidates = tm.semantic_lookup(
    site_id='myblog',
    src_lang='en',
    tgt_lang='fr',
    text='Convert Excel to PDF',
    threshold=0.80,
    limit=5
)

for candidate in candidates:
    print(f"Similarity: {candidate.similarity:.2f}")
    print(f"Source: {candidate.source}")
    print(f"Translation: {candidate.target}")
```

### Custom Model Selection

Choose specific models per language pair:

```python
from src.model_runtime.loader import ModelLoader
from src.model_runtime.registry import ModelRegistry

registry = ModelRegistry(Path('config/model_registry.yaml'))
loader = ModelLoader(registry, device='cuda')

# Load specific model
model = loader.load_model('nllb_200_600m')

# Translate with specific model
result = engine.translate_file(
    site_id='myblog',
    file_path=Path('content/post.md'),
    target_langs=['fr'],
    model_override='nllb_200_600m'
)
```

### Automatic Mode (File Watching)

Start the orchestrator in auto mode to watch for file changes:

```bash
# Via Docker
docker-compose up -d

# Via Python
python -m src.orchestrator.orchestrator --mode auto
```

**Auto mode features:**
- Watches configured content directories
- Automatically translates new/modified files
- Performs periodic full sweeps
- Maintains translation currency

**Configuration:**
```yaml
# config/global.yaml
orchestrator:
  mode: "auto"
  sweep_interval_hours: 24
  file_watcher_debounce_seconds: 2.0
  enable_file_watcher: true
  enable_sweep_scheduler: true
```

### Validation and Quality Checks

Enable comprehensive validation:

```python
# Configure validation
validation:
  enabled: true
  rules:
    - placeholder_integrity
    - yaml_validity
    - structure_preservation
    - link_validity
  strict_mode: false  # Set true to fail on warnings

# Check translation quality
result = engine.translate_file(...)

for issue in result.validation_issues:
    print(f"{issue.severity}: {issue.message}")
    print(f"  Location: {issue.location}")
```

---

## Translation Memory Management

### Viewing TM Statistics

```python
from src.observability.tm_admin import TranslationMemoryAdmin

admin = TranslationMemoryAdmin(tm)

# Get overall stats
stats = admin.get_statistics()
print(f"Total entries: {stats.total_entries}")
print(f"L1 hit rate: {stats.l1_hit_rate:.2%}")
print(f"L2 hit rate: {stats.l2_hit_rate:.2%}")
print(f"L3 hit rate: {stats.l3_hit_rate:.2%}")

# Per-site stats
site_stats = admin.get_site_statistics('myblog')
print(f"Site entries: {site_stats.entry_count}")
```

### Exporting TM Data

Export TM for review or backup:

```bash
# Via CLI
tm-admin dump-site --site myblog --out myblog-tm.ndjson

# Via Python
admin.dump_site('myblog', Path('backups/myblog-tm.ndjson'))
```

### Cleaning TM Data

Remove old or unused entries:

```python
# Remove entries older than 90 days with no recent use
admin.cleanup(
    max_age_days=90,
    min_usage_count=1,
    dry_run=False
)

# Remove duplicates
admin.deduplicate(site_id='myblog')
```

### TM Lookups

**Exact lookup:**
```python
translation = tm.lookup(
    site_id='myblog',
    src_lang='en',
    tgt_lang='fr',
    text='Hello World'
)
print(translation)  # "Bonjour le monde" or None
```

**Semantic lookup:**
```python
candidates = tm.semantic_lookup(
    site_id='myblog',
    src_lang='en',
    tgt_lang='fr',
    text='Hello everyone',
    threshold=0.75,
    limit=5
)

for c in candidates:
    print(f"{c.similarity:.2f}: {c.source} -> {c.target}")
```

---

## Best Practices

### Site Profile Configuration

1. **Start conservative:**
   - Begin with `passthrough` for unknown frontmatter keys
   - Add translation rules incrementally
   - Test with small batches first

2. **Preserve critical elements:**
   - Always preserve Hugo shortcodes: `{{<` and `{{%`
   - Protect URLs and links
   - Keep code blocks intact

3. **Use computed fields wisely:**
   ```yaml
   frontmatter:
     slug:
       mode: computed
       strategy: slugify_title  # Auto-generate from translated title
   ```

### Performance Optimization

1. **Enable semantic TM:**
   - Reduces model calls by 30-50%
   - Set threshold between 0.75-0.85
   - Monitor false positives

2. **Use appropriate models:**
   - Small sites: `opus_en_*` (fast, language-specific)
   - Medium sites: `m2m100_418m` (balanced)
   - Large sites with GPU: `m2m100_1.2b` or `nllb_200_1.3b`

3. **Batch processing:**
   ```python
   # Process multiple directories
   for directory in content_dirs:
       engine.translate_directory(
           site_id='myblog',
           directory=directory,
           target_langs=['fr'],
           parallel=True,
           max_workers=4
       )
   ```

### TM Management

1. **Regular backups:**
   ```bash
   # Daily TM backups
   tm-admin dump-site --site myblog --out backups/tm-$(date +%Y%m%d).ndjson
   ```

2. **Monitor hit rates:**
   - Target: >50% TM hit rate after initial population
   - Low hit rate may indicate:
     - Content too diverse
     - Semantic threshold too high
     - TM not populated

3. **Periodic cleanup:**
   ```bash
   # Monthly cleanup
   tm-admin cleanup --max-age-days 90 --min-usage 2
   ```

### Error Handling

1. **Check results:**
   ```python
   result = engine.translate_file(...)

   if not result.success:
       for error in result.errors:
           logger.error(f"Translation error: {error}")
       # Handle failure
   ```

2. **Enable detailed logging:**
   ```yaml
   observability:
     log_level: "DEBUG"
     flow_artifact_detail: "full"
   ```

3. **Monitor validation issues:**
   ```python
   for issue in result.validation_issues:
       if issue.severity == 'error':
           # Critical issue - investigate
           logger.error(issue)
   ```

---

## Troubleshooting

### Common Issues

#### Model Loading Failures

**Symptom:** `ModelLoadError: Failed to load model`

**Solutions:**
1. Check model exists in registry:
   ```python
   registry.list_models()
   ```

2. Verify model files downloaded:
   ```bash
   ls -lh data/models/
   ```

3. Check memory availability:
   ```python
   hw_info = HardwareDetector().detect()
   print(f"Available RAM: {hw_info.total_ram_gb}GB")
   ```

#### Low TM Hit Rate

**Symptom:** TM hit rate <20%

**Solutions:**
1. Check semantic TM enabled:
   ```yaml
   tm_prefs:
     use_semantic_tm: true
   ```

2. Lower semantic threshold:
   ```yaml
   tm_prefs:
     semantic_threshold: 0.75  # Try lower
   ```

3. Populate TM with existing translations

#### Translation Quality Issues

**Symptom:** Poor translation quality

**Solutions:**
1. Try larger model:
   ```yaml
   model_defaults:
     fallback_model: "m2m100_1.2b"
   ```

2. Check language pair supported:
   ```python
   model_info = registry.get_model('m2m100_418m')
   print(model_info.supported_pairs)
   ```

3. Review validation issues:
   ```python
   for issue in result.validation_issues:
       print(issue)
   ```

#### Performance Problems

**Symptom:** Slow translation speed

**Solutions:**
1. Enable parallel processing:
   ```python
   result = engine.translate_directory(..., parallel=True)
   ```

2. Use GPU if available:
   ```yaml
   model_defaults:
     device: "cuda"
   ```

3. Use CTranslate2 models (faster):
   ```yaml
   model_defaults:
     fallback_model: "m2m100_418m_ct2"
   ```

### Getting Help

1. **Check logs:**
   ```bash
   # Docker
   docker-compose logs orchestrator
   docker-compose logs worker-cpu-1

   # Local
   tail -f data/logs/translation.log
   ```

2. **Enable debug mode:**
   ```yaml
   observability:
     log_level: "DEBUG"
     flow_artifact_detail: "full"
   ```

3. **Review metrics:**
   ```bash
   # Access Prometheus
   open http://localhost:9090

   # View Grafana dashboard
   open http://localhost:3000
   ```

4. **Test individual components:**
   ```bash
   # Run test suite
   pytest tests/ -v

   # Test specific component
   pytest tests/unit/test_translation_engine.py -v
   ```

---

## Next Steps

- Review [Configuration Reference](CONFIGURATION.md) for detailed settings
- See [Deployment Guide](DEPLOYMENT.md) for production deployment
- Check [Operations Manual](OPERATIONS.md) for ongoing maintenance
- Consult [Troubleshooting Guide](TROUBLESHOOTING.md) for detailed problem solving

---

**Documentation Version:** 1.0.0
**Last Updated:** 2025-11-21
