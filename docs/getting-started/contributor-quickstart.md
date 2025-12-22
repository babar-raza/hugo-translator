# Contributor Quickstart

For engineers extending the system.

## Prerequisites
- Python 3.10+; install dev extras: `pip install -r requirements/dev.txt`.
- Understand core entrypoints: `src/cli.py`, `src/translation_engine/engine.py`, `src/utils/config_loader.py`, `src/tm/translation_memory.py`.

## Steps
1) Run tests with coverage (pyproject markers configured):
   ```bash
   pytest -q --cov=src
   ```
2) Explore the architecture notes under `docs/architecture/` for parser, segment extractor, reconstruction, and validation flows.
3) Use the canonical references:
   - Config: [reference/config.md](../reference/config.md)
   - CLI flags: [reference/cli.md](../reference/cli.md)
   - File contracts: [reference/file-contracts.md](../reference/file-contracts.md)
4) Follow docs standards when adding docs: [development/docs-standards.md](../development/docs-standards.md) and `_audit/style_guide.md`.

## Next Steps
- Scripts catalog: [development/scripts.md](../development/scripts.md)
- Testing details: [development/testing.md](../development/testing.md)
