# Model Storage Strategy

This document explains how translation models are stored, cached, and managed in the hugo-translator system.

## Storage Locations

### HuggingFace Cache (`~/.cache/huggingface/hub/`)

All HuggingFace models are automatically downloaded and cached in the standard HuggingFace cache directory:

**Location (cross-platform)**:
- **Linux/macOS**: `~/.cache/huggingface/hub/`
- **Windows**: `C:\Users\<username>\.cache\huggingface\hub\`

**Structure**:
```
~/.cache/huggingface/hub/
├── models--facebook--m2m100_418M/
│   ├── snapshots/
│   │   └── <commit-hash>/
│   │       ├── config.json
│   │       ├── pytorch_model.bin
│   │       ├── tokenizer_config.json
│   │       └── ...
│   └── refs/
│       └── main
├── models--Helsinki-NLP--opus-mt-en-es/
│   └── ...
└── ...
```

**Key Characteristics**:
- Models are identified by `<org>--<model-name>` format
- Each model has snapshots identified by git commit hashes
- Shared between all applications using HuggingFace Transformers
- Automatically managed by `huggingface_hub` library
- Uses file locks to prevent corruption during concurrent access

### CTranslate2 Models (`./models/ct2/`)

Optimized CTranslate2 models are stored locally in the project directory:

**Location**: `<project-root>/models/ct2/`

**Structure**:
```
models/ct2/
├── m2m100_418m/
│   ├── model.bin
│   ├── shared_vocabulary.json
│   └── config.json
├── m2m100_418m_int8/
│   ├── model.bin (INT8 quantized)
│   ├── shared_vocabulary.json
│   └── config.json
└── nllb_200_600m_int8/
    └── ...
```

**Key Characteristics**:
- Models must be manually converted from HuggingFace format
- Significantly smaller than HuggingFace models (2-4x compression)
- Faster inference (2-3x speedup on CPU)
- INT8 quantization provides additional 50% size reduction
- Not shared between projects (each project has own copy)

## Storage Requirements

### HuggingFace Models

| Model | Parameters | Disk Size (FP32) | Minimum RAM | Recommended Device |
|-------|------------|------------------|-------------|-------------------|
| m2m100_418m | 418M | ~1.6 GB | 4 GB | CPU/CUDA |
| nllb_200_600m | 600M | ~2.4 GB | 6 GB | CUDA |
| m2m100_1.2b | 1.2B | ~4.8 GB | 8 GB | CUDA |
| nllb_200_1.3b | 1.3B | ~5.2 GB | 10 GB | CUDA |
| small100 | 300M | ~1.2 GB | 3 GB | CPU |
| opus_en_es | 77M | ~300 MB | 1 GB | CPU |
| opus_en_de | 77M | ~300 MB | 1 GB | CPU |
| opus_en_fr | 77M | ~300 MB | 1 GB | CPU |
| marian_en_romance | 74M | ~300 MB | 1 GB | CPU |
| t5_small | 60M | ~240 MB | 1 GB | CPU |
| t5_base | 220M | ~890 MB | 2 GB | CPU |
| t5_3b | 3B | ~11 GB | 16 GB | CUDA |

**Storage Formula**:
- FP32 models: `parameters * 4 bytes / 1024^3 = GB`
- Example: 418M params * 4 bytes = 1.67 GB

### CTranslate2 Models

| Model | Original Size | CT2 Size | CT2 INT8 Size | Compression Ratio |
|-------|--------------|----------|---------------|-------------------|
| m2m100_418m | 1.6 GB | ~800 MB | ~250 MB | 50% / 16% |
| nllb_200_600m | 2.4 GB | ~1.2 GB | ~350 MB | 50% / 15% |

**Compression Benefits**:
- CT2 FP32: ~50% of original size (optimized model format)
- CT2 INT8: ~15% of original size (quantization + optimization)

## Cache Management

### Automatic Cache Management

HuggingFace cache is managed automatically:
- Old model versions are **not** automatically deleted
- Cache grows over time as models are downloaded
- Multiple versions of same model may coexist

### Manual Cache Inspection

**List cached models**:
```bash
# Linux/macOS
ls -lh ~/.cache/huggingface/hub/

# Windows PowerShell
Get-ChildItem ~\.cache\huggingface\hub\ | Format-Table Name,Length
```

**Check cache size**:
```bash
# Linux/macOS
du -sh ~/.cache/huggingface/hub/

# Windows PowerShell
(Get-ChildItem ~\.cache\huggingface\hub\ -Recurse | Measure-Object -Property Length -Sum).Sum / 1GB
```

### Cache Cleanup

**Manual cleanup (use with caution)**:
```bash
# Remove entire HuggingFace cache (all models)
rm -rf ~/.cache/huggingface/

# Remove specific model
rm -rf ~/.cache/huggingface/hub/models--facebook--m2m100_418M

# Remove old snapshots (keep only latest)
# Navigate to model directory and delete old snapshot folders
```

**Recommended cleanup strategy**:
1. Identify unused models using download timestamps
2. Remove models not in `model_registry.yaml`
3. Keep only latest snapshot for each model
4. Run cleanup when disk space is low

### Programmatic Cache Management

**Using HuggingFace Hub CLI**:
```bash
# Install HuggingFace CLI
pip install huggingface_hub[cli]

# Scan cache
huggingface-cli scan-cache

# Delete specific models
huggingface-cli delete-cache --repo-id facebook/m2m100_418M
```

## Model Loading Process

### HuggingFace Models

1. **Check local cache**: `~/.cache/huggingface/hub/models--<org>--<model>/`
2. **If not found**: Download from HuggingFace Hub
3. **Download process**:
   - Downloads model files (pytorch_model.bin, config.json, etc.)
   - Stores in cache with commit hash
   - Creates symlinks to latest version
4. **Load into memory**: Load from cache using Transformers library

**Example** (m2m100_418M):
```python
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

# Downloads to cache if not present
model = AutoModelForSeq2SeqLM.from_pretrained("facebook/m2m100_418M")
tokenizer = AutoTokenizer.from_pretrained("facebook/m2m100_418M")
```

### CTranslate2 Models

1. **Check local path**: `./models/ct2/<model-name>/`
2. **If not found**: **ERROR** (no automatic download)
3. **Manual conversion required**:
   ```bash
   ct2-transformers-converter --model facebook/m2m100_418M \
       --output_dir ./models/ct2/m2m100_418m \
       --quantization int8
   ```
4. **Load into memory**: Load from local directory

**Example** (m2m100_418m_ct2):
```python
import ctranslate2

# Loads from local directory only
translator = ctranslate2.Translator("./models/ct2/m2m100_418m")
```

## Storage Best Practices

### Development Environments

**Recommendations**:
- Use HuggingFace cache for flexibility
- Download only models needed for testing
- Use smaller models (opus_en_*, t5_small) for quick iteration
- Clean cache periodically (weekly/monthly)

**Minimum storage**:
- 5-10 GB for development (2-3 small models)
- 20-30 GB for full model testing

### Production Environments

**Recommendations**:
- Pre-download models during deployment
- Use CTranslate2 for CPU deployments (50% size reduction)
- Use INT8 quantization where acceptable (85% size reduction)
- Pin model versions in `model_registry.yaml`
- Use container volumes for HuggingFace cache
- Implement cache warming on container startup

**Minimum storage**:
- 2-5 GB per model (HuggingFace)
- 1-2 GB per model (CTranslate2)
- 20-50 GB for production (5-10 models)

### CI/CD Environments

**Recommendations**:
- Cache HuggingFace directory between runs
- Use smaller test models (m2m100_418m, opus_en_es)
- Clean cache after each run (if no caching between runs)
- Use Docker layer caching for model files

**CI cache configuration** (GitHub Actions example):
```yaml
- name: Cache HuggingFace models
  uses: actions/cache@v3
  with:
    path: ~/.cache/huggingface
    key: huggingface-${{ hashFiles('config/model_registry.yaml') }}
```

## Docker/Container Deployments

### Volume Mounting Strategy

**Mount HuggingFace cache as volume**:
```yaml
# docker-compose.yml
services:
  translator:
    image: hugo-translator:latest
    volumes:
      - huggingface-cache:/root/.cache/huggingface
volumes:
  huggingface-cache:
```

**Benefits**:
- Models persist between container restarts
- Shared cache across multiple containers
- Faster container startup (no re-download)

### Pre-warming Cache

**Download models during image build**:
```dockerfile
# Dockerfile
FROM python:3.10-slim

# Install dependencies
COPY requirements.txt .
RUN pip install -r requirements.txt

# Pre-download models
COPY scripts/download_models.py .
COPY config/model_registry.yaml ./config/
RUN python scripts/download_models.py --registry config/model_registry.yaml

# Copy application code
COPY . .
CMD ["python", "src/cli.py"]
```

**Download script** (`scripts/download_models.py`):
```python
#!/usr/bin/env python3
"""Pre-download HuggingFace models to warm cache."""
import argparse
from pathlib import Path
import yaml
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

def download_models(registry_path: Path):
    """Download all HuggingFace models from registry."""
    with open(registry_path) as f:
        registry = yaml.safe_load(f)

    for model in registry.get("models", []):
        if model.get("backend") != "huggingface":
            continue

        hf_id = model.get("hf_model_id")
        if not hf_id:
            continue

        print(f"Downloading {hf_id}...")
        AutoModelForSeq2SeqLM.from_pretrained(hf_id)
        AutoTokenizer.from_pretrained(hf_id)
        print(f"✓ {hf_id} downloaded")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, required=True)
    args = parser.parse_args()
    download_models(args.registry)
```

## Model Update Strategy

### Updating HuggingFace Models

**Automatic updates** (not recommended for production):
```python
# Always downloads latest version
model = AutoModelForSeq2SeqLM.from_pretrained("facebook/m2m100_418M")
```

**Pinned versions** (recommended for production):
```python
# Pin to specific commit/revision
model = AutoModelForSeq2SeqLM.from_pretrained(
    "facebook/m2m100_418M",
    revision="abc123def456"  # Specific commit hash
)
```

**Best practice**:
1. Test new model version in staging
2. Update `model_registry.yaml` with specific revision
3. Deploy to production with pinned version
4. Document version change in release notes

### Updating CTranslate2 Models

**Manual process**:
1. Download new HuggingFace model version
2. Convert to CTranslate2 format
3. Test converted model
4. Replace old model directory
5. Update `model_registry.yaml`

**Example**:
```bash
# Convert new version
ct2-transformers-converter \
    --model facebook/m2m100_418M \
    --revision abc123def456 \
    --output_dir ./models/ct2/m2m100_418m_v2 \
    --quantization int8

# Test new model
python -m src.cli translate --model m2m100_418m_ct2 \
    --model-path ./models/ct2/m2m100_418m_v2 \
    test.md test_output.md

# If tests pass, replace old model
rm -rf ./models/ct2/m2m100_418m
mv ./models/ct2/m2m100_418m_v2 ./models/ct2/m2m100_418m
```

## Security Considerations

### Trusted Model Sources

**Only download models from trusted sources**:
- Official HuggingFace repositories (facebook, Helsinki-NLP, etc.)
- Verified model publishers
- Models with high download counts and community reviews

**Avoid**:
- Random user-uploaded models
- Models without clear licensing
- Models with suspicious file sizes or structures

### Model Verification

**Verify model integrity**:
```python
from huggingface_hub import model_info

# Check model metadata
info = model_info("facebook/m2m100_418M")
print(f"Downloads: {info.downloads}")
print(f"Likes: {info.likes}")
print(f"Tags: {info.tags}")
```

### Cache Permissions

**Secure cache directory**:
```bash
# Ensure cache is only accessible by user
chmod 700 ~/.cache/huggingface/

# Check permissions
ls -ld ~/.cache/huggingface/
# Should show: drwx------ (700)
```

## Troubleshooting

### Cache Corruption

**Symptoms**:
- `OSError: Unable to load weights from checkpoint`
- `RuntimeError: Error loading pytorch_model.bin`

**Solution**:
```bash
# Delete corrupted model from cache
rm -rf ~/.cache/huggingface/hub/models--<org>--<model>

# Re-download
python -c "from transformers import AutoModelForSeq2SeqLM; AutoModelForSeq2SeqLM.from_pretrained('<org>/<model>')"
```

### Disk Space Issues

**Symptoms**:
- `OSError: [Errno 28] No space left on device`
- Download failures

**Solution**:
```bash
# Check cache size
du -sh ~/.cache/huggingface/

# Remove old models
huggingface-cli scan-cache
huggingface-cli delete-cache --older-than 30d

# Or clean entire cache
rm -rf ~/.cache/huggingface/
```

### Network Issues During Download

**Symptoms**:
- `ConnectionError: Failed to download`
- `ReadTimeout: Read timed out`

**Solution**:
```python
# Increase timeout
from transformers import AutoModelForSeq2SeqLM

model = AutoModelForSeq2SeqLM.from_pretrained(
    "facebook/m2m100_418M",
    resume_download=True,  # Resume partial downloads
    timeout=600  # 10 minute timeout
)
```

## Related Documentation

- [Model Registry](../MODEL_REGISTRY.md) - Registry format and model metadata
- [CTranslate2 Guide](../deployment/CTRANSLATE2.md) - Converting and using CT2 models
- [Docker Deployment](../deployment/DOCKER.md) - Container deployment strategies
- [HuggingFace Hub Documentation](https://huggingface.co/docs/huggingface_hub/guides/download) - Official cache documentation
