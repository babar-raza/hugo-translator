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
translate-hugo --site products.aspose.net --dry-run
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

**For Operators:**
```bash
# Run integrity check on L2 LMDB
python -c "from src.tm.integrity import check_cache_integrity; from pathlib import Path; report = check_cache_integrity(Path('data/tm/l2_lmdb')); print(f'Health: {report.health_percentage:.1f}%')"
```

📚 **Full TM Documentation**: [Translation Memory Guide](docs/guides/tm-getting-started.md)

### Content-Based Change Detection

Accurately detect file changes using content hashing instead of modification timestamps. Avoid unnecessary retranslations when files are touched but content is unchanged.

**Benefits:**
- ✅ **No false positives**: Detects actual content changes, not just timestamp updates
- ✅ **Git-friendly**: Works seamlessly with `git checkout`, `git pull`, and other operations
- ✅ **CI/CD compatible**: Handles file regeneration without triggering retranslations
- ✅ **Performance optimized**: Fast-path mtime check avoids redundant hashing (<2% overhead)

**Common Use Cases:**
- Files touched without content changes (`touch file.md`)
- Git operations that update timestamps (`git checkout`, `git pull`)
- Build systems that regenerate files with identical content
- CI/CD pipelines with fresh repository clones

**Quick Start:**
```bash
# Enable in config/global.yaml
features:
  enable_content_hash_tracking: true

# Or disable for a specific run
translate-hugo --site example.com --disable-content-hash

# Rebuild hashes from scratch
translate-hugo --site example.com --rebuild-content-hashes
```

📚 **Full Documentation**: [Content Hash Tracking Guide](docs/guides/content-hash-tracking.md)

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
python -m src.benchmarking.cli run \
    --model facebook/m2m100_418M \
    --device cpu \
    --batch-sizes 8 \
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
translate-hugo --site mysite --sort-segments-by-length
```

**Note:** Sorting overhead is typically <1% of total translation time. Output preserves original document structure exactly.

Full Documentation: [Segment Sorting Guide](docs/features/segment-sorting.md)

### Agent Metrics API (Dry-Run)

Posts per-run translation metrics to a shared Google Sheet for cross-agent visibility. Currently in dry-run mode (payloads logged, not posted to production).

- **Safety**: Append-only sheet, dry_run=true default, enabled=false default, test row cap
- **17-field payload**: timestamp, agent identity, job type, scope, item counts, LLM token usage
- **Profile-driven scope**: Derives product, platform, website from site profile configuration
- **Local evidence**: Sidecar JSON and JSONL ledger for audit

Full Documentation: [Agent Metrics API](docs/observability/agent-metrics-api.md)

## Quick Start

### First-Time Setup

```bash
# 1. Run the bootstrap script (creates venv, installs deps, copies .env)
python scripts/setup_dev_env.py

# 2. Activate the virtual environment
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# 3. Edit .env — set paths to your content repository clones
#    ASPOSE_NET_CONTENT=/path/to/aspose.net/content
#    ASPOSE_ORG_CONTENT=/path/to/aspose.org/content

# 4. Run the test suite to verify setup
python -m pytest tests/unit -x -q

# 5. Try a dry-run translation
translate-hugo --site products.aspose.net --max-files 5 --dry-run
```

Translation models download automatically from HuggingFace on first use (1-5 GB depending on model). No manual model downloads needed.

For GPU acceleration, also run: `pip install -r requirements/gpu.txt`

For detailed first-time installation (Windows, Linux, macOS), see the **[Setup Guide](docs/user-guide/setup.md)**.

### Documentation

- **[Full Documentation](docs/README.md)** - Complete docs home with navigation by persona
- **[User Quickstart](docs/getting-started/user-quickstart.md)** - Translate your first Hugo site
- **[Operator Quickstart](docs/getting-started/operator-quickstart.md)** - Deploy and monitor
- **[Contributor Quickstart](docs/getting-started/contributor-quickstart.md)** - Development setup

### Key Guides

- [Model Selection](docs/guides/model-selection.md) - Understanding models, downloads, and configuration
- [Quality Improvement](docs/guides/quality-improvement.md) - Validation and terminology
- [Configuration Reference](docs/reference/config.md) - All config options
- [CLI Reference](docs/reference/cli.md) - Command-line usage
- [Troubleshooting](docs/operations/troubleshooting.md) - Common issues and fixes

### Running Tests

```bash
pytest tests/unit/ -q                    # Unit tests (~20s)
pytest tests/regression/ -q              # Regression tests
pytest tests/unit/workers/ -v            # Worker tests only
pytest -q --cov=src                      # With coverage
```

### Key Configuration Files

- `config/model_registry.yaml` - Available translation models and metadata
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

## Translation Models

### Automatic Model Downloads

**Models are downloaded automatically** when first needed - no manual intervention required.

When you run your first translation, the system:
1. Determines which model to use (see [Model Selection](#model-selection) below)
2. Automatically downloads the model from HuggingFace Hub (~1-2GB)
3. Caches the model locally for instant future use
4. Models are stored in `~/.cache/huggingface/` (or `%USERPROFILE%\.cache\huggingface\` on Windows)

**No prompts, no manual downloads, just automatic setup.**

### Model Selection

The system chooses which translation model to use based on this priority:

1. **CLI Override** (highest priority): `--model m2m100_1.2b`
2. **Site Profile Default**: Configured in `config/site_profiles/*.yaml`
3. **Fallback Default**: `m2m100_418m` (418M parameters, multilingual)

**Available Models:**

The system includes 19+ pre-configured models in the [model registry](config/model_registry.yaml):

| Model | Parameters | Size | Languages | Best For |
|-------|-----------|------|-----------|----------|
| `m2m100_418m` | 418M | ~1.6GB | 100 languages | Default, balanced speed/quality |
| `m2m100_1.2b` | 1.2B | ~4.8GB | 100 languages | Higher quality translations |
| `nllb_600m` | 600M | ~2.4GB | 200 languages | More language pairs |
| `nllb_1.3b` | 1.3B | ~5.2GB | 200 languages | Best quality, resource-intensive |
| `opus_mt_*` | Varies | ~300MB | Language-pair specific | Fastest, single pair only |

**Smart Recommendations:**

The system can recommend models based on your hardware:

```bash
python -c "
from src.model_runtime.registry import ModelRegistry
from src.model_runtime.hardware import HardwareDetector

registry = ModelRegistry()
hw = HardwareDetector().detect()

# Get recommendation based on detected hardware
rec = registry.recommend_model(
    src_lang='en',
    tgt_lang='fr',
    hardware=hw,
    prefer_quality=True
)
print(f'Recommended: {rec.model_id}')
"
```

The recommendation engine considers:
- Language pair support
- Hardware constraints (RAM, GPU VRAM)
- Device compatibility (CPU vs CUDA)
- Model quality (parameter count)
- Performance (inference speed)

📚 **Full Model Documentation**: [Model Selection Guide](docs/guides/model-selection.md)

### Configuring Models

**Per-site configuration:**

Edit `config/site_profiles/mysite.yaml`:
```yaml
default_model: "nllb_1.3b"  # Use higher quality model for this site
```

**CLI override for testing:**
```bash
# Try different models without changing config
translate-hugo --site mysite --model m2m100_1.2b --target-langs fr
```

**Manual model pre-download (optional):**

```bash
# Pre-download a specific model before translation
python -c "
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
tokenizer = AutoTokenizer.from_pretrained('facebook/m2m100_418M')
model = AutoModelForSeq2SeqLM.from_pretrained('facebook/m2m100_418M')
print('Model cached successfully')
"
```

## Architecture

### Deployment Models

The system supports two deployment paths. The **Windows-native** path is the current production deployment. The **Docker** path enables optional scale-out with Redis and containerized workers.

#### Windows-Native (Current Production Path)

Two autonomous worker processes run as Windows Task Scheduler jobs:

- **Content Worker** (`src/workers/autonomous_content_translation_worker.py`) — Scheduled translation daemon. Runs 4–12 times per day on a configurable window, translates Hugo markdown files, commits results to git.
- **TM Improvement Worker** (`src/workers/tm_improvement_worker.py`) — Scheduled LLM improvement daemon. Consumes the improvement queue, refines low-quality translations in the TM database.

Both workers are started via `scripts/start_workers.ps1` and registered with Task Scheduler via `scripts/setup_task_scheduler.ps1`. No Redis or Docker required.

See [Windows-Native Deployment](docs/operations/windows-native-deployment.md) for setup instructions.

#### Docker / Distributed (Optional Scale-Out)

An orchestrator + Redis queue + containerized workers path is also implemented:

- **Orchestrator** — Monitors content directories, creates translation jobs, manages the Redis job queue
- **Redis Queue** — Distributed job queue for orchestrator-worker communication
- **Workers** — Process translation jobs from queue, write translated output

See [Redis Queue Architecture](docs/architecture/redis-queue.md) and `docker-compose.yml` for details.

### Translation Pipeline

Every file processed by either deployment path goes through the same core pipeline:

```
Hugo Markdown
    → HugoParser (frontmatter, shortcodes, code blocks)
    → SegmentExtractor (translatable text units + placeholders)
    → Translation Memory lookup (L1 in-memory → L2 LMDB → L3 FAISS GPU)
    → MT Model (M2M100 / NLLB / Opus) for cache misses
    → 10-validator Quality Suite (ACCEPT / RETRY / REJECT)
    → MarkdownReconstructor
    → Atomic file write
    → Git auto-commit
```

### Agentic Architecture

The system includes autonomous decision-making and cross-session state management:

- **Supervisor Loop** (`src/workers/supervisor_loop.py`) — Inspect-decide-execute control loop that reads run signals, classifies outcomes, and selects next work units. Decisions: PROCEED, SKIP, BLOCK, CIRCUIT_BREAK, RESUME.
- **Task Queue** (`src/workers/task_queue.py`) — Programmatic task queue with priority levels (P0-P2), dependency resolution, and blocker tracking. Replaces manual task backlog.
- **Continuation State** (`src/workers/continuation_state.py`) — Cross-session state machine (IDLE/RUNNING/COMPLETED/FAILED/INTERRUPTED) with atomic writes. Enables resume-after-failure and circuit breaker patterns.
- **Run Signal Emitter** (`src/observability/run_signal_emitter.py`) — Emits structured JSON signals after each run with verdict (CLEAN_RUN/DEGRADED_RUN/FAILED_RUN/BLOCKED), file stats, and autonomy score.
- **Model Selector** (`src/translation_engine/model_selector.py`) — Selects the best translation model per (site, language) pair based on historical acceptance rates.
- **Blocker Classifier** (`src/observability/blocker_classifier.py`) — LLM-backed classification of stuck items by root cause (CONFIG_ERROR, DATA_QUALITY, MODEL_LIMITATION, etc.).
- **Contradiction Detector** (`src/observability/contradiction_detector.py`) — Audits config claims against observed runtime behavior to detect drift.
- **Run Summarizer** (`src/observability/run_summarizer.py`) — LLM-backed generation of human-readable run summaries.
- **Evidence Declaration** (`src/observability/evidence_declaration.py`) — Pydantic-validated evidence schema with JSON schema export for audit trails.
- **Reviewer Bridge** (`scripts/ops/reviewer_bridge.py`) — MCP JSON-RPC 2.0 bridge for posting run signals to external review systems.

All agentic modules default to `enabled: false` / `dry_run: true` in `config/global.yaml` and can be activated per-module.

### Directory Structure

```
hugo-translator/
├── archive/                      # Historical artifacts
│   ├── legacy/                   # Old translation system
│   ├── plans/                    # Completed plans
│   ├── reports/                  # Historical reports
│   └── samples/                  # Development samples
├── config/                       # Configuration
│   ├── global.yaml               # Global settings
│   ├── site_profiles/            # Site-specific configs
│   └── terminology/              # Term protection rules
├── data/                         # Data directory
│   ├── benchmark_corpus/         # Benchmark test data
│   ├── benchmarks/               # Benchmark results
│   └── tm/                       # Translation memory storage
├── docker/                       # Docker configurations
├── docs/                         # Documentation
│   ├── development/              # Developer guides
│   ├── deployment/               # Deployment guides
│   ├── operations/               # Operations runbooks
│   └── ...                       # Additional docs
├── models/                       # Model storage
├── plans/                        # Active plans only
│   ├── autonomous_workers/       # Worker implementation plans
│   ├── from_chat/                # Plans from conversations
│   └── templates/                # Plan templates
├── reports/                      # Active reports only
│   ├── agents/                   # Agent execution reports
│   └── autonomous_workers/       # Worker analysis reports
├── requirements/                 # Python dependencies
├── scripts/                      # Scripts (reorganized)
│   ├── archived/                 # Historical scripts
│   │   └── migrations/           # One-time migration scripts
│   ├── diagnostics/              # Diagnostic utilities
│   └── observability/            # Telemetry scripts
├── specs/                        # Technical specifications
├── src/                          # Source code
│   ├── benchmarking/             # Benchmarking system (dev-only)
│   ├── model_runtime/            # Model loading/inference
│   ├── observability/            # Logging/telemetry
│   ├── orchestrator/             # Job orchestration
│   ├── shared_engines/           # Unified shared engines
│   ├── tm/                       # Translation memory (L1/L2/L3)
│   ├── translation_engine/       # Core translation logic
│   ├── utils/                    # Shared utilities
│   ├── verification/             # Output verification
│   └── workers/                  # Worker processes
└── tests/                        # Test suite
    ├── contract/                 # Contract tests
    ├── fixtures/                 # Consolidated test fixtures
    ├── golden/                   # Golden tests
    ├── integration/              # Integration tests
    ├── regression/               # Regression tests
    ├── smoke/                    # Smoke tests
    └── unit/                     # Unit tests
```

For detailed structure documentation, see [Repository Structure](docs/development/REPO_STRUCTURE.md).

## Installation

For first-time setup with automated scripts and GPU detection, see the **[Setup Guide](docs/user-guide/setup.md)**.

### Prerequisites

- **Python 3.10+**
- **CUDA 12.1+** (optional) — GPU acceleration; CPU fallback is automatic
- **Redis 7+** (optional, Docker deployment only) — Required only for the distributed orchestrator path, not for Windows-native workers. Docker includes it via `docker-compose.yml`; otherwise `apt install redis-server` or `brew install redis`
- **Docker** (optional) — For containerized scale-out deployment only

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
python scripts/diag/verify_telemetry.py --latest

# Run comprehensive health checks (requires local-telemetry repo)
cd ../local-telemetry
python scripts/diagnose_pragma_settings.py
python scripts/check_db_integrity.py
python scripts/validate_installation.py
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, code style, and PR guidelines.

For autonomous agent guardrails, see [AGENTS.md](AGENTS.md) and [Agent Guardrails](docs/AGENT_GUARDRAILS.md).

## Version

Current version: 0.1.0 (see pyproject.toml)

## License

See LICENSE file for details.
