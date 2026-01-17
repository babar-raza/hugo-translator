# VRAM Budget Enforcement Policy

**Status:** Implemented
**Version:** 1.0
**Last Updated:** 2026-01-16

## Overview

This specification describes the centralized VRAM budget enforcement system that prevents GPU out-of-memory (OOM) errors by limiting per-process VRAM usage to a configurable percentage (default: 60%).

## Motivation

GPU out-of-memory errors are a common failure mode in translation workloads, especially when:
- Multiple models are loaded sequentially
- Large batches are processed
- Multiple workers share the same GPU
- System has limited VRAM (e.g., 4-6 GB GPUs)

The VRAM budget enforcement system provides:
1. **Early enforcement**: Budget is applied at process startup before any model loading
2. **Centralized configuration**: Single source of truth for VRAM limits (global.yaml)
3. **Percentage-based limits**: Automatically scales to different GPU sizes (e.g., 60% of 8 GB = 4.9 GB)
4. **Idempotent application**: Budget is applied exactly once per device per process
5. **Non-breaking**: Existing CLI usage continues to work without changes

## Configuration

### Global Configuration (global.yaml)

```yaml
hardware:
  enable_gpu: true
  max_gpu_memory_percent: 60  # Primary setting - 60% of total VRAM (safe default)
  max_gpu_memory_mb: null     # Optional explicit override (takes precedence over percent)
  gpu_device_id: -1           # -1 = auto-select best GPU, 0+ = specific device
  allow_cpu_fallback: true
```

### Execution Mode Overrides

Different execution modes can override the global defaults:

```yaml
execution:
  modes:
    windows_cuda:
      max_gpu_memory_percent: 60
      max_gpu_memory_mb: null

    docker_gpu:
      max_gpu_memory_percent: 60
      max_gpu_memory_mb: null  # Can override to explicit value like 6144

    docker_cpu:
      # No VRAM settings - CPU-only mode
```

### Configuration Precedence

Budget resolution follows this precedence (highest to lowest):

1. **Explicit MB limit** (`max_gpu_memory_mb`): Takes absolute priority
2. **Percentage limit** (`max_gpu_memory_percent`): Used if MB not set
3. **Default 60%**: Applied if neither MB nor percent specified

## Architecture

### Core Components

#### 1. VRAMBudget Dataclass (`src/hardware/vram_budget.py`)

Represents a computed VRAM budget with:
- `fraction`: Memory fraction for torch.cuda.set_per_process_memory_fraction (0.0-1.0)
- `percent`: Human-readable percentage (0-100)
- `computed_mb`: Actual MB budget based on GPU total memory
- `source`: How budget was determined ("percent", "mb", "default")

#### 2. VRAMEnforcer Class (`src/hardware/vram_enforcer.py`)

Main enforcement engine with:
- `enforce_from_config(hardware_config, device)`: Apply budget from config
- `enforce_fraction(device_id, fraction)`: Apply specific fraction
- Idempotent enforcement: Only applies once per device per process
- Thread-safe with global enforcement lock

#### 3. LimitingEngine Integration (`src/shared_engines/limiting_engine.py`)

- Computes `max_gpu_memory_mb` from `max_gpu_memory_percent` at initialization
- Passes computed value to ModelLoader
- Ensures SharedEngines has concrete MB value for model loading

#### 4. WorkerRunner Integration (`src/workers/runner.py`)

- Applies VRAM enforcement in `__init__` for CUDA modes
- Enforces BEFORE any model loading
- Only applies in `WINDOWS_CUDA` and `DOCKER_GPU` modes
- Skipped in `DOCKER_CPU` mode (device policy forces CPU)

## Enforcement Flow

### 1. Worker Startup (workers/runner.py)

```python
# WorkerRunner.__init__
1. Device policy enforcement (CPU-only for docker_cpu)
2. VRAM budget enforcement (for windows_cuda, docker_gpu)
   - Read hardware config from mode_config
   - Call VRAMEnforcer.enforce_from_config()
   - Apply torch.cuda.set_per_process_memory_fraction()
3. Continue with worker setup
```

### 2. Model Loading (workers/job_processor.py)

```python
# JobProcessor.setup()
1. Get max_gpu_memory_mb from config:
   - SharedEngines: Use LimitingEngine.limits.max_gpu_memory_mb (pre-computed)
   - Legacy mode: Compute from hardware config using resolve_vram_budget_mb()
2. Pass max_gpu_memory_mb to ModelLoader
3. ModelLoader passes to backend constructors
```

### 3. Backend Enforcement (model_runtime/loader.py)

```python
# HuggingFaceBackend.load() and CTranslate2Backend.load()
1. If max_memory_mb set, apply torch.cuda.set_per_process_memory_fraction()
2. Load model
3. Log memory usage
```

## Enforcement Points

| Location | When Applied | Purpose |
|----------|-------------|---------|
| WorkerRunner.__init__ | Process startup (CUDA modes) | Early process-wide enforcement |
| ModelLoader backend | Model load time | Per-backend enforcement (fallback) |
| LimitingEngine | Initialization | Compute MB from percent for SharedEngines |

## Testing

### Unit Tests

#### test_vram_enforcer.py
- Enforcement with percent, MB, and default
- Idempotent behavior (only applies once)
- GPU disabled/unavailable handling
- Device ID parsing
- Context manager usage

#### test_runner_vram_policy.py
- WINDOWS_CUDA mode applies enforcement
- DOCKER_GPU mode applies enforcement
- DOCKER_CPU mode skips enforcement
- Error handling (graceful degradation)
- Integration with device policy

### Running Tests

```bash
# Run VRAM enforcer tests
pytest tests/unit/hardware/test_vram_enforcer.py -v

# Run runner VRAM policy tests
pytest tests/unit/workers/test_runner_vram_policy.py -v

# Run all hardware tests
pytest tests/unit/hardware/ -v
```

## Usage Examples

### Example 1: Default 60% Budget

```yaml
# global.yaml
hardware:
  enable_gpu: true
  max_gpu_memory_percent: 60
```

On 8 GB GPU:
- Budget: 4915 MB (60% of 8192 MB)
- Applied at worker startup
- Prevents OOM by reserving 40% headroom

### Example 2: Explicit MB Limit

```yaml
# global.yaml
hardware:
  enable_gpu: true
  max_gpu_memory_mb: 4096  # Explicit 4 GB limit
```

On 8 GB GPU:
- Budget: 4096 MB (explicit)
- Applied regardless of GPU size
- Useful for multi-worker scenarios

### Example 3: Higher Limit for Dedicated GPU

```yaml
# global.yaml
execution:
  modes:
    docker_gpu:
      max_gpu_memory_percent: 80  # Higher limit for dedicated container
```

On 16 GB GPU:
- Budget: 13107 MB (80% of 16384 MB)
- More aggressive usage for dedicated resources

## Troubleshooting

### Still Getting OOM Errors

If OOM errors persist after enforcement:

1. **Check budget was applied**: Look for log message:
   ```
   Applied VRAM budget: 4915MB (60.0% of 8192MB) on device cuda:0
   ```

2. **Lower the budget**: Try 50% or explicit MB limit:
   ```yaml
   max_gpu_memory_percent: 50  # More conservative
   # OR
   max_gpu_memory_mb: 3072  # Explicit 3 GB
   ```

3. **Reduce batch size**: Even with budget, large batches can cause OOM:
   ```yaml
   model_defaults:
     batch_size: 2  # Reduce from 4
   ```

### Budget Not Applied

Check these conditions:
1. GPU must be enabled: `enable_gpu: true`
2. Device must be CUDA: `device: "cuda"` or `device: "cuda:0"`
3. CUDA must be available: `torch.cuda.is_available() == True`
4. Execution mode must be CUDA-capable: `WINDOWS_CUDA` or `DOCKER_GPU`

### Idempotent Enforcement

VRAMEnforcer maintains process-wide state to ensure budget is applied exactly once per device:

```python
# First call: applies budget
enforcer = VRAMEnforcer()
max_mb, budget = enforcer.enforce_from_config(config, "cuda:0")
# Logs: "Applied VRAM budget: 4915MB..."

# Second call: no-op (idempotent)
max_mb2, budget2 = enforcer.enforce_from_config(config, "cuda:0")
# Logs: "VRAM budget already applied to device 0 (4915MB, 60.0%)"
```

## Backward Compatibility

### Existing CLI Usage

All existing CLI usage continues to work:

```bash
# Before: Used max_gpu_memory_mb directly
python -m src.cli translate site.yaml -t de -t fr

# After: Automatically uses max_gpu_memory_percent (60% default)
python -m src.cli translate site.yaml -t de -t fr
```

### Legacy Configuration

Old config files with only `max_gpu_memory_mb` continue to work:

```yaml
# Old config (still works)
hardware:
  max_gpu_memory_mb: 4096

# New config (preferred)
hardware:
  max_gpu_memory_percent: 60
  max_gpu_memory_mb: null
```

## Future Enhancements

### Multi-Worker Coordination

Future versions could add Redis-based coordination for multi-worker VRAM allocation:

```yaml
hardware:
  vram_coordination:
    enabled: true
    redis_lock_key: "vram_allocation"
    worker_count: 4
    per_worker_percent: 15  # 4 workers × 15% = 60% total
```

### Dynamic Budget Adjustment

Adaptive budget based on actual usage patterns:

```yaml
hardware:
  adaptive_vram:
    enabled: true
    min_percent: 50
    max_percent: 80
    adjust_on_oom: true
```

## References

- PyTorch CUDA Memory Management: https://pytorch.org/docs/stable/notes/cuda.html#memory-management
- VRAM Budget Computation: [src/hardware/vram_budget.py](../../src/hardware/vram_budget.py)
- VRAM Enforcer Implementation: [src/hardware/vram_enforcer.py](../../src/hardware/vram_enforcer.py)
- Worker Integration: [src/workers/runner.py](../../src/workers/runner.py)
- LimitingEngine Integration: [src/shared_engines/limiting_engine.py](../../src/shared_engines/limiting_engine.py)

## Acceptance Criteria

- [x] VRAMBudget dataclass with fraction, percent, computed_mb
- [x] resolve_vram_budget_mb() with 3-tier precedence
- [x] VRAMEnforcer with enforce_from_config() and idempotent behavior
- [x] ensure_vram_budget() context manager
- [x] LimitingEngine computes max_gpu_memory_mb from percent
- [x] WorkerRunner applies enforcement for WINDOWS_CUDA and DOCKER_GPU
- [x] JobProcessor passes max_memory_mb to ModelLoader
- [x] Unit tests for VRAMEnforcer (mocked torch.cuda)
- [x] Unit tests for WorkerRunner VRAM policy
- [x] Documentation in VRAM_POLICY.md
- [x] global.yaml updated with max_gpu_memory_percent
- [x] Existing CLI usage continues to work
