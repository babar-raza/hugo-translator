# Hugo Translation System Documentation

A production-ready automated translation system for Hugo static sites with built-in validation, terminology protection, and quality assurance.

## Quick Start

**New to the system?** Start here:

- **[User Quickstart](getting-started/user-quickstart.md)** - Translate your first Hugo site
- **[Operator Quickstart](getting-started/operator-quickstart.md)** - Deploy and monitor the system
- **[Contributor Quickstart](getting-started/contributor-quickstart.md)** - Set up development environment

## By Persona

### 👤 Content Translator (User)
Translate Hugo content with quality assurance.

**Key Tasks:**
- [Translate single files](guides/translation-workflows.md#single-file-translation)
- [Batch translate directories](guides/batch-optimization.md)
- [Configure validation rules](guides/quality-improvement.md)
- [Handle terminology](guides/quality-improvement.md#terminology-protection)

**Translation Memory:**
- [TM Getting Started](guides/tm-getting-started.md) - Understanding TM and cache performance
- [TM Override Modes](guides/tm-override-modes.md) - Control cache behavior (bypass, refresh, validate)

**Reference:**
- [CLI Commands](reference/cli.md) - All command-line options
- [File Contracts](reference/file-contracts.md) - Input/output formats

### 🛠️ Site Operator (Ops/SRE)
Deploy, monitor, and maintain production systems.

**Key Tasks:**
- [Deploy with Docker](operations/deployment.md)
- [Monitor performance](operations/monitoring.md)
- [Troubleshoot issues](operations/troubleshooting.md)
- [Backup and restore](operations/backup-restore.md)

**Translation Memory Operations:**
- [TM Maintenance](operations/tm-maintenance.md) - Daily/weekly maintenance, integrity checks, backups
- [TM Statistics & Monitoring](guides/tm-statistics-monitoring-guide.md) - Monitor hit rates and health
- [TM Troubleshooting](operations/tm-troubleshooting.md) - Diagnose corruption, performance issues
- [TM Performance Tuning](operations/tm-performance-tuning.md) - Optimize L1/L2/L3 layers

**Reference:**
- [Deployment Guide](operations/deployment.md) - Production setup
- [Monitoring](operations/monitoring.md) - Metrics and alerts

### 💻 System Contributor (Engineer)
Understand, extend, and contribute to the codebase.

**Key Tasks:**
- [Set up development](development/setup.md)
- [Run tests](development/testing.md)
- [Understand architecture](architecture/translation-engine.md)
- [Add features](development/scripts.md)

**Translation Memory Deep Dives:**
- [TM Architecture](architecture/translation-memory.md) - L1/L2/L3 design, ACID guarantees, crash safety
- [TM API Reference](reference/tm-api.md) - Programmatic usage of TM layers

**Reference:**
- [Architecture Overview](architecture/) - System design
- [API Reference](reference/api.md) - Extension points

## By Scenario

### 🚀 Getting Started
- [User Quickstart](getting-started/user-quickstart.md) - First translation
- [Operator Quickstart](getting-started/operator-quickstart.md) - First deployment
- [Contributor Quickstart](getting-started/contributor-quickstart.md) - First contribution

### ⚙️ Configuration
- [Global Config](reference/config.md#globalyaml) - System-wide settings
- [Site Profiles](reference/config.md#site-profiles) - Per-site configuration
- [Validation Rules](reference/config.md#validationyaml) - Quality controls
- [Terminology](reference/config.md#terminologyyaml) - Protected terms

### 🔧 Operations
- [Docker Deployment](operations/deployment.md) - Container setup
- [Monitoring](operations/monitoring.md) - Observability
- [Troubleshooting](operations/troubleshooting.md) - Problem solving
- [Backup/Restore](operations/backup-restore.md) - Data management

### 🏗️ Architecture
- [Translation Engine](architecture/translation-engine.md) - Core components
- [Validation Pipeline](architecture/validation-pipeline.md) - Quality assurance
- [Translation Memory](architecture/translation-memory.md) - Caching system
- [Model Runtime](architecture/model-runtime.md) - AI integration

### 💾 Translation Memory (TM)
- **Getting Started**: [TM Introduction](guides/tm-getting-started.md) - What is TM and how it saves time
- **Operations**: [Maintenance](operations/tm-maintenance.md) | [Monitoring](guides/tm-statistics-monitoring-guide.md) | [Troubleshooting](operations/tm-troubleshooting.md) | [Performance](operations/tm-performance-tuning.md)
- **Advanced**: [Override Modes](guides/tm-override-modes.md) - Control cache behavior
- **Technical**: [Architecture](architecture/translation-memory.md) | [API Reference](reference/tm-api.md)

### 🧪 Development
- [Setup](development/setup.md) - Development environment
- [Testing](development/testing.md) - Test suite and execution
- [Scripts](development/scripts.md) - Development tooling
- [Docs Standards](development/docs-standards.md) - Documentation guidelines

## Key Concepts

### Translation Workflow
1. **Parse** Hugo markdown into AST
2. **Extract** translatable segments
3. **Lookup** Translation Memory
4. **Translate** new segments via AI models
5. **Validate** quality and structure
6. **Reconstruct** translated markdown
7. **Write** output files

### Quality Assurance
- **10 Validators** check translation quality
- **Decision Engine** (ACCEPT/RETRY/REJECT)
- **Terminology Protection** preserves brand terms
- **Structure Preservation** maintains Hugo formatting

### Translation Memory
- **L1 Cache** - Fast in-memory LRU cache (configurable size)
- **L2 Persistent** - LMDB database with ACID guarantees and crash safety
- **L3 Semantic** - FAISS vector search for fuzzy matching (90%+ similarity)
- **Operations** - Integrity checks, backups, performance tuning
- **Control** - Override modes (bypass, refresh, validate) for cache management

## Source of Truth

Code is the authoritative source. Documentation links to implementation:

- **Entry Points**: `src/cli.py`, `src/translation_engine/engine.py`
- **Configuration**: `src/utils/config_loader.py`, `config/*.yaml`
- **Core Logic**: `src/translation_engine/`, `src/tm/`, `src/model_runtime/`

## Contributing to Docs

Follow the [style guide](_audit/style_guide.md) and [IA proposal](_audit/README_IA_PROPOSAL.md).

**Quick Edits:**
- Reference updates: Edit `docs/reference/`
- Guide improvements: Edit `docs/guides/`
- New features: Add to appropriate section

**Major Changes:**
- Review [IA proposal](_audit/README_IA_PROPOSAL.md) for placement
- Follow [migration plan](_audit/docs_migration_plan.md) for consistency
- Update [traceability](_audit/traceability.md) for coverage

---

**Version**: 1.1.0 | **Last Updated**: 2025-12-24
