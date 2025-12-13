# Hugo Translation System

A production-grade translation system for Hugo static sites featuring multi-layer Translation Memory with semantic search, intelligent caching, and structure-preserving markdown reconstruction.

## Overview

This system translates Hugo markdown content (frontmatter + body) across multiple languages while:

- **Preserving structure**: YAML frontmatter comments, quote styles, markdown formatting, shortcodes, and links
- **Maximizing reuse**: 3-tier Translation Memory (L1 cache, L2 persistent LMDB, L3 semantic FAISS) dramatically reduces API calls
- **Supporting multiple backends**: HuggingFace Transformers (M2M100, NLLB), with GPU acceleration via CUDA/MPS
- **Validating quality**: Pre-write and post-write validation ensures translated output integrity

## Key Features

### Translation Memory (3-Layer Architecture)

| Layer | Storage | Match Type | Speed |
|-------|---------|------------|-------|
| **L1** | In-memory LRU | Exact | <1ms |
| **L2** | LMDB persistent | Exact | ~5ms |
| **L3** | FAISS + Sentence Transformers | Semantic (80%+ similarity) | ~50ms |

### Translation Workflow

```
Hugo MD File
     |
     v
+--------------------+
|   Hugo Parser      |  Parse frontmatter (YAML) + body (Markdown AST)
+--------------------+
     |
     v
+--------------------+
| Segment Extractor  |  Extract translatable segments, protect links/shortcodes
+--------------------+
     |
     v
+--------------------+
|  Translation Memory|  L1 -> L2 -> L3 cascade lookup
+--------------------+
     |
     | (cache miss)
     v
+--------------------+
|  Model Backend     |  M2M100, NLLB, etc. (CPU/GPU)
+--------------------+
     |
     v
+--------------------+
|  Reconstructor     |  Rebuild markdown with translations, preserve structure
+--------------------+
     |
     v
+--------------------+
|   Validator        |  Check placeholders, YAML, structure integrity
+--------------------+
     |
     v
  Output File (per target language)
```

### Supported Translation Models

| Model | ID | Size | Quality | Speed |
|-------|-----|------|---------|-------|
| M2M100 418M | `m2m100_418m` | 418M params | Good | Fast |
| M2M100 1.2B | `m2m100_1.2b` | 1.2B params | Better | Medium |
| NLLB 200 600M | `nllb_200_600m` | 600M params | Good | Fast |
| Small100 | `small100` | 330M params | Fair | Fastest |

## Installation

### Prerequisites

- Python 3.10+
- 8GB+ RAM (16GB recommended for larger models)
- Optional: NVIDIA GPU with CUDA for acceleration

### Quick Start

```bash
# Clone repository
git clone <repository-url>
cd hugo-translator

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -e ".[dev]"          # Development install
# OR
pip install -r requirements/cpu.txt   # CPU-only
pip install -r requirements/gpu.txt   # With GPU support

# Configure environment
cp .env.example .env

# Verify installation
python -c "from src.translation_engine import TranslationEngine; print('OK')"
```

### Docker Installation

```bash
# Copy and configure environment
cp .env.example .env

# Start services
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f
```

## Usage

### Command Line Interface

```bash
# Translate a single file
translate-hugo --site products.aspose.net --input content/en/products/overview.md --target-langs de fr es

# Translate a directory
translate-hugo --site kb.aspose.net --input content/en/ --target-langs de fr

# With validation mode
translate-hugo --site docs.aspose.net --input content/en/ --target-langs de --validation-mode strict

# Dry run (preview without writing)
translate-hugo --site example --input content/en/ --target-langs de --dry-run

# With custom config
translate-hugo --site example --config-root ./custom-config --target-langs de fr
```

### CLI Options

| Flag | Description |
|------|-------------|
| `--site` | Site profile ID (required) |
| `--input` | Input file or directory |
| `--target-langs` | Target languages (space-separated) |
| `--validation-mode` | `strict`, `normal`, `lenient`, or `off` |
| `--disable-validation` | Skip all validation |
| `--dry-run` | Preview without writing files |
| `--max-retries` | Max retry attempts on validation failure |
| `--log-level` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `--config-root` | Custom config directory path |

### Programmatic Usage

```python
from src.translation_engine import TranslationEngine
from src.tm import TranslationMemory
from src.model_runtime import ModelLoader
from src.utils.config_loader import ConfigService

# Initialize components
config = ConfigService("./config")
tm = TranslationMemory(data_dir="./data/tm", enable_semantic=True)
model_loader = ModelLoader(cache_dir="./data/models")

# Create engine
engine = TranslationEngine(
    config_service=config,
    tm=tm,
    model_loader=model_loader,
    enable_validation=True,
)

# Translate a file
result = engine.translate_file(
    site_id="example",
    file_path=Path("content/en/page.md"),
    target_langs=["de", "fr", "es"],
)

print(f"Success: {result.success}")
print(f"Outputs: {result.outputs}")
print(f"TM hits: {result.stats.tm_hits}")
```

## Configuration

### Directory Structure

```
config/
├── global.yaml              # System-wide settings
├── model_registry.yaml      # Available translation models
├── validation.yaml          # Validation rules and thresholds
├── terminology.yaml         # Protected terms and glossaries
├── site_profiles/           # Per-site configurations
│   ├── default.yaml
│   ├── example.yaml
│   └── <your-site>.yaml
└── schemas/
    └── site_profile.schema.json
```

### Site Profile Example

```yaml
# config/site_profiles/example.yaml
site_id: "example"
name: "Example Site"
default_source_lang: "en"
target_langs:
  - de
  - fr
  - es

content_roots:
  - "./content/en"

output_layout:
  per_language_folders: true
  pattern: "{lang}/{path}"

frontmatter_mode:
  title: translate
  description: translate
  keywords: translate
  date: preserve
  url: preserve
  aliases: preserve

tm_prefs:
  use_semantic_tm: true
  semantic_threshold: 0.80
```

### Environment Variables

Key variables (see `.env.example` for full list):

| Variable | Description | Default |
|----------|-------------|---------|
| `DEVICE` | Translation device (`auto`, `cpu`, `cuda`) | `auto` |
| `DEFAULT_MODEL` | Default translation model | `m2m100_418m` |
| `TM_DATA_PATH` | Translation Memory storage path | `./data/tm` |
| `TM_SEMANTIC_THRESHOLD` | L3 semantic match threshold | `0.80` |
| `MAX_PARALLEL_FILES` | Parallel file processing limit | `4` |
| `LOG_LEVEL` | Logging verbosity | `INFO` |

## Project Structure

```
hugo-translator/
├── src/                          # Source code
│   ├── cli.py                    # Command-line interface
│   ├── translation_engine/       # Core translation workflow
│   │   ├── engine.py            # Main orchestrator
│   │   ├── parser/              # Hugo markdown parser
│   │   ├── extractor/           # Segment extraction
│   │   ├── reconstructor/       # Output reconstruction
│   │   ├── validation/          # Quality validators
│   │   └── handlers/            # Special content handlers
│   ├── tm/                       # Translation Memory
│   │   ├── l1_cache.py          # In-memory LRU cache
│   │   ├── l2_persistent.py     # LMDB storage
│   │   ├── l3_semantic.py       # FAISS semantic search
│   │   └── translation_memory.py # Unified interface
│   ├── model_runtime/            # Model management
│   │   ├── loader.py            # Model loading
│   │   ├── registry.py          # Model registry
│   │   └── hardware.py          # Device detection
│   ├── orchestrator/             # Job scheduling
│   │   ├── orchestrator.py      # Job coordination
│   │   ├── queue.py             # Job queue
│   │   ├── scheduler.py         # Periodic tasks
│   │   └── watcher.py           # File watching
│   ├── observability/            # Logging & metrics
│   │   ├── logger.py            # Structured logging
│   │   ├── metrics.py           # Prometheus metrics
│   │   └── flow_artifacts.py    # Debug artifacts
│   └── utils/                    # Shared utilities
│       └── config_loader.py     # Configuration management
├── config/                       # Configuration files
├── tests/                        # Test suite
│   ├── unit/                    # Unit tests
│   ├── integration/             # Integration tests
│   └── fixtures/                # Test data
├── scripts/                      # Operational scripts
├── docker/                       # Docker configurations
├── docs/                         # Documentation
├── samples/                      # Sample Hugo content
├── requirements/                 # Dependencies
│   ├── base.txt                 # Core dependencies
│   ├── cpu.txt                  # CPU-only
│   ├── gpu.txt                  # With GPU support
│   └── dev.txt                  # Development tools
├── pyproject.toml               # Package configuration
├── docker-compose.yml           # Container orchestration
└── Dockerfile                   # Container build
```

## Development

### Running Tests

```bash
# All tests
pytest tests/ -v

# Unit tests only
pytest tests/unit/ -v

# With coverage
pytest tests/ -v --cov=src --cov-report=html

# Specific test file
pytest tests/unit/phase-3/test_translation_memory.py -v
```

### Code Quality

```bash
# Format code
black src/ tests/

# Lint
ruff check src/ tests/

# Type check
mypy src/

# All checks
black src/ tests/ && ruff check src/ tests/ && mypy src/
```

### Adding a New Site Profile

1. Create `config/site_profiles/<site-id>.yaml`
2. Define content roots, target languages, and frontmatter rules
3. Add sample content to `samples/<site-id>/`
4. Test with: `translate-hugo --site <site-id> --input samples/<site-id>/ --target-langs de --dry-run`

## Performance

### Expected Throughput

| Operation | Speed |
|-----------|-------|
| L1 cache lookup | >10,000/sec |
| L2 LMDB lookup | >5,000/sec |
| L3 semantic search | ~100/sec |
| Model translation (CPU) | ~5-10 segments/sec |
| Model translation (GPU) | ~50-100 segments/sec |

### Optimization Tips

- **Maximize TM hits**: Pre-populate TM from existing translations
- **Use GPU**: 5-10x faster for model translations
- **Tune batch size**: Larger batches improve GPU throughput
- **Enable parallel processing**: Process multiple files concurrently
- **Adjust semantic threshold**: Lower threshold = more L3 hits but less precision

## Documentation

Detailed documentation is available in `docs/`:

- [User Guide](docs/USER_GUIDE.md) - Complete usage instructions
- [Configuration Reference](docs/CONFIGURATION.md) - All configuration options
- [Deployment Guide](docs/DEPLOYMENT.md) - Production deployment
- [Operations Manual](docs/OPERATIONS.md) - Day-to-day operations
- [Troubleshooting](docs/TROUBLESHOOTING.md) - Common issues and solutions
- [CLI Reference](docs/CLI_FLAGS_REFERENCE.md) - All CLI flags explained

## License

MIT License - see LICENSE file for details.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes with tests
4. Ensure all tests pass and code quality checks pass
5. Submit a pull request

---

**Built with:** Python 3.10+ | HuggingFace Transformers | FAISS | LMDB | ruamel.yaml
