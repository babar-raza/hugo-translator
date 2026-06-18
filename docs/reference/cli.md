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
- `--auto-select-model` — 📋 Automatically select best model per target language (uses Opus when available, falls back to multilingual). Mutually exclusive with `--model`.
- `--device {auto,cpu,cuda}` — 📋 Device for model inference: `auto` (default), `cpu`, or `cuda`. `auto` selects CUDA if available.
- `--load-mode {auto,fp16,fp32,int8}` — 📋 Model precision/quantization mode. `auto` selects best available. `fp16` reduces memory at slight quality cost. `int8` maximises memory savings.

## Post-Translation Verification
- `--verify` — Enable post-translation verification (detects mixed-language, untranslated segments).
- `--fix` — Automatically retry failed verification (requires --verify).
- `--verification-report PATH` — Output verification report to file (JSON or Markdown based on extension).

## Output Control
- `--dry-run` — Preview decisions without writing files.
- `--save-rejected` — Save rejected translations to disk for debugging.
- `--max-files N` — 📋 Maximum number of files to process (0 = unlimited, default: 0). Files are selected deterministically by sorted path for reproducibility. Useful for sampling and testing.

## Logging
- `--log-level {DEBUG,INFO,WARNING,ERROR}` — Default `INFO`.
- `--log-file PATH` — Write logs to file instead of stdout.

## Progress & Metrics
- `--metrics-file PATH` — 📋 Write metrics to file. Creates `PATH_current.json` (current snapshot) and `PATH.ndjson` (append-only stream).
- `--metrics-interval SECS` — 📋 Metrics update interval in seconds (default: 2.0). Controls write frequency of `--metrics-file` snapshots.
- `--metrics-only` — 📋 Suppress normal log output; emit only a compact metrics line per interval. Designed for use in a second terminal alongside the main process.
- `--no-progress` — 📋 Disable progress tracking and ETA display entirely.

## Resume Control (Crash Recovery)
- `--resume` — 📋 Resume from previous progress file if available (default: enabled). Skips already-completed files.
- `--no-resume` — 📋 Ignore any previous progress and start fresh (equivalent to `--resume` off).
- `--force-restart` — 📋 Clear all stored progress for the site and restart from the beginning. Overrides `--resume`.
- `--progress-dir DIR` — 📋 Directory to store per-site progress files (default: `.translation_progress`).

## Git Change Detection
- `--changed-since SHA` — 📋 Only translate files changed since the given Git commit SHA. Runs `git diff` in the content repository; falls back to full scan on failure. Example: `--changed-since $GITHUB_EVENT_BEFORE` for CI incremental runs.

## Translation Cache Control
- `--force-retranslate` — 📋 Bypass cache lookup and force a fresh translation from the model. Cache is still updated with the new result.
- `--cache-write-mode {auto,always,never}` — 📋 Cache write strategy: `auto` (write if entry missing, default), `always` (overwrite existing entries), `never` (read-only; no cache updates).
- `--disable-content-hash` — 📋 Disable content-hash-based change detection; use file modification time only.
- `--rebuild-content-hashes` — 📋 Ignore all stored content hashes and recompute from disk (forces a full metadata rebuild).
- `--validate-output-integrity` — 📋 Validate translated output file integrity to detect manual post-translation edits.

## Multi-Language Processing
- `--parallel-languages N` — 📋 Process up to N languages in parallel (0 = disabled, default). Mutually exclusive with `--global-lang-rounds`.
- `--global-lang-rounds N` — 📋 Process N texts per language in round-robin fashion (0 = disabled, default). Mutually exclusive with `--parallel-languages`.
- `--global-lang-sort {asc,desc}` — 📋 When using `--global-lang-rounds`, sort languages by missing-translation count: `desc` = most-missing first (default), `asc` = least-missing first.
- `--fail-fast` — 📋 Stop multi-language processing on the first language failure (default: True).
- `--no-fail-fast` — 📋 Continue processing remaining languages even when one language fails.

## Benchmarking & Production Metrics
- `--enable-production-metrics` — 📋 Enable production metrics recording to the benchmark database (opt-in; overrides config). Records timing and quality data for benchmarking analysis.

## Git Commit Control
- `--auto-commit` — 📋 Enable automatic git commits after successful translation. Overrides `auto_commit` setting in site profile / global config.
- `--no-commit` — 📋 Disable automatic git commits for this run (override config default).
- `--commit-message TEXT` — 📋 Override the commit message template for automatic commits.

## Miscellaneous
- `--version` — Show program version (from `pyproject.toml`) and exit.

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
