# Hugo Translation System - Deployment Guide

**Version:** 1.0.0
**Last Updated:** 2025-11-21

---

## Table of Contents

1. [System Requirements](#system-requirements)
2. [Pre-Deployment Checklist](#pre-deployment-checklist)
3. [Docker Deployment](#docker-deployment)
4. [Environment Configuration](#environment-configuration)
5. [Starting Services](#starting-services)
6. [Health Checks and Verification](#health-checks-and-verification)
7. [Scaling Considerations](#scaling-considerations)
8. [Security Hardening](#security-hardening)
9. [Monitoring Setup](#monitoring-setup)
10. [Rollback Procedures](#rollback-procedures)

---

## System Requirements

### Minimum Requirements

**Hardware:**
- **CPU:** 4 cores (x86_64)
- **RAM:** 8GB
- **Storage:** 20GB SSD
- **Network:** 100 Mbps

**Software:**
- **OS:** Linux (Ubuntu 20.04+ recommended), macOS 11+, or Windows 10+ with WSL2
- **Docker:** 20.10+
- **Docker Compose:** 2.0+
- **Python:** 3.10+ (for local development)

### Recommended Requirements

**Hardware:**
- **CPU:** 8+ cores (x86_64)
- **RAM:** 16GB+
- **GPU:** NVIDIA GPU with 8GB+ VRAM (optional but recommended)
  - CUDA 11.0+ support
  - NVIDIA Docker runtime installed
- **Storage:** 50GB+ SSD
- **Network:** 1 Gbps

**Software:**
- **OS:** Ubuntu 22.04 LTS
- **Docker:** 24.0+
- **Docker Compose:** 2.20+
- **NVIDIA Driver:** 525+ (for GPU support)

### Port Requirements

The following ports must be available:

| Port | Service | Required | Description |
|------|---------|----------|-------------|
| 9090 | Prometheus | Yes | Metrics collection |
| 9091 | Pushgateway | Yes | Batch job metrics |
| 3000 | Grafana | No | Metrics visualization (optional) |

---

## Pre-Deployment Checklist

### 1. Verify System Prerequisites

```bash
# Check Docker version
docker --version
# Required: 20.10+

# Check Docker Compose version
docker-compose --version
# Required: 2.0+

# Check available disk space
df -h
# Required: 20GB+ free

# Check available memory
free -h
# Required: 8GB+ total

# Check CPU cores
nproc
# Required: 4+ cores
```

### 2. GPU Setup (Optional)

If using GPU acceleration:

```bash
# Check NVIDIA driver
nvidia-smi

# Install NVIDIA Docker runtime
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | sudo tee /etc/apt/sources.list.d/nvidia-docker.list

sudo apt-get update
sudo apt-get install -y nvidia-docker2
sudo systemctl restart docker

# Test GPU access
docker run --rm --gpus all nvidia/cuda:11.0-base nvidia-smi
```

### 3. Prepare Configuration

```bash
# Clone repository
git clone <repository-url>
cd hugo-translator

# Create environment file
cp .env.example .env.production

# Edit configuration (see Environment Configuration section)
nano .env.production

# Verify configuration files exist
ls -l config/global.yaml
ls -l config/model_registry.yaml
ls -l config/site_profiles/
```

### 4. Create Data Directories

```bash
# Create persistent data directories
mkdir -p data/tm
mkdir -p data/models
mkdir -p data/artifacts
mkdir -p data/logs
mkdir -p backups

# Set permissions
chmod -R 755 data/
chmod -R 755 backups/
```

---

## Docker Deployment

### Deployment Architecture

The system consists of the following containers:

```
┌─────────────────────────────────────────────────────────┐
│                    Docker Network                        │
│                    (translator_net)                      │
│                                                          │
│  ┌──────────────┐      ┌──────────────┐                │
│  │ Orchestrator │◄────►│ Worker CPU-1 │                │
│  │   (Control)  │      │ (Translation)│                │
│  └──────┬───────┘      └──────────────┘                │
│         │                                                │
│         │              ┌──────────────┐                │
│         └─────────────►│ Worker GPU-1 │                │
│                        │ (Translation)│                │
│                        └──────────────┘                │
│                                                          │
│  ┌──────────────┐      ┌──────────────┐                │
│  │  Prometheus  │◄────►│ Pushgateway  │                │
│  │   (Metrics)  │      │   (Metrics)  │                │
│  └──────────────┘      └──────────────┘                │
│                                                          │
│  ┌──────────────┐                                       │
│  │   Grafana    │      (Optional)                       │
│  │(Visualization)│                                       │
│  └──────────────┘                                       │
└─────────────────────────────────────────────────────────┘
```

### Build Docker Images

```bash
# Build all images
docker-compose build

# Build specific service
docker-compose build orchestrator
docker-compose build worker-cpu-1

# Build GPU worker (if GPU available)
docker-compose build worker-gpu-1

# Verify images created
docker images | grep hugo-translator
```

### Image Sizes

Expected image sizes:

- **orchestrator:** ~2GB
- **worker-cpu:** ~2GB
- **worker-gpu:** ~4GB (includes CUDA)
- **prometheus:** ~200MB
- **pushgateway:** ~50MB
- **grafana:** ~300MB

---

## Environment Configuration

### Production Environment Template

Create `.env.production` with the following settings:

```bash
# =================================================================
# PRODUCTION ENVIRONMENT CONFIGURATION
# Hugo Translation System
# =================================================================

# System Environment
ENVIRONMENT=production
LOG_LEVEL=INFO
FLOW_ARTIFACT_DETAIL=summary

# =================================================================
# PATHS (Container paths - do not change unless customizing mounts)
# =================================================================
CONFIG_PATH=/app/config
CONTENT_ROOT=/data/content
OUTPUT_DIR=/data/output
TM_DATA_PATH=/data/tm
MODEL_CACHE_PATH=/data/models
ARTIFACTS_PATH=/data/artifacts
LOGS_PATH=/data/logs
BACKUP_PATH=/backups

# =================================================================
# TRANSLATION MEMORY CONFIGURATION
# =================================================================
# L1 Cache (in-memory)
TM_L1_CACHE_SIZE=10000

# L2 Persistent (LMDB)
TM_L2_MAX_SIZE_MB=2048

# L3 Semantic (Vector search)
TM_L3_EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-mpnet-base-v2
TM_SEMANTIC_THRESHOLD=0.80
TM_USE_SEMANTIC=true

# =================================================================
# MODEL RUNTIME CONFIGURATION
# =================================================================
# Default model (see config/model_registry.yaml for options)
DEFAULT_MODEL=m2m100_418m

# Device selection
# Options: auto (recommended), cpu, cuda, mps
DEVICE=auto

# Batch size for translation
# Larger = faster but more memory
# Recommended: 32 for CPU, 64-128 for GPU
MODEL_BATCH_SIZE=32

# Model caching
MAX_CACHED_MODELS=2

# =================================================================
# ORCHESTRATOR CONFIGURATION
# =================================================================
# Mode: auto (file watching + sweeps) or manual (on-demand only)
ORCHESTRATOR_MODE=auto

# Worker pool size
MAX_WORKERS=4

# Sweep interval (hours)
# How often to perform full content sweep
SWEEP_INTERVAL_HOURS=24

# File watching
FILE_WATCHER_ENABLED=true
FILE_WATCHER_DEBOUNCE_SECONDS=2.0

# =================================================================
# PERFORMANCE SETTINGS
# =================================================================
# Parallel processing
PARALLEL_TRANSLATION=true
MAX_PARALLEL_FILES=8

# =================================================================
# OBSERVABILITY CONFIGURATION
# =================================================================
# Metrics
METRICS_ENABLED=true
METRICS_PORT=9090
PROMETHEUS_PUSHGATEWAY=http://pushgateway:9091

# Logging
# Levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_LEVEL=INFO
LOG_FORMAT=json

# Flow artifacts
# Options: none, summary, sampled, full
# Production: summary or sampled (5%)
FLOW_ARTIFACT_DETAIL=summary
FLOW_ARTIFACT_SAMPLE_RATE=0.05

# =================================================================
# VALIDATION SETTINGS
# =================================================================
VALIDATION_ENABLED=true
VALIDATION_STRICT_MODE=false

# =================================================================
# SECURITY SETTINGS
# =================================================================
MAX_FILE_SIZE_MB=10
ENABLE_INPUT_VALIDATION=true
SANITIZE_OUTPUT=true

# =================================================================
# FEATURE FLAGS
# =================================================================
ENABLE_PARALLEL_PROCESSING=true
ENABLE_SEMANTIC_TM=true
ENABLE_MODEL_BENCHMARKING=false
ENABLE_AUTO_MODEL_SELECTION=true

# =================================================================
# OPTIONAL: HUGGINGFACE TOKEN
# Required only for:
# - Private models
# - Avoiding rate limits on model downloads
# =================================================================
# HF_TOKEN=your_huggingface_token_here

# =================================================================
# OPTIONAL: REDIS (for distributed job queue)
# =================================================================
# REDIS_HOST=redis
# REDIS_PORT=6379
# REDIS_PASSWORD=
# REDIS_DB=0
```

### Environment Variables Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `ENVIRONMENT` | production | Environment name (development, staging, production) |
| `LOG_LEVEL` | INFO | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `DEVICE` | auto | Compute device (auto, cpu, cuda, mps) |
| `DEFAULT_MODEL` | m2m100_418m | Default translation model |
| `ORCHESTRATOR_MODE` | auto | Orchestrator mode (auto, manual) |
| `TM_SEMANTIC_THRESHOLD` | 0.80 | Similarity threshold for semantic TM (0.0-1.0) |
| `MAX_WORKERS` | 4 | Maximum concurrent workers |
| `METRICS_ENABLED` | true | Enable Prometheus metrics |

---

## Starting Services

### Start All Services

```bash
# Start in background (recommended)
docker-compose up -d

# Start with logs (for testing)
docker-compose up

# Start specific services only
docker-compose up -d orchestrator worker-cpu-1 prometheus pushgateway
```

### Start with GPU Support

```bash
# Start GPU worker
docker-compose --profile gpu up -d

# Verify GPU access
docker-compose exec worker-gpu-1 nvidia-smi
```

### Start with Monitoring

```bash
# Start with Grafana dashboard
docker-compose --profile monitoring up -d

# Access Grafana at http://localhost:3000
# Default credentials: admin/admin
```

### Service Startup Order

Services start in the following order:

1. **Orchestrator** (starts first, creates job queue)
2. **Workers** (wait for orchestrator health check)
3. **Prometheus** (starts in parallel)
4. **Pushgateway** (starts in parallel)
5. **Grafana** (depends on Prometheus)

---

## Health Checks and Verification

### Check Service Status

```bash
# View all services
docker-compose ps

# Expected output:
# NAME                        STATUS              PORTS
# translator-orchestrator     Up (healthy)
# translator-worker-cpu-1     Up (healthy)
# translator-prometheus       Up                  0.0.0.0:9090->9090/tcp
# translator-pushgateway      Up                  0.0.0.0:9091->9091/tcp
```

### View Service Logs

```bash
# All services
docker-compose logs

# Specific service
docker-compose logs orchestrator
docker-compose logs worker-cpu-1

# Follow logs in real-time
docker-compose logs -f orchestrator

# Last 100 lines
docker-compose logs --tail=100 orchestrator
```

### Test Orchestrator

```bash
# Execute health check
docker-compose exec orchestrator python -c "
from pathlib import Path
from src.utils.config_loader import ConfigService

config = ConfigService(Path('/app/config'))
sites = config.list_sites()
print(f'✓ Configuration loaded: {len(sites)} sites')
"

# Expected output:
# ✓ Configuration loaded: X sites
```

### Test Worker

```bash
# Test worker initialization
docker-compose exec worker-cpu-1 python -c "
from pathlib import Path
from src.model_runtime.hardware import HardwareDetector

detector = HardwareDetector()
hw_info = detector.detect()
print(f'✓ Hardware detected: {hw_info.recommended_device}')
print(f'✓ RAM: {hw_info.total_ram_gb:.1f}GB')
print(f'✓ CPU cores: {hw_info.cpu_count}')
"

# Expected output:
# ✓ Hardware detected: cpu (or cuda)
# ✓ RAM: 16.0GB
# ✓ CPU cores: 8
```

### Test Translation Memory

```bash
# Verify TM initialization
docker-compose exec worker-cpu-1 python -c "
from pathlib import Path
from src.tm.l1_cache import L1Cache
from src.tm.l2_persistent import L2PersistentTM
from src.tm.l3_semantic import L3SemanticTM
from src.tm.translation_memory import TranslationMemory

l1 = L1Cache(max_size=1000)
l2 = L2PersistentTM(Path('/data/tm/test.lmdb'))
l3 = L3SemanticTM(Path('/data/tm/test_index'))
tm = TranslationMemory(l1, l2, l3)

print('✓ Translation Memory initialized')
l2.close()
"
```

### Test Model Loading

```bash
# Test model registry
docker-compose exec worker-cpu-1 python -c "
from pathlib import Path
from src.model_runtime.registry import ModelRegistry

registry = ModelRegistry(Path('/app/config/model_registry.yaml'))
models = registry.list_models()
print(f'✓ Model registry loaded: {len(models)} models')
for model in models[:3]:
    print(f'  - {model.name}')
"
```

### End-to-End Test

```bash
# Run simple translation test
docker-compose exec worker-cpu-1 python -c "
from pathlib import Path
from src.translation_engine.engine import TranslationEngine
from src.utils.config_loader import ConfigService
from src.tm.translation_memory import create_translation_memory
from src.model_runtime.loader import create_model_loader

# Initialize
config = ConfigService(Path('/app/config'))
tm = create_translation_memory(Path('/data/tm'))
loader = create_model_loader(Path('/app/config'))
engine = TranslationEngine(config, tm, loader)

# Create test file
test_file = Path('/tmp/test.md')
test_file.write_text('''---
title: Test Page
---

# Hello World

This is a test.
''')

# Get first site
sites = config.list_sites()
if sites:
    result = engine.translate_file(sites[0], test_file, ['fr'])
    print(f'✓ Translation test: {\"SUCCESS\" if result.success else \"FAILED\"}')
    if result.success:
        print(f'  Segments: {result.stats.total_segments}')
else:
    print('⚠ No site profiles configured')
"
```

### Check Metrics

```bash
# Test Prometheus access
curl http://localhost:9090/api/v1/status/config

# View current metrics
curl http://localhost:9090/api/v1/query?query=up

# Test Pushgateway
curl http://localhost:9091/metrics
```

### Verify Data Persistence

```bash
# Check volume mounts
docker volume ls | grep translator

# Inspect TM data
docker-compose exec orchestrator ls -lh /data/tm/

# Inspect model cache
docker-compose exec worker-cpu-1 ls -lh /data/models/

# Inspect artifacts
docker-compose exec orchestrator ls -lh /data/artifacts/
```

---

## Scaling Considerations

### Horizontal Scaling (Add Workers)

Add more workers to handle increased load:

```yaml
# In docker-compose.yml, add more workers:

  worker-cpu-2:
    <<: *worker-cpu-template
    container_name: translator-worker-cpu-2
    environment:
      - WORKER_ID=cpu-2

  worker-cpu-3:
    <<: *worker-cpu-template
    container_name: translator-worker-cpu-3
    environment:
      - WORKER_ID=cpu-3
```

**Scaling Guidelines:**
- 1 worker per 4 CPU cores (CPU-bound workloads)
- 1 GPU worker per GPU
- Monitor memory usage (each worker uses 2-4GB)
- Consider network bandwidth for distributed deployments

### Vertical Scaling (Resource Limits)

Configure resource limits:

```yaml
# In docker-compose.yml:

services:
  worker-cpu-1:
    deploy:
      resources:
        limits:
          cpus: '4'
          memory: 8G
        reservations:
          cpus: '2'
          memory: 4G
```

### Load Balancing

For distributed deployments:

1. **Use Redis for job queue:**
   ```yaml
   orchestrator:
     environment:
       - JOB_QUEUE_BACKEND=redis
       - REDIS_HOST=redis
   ```

2. **Deploy Redis:**
   ```yaml
   services:
     redis:
       image: redis:7-alpine
       ports:
         - "6379:6379"
       volumes:
         - redis_data:/data
   ```

3. **Run multiple orchestrators (active-passive):**
   - One active orchestrator
   - Standby orchestrators for failover

### Performance Targets

| Metric | Target | Acceptable |
|--------|--------|------------|
| Single file (1KB) | <2s | <5s |
| Directory (100 files) | <5min | <10min |
| TM lookups | >10k/sec | >5k/sec |
| Memory per worker | <4GB | <8GB |
| CPU usage | 70-90% | 50-100% |

---

## Security Hardening

### Container Security

1. **Run as non-root user:**
   ```dockerfile
   # In Dockerfile:
   RUN useradd -m -u 1000 appuser
   USER appuser
   ```

2. **Use specific image versions:**
   ```dockerfile
   FROM python:3.10-slim@sha256:...
   ```

3. **Scan for vulnerabilities:**
   ```bash
   docker scan hugo-translator-worker:latest
   ```

### Network Security

1. **Isolate network:**
   ```yaml
   networks:
     translator_net:
       driver: bridge
       internal: true  # No external access
   ```

2. **Expose only necessary ports:**
   ```yaml
   ports:
     - "127.0.0.1:9090:9090"  # Only localhost
   ```

3. **Use secrets for sensitive data:**
   ```yaml
   services:
     worker:
       secrets:
         - hf_token

   secrets:
     hf_token:
       file: ./secrets/hf_token.txt
   ```

### File System Security

```bash
# Secure configuration files
chmod 600 .env.production
chmod 644 config/*.yaml

# Secure data directories
chown -R 1000:1000 data/
chmod 755 data/

# Secure secrets
mkdir -p secrets/
chmod 700 secrets/
```

### Dependency Security

```bash
# Check for vulnerabilities
pip install safety
safety check -r requirements/base.txt

# Update vulnerable packages
pip install --upgrade <package>
```

---

## Monitoring Setup

### Prometheus Configuration

Create `docker/prometheus/prometheus.yml`:

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s
  external_labels:
    cluster: 'translation-system'
    environment: 'production'

# Alert rules
rule_files:
  - '/etc/prometheus/alert_rules.yml'

# Scrape configurations
scrape_configs:
  - job_name: 'pushgateway'
    honor_labels: true
    static_configs:
      - targets: ['pushgateway:9091']

  - job_name: 'translation-workers'
    static_configs:
      - targets: ['worker-cpu-1:9090', 'worker-gpu-1:9090']
```

### Alert Rules

Create `docker/prometheus/alert_rules.yml`:

```yaml
groups:
  - name: translation_system
    interval: 30s
    rules:
      - alert: HighTranslationFailureRate
        expr: rate(translation_errors_total[5m]) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High translation failure rate"

      - alert: WorkerDown
        expr: up{job="translation-workers"} == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Translation worker is down"

      - alert: HighQueueDepth
        expr: job_queue_depth > 1000
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "High job queue depth"
```

### Grafana Dashboard

Access Grafana at `http://localhost:3000` (admin/admin)

1. **Add Prometheus data source:**
   - URL: `http://prometheus:9090`

2. **Import dashboard:**
   - Use pre-built dashboard in `docker/grafana/dashboards/`

3. **Key metrics to monitor:**
   - Translation throughput (segments/sec)
   - TM hit rates (L1/L2/L3)
   - Queue depth
   - Worker health
   - Error rates

---

## Rollback Procedures

### Quick Rollback

```bash
# Stop current deployment
docker-compose down

# Restore previous version
git checkout <previous-tag>

# Restore configuration
cp backups/.env.production.backup .env.production

# Start previous version
docker-compose up -d

# Verify
docker-compose ps
docker-compose logs orchestrator
```

### Data Rollback

```bash
# Stop services
docker-compose down

# Restore TM data
tar -xzf backups/tm_data_YYYYMMDD.tar.gz -C data/tm/

# Restore configuration
tar -xzf backups/config_YYYYMMDD.tar.gz

# Restart services
docker-compose up -d
```

### Emergency Procedures

**Total system failure:**

```bash
# 1. Stop all services
docker-compose down -v  # WARNING: Removes volumes

# 2. Restore from backup
./scripts/restore.sh backups/YYYYMMDD_HHMMSS

# 3. Restart
docker-compose up -d

# 4. Verify
./scripts/health_check.sh
```

---

## Post-Deployment

### Verify Deployment

```bash
# Run deployment verification
./scripts/verify_deployment.sh

# Expected output:
# ✓ All services running
# ✓ Health checks passing
# ✓ Configuration loaded
# ✓ Models available
# ✓ TM initialized
# ✓ Metrics accessible
```

### Initial Configuration

1. **Configure site profiles:**
   ```bash
   # Add site profiles in config/site_profiles/
   # See USER_GUIDE.md for examples
   ```

2. **Download initial models:**
   ```bash
   docker-compose exec worker-cpu-1 python -c "
   from src.model_runtime.loader import download_models
   download_models(['m2m100_418m'])
   "
   ```

3. **Populate Translation Memory:**
   ```bash
   # Run initial translation to populate TM
   # See OPERATIONS.md for procedures
   ```

### Monitoring Setup

1. **Configure alerts:**
   - Edit `docker/prometheus/alert_rules.yml`
   - Set up notification channels (email, Slack, etc.)

2. **Set up dashboards:**
   - Import Grafana dashboards
   - Configure refresh intervals

3. **Enable log aggregation:**
   - Optional: Configure ELK stack or similar
   - See [README.md](README.md)

---

## Next Steps

- Review [Operations Manual](README.md) for daily operations
- Set up monitoring and alerting
- Configure backup procedures
- Review [Troubleshooting Guide](troubleshooting.md)

---

**Documentation Version:** 1.0.0
**Last Updated:** 2025-11-21
