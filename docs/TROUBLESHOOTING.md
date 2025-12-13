# Hugo Translation System - Troubleshooting Guide

**Version:** 1.0.0
**Last Updated:** 2025-11-21

---

## Table of Contents

1. [Common Issues and Solutions](#common-issues-and-solutions)
2. [Error Messages Reference](#error-messages-reference)
3. [Performance Problems](#performance-problems)
4. [Docker Issues](#docker-issues)
5. [Model Loading Issues](#model-loading-issues)
6. [Translation Memory Issues](#translation-memory-issues)
7. [Configuration Issues](#configuration-issues)
8. [Debugging Techniques](#debugging-techniques)
9. [Getting Help](#getting-help)

---

## Common Issues and Solutions

### Issue: Services Won't Start

**Symptoms:**
- `docker-compose up` fails
- Containers exit immediately
- Health checks failing

**Diagnosis:**

```bash
# Check service status
docker-compose ps

# View logs
docker-compose logs orchestrator
docker-compose logs worker-cpu-1

# Check for port conflicts
netstat -tulpn | grep -E '(9090|9091|3000)'
```

**Solutions:**

1. **Port conflict:**
   ```bash
   # Find process using port
   lsof -i :9090

   # Kill process or change port in docker-compose.yml
   # ports:
   #   - "9095:9090"  # Use different external port
   ```

2. **Configuration error:**
   ```bash
   # Validate docker-compose.yml
   docker-compose config

   # Validate configuration files
   python -c "
   from pathlib import Path
   from src.utils.config_loader import ConfigService
   config = ConfigService(Path('config'))
   print('✓ Configuration valid')
   "
   ```

3. **Missing volumes:**
   ```bash
   # Create required directories
   mkdir -p data/tm data/models data/artifacts data/logs

   # Check volume mounts
   docker volume ls
   docker-compose down -v  # WARNING: Removes volumes
   docker-compose up -d
   ```

4. **Docker daemon issues:**
   ```bash
   # Restart Docker daemon
   sudo systemctl restart docker

   # Check Docker status
   sudo systemctl status docker
   ```

---

### Issue: Translation Failures

**Symptoms:**
- `translate_file()` returns `success=False`
- Errors in logs
- Partial translations

**Diagnosis:**

```python
# Check translation result
result = engine.translate_file(...)

if not result.success:
    print("Errors:")
    for error in result.errors:
        print(f"  - {error}")

    print("\nValidation Issues:")
    for issue in result.validation_issues:
        print(f"  - {issue.severity}: {issue.message}")
```

**Solutions:**

1. **Invalid frontmatter:**
   ```yaml
   # Check YAML syntax
   ---
   title: "Valid Title"  # Use quotes if contains special chars
   date: 2024-01-01
   ---
   ```

2. **Unsupported language pair:**
   ```python
   # Check model supports language pair
   from src.model_runtime.registry import ModelRegistry

   registry = ModelRegistry(Path('config/model_registry.yaml'))
   model = registry.get_model('m2m100_418m')

   # Check supported pairs
   if model.supported_pairs == 'all':
       print("All pairs supported")
   else:
       print(f"Supported: {model.supported_pairs}")
   ```

3. **Model loading failure:**
   ```python
   # Test model loading
   from src.model_runtime.loader import ModelLoader

   loader = ModelLoader(registry, device='auto')
   try:
       model = loader.load_model('m2m100_418m')
       print("✓ Model loaded")
   except Exception as e:
       print(f"✗ Model load failed: {e}")
   ```

4. **File encoding issues:**
   ```bash
   # Check file encoding
   file -i content/post.md

   # Convert to UTF-8 if needed
   iconv -f ISO-8859-1 -t UTF-8 content/post.md > content/post_utf8.md
   ```

---

### Issue: Low Translation Memory Hit Rate

**Symptoms:**
- TM hit rate <20%
- Many model calls
- Slow translation

**Diagnosis:**

```python
from pathlib import Path
from src.observability.tm_admin import TranslationMemoryAdmin
from src.tm.translation_memory import create_translation_memory

tm = create_translation_memory(Path('data/tm'))
admin = TranslationMemoryAdmin(tm)
stats = admin.get_statistics()

print(f"L1 hit rate: {stats.l1_hit_rate:.2%}")
print(f"L2 hit rate: {stats.l2_hit_rate:.2%}")
print(f"L3 hit rate: {stats.l3_hit_rate:.2%}")
print(f"Total entries: {stats.total_entries:,}")
```

**Solutions:**

1. **TM not populated:**
   ```bash
   # Run batch translation to populate TM
   docker-compose exec orchestrator python -c "
   from pathlib import Path
   from src.translation_engine.engine import TranslationEngine
   # ... initialize engine

   result = engine.translate_directory(
       site_id='mysite',
       directory=Path('/data/content'),
       target_langs=['fr'],
       recursive=True
   )
   "
   ```

2. **Semantic threshold too high:**
   ```yaml
   # In site profile, lower threshold
   tm_prefs:
     semantic_threshold: 0.75  # Lower from 0.80
   ```

3. **Semantic TM disabled:**
   ```yaml
   # Enable semantic TM
   tm_prefs:
     use_semantic_tm: true
   ```

4. **Content too diverse:**
   ```python
   # Check TM content diversity
   entries = admin.list_entries(limit=100)

   # If content varies significantly, semantic TM won't help much
   # Consider domain-specific models
   ```

---

### Issue: Slow Translation Performance

**Symptoms:**
- Translations taking too long
- High CPU/memory usage
- Timeout errors

**Diagnosis:**

```bash
# Check resource usage
docker stats --no-stream

# Profile translation
docker-compose exec worker-cpu-1 python -c "
import time
from pathlib import Path
from src.translation_engine.engine import TranslationEngine
# ... initialize

test_file = Path('/data/content/test.md')

start = time.time()
result = engine.translate_file('mysite', test_file, ['fr'])
duration = time.time() - start

print(f'Translation time: {duration:.2f}s')
print(f'Segments: {result.stats.total_segments}')
print(f'Speed: {result.stats.total_segments / duration:.1f} segments/sec')
"
```

**Solutions:**

1. **Enable parallel processing:**
   ```bash
   # Edit .env.production
   PARALLEL_TRANSLATION=true
   MAX_PARALLEL_FILES=8

   # Restart
   docker-compose restart
   ```

2. **Use GPU:**
   ```bash
   # Check GPU available
   docker-compose exec worker-gpu-1 nvidia-smi

   # Enable GPU worker
   docker-compose --profile gpu up -d

   # Set device
   DEVICE=cuda
   ```

3. **Use faster model:**
   ```yaml
   # Use CTranslate2 model (faster on CPU)
   model_prefs:
     preferred_model: "m2m100_418m_ct2"
   ```

4. **Increase batch size:**
   ```bash
   # If memory allows
   MODEL_BATCH_SIZE=64  # Increase from 32
   ```

5. **Optimize TM lookups:**
   ```yaml
   # Increase L1 cache size
   tm_defaults:
     l1_cache_size: 20000  # Increase from 10000
   ```

---

### Issue: Out of Memory

**Symptoms:**
- Container killed (OOM)
- Slow performance
- Swap usage high

**Diagnosis:**

```bash
# Check memory usage
docker stats --no-stream

# Check system memory
free -h

# Check container limits
docker inspect translator-worker-cpu-1 | grep -A 5 Memory

# Check process memory
docker-compose exec worker-cpu-1 ps aux --sort=-%mem | head -10
```

**Solutions:**

1. **Reduce batch size:**
   ```bash
   MODEL_BATCH_SIZE=16  # Reduce from 32
   docker-compose restart worker-cpu-1
   ```

2. **Reduce cache sizes:**
   ```yaml
   # In config/global.yaml
   tm_defaults:
     l1_cache_size: 5000  # Reduce from 10000

   model_defaults:
     max_cached_models: 1  # Reduce from 2
   ```

3. **Use smaller model:**
   ```yaml
   model_prefs:
     preferred_model: "opus_en_fr"  # Smaller than m2m100
   ```

4. **Set memory limits:**
   ```yaml
   # In docker-compose.yml
   services:
     worker-cpu-1:
       deploy:
         resources:
           limits:
             memory: 6G
           reservations:
             memory: 4G
   ```

5. **Reduce worker count:**
   ```bash
   # Stop extra workers
   docker-compose stop worker-cpu-2 worker-cpu-3

   # Or reduce MAX_WORKERS
   MAX_WORKERS=2
   ```

---

## Error Messages Reference

### Configuration Errors

#### `ConfigError: Site profile not found: <site-id>`

**Cause:** Site profile file missing or misnamed

**Solution:**
```bash
# Check profile exists
ls -l config/site_profiles/<site-id>.yaml

# Verify site_id matches filename
grep "site_id:" config/site_profiles/<site-id>.yaml
```

---

#### `ValidationError: Invalid frontmatter mode: <mode>`

**Cause:** Invalid mode in site profile

**Solution:**
```yaml
# Valid modes:
frontmatter:
  field: { mode: translate }         # ✓
  field: { mode: passthrough }       # ✓
  field: { mode: computed }          # ✓
  field: { mode: translate_list }    # ✓
  field: { mode: copy_structure }    # ✓
  field: { mode: ignore }            # ✓
  field: { mode: invalid }           # ✗
```

---

### Model Errors

#### `ModelLoadError: Failed to load model: <model-id>`

**Cause:** Model not downloaded or incompatible

**Solution:**
```bash
# Download model
docker-compose exec worker-cpu-1 python -c "
from src.model_runtime.loader import download_model
download_model('<model-id>')
"

# Check model registry
grep -A 10 "<model-id>" config/model_registry.yaml

# Verify model files
docker-compose exec worker-cpu-1 ls -lh /data/models/<model-id>
```

---

#### `DeviceError: CUDA not available`

**Cause:** GPU requested but not available

**Solution:**
```bash
# Check GPU
nvidia-smi

# If no GPU, use CPU
DEVICE=cpu

# Or use auto-detect
DEVICE=auto
```

---

#### `MemoryError: Unable to allocate tensor`

**Cause:** Model too large for available memory

**Solution:**
```bash
# Use smaller model
DEFAULT_MODEL=opus_en_fr  # Instead of m2m100_1.2b

# Or reduce batch size
MODEL_BATCH_SIZE=8

# Or use CTranslate2 (more efficient)
DEFAULT_MODEL=m2m100_418m_ct2
```

---

### Translation Memory Errors

#### `TMError: Failed to open database`

**Cause:** LMDB database corrupted or locked

**Solution:**
```bash
# Stop services
docker-compose down

# Remove corrupted database
rm -rf data/tm/*.lmdb*

# Restore from backup
tar -xzf backups/latest/tm_data.tar.gz -C data/

# Restart
docker-compose up -d
```

---

#### `IndexError: Semantic index not found`

**Cause:** L3 semantic index missing or corrupted

**Solution:**
```python
# Rebuild index
from pathlib import Path
from src.tm.l3_semantic import L3SemanticTM

l3 = L3SemanticTM(Path('data/tm/index'))
l3.rebuild_index()
print("✓ Index rebuilt")
```

---

### Translation Errors

#### `SegmentExtractionError: Failed to parse frontmatter`

**Cause:** Invalid YAML in frontmatter

**Solution:**
```yaml
# Check YAML syntax
---
title: "Fix: Use quotes"  # ✓ Quoted
date: 2024-01-01          # ✓ Valid date
tags: [tech, blog]        # ✓ Valid list
invalid: {                # ✗ Unclosed brace
---

# Validate YAML
python -c "
import yaml
content = open('content/post.md').read()
frontmatter = content.split('---')[1]
yaml.safe_load(frontmatter)
"
```

---

#### `ValidationError: Placeholder mismatch`

**Cause:** Placeholders not preserved in translation

**Solution:**
```python
# Check preserve_patterns in site profile
preserve_patterns:
  - "{{<"   # Hugo shortcodes
  - "{{%"
  - "{0}"   # Format placeholders
  - "http://"

# If issue persists, disable strict mode
validation:
  strict_mode: false
```

---

#### `ReconstructionError: Failed to reconstruct document`

**Cause:** Document structure corrupted during translation

**Solution:**
```bash
# Enable debug logging
LOG_LEVEL=DEBUG
FLOW_ARTIFACT_DETAIL=full

# Review flow artifacts
docker-compose logs worker-cpu-1 | grep reconstruction

# Check source file structure
cat content/problematic.md
```

---

## Performance Problems

### High CPU Usage

**Symptoms:**
- CPU usage >90% sustained
- System sluggish
- Slow response times

**Diagnosis:**
```bash
# Check CPU usage by container
docker stats --no-stream

# Check process CPU
docker-compose exec worker-cpu-1 top -b -n 1
```

**Solutions:**

1. **Limit worker count:**
   ```bash
   MAX_WORKERS=2  # Reduce from 4
   ```

2. **Set CPU limits:**
   ```yaml
   deploy:
     resources:
       limits:
         cpus: '2'
   ```

3. **Reduce parallel files:**
   ```bash
   MAX_PARALLEL_FILES=2  # Reduce from 8
   ```

---

### High Memory Usage

**Symptoms:**
- Memory usage >80%
- Swap usage increasing
- OOM kills

**Solutions:** See [Out of Memory](#issue-out-of-memory) section

---

### Slow Database Operations

**Symptoms:**
- TM lookups slow
- High I/O wait
- Database lock timeouts

**Diagnosis:**
```bash
# Check I/O
docker-compose exec orchestrator iostat -x 1 10

# Check database size
docker-compose exec orchestrator du -sh /data/tm/*.lmdb*
```

**Solutions:**

1. **Compact database:**
   ```python
   from pathlib import Path
   from src.tm.l2_persistent import L2PersistentTM

   l2 = L2PersistentTM(Path('data/tm/db.lmdb'))
   l2.compact()
   l2.close()
   ```

2. **Use SSD storage:**
   ```yaml
   # Mount on SSD volume
   volumes:
     - /mnt/ssd/tm:/data/tm
   ```

3. **Increase cache size:**
   ```yaml
   tm_defaults:
     l1_cache_size: 20000
   ```

---

## Docker Issues

### Container Exits Immediately

**Diagnosis:**
```bash
# Check exit code
docker-compose ps

# View exit logs
docker-compose logs --tail=50 orchestrator
```

**Solutions:**

1. **Check command:**
   ```yaml
   # In docker-compose.yml
   command: ["python", "-m", "src.orchestrator.orchestrator"]
   ```

2. **Check paths:**
   ```bash
   docker-compose exec orchestrator ls -l /app/src
   ```

3. **Check permissions:**
   ```bash
   docker-compose exec orchestrator ls -la /data
   ```

---

### Health Check Failing

**Diagnosis:**
```bash
# Check health status
docker inspect translator-orchestrator | grep -A 10 Health

# Run health check manually
docker-compose exec orchestrator python -c "import sys; sys.exit(0)"
```

**Solutions:**

1. **Increase timeout:**
   ```yaml
   healthcheck:
     timeout: 30s  # Increase from 10s
     start_period: 60s  # Increase from 40s
   ```

2. **Fix health check command:**
   ```yaml
   healthcheck:
     test: ["CMD", "python", "-c", "import sys; sys.exit(0)"]
   ```

---

### Volume Permission Errors

**Symptoms:**
- Permission denied errors
- Cannot write to /data

**Solution:**
```bash
# Check volume ownership
docker-compose exec orchestrator ls -la /data

# Fix permissions
docker-compose down
sudo chown -R 1000:1000 data/
docker-compose up -d
```

---

### Network Issues

**Symptoms:**
- Containers can't communicate
- Connection refused errors

**Diagnosis:**
```bash
# Check network
docker network ls
docker network inspect translator_net

# Test connectivity
docker-compose exec worker-cpu-1 ping orchestrator
docker-compose exec worker-cpu-1 curl http://prometheus:9090
```

**Solutions:**

1. **Recreate network:**
   ```bash
   docker-compose down
   docker network rm translator_net
   docker-compose up -d
   ```

2. **Check DNS:**
   ```yaml
   # Add explicit DNS
   services:
     worker:
       dns:
         - 8.8.8.8
   ```

---

## Model Loading Issues

### Model Download Fails

**Symptoms:**
- Download timeout
- Connection errors
- Incomplete downloads

**Solutions:**

1. **Use HuggingFace token:**
   ```bash
   # Get token from https://huggingface.co/settings/tokens
   HF_TOKEN=your_token_here
   ```

2. **Download manually:**
   ```bash
   # Download to local directory
   git lfs install
   git clone https://huggingface.co/facebook/m2m100_418M models/m2m100_418m

   # Update registry with local path
   ```

3. **Use mirror:**
   ```bash
   # Set HuggingFace mirror
   export HF_ENDPOINT=https://hf-mirror.com
   ```

---

### Model Version Incompatibility

**Symptoms:**
- "Model file corrupt" errors
- Tensor shape mismatch
- Unexpected model behavior

**Solution:**
```bash
# Remove and re-download model
docker-compose exec worker-cpu-1 rm -rf /data/models/<model-id>

docker-compose exec worker-cpu-1 python -c "
from src.model_runtime.loader import download_model
download_model('<model-id>', force=True)
"
```

---

### GPU Not Detected

**Symptoms:**
- CUDA not available
- Model falls back to CPU

**Diagnosis:**
```bash
# Check GPU in container
docker-compose exec worker-gpu-1 nvidia-smi

# Check Docker GPU runtime
docker run --rm --gpus all nvidia/cuda:11.0-base nvidia-smi
```

**Solutions:**

1. **Install NVIDIA Docker:**
   ```bash
   distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
   curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | \
     sudo tee /etc/apt/sources.list.d/nvidia-docker.list

   sudo apt-get update
   sudo apt-get install -y nvidia-docker2
   sudo systemctl restart docker
   ```

2. **Update docker-compose.yml:**
   ```yaml
   services:
     worker-gpu-1:
       deploy:
         resources:
           reservations:
             devices:
               - driver: nvidia
                 count: 1
                 capabilities: [gpu]
   ```

3. **Check CUDA version:**
   ```bash
   # Ensure CUDA version matches model requirements
   nvidia-smi
   # Should show CUDA 11.0+
   ```

---

## Translation Memory Issues

### L3 Semantic Search Not Working

**Symptoms:**
- No semantic matches found
- L3 hit rate 0%
- Embedding errors

**Diagnosis:**
```python
from pathlib import Path
from src.tm.l3_semantic import L3SemanticTM

l3 = L3SemanticTM(Path('data/tm/index'))

# Test embedding
try:
    embedding = l3._embed_text("test text")
    print(f"✓ Embedding works: shape {embedding.shape}")
except Exception as e:
    print(f"✗ Embedding failed: {e}")
```

**Solutions:**

1. **Download embedding model:**
   ```python
   from sentence_transformers import SentenceTransformer

   model = SentenceTransformer(
       'sentence-transformers/paraphrase-multilingual-mpnet-base-v2'
   )
   # Model will download automatically
   ```

2. **Rebuild index:**
   ```python
   l3.rebuild_index()
   ```

3. **Check threshold:**
   ```yaml
   # Lower threshold
   tm_prefs:
     semantic_threshold: 0.70
   ```

---

### TM Database Corruption

**Symptoms:**
- Database errors
- Checksum failures
- Cannot open database

**Solution:**
```bash
# 1. Stop services
docker-compose down

# 2. Backup corrupted database
mv data/tm/db.lmdb data/tm/db.lmdb.corrupt

# 3. Restore from backup
tar -xzf backups/latest/tm_data.tar.gz -C data/

# 4. Or rebuild from export
docker-compose up -d orchestrator
docker-compose exec orchestrator python -c "
from pathlib import Path
from src.tm.translation_memory import rebuild_from_export

rebuild_from_export(
    export_file=Path('/backups/tm_export.ndjson'),
    output_dir=Path('/data/tm')
)
"

# 5. Restart
docker-compose down
docker-compose up -d
```

---

## Configuration Issues

### YAML Parsing Errors

**Symptoms:**
- "Failed to load config"
- YAML syntax errors

**Solutions:**

```bash
# Validate YAML syntax
python -c "
import yaml
with open('config/global.yaml') as f:
    yaml.safe_load(f)
print('✓ Valid YAML')
"

# Common YAML mistakes:
# 1. Wrong indentation
#    key:
#      subkey: value  # Correct (2 spaces)
#    key:
#        subkey: value  # Wrong (4 spaces)

# 2. Missing quotes
#    title: Hello: World  # Wrong (: needs quotes)
#    title: "Hello: World"  # Correct

# 3. List syntax
#    tags:
#      - tag1  # Correct
#      - tag2
#    tags: [tag1, tag2]  # Also correct
```

---

### Environment Variables Not Applied

**Symptoms:**
- Settings not taking effect
- Using defaults despite env vars

**Diagnosis:**
```bash
# Check environment variable is set
docker-compose exec orchestrator env | grep TM_SEMANTIC_THRESHOLD

# Check it's loaded
docker-compose exec orchestrator python -c "
import os
print(f\"Env var: {os.getenv('TM_SEMANTIC_THRESHOLD')}\")

from pathlib import Path
from src.utils.config_loader import ConfigService

config = ConfigService(Path('/app/config'))
print(f\"Loaded: {config.global_config.tm_defaults.semantic_threshold}\")
"
```

**Solutions:**

1. **Use .env file:**
   ```bash
   # Create .env.production
   TM_SEMANTIC_THRESHOLD=0.85

   # Reference in docker-compose.yml
   env_file:
     - .env.production
   ```

2. **Restart services:**
   ```bash
   docker-compose down
   docker-compose up -d
   ```

---

## Debugging Techniques

### Enable Debug Logging

```bash
# Set debug level
LOG_LEVEL=DEBUG
FLOW_ARTIFACT_DETAIL=full

# Restart services
docker-compose restart

# View detailed logs
docker-compose logs -f orchestrator | jq .
```

---

### Use Python Debugger

```python
# Add breakpoint in code
import pdb; pdb.set_trace()

# Or use ipdb for better experience
import ipdb; ipdb.set_trace()

# Run in interactive mode
docker-compose exec orchestrator python -i -c "
from pathlib import Path
from src.translation_engine.engine import TranslationEngine
# ... setup
# Now in interactive Python shell
"
```

---

### Profile Performance

```python
import cProfile
import pstats

profiler = cProfile.Profile()
profiler.enable()

# Run translation
result = engine.translate_file(...)

profiler.disable()
stats = pstats.Stats(profiler)
stats.sort_stats('cumulative')
stats.print_stats(20)  # Top 20 functions
```

---

### Inspect Flow Artifacts

```bash
# Enable full flow artifacts
FLOW_ARTIFACT_DETAIL=full

# Run translation
# ...

# Review artifacts
ls -lh data/artifacts/jobs/
cat data/artifacts/jobs/<job-id>.ndjson | jq .
```

---

### Test Individual Components

```bash
# Test parser
docker-compose exec worker-cpu-1 python -c "
from pathlib import Path
from src.translation_engine.parser.hugo_parser import HugoParser

parser = HugoParser()
result = parser.parse_file(Path('/data/content/test.md'))
print(f'Frontmatter: {result.frontmatter}')
print(f'Body AST: {result.body_ast}')
"

# Test extractor
# Test TM
# Test model
# etc.
```

---

## Getting Help

### Gather Diagnostic Information

Before seeking help, gather:

```bash
#!/bin/bash
# gather_diagnostics.sh

echo "=== System Information ===" > diagnostics.txt
uname -a >> diagnostics.txt
docker --version >> diagnostics.txt
docker-compose --version >> diagnostics.txt

echo -e "\n=== Service Status ===" >> diagnostics.txt
docker-compose ps >> diagnostics.txt

echo -e "\n=== Recent Logs ===" >> diagnostics.txt
docker-compose logs --tail=100 >> diagnostics.txt

echo -e "\n=== Configuration ===" >> diagnostics.txt
docker-compose config >> diagnostics.txt

echo -e "\n=== Resource Usage ===" >> diagnostics.txt
docker stats --no-stream >> diagnostics.txt
df -h >> diagnostics.txt
free -h >> diagnostics.txt

echo "Diagnostics saved to diagnostics.txt"
```

### Check Documentation

1. [User Guide](USER_GUIDE.md) - Usage and features
2. [Configuration Reference](CONFIGURATION.md) - Settings
3. [Deployment Guide](DEPLOYMENT.md) - Installation
4. [Operations Manual](OPERATIONS.md) - Maintenance

### Run Test Suite

```bash
# Run all tests
docker-compose exec orchestrator pytest tests/ -v

# Run specific test category
docker-compose exec orchestrator pytest tests/unit/ -v
docker-compose exec orchestrator pytest tests/integration/ -v

# Run with verbose output
docker-compose exec orchestrator pytest tests/ -vv --tb=long
```

### Contact Support

Include in your support request:

1. **System information:**
   - OS and version
   - Docker version
   - Hardware specs (CPU, RAM, GPU)

2. **Problem description:**
   - What were you trying to do?
   - What happened instead?
   - When did it start?

3. **Logs and diagnostics:**
   - Output of `gather_diagnostics.sh`
   - Relevant error messages
   - Configuration files (remove secrets!)

4. **Steps to reproduce:**
   - Minimal example that triggers the issue
   - Sample files if applicable

---

## Quick Reference

### Common Commands

```bash
# Restart all services
docker-compose restart

# View logs
docker-compose logs -f orchestrator

# Check status
docker-compose ps

# Run health check
./scripts/health_check.sh

# Backup
./scripts/backup.sh

# Restore
./scripts/restore.sh /backups/YYYYMMDD_HHMMSS

# Clean up
docker-compose down
docker system prune -a

# Rebuild
docker-compose build
docker-compose up -d
```

### Emergency Procedures

```bash
# Full reset (WARNING: Destroys data)
docker-compose down -v
rm -rf data/*
docker-compose up -d

# Restore from backup
./scripts/restore.sh /backups/last_known_good

# Restart with clean slate (keeps data)
docker-compose down
docker-compose up -d --force-recreate
```

---

**Documentation Version:** 1.0.0
**Last Updated:** 2025-11-21
