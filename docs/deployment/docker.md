# Docker Volume Management

## Overview

The Hugo Translation System uses Docker named volumes for persistent data storage across container lifecycle events (restarts, rebuilds, updates). This document describes the volume architecture and management best practices.

## Volume Architecture

### Named Volumes

| Volume Name | Purpose | Mount Point | Shared Across |
|-------------|---------|-------------|---------------|
| `tm_data` | Translation Memory cache (L1/L2/L3 indices) | `/data/tm` | All services |
| `model_cache` | Downloaded ML models (M2M100, mBART, etc.) | `/data/models` | All services |
| `metadata_storage` | Content hash metadata (.translation_metadata.json) | `/data/metadata` | All services |
| `artifacts` | Debug artifacts, flow outputs | `/data/artifacts` | Orchestrator only |
| `logs` | NDJSON log files | `/data/logs` | All services |
| `redis_data` | Job queue persistence | `/data` | Redis only |
| `prometheus_data` | Metrics time-series database | `/prometheus` | Prometheus only |
| `grafana_data` | Dashboards and configuration | `/var/lib/grafana` | Grafana only |

### Bind Mounts

| Host Path | Container Path | Purpose | Access |
|-----------|----------------|---------|--------|
| `./config` | `/app/config` | Site profiles, model registry, global config | Read-only |
| `D:/onedrive/Documents/GitHub/aspose.net/content` | `/content` | Source markdown files (Hugo content directory) | Read-write |

## Content Hash Metadata Volume

### Purpose

The `metadata_storage` volume stores content hash metadata separately from content and output files. This separation provides:

1. **Isolation**: Metadata persists independently of content directory changes
2. **Performance**: Dedicated volume can be optimized for small file I/O
3. **Backup**: Separate backup/restore lifecycle from content
4. **Security**: Metadata not exposed to content bind mount

### Configuration

Enable dedicated metadata directory in `config/global.yaml`:

```yaml
content_hash_tracking:
  enabled: true
  metadata_dir: "/data/metadata"  # Docker volume mount point
  metadata_file: ".translation_metadata.json"
```

If `metadata_dir` is empty, metadata is stored alongside output files (legacy behavior).

### Data Structure

```
/data/metadata/
└── .translation_metadata.json  # Single file containing all source file hashes
```

**Schema (v1.0)**:
```json
{
  "version": "1.0",
  "created_at": "2025-01-15T10:30:00Z",
  "updated_at": "2025-01-15T14:22:00Z",
  "source_files": {
    "/content/en/docs/example.md": {
      "hash": "a1b2c3d4e5f6...",
      "algorithm": "md5",
      "size": 4096,
      "mtime": 1705323600.0,
      "last_checked": "2025-01-15T14:22:00Z"
    }
  }
}
```

## Volume Lifecycle Management

### Creating Volumes

Volumes are created automatically by Docker Compose on first `docker-compose up`:

```bash
docker-compose up -d
```

Verify volumes:

```bash
docker volume ls | grep hugo-translator
```

### Inspecting Volumes

View volume details:

```bash
docker volume inspect hugo-translator_metadata_storage
```

Output:
```json
[
  {
    "CreatedAt": "2025-01-15T10:00:00Z",
    "Driver": "local",
    "Mountpoint": "/var/lib/docker/volumes/hugo-translator_metadata_storage/_data",
    "Name": "hugo-translator_metadata_storage",
    "Scope": "local"
  }
]
```

### Backing Up Volumes

**Metadata Volume**:
```bash
# Create backup
docker run --rm \
  -v hugo-translator_metadata_storage:/source:ro \
  -v $(pwd)/backups:/backup \
  alpine tar czf /backup/metadata-$(date +%Y%m%d).tar.gz -C /source .

# Restore from backup
docker run --rm \
  -v hugo-translator_metadata_storage:/target \
  -v $(pwd)/backups:/backup \
  alpine tar xzf /backup/metadata-20250115.tar.gz -C /target
```

**TM Data Volume** (large - use rsync or selective backup):
```bash
# Backup L3 FAISS index only
docker run --rm \
  -v hugo-translator_tm_data:/source:ro \
  -v $(pwd)/backups:/backup \
  alpine tar czf /backup/tm-l3-$(date +%Y%m%d).tar.gz -C /source l3_faiss
```

### Pruning Volumes

**WARNING**: This deletes all data. Ensure backups exist.

```bash
# Stop services
docker-compose down

# Remove all volumes (DESTRUCTIVE)
docker-compose down -v

# Remove specific volume
docker volume rm hugo-translator_metadata_storage
```

### Migrating Volumes Between Hosts

**Export**:
```bash
# Create portable archive
docker run --rm \
  -v hugo-translator_metadata_storage:/data:ro \
  -v $(pwd):/backup \
  alpine tar czf /backup/metadata-export.tar.gz -C /data .
```

**Import**:
```bash
# On new host, create volume and extract
docker volume create hugo-translator_metadata_storage
docker run --rm \
  -v hugo-translator_metadata_storage:/data \
  -v $(pwd):/backup \
  alpine tar xzf /backup/metadata-export.tar.gz -C /data
```

## Volume Sizing and Monitoring

### Expected Sizes

| Volume | Typical Size | Growth Rate |
|--------|--------------|-------------|
| `metadata_storage` | 1-10 MB | Low (grows with # source files) |
| `tm_data` | 500 MB - 10 GB | Medium (grows with translations) |
| `model_cache` | 2-20 GB | Low (static after download) |
| `logs` | 100 MB - 1 GB | High (log rotation configured) |
| `redis_data` | 10-500 MB | Medium (queue size dependent) |

### Monitoring Disk Usage

**All volumes**:
```bash
docker system df -v | grep hugo-translator
```

**Specific volume**:
```bash
docker run --rm \
  -v hugo-translator_metadata_storage:/data:ro \
  alpine du -sh /data
```

**Inside running container**:
```bash
docker exec hugo-translator-orchestrator df -h /data/metadata
```

### Cleanup Strategies

**Logs** (auto-rotated, see `docker-compose.yml`):
```yaml
logging:
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "3"
```

**TM Cache** (manual cleanup - see CHH-05):
```bash
# Remove old L2 entries (example - not implemented yet)
docker exec hugo-translator-orchestrator \
  python -m src.tm.cleanup --days 90
```

## Troubleshooting

### Metadata File Not Found

**Symptom**: `WARNING: Metadata file not found, falling back to mtime`

**Cause**: Volume mount missing or metadata_dir misconfigured

**Fix**:
```bash
# Verify volume mounted
docker exec hugo-translator-orchestrator ls -la /data/metadata

# Check config
docker exec hugo-translator-orchestrator \
  python -c "from src.utils.config_loader import get_global_config; \
             print(get_global_config()['content_hash_tracking']['metadata_dir'])"

# Expected: /data/metadata
```

### Permission Denied

**Symptom**: `PermissionError: [Errno 13] Permission denied: '/data/metadata/.translation_metadata.json'`

**Cause**: Volume created with wrong ownership

**Fix**:
```bash
# Recreate volume with correct permissions
docker-compose down
docker volume rm hugo-translator_metadata_storage
docker-compose up -d

# Or fix permissions in running container
docker exec -u root hugo-translator-orchestrator \
  chown -R 1000:1000 /data/metadata
```

### Metadata Corruption

**Symptom**: `ERROR: Failed to load metadata: JSONDecodeError`

**Cause**: Container crash during write, disk full, filesystem error

**Fix**:
```bash
# Automatic recovery: Engine falls back to mtime and recreates metadata
# Manual recovery: Delete corrupted file, engine will rebuild
docker exec hugo-translator-orchestrator \
  rm /data/metadata/.translation_metadata.json

# Trigger rebuild by running translation
docker exec hugo-translator-orchestrator \
  python -m src.cli example.com --target-lang es --force-retranslate
```

### Volume Full

**Symptom**: `OSError: [Errno 28] No space left on device`

**Fix**:
```bash
# Check disk usage
docker exec hugo-translator-orchestrator df -h

# Prune Docker system (removes unused images, containers, volumes)
docker system prune -a

# Increase Docker Desktop disk limit (Settings > Resources > Disk image size)
# Or migrate to larger host
```

## Multi-Worker Considerations

### Shared Volume Access

All services (orchestrator + workers) mount volumes in **read-write** mode. This enables:
- Workers to read TM cache and models
- Workers to write log files
- Orchestrator to coordinate via Redis queue

### Race Condition Protection

**Current Status** (CHH-02): Metadata writes are NOT protected by Redis locking.

**Risk**: Concurrent translations may corrupt metadata file.

**Mitigation** (implemented in CHH-02):
- Redis-based file locking for metadata writes
- Retry logic with exponential backoff
- Atomic writes (temp file + rename)

**Workaround** (until CHH-02):
- Run single worker: `docker-compose up orchestrator worker-cpu`
- Disable GPU worker: `docker-compose --profile "" up`

## Best Practices

1. **Regular backups**: Backup `metadata_storage` and `tm_data` weekly
2. **Monitor disk usage**: Set up alerts for volumes >80% full
3. **Test restores**: Verify backups are valid before disaster strikes
4. **Separate concerns**: Keep content in bind mount, metadata in volume
5. **Version control**: Store `docker-compose.yml` and configs in Git
6. **Document changes**: Update this file when adding new volumes
7. **Prune regularly**: Remove unused images/containers to free space

## References

- Docker Compose Volumes: https://docs.docker.com/compose/compose-file/compose-file-v3/#volumes
- Content Hash Tracking: [docs/architecture/content-hash-tracking.md](../architecture/content-hash-tracking.md)
- Model Storage: [docs/deployment/MODEL_STORAGE.md](MODEL_STORAGE.md)
