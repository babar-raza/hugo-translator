# Dual-Run Execution Layer - Deployment Guide

**Phase 2: Autonomous Workers Unification (AW-03)**

## Overview

The Dual-Run Execution Layer enables workers to run in three deployment modes:

1. **windows_cuda** - Windows native with CUDA GPU support
2. **docker_cpu** - Docker containerized with CPU-only enforcement
3. **docker_gpu** - Docker containerized with GPU passthrough

Each mode has mode-specific configuration defaults defined in `config/global.yaml` and enforces device policies to guarantee CPU-only execution when needed.

## Architecture

### Execution Modes

| Mode | Platform | GPU Support | Use Case |
|------|----------|-------------|----------|
| `windows_cuda` | Windows native | Auto-detect (CUDA/CPU/MPS) | Development, high-performance GPU workstations |
| `docker_cpu` | Docker container | **Forced CPU-only** | Cloud deployment, CPU-only servers, cost optimization |
| `docker_gpu` | Docker container | GPU passthrough (nvidia-docker) | GPU-enabled cloud instances, dedicated GPU containers |

### Configuration Precedence (3-Tier)

1. **Environment Variables** (highest priority)
   - Set via command line, docker-compose.yml, or shell
   - Example: `EXECUTION_MODE=docker_cpu`

2. **Execution Mode Defaults** (middle priority)
   - Defined in `config/global.yaml` under `execution.modes.{mode}`
   - Mode-specific overrides for device, retries, polling, etc.

3. **Global Configuration** (lowest priority)
   - Fallback defaults from global.yaml
   - Used when no mode-specific config exists

### Device Policy Enforcement

For **docker_cpu** mode, multiple enforcement layers guarantee CPU-only execution:

1. **Environment Variable**: `CUDA_VISIBLE_DEVICES=""` (hides GPUs from PyTorch)
2. **Runtime Check**: Validates `torch.cuda.is_available() == False`
3. **Device Override**: Forces `device="cpu"` regardless of configuration

This prevents accidental GPU usage in CPU-only deployments (cost control, resource isolation).

## Deployment Instructions

### 1. Docker Deployment (Recommended for Production)

#### CPU Worker (docker_cpu mode)

```bash
# Using docker-compose
docker-compose up worker-cpu -d

# Or using docker run
docker run -d \
  --name hugo-translator-worker-cpu \
  -e EXECUTION_MODE=docker_cpu \
  -e WORKER_ID=cpu-1 \
  -e REDIS_HOST=redis \
  -e REDIS_PORT=6379 \
  -e USE_SHARED_ENGINES=true \
  -v ./config:/app/config:ro \
  -v ./data/tm:/data/tm \
  hugo-translator-worker:latest
```

**Key Features:**
- CPU-only enforcement (guaranteed by DevicePolicy)
- Faster polling interval (3s vs 5s)
- More retries (5 vs 3) for resilience
- No GPU memory allocation

#### GPU Worker (docker_gpu mode)

```bash
# Using docker-compose (with GPU profile)
docker-compose --profile gpu up worker-gpu -d

# Or using docker run with nvidia runtime
docker run -d \
  --name hugo-translator-worker-gpu \
  --gpus all \
  -e EXECUTION_MODE=docker_gpu \
  -e WORKER_ID=gpu-1 \
  -e REDIS_HOST=redis \
  -e REDIS_PORT=6379 \
  -e CUDA_VISIBLE_DEVICES=0 \
  -e USE_SHARED_ENGINES=true \
  -v ./config:/app/config:ro \
  -v ./data/tm:/data/tm \
  hugo-translator-worker-gpu:latest
```

**Requirements:**
- NVIDIA GPU with CUDA support
- nvidia-docker runtime installed
- Docker Compose v2.3+ for GPU support

### 2. Windows Native Deployment (windows_cuda mode)

#### Using PowerShell Script

```powershell
# Start worker directly
.\scripts\deploy_windows_worker.ps1 `
  -WorkerID "windows-gpu-1" `
  -RedisHost "localhost" `
  -RedisPort 6379 `
  -LogLevel "INFO"

# Install as Windows service (requires NSSM)
.\scripts\deploy_windows_worker.ps1 `
  -WorkerID "windows-gpu-1" `
  -RedisHost "localhost" `
  -InstallService `
  -ServiceName "HugoTranslatorWorker"
```

#### Manual Configuration

```powershell
# Set environment variables
$env:EXECUTION_MODE = "windows_cuda"
$env:WORKER_ID = "windows-gpu-1"
$env:REDIS_HOST = "localhost"
$env:REDIS_PORT = "6379"
$env:CONFIG_PATH = ".\config"
$env:TM_DATA_PATH = ".\data\tm"
$env:USE_SHARED_ENGINES = "true"
$env:LOG_LEVEL = "INFO"

# Activate virtual environment (if using)
.\venv-cuda\Scripts\Activate.ps1

# Run worker
python -m src.workers
```

## Configuration Reference

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `EXECUTION_MODE` | No | `windows_cuda` | Execution mode (windows_cuda, docker_cpu, docker_gpu) |
| `WORKER_ID` | No | `worker-default` | Unique worker identifier |
| `REDIS_HOST` | No | `localhost` | Redis server hostname |
| `REDIS_PORT` | No | `6379` | Redis server port |
| `REDIS_DB` | No | `0` | Redis database number |
| `REDIS_PASSWORD` | No | - | Redis password (if auth enabled) |
| `POLL_INTERVAL` | No | Mode-specific | Seconds between queue polls |
| `MAX_RETRIES` | No | Mode-specific | Maximum job retry attempts |
| `CONFIG_PATH` | No | `./config` | Configuration directory path |
| `TM_DATA_PATH` | No | `./data/tm` | Translation memory storage path |
| `DEVICE` | No | Mode-specific | Device for inference (cpu, cuda, auto) |
| `USE_SHARED_ENGINES` | No | `true` | Enable SharedEngines architecture |
| `LOG_LEVEL` | No | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |

### Mode-Specific Defaults (config/global.yaml)

```yaml
execution:
  default_mode: "windows_cuda"

  modes:
    windows_cuda:
      device: "auto"
      enable_gpu: true
      max_gpu_memory_mb: 4096
      poll_interval: 5.0
      max_retries: 3
      worker_id_prefix: "windows-gpu"

    docker_cpu:
      device: "cpu"
      enable_gpu: false
      max_gpu_memory_mb: 0
      poll_interval: 3.0
      max_retries: 5
      worker_id_prefix: "docker-cpu"

    docker_gpu:
      device: "cuda"
      enable_gpu: true
      max_gpu_memory_mb: 6144
      poll_interval: 5.0
      max_retries: 3
      worker_id_prefix: "docker-gpu"
```

## Backward Compatibility

### Legacy Mode (No EXECUTION_MODE)

Workers without `EXECUTION_MODE` environment variable run in **legacy mode**:

- Emits deprecation warning
- Uses original configuration loading
- Supports `USE_SHARED_ENGINES` flag
- No device policy enforcement
- No mode-specific defaults

```bash
# Legacy mode (deprecated)
REDIS_HOST=localhost \
REDIS_PORT=6379 \
USE_SHARED_ENGINES=true \
python -m src.workers
```

**Migration Path:**
1. Add `EXECUTION_MODE=windows_cuda` to existing deployments
2. Test dual-run execution layer
3. Migrate to mode-specific configuration in global.yaml
4. Remove legacy environment variables

## Telemetry Events

Dual-run execution layer emits telemetry events for tracking:

```python
# Worker startup event
{
  "event_type": "worker_started_with_execution_mode",
  "worker_id": "cpu-1",
  "execution_mode": "docker_cpu",
  "device": "cpu",
  "mode": "worker_runner"
}
```

## Troubleshooting

### GPU Still Detected in docker_cpu Mode

**Symptom:** `torch.cuda.is_available()` returns `True` in docker_cpu mode

**Cause:** PyTorch was initialized before `CUDA_VISIBLE_DEVICES=""` was set

**Solution:** Device override ensures CPU-only execution regardless. Check logs:
```
WARNING - CUDA still available after setting CUDA_VISIBLE_DEVICES=''.
This is expected if torch was initialized before enforcement.
Device override will ensure CPU-only execution.
```

### Invalid EXECUTION_MODE Value

**Symptom:** Warning about invalid execution mode

**Solution:** Use one of: `windows_cuda`, `docker_cpu`, `docker_gpu`
```bash
# Correct
export EXECUTION_MODE=docker_cpu

# Incorrect
export EXECUTION_MODE=docker  # Invalid
```

### Worker Not Using Mode Defaults

**Symptom:** Worker ignores mode-specific configuration from global.yaml

**Cause:** Environment variables override mode defaults (by design)

**Solution:** Remove conflicting environment variables to use mode defaults:
```bash
# This overrides mode config
export POLL_INTERVAL=10

# Remove to use mode default (3.0 for docker_cpu)
unset POLL_INTERVAL
```

## Monitoring and Validation

### Verify Execution Mode

Check worker logs on startup:
```
INFO - Using WorkerRunner with execution mode: docker_cpu
INFO - Loaded execution mode config for 'docker_cpu' from global.yaml: ['device', 'enable_gpu', 'max_gpu_memory_mb', 'poll_interval', 'max_retries', 'worker_id_prefix']
INFO - Execution mode: docker_cpu
INFO - Enforcing CPU-only device policy for docker_cpu mode
INFO - CPU-only enforcement verified: CUDA not available
INFO - Device after policy enforcement: cpu
```

### Verify Device Policy

```bash
# Inside container or worker process
python -c "
import torch
print(f'CUDA available: {torch.cuda.is_available()}')
print(f'Device count: {torch.cuda.device_count()}')
print(f'CUDA_VISIBLE_DEVICES: {os.environ.get(\"CUDA_VISIBLE_DEVICES\", \"not set\")}')
"
```

Expected output for docker_cpu mode:
```
CUDA available: False
Device count: 0
CUDA_VISIBLE_DEVICES:
```

## Rollback Procedures

### Rollback to Legacy Mode

1. Remove `EXECUTION_MODE` environment variable from deployment:
   ```bash
   # docker-compose.yml
   environment:
     # - EXECUTION_MODE=docker_cpu  # Comment out
     - WORKER_ID=cpu-1
     - REDIS_HOST=redis
   ```

2. Restart worker:
   ```bash
   docker-compose restart worker-cpu
   ```

3. Verify legacy mode warning in logs:
   ```
   WARNING - Running without EXECUTION_MODE environment variable is deprecated.
   Set EXECUTION_MODE to 'windows_cuda', 'docker_cpu', or 'docker_gpu'.
   ```

### Rollback to Phase 5 (SharedEngines without Dual-Run)

1. Revert changes to:
   - `src/workers/job_processor.py` (main function)
   - `docker-compose.yml` (remove EXECUTION_MODE)
   - `config/global.yaml` (remove execution section)

2. Remove new files:
   - `src/workers/runner.py`
   - `tests/unit/workers/test_runner.py`
   - `scripts/deploy_windows_worker.ps1`

3. Redeploy workers without EXECUTION_MODE

## Performance Considerations

### docker_cpu Mode
- **Slower** than GPU modes (expected for CPU inference)
- **More resilient** with higher retry count (5 vs 3)
- **Faster polling** (3s vs 5s) for better responsiveness
- **Zero GPU costs** - ideal for cloud cost optimization

### docker_gpu Mode
- **Fastest** performance with GPU acceleration
- **Higher memory** allocation (6144MB vs 4096MB)
- **Requires** nvidia-docker and CUDA-capable GPU
- **Best for** high-throughput production workloads

### windows_cuda Mode
- **Flexible** device detection (auto-selects best available)
- **Development-friendly** with direct file system access
- **Easy debugging** with native tools and IDEs
- **Best for** local development and testing

## Security Considerations

### CPU-Only Enforcement
- Prevents GPU resource exhaustion in shared environments
- Isolates CPU workers from GPU workers
- Enables fair resource allocation in multi-tenant deployments

### Container Isolation
- Docker containers provide process isolation
- Volume mounts limit file system access (`:ro` for config)
- Network isolation via docker networks
- GPU passthrough requires elevated privileges (nvidia-docker)

## Next Steps

- **Phase 3**: Extend dual-run to all 10 worker types
- **Phase 4**: Add execution mode selection UI
- **Phase 5**: Implement dynamic mode switching (no restart)
- **Phase 6**: Multi-mode load balancing (CPU + GPU workers)

## References

- [TASK-AW-03: Dual-Run Execution Layer Specification](../../specs/task_aw_03_dual_run.md)
- [Phase 5: Autonomous Workers Unification](../../reports/agents/agent_a/phase5_complete/)
- [SharedEngines Architecture](../../docs/architecture/shared_engines.md)
- [Worker Configuration Guide](../../docs/configuration/workers.md)
