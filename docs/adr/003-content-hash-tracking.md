# ADR-003: Content Hash Tracking

- **Status:** Accepted
- **Date:** 2026-04-20
- **Decision Makers:** Translation System Team

## Context

The translation system detects which source files need retranslation by comparing modification times. This approach has false positives: `git checkout`, `touch`, file copy, and OneDrive sync all update mtime without changing content. Each false positive triggers an unnecessary MT inference cycle (seconds per file, GPU compute).

On a typical docs.aspose.net run with ~12,000 source files, mtime-based detection produced 5-15% false positives, wasting 10-30 minutes of GPU time per run.

## Decision

Implement content hash tracking (CHH-01) as the primary change detection mechanism:

- Compute SHA-256 of each source file's content after normalization (strip trailing whitespace, normalize line endings).
- Store hashes in `.translation_metadata.json` in the output directory alongside translations.
- On each run, compare current hash to stored hash. Only retranslate if hash differs.
- First run after enabling: hash all files (one-time ~1% performance cost to build the hash map).
- Opt-out: `--disable-content-hash` CLI flag or `enable_content_hash_tracking: false` in config.
- Enabled by default for all new deployments.

Production hardening (CHH-02 through CHH-05):
- **CHH-02:** Redis distributed locking for multi-worker metadata updates (Docker path only).
- **CHH-03:** Dedicated Docker volume for metadata persistence across container recreation.
- **CHH-04:** Prometheus metrics for hash operations (compute duration, cache hits/misses, change rate).
- **CHH-05:** Automatic cleanup of stale metadata entries (files deleted from source).

## Consequences

**Positive:**
- Eliminates false-positive retranslations from mtime changes
- 5-15% reduction in unnecessary MT inference per run
- Metadata file is human-readable JSON (debuggable)
- Opt-out flag available for environments where hashing adds unwanted overhead

**Negative:**
- First run after enabling is slightly slower (must hash all files)
- `.translation_metadata.json` added to output directories (one file per content root)
- Multi-worker deployments require Redis for safe concurrent metadata updates (CHH-02)
- Hash computation adds ~1ms per file (negligible vs MT inference time)

## References

- CHANGELOG entry: `CHANGELOG.md` (CHH-01 through CHH-05)
- Implementation: `src/translation_engine/engine.py` (content hash integration)
- Prometheus metrics: `docker/grafana/dashboards/content-hash-tracking.json`
- Configuration: `config/global.yaml` (`features.enable_content_hash_tracking`)
