# User Quickstart (CLI)

Applies to translators running the CLI locally or in CI. CLI defaults are defined in `src/cli.py`.

## Prerequisites
- Python 3.10+ and project dependencies installed (`pip install -r requirements/cpu.txt` or `gpu.txt`).
- Config files present in `./config` (global.yaml, validation.yaml, terminology.yaml, site_profiles/*.yaml).
- Source content available locally.

## Steps
1) Identify the site profile ID (e.g., `products.aspose.net`) from `config/site_profiles/`.
2) (Optional) Override source/target languages via env vars: `SITE_<SITE>_DEFAULT_SOURCE_LANG`, `SITE_<SITE>_TARGET_LANGS` (src/utils/config_loader.py).
3) Run translation with CLI overrides as needed:
   ```bash
   translate-hugo --site products.aspose.net \
     --input ./samples/products.aspose.net/en/sample-live-product-catalog-overview.md \
     --target-langs de fr \
     --validation-mode strict \
     --enable-terminology \
     --dry-run
   ```
4) Review logs for validation decisions and output paths (see [CLI Reference](../reference/cli.md) for all flags).

## What’s Next
- Need directory translation or retries? See [CLI Reference](../reference/cli.md).
- Want to understand where files are written? See [File Contracts](../reference/file-contracts.md).
