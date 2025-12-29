# Model Organization and Download Specification

**Version:** 1.0
**Status:** Production-Ready
**Last Updated:** 2025-12-28
**Parent:** [REQUIREMENTS.md](../REQUIREMENTS.md)

## Executive Summary

This specification defines the directory structure, download mechanisms, and management strategies for translation models in the Hugo Translation System. It ensures models are organized, discoverable, and downloadable with minimal user intervention.

## Table of Contents

1. [Directory Structure](#directory-structure)
2. [Model Download Requirements](#model-download-requirements)
3. [Model Registry](#model-registry)
4. [Download Mechanisms](#download-mechanisms)
5. [Model Verification](#model-verification)
6. [Quality Dimensions](#quality-dimensions)
7. [Acceptance Criteria](#acceptance-criteria)
8. [Implementation Guidance](#implementation-guidance)

---

## Directory Structure

### DIR-001: Standardized Model Layout
**Priority:** P0 (Critical)

All models MUST be stored in the `models/` directory with a consistent organizational structure.

**Base Directory:**
```
C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\models\
```

**Organizational Hierarchy:**
```
models/
├── README.md                           # Model directory documentation
├── .gitignore                          # Exclude large model files from git
│
├── m2m100_418M/                        # Facebook M2M100 418M (PyTorch)
│   ├── config.json
│   ├── tokenizer_config.json
│   ├── sentencepiece.bpe.model
│   ├── pytorch_model.bin               # 1.6 GB
│   └── vocab.json
│
├── m2m100_1.2B/                        # Facebook M2M100 1.2B (PyTorch)
│   ├── config.json
│   ├── tokenizer_config.json
│   ├── sentencepiece.bpe.model
│   ├── pytorch_model.bin               # 4.8 GB
│   └── vocab.json
│
├── nllb_200_600m/                      # NLLB-200 600M (PyTorch)
│   ├── config.json
│   ├── tokenizer_config.json
│   ├── sentencepiece.bpe.model
│   ├── pytorch_model.bin               # 2.4 GB
│   └── vocab.json
│
├── nllb_200_1.3b/                      # NLLB-200 1.3B (PyTorch)
│   ├── config.json
│   ├── tokenizer_config.json
│   ├── sentencepiece.bpe.model
│   ├── pytorch_model.bin               # 5.2 GB
│   └── vocab.json
│
├── ct2/                                # CTranslate2 Optimized Models
│   ├── m2m100_418m/                    # CTranslate2 FP32
│   │   ├── config.json
│   │   ├── model.bin                   # 800 MB (2x smaller than PyTorch)
│   │   ├── vocabulary.txt
│   │   └── shared_vocabulary.txt
│   │
│   ├── m2m100_418m_int8/               # CTranslate2 INT8 Quantized
│   │   ├── config.json
│   │   ├── model.bin                   # 250 MB (8x smaller!)
│   │   ├── vocabulary.txt
│   │   └── shared_vocabulary.txt
│   │
│   └── nllb_200_600m_int8/             # NLLB CTranslate2 INT8
│       ├── config.json
│       ├── model.bin                   # 350 MB
│       ├── vocabulary.txt
│       └── shared_vocabulary.txt
│
├── opus/                               # Opus-MT Specialized Models
│   ├── opus-mt-en-fr/                  # English → French
│   │   ├── config.json
│   │   ├── tokenizer_config.json
│   │   ├── source.spm
│   │   ├── target.spm
│   │   └── pytorch_model.bin           # 300 MB
│   │
│   ├── opus-mt-en-es/                  # English → Spanish
│   │   └── ...
│   │
│   └── opus-mt-en-de/                  # English → German
│       └── ...
│
├── small100/                           # Small100 Multilingual
│   ├── config.json
│   ├── tokenizer_config.json
│   ├── sentencepiece.bpe.model
│   ├── pytorch_model.bin               # 1.2 GB
│   └── vocab.json
│
└── model_manifest.json                 # Metadata for all downloaded models
```

**Rationale:**
- **Top-level separation:** PyTorch vs CTranslate2 vs Specialized
- **Model family grouping:** Opus models together, CT2 optimized models together
- **Predictable paths:** Model ID → Directory name (lowercase, underscores)
- **Metadata tracking:** `model_manifest.json` for download/verification status

### DIR-002: Model Manifest File

The `models/model_manifest.json` file MUST track all downloaded models:

```json
{
  "version": "1.0",
  "last_updated": "2025-12-28T10:30:00Z",
  "models": [
    {
      "model_id": "m2m100_418m",
      "local_path": "models/m2m100_418M",
      "download_source": "huggingface:facebook/m2m100_418M",
      "size_mb": 1600,
      "files": [
        {"name": "pytorch_model.bin", "size_bytes": 1677721600, "sha256": "abc123..."},
        {"name": "config.json", "size_bytes": 1234, "sha256": "def456..."}
      ],
      "downloaded_at": "2025-12-28T09:15:00Z",
      "verified": true,
      "backend": "huggingface"
    },
    {
      "model_id": "m2m100_418m_ct2_int8",
      "local_path": "models/ct2/m2m100_418m_int8",
      "download_source": "ctranslate2:converted",
      "size_mb": 250,
      "files": [
        {"name": "model.bin", "size_bytes": 262144000, "sha256": "xyz789..."}
      ],
      "downloaded_at": "2025-12-28T09:45:00Z",
      "verified": true,
      "backend": "ctranslate2"
    }
  ]
}
```

**Usage:**
- Check if model already downloaded
- Verify integrity before loading
- Track disk space usage
- Support model cleanup/removal

---

## Model Download Requirements

### DL-001: Automated Model Download
**Priority:** P0 (Critical)

Users MUST be able to download all required models via a single CLI command.

**Command:**
```bash
python -m src.cli download-models --all
```

**Expected Output:**
```
Model Download Manager
══════════════════════════════════════════════════════════════

Discovering models from registry...
└─ Found 10 models requiring download

Download Plan:
┌────────────────────────┬──────────┬──────────────┬──────────┐
│ Model ID               │ Size     │ Source       │ Status   │
├────────────────────────┼──────────┼──────────────┼──────────┤
│ m2m100_418m            │ 1.6 GB   │ HuggingFace  │ Queued   │
│ m2m100_418m_ct2        │ 800 MB   │ HuggingFace  │ Queued   │
│ m2m100_418m_ct2_int8   │ 250 MB   │ Conversion   │ Queued   │
│ nllb_200_600m_ct2_int8 │ 350 MB   │ Conversion   │ Queued   │
│ ...                    │          │              │          │
└────────────────────────┴──────────┴──────────────┴──────────┘

Total Download Size: 8.2 GB
Estimated Time: ~25 minutes (10 Mbps network)

Proceed with download? [Y/n]: Y

[1/10] Downloading m2m100_418m...
  ├─ Fetching: facebook/m2m100_418M from HuggingFace Hub
  ├─ Progress: ████████████████████ 100% (1.6 GB / 1.6 GB)
  ├─ Speed: 12.3 MB/s
  ├─ ETA: Complete
  └─ Verifying checksum... ✓ OK

[2/10] Downloading m2m100_418m_ct2...
  └─ ...

Download Summary:
  ✓ 10 models downloaded successfully
  ✗ 0 models failed
  💾 8.2 GB disk space used
  ⏱ Total time: 23m 15s

All models ready for use!
```

### DL-002: Selective Model Download

Users MUST be able to download specific models:

**By Model ID:**
```bash
python -m src.cli download-models --model m2m100_418m
```

**By Language Requirement:**
```bash
python -m src.cli download-models --language fr
# Downloads all models supporting French
```

**By Priority (Production Models Only):**
```bash
python -m src.cli download-models --priority P0
# Downloads only critical production models (m2m100_418m, nllb_200_600m, etc.)
```

### DL-003: Download Resumption

Interrupted downloads MUST support resumption without re-downloading completed files.

**Implementation:**
- Use HuggingFace Hub's `resume_download=True`
- Track partial downloads in manifest
- Verify partial files before resuming

**Example:**
```bash
# First attempt (interrupted at 60%)
python -m src.cli download-models --model m2m100_418m
# Downloads 60% of pytorch_model.bin... [Network failure]

# Resume (continues from 60%)
python -m src.cli download-models --model m2m100_418m
# Resuming download from 1006 MB / 1600 MB...
# ████████████░░░░░░░░ 60% → 100% (594 MB remaining)
```

### DL-004: Network Error Handling

Download failures MUST provide actionable error messages:

**Network Timeout:**
```
ERROR: Download timeout for m2m100_418m
  ├─ Source: https://huggingface.co/facebook/m2m100_418M
  ├─ Error: Connection timeout after 120 seconds
  └─ Solution: Check network connection and retry with --retry

Retry command:
  python -m src.cli download-models --model m2m100_418m --retry 3
```

**Disk Space Insufficient:**
```
ERROR: Insufficient disk space
  ├─ Required: 1.6 GB
  ├─ Available: 850 MB
  └─ Solution: Free up disk space or use --path to specify alternate location

Alternate path:
  python -m src.cli download-models --model m2m100_418m --path D:\models
```

**HuggingFace Rate Limit:**
```
ERROR: Rate limit exceeded
  ├─ Source: HuggingFace Hub
  ├─ Limit: 10 concurrent downloads
  ├─ Current: 12 active downloads
  └─ Solution: Wait 60 seconds or reduce --parallel flag

Retry with reduced parallelism:
  python -m src.cli download-models --all --parallel 5
```

---

## Model Registry

### REG-001: Registry Configuration File
**Priority:** P0 (Critical)

All models MUST be defined in `config/model_registry.yaml`.

**Schema:**
```yaml
models:
  - model_id: m2m100_418m                     # Unique identifier (required)
    name: "Facebook M2M100 (418M)"            # Human-readable name
    backend: huggingface                      # Backend: huggingface, ctranslate2
    local_path: models/m2m100_418M            # Local storage path
    hf_model_id: facebook/m2m100_418M         # HuggingFace Hub ID (if backend=huggingface)
    supported_pairs: all                      # "all" or list of [source, target] pairs
    model_size_mb: 1600                       # Disk space required
    min_ram_gb: 4                             # Minimum RAM requirement
    optimal_device: cuda                      # cpu, cuda, mps
    parameters: 418000000                     # Model parameter count
    license: MIT                              # License identifier
    description: >
      Multilingual translation model from Facebook.
      Supports 100 languages with good quality.

  - model_id: opus_en_fr
    name: "Opus-MT English-French"
    backend: huggingface
    local_path: models/opus/opus-mt-en-fr
    hf_model_id: Helsinki-NLP/opus-mt-en-fr
    supported_pairs:
      - [en, fr]                              # English → French only
      - [fr, en]                              # French → English (bidirectional)
    model_size_mb: 300
    min_ram_gb: 1
    optimal_device: cpu
    parameters: 77000000
    license: CC-BY-4.0
    description: >
      Specialized English-French model. Fast and lightweight.
```

**Validation Rules:**
- `model_id` MUST be unique
- `local_path` MUST be under `models/` directory
- `hf_model_id` MUST be valid HuggingFace Hub path (if `backend=huggingface`)
- `supported_pairs` MUST be "all" or list of 2-element lists

### REG-002: Registry Loading and Validation

The system MUST validate registry on load:

```python
from src.model_runtime.registry import ModelRegistry

registry = ModelRegistry.load("config/model_registry.yaml")

# Validation checks
registry.validate()
# Checks:
# - All model_ids unique
# - All paths valid
# - All HuggingFace IDs reachable (optional network check)
# - No duplicate local_paths
```

**Validation Errors:**
```
ERROR: Invalid model registry
  ├─ Duplicate model_id: "m2m100_418m" appears twice
  ├─ Invalid path: "models/../../../etc/passwd" (path traversal detected)
  └─ Missing field: "hf_model_id" required for backend=huggingface

Fix config/model_registry.yaml and retry.
```

---

## Download Mechanisms

### MECH-001: HuggingFace Hub Download

For models with `backend: huggingface`, use the HuggingFace Hub API:

```python
from huggingface_hub import snapshot_download

def download_huggingface_model(model_config):
    """Download model from HuggingFace Hub."""
    local_path = snapshot_download(
        repo_id=model_config.hf_model_id,
        local_dir=model_config.local_path,
        local_dir_use_symlinks=False,      # Copy files, don't symlink
        resume_download=True,               # Resume interrupted downloads
        token=None,                         # No token needed for public models
        ignore_patterns=["*.msgpack", "*.h5"]  # Skip non-PyTorch formats
    )

    return local_path
```

**Progress Tracking:**
```python
from huggingface_hub import HfApi
from tqdm import tqdm

def download_with_progress(hf_model_id, local_path):
    api = HfApi()
    repo_info = api.repo_info(repo_id=hf_model_id)

    # Get total size
    total_size = sum(f.size for f in repo_info.siblings)

    # Download with progress bar
    with tqdm(total=total_size, unit='B', unit_scale=True) as pbar:
        def progress_callback(chunk_size):
            pbar.update(chunk_size)

        snapshot_download(
            repo_id=hf_model_id,
            local_dir=local_path,
            resume_download=True,
            # Note: HuggingFace Hub doesn't support progress callbacks directly
            # Alternative: Poll local_dir size in separate thread
        )
```

### MECH-002: CTranslate2 Model Conversion

For CTranslate2 models, download PyTorch version first, then convert:

```python
import ctranslate2

def convert_to_ctranslate2(pytorch_model_path, output_path, quantization="float32"):
    """Convert PyTorch model to CTranslate2 format."""
    converter = ctranslate2.converters.TransformersConverter(pytorch_model_path)

    converter.convert(
        output_dir=output_path,
        quantization=quantization,  # "float32", "float16", "int8"
        force=True  # Overwrite if exists
    )

    print(f"✓ Converted to CTranslate2: {output_path}")
    print(f"  └─ Quantization: {quantization}")

# Example: Convert M2M100 to INT8
convert_to_ctranslate2(
    pytorch_model_path="models/m2m100_418M",
    output_path="models/ct2/m2m100_418m_int8",
    quantization="int8"
)
```

**Download Workflow for CT2 Models:**
1. Check if CTranslate2 model exists in HuggingFace Hub (pre-converted)
2. If yes: Download directly
3. If no: Download PyTorch version → Convert → Save to `ct2/` directory

### MECH-003: Parallel Downloads

Download multiple models in parallel (respecting rate limits):

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def download_all_models(model_configs, max_workers=5):
    """Download multiple models in parallel."""
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(download_model, config): config
            for config in model_configs
        }

        for future in as_completed(futures):
            config = futures[future]
            try:
                result = future.result()
                print(f"✓ Downloaded: {config.model_id}")
            except Exception as e:
                print(f"✗ Failed: {config.model_id} - {e}")
```

**Rate Limiting:**
- HuggingFace Hub: Max 10 concurrent downloads
- Retry with exponential backoff on 429 errors

---

## Model Verification

### VER-001: Checksum Verification
**Priority:** P1 (High)

Downloaded models SHOULD be verified using checksums:

```python
import hashlib

def compute_file_hash(file_path, algorithm="sha256"):
    """Compute file hash for verification."""
    hasher = hashlib.new(algorithm)

    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)

    return hasher.hexdigest()

def verify_model_integrity(model_path, expected_hashes):
    """Verify all model files match expected hashes."""
    for file_name, expected_hash in expected_hashes.items():
        file_path = model_path / file_name
        actual_hash = compute_file_hash(file_path)

        if actual_hash != expected_hash:
            raise IntegrityError(
                f"Checksum mismatch: {file_name}\n"
                f"  Expected: {expected_hash}\n"
                f"  Actual:   {actual_hash}"
            )

    print("✓ Model integrity verified")
```

**Checksum Storage:**
```json
{
  "model_id": "m2m100_418m",
  "checksums": {
    "pytorch_model.bin": "a1b2c3d4e5f6...",
    "config.json": "f6e5d4c3b2a1...",
    "tokenizer_config.json": "1234567890ab..."
  }
}
```

### VER-002: Load Test Verification

After download, verify model loads correctly:

```python
def verify_model_loads(model_id):
    """Verify model can be loaded and run a test translation."""
    from src.model_runtime.loader import ModelLoader

    loader = ModelLoader()
    model = loader.load_model(model_id)

    # Run test translation
    test_input = "Hello, world!"
    test_output = model.translate(test_input, target_lang="fr")

    if not test_output:
        raise VerificationError(f"Model {model_id} failed test translation")

    print(f"✓ Model {model_id} verified")
    print(f"  └─ Test: '{test_input}' → '{test_output}'")
```

**Expected Output:**
```
✓ Model m2m100_418m verified
  └─ Test: 'Hello, world!' → 'Bonjour, le monde!'
```

### VER-003: Disk Space Verification

Before download, verify sufficient disk space:

```python
import shutil

def check_disk_space(model_size_mb, download_path):
    """Check if sufficient disk space available."""
    stat = shutil.disk_usage(download_path)
    available_mb = stat.free / 1024 / 1024

    required_mb = model_size_mb * 1.2  # 20% buffer for temporary files

    if available_mb < required_mb:
        raise InsufficientDiskSpaceError(
            f"Insufficient disk space:\n"
            f"  Required: {required_mb:.0f} MB\n"
            f"  Available: {available_mb:.0f} MB\n"
            f"  Free up {required_mb - available_mb:.0f} MB and retry."
        )
```

---

## Quality Dimensions

### 1. Completeness (5/5)
**Measurement:**
- [ ] All models in registry downloadable
- [ ] All download mechanisms tested (HuggingFace, CTranslate2)
- [ ] All model formats supported (PyTorch, CT2, ONNX)

**Test:**
```bash
python -m src.cli download-models --all --dry-run
# Should list all 10 models as downloadable
```

### 2. Reliability (5/5)
**Measurement:**
- [ ] Download resumption works after interruption
- [ ] Checksum verification catches corrupted files
- [ ] Network errors handled gracefully

**Test:**
```python
def test_download_resumption():
    # Start download
    download_model("m2m100_418m")

    # Simulate interruption at 50%
    interrupt_at_progress(0.5)

    # Resume download
    download_model("m2m100_418m")

    # Verify complete
    assert model_exists("m2m100_418m")
    assert model_integrity("m2m100_418m")
```

### 3. Usability (5/5)
**Measurement:**
- [ ] Single command downloads all models
- [ ] Progress bars show ETA
- [ ] Error messages actionable

**User Test:**
- First-time user completes model download in <5 minutes
- Zero manual file operations required

### 4. Performance (4/5)
**Measurement:**
- [ ] Parallel downloads utilize full bandwidth
- [ ] Large models (>1GB) download at ≥10 MB/s (on 100 Mbps network)
- [ ] CTranslate2 conversion completes in <5 minutes per model

**Benchmarks:**
- M2M100 418M (1.6 GB): Download in ~2.5 minutes (10 MB/s)
- NLLB 1.3B (5.2 GB): Download in ~8 minutes (10 MB/s)

### 5. Maintainability (5/5)
**Measurement:**
- [ ] New models added via registry YAML only
- [ ] Download logic abstracted (backend-agnostic)
- [ ] Model paths configurable

**Test:**
```yaml
# Add new model to registry
- model_id: new_model_123
  backend: huggingface
  hf_model_id: org/new_model
  # ... other fields

# Download immediately works
python -m src.cli download-models --model new_model_123
```

---

## Acceptance Criteria

### Functional Acceptance

1. **Download All Models**
   - [ ] Command `download-models --all` downloads all 10 models
   - [ ] All models stored in correct directory structure
   - [ ] Manifest file updated with download metadata

2. **Download Resumption**
   - [ ] Interrupted downloads resume from last checkpoint
   - [ ] No re-download of already-downloaded files
   - [ ] Partial files verified before resuming

3. **Model Verification**
   - [ ] Checksums validated for all downloaded files
   - [ ] Load test successful for all models
   - [ ] Corrupted files detected and re-downloaded

### Non-Functional Acceptance

4. **Performance**
   - [ ] Parallel downloads utilize ≥80% available bandwidth
   - [ ] Download time within ±20% of theoretical minimum

5. **Usability**
   - [ ] Error messages provide actionable solutions
   - [ ] Progress bars show accurate ETA (±10%)
   - [ ] Zero manual intervention required

6. **Reliability**
   - [ ] Network failures do not corrupt downloads
   - [ ] Disk full errors detected before download
   - [ ] 100 consecutive downloads succeed (or fail gracefully)

---

## Implementation Guidance

### CLI Command Implementation

```python
# src/cli.py

import click
from src.model_runtime.downloader import ModelDownloader

@click.command()
@click.option('--all', is_flag=True, help='Download all models')
@click.option('--model', help='Download specific model by ID')
@click.option('--language', help='Download models supporting language')
@click.option('--priority', help='Download models by priority (P0, P1, P2)')
@click.option('--parallel', default=5, help='Max parallel downloads')
@click.option('--retry', default=3, help='Retry failed downloads N times')
def download_models(all, model, language, priority, parallel, retry):
    """Download translation models."""
    downloader = ModelDownloader()

    if all:
        models = downloader.get_all_models()
    elif model:
        models = [downloader.get_model(model)]
    elif language:
        models = downloader.get_models_for_language(language)
    elif priority:
        models = downloader.get_models_by_priority(priority)
    else:
        click.echo("Specify --all, --model, --language, or --priority")
        return

    downloader.download(
        models=models,
        max_workers=parallel,
        max_retries=retry
    )
```

### Model Downloader Class

```python
# src/model_runtime/downloader.py

from pathlib import Path
from huggingface_hub import snapshot_download
from concurrent.futures import ThreadPoolExecutor

class ModelDownloader:
    def __init__(self, registry_path="config/model_registry.yaml"):
        self.registry = ModelRegistry.load(registry_path)
        self.models_dir = Path("models")

    def download(self, models, max_workers=5, max_retries=3):
        """Download models in parallel."""
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []

            for model in models:
                future = executor.submit(
                    self._download_single,
                    model,
                    max_retries
                )
                futures.append((future, model))

            for future, model in futures:
                try:
                    result = future.result()
                    print(f"✓ {model.model_id}: {result}")
                except Exception as e:
                    print(f"✗ {model.model_id}: {e}")

    def _download_single(self, model, max_retries):
        """Download single model with retry logic."""
        for attempt in range(max_retries):
            try:
                if model.backend == "huggingface":
                    return self._download_huggingface(model)
                elif model.backend == "ctranslate2":
                    return self._download_ctranslate2(model)
                else:
                    raise ValueError(f"Unknown backend: {model.backend}")
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                print(f"  Retry {attempt + 1}/{max_retries}...")
                time.sleep(2 ** attempt)  # Exponential backoff

    def _download_huggingface(self, model):
        """Download from HuggingFace Hub."""
        local_path = snapshot_download(
            repo_id=model.hf_model_id,
            local_dir=str(self.models_dir / model.local_path),
            local_dir_use_symlinks=False,
            resume_download=True
        )

        self._verify_model(model, local_path)
        self._update_manifest(model, local_path)

        return local_path
```

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-12-28 | System | Initial specification |

---

## Related Specifications

- [REQUIREMENTS.md](../REQUIREMENTS.md) - Parent requirements
- [36_LANGUAGE_COVERAGE.md](36_LANGUAGE_COVERAGE.md) - Model-language mapping
