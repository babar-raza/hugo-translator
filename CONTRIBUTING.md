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

## Architecture

- `src/translation_engine/` — core translation pipeline (engine, extractor, reconstructor, validation)
- `src/model_runtime/` — model loading, inference backends (M2M100, CT2, LLM)
- `src/tm/` — 3-layer translation memory (L1 in-memory, L2 LMDB, L3 FAISS)
- `src/workers/` — autonomous worker daemons
- `src/observability/` — telemetry, git commit, metrics
- `config/` — global config, site profiles, terminology

## Pull Requests

1. Branch from `main`
2. Keep changes focused — one concern per PR
3. Ensure `pytest tests/unit/ -q` passes
4. Do not commit `.env`, credentials, or model binaries

## Repository Hygiene

- **Never commit hardcoded personal paths** (e.g., `D:\onedrive`, `C:\Users\<name>`). The pre-commit hook blocks these in Python, YAML, shell, and batch files.
- **Personal utility scripts** should not be tracked. Keep them untracked or in a local-only directory.
- **Test scripts** go under `tests/`, not at the project root or in `src/`.
- **Pre-commit hooks are mandatory** — run `pre-commit install` after cloning.
- Run `bash scripts/check_share_safe.sh` before pushing to verify no private data leaks.
