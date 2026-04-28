# Content Hash Tracking Guide

## Overview

Content hash tracking is a feature that uses cryptographic hashing to accurately detect file changes, eliminating false positives from timestamp-based change detection.

### The Problem

Traditional modification time (mtime) based change detection triggers retranslation when:
- Files are touched without content changes (`touch file.md`)
- Git operations change timestamps (`git checkout`, `git pull`)
- File copies preserve content but update mtime
- CI/CD systems regenerate files with identical content

This causes unnecessary retranslations, wasting time and API costs.

### The Solution

Content hash tracking computes a cryptographic hash (MD5 or SHA256) of file contents and stores it in persistent metadata. When checking if a file needs retranslation, the system:

1. **Fast path**: Compares mtime first (if unchanged, skip hash computation)
2. **Slow path**: Computes current hash and compares with stored hash
3. **Decision**: Only retranslate if hash changed (actual content change)

## Benefits

- ✅ **Accurate change detection**: No false positives from timestamp changes
- ✅ **Performance optimized**: Fast-path mtime check avoids redundant hashing
- ✅ **Git-friendly**: Works seamlessly with `git checkout`, `git pull`, etc.
- ✅ **CI/CD compatible**: Handles file regeneration correctly
- ✅ **Graceful degradation**: Falls back to mtime if metadata corrupted
- ✅ **Output integrity**: Optionally detect manual edits to translated files

## Configuration

### YAML Configuration

Add to `config/global.yaml`:

```yaml
# Feature flag (master toggle)
features:
  enable_content_hash_tracking: false  # Set to true to enable

# Detailed configuration
content_hash_tracking:
  # Hash algorithm: "md5" (fast, ~500 MB/s) or "sha256" (secure but slower)
  hash_algorithm: "md5"

  # Metadata file location (relative to output directory)
  metadata_file: ".translation_metadata.json"

  # In-memory LRU cache size for file hashes
  in_memory_cache_size: 1000

  # Update metadata even when skipping translation
  update_metadata_on_skip: true

  # Validate translated output integrity (detect manual edits)
  validate_output_integrity: false

  # Fall back to mtime if metadata corrupted
  fallback_to_mtime: true

  # Fast-path optimization: only hash if mtime changed
  fast_path_mtime_check: true
```

### CLI Flags

Override configuration at runtime:

```bash
# Disable content hash tracking for this run
translate-hugo --site example.com --disable-content-hash

# Rebuild content hashes from scratch (ignores stored metadata)
translate-hugo --site example.com --rebuild-content-hashes

# Enable output integrity validation
translate-hugo --site example.com --validate-output-integrity
```

## Use Cases

### 1. Git Workflows

**Problem**: `git checkout` changes file mtimes even when content unchanged.

**Solution**: Content hash tracking detects no actual changes.

```bash
# Switch branches (timestamps change)
git checkout feature-branch

# Translate (skips files with unchanged content)
translate-hugo --site example.com
```

### 2. CI/CD Pipelines

**Problem**: CI systems clone repositories fresh, all files have current timestamps.

**Solution**: Persist metadata file (`.translation_metadata.json`) in output directory, commit it to version control.

```bash
# First run: translate all files, create metadata
translate-hugo --site example.com

# Commit metadata
git add output/.translation_metadata.json
git commit -m "Add translation metadata"

# Subsequent CI runs: only changed files retranslated
```

### 3. Incremental Builds

**Problem**: Build systems regenerate files even if content unchanged.

**Solution**: Content hash detects identical regenerated files.

```bash
# Build regenerates Markdown from source (timestamps updated)
make build

# Translate (skips files with unchanged content)
translate-hugo --site example.com
```

### 4. Collaborative Editing

**Problem**: Multiple editors touch files, creating timestamp noise.

**Solution**: Only actual content changes trigger retranslation.

```bash
# Editor 1: touches file without changes
touch content/blog/post.md

# Editor 2: translates (skips unchanged file)
translate-hugo --site example.com
```

## Performance Impact

### Hash Computation Speed

- **MD5**: ~500 MB/s on typical hardware
  - 10 MB file: <20ms
  - 100 KB file: <0.5ms

- **SHA256**: ~200 MB/s (slower but more secure)
  - 10 MB file: ~50ms
  - 100 KB file: ~1ms

### Overall Overhead

With fast-path mtime optimization:
- **First run** (no metadata): Hash all files (~1-2% overhead)
- **Subsequent runs** (metadata exists): Mtime check only (~0.1% overhead)
- **Files touched** (content unchanged): Hash recomputed (~5% overhead for those files)

**Recommendation**: Use MD5 for maximum performance. SHA256 only needed if cryptographic security is required.

## Troubleshooting

### Metadata File Corrupted

**Symptom**: Warning log: "Metadata corrupted, rebuilding"

**Cause**: `.translation_metadata.json` file damaged (disk error, interrupted write, manual edit)

**Solution**: Automatic recovery with empty metadata. System rebuilds hashes on next run.

**Manual recovery**:
```bash
# Delete corrupted metadata
rm output/.translation_metadata.json

# Rebuild from scratch
translate-hugo --site example.com --rebuild-content-hashes
```

### Hash Mismatch (False Positives)

**Symptom**: Files retranslated even though content appears unchanged

**Cause**: Line ending changes (CRLF ↔ LF), encoding changes, invisible characters

**Investigation**:
```bash
# Check file hash manually
md5sum source/file.md

# Compare with stored hash
cat output/.translation_metadata.json | jq '.files["source/file.md"].source.hash'

# Check for line ending issues
file source/file.md  # Should show: "text/plain; charset=utf-8"
```

**Solution**: Normalize line endings in repository (`.gitattributes`):
```
*.md text eol=lf
```

### Performance Degradation

**Symptom**: Translation slower after enabling content hash tracking

**Cause**: Large files or slow disk I/O

**Solutions**:
1. **Use MD5 instead of SHA256**:
   ```yaml
   content_hash_tracking:
     hash_algorithm: "md5"  # 2.5x faster than SHA256
   ```

2. **Enable fast-path mtime optimization** (default):
   ```yaml
   content_hash_tracking:
     fast_path_mtime_check: true
   ```

3. **Increase cache size** for large projects:
   ```yaml
   content_hash_tracking:
     in_memory_cache_size: 5000  # Default: 1000
   ```

### Metadata Not Persisting

**Symptom**: Every run behaves like first run (no skips)

**Cause**: Metadata file not writable or output directory incorrect

**Investigation**:
```bash
# Check metadata file exists
ls -l output/.translation_metadata.json

# Check permissions
ls -ld output/
```

**Solution**: Ensure output directory is writable:
```bash
chmod -R u+w output/
```

## FAQ

### Q: Should I commit `.translation_metadata.json` to version control?

**A**: For CI/CD: **Yes**, commit it to avoid rehashing on every CI run.

For local development: **Optional**. Add to `.gitignore` if you want clean diffs.

### Q: What happens if I delete the metadata file?

**A**: System starts fresh, hashes all files on next run. No data loss, just performance cost of rehashing.

### Q: Can I use SHA256 instead of MD5?

**A**: Yes, configure `hash_algorithm: "sha256"`. Slower but more secure. MD5 is sufficient for change detection.

### Q: Does this work with Translation Memory (TM)?

**A**: Yes, both systems work independently:
- Content hash: File-level change detection
- TM: Segment-level reuse

Both reduce redundant work.

### Q: What's the metadata file format?

**A**: JSON with schema version 1.0:
```json
{
  "schema_version": "1.0",
  "site_id": "example.com",
  "files": {
    "source/file.md": {
      "source": {
        "path": "source/file.md",
        "hash": "abc123...",
        "last_modified": "2025-01-15T10:30:00Z",
        "size_bytes": 1024
      },
      "outputs": {
        "es": {
          "path": "output/es/file.md",
          "hash": "def456...",
          "translated_at": "2025-01-15T10:31:00Z",
          "source_hash_at_translation": "abc123...",
          "status": "success"
        }
      }
    }
  }
}
```

### Q: How do I rebuild hashes from scratch?

**A**: Use `--rebuild-content-hashes` flag:
```bash
translate-hugo --site example.com --rebuild-content-hashes
```

This deletes existing metadata and recomputes all hashes.

## Migration Guide

### Enabling for Existing Projects

1. **Enable feature flag** in `config/global.yaml`:
   ```yaml
   features:
     enable_content_hash_tracking: true
   ```

2. **First run**: All files will be hashed (one-time cost)
   ```bash
   translate-hugo --site example.com
   ```

3. **Verify metadata created**:
   ```bash
   ls -lh output/.translation_metadata.json
   ```

4. **Subsequent runs**: Only changed files retranslated

### Disabling Content Hash Tracking

1. **Set feature flag to false**:
   ```yaml
   features:
     enable_content_hash_tracking: false
   ```

2. **Or use CLI flag**:
   ```bash
   translate-hugo --site example.com --disable-content-hash
   ```

3. **Optional**: Delete metadata file to reclaim space:
   ```bash
   rm output/.translation_metadata.json
   ```

System will fall back to mtime-based detection.

## Breaking Change Notice (v2.0)

Starting in v2.0, content hash tracking is **enabled by default**.

### Impact
- First run after upgrade will hash all source files (one-time cost)
- Metadata file created: `output/.translation_metadata.json`
- Performance overhead: <2% (see benchmarks)

### Migration Steps
1. Upgrade to v2.0
2. First translation run hashes all files (~1-2% slower)
3. Subsequent runs benefit from accurate change detection

### Rollback (if needed)
If you experience issues, disable temporarily:
```bash
# Option 1: CLI flag
translate-hugo --site example.com --disable-content-hash

# Option 2: Config change
# In config/global.yaml, set:
features:
  enable_content_hash_tracking: false
```

### Verification
```bash
# Check metadata file created
ls -lh output/.translation_metadata.json

# Verify hash checks in logs
grep "content unchanged" logs/translation.log
```

## Advanced Topics

### Custom Hash Algorithm

If you need a different algorithm, extend `src/utils/content_hash.py`:

```python
def compute_file_hash(file_path: Path, algorithm: HashAlgorithm = "md5") -> str:
    if algorithm == "blake2b":
        hasher = hashlib.blake2b()
    # ... existing algorithms ...
```

### Output Integrity Validation

Detect manual edits to translated files:

```yaml
content_hash_tracking:
  validate_output_integrity: true
```

When enabled, system compares stored output hash with current file. If mismatch detected, triggers retranslation.

**Warning**: May increase overhead if translations are frequently regenerated.

## See Also

- [Architecture Documentation](../architecture/content-hash-tracking.md)
- [Configuration Guide](../../config/global.yaml)
- [Translation Engine Documentation](../architecture/translation-engine.md)
