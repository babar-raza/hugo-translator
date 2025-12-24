# Hugo Translation System

A production-ready automated translation system for Hugo static sites with built-in validation, terminology protection, and quality assurance.

## Overview

The Hugo Translation System translates Hugo markdown content while preserving:
- YAML frontmatter structure
- Hugo shortcodes
- Code blocks and syntax
- Markdown formatting
- Links and references
- Protected terminology (company names, product names, API identifiers)

## Key Features

### Automated Quality Validation

The system includes a comprehensive validation engine with 10 validators that check translation quality before writing files to disk:

- **Completeness**: 100% segment coverage, no missing translations
- **Language Consistency**: Target language detection using langdetect
- **Terminology Preservation**: Protect Aspose, .NET, product names, API identifiers
- **Shortcode Preservation**: Hugo shortcode integrity ({{< ... >}})
- **Structure Validation**: Markdown heading/list/code block preservation
- **Placeholder Integrity**: Code/link placeholder restoration
- **Frontmatter Protection**: Field-level translation rules
- **Link Validation**: Link integrity and URL preservation
- **YAML Validation**: Frontmatter syntax validation
- **File Placement**: Output directory structure validation

### Decision Engine (ACCEPT/RETRY/REJECT)

Automated decision-making based on validation results:
- **ACCEPT**: Translation meets quality standards, write to disk
- **RETRY**: Translation has fixable issues, retry with feedback (up to 2 times)
- **REJECT**: Translation has critical errors, discard

### Configurable Validation Modes

Choose validation strictness for your use case:
- **Strict**: Zero tolerance, reject on first error (API docs, critical content)
- **Normal**: Balanced approach, tolerate minor issues (default)
- **Lenient**: Tolerant, more retries (draft content, testing)

### CLI Control

```bash
# Use strict validation
translate-hugo --site products.aspose.net --validation-mode strict

# Disable validation for testing
translate-hugo --site products.aspose.net --disable-validation

# Use custom validation config
translate-hugo --site products.aspose.net --validation-config ./custom-validation.yaml

# Preview validation decisions without writing files
translate-hugo --site products.aspose.net --preview
```

### Translation Memory (TM)

The system includes a 3-layer Translation Memory that dramatically reduces translation costs and time:

- **L1 Cache**: In-memory LRU cache for instant lookups
- **L2 Persistent**: LMDB database with ACID guarantees and crash safety
- **L3 Semantic**: FAISS-based fuzzy matching for similar translations (90%+ similarity)

**Typical Performance:**
- 70-95% cache hit rate on production content
- 10-50x speedup vs. fresh translation
- Automatic integrity checking and backup/restore

**For Users:**
```bash
# Check TM status and hit rates
python -c "from src.tm import create_translation_memory; from pathlib import Path; tm = create_translation_memory(Path('data/tm')); print(tm.get_stats())"
```

**For Operators:**
```bash
# Run integrity check
python -c "from src.tm.integrity import check_cache_integrity; from pathlib import Path; report = check_cache_integrity(Path('data/tm/l2_lmdb')); print(f'Health: {report.health_percentage:.1f}%')"

# Create backup
python -c "from src.tm.backup import create_tm_backup; from pathlib import Path; backup_path = create_tm_backup(Path('data/tm'), Path('backups')); print(f'Backup: {backup_path}')"
```

📚 **Full TM Documentation**: [Translation Memory Guide](docs/guides/tm-getting-started.md)

### Benchmarking System

Comprehensive benchmarking system for performance measurement and ML-based model recommendations:

- **Performance Measurement**: Accurate metrics for throughput, memory usage, and latency
- **Model Comparison**: Compare translation models on your hardware
- **Production Learning**: Optionally record real workloads (OPT-IN) to improve recommendations
- **Adaptive Recommendations**: ML-based suggestions for optimal configurations

**Key Features:**
- SQLite database with schema versioning (v1-v4 migrations)
- Hardware detection with PII sanitization
- Bounded metric storage (prevents memory leaks)
- Thread-safe concurrent operations
- OPT-IN production metrics (enabled=False default)

**Quick Start:**
```bash
# Run benchmark
python -m src.benchmarking.cli benchmark run \
    --model facebook/m2m100_418M \
    --device cpu \
    --batch-size 8 \
    --corpus tiny

# Get recommendation
python -c "
from pathlib import Path
from src.benchmarking.storage import BenchmarkDatabase
from src.benchmarking.recommender import ModelRecommender
from src.benchmarking.system_info import SystemInfoCollector

db = BenchmarkDatabase(Path('data/benchmarks/benchmarks.db'))
recommender = ModelRecommender(db)
system_info = SystemInfoCollector().collect()
rec = recommender.recommend(system_info)
print(f'Recommended: {rec.model_id} (batch_size={rec.batch_size})')
"
```

**Metrics Configuration:**

The system uses configurable bounded storage to prevent memory leaks in long-running operations. Configure via `config/metrics.yaml` or environment variables:

```bash
# High-traffic production tuning
export METRICS_ENGINE_MAXLEN=2000    # Retry metrics
export METRICS_L3_MAXLEN=20000       # L3 semantic operations
export METRICS_BATCH_MAXLEN=10000    # Batch processing
```

**Default limits:**
- Translation engine retry metrics: 1,000 samples
- L3 semantic timing metrics: 10,000 samples
- Batch optimizer timing metrics: 5,000 samples

📚 **Configuration Guide**: [Metrics Configuration](docs/configuration/metrics.md)

📚 **Full Benchmarking Documentation**: [Benchmarking Guide](docs/features/benchmarking.md)

### Segment Sorting

Optional performance optimization that sorts translation segments by length (shortest first) before processing:

- **Improved GPU Batching**: Groups similar-length segments together for efficient batching
- **Reduced Memory Fragmentation**: Homogeneous batches reduce padding overhead
- **Better GPU Utilization**: Minimizes wasted compute on padding tokens
- **Lower OOM Risk**: More predictable memory usage with uniform batch sizes

**When to use:**
- Large translation jobs (1000+ segments)
- Documents with high length variance (short titles + long paragraphs)
- GPU-based translation (CUDA)
- Low TM cache hit rates (<50%)

**Quick Start:**
```bash
# Enable via CLI flag
python -m src.cli translate --site mysite --sort-segments-by-length

# Or configure in config/default.yaml
body_rules:
  sort_segments_by_length: true
```

**Note:** Sorting overhead is typically <1% of total translation time. Output preserves original document structure exactly.

📚 **Full Documentation**: [Segment Sorting Guide](docs/features/segment-sorting.md)

## Quick Start

### First-Time Setup

New to the project? Start here:

- **[⚡ Setup Guide](docs/user-guide/setup.md)** - First-time installation for Windows, Linux, and macOS
  - Automated setup scripts with GPU auto-detection
  - Prerequisites, troubleshooting, and verification
  - Platform-specific instructions (including WSL)

### Documentation

- **[📚 Full Documentation](docs/README.md)** - Complete docs home with navigation by persona
- **[🚀 User Quickstart](docs/getting-started/user-quickstart.md)** - Translate your first Hugo site
- **[⚙️ Operator Quickstart](docs/getting-started/operator-quickstart.md)** - Deploy and monitor
- **[💻 Contributor Quickstart](docs/getting-started/contributor-quickstart.md)** - Development setup

### Key Guides

- [Translation Workflows](docs/guides/translation-workflows.md) - Basic to advanced usage
- [Quality Improvement](docs/guides/quality-improvement.md) - Validation and terminology
- [Configuration Reference](docs/reference/config.md) - All config options
- [CLI Reference](docs/reference/cli.md) - Command-line usage
- [Troubleshooting](docs/operations/troubleshooting.md) - Common issues and fixes

### Key Configuration Files

- `config/validation.yaml` - Validation rules, decision thresholds, retry strategy
- `config/terminology.yaml` - Protected terminology (exact matches and patterns)
- `config/metrics.yaml` - Metrics storage limits, thresholds, statistics configuration
- `config/site_profiles/*.yaml` - Site-specific configuration

### Example: Enable Terminology Protection

Edit `config/terminology.yaml`:

```yaml
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
```

## Architecture

- **Source**: `src/` - Core translation engine and validators
- **Tests**: `tests/` - Comprehensive test suite
- **Config**: `config/` - Validation, terminology, site profiles
- **Docs**: `docs/` - User guides, reference, troubleshooting

## Installation

For first-time setup with automated scripts and GPU detection, see the **[Setup Guide](docs/user-guide/setup.md)**.

### Manual Installation (Advanced Users)

If you prefer manual installation or need custom configuration:

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: .\venv\Scripts\Activate.ps1

# Install dependencies (CPU mode)
pip install -r requirements/cpu.txt

# Or for GPU mode (requires CUDA 12.1+)
pip install torch --index-url https://download.pytorch.org/whl/cu121
pip install -r requirements/gpu.txt

# Install package
pip install -e .
```

### Optional Dependencies

#### Language Quality Checking

The AST batch translation system uses `langdetect` to verify translations are in the target language. If not installed, this check is skipped with a warning logged.

**Install:**
```bash
pip install -e ".[quality]"
```

**What it does:** Detects mixed-language output during batch translation and triggers automatic fallback to individual translation to ensure language purity.

**Without langdetect:** Translations still work correctly, but mixed-language output may not be detected during batch translation. The sentence-level language consistency validator will still catch most issues.

#### Development Tools

```bash
pip install -e ".[dev]"  # Install pytest, black, ruff, mypy, etc.
```

#### GPU Acceleration

```bash
pip install -e ".[gpu]"  # Install FAISS-GPU, CTranslate2
```

#### Documentation

```bash
pip install -e ".[docs]"  # Install Sphinx and themes
```

## Telemetry Health Monitoring

This repository includes automated health checks for telemetry integration:

### Daily Health Check Workflow

The GitHub Actions workflow automatically validates telemetry system health:
- Runs daily at 9 AM UTC
- Validates PRAGMA settings (synchronous=FULL, busy_timeout=30000)
- Checks database integrity
- Verifies recent telemetry runs

### Manual Trigger

```bash
# Trigger health check manually
gh workflow run telemetry_health_check.yml
```

### View Results

- **GitHub Actions Tab**: Navigate to Actions → "Telemetry Health Check"
- **Command Line**:
  ```bash
  gh run list --workflow=telemetry_health_check.yml
  gh run view --log
  ```

### Local Validation

Run validation scripts locally:

```bash
# Verify latest telemetry record
python scripts/verify_telemetry.py --latest

# Run comprehensive health checks (requires local-telemetry repo)
cd ../local-telemetry
python scripts/diagnose_pragma_settings.py
python scripts/check_db_integrity.py
python scripts/validate_installation.py
```

## Version

Current version: 1.0

## License

See LICENSE file for details.
