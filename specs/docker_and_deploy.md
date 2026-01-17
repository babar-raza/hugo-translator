# Docker and Deployment

## Overview

The Hugo Translation System is designed to run in Docker containers for easy deployment and scalability. This document describes the Docker configuration, deployment options, and best practices.

## Docker Configuration

### Dockerfiles

#### Main Dockerfile

- **File**: `Dockerfile`
- **Description**: Main Dockerfile for orchestrator and CPU workers
- **Base Image**: `python:3.10-bullseye`
- **Evidence**: [`evidence-020`](specs/_evidence_index.yml:evidence-020)
- **Features**:
  - Python 3.10 environment
  - CPU-based translation
  - Orchestrator services
  - Default command: `python -m src.orchestrator`

#### GPU Dockerfile

- **File**: `Dockerfile.gpu`
- **Description**: Dockerfile for GPU workers
- **Base Image**: `nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04`
- **Evidence**: [`evidence-021`](specs/_evidence_index.yml:evidence-021)
- **Features**:
  - CUDA 11.8 with cuDNN 8
  - Python 3.10 environment
  - GPU-based translation
  - Default command: `python -m src.workers.translation_worker`

### Docker Compose

- **File**: `docker-compose.yml`
- **Description**: Docker Compose configuration for the entire system
- **Evidence**: [`evidence-002`](specs/_evidence_index.yml:evidence-002)
- **Services**:
  - `orchestrator`: Translation orchestrator
  - `worker-cpu`: CPU-based translation worker
  - `worker-gpu`: GPU-based translation worker
  - `redis`: Job queue backend
  - `prometheus`: Metrics collection
  - `pushgateway`: Metrics push gateway
  - `grafana`: Metrics visualization

## Deployment Options

### Local Development

```bash
# Build and start all services
docker-compose up --build

# Start specific services
docker-compose up orchestrator worker-cpu redis

# Start with GPU support
docker-compose --profile gpu up worker-gpu

# Start with monitoring
docker-compose --profile monitoring up prometheus grafana
```

### Production Deployment

```bash
# Build production images
docker-compose -f docker-compose.yml -f docker-compose.prod.yml build

# Start production services
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Scale workers
docker-compose up -d --scale worker-cpu=4

# Update services
docker-compose up -d --build orchestrator
```

### Kubernetes Deployment

The system can be deployed to Kubernetes using the provided Docker images:

```yaml
# deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: hugo-translator-orchestrator
spec:
  replicas: 1
  selector:
    matchLabels:
      app: hugo-translator-orchestrator
  template:
    metadata:
      labels:
        app: hugo-translator-orchestrator
    spec:
      containers:
      - name: orchestrator
        image: hugo-translator-orchestrator:latest
        ports:
        - containerPort: 8000
        env:
        - name: MODE
          value: "auto"
        - name: CONFIG_PATH
          value: "/app/config"
        volumeMounts:
        - name: config
          mountPath: /app/config
          readOnly: true
      volumes:
      - name: config
        hostPath:
          path: /path/to/config
```

## Deployment Profiles

### CPU Profile

- **Description**: CPU-only deployment
- **Services**: orchestrator, worker-cpu, redis
- **Use Case**: Development, testing, small-scale production

### GPU Profile

- **Description**: GPU-accelerated deployment
- **Services**: orchestrator, worker-gpu, redis
- **Use Case**: Production with GPU acceleration
- **Requirements**: NVIDIA GPU, nvidia-docker

### Monitoring Profile

- **Description**: Full monitoring stack
- **Services**: prometheus, pushgateway, grafana
- **Use Case**: Production monitoring and observability

## Configuration

### Environment Variables

Configure services using environment variables:

```bash
# Set environment variables
export MODE=auto
export CONFIG_PATH=/app/config
export REDIS_HOST=redis
export REDIS_PORT=6379

# Start services
docker-compose up
```

### Configuration Files

Mount configuration files into containers:

```yaml
# docker-compose.yml
services:
  orchestrator:
    volumes:
      - ./config:/app/config:ro
      - ./data:/app/data
```

## Scaling

### Horizontal Scaling

Scale workers to handle increased load:

```bash
# Scale CPU workers
docker-compose up -d --scale worker-cpu=4

# Scale GPU workers
docker-compose --profile gpu up -d --scale worker-gpu=2
```

### Vertical Scaling

Adjust resource limits for containers:

```yaml
# docker-compose.yml
services:
  worker-cpu:
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 4G
```

## Health Checks

### Service Health

Monitor service health using Docker health checks:

```bash
# Check service health
docker-compose ps

# View health status
docker inspect --format='{{json .State.Health}}' container_name
```

### Application Health

Use the health check endpoints:

```bash
# Check orchestrator health
curl http://localhost:8000/health

# Check worker health
curl http://localhost:8001/health
```

## Logging

### View Logs

```bash
# View all logs
docker-compose logs

# View specific service logs
docker-compose logs orchestrator

# Follow logs in real-time
docker-compose logs -f
```

### Log Configuration

Configure logging in `docker-compose.yml`:

```yaml
services:
  orchestrator:
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

## Best Practices

1. **Configuration Management**: Use environment variables and mounted volumes for configuration
2. **Resource Limits**: Set appropriate resource limits for containers
3. **Health Monitoring**: Implement health checks for all services
4. **Logging**: Configure proper logging and log rotation
5. **Scaling**: Scale workers based on load and available resources
6. **Security**: Secure sensitive data using Docker secrets or environment variables
7. **Updates**: Regularly update Docker images and dependencies
8. **Backup**: Backup configuration and data volumes regularly
