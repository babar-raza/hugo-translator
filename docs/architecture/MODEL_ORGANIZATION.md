# Model Organization Architecture

**Version:** 1.0
**Status:** Production-Ready
**Last Updated:** 2025-12-28

## Overview

The Hugo Translation System uses a professional model organization strategy inspired by HuggingFace Hub and industry best practices for managing machine learning models in production environments.

## Table of Contents

1. [Design Principles](#design-principles)
2. [Directory Structure](#directory-structure)
3. [Model Identification](#model-identification)
4. [Metadata Schema](#metadata-schema)
5. [Model Lifecycle](#model-lifecycle)
6. [Disk Space Management](#disk-space-management)
7. [Multi-Backend Support](#multi-backend-support)
8. [Version Management](#version-management)
9. [Security](#security)
10. [Troubleshooting](#troubleshooting)

---

## Design Principles

### 1. Backend Separation
Different model backends are stored in separate directories to prevent file conflicts and enable backend-specific optimizations.

**Rationale:**
- PyTorch and CTranslate2 models have different file structures
- Prevents accidental mixing of incompatible files
- Enables backend-specific tooling and validation

### 2. Self-Describing Models
Each model directory contains complete metadata describing its provenance, configuration, and verification status.

**Rationale:**
- No external database required to understand model inventory
- Portable: models can be moved between systems with metadata intact
- Audit trail: download source, verification history tracked

### 3. Git-Friendly Structure
Directory structure and metadata tracked in git, binary files excluded.

**Rationale:**
- Team collaboration on model selection and configuration
- History of which models were added/removed
- Binary files downloaded on-demand (not in git)

### 4. Automated Management
All operations (download, verify, cleanup) automated via scripts.

**Rationale:**
- Consistency across team members and environments
- Error handling and retry logic
- Audit logging for compliance

### 5. Scalable Organization
Supports 100+ models without naming collisions or performance degradation.

**Rationale:**
- Future-proof for multilingual expansion
- Efficient disk I/O (no deep nesting)
- Fast model discovery and loading

---

## Directory Structure

### Complete Layout

```
models/
├── huggingface/                  # Backend: HuggingFace Transformers
│   ├── m2m100_418m/              # Model directory
│   │   ├── config.json           # Model configuration
│   │   ├── pytorch_model.bin     # Model weights (PyTorch)
│   │   ├── tokenizer_config.json # Tokenizer config
│   │   ├── special_tokens_map.json
│   │   ├── tokenizer.json        # Fast tokenizer
│   │   ├── sentencepiece.bpe.model
│   │   └── .metadata.json        # Custom metadata (our addition)
│   ├── m2m100_1.2b/
│   │   ├── config.json
│   │   ├── pytorch_model.bin
│   │   └── .metadata.json
│   ├── nllb_200_600m/
│   ├── nllb_200_1.3b/
│   └── opus-mt/                  # Model family grouping
│       ├── opus-mt-en-fr/
│       ├── opus-mt-en-de/
│       └── opus-mt-en-es/
├── ctranslate2/                  # Backend: CTranslate2 (optimized)
│   ├── m2m100_418m/
│   │   ├── model.bin             # CTranslate2 binary format
│   │   ├── shared_vocabulary.json
│   │   ├── source_vocabulary.json
│   │   ├── target_vocabulary.json
│   │   └── .metadata.json
│   ├── m2m100_418m_int8/         # INT8 quantized variant
│   │   ├── model.bin
│   │   └── .metadata.json
│   └── nllb_200_600m_int8/
├── cache/                        # Temporary runtime cache
│   ├── tokenizers/               # Tokenizer caches
│   ├── downloads/                # Partial downloads (resume support)
│   └── compilation/              # CTranslate2 compilation artifacts
├── inventory.json                # Model inventory database (auto-generated)
├── .gitkeep                      # Ensures models/ tracked in git
└── README.md                     # User-facing documentation
```

### Naming Conventions

**Model Directory Names:**
- Format: `{model_family}_{parameter_count}[_{variant}]`
- Examples: `m2m100_418m`, `nllb_200_1.3b`, `m2m100_418m_int8`
- Use lowercase with underscores (no spaces, hyphens, or camelCase)

**Model Family Grouping:**
- Specialized models grouped under family subdirectory
- Example: `opus-mt/opus-mt-en-fr/`, `opus-mt/opus-mt-en-de/`

---

## Model Identification

### Three-Level Identification System

#### 1. Internal Model ID
**Format:** `{family}_{size}[_{variant}]`
**Example:** `m2m100_418m_ct2_int8`
**Usage:** Configuration files, logs, database keys

#### 2. HuggingFace Model ID
**Format:** `{org}/{repo}`
**Example:** `facebook/m2m100_418M`
**Usage:** Downloads, documentation, citations

#### 3. Local Path
**Format:** `models/{backend}/{model_id}`
**Example:** `models/ctranslate2/m2m100_418m_int8`
**Usage:** File system operations, model loading

### Mapping Example

| Internal ID | HuggingFace ID | Local Path |
|-------------|----------------|------------|
| `m2m100_418m` | `facebook/m2m100_418M` | `models/huggingface/m2m100_418m/` |
| `m2m100_418m_ct2` | `facebook/m2m100_418M` (converted) | `models/ctranslate2/m2m100_418m/` |
| `opus_en_fr` | `Helsinki-NLP/opus-mt-en-fr` | `models/huggingface/opus-mt/opus-mt-en-fr/` |

---

## Metadata Schema

### `.metadata.json` Structure

Every model directory MUST contain `.metadata.json`:

```json
{
  "$schema": "https://huggingface.co/schemas/model-metadata.json",
  "model_id": "m2m100_418m",
  "backend": "huggingface",
  "hf_model_id": "facebook/m2m100_418M",
  "local_path": "models/huggingface/m2m100_418m",
  "downloaded_at": "2025-12-27T10:00:00Z",
  "download_source": "huggingface_hub",
  "download_method": "snapshot_download",
  "size_mb": 1600,
  "files": [
    "config.json",
    "pytorch_model.bin",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "tokenizer.json",
    "sentencepiece.bpe.model"
  ],
  "sha256": {
    "pytorch_model.bin": "a1b2c3d4e5f6...",
    "config.json": "f6e5d4c3b2a1..."
  },
  "license": "MIT",
  "supported_pairs": "all",
  "last_verified": "2025-12-27T10:05:00Z",
  "verification_status": "passed",
  "verification_method": "load_and_inference",
  "parameters": 418000000,
  "quantization": null,
  "device_compatibility": ["cpu", "cuda"],
  "notes": ""
}
```

### Required Fields

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `model_id` | string | Internal model identifier | `"m2m100_418m"` |
| `backend` | string | Model backend | `"huggingface"`, `"ctranslate2"` |
| `hf_model_id` | string | HuggingFace Hub identifier | `"facebook/m2m100_418M"` |
| `local_path` | string | Relative path from project root | `"models/huggingface/m2m100_418m"` |
| `downloaded_at` | ISO 8601 | Download timestamp | `"2025-12-27T10:00:00Z"` |
| `size_mb` | number | Total size in megabytes | `1600` |
| `license` | string | Model license | `"MIT"`, `"CC-BY-4.0"` |
| `last_verified` | ISO 8601 | Last verification timestamp | `"2025-12-27T10:05:00Z"` |
| `verification_status` | string | Verification result | `"passed"`, `"failed"`, `"pending"` |

### Optional Fields

| Field | Type | Description |
|-------|------|-------------|
| `files` | array | List of files in model directory |
| `sha256` | object | SHA256 checksums per file |
| `supported_pairs` | string/array | Language pairs supported |
| `parameters` | integer | Model parameter count |
| `quantization` | string | Quantization type (`"int8"`, `"fp16"`, etc.) |
| `device_compatibility` | array | Compatible devices (`["cpu", "cuda"]`) |
| `notes` | string | Free-form notes |

---

## Model Lifecycle

### 1. Discovery
Identify candidate models from HuggingFace Hub or model registries.

**Tools:**
- `scripts/models/discover_models.py` - Search HuggingFace for translation models
- Manual curation in `config/model_registry.yaml`

### 2. Registration
Add model to `config/model_registry.yaml` with metadata.

**Example:**
```yaml
- model_id: m2m100_418m
  name: Facebook M2M100 (418M)
  backend: huggingface
  hf_model_id: facebook/m2m100_418M
  supported_pairs: all
  model_size_mb: 1600
  min_ram_gb: 4
  optimal_device: cuda
  parameters: 418000000
  license: MIT
```

### 3. Download
Download model files to correct directory structure.

**Command:**
```bash
python scripts/models/download_models.py --model m2m100_418m
```

**Process:**
1. Validate model_id exists in registry
2. Check disk space (required + 50% buffer)
3. Create directory: `models/{backend}/{model_id}/`
4. Create `.downloading` marker file
5. Download via HuggingFace Hub API (with resume support)
6. Verify checksums (if available)
7. Create `.metadata.json`
8. Remove `.downloading` marker
9. Update `models/inventory.json`

### 4. Verification
Validate model integrity and functionality.

**Command:**
```bash
python scripts/verify_models.py --model m2m100_418m
```

**Checks:**
- All required files present
- Checksums match (if recorded)
- Model loads successfully
- Basic inference works (translate "Hello" → "Hola")
- Memory usage within expected range

### 5. Usage
Load model for translation tasks.

**Loader Logic:**
```python
def load_model(model_id: str):
    metadata = read_metadata(model_id)
    if metadata['backend'] == 'huggingface':
        return load_huggingface_model(metadata['local_path'])
    elif metadata['backend'] == 'ctranslate2':
        return load_ctranslate2_model(metadata['local_path'])
```

### 6. Cleanup
Remove unused or outdated models.

**Command:**
```bash
python scripts/models/cleanup_models.py --unused
```

**Safety:**
- Never delete currently loaded models
- Move to `.trash/` instead of permanent deletion
- Update inventory atomically

---

## Disk Space Management

### Space Requirements by Model Type

| Model Type | Typical Size | Example |
|------------|--------------|---------|
| Small (PyTorch) | 300-800 MB | opus-mt-en-fr (300 MB) |
| Medium (PyTorch) | 1.5-2.5 GB | m2m100_418m (1.6 GB) |
| Large (PyTorch) | 5-7 GB | nllb_200_1.3b (5.2 GB) |
| Small (CT2 INT8) | 100-300 MB | opus-mt-en-fr_ct2_int8 (150 MB) |
| Medium (CT2 INT8) | 250-600 MB | m2m100_418m_ct2_int8 (400 MB) |

### Total Space Estimates

| Deployment Profile | Model Count | Total Space |
|-------------------|-------------|-------------|
| **Minimal** | 1 (INT8) | 500 MB |
| **Essential** | 4 (INT8 variants) | 2 GB |
| **Production CPU** | 10 (Mixed) | 15 GB |
| **Production GPU** | 15 (All variants) | 50 GB |
| **Full Suite** | 30+ (Research) | 100+ GB |

### Disk Management Strategies

#### 1. Lazy Loading
Only download models when first needed.

#### 2. Tiered Storage
- **Fast SSD:** Frequently used models
- **Slower HDD:** Rarely used models, backups

#### 3. Compression
- Use filesystem compression (NTFS, Btrfs)
- Saves 20-30% space with minimal CPU overhead

#### 4. Deduplication
- Some files (tokenizers) shared across variants
- Use hardlinks or symlinks where safe

---

## Multi-Backend Support

### HuggingFace Transformers

**Format:** PyTorch (*.bin, *.safetensors)

**Pros:**
- Full precision (FP32)
- All model features available
- Widely compatible
- Easy fine-tuning

**Cons:**
- Slower inference
- More memory usage
- Larger disk footprint

**Use Cases:**
- GPU inference
- Quality-critical production
- Research and experimentation
- Fine-tuning

### CTranslate2

**Format:** Custom binary (model.bin)

**Pros:**
- 2-4x faster inference
- 50% less memory
- INT8 quantization support
- CPU-optimized kernels

**Cons:**
- Limited to translation
- No fine-tuning
- Conversion step required

**Use Cases:**
- CPU production deployments
- High-throughput scenarios
- Memory-constrained environments

### ONNX (Future)

**Format:** ONNX (*.onnx)

**Pros:**
- Cross-platform (Python, C++, JavaScript)
- Embedded devices
- No PyTorch dependency

**Cons:**
- Limited operator support
- Conversion complexity

---

## Version Management

### Model Versioning Strategy

**Challenge:** Models updated on HuggingFace Hub

**Solution:** Snapshot-based versioning

#### Approach 1: Commit Hash Pinning
```yaml
model_id: m2m100_418m_v1
hf_model_id: facebook/m2m100_418M
revision: "a1b2c3d4e5f6..."  # Git commit hash
```

#### Approach 2: Date-Based Snapshots
```
models/huggingface/m2m100_418m_2025-01/
models/huggingface/m2m100_418m_2025-12/
```

#### Approach 3: Semantic Versioning
```yaml
model_id: m2m100_418m_v2.1
notes: "Updated tokenizer, improved quality"
```

**Current Implementation:** Approach 1 (commit pinning)

**Rationale:**
- Reproducible benchmarks
- Stable production deployments
- Explicit upgrade path

---

## Security

### Download Security

1. **Source Restriction**
   - Only download from `hub.huggingface.co`
   - No arbitrary URLs accepted

2. **Checksum Verification**
   - SHA256 verification for all files
   - Checksums from HuggingFace Hub metadata

3. **Malware Scanning**
   - PyTorch models: Inspect pickle files (no arbitrary code execution)
   - CTranslate2: Binary format (no code execution risk)

### Model Integrity

**Verification Steps:**
1. File presence check
2. Checksum validation
3. Load test (detect corruption)
4. Inference test (detect degradation)

**Verification Frequency:**
- On download: Always
- On system boot: Optional (slow)
- Periodic: Weekly via cron

### Access Control

**File Permissions:**
```bash
# Model files: read-only
chmod 444 models/huggingface/*/pytorch_model.bin

# Metadata: writable (for verification updates)
chmod 644 models/**/.metadata.json
```

---

## Troubleshooting

### Model Directory Not Found

**Symptoms:**
```
FileNotFoundError: models/huggingface/m2m100_418m not found
```

**Diagnosis:**
```bash
# Check if model in registry
grep "m2m100_418m" config/model_registry.yaml

# Check inventory
cat models/inventory.json
```

**Solution:**
```bash
# Download missing model
python scripts/models/download_models.py --model m2m100_418m
```

---

### Model Fails to Load

**Symptoms:**
```
RuntimeError: Error loading pytorch_model.bin
```

**Diagnosis:**
```bash
# Verify integrity
python scripts/verify_models.py --model m2m100_418m
```

**Solutions:**
1. **Corrupted download:**
   ```bash
   python scripts/models/download_models.py --model m2m100_418m --force
   ```

2. **Incompatible PyTorch version:**
   ```bash
   pip install --upgrade torch
   ```

3. **Insufficient memory:**
   ```bash
   # Use smaller variant or INT8 quantization
   python scripts/models/download_models.py --model m2m100_418m_ct2_int8
   ```

---

### Out of Disk Space

**Symptoms:**
```
OSError: [Errno 28] No space left on device
```

**Diagnosis:**
```bash
df -h models/
du -sh models/*
```

**Solutions:**
1. **Remove cache:**
   ```bash
   rm -rf models/cache/*
   ```

2. **Remove unused models:**
   ```bash
   python scripts/models/cleanup_models.py --unused
   ```

3. **Use INT8 variants:**
   ```bash
   # Replace FP32 with INT8 (50% space savings)
   python scripts/models/remove_model.py m2m100_418m
   python scripts/models/download_models.py --model m2m100_418m_ct2_int8
   ```

---

## References

- **HuggingFace Hub:** https://huggingface.co/docs/hub
- **CTranslate2:** https://opennmt.net/CTranslate2/
- **Model Cards:** https://huggingface.co/docs/hub/model-cards
- **M2M100 Paper:** https://arxiv.org/abs/2010.11125
- **NLLB Paper:** https://arxiv.org/abs/2207.04672

---

**Revision History:**
- v1.0 (2025-12-28): Initial production-ready specification
