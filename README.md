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

## Quick Start

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

### Basic Installation

```bash
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
