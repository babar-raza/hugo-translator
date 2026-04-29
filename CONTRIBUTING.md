# Contributing to Hugo Translator

## Quick Start

```bash
git clone <repo-url>
cd hugo-translator
python scripts/setup_dev_env.py   # Creates venv, installs deps, copies .env
.venv/Scripts/activate             # Windows
# source .venv/bin/activate        # Linux/macOS
# Edit .env with your content repo paths
```

## Environment Variables

Site profiles use env-var paths. Set these in your `.env`:

```
ASPOSE_NET_CONTENT=/path/to/aspose.net/content
ASPOSE_ORG_CONTENT=/path/to/aspose.org/content
```

## Running Tests

```bash
pytest tests/unit/ -q                    # Unit tests (~20s)
pytest tests/regression/ -q              # Regression tests
pytest tests/unit/workers/ -v            # Worker tests only
```

## Code Style

- Python 3.10+, type hints encouraged
- Ruff for linting and formatting
- Commit format: `<type>(<scope>): <subject>` (imperative mood)
- Types: `feat`, `fix`, `chore`, `docs`

## Repository Structure

The root should contain only essential project files (~13 files). Everything else lives in organized subdirectories.

**Root files** (keep minimal):
`README.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, `LICENSE`, `TASK_BACKLOG.md`, `pyproject.toml`, `.gitignore`, `.gitattributes`, `.pre-commit-config.yaml`, `.env.example`, `Dockerfile`, `Dockerfile.gpu`, `.dockerignore`

**Tracked directories:**

| Directory | Purpose |
|-----------|---------|
| `src/` | All source code (engine, workers, TM, models, CLI) |
| `tests/` | Test suites: `unit/`, `integration/`, `regression/`, `e2e/`, `smoke/`, `contract/` |
| `config/` | Configuration: `global.yaml`, `model_registry.yaml`, `site_profiles/`, `terminology/` |
| `scripts/` | Operational scripts (setup, workers, CI gates, health checks) |
| `docs/` | Architecture docs, guides, reference |
| `specs/` | Technical specifications |
| `requirements/` | Python dependency files (`base.txt`, `cpu.txt`, `gpu.txt`, `dev.txt`) |
| `models/` | Model metadata only — binaries downloaded at runtime |
| `data/benchmark_corpus/` | Tracked benchmark test data |
| `.github/workflows/` | CI/CD pipelines |

**Local-only directories** (gitignored, never committed):

| Directory | Purpose |
|-----------|---------|
| `reports/` | Agent reports, translation logs, evidence bundles |
| `plans/` | Task plans and working documents |
| `logs/` | Runtime logs, heartbeats, PID files |
| `runs/` | Translation run outputs |
| `output/` | Test translation outputs |
| `data/` (except benchmark_corpus) | TM caches, model caches, runtime data |
| `scripts/archived/` | Old one-off scripts preserved locally |
| `.translation_progress/` | Batch progress tracking |
| `telemetry_buffer/` | Telemetry event queue |

**Models:** Binary model files (M2M100, NLLB, FastText) are ~14 GB and are never committed. They are downloaded at first run. See `models/README.md`.

## Architecture

- `src/translation_engine/` — core translation pipeline (engine, extractor, reconstructor, validation)
- `src/model_runtime/` — model loading, inference backends (M2M100, CT2, LLM)
- `src/tm/` — 3-layer translation memory (L1 in-memory, L2 LMDB, L3 FAISS)
- `src/workers/` — autonomous worker daemons
- `src/observability/` — telemetry, git commit, metrics
- `config/` — global config, site profiles, terminology

## Autonomous Agents

This project uses autonomous worker agents. See [AGENTS.md](AGENTS.md) for worker details and [Agent Guardrails](docs/AGENT_GUARDRAILS.md) for safety rules.

## Pull Requests

1. Branch from `main`
2. Keep changes focused — one concern per PR
3. Ensure `pytest tests/unit/ -q` passes
4. Do not commit `.env`, credentials, or model binaries

## Repository Hygiene

- **Keep the root clean.** Only the ~13 files listed above belong at root. Do not add scripts, reports, logs, or temp files at root.
- **Never commit hardcoded personal paths** (e.g., `D:\onedrive`, `C:\Users\<name>`). The pre-commit hook blocks these in Python, YAML, shell, and batch files.
- **Scripts** go in `scripts/`. One-off or experimental scripts go in `scripts/archived/` (gitignored).
- **Test scripts** go under `tests/`, not at the project root or in `src/`.
- **Reports, plans, logs** are local-only — they are gitignored and should never be committed.
- **Config backups** — do not commit `model_registry.backup.yaml` or similar variants. Only `model_registry.yaml` is canonical.
- **Pre-commit hooks are mandatory** — run `pre-commit install` after cloning.
- Run `bash scripts/check_share_safe.sh` before pushing to verify no private data leaks.
