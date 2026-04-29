# Hardware Setup and Optimization Guide

**Version:** 1.0.0
**Last Updated:** 2025-12-19
**Audience:** Operations Team

---

## Table of Contents

1. [System Requirements](#system-requirements)
2. [GPU Setup](#gpu-setup)
3. [CPU Optimization](#cpu-optimization)
4. [Memory Management](#memory-management)
5. [Performance Tuning](#performance-tuning)
6. [Troubleshooting](#troubleshooting)
7. [Verification Procedures](#verification-procedures)

---

## System Requirements

### Minimum Hardware Requirements

| Component | CPU-Only | GPU-Enabled |
|-----------|----------|-------------|
| **CPU** | 4 cores (x86_64) | 4+ cores (x86_64) |
| **RAM** | 8GB | 8GB+ |
| **GPU** | N/A | NVIDIA GPU with 8GB+ VRAM |
| **Storage** | 50GB SSD | 50GB+ SSD |
| **Network** | 100 Mbps | 1 Gbps |

### Recommended Hardware

| Component | Specification | Notes |
|-----------|---------------|-------|
| **CPU** | 8+ cores (Intel i7/AMD Ryzen 7+) | More cores = better parallel processing |
| **RAM** | 16GB+ DDR4 | 32GB+ for large batch processing |
| **GPU** | NVIDIA RTX 30/40 series, 8GB+ VRAM | CUDA 11.8+ compatible |
| **Storage** | NVMe SSD 500GB+ | Fast I/O for model loading and TM access |
| **Network** | 1 Gbps | Required for distributed deployments |

---

## GPU Setup

### Prerequisites

The system uses CUDA 11.8 with cuDNN 8 for GPU acceleration. All GPU operations are handled through:

- **PyTorch** with CUDA support
- **CTranslate2** for optimized inference
- **FAISS-GPU** for semantic search

### NVIDIA Driver Installation

#### Ubuntu/Debian

```bash
# Update package lists
sudo apt update

# Install NVIDIA drivers (version 525+ required)
sudo apt install nvidia-driver-525

# Reboot system
sudo reboot

# Verify installation
nvidia-smi
```

#### Windows

1. Download NVIDIA drivers from [nvidia.com](https://www.nvidia.com/Download/index.aspx)
2. Install with default settings
3. Reboot system
4. Verify with `nvidia-smi` in PowerShell

#### macOS

GPU acceleration is not supported on macOS. Use CPU-only mode.

### CUDA Toolkit Installation

#### Ubuntu/Debian

```bash
# Add CUDA repository
wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-ubuntu2204.pin
sudo mv cuda-ubuntu2204.pin /etc/apt/preferences.d/cuda-repository-pin-600
wget https://developer.download.nvidia.com/compute/cuda/11.8.0/local_installers/cuda_11.8.0_520.61.05_linux.run
sudo sh cuda_11.8.0_520.61.05_linux.run

# Add to PATH
echo 'export PATH=/usr/local/cuda/bin:$PATH' >> ~/.bashrc
echo 'export LD_LIBRARY_PATH=/usr/local/cuda/lib64:$LD_LIBRARY_PATH' >> ~/.bashrc
source ~/.bashrc

# Verify CUDA installation
nvcc --version
```

#### Windows

1. Download CUDA 11.8 from [NVIDIA Developer](https://developer.nvidia.com/cuda-11-8-0-download-archive)
2. Install with default settings
3. Verify with `nvcc --version` in PowerShell

### NVIDIA Docker Runtime

#### Ubuntu/Debian

```bash
# Add NVIDIA Docker repository
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | sudo tee /etc/apt/sources.list.d/nvidia-docker.list

# Install NVIDIA Docker
sudo apt-get update && sudo apt-get install -y nvidia-docker2
sudo systemctl restart docker

# Test GPU access in container
docker run --rm --gpus all nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04 nvidia-smi
```

#### Windows

NVIDIA Docker is supported through Docker Desktop with WSL2:

1. Enable WSL2 in Docker Desktop settings
2. Enable GPU support in Docker Desktop → Settings → Resources → Advanced
3. Test with: `docker run --rm --gpus all nvidia/cuda:11.8.0-base nvidia-smi`

### GPU Worker Deployment

#### Docker Compose

```bash
# Start with GPU support
docker-compose --profile gpu up -d

# Verify GPU worker
docker-compose logs worker-gpu-1
docker-compose exec worker-gpu-1 nvidia-smi
```

#### Environment Variables

```env
# GPU-specific settings
CUDA_VISIBLE_DEVICES=0
PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:512
```

### GPU Memory Management

#### VRAM Monitoring

```bash
# Real-time GPU usage
watch -n 1 nvidia-smi

# GPU memory info
nvidia-smi --query-gpu=memory.used,memory.total --format=csv
```

#### Memory Optimization

```python
# In Python scripts
import torch

# Enable memory efficient operations
torch.cuda.set_per_process_memory_fraction(0.8)  # Use 80% of GPU memory
torch.cuda.empty_cache()  # Clear cache between operations
```

---

## CPU Optimization

### Automatic CPU Optimization

The system includes automatic CPU optimization that detects hardware capabilities and configures optimal settings:

```python
from src.model_runtime.cpu_optimizer import CPUOptimizer

# Auto-detect optimal settings
optimizer = CPUOptimizer()
config = optimizer.optimize()

print(f"Batch size: {config.batch_size}")
print(f"Thread count: {config.num_threads}")
```

### Batch Size Selection

#### Memory-Based Auto-Detection

| RAM | Recommended Batch Size | Notes |
|-----|----------------------|-------|
| <8GB | 4-8 | Conservative to prevent OOM |
| 8-16GB | 8-16 | Balanced throughput/memory |
| 16-32GB | 16-32 | Higher throughput |
| 32GB+ | 32-48 | Maximum performance |

#### Manual Override

```bash
# Override batch size
translate-hugo \
  --site example \
  --input content/ \
  --output translated/ \
  --batch-size 16
```

### Thread Count Optimization

#### Physical vs Logical Cores

```python
import psutil

# Get physical cores (recommended)
physical_cores = psutil.cpu_count(logical=False)
print(f"Physical cores: {physical_cores}")

# Reserve 1 core for OS on systems with 8+ cores
if physical_cores >= 8:
    optimal_threads = physical_cores - 1
else:
    optimal_threads = physical_cores
```

#### Environment Variables

The optimizer automatically sets:

```bash
export OMP_NUM_THREADS=7        # OpenMP threads
export MKL_NUM_THREADS=7        # Intel MKL threads
export NUMEXPR_MAX_THREADS=7    # NumExpr threads
```

### Model Selection for CPU

#### Recommended CPU Models

| Model | Backend | Memory | Speed | Use Case |
|-------|---------|--------|-------|----------|
| `m2m100_418m_ct2` | CTranslate2 FP32 | ~1.2GB | Fastest | Production CPU |
| `m2m100_418m_ct2_int8` | CTranslate2 INT8 | ~600MB | Fast | Memory-constrained |
| `m2m100_418m` | HuggingFace | ~2.4GB | Baseline | Development |

#### Model Conversion

Convert HuggingFace models to CTranslate2 for CPU optimization:

```bash
python -m src.model_runtime.ct2_converter \
  --model models/m2m100_418M \
  --output models/ct2/m2m100_418m \
  --quantization int8 \
  --validate
```

---

## Memory Management

### RAM Monitoring

#### System Memory Usage

```bash
# Real-time memory monitoring
watch -n 1 free -h

# Detailed memory info
cat /proc/meminfo | grep -E "(MemTotal|MemFree|MemAvailable)"
```

#### Python Memory Monitoring

```python
import psutil
import os

def get_memory_usage():
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / 1024 / 1024  # MB

print(f"Current memory usage: {get_memory_usage():.1f} MB")
```

### Memory Optimization Strategies

#### Translation Memory (L1 Cache)

```yaml
# In global.yaml
tm:
  l1_cache_size: 10000  # Increase for more segments in memory
```

#### Batch Processing Memory

- **Small batches**: Lower memory usage, slower processing
- **Large batches**: Higher memory usage, faster processing
- **Optimal balance**: Keep memory usage under 70% of available RAM

#### Garbage Collection Tuning

```python
import gc

# Force garbage collection between batches
gc.collect()

# Disable automatic GC for performance
gc.disable()
# ... run translation ...
gc.enable()
```

### Out-of-Memory Prevention

#### Safety Margins

- Reserve 2GB minimum free RAM for OS operations
- Keep translation memory under 50% of total RAM
- Monitor for memory leaks in long-running processes

#### OOM Recovery

```python
# Graceful degradation on OOM
try:
    result = engine.translate_batch(batch)
except RuntimeError as e:
    if "out of memory" in str(e).lower():
        # Reduce batch size and retry
        smaller_batch = batch[:len(batch)//2]
        result = engine.translate_batch(smaller_batch)
        # Log OOM event
        logger.warning(f"OOM detected, reduced batch size to {len(smaller_batch)}")
```

---

## Performance Tuning

### Benchmarking Your Hardware

#### CPU Benchmark

```bash
# Run comprehensive CPU benchmarks
python scripts/benchmark_cpu_comprehensive.py \
  --models m2m100_418m_ct2 \
  --batch-sizes 4,8,16 \
  --iterations 3 \
  --corpus small \
  --save-to-db data/benchmarks/cpu.db
```

#### GPU Benchmark

```bash
# GPU translation benchmark
python scripts/benchmark_gpu_translation.py \
  --model m2m100_418m \
  --batch-sizes 16,32,64 \
  --iterations 5 \
  --output results/gpu_benchmark.json
```

### Parallel Processing

#### Worker Scaling Guidelines

| Hardware | CPU Workers | GPU Workers | Notes |
|----------|-------------|-------------|-------|
| 4 cores, 8GB RAM | 1 | N/A | Single-threaded |
| 8 cores, 16GB RAM | 2-4 | 1 | Balanced |
| 16+ cores, 32GB+ RAM | 4-8 | 1-2 | High-throughput |

#### Memory per Worker

- **CPU Worker**: 2-4GB RAM per worker
- **GPU Worker**: 4-8GB VRAM per worker
- **Overhead**: 1GB per worker for OS and libraries

### Storage Optimization

#### Fast Storage Requirements

- **NVMe SSD**: Recommended for model loading and TM access
- **I/O Speed**: 500MB/s+ read/write speeds
- **Space**: 50GB+ for models, TM, and temporary files

#### TM Database Optimization

```yaml
# LMDB settings for performance
tm:
  l2_max_size_mb: 2048
  l2_sync_interval: 300  # seconds
```

---

## Troubleshooting

### GPU Issues

#### "CUDA not available"

```bash
# Check NVIDIA driver
nvidia-smi

# Check CUDA installation
nvcc --version

# Test PyTorch CUDA
python -c "import torch; print(torch.cuda.is_available())"
```

**Solutions:**
1. Reinstall NVIDIA drivers
2. Update CUDA toolkit
3. Check GPU compatibility (CUDA 11.8+ required)

#### "Out of GPU memory"

```bash
# Monitor GPU memory
nvidia-smi --query-gpu=memory.used,memory.total --format=csv

# Reduce batch size
export PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:512
```

**Solutions:**
1. Reduce batch size in configuration
2. Use smaller models
3. Enable memory fragmentation prevention

#### Docker GPU Access Failed

```bash
# Test NVIDIA Docker
docker run --rm --gpus all nvidia/cuda:11.8.0-base nvidia-smi

# Check Docker daemon configuration
sudo systemctl status nvidia-docker
```

### CPU Issues

#### Low Throughput

```bash
# Check thread utilization
htop  # or Task Manager on Windows

# Verify environment variables
echo $OMP_NUM_THREADS
echo $MKL_NUM_THREADS
```

**Solutions:**
1. Run CPU optimizer: `python -c "from src.model_runtime.cpu_optimizer import CPUOptimizer; print(CPUOptimizer().optimize())"`
2. Check for background processes consuming CPU
3. Verify physical cores are being used

#### High Memory Usage

```bash
# Monitor memory
free -h

# Check for memory leaks
python -c "import psutil; print(psutil.Process().memory_info())"
```

**Solutions:**
1. Reduce batch size
2. Use CT2 INT8 models
3. Enable garbage collection
4. Check for memory leaks in model backends

### Common Issues

#### Model Loading Failures

```bash
# Check model cache permissions
ls -l data/models/

# Verify model integrity
python -c "from transformers import AutoModel; AutoModel.from_pretrained('models/m2m100_418M')"
```

#### TM Database Corruption

```bash
# Backup current TM
cp data/tm/tm.lmdb data/tm/tm.lmdb.backup

# Rebuild TM index
python scripts/build_l3_index.py --use-gpu
```

---

## Verification Procedures

### Hardware Detection Test

```python
# Test hardware detection
from src.model_runtime.hardware import HardwareDetector

detector = HardwareDetector()
hw_info = detector.detect()

print(f"CPU cores: {hw_info.cpu_count}")
print(f"RAM: {hw_info.total_ram_gb:.1f}GB")
print(f"GPU available: {hw_info.gpu_available}")
print(f"Recommended device: {hw_info.recommended_device}")
```

### GPU Verification

```bash
# Comprehensive GPU test
docker run --rm --gpus all nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04 bash -c "
nvidia-smi && \
python -c 'import torch; print(f\"PyTorch CUDA: {torch.cuda.is_available()}\")' && \
python -c 'import ctranslate2; print(\"CTranslate2: OK\")' && \
echo 'GPU setup verified'
"
```

### CPU Optimization Test

```bash
# Test CPU optimizer
python -c "
from src.model_runtime.cpu_optimizer import CPUOptimizer
config = CPUOptimizer().optimize()
print(f'Batch size: {config.batch_size}')
print(f'Threads: {config.num_threads}')
print('CPU optimization: OK')
"
```

### End-to-End Performance Test

```bash
# Create test file
echo "# Test Document

This is a test document for translation performance verification.

## Section 1

Some content to translate.

## Section 2

More content for testing." > test_content.md

# Run translation test
translate-hugo \
  --site default \
  --input test_content.md \
  --output test_translated.md \
  --source-lang en \
  --target-lang es

# Check results
cat test_translated.md
```

### Performance Benchmarks

```bash
# Quick performance test
python scripts/benchmark_cpu_comprehensive.py \
  --models m2m100_418m_ct2 \
  --batch-sizes 8 \
  --iterations 1 \
  --corpus tiny \
  --verbose
```

---

## Best Practices

### Hardware Selection

1. **GPU-first for production**: 5-10x faster than CPU for supported models
2. **CPU for cost optimization**: Lower infrastructure costs, good for development
3. **Balance RAM and cores**: More RAM allows larger batches, more cores enable parallelism

### Configuration Management

1. **Test configurations**: Always benchmark before production deployment
2. **Monitor resources**: Set up alerts for high memory/CPU usage
3. **Regular updates**: Keep drivers and CUDA toolkit current
4. **Backup configurations**: Document working hardware setups

### Maintenance

1. **Regular benchmarks**: Track performance over time
2. **Update drivers**: NVIDIA releases improve performance and fix bugs
3. **Monitor temperatures**: GPU/CPU thermal throttling reduces performance
4. **Clean up models**: Remove unused cached models to free disk space

### Scaling

1. **Start small**: Test with minimal resources, scale up gradually
2. **Horizontal scaling**: Add workers before upgrading hardware
3. **Resource limits**: Set Docker memory/CPU limits to prevent resource exhaustion
4. **Load balancing**: Distribute work across multiple workers

---

**Document Version:** 1.0.0
**Last Updated:** 2025-12-19
