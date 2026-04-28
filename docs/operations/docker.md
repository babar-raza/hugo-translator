# Docker Deployment Guide

This directory contains Docker configuration for deploying the Hugo Translation System.

## Quick Start

### CPU-Only Deployment

```bash
# Build and start services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

### GPU-Enabled Deployment

```bash
# Build and start with GPU worker
docker-compose --profile gpu up -d

# View GPU worker logs
docker-compose logs -f worker-gpu
```

## Architecture

The system consists of three main services:

1. **Orchestrator**: Manages job queue, file watching, and sweep scheduling
2. **CPU Worker**: Translates content using CPU resources
3. **GPU Worker** (optional): Translates content using GPU acceleration

## Configuration

### Environment Variables

Create a `.env` file in the project root:

```env
# Logging
LOG_LEVEL=INFO
LOG_FILE=/app/logs/orchestrator.log

# Translation Memory
TM_DB_PATH=/app/data/tm.lmdb

# Artifacts
ARTIFACTS_DIR=/app/artifacts
ARTIFACT_DETAIL_LEVEL=SUMMARY

# Models
MODEL_CACHE_DIR=/app/models
```

### Volume Mounts

- `./data`: TM database and persistent storage
- `./logs`: Application logs
- `./artifacts`: Flow artifacts and job traces
- `./models`: Translation model cache
- `./config`: Site profiles and configuration
- `./content`: Hugo content (read-only)

## Building Images

### Build CPU Image

```bash
docker build -t hugo-translator:cpu -f Dockerfile .
```

### Build GPU Image

```bash
docker build -t hugo-translator:gpu -f Dockerfile.gpu .
```

## Scaling Workers

### Add More CPU Workers

```bash
docker-compose up -d --scale worker-cpu=3
```

### Add More GPU Workers

```bash
docker-compose --profile gpu up -d --scale worker-gpu=2
```

## Health Checks

All services include health checks:

```bash
# Check orchestrator health
docker-compose exec orchestrator python -c "import sys; sys.exit(0)"

# Check GPU availability (GPU worker)
docker-compose exec worker-gpu python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}')"
```

## Monitoring

### View Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f orchestrator
docker-compose logs -f worker-cpu
docker-compose logs -f worker-gpu
```

### Resource Usage

```bash
# View container stats
docker stats

# View specific container
docker stats hugo-translator-orchestrator
```

## Troubleshooting

### GPU Not Detected

Ensure nvidia-docker is installed:

```bash
# Install nvidia-docker2
sudo apt-get install nvidia-docker2
sudo systemctl restart docker

# Test GPU access
docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi
```

### Permission Issues

Fix volume permissions:

```bash
sudo chown -R $(id -u):$(id -g) data logs artifacts
```

### Out of Memory

Increase Docker memory limits in Docker Desktop or daemon.json:

```json
{
  "default-runtime": "nvidia",
  "runtimes": {
    "nvidia": {
      "path": "nvidia-container-runtime",
      "runtimeArgs": []
    }
  },
  "default-shm-size": "2G"
}
```

## Production Deployment

### Using Docker Swarm

```bash
# Initialize swarm
docker swarm init

# Deploy stack
docker stack deploy -c docker-compose.yml hugo-translator

# Scale services
docker service scale hugo-translator_worker-cpu=5
```

### Using Kubernetes

Convert to Kubernetes manifests:

```bash
# Install kompose
curl -L https://github.com/kubernetes/kompose/releases/download/v1.28.0/kompose-linux-amd64 -o kompose
chmod +x kompose
sudo mv kompose /usr/local/bin/

# Convert
kompose convert -f docker-compose.yml -o k8s/
```

## Backup and Restore

### Backup TM Database

```bash
# Stop services
docker-compose down

# Backup data
tar -czf backup-$(date +%Y%m%d).tar.gz data/

# Restart services
docker-compose up -d
```

### Restore TM Database

```bash
# Stop services
docker-compose down

# Restore data
tar -xzf backup-20231215.tar.gz

# Restart services
docker-compose up -d
```

## Security

### Network Isolation

Services communicate via internal bridge network (`translator-network`).

### Read-Only Mounts

Content directory is mounted read-only to prevent accidental modifications.

### User Permissions

Run containers as non-root user:

```dockerfile
# Add to Dockerfile
RUN useradd -m -u 1000 translator
USER translator
```

## Performance Tuning

### Batch Size

Adjust batch size in config/model_registry.yaml:

```yaml
batch_size: 32  # Increase for better GPU utilization
```

### Worker Count

Scale based on available resources:

- CPU workers: 1-2 per CPU core
- GPU workers: 1 per GPU

### Memory Limits

Set memory limits in docker-compose.yml:

```yaml
deploy:
  resources:
    limits:
      memory: 4G
    reservations:
      memory: 2G
```

## See Also

- [Docker Volume Management](../deployment/docker.md) - Persistent storage, backup/restore, volume lifecycle
