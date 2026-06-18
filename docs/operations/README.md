# Hugo Translation System - Operations Manual

**Version:** 1.0.0
**Last Updated:** 2025-11-21

> **Quick Reference**: For daily operational checklist and step-by-step procedures, see [DAILY_OPERATIONS.md](DAILY_OPERATIONS.md). This manual provides comprehensive guidance across all time scales (daily, weekly, monthly maintenance).

---

## Table of Contents

1. [Daily Operations](#daily-operations)
2. [Health Monitoring](#health-monitoring)
3. [Maintenance Tasks](#maintenance-tasks)
4. [Backup and Restore](#backup-and-restore)
5. [Common Operational Tasks](#common-operational-tasks)
6. [Emergency Procedures](#emergency-procedures)
7. [Performance Tuning](#performance-tuning)
8. [Capacity Planning](#capacity-planning)

---

## Daily Operations

### Morning Health Check Routine

Perform these checks at the start of each day:

```bash
#!/bin/bash
# daily_health_check.sh

echo "=== Hugo Translation System - Daily Health Check ==="
echo "Date: $(date)"
echo ""

# 1. Check all services are running
echo "1. Checking service status..."
docker-compose ps
echo ""

# 2. Check container health
echo "2. Checking container health..."
docker-compose ps | grep -E '(healthy|Up)'
echo ""

# 3. Check recent logs for errors
echo "3. Checking for errors in last 24h..."
docker-compose logs --since=24h | grep -i error | tail -20
echo ""

# 4. Check disk space
echo "4. Checking disk space..."
df -h | grep -E '(Filesystem|/data)'
echo ""

# 5. Check TM statistics
echo "5. Checking Translation Memory stats..."
docker-compose exec -T orchestrator python -c "
from pathlib import Path
from src.observability.tm_admin import TranslationMemoryAdmin
from src.tm.translation_memory import create_translation_memory

tm = create_translation_memory(Path('/data/tm'))
admin = TranslationMemoryAdmin(tm)
stats = admin.get_statistics()

print(f'Total TM entries: {stats.total_entries:,}')
print(f'L1 hit rate: {stats.l1_hit_rate:.2%}')
print(f'L2 hit rate: {stats.l2_hit_rate:.2%}')
print(f'L3 hit rate: {stats.l3_hit_rate:.2%}')
"
echo ""

# 6. Check recent translation activity
echo "6. Recent translation activity..."
docker-compose exec -T orchestrator python -c "
from pathlib import Path
from src.observability.metrics import MetricsCollector

collector = MetricsCollector()
metrics = collector.get_summary(hours=24)

print(f'Translations (24h): {metrics.get(\"translations_total\", 0)}')
print(f'Files processed: {metrics.get(\"files_processed\", 0)}')
print(f'Errors: {metrics.get(\"errors_total\", 0)}')
"
echo ""

echo "=== Health Check Complete ==="
```

### Daily Metrics Review

Check key performance indicators:

```bash
# Access Prometheus
open http://localhost:9090

# View key metrics:
# - translation_throughput_total
# - tm_hit_rate
# - job_queue_depth
# - translation_errors_total
# - worker_utilization
```

### Daily Backup

Run automated backup:

```bash
# Run daily backup script
./scripts/backup.sh daily

# Verify backup created
ls -lh backups/daily/$(date +%Y%m%d)*

# Check backup size
du -sh backups/daily/$(date +%Y%m%d)*
```

---

## Health Monitoring

### Service Health Checks

**Check individual service health:**

```bash
# Orchestrator
docker-compose exec orchestrator python -c "
from pathlib import Path
from src.orchestrator.orchestrator import TranslationOrchestrator

# Check can initialize
print('✓ Orchestrator healthy')
"

# Worker
docker-compose exec worker-cpu-1 python -c "
from src.workers.translation_worker import TranslationWorker

worker = TranslationWorker()
worker.setup()
print('✓ Worker healthy')
worker.shutdown()
"

# Translation Memory
docker-compose exec worker-cpu-1 python -c "
from pathlib import Path
from src.tm.translation_memory import create_translation_memory

tm = create_translation_memory(Path('/data/tm'))
result = tm.lookup('test', 'en', 'fr', 'test')
print('✓ Translation Memory healthy')
"
```

### Resource Monitoring

**Monitor resource usage:**

```bash
# Container resource usage
docker stats --no-stream

# Disk usage
docker-compose exec orchestrator df -h /data

# Memory usage per service
docker-compose exec worker-cpu-1 free -h

# GPU usage (if applicable)
docker-compose exec worker-gpu-1 nvidia-smi
```

### Log Monitoring

**Monitor logs for issues:**

```bash
# Watch logs in real-time
docker-compose logs -f orchestrator worker-cpu-1

# Search for errors
docker-compose logs --since=1h | grep -i error

# Search for warnings
docker-compose logs --since=1h | grep -i warning

# View structured logs
docker-compose exec orchestrator tail -f /data/logs/translation.log | jq .
```

### Prometheus Alerts

**Check active alerts:**

```bash
# View active alerts
curl http://localhost:9090/api/v1/alerts | jq '.data.alerts[] | select(.state=="firing")'

# Check alert rules
curl http://localhost:9090/api/v1/rules | jq .
```

---

## Maintenance Tasks

### Weekly Maintenance

Perform these tasks weekly:

#### 1. Translation Memory Cleanup

```bash
# Remove old unused entries
docker-compose exec orchestrator python -c "
from pathlib import Path
from src.observability.tm_admin import TranslationMemoryAdmin
from src.tm.translation_memory import create_translation_memory

tm = create_translation_memory(Path('/data/tm'))
admin = TranslationMemoryAdmin(tm)

# Remove entries older than 90 days with <2 uses
result = admin.cleanup(
    max_age_days=90,
    min_usage_count=2,
    dry_run=False
)

print(f'Removed {result.removed_count} entries')
print(f'Freed {result.space_freed_mb}MB')
"
```

#### 2. Model Cache Management

```bash
# Check model cache size
docker-compose exec worker-cpu-1 du -sh /data/models/*

# Remove unused models (keep only actively used)
docker-compose exec worker-cpu-1 python -c "
from pathlib import Path
from src.model_runtime.loader import ModelLoader
from src.model_runtime.registry import ModelRegistry

registry = ModelRegistry(Path('/app/config/model_registry.yaml'))
loader = ModelLoader(registry)

# Clear cache of unused models
loader.clear_unused_models(keep_latest=2)
print('✓ Model cache cleaned')
"
```

#### 3. Log Rotation

```bash
# Rotate logs
docker-compose exec orchestrator python -c "
from pathlib import Path
import shutil
from datetime import datetime

logs_dir = Path('/data/logs')
archive_dir = logs_dir / 'archive' / datetime.now().strftime('%Y%m')
archive_dir.mkdir(parents=True, exist_ok=True)

# Move logs older than 7 days to archive
for log_file in logs_dir.glob('*.log'):
    age_days = (datetime.now() - datetime.fromtimestamp(log_file.stat().st_mtime)).days
    if age_days > 7:
        shutil.move(str(log_file), str(archive_dir / log_file.name))
        print(f'Archived {log_file.name}')
"
```

#### 4. Metrics Cleanup

```bash
# Prometheus data retention (configured in docker-compose.yml)
# Default: 30 days

# Check Prometheus storage size
docker-compose exec prometheus du -sh /prometheus

# Manual cleanup if needed
docker-compose exec prometheus promtool tsdb clean-tombstones /prometheus
```

### Monthly Maintenance

#### 1. Full TM Export

```bash
# Export all TM data for audit/backup
docker-compose exec orchestrator python -c "
from pathlib import Path
from src.observability.tm_admin import TranslationMemoryAdmin
from src.tm.translation_memory import create_translation_memory
from datetime import datetime

tm = create_translation_memory(Path('/data/tm'))
admin = TranslationMemoryAdmin(tm)

export_file = Path(f'/backups/tm-export-{datetime.now().strftime(\"%Y%m%d\")}.ndjson')
admin.export_all(export_file)
print(f'✓ Exported TM to {export_file}')
"
```

#### 2. Model Updates

```bash
# Check for model updates
docker-compose exec worker-cpu-1 python -c "
from pathlib import Path
from src.model_runtime.registry import ModelRegistry

registry = ModelRegistry(Path('/app/config/model_registry.yaml'))

for model in registry.list_models():
    print(f'{model.model_id}: {model.name}')
    # Check if updates available from HuggingFace
"

# Update specific model
docker-compose exec worker-cpu-1 python -c "
from pathlib import Path
from src.model_runtime.loader import download_model

download_model('m2m100_418m', force=True)
print('✓ Model updated')
"
```

#### 3. Configuration Review

```bash
# Review site profiles for optimization
docker-compose exec orchestrator python -c "
from pathlib import Path
from src.utils.config_loader import ConfigService

config = ConfigService(Path('/app/config'))

for site_id in config.list_sites():
    profile = config.get_site_profile(site_id)
    print(f'Site: {site_id}')
    print(f'  Languages: {len(profile.target_langs)}')
    print(f'  TM threshold: {profile.tm_prefs.semantic_threshold}')
    print()
"
```

### Quarterly Maintenance

#### 1. Performance Review

```bash
# Generate performance report
docker-compose exec orchestrator python scripts/generate_performance_report.py --period quarterly

# Review metrics:
# - Translation throughput trends
# - TM hit rate trends
# - Error rate trends
# - Resource utilization trends
```

#### 2. Capacity Planning Review

```bash
# Analyze growth trends
docker-compose exec orchestrator python -c "
from pathlib import Path
from src.observability.tm_admin import TranslationMemoryAdmin
from src.tm.translation_memory import create_translation_memory

tm = create_translation_memory(Path('/data/tm'))
admin = TranslationMemoryAdmin(tm)

stats = admin.get_statistics()
print(f'TM size: {stats.total_entries:,} entries')
print(f'Storage: {stats.storage_size_mb:.1f}MB')
print(f'Growth rate: {stats.daily_growth_rate:.1f} entries/day')

# Project 6 months
projected = stats.total_entries + (stats.daily_growth_rate * 180)
print(f'Projected size (6mo): {projected:,.0f} entries')
"
```

---

## Backup and Restore

### Backup Procedures

#### Full Backup

```bash
#!/bin/bash
# backup.sh - Full system backup

BACKUP_DIR="/backups/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

echo "Starting backup to $BACKUP_DIR"

# 1. Backup Translation Memory
echo "Backing up TM..."
docker-compose exec -T orchestrator tar -czf - /data/tm \
    > "$BACKUP_DIR/tm_data.tar.gz"

# 2. Backup Configuration
echo "Backing up configuration..."
tar -czf "$BACKUP_DIR/config.tar.gz" config/

# 3. Backup Environment
echo "Backing up environment..."
cp .env.production "$BACKUP_DIR/.env.production"

# 4. Backup Logs (last 30 days)
echo "Backing up logs..."
docker-compose exec -T orchestrator find /data/logs -name "*.log" -mtime -30 \
    -exec tar -czf - {} + > "$BACKUP_DIR/logs.tar.gz"

# 5. Export TM as NDJSON (human-readable)
echo "Exporting TM..."
docker-compose exec -T orchestrator python -c "
from pathlib import Path
from src.observability.tm_admin import TranslationMemoryAdmin
from src.tm.translation_memory import create_translation_memory

tm = create_translation_memory(Path('/data/tm'))
admin = TranslationMemoryAdmin(tm)
admin.export_all(Path('/tmp/tm_export.ndjson'))
" && docker-compose exec -T orchestrator cat /tmp/tm_export.ndjson \
    > "$BACKUP_DIR/tm_export.ndjson"

# 6. Generate manifest
cat > "$BACKUP_DIR/manifest.txt" <<EOF
Backup Date: $(date)
System Version: 1.0.0
TM Data: tm_data.tar.gz
Configuration: config.tar.gz
Environment: .env.production
Logs: logs.tar.gz
TM Export: tm_export.ndjson
EOF

# 7. Calculate checksums
cd "$BACKUP_DIR"
sha256sum *.tar.gz *.ndjson > checksums.sha256

echo "Backup completed: $BACKUP_DIR"
ls -lh "$BACKUP_DIR"
```

#### Incremental Backup (TM only)

```bash
#!/bin/bash
# backup_tm_incremental.sh

BACKUP_DIR="/backups/incremental"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"

# Backup only changed TM data
docker-compose exec -T orchestrator tar -czf - /data/tm \
    > "$BACKUP_DIR/tm_${TIMESTAMP}.tar.gz"

# Keep only last 7 incremental backups
cd "$BACKUP_DIR"
ls -t tm_*.tar.gz | tail -n +8 | xargs rm -f

echo "Incremental backup completed"
```

### Restore Procedures

#### Full Restore

```bash
#!/bin/bash
# restore.sh - Restore from backup

if [ -z "$1" ]; then
    echo "Usage: $0 <backup_directory>"
    exit 1
fi

BACKUP_DIR="$1"

if [ ! -d "$BACKUP_DIR" ]; then
    echo "Error: Backup directory not found: $BACKUP_DIR"
    exit 1
fi

echo "Restoring from $BACKUP_DIR"

# 1. Verify checksums
echo "Verifying checksums..."
cd "$BACKUP_DIR"
sha256sum -c checksums.sha256 || {
    echo "Error: Checksum verification failed"
    exit 1
}

# 2. Stop services
echo "Stopping services..."
cd -
docker-compose down

# 3. Restore Translation Memory
echo "Restoring TM..."
docker-compose up -d orchestrator
sleep 5
docker-compose exec -T orchestrator tar -xzf - -C / < "$BACKUP_DIR/tm_data.tar.gz"

# 4. Restore Configuration
echo "Restoring configuration..."
tar -xzf "$BACKUP_DIR/config.tar.gz"

# 5. Restore Environment
echo "Restoring environment..."
cp "$BACKUP_DIR/.env.production" .env.production

# 6. Restart all services
echo "Restarting services..."
docker-compose down
docker-compose up -d

# 7. Verify restoration
echo "Verifying restoration..."
sleep 10
docker-compose ps

echo "Restore completed from: $BACKUP_DIR"
```

### Backup Retention Policy

**Recommended retention:**

| Backup Type | Frequency | Retention | Location |
|-------------|-----------|-----------|----------|
| Full | Daily | 7 days | Local |
| Full | Weekly | 4 weeks | Local |
| Full | Monthly | 12 months | Off-site |
| Incremental | Hourly | 24 hours | Local |
| TM Export | Monthly | Indefinite | Off-site |

**Implementation:**

```bash
# Daily cleanup script
find /backups/daily -name "*.tar.gz" -mtime +7 -delete
find /backups/weekly -name "*.tar.gz" -mtime +28 -delete
find /backups/incremental -name "*.tar.gz" -mtime +1 -delete
```

---

## Common Operational Tasks

### Add New Site Profile

```bash
# 1. Create site profile
cat > config/site_profiles/newsite.yaml <<EOF
site_id: newsite
content_roots:
  - /data/content/newsite
default_source_lang: en
target_langs:
  - fr
  - de

frontmatter:
  title: { mode: translate }
  description: { mode: translate }
  date: { mode: passthrough }

body:
  translate_markdown: true

output_layout:
  per_language_folders: true
  pattern: "{lang}/{path}"

tm_prefs:
  use_semantic_tm: true
  semantic_threshold: 0.80
EOF

# 2. Validate profile
docker-compose exec orchestrator python -c "
from pathlib import Path
from src.utils.config_loader import ConfigService

config = ConfigService(Path('/app/config'))
profile = config.get_site_profile('newsite')
print(f'✓ Profile valid: {profile.site_id}')
"

# 3. Reload configuration (restart orchestrator)
docker-compose restart orchestrator
```

### Update Model Registry

```bash
# 1. Edit model registry
nano config/model_registry.yaml

# Add new model entry:
# - model_id: new_model
#   name: "New Model"
#   ...

# 2. Download model
docker-compose exec worker-cpu-1 python -c "
from src.model_runtime.loader import download_model
download_model('new_model')
"

# 3. Test model
docker-compose exec worker-cpu-1 python -c "
from pathlib import Path
from src.model_runtime.loader import ModelLoader
from src.model_runtime.registry import ModelRegistry

registry = ModelRegistry(Path('/app/config/model_registry.yaml'))
loader = ModelLoader(registry)
model = loader.load_model('new_model')
print('✓ Model loaded successfully')
"

# 4. Restart workers
docker-compose restart worker-cpu-1
```

### Scale Workers

```bash
# Add new worker to docker-compose.yml
cat >> docker-compose.yml <<EOF
  worker-cpu-2:
    build:
      context: .
      dockerfile: Dockerfile
    image: hugo-translator-worker:latest
    container_name: translator-worker-cpu-2
    env_file:
      - .env.production
    environment:
      - WORKER_ID=cpu-2
      - DEVICE=cpu
    volumes:
      - ./config:/app/config:ro
      - content_data:/data/content:ro
      - tm_data:/data/tm
      - model_cache:/data/models
    networks:
      - translator_net
    depends_on:
      - orchestrator
    restart: unless-stopped
EOF

# Start new worker
docker-compose up -d worker-cpu-2

# Verify
docker-compose ps worker-cpu-2
```

### Query Translation Memory

```bash
# Exact lookup
docker-compose exec orchestrator python -c "
from pathlib import Path
from src.tm.translation_memory import create_translation_memory

tm = create_translation_memory(Path('/data/tm'))
result = tm.lookup('mysite', 'en', 'fr', 'Hello World')
print(f'Translation: {result}')
"

# Semantic lookup
docker-compose exec orchestrator python -c "
from pathlib import Path
from src.tm.translation_memory import create_translation_memory

tm = create_translation_memory(Path('/data/tm'))
candidates = tm.semantic_lookup(
    'mysite', 'en', 'fr',
    'Hello everyone',
    threshold=0.75,
    limit=5
)

for c in candidates:
    print(f'{c.similarity:.2f}: {c.source} -> {c.target}')
"
```

### Manual Translation Job

```bash
# Translate single file
docker-compose exec orchestrator python -c "
from pathlib import Path
from src.translation_engine.engine import TranslationEngine
from src.utils.config_loader import ConfigService
from src.tm.translation_memory import create_translation_memory
from src.model_runtime.loader import create_model_loader

config = ConfigService(Path('/app/config'))
tm = create_translation_memory(Path('/data/tm'))
loader = create_model_loader(Path('/app/config'))
engine = TranslationEngine(config, tm, loader)

result = engine.translate_file(
    site_id='mysite',
    file_path=Path('/data/content/mysite/post.md'),
    target_langs=['fr', 'de']
)

print(f'Success: {result.success}')
for lang, output in result.outputs.items():
    print(f'{lang}: {output}')
"

# Translate directory
docker-compose exec orchestrator python -c "
from pathlib import Path
from src.translation_engine.engine import TranslationEngine
# ... (same setup)

result = engine.translate_directory(
    site_id='mysite',
    directory=Path('/data/content/mysite/posts'),
    target_langs=['fr'],
    recursive=True,
    parallel=True
)

print(f'Files translated: {result.files_translated}')
print(f'Time: {result.total_time_seconds:.1f}s')
"
```

---

## Emergency Procedures

### Service Not Starting

```bash
# 1. Check logs
docker-compose logs orchestrator

# 2. Check configuration
docker-compose config

# 3. Rebuild and restart
docker-compose down
docker-compose build orchestrator
docker-compose up -d orchestrator

# 4. If still failing, restore from backup
./scripts/restore.sh /backups/latest
```

### High Error Rate

```bash
# 1. Check recent errors
docker-compose logs --tail=100 | grep -i error

# 2. Check specific error types
docker-compose exec orchestrator python -c "
from src.observability.metrics import MetricsCollector

collector = MetricsCollector()
errors = collector.get_errors(hours=1)
for error_type, count in errors.items():
    print(f'{error_type}: {count}')
"

# 3. If model loading errors, clear model cache
docker-compose exec worker-cpu-1 rm -rf /data/models/*
docker-compose restart worker-cpu-1

# 4. If TM errors, rebuild TM index
docker-compose exec orchestrator python -c "
from pathlib import Path
from src.tm.l3_semantic import L3SemanticTM

l3 = L3SemanticTM(Path('/data/tm/index'))
l3.rebuild_index()
print('✓ Index rebuilt')
"
```

### Out of Disk Space

```bash
# 1. Check disk usage
df -h
docker system df

# 2. Clean Docker resources
docker system prune -a

# 3. Clean old logs
find /data/logs -name "*.log" -mtime +7 -delete

# 4. Clean old backups
find /backups/daily -mtime +7 -delete

# 5. Compact TM database
docker-compose exec orchestrator python -c "
from pathlib import Path
from src.tm.l2_persistent import L2PersistentTM

l2 = L2PersistentTM(Path('/data/tm/db.lmdb'))
l2.compact()
print('✓ Database compacted')
l2.close()
"
```

### Memory Issues

```bash
# 1. Check memory usage
docker stats --no-stream

# 2. Reduce worker count
docker-compose stop worker-cpu-2 worker-cpu-3

# 3. Reduce batch size
# Edit .env.production:
# MODEL_BATCH_SIZE=16

docker-compose restart worker-cpu-1

# 4. Reduce cache sizes
# Edit config/global.yaml:
# tm_defaults:
#   l1_cache_size: 5000

docker-compose restart orchestrator
```

### Data Corruption

```bash
# 1. Stop services
docker-compose down

# 2. Restore from last known good backup
./scripts/restore.sh /backups/YYYYMMDD_HHMMSS

# 3. Verify restoration
docker-compose up -d
./scripts/verify_deployment.sh

# 4. If TM corrupted, rebuild from exports
docker-compose exec orchestrator python -c "
from pathlib import Path
from src.tm.translation_memory import rebuild_from_export

rebuild_from_export(
    export_file=Path('/backups/tm_export.ndjson'),
    output_dir=Path('/data/tm')
)
"
```

---

## Performance Tuning

### Optimize TM Hit Rate

```bash
# 1. Check current hit rate
docker-compose exec orchestrator python -c "
from pathlib import Path
from src.observability.tm_admin import TranslationMemoryAdmin
from src.tm.translation_memory import create_translation_memory

tm = create_translation_memory(Path('/data/tm'))
admin = TranslationMemoryAdmin(tm)
stats = admin.get_statistics()

print(f'L2 hit rate: {stats.l2_hit_rate:.2%}')
print(f'L3 hit rate: {stats.l3_hit_rate:.2%}')
"

# 2. If L3 hit rate low, lower threshold
# Edit site profile:
# tm_prefs:
#   semantic_threshold: 0.75  # Lower from 0.80

# 3. If overall hit rate low, ensure TM populated
# Run batch translation to populate TM
```

### Optimize Translation Speed

```bash
# 1. Enable parallel processing
# Edit .env.production:
# PARALLEL_TRANSLATION=true
# MAX_PARALLEL_FILES=8

# 2. Use GPU if available
# DEVICE=cuda

# 3. Use CTranslate2 models (faster on CPU)
# Edit site profile:
# model_prefs:
#   preferred_model: "m2m100_418m_ct2"

# 4. Increase batch size (if memory allows)
# MODEL_BATCH_SIZE=64

# 5. Restart services
docker-compose restart
```

### Optimize Resource Usage

```bash
# 1. Set resource limits
# Edit docker-compose.yml:
# deploy:
#   resources:
#     limits:
#       cpus: '4'
#       memory: 8G

# 2. Reduce cache sizes if memory constrained
# Edit config/global.yaml:
# tm_defaults:
#   l1_cache_size: 5000
#   l2_max_size_mb: 512

# 3. Limit concurrent jobs
# orchestrator:
#   max_workers: 2

# 4. Apply changes
docker-compose down
docker-compose up -d
```

---

## Capacity Planning

### Monitor Growth Trends

```bash
# Generate growth report
docker-compose exec orchestrator python -c "
from pathlib import Path
from src.observability.tm_admin import TranslationMemoryAdmin
from src.tm.translation_memory import create_translation_memory

tm = create_translation_memory(Path('/data/tm'))
admin = TranslationMemoryAdmin(tm)

# Get historical stats (if available)
stats = admin.get_statistics()

print('Current State:')
print(f'  TM entries: {stats.total_entries:,}')
print(f'  Storage: {stats.storage_size_mb:.1f}MB')
print(f'  Daily growth: {stats.daily_growth_rate:.1f} entries/day')

# Project future
months = 6
projected_entries = stats.total_entries + (stats.daily_growth_rate * 30 * months)
projected_storage = stats.storage_size_mb * (projected_entries / stats.total_entries)

print(f'\nProjected ({months} months):')
print(f'  TM entries: {projected_entries:,.0f}')
print(f'  Storage: {projected_storage:.1f}MB')
"
```

### Scaling Recommendations

Based on workload:

| Files/Day | Workers | RAM | Storage | GPU |
|-----------|---------|-----|---------|-----|
| <100 | 1-2 | 8GB | 50GB | Optional |
| 100-1000 | 2-4 | 16GB | 100GB | Recommended |
| 1000-10000 | 4-8 | 32GB | 500GB | Required |
| 10000+ | 8+ | 64GB+ | 1TB+ | Multiple |

---

## Next Steps

- Review [Troubleshooting Guide](troubleshooting.md) for problem resolution
- See [User Guide](../user-guide/setup.md) for feature usage
- Check [Configuration Reference](../reference/config.md) for tuning options

---

**Documentation Version:** 1.0.0
**Last Updated:** 2025-11-21
