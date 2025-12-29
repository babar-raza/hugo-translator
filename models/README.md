# Translation Models

**Directory:** `models/`
**Purpose:** Store all translation model files for the Hugo Translation System
**Version:** 1.0

## Directory Structure

```
models/
├── huggingface/           # HuggingFace Transformers models (PyTorch)
│   ├── m2m100_418m/       # Facebook M2M100 (418M parameters)
│   ├── m2m100_1.2b/       # Facebook M2M100 (1.2B parameters)
│   ├── nllb_200_600m/     # NLLB-200 (600M parameters)
│   ├── nllb_200_1.3b/     # NLLB-200 (1.3B parameters)
│   └── opus-mt/           # Helsinki-NLP Opus-MT models
│       ├── opus-mt-en-fr/
│       ├── opus-mt-en-de/
│       └── opus-mt-en-es/
├── ctranslate2/           # CTranslate2 optimized models
│   ├── m2m100_418m/       # FP32 version
│   ├── m2m100_418m_int8/  # INT8 quantized (smaller, faster)
│   └── nllb_200_600m_int8/
├── cache/                 # Runtime cache (temporary, auto-managed)
├── inventory.json         # Model inventory database (auto-generated)
└── README.md              # This file
```

## Disk Space Requirements

| Profile | Space Required | Models Included |
|---------|---------------|-----------------|
| **Minimal** | 2 GB | m2m100_418m_ct2_int8 (1 model) |
| **Recommended** | 10 GB | All CTranslate2 INT8 models (4 models) |
| **Full CPU** | 30 GB | All CPU-optimized models (10 models) |
| **Full GPU** | 50 GB | All models including large GPU variants |

## Quick Start

### 1. Download Models

```bash
# Download all essential models
python scripts/download_models.py --essential

# Download specific model
python scripts/download_models.py --model m2m100_418m

# Download all models (requires 50GB disk space)
python scripts/download_models.py --all
```

### 2. Verify Models

```bash
# Verify all downloaded models
python scripts/verify_models.py

# Verify specific model
python scripts/verify_models.py --model m2m100_418m
```

### 3. Check Disk Usage

```bash
# View model inventory and disk usage
python scripts/list_models.py --show-size
```

## Model Organization Principles

### 1. Backend Separation
Models are grouped by backend:
- **huggingface/**: PyTorch models loaded via HuggingFace Transformers
- **ctranslate2/**: Optimized models converted to CTranslate2 format

### 2. Flat Model Directories
Each model gets its own directory (no nesting):
- ✅ `huggingface/m2m100_418m/`
- ❌ `huggingface/facebook/m2m100/418m/`

### 3. Metadata Files
Every model directory contains `.metadata.json`:

```json
{
  "model_id": "m2m100_418m",
  "backend": "huggingface",
  "hf_model_id": "facebook/m2m100_418M",
  "downloaded_at": "2025-12-27T10:00:00Z",
  "size_mb": 1600,
  "sha256": {
    "pytorch_model.bin": "abc123..."
  },
  "license": "MIT",
  "last_verified": "2025-12-27T10:05:00Z",
  "verification_status": "passed"
}
```

### 4. Git Exclusions
Model binaries (*.bin, *.safetensors) are excluded from git:
- Only directory structure and metadata tracked
- Actual model files downloaded on-demand

## Adding a Model

### Manual Method
1. Create directory: `mkdir -p models/huggingface/<model_id>`
2. Download files from HuggingFace Hub
3. Create `.metadata.json` manually
4. Update `models/inventory.json`

### Automated Method (Recommended)
```bash
# Add to config/model_registry.yaml first
# Then download automatically
python scripts/download_models.py --model <model_id>
```

## Removing a Model

### Safe Removal
```bash
# Remove model and update inventory
python scripts/remove_model.py <model_id>

# Model moved to models/.trash/ (recoverable)
```

### Force Removal
```bash
# Permanently delete (cannot undo)
python scripts/remove_model.py <model_id> --force
```

## Cache Management

The `models/cache/` directory stores:
- Temporary files during model download
- Tokenizer caches
- CTranslate2 compilation outputs

**Safe to delete:** Yes, will be recreated as needed

```bash
# Clear cache
rm -rf models/cache/*
```

## Model Inventory

The `models/inventory.json` file tracks all downloaded models:

```json
{
  "version": "1.0",
  "last_updated": "2025-12-28T10:00:00Z",
  "models": [
    {
      "model_id": "m2m100_418m",
      "path": "models/huggingface/m2m100_418m",
      "backend": "huggingface",
      "size_mb": 1600,
      "languages_supported": "all"
    }
  ],
  "total_size_mb": 1600,
  "total_models": 1
}
```

**Auto-updated** by download and removal scripts.

## Troubleshooting

### Model Not Found
```bash
# Check if model exists in inventory
python scripts/list_models.py

# Re-download if missing
python scripts/download_models.py --model <model_id> --force
```

### Corrupted Model
```bash
# Verify integrity
python scripts/verify_models.py --model <model_id>

# Re-download if verification fails
python scripts/download_models.py --model <model_id> --force
```

### Disk Space Full
```bash
# Check disk usage
df -h models/

# Remove unused models
python scripts/cleanup_models.py --unused

# Clear cache
rm -rf models/cache/*
```

### Download Interrupted
```bash
# Downloads support resume - just re-run
python scripts/download_models.py --model <model_id>
# Will continue from where it stopped
```

## Model Backends Explained

### HuggingFace Transformers
- **Format:** PyTorch (*.bin or *.safetensors)
- **Pros:** Full precision, all features, widely compatible
- **Cons:** Slower inference, more memory
- **Use Case:** GPU inference, quality-critical tasks

### CTranslate2
- **Format:** Custom binary (model.bin)
- **Pros:** 2-4x faster, 50% less memory, supports INT8 quantization
- **Cons:** Limited to translation tasks
- **Use Case:** CPU inference, production deployments

## Security

### Checksum Verification
All downloads are verified via SHA256 checksums from HuggingFace Hub.

### Source Restrictions
- **Allowed:** HuggingFace Hub only (hub.huggingface.co)
- **Forbidden:** Arbitrary URLs, local file paths

### Malware Scanning
Models downloaded from trusted sources only. No executable code in model files.

## Performance Optimization

### Model Selection by Use Case

| Use Case | Recommended Model | Rationale |
|----------|-------------------|-----------|
| **CPU Production** | m2m100_418m_ct2_int8 | Best speed/quality on CPU |
| **GPU Production** | nllb_200_1.3b | Best quality with GPU |
| **Low Memory** | m2m100_418m_ct2_int8 | Only 250MB RAM |
| **High Quality** | nllb_200_1.3b | State-of-the-art scores |
| **Fast Prototyping** | m2m100_418m | Good balance |

### Disk I/O Optimization
- Use SSD for `models/` directory (NVMe preferred)
- Separate `models/cache/` to faster disk if available
- Enable filesystem compression (NTFS/Btrfs) to save 20-30% space

## Related Documentation

- [Model Registry](../config/model_registry.yaml) - Model definitions and metadata
- [Model Organization Architecture](../docs/architecture/MODEL_ORGANIZATION.md) - Design details
- [Benchmarking Guide](../docs/operations/BENCHMARKING.md) - Performance data

## Support

For issues with model downloads or organization:
1. Check `logs/model_download.log` for errors
2. Verify internet connectivity to huggingface.co
3. Ensure sufficient disk space: `df -h models/`
4. Consult troubleshooting section above

---

**Last Updated:** 2025-12-28
**Maintained By:** Hugo Translation System Team
