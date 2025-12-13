# Hugo Translation System - User Guide

**Version**: 1.0.0
**Last Updated**: 2025-11-19

## Table of Contents

1. [Introduction](#introduction)
2. [Quick Start](#quick-start)
3. [Configuration](#configuration)
4. [Translation Modes](#translation-modes)
5. [Translation Memory](#translation-memory)
6. [Monitoring and Logging](#monitoring-and-logging)
7. [Troubleshooting](#troubleshooting)
8. [Best Practices](#best-practices)

## Introduction

The Hugo Translation System is a comprehensive multi-site translation solution designed for Hugo static sites. It provides:

- **Multi-site support** with per-site configuration
- **3-layer Translation Memory** for optimal performance
- **Auto and manual translation modes**
- **Comprehensive logging and monitoring**
- **High-quality neural machine translation**

### Key Features

✅ **Intelligent Translation Memory**
- L1 in-memory cache for instant lookups
- L2 persistent storage for cross-session reuse
- L3 semantic matching for similar phrases

✅ **Flexible Translation Modes**
- Auto mode: Watches files and translates automatically
- Manual mode: Translate on-demand
- Sweep mode: Batch process entire site

✅ **Production Ready**
- 348+ tests with 80% coverage
- Thread-safe operations
- Comprehensive error handling

## Quick Start

###Installation

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd hugo-translator
   ```

2. **Create virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   # For CPU-only (recommended for development)
   pip install -r requirements/cpu.txt

   # For GPU support (production)
   pip install -r requirements/gpu.txt

   # For development
   pip install -r requirements/dev.txt
   ```

4. **Configure environment**:
   ```bash
   cp .env.example .env
   # Edit .env with your settings
   ```

### First Translation

1. **Create a site profile** in `config/site_profiles/mysite.yaml`:

```yaml
site_id: mysite.example.com
content_roots:
  - /path/to/hugo/content
default_source_lang: en
target_langs: [fr, es, de]

frontmatter:
  title:
    mode: translate
  description:
    mode: translate

body:
  translate_markdown: true
  preserve_blocks:
    - block_code
    - codespan
  preserve_patterns: []
  placeholder_syntax:
    - "{{"

output_layout:
  per_language_folders: true
  pattern: "/{lang}/{relative_path}"

tm_prefs:
  use_semantic_tm: true
  fallback_exact_only: false
```

2. **Run a manual translation**:

```python
from pathlib import Path
from src.utils.config_loader import ConfigService
from src.tm.l1_cache import L1Cache
from src.tm.l2_persistent import L2PersistentTM
from src.tm.translation_memory import TranslationMemory
from src.model_runtime.registry import ModelRegistry
from src.model_runtime.loader import ModelLoader
from src.translation_engine.engine import TranslationEngine

# Initialize components
config_service = ConfigService(Path("config"))
l1_cache = L1Cache(max_size=10000)
l2_tm = L2PersistentTM(Path("data/tm.lmdb"))
tm = TranslationMemory(l1_cache, l2_tm)

registry = ModelRegistry(Path("config/model_registry.yaml"))
model_loader = ModelLoader(registry, device="cpu")

engine = TranslationEngine(config_service, tm, model_loader)

# Translate a file
result = engine.translate_file(
    site_id="mysite.example.com",
    file_path=Path("/path/to/content/blog/post.md"),
    target_langs=["fr", "es"]
)

print(f"Translated {result.stats.total_segments} segments")
print(f"TM hit rate: {result.stats.tm_hits / result.stats.total_segments * 100:.1f}%")
```

## Configuration

### Site Profile Structure

Site profiles define how each site should be translated. They are YAML files stored in `config/site_profiles/`.

#### Basic Configuration

```yaml
site_id: example.com      # Unique site identifier
content_roots:             # Hugo content directories
  - /path/to/content
default_source_lang: en    # Source language code
target_langs: [fr, es, de] # Target language codes
```

#### Frontmatter Rules

Control how frontmatter fields are translated:

```yaml
frontmatter:
  title:
    mode: translate      # Translate this field
  slug:
    mode: passthrough    # Copy as-is
  author:
    mode: passthrough    # Don't translate names
  tags:
    mode: translate_list # Translate each list item
```

**Modes**:
- `translate`: Translate the field
- `passthrough`: Copy original value
- `translate_list`: Translate each item in a list
- `computed`: Apply custom strategy (e.g., slug generation)

#### Body Rules

Control Markdown body translation:

```yaml
body:
  translate_markdown: true
  preserve_blocks:        # Don't translate these nodes
    - block_code
    - codespan
    - html_inline
  preserve_patterns:      # Regex patterns to protect
    - "https?://[^\s]+"   # URLs
    - "{{.*?}}"           # Hugo shortcodes
  placeholder_syntax:     # Shortcode delimiters
    - "{{"
    - "{%"
```

#### Output Layout

Configure where translations are saved:

```yaml
output_layout:
  per_language_folders: true  # Use /lang/path structure
  pattern: "/{lang}/{relative_path}"  # Output path pattern
```

#### Translation Memory Preferences

Configure TM behavior:

```yaml
tm_prefs:
  use_semantic_tm: true        # Enable semantic matching
  fallback_exact_only: false   # Allow fuzzy matches
  min_confidence: 0.75         # Minimum semantic similarity
```

### Model Configuration

Models are defined in `config/model_registry.yaml`:

```yaml
models:
  - model_id: m2m100_418m
    name: "Facebook M2M100 (418M)"
    backend: huggingface
    supported_pairs: all  # Supports all language pairs
    model_size_mb: 1600
    min_ram_gb: 4
    optimal_device: cuda
    parameters: 418000000
    license: MIT
    local_path: null  # Downloads from HuggingFace

  - model_id: m2m100_418m_ct2
    name: "Facebook M2M100 (CTranslate2)"
    backend: ctranslate2
    supported_pairs: all
    model_size_mb: 800
    min_ram_gb: 2
    optimal_device: cpu
    parameters: 418000000
    license: MIT
    local_path: /path/to/ct2/model
```

## Translation Modes

### Auto Mode

Watches content directories and translates files automatically when they change.

**Setup**:

```python
from src.orchestrator.orchestrator import TranslationOrchestrator

orchestrator = TranslationOrchestrator(
    config_service=config_service,
    enable_file_watcher=True,
    enable_sweep_scheduler=True,
    sweep_interval_minutes=60
)

# Start in auto mode
orchestrator.start()

# System now watches for file changes and translates automatically
```

**Configuration**:
- **Debounce time**: Default 2 seconds (adjustable)
- **Priority**: Auto jobs have priority 3 (higher than manual)
- **File types**: Only `.md` and `.markdown` files

### Manual Mode

Translate files on-demand via API calls.

**Single File**:

```python
result = engine.translate_file(
    site_id="example.com",
    file_path=Path("content/blog/post.md"),
    target_langs=["fr", "es"],
    force=False  # Use TM if available
)
```

**Directory**:

```python
result = engine.translate_directory(
    site_id="example.com",
    directory=Path("content/blog"),
    target_langs=["fr", "es"],
    recursive=True,
    parallel=True  # Use multiple workers
)
```

### Sweep Mode

Periodically scan entire site for untranslated or outdated content.

**Trigger Manual Sweep**:

```python
orchestrator.scheduler.trigger_sweep(site_id="example.com")
```

**Configuration**:
- **Interval**: Default 60 minutes
- **Batch size**: 50 files per job
- **Priority**: Sweep jobs have priority 7 (lower than auto/manual)

## Translation Memory

### Overview

The 3-layer TM provides optimal balance between speed and quality:

1. **L1 Cache**: In-memory LRU cache (~1µs lookups)
2. **L2 Persistent**: LMDB database (~1ms lookups)
3. **L3 Semantic**: Vector search (~100ms lookups)

### TM Lookup Flow

```
Text to translate
    ↓
[L1 Cache] → Hit? → Return translation (99% of repeated text)
    ↓ Miss
[L2 Exact] → Hit? → Return translation (70-80% of similar text)
    ↓ Miss
[L3 Semantic] → Match > threshold? → Return best match (60-70% fuzzy)
    ↓ No match
[Model Translation] → Translate with NMT → Store in all layers
```

### Configuration

**L1 Cache**:
```python
l1_cache = L1Cache(
    max_size=10000  # Maximum cached translations
)
```

**L2 Persistent**:
```python
l2_tm = L2PersistentTM(
    db_path=Path("data/tm.lmdb"),
    max_size_mb=1024  # Maximum database size
)
```

**L3 Semantic**:
```python
l3_tm = L3SemanticTM(
    index_path=Path("data/semantic.index"),
    embedding_model="all-MiniLM-L6-v2",
    threshold=0.75  # Minimum similarity
)
```

### TM Statistics

```python
from src.observability.tm_admin import TranslationMemoryAdmin

admin = TranslationMemoryAdmin(tm)
stats = admin.get_stats()

print(f"Total entries: {stats['total_entries']}")
print(f"L1 hit rate: {stats['l1_cache_stats']['hit_rate']:.1f}%")
print(f"L2 size: {stats['l2_size']} entries")
```

## Monitoring and Logging

### Structured Logging

The system uses structured JSON logging for all operations.

**Setup**:

```python
from src.observability.logger import setup_structured_logging, get_logger

# Configure logging
setup_structured_logging(
    log_level="INFO",
    log_file=Path("logs/translation.log"),
    console_output=True
)

logger = get_logger("my_app")

# Logging is automatic for all operations
# Logs include: job lifecycle, TM hits, errors, etc.
```

**Log Example**:

```json
{
  "type": "job_completed",
  "timestamp": "2025-11-19T10:30:45.123Z",
  "job_id": "job_001",
  "site_id": "example.com",
  "success": true,
  "total_segments": 150,
  "tm_hits": 105,
  "tm_hit_rate": 70.0,
  "duration_seconds": 45.2
}
```

### Flow Artifacts

Enable detailed per-job artifacts for debugging:

```python
from src.observability.flow_artifacts import FlowArtifactWriter, DetailLevel

artifact_writer = FlowArtifactWriter(
    artifacts_dir=Path("artifacts"),
    detail_level=DetailLevel.FULL  # NONE, SUMMARY, SAMPLED, FULL
)

# Artifacts are written automatically during translation
# Each job creates a file: artifacts/job_<id>.ndjson
```

### Metrics

Track system performance:

- **Translation throughput**: Segments per second
- **TM hit rates**: L1/L2/L3 effectiveness
- **Job queue depth**: Pending work
- **Model performance**: Translation speed per model

## Troubleshooting

### Common Issues

#### Low TM Hit Rate

**Problem**: TM hit rate below 50%

**Solutions**:
1. Enable semantic TM (`use_semantic_tm: true`)
2. Lower similarity threshold (try 0.70 instead of 0.80)
3. Check text normalization settings
4. Verify site_id matches across sessions

#### Slow Translation

**Problem**: Translation takes too long

**Solutions**:
1. Use CTranslate2 backend (2-5x faster on CPU)
2. Enable GPU if available
3. Increase batch size for directory translation
4. Check model size vs available RAM

#### Memory Issues

**Problem**: System runs out of memory

**Solutions**:
1. Reduce L1 cache size
2. Use smaller model (e.g., 418M instead of 1.2B)
3. Limit LMDB database size
4. Process files in smaller batches

#### File Watcher Not Working

**Problem**: Auto mode doesn't detect changes

**Solutions**:
1. Check content_roots paths in site profile
2. Verify watchdog is installed
3. Check file permissions
4. Look for errors in logs
5. Try increasing debounce time

### Debug Mode

Enable detailed logging:

```python
setup_structured_logging(log_level="DEBUG")
```

Check logs:

```bash
tail -f logs/translation.log
```

### Getting Help

1. **Check logs** in `logs/` directory
2. **Review flow artifacts** in `artifacts/` directory
3. **Run validation** on site profile:
   ```python
   errors = config_service.validate_all_profiles()
   ```
4. **Test TM** with known text:
   ```python
   result = tm.lookup(site_id="example.com", src_lang="en",
                     tgt_lang="fr", text="Hello world")
   ```

## Best Practices

### Configuration

1. **Start simple**: Begin with basic frontmatter rules, add complexity gradually
2. **Test thoroughly**: Validate translations on a small sample first
3. **Use semantic TM**: Enable for better hit rates (10-20% improvement)
4. **Configure appropriately**: Adjust thresholds based on your content quality needs

### Translation Memory

1. **Warm up TM**: Translate representative sample to populate TM before bulk processing
2. **Monitor hit rates**: Track TM effectiveness and adjust thresholds
3. **Regular backups**: Export TM data periodically
4. **Clear strategically**: Only clear TM when content style changes significantly

### Performance

1. **Use appropriate hardware**:
   - Development: CPU with CTranslate2
   - Production: GPU for speed, CPU for cost
2. **Batch operations**: Translate directories, not individual files
3. **Enable caching**: Ensure all TM layers are active
4. **Monitor resources**: Watch RAM, disk, GPU usage

### Quality

1. **Validate output**: Use validation suite to catch issues
2. **Review samples**: Manually check 5-10% of translations
3. **Iterate on rules**: Refine frontmatter and body rules based on results
4. **Use context**: Provide good context in segments for better translations

### Maintenance

1. **Update models**: Check for newer/better models periodically
2. **Monitor logs**: Review errors and warnings weekly
3. **Backup data**: Regular backups of TM database
4. **Clean artifacts**: Purge old flow artifacts (keep last 30 days)

---

## Quick Reference

### File Locations

| Item | Path |
|------|------|
| Site Profiles | `config/site_profiles/*.yaml` |
| Model Registry | `config/model_registry.yaml` |
| TM Database | `data/tm.lmdb` |
| Semantic Index | `data/semantic.index` |
| Logs | `logs/translation.log` |
| Flow Artifacts | `artifacts/job_*.ndjson` |

### Common Commands

```bash
# Run tests
pytest tests/unit/

# Check coverage
pytest --cov=src --cov-report=html

# Format code
black src/ tests/

# Type check
mypy src/

# Run example translation
python examples/translate_file.py
```

### Support

- **Documentation**: `docs/` directory
- **Issues**: GitHub Issues
- **Examples**: `examples/` directory
- **Tests**: `tests/` directory for usage examples

---

**Happy Translating! 🌐**
