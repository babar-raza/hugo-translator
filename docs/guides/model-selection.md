# Model Selection and Management Guide

This guide explains how the Hugo Translation System selects, downloads, and manages translation models.

## Table of Contents

- [Overview](#overview)
- [Automatic Model Downloads](#automatic-model-downloads)
- [Model Selection Logic](#model-selection-logic)
- [Available Models](#available-models)
- [Model Registry](#model-registry)
- [Recommendation Engine](#recommendation-engine)
- [Configuration](#configuration)
- [Model Management](#model-management)
- [Troubleshooting](#troubleshooting)

## Overview

The Hugo Translation System uses state-of-the-art neural machine translation models from HuggingFace. The system handles all model management automatically:

- ✅ **Automatic downloads** - No manual intervention required
- ✅ **Smart selection** - Hardware-aware model recommendations
- ✅ **Flexible configuration** - Override at CLI, site profile, or global level
- ✅ **Efficient caching** - Models downloaded once, reused forever

## Automatic Model Downloads

### How It Works

**Models are downloaded automatically on first use** - you never need to manually download anything.

**Flow:**

1. You run a translation command
2. System determines which model to use (see [Model Selection Logic](#model-selection-logic))
3. System checks if model is cached locally
4. If not cached: Downloads from HuggingFace Hub automatically
5. Loads model into memory and begins translation

**First Run:**
```bash
translate-hugo --site mysite --source-lang en --target-lang fr
# Output: Downloading model facebook/m2m100_418M... (1.6GB)
# Output: Model cached at ~/.cache/huggingface/hub/models--facebook--m2m100_418M
# Output: Translating...
```

**Subsequent Runs:**
```bash
translate-hugo --site mysite --source-lang en --target-lang fr
# Output: Loading cached model facebook/m2m100_418M
# Output: Translating...
```

### Download Location

Models are stored in the standard HuggingFace cache directory:

- **Linux/macOS**: `~/.cache/huggingface/hub/`
- **Windows**: `%USERPROFILE%\.cache\huggingface\hub\`

### Download Size

Typical model sizes:

| Model | Download Size | Disk Size (cached) |
|-------|---------------|-------------------|
| `m2m100_418m` | ~1.6GB | ~2GB |
| `m2m100_1.2b` | ~4.8GB | ~5.5GB |
| `nllb_600m` | ~2.4GB | ~3GB |
| `nllb_1.3b` | ~5.2GB | ~6GB |
| `opus_mt_*` | ~300MB | ~400MB |

### Network Requirements

**Bandwidth:**
- First download: Requires internet connection with sufficient bandwidth
- Subsequent runs: No internet required (uses cached model)

**Timeout Configuration:**
```bash
# Increase download timeout for slow connections (default: 300s)
export HF_HUB_DOWNLOAD_TIMEOUT=600  # 10 minutes
```

**Offline Mode:**
```bash
# Use only cached models, never download
export HF_HUB_OFFLINE=1
```

### Pre-downloading Models (Optional)

For production deployments or air-gapped systems, you can pre-download models:

```bash
# Pre-download default model
python -c "
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

model_id = 'facebook/m2m100_418M'
print(f'Downloading {model_id}...')

tokenizer = AutoTokenizer.from_pretrained(model_id)
model = AutoModelForSeq2SeqLM.from_pretrained(model_id)

print(f'Model cached successfully at ~/.cache/huggingface/')
"

# Pre-download specific model
python -c "
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

model_id = 'facebook/nllb-200-1.3B'
tokenizer = AutoTokenizer.from_pretrained(model_id)
model = AutoModelForSeq2SeqLM.from_pretrained(model_id)
print('Done')
"
```

## Model Selection Logic

The system uses a **priority-based selection** mechanism:

### Priority Order

1. **CLI Override** (highest priority)
2. **Site Profile Default**
3. **Fallback Default**

### 1. CLI Override

Use the `--model` flag to override for a specific run:

```bash
# Use higher quality model for this translation
translate-hugo --site docs --model nllb_1.3b --source-lang en --target-lang fr

# Test with faster model
translate-hugo --site blog --model opus_mt_en_fr --source-lang en --target-lang fr
```

**Use cases:**
- Testing different models
- One-off high-quality translations
- Performance benchmarking
- Emergency fallback

### 2. Site Profile Default

Configure default model per site in `config/site_profiles/mysite.yaml`:

```yaml
site_profile:
  name: "mysite"
  default_model: "nllb_1.3b"  # Higher quality for this site
```

**Use cases:**
- Different quality requirements per site
- Site-specific language pairs (use language-pair specific models)
- Consistent model selection for a site

### 3. Fallback Default

If no override or site profile default is set, the system uses:

**Default Model:** `m2m100_418m` (Facebook M2M100 418M parameters)

**Why this default:**
- ✅ Supports 100 languages
- ✅ Balanced speed/quality
- ✅ Reasonable resource requirements (works on 8GB RAM)
- ✅ Well-tested and reliable

**Hardcoded in:** [src/translation_engine/engine.py:496](../../src/translation_engine/engine.py#L496)

```python
def _get_model_id(self, site_profile):
    # CLI override takes precedence
    if self.model_id_override:
        return self.model_id_override
    # Fall back to site profile or hardcoded default
    return getattr(site_profile, 'default_model', None) or "m2m100_418m"
```

## Available Models

### Model Registry

All available models are defined in [config/model_registry.yaml](../../config/model_registry.yaml).

Each model entry includes:

```yaml
models:
  - model_id: "m2m100_418m"
    backend: "huggingface"
    hf_model_id: "facebook/m2m100_418M"
    model_size_mb: 1600
    min_ram_gb: 4
    optimal_device: "cpu"  # or "cuda"
    supported_pairs: "all"  # or list of language pairs
    parameters: 418000000
    license: "MIT"
```

### Model Catalog

#### M2M100 Series (Facebook)

**m2m100_418m** (Default)
- **Parameters:** 418M
- **Size:** ~1.6GB
- **Languages:** 100 (multilingual many-to-many)
- **Device:** CPU/CUDA
- **RAM:** 4GB minimum
- **Best for:** General-purpose translation, balanced speed/quality
- **HuggingFace:** `facebook/m2m100_418M`

**m2m100_1.2b**
- **Parameters:** 1.2B
- **Size:** ~4.8GB
- **Languages:** 100 (multilingual many-to-many)
- **Device:** CUDA recommended (CPU slow)
- **RAM:** 8GB minimum
- **Best for:** Higher quality translations, GPU systems
- **HuggingFace:** `facebook/m2m100_1.2B`

#### NLLB Series (Meta)

**nllb_600m**
- **Parameters:** 600M
- **Size:** ~2.4GB
- **Languages:** 200 (low-resource language support)
- **Device:** CPU/CUDA
- **RAM:** 6GB minimum
- **Best for:** More language pairs, low-resource languages
- **HuggingFace:** `facebook/nllb-200-distilled-600M`

**nllb_1.3b**
- **Parameters:** 1.3B
- **Size:** ~5.2GB
- **Languages:** 200 (low-resource language support)
- **Device:** CUDA recommended
- **RAM:** 10GB minimum
- **Best for:** Best quality, comprehensive language coverage
- **HuggingFace:** `facebook/nllb-200-1.3B`

#### Opus-MT Series (Language-Pair Specific)

**opus_mt_en_fr** (Example)
- **Parameters:** ~80M
- **Size:** ~300MB
- **Languages:** EN→FR only
- **Device:** CPU/CUDA
- **RAM:** 2GB minimum
- **Best for:** Fastest translation, single language pair
- **HuggingFace:** `Helsinki-NLP/opus-mt-en-fr`

**Other Opus-MT Models:**
- `opus_mt_en_de` (English → German)
- `opus_mt_en_es` (English → Spanish)
- `opus_mt_en_it` (English → Italian)
- `opus_mt_en_zh` (English → Chinese)
- Many more available for specific pairs

#### CTranslate2 Optimized Models

**m2m100_418m_ct2**
- **Backend:** CTranslate2 (optimized runtime)
- **Size:** ~800MB (compressed)
- **Speed:** 2-4x faster than HuggingFace
- **RAM:** 3GB minimum
- **Best for:** Production deployments, speed-critical applications

**nllb_600m_ct2**
- **Backend:** CTranslate2
- **Size:** ~1.2GB
- **Speed:** 2-4x faster than HuggingFace
- **Best for:** Production with more language pairs

### Model Comparison Table

| Model | Params | Size | Speed | Quality | RAM | Languages | Use Case |
|-------|--------|------|-------|---------|-----|-----------|----------|
| `opus_mt_*` | 80M | 300MB | ⚡⚡⚡⚡⚡ | ⭐⭐⭐ | 2GB | Single pair | Fastest, dedicated pair |
| `m2m100_418m` | 418M | 1.6GB | ⚡⚡⚡⚡ | ⭐⭐⭐⭐ | 4GB | 100 | Default, balanced |
| `nllb_600m` | 600M | 2.4GB | ⚡⚡⚡ | ⭐⭐⭐⭐ | 6GB | 200 | More languages |
| `m2m100_1.2b` | 1.2B | 4.8GB | ⚡⚡ | ⭐⭐⭐⭐⭐ | 8GB | 100 | High quality |
| `nllb_1.3b` | 1.3B | 5.2GB | ⚡⚡ | ⭐⭐⭐⭐⭐ | 10GB | 200 | Best quality |

## Recommendation Engine

The system includes a **hardware-aware recommendation engine** that suggests optimal models based on your system.

### How It Works

**Location:** [src/model_runtime/registry.py:183-282](../../src/model_runtime/registry.py#L183-L282)

**Algorithm:**

1. **Filter by language pair:** Only consider models that support the source/target languages
2. **Filter by hardware:** Exclude models that exceed available RAM or require unavailable device (CUDA)
3. **Score candidates:** Rank remaining models using a scoring function
4. **Return best:** Select model with highest score

**Scoring Function:**

```python
score = 0

# Device match bonus (+10 points)
if model.optimal_device == hardware.device:
    score += 10

# Quality preference (parameter count)
if prefer_quality:
    score += (model.parameters / 1e9) * 5  # More params = better quality
else:
    score -= (model.parameters / 1e9) * 2  # Fewer params = faster

# Backend preference
if model.backend == "ctranslate2":
    score += 5  # CTranslate2 is faster
elif model.backend == "huggingface":
    score += 3

# Size penalty (smaller = better for speed)
score -= (model.model_size_mb / 1000)  # -1 per GB

return score
```

### Using the Recommendation Engine

**Python API:**

```python
from src.model_runtime.registry import ModelRegistry
from src.benchmarking.system_info import SystemInfoCollector

# Initialize
registry = ModelRegistry()
system_info = SystemInfoCollector().collect()

# Get recommendation
recommended_model = registry.recommend_model(
    src_lang="en",
    tgt_lang="fr",
    hardware={
        "device": "cuda",  # or "cpu"
        "ram_gb": 16,
        "gpu_vram_gb": 8  # optional, for CUDA
    },
    prefer_quality=True  # False for speed
)

print(f"Recommended model: {recommended_model}")
```

**Example Recommendations:**

**Scenario 1: GPU System, Quality Priority**
```python
hardware = {"device": "cuda", "ram_gb": 16, "gpu_vram_gb": 8}
prefer_quality = True
# → Recommendation: nllb_1.3b
```

**Scenario 2: CPU System, Speed Priority**
```python
hardware = {"device": "cpu", "ram_gb": 8}
prefer_quality = False
# → Recommendation: m2m100_418m
```

**Scenario 3: Low-Resource System**
```python
hardware = {"device": "cpu", "ram_gb": 4}
prefer_quality = False
# → Recommendation: opus_mt_en_fr (if supported pair)
```

**Scenario 4: Single Language Pair, Maximum Speed**
```python
hardware = {"device": "cpu", "ram_gb": 8}
src_lang = "en"
tgt_lang = "fr"
prefer_quality = False
# → Recommendation: opus_mt_en_fr
```

## Configuration

### Global Configuration

Edit [config/global.yaml](../../config/global.yaml):

```yaml
translation:
  default_model: "m2m100_418m"  # Global default
```

### Site Profile Configuration

Edit `config/site_profiles/mysite.yaml`:

```yaml
site_profile:
  name: "mysite"
  default_model: "nllb_1.3b"  # Override for this site
```

### CLI Configuration

Override at runtime:

```bash
# Use specific model
translate-hugo --site mysite --model nllb_1.3b

# Use language-pair specific model
translate-hugo --site blog --model opus_mt_en_fr --source-lang en --target-lang fr
```

### Environment Variables

Control download behavior:

```bash
# Download timeout (seconds)
export HF_HUB_DOWNLOAD_TIMEOUT=600

# Offline mode (use cached models only)
export HF_HUB_OFFLINE=1

# Custom cache directory
export HF_HOME=/mnt/data/huggingface_cache
```

## Model Management

### Listing Cached Models

```bash
# List all cached HuggingFace models
ls -lh ~/.cache/huggingface/hub/
```

**Output:**
```
drwxr-xr-x  models--facebook--m2m100_418M
drwxr-xr-x  models--facebook--nllb-200-1.3B
drwxr-xr-x  models--Helsinki-NLP--opus-mt-en-fr
```

### Checking Model Size

```bash
# Check disk usage of cached models
du -sh ~/.cache/huggingface/hub/*
```

**Output:**
```
2.0G    models--facebook--m2m100_418M
6.1G    models--facebook--nllb-200-1.3B
412M    models--Helsinki-NLP--opus-mt-en-fr
```

### Removing Cached Models

```bash
# Remove specific model
rm -rf ~/.cache/huggingface/hub/models--facebook--m2m100_418M

# Remove all cached models (WARNING: Will re-download on next use)
rm -rf ~/.cache/huggingface/hub/*
```

### Clearing Model Cache

**Python API:**

```python
from pathlib import Path
import shutil

cache_dir = Path.home() / ".cache" / "huggingface" / "hub"

# Remove specific model
model_dir = cache_dir / "models--facebook--m2m100_418M"
if model_dir.exists():
    shutil.rmtree(model_dir)
    print(f"Removed {model_dir}")

# List all cached models
for model_dir in cache_dir.glob("models--*"):
    size = sum(f.stat().st_size for f in model_dir.rglob('*'))
    print(f"{model_dir.name}: {size / 1e9:.2f} GB")
```

### Verifying Model Integrity

```python
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

model_id = "facebook/m2m100_418M"

try:
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    model = AutoModelForSeq2SeqLM.from_pretrained(model_id)
    print(f"✓ Model {model_id} loaded successfully")
except Exception as e:
    print(f"✗ Failed to load {model_id}: {e}")
```

### Monitoring Model Usage

The system logs model loading and usage:

```bash
# View model loading logs
tail -f logs/translation.log | grep "Loading model"
```

**Example Output:**
```
2024-12-24 10:30:15 INFO Loading model m2m100_418m from cache
2024-12-24 10:30:18 INFO Model loaded successfully (2.1s)
```

## Troubleshooting

### Model Download Fails

**Symptom:**
```
ConnectionError: Could not connect to HuggingFace Hub
```

**Solutions:**

1. **Check internet connection:**
   ```bash
   curl -I https://huggingface.co
   ```

2. **Check firewall/proxy:**
   ```bash
   export HTTP_PROXY=http://proxy.company.com:8080
   export HTTPS_PROXY=http://proxy.company.com:8080
   ```

3. **Increase timeout:**
   ```bash
   export HF_HUB_DOWNLOAD_TIMEOUT=900  # 15 minutes
   ```

4. **Pre-download manually:**
   ```python
   from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
   tokenizer = AutoTokenizer.from_pretrained('facebook/m2m100_418M')
   model = AutoModelForSeq2SeqLM.from_pretrained('facebook/m2m100_418M')
   ```

### Model Download Hangs

**Symptom:** Download starts but freezes at 50%.

**Solutions:**

1. **Kill and restart:**
   ```bash
   # Kill the process
   pkill -f translate-hugo

   # Clear partial download
   rm -rf ~/.cache/huggingface/hub/models--facebook--m2m100_418M

   # Retry
   translate-hugo --site mysite --source-lang en --target-lang fr
   ```

2. **Use different network:**
   - Try different WiFi network
   - Use mobile hotspot
   - Try VPN if corporate firewall is blocking

### Out of Memory (OOM)

**Symptom:**
```
RuntimeError: CUDA out of memory. Tried to allocate 2.5 GiB
```

**Solutions:**

1. **Use smaller model:**
   ```bash
   translate-hugo --site mysite --model m2m100_418m  # Instead of 1.2b
   ```

2. **Use CPU mode:**
   ```bash
   translate-hugo --site mysite --device cpu
   ```

3. **Reduce batch size:**
   ```bash
   translate-hugo --site mysite --batch-size 4  # Default is 8
   ```

4. **Close GPU-heavy processes:**
   ```bash
   nvidia-smi  # Check GPU usage
   # Close games, browsers, ML tools
   ```

### Model Not Found in Registry

**Symptom:**
```
ValueError: Model 'my_custom_model' not found in registry
```

**Solution:** Add model to [config/model_registry.yaml](../../config/model_registry.yaml):

```yaml
models:
  - model_id: "my_custom_model"
    backend: "huggingface"
    hf_model_id: "myorg/my-model-name"
    model_size_mb: 2000
    min_ram_gb: 6
    optimal_device: "cuda"
    supported_pairs: "all"
    parameters: 500000000
    license: "MIT"
```

### Corrupted Model Cache

**Symptom:** Model loads but produces gibberish translations.

**Solution:** Clear cache and re-download:

```bash
# Remove corrupted model
rm -rf ~/.cache/huggingface/hub/models--facebook--m2m100_418M

# Re-download will happen automatically on next run
translate-hugo --site mysite --source-lang en --target-lang fr
```

### Disk Space Issues

**Symptom:**
```
OSError: [Errno 28] No space left on device
```

**Solutions:**

1. **Check available space:**
   ```bash
   df -h ~/.cache/huggingface
   ```

2. **Remove unused models:**
   ```bash
   # List models by size
   du -sh ~/.cache/huggingface/hub/models--* | sort -h

   # Remove large unused models
   rm -rf ~/.cache/huggingface/hub/models--facebook--nllb-200-3.3B
   ```

3. **Move cache to larger disk:**
   ```bash
   export HF_HOME=/mnt/large_disk/huggingface_cache
   ```

4. **Use smaller model:**
   ```yaml
   # config/site_profiles/mysite.yaml
   default_model: "opus_mt_en_fr"  # Only 300MB instead of 5GB
   ```

## Best Practices

### Production Deployments

1. **Pre-download models** in Docker build or CI/CD pipeline
2. **Pin specific model versions** in config for reproducibility
3. **Monitor disk usage** - set up alerts for cache directory
4. **Use CTranslate2 models** for 2-4x speed improvement
5. **Test model changes** in staging before production

### Development

1. **Use smaller models** for faster iteration (opus_mt_* or m2m100_418m)
2. **Override via CLI** to test different models
3. **Cache models locally** to avoid re-downloads
4. **Document model choices** in site profile comments

### Cost Optimization

1. **Use Translation Memory** - 70-95% cache hit rate reduces model usage
2. **Batch translations** for better GPU utilization
3. **Use smaller models** where quality requirements allow
4. **Monitor model usage** to identify opportunities for optimization

### Quality Optimization

1. **Use larger models** (nllb_1.3b) for critical content
2. **Test multiple models** on sample content
3. **Use language-pair specific models** when available (often better quality)
4. **Benchmark quality** using BLEU scores (see [Benchmarking Guide](../features/benchmarking.md))

## Related Documentation

- [Setup Guide](../user-guide/setup.md) - Initial setup and GPU detection
- [Benchmarking Guide](../features/benchmarking.md) - Measure model performance
- [Configuration Reference](../reference/config.md) - All configuration options
- [Model Registry](../../config/model_registry.yaml) - Full model catalog
- [Translation Memory Guide](tm-getting-started.md) - Reduce model usage with caching

---

**Last Updated:** 2024-12-24
**Applies To:** Hugo Translation System v0.1.0+
