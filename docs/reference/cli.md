# CLI Reference (translate-hugo)

Source of truth: `src/cli.py` (argument parser and execution).

## Usage
```
translate-hugo --site <site-id> [options]
```

## Required
- `--site SITE` — Site profile ID (e.g., `products.aspose.net`).

## Input / Targets
- `--input PATH` — Source file or directory. Defaults to first `content_roots` entry from the site profile.
- `--target-langs LANG [LANG ...]` — Override target languages (space-separated).
- `--output PATH` — Output directory override (otherwise determined by site profile/output layout).
- `--config-root PATH` — Config root directory (default `./config`).

## Validation Control
- `--validation-mode {strict,normal,lenient,off}` — Override validation strictness (affects decision rules).
- `--disable-validation` — Disable validation entirely (equivalent to `--validation-mode off`).
- `--force-accept` — Accept all translations without validation (ignore all validation errors).
- `--strict-reject` — Reject translations on any validation issue (no retries, fail fast).
- `--validation-config PATH` — Custom `validation.yaml` path.
- `--max-retries N` — Override retry attempts (0-5). Applied to decision engine init.

## Terminology Control
- `--enable-terminology` — Force-enable terminology preservation/validation.
- `--disable-terminology` — Force-disable terminology preservation/validation.
- `--terminology-mode {protect,validate,both,none}` — Override terminology mode.
- `--terminology-config PATH` — Custom `terminology.yaml` path.

## Model Control
- `--model MODEL_ID` — Override translation model (e.g., m2m100_1.2b, nllb_200_600m).
- `--max-tokens N` — Override maximum new tokens for translation model (default: 512).
- `--batch-size N` — Override batch size for translation (default: auto-detected based on RAM).
- `--sort-segments-by-length` — Sort segments by length (shortest first) before translation for improved GPU batching efficiency. Recommended for large jobs (1000+ segments) with high length variance. **Performance impact:** 0-20% throughput improvement on heterogeneous corpora. See [Segment Sorting Guide](../features/segment-sorting.md) for details.
- `--no-sort-segments-by-length` — Explicitly disable segment sorting (override config file setting). Processes segments in document order (default behavior).

## Post-Translation Verification
- `--verify` — Enable post-translation verification (detects mixed-language, untranslated segments).
- `--fix` — Automatically retry failed verification (requires --verify).
- `--verification-report PATH` — Output verification report to file (JSON or Markdown based on extension).

## Output Control
- `--dry-run` — Preview decisions without writing files.
- `--save-rejected` — Save rejected translations to disk for debugging.

## Logging
- `--log-level {DEBUG,INFO,WARNING,ERROR}` — Default `INFO`.
- `--log-file PATH` — Write logs to file instead of stdout.

## Examples
```
# Strict validation with terminology enabled
translate-hugo --site products.aspose.net \
  --validation-mode strict \
  --enable-terminology \
  --target-langs de fr

# Disable validation for a quick check
translate-hugo --site products.aspose.net --disable-validation

# Custom configs with dry-run
translate-hugo --site products.aspose.net \
  --input ./samples/products.aspose.net/en/sample-live-product-catalog-overview.md \
  --validation-config ./config/validation.yaml \
  --terminology-config ./config/terminology.yaml \
  --dry-run

# Enable segment sorting for large translation job
translate-hugo --site products.aspose.net \
  --target-langs es fr de \
  --sort-segments-by-length
```

## Behavior Notes
- Config paths from CLI overwrite defaults before site profiles are loaded (see `CLIConfigOverrides.apply_to_config_service`).
- Validation/terminology flags set booleans and mode overrides passed into `TranslationEngine`.
- If no `--input` is provided, the CLI uses the first `content_root` from the site profile; when a directory is given, all `.md` files are processed.
- Telemetry/logging setup occurs before translation; `--dry-run` still parses/validates but skips writes.
- **Segment Sorting:** CLI flags (`--sort-segments-by-length`, `--no-sort-segments-by-length`) override config file settings (`body_rules.sort_segments_by_length`). When neither flag is specified, the config value is used (default: `false`, document order).
