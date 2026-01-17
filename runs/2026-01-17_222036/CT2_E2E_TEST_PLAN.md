# CT2 End-to-End Test Plan

**Date:** 2026-01-17
**Status:** Ready for execution (requires ctranslate2 installed)
**Environment:** .venv Python environment

## Prerequisites

### 1. Install CTranslate2

```bash
# Activate virtual environment
.venv/Scripts/activate  # Windows
# or: source .venv/bin/activate  # Linux/Mac

# Install CT2 (CPU version)
pip install ctranslate2

# OR install with CUDA support
pip install ctranslate2[cuda11]  # for CUDA 11.x
pip install ctranslate2[cuda12]  # for CUDA 12.x
```

### 2. Verify Installation

```bash
python -c "import ctranslate2; print(f'CT2 version: {ctranslate2.__version__}')"
# Expected: CT2 version: 4.x.x
```

### 3. Ensure Models Downloaded

```bash
# Check available models
.venv/Scripts/python -m src.model_runtime.model_cli list

# Download m2m100_418m if not present
.venv/Scripts/python -m src.model_runtime.model_cli download --model-id m2m100_418m
```

---

## Test Scenario 1: Single Model Conversion

### Objective
Convert m2m100_418M to CT2 INT8 format and verify registry/manifest updates.

### Steps

#### 1.1 Check Initial State

```bash
# List existing CT2 models
.venv/Scripts/python -m src.model_runtime.model_cli list-ct2

# Expected: No CT2 models exist yet
```

#### 1.2 Convert Model

```bash
# Convert m2m100_418m to CT2 INT8
.venv/Scripts/python -m src.model_runtime.model_cli convert-ct2 \
    --model m2m100_418m \
    --quant int8
```

**Expected Output:**
```
INFO: === CT2 Conversion ===
INFO: Converting m2m100_418m...
INFO: Converting models/m2m100_418M -> models/ct2/m2m100_418m__int8
INFO: Conversion completed successfully
INFO: Updating manifest: m2m100_418m__int8_ct2
INFO: ✓ Manifest updated for m2m100_418m__int8_ct2
INFO: Updating registry: m2m100_418m__int8_ct2
INFO: ✓ Registry updated for m2m100_418m__int8_ct2
INFO: ✓ CT2 conversion complete: m2m100_418m__int8_ct2 (480.0MB)

=== Conversion Summary ===
Total: 1
Success: 1
Failed: 0
Total size: 480.0 MB
```

#### 1.3 Verify File Structure

```bash
# Check CT2 directory created
ls -lh models/ct2/

# Expected structure:
# models/ct2/
# └── m2m100_418m__int8/
#     ├── model.bin
#     ├── config.json
#     └── shared_vocabulary.txt (or .json)
```

#### 1.4 Verify CT2 Model Listed

```bash
# List CT2 models again
.venv/Scripts/python -m src.model_runtime.model_cli list-ct2
```

**Expected:**
```
CT2 Model ID                             Status          Path
------------------------------------------------------------------------------------------------------------
Existing CT2 Models:
  ✓ m2m100_418m__int8_ct2                Ready           models/ct2/m2m100_418m__int8

Existing CT2 models: 1
```

#### 1.5 Verify Manifest Entry

```bash
# Check manifest contains CT2 entry
cat models/model_manifest.json | grep -A 10 "m2m100_418m__int8_ct2"
```

**Expected Fields:**
- `model_id`: "m2m100_418m__int8_ct2"
- `local_path`: "models/ct2/m2m100_418m__int8"
- `download_source`: "ct2_conversion:m2m100_418m"
- `backend`: "ctranslate2"
- `verified`: true

#### 1.6 Verify Registry Entry

```bash
# Check if CT2 model in registry
.venv/Scripts/python -c "
from src.model_runtime import ModelRegistry
registry = ModelRegistry('config/model_registry.yaml')
try:
    model = registry.get_model('m2m100_418m__int8_ct2')
    print(f'Model ID: {model.model_id}')
    print(f'Backend: {model.backend}')
    print(f'Optimal Device: {model.optimal_device}')
    print(f'Size: {model.model_size_mb} MB')
    print(f'Min RAM: {model.min_ram_gb} GB')
except KeyError:
    print('Model not in registry (expected - only in local registry)')
"
```

**Note:** CT2 models are registered in-memory during runtime. To persist, run:

```bash
# Save registry with CT2 model
.venv/Scripts/python -c "
from src.model_runtime import ModelRegistry
from pathlib import Path

registry = ModelRegistry('config/model_registry.yaml')
# CT2 model would be registered during conversion
# For now, check models directory directly
print('Registry models:', len(registry))
"
```

---

## Test Scenario 2: Batch Conversion

### Objective
Convert multiple models at once using `--all-multilingual`.

### Steps

#### 2.1 Plan Conversion

```bash
# Check which models will be converted
# (This would require adding a --plan flag to convert-ct2)
.venv/Scripts/python -m src.model_runtime.model_cli list-ct2 --show-potential
```

#### 2.2 Convert All Multilingual Models

```bash
# Convert m2m100, nllb, small100
.venv/Scripts/python -m src.model_runtime.model_cli convert-ct2 \
    --all-multilingual \
    --quant int8
```

**Expected Output:**
```
INFO: === CT2 Conversion ===
INFO: Converting multilingual models: m2m100_418m, m2m100_1.2b, nllb_distilled_600m, small100

Converting m2m100_418m...
✓ m2m100_418m -> m2m100_418m__int8_ct2 (480.0MB)

Converting m2m100_1.2b...
✓ m2m100_1.2b -> m2m100_1.2b__int8_ct2 (1440.0MB)

Converting nllb_distilled_600m...
✓ nllb_distilled_600m -> nllb_distilled_600m__int8_ct2 (720.0MB)

Converting small100...
✓ small100 -> small100__int8_ct2 (360.0MB)

=== Conversion Summary ===
Total: 4
Success: 4
Failed: 0
Total size: 3000.0 MB
```

#### 2.3 Verify All CT2 Models Created

```bash
# Check directory structure
ls -lh models/ct2/

# Expected:
# m2m100_418m__int8/
# m2m100_1.2b__int8/
# nllb_distilled_600m__int8/
# small100__int8/
```

---

## Test Scenario 3: Translation with CT2 Model

### Objective
Use converted CT2 model for actual content translation.

### Steps

#### 3.1 Create Test Content

```bash
# Create test markdown file
cat > test_ct2_translation.md << 'EOF'
---
title: Test Translation
description: Testing CT2 model translation
---

# Hello World

This is a test document for CT2 model translation.
The quick brown fox jumps over the lazy dog.
EOF
```

#### 3.2 Translate Using CT2 Model (CPU)

```bash
# Translate with CT2 INT8 model on CPU
.venv/Scripts/python -m src.cli translate \
    --src-lang en \
    --tgt-lang fr \
    --device cpu \
    --model-id m2m100_418m__int8_ct2 \
    --input test_ct2_translation.md \
    --output test_ct2_translation.fr.md
```

**Expected:**
- Translation completes successfully
- Output file created: `test_ct2_translation.fr.md`
- French translation of content

#### 3.3 Verify Translation Quality

```bash
# Check translated content
cat test_ct2_translation.fr.md

# Expected:
# - Title and description translated
# - "Hello World" -> "Bonjour le monde"
# - Content translated to French
```

#### 3.4 Compare CT2 vs HuggingFace Performance

```bash
# Benchmark CT2 model
.venv/Scripts/python -m src.cli benchmark \
    --model-id m2m100_418m__int8_ct2 \
    --device cpu \
    --src-lang en \
    --tgt-lang fr \
    --num-samples 100

# Benchmark HuggingFace model
.venv/Scripts/python -m src.cli benchmark \
    --model-id m2m100_418m \
    --device cpu \
    --src-lang en \
    --tgt-lang fr \
    --num-samples 100
```

**Compare:**
- Inference speed (CT2 should be 2-3x faster)
- Memory usage (CT2 should use ~60% RAM)
- Translation quality (should be similar, <1% BLEU difference)

---

## Test Scenario 4: Device-Aware Selection

### Objective
Verify CT2 models can be selected on CUDA (device-aware change).

### Steps

#### 4.1 Test CT2 on CUDA (If Available)

```bash
# Translate with CT2 model on CUDA
.venv/Scripts/python -m src.cli translate \
    --src-lang en \
    --tgt-lang fr \
    --device cuda \
    --model-id m2m100_418m__int8_ct2 \
    --input test_ct2_translation.md \
    --output test_ct2_translation.cuda.fr.md
```

**Before (Old Behavior):**
- Would fail: "Model optimal_device (cpu) doesn't match hardware (cuda)"

**After (New Behavior):**
- Should succeed: CT2 model runs on CUDA
- May have warning: "Using model optimized for cpu on cuda device"

#### 4.2 Benchmark CT2 on CUDA

```bash
# Benchmark CT2 INT8 on CUDA
.venv/Scripts/python -m src.cli benchmark \
    --model-id m2m100_418m__int8_ct2 \
    --device cuda \
    --src-lang en \
    --tgt-lang fr \
    --num-samples 100
```

**Expected:**
- Benchmark runs successfully
- Performance metrics collected
- Shows CT2 INT8 is viable on CUDA (even if not optimal)

---

## Test Scenario 5: Quantization Comparison

### Objective
Compare INT8 vs FLOAT16 quantization quality and performance.

### Steps

#### 5.1 Convert Same Model with Different Quantizations

```bash
# Convert to INT8
.venv/Scripts/python -m src.model_runtime.model_cli convert-ct2 \
    --model m2m100_418m \
    --quant int8 \
    --force

# Convert to FLOAT16
.venv/Scripts/python -m src.model_runtime.model_cli convert-ct2 \
    --model m2m100_418m \
    --quant float16 \
    --force
```

#### 5.2 Verify Both Versions Exist

```bash
ls -lh models/ct2/

# Expected:
# m2m100_418m__int8/    (~480 MB)
# m2m100_418m__float16/ (~800 MB)
```

#### 5.3 Compare Translation Quality

```bash
# Translate with INT8
.venv/Scripts/python -m src.cli translate \
    --model-id m2m100_418m__int8_ct2 \
    --src-lang en --tgt-lang fr \
    --input test_ct2_translation.md \
    --output test_int8.fr.md

# Translate with FLOAT16
.venv/Scripts/python -m src.cli translate \
    --model-id m2m100_418m__float16_ct2 \
    --src-lang en --tgt-lang fr \
    --input test_ct2_translation.md \
    --output test_float16.fr.md

# Compare outputs
diff test_int8.fr.md test_float16.fr.md
```

**Expected:**
- Translations very similar
- Minor wording differences possible
- FLOAT16 may have slightly better quality

---

## Test Scenario 6: Force Reconversion

### Objective
Test `--force` flag to reconvert existing CT2 models.

### Steps

#### 6.1 Attempt Conversion Without Force

```bash
# Try to convert already-converted model
.venv/Scripts/python -m src.model_runtime.model_cli convert-ct2 \
    --model m2m100_418m \
    --quant int8
```

**Expected:**
```
INFO: CT2 model already exists and is valid: models/ct2/m2m100_418m__int8
✓ m2m100_418m -> m2m100_418m__int8_ct2 (480.0MB)
(Skips conversion, returns existing)
```

#### 6.2 Force Reconversion

```bash
# Force reconversion
.venv/Scripts/python -m src.model_runtime.model_cli convert-ct2 \
    --model m2m100_418m \
    --quant int8 \
    --force
```

**Expected:**
```
INFO: Removing existing output directory: models/ct2/m2m100_418m__int8
INFO: Converting models/m2m100_418M -> models/ct2/m2m100_418m__int8
INFO: Conversion completed successfully
✓ m2m100_418m -> m2m100_418m__int8_ct2 (480.0MB)
```

---

## Test Scenario 7: Error Handling

### Objective
Test error conditions and graceful failures.

### Steps

#### 7.1 Convert Non-Existent Model

```bash
.venv/Scripts/python -m src.model_runtime.model_cli convert-ct2 \
    --model nonexistent_model \
    --quant int8
```

**Expected:**
```
ERROR: Source model not found in registry: nonexistent_model
✗ nonexistent_model: Source model not found in registry

=== Conversion Summary ===
Total: 1
Success: 0
Failed: 1
```

#### 7.2 Convert Model Not Downloaded

```bash
# Try to convert model in registry but not downloaded
.venv/Scripts/python -m src.model_runtime.model_cli convert-ct2 \
    --model opus_en_de \
    --quant int8
```

**Expected:**
```
ERROR: Source model not found on disk: models/opus-en-de
✗ opus_en_de: Source model not found on disk

=== Conversion Summary ===
Total: 1
Success: 0
Failed: 1
```

---

## Validation Checklist

After completing all test scenarios, verify:

### File System
- [ ] CT2 models in `models/ct2/<model>__<quant>/` (not scattered)
- [ ] Each CT2 directory contains `model.bin`, `config.json`, vocabulary files
- [ ] Source models remain intact in `models/`
- [ ] No leftover temporary files

### Manifest
- [ ] `models/model_manifest.json` contains all CT2 entries
- [ ] Each entry has `download_source: "ct2_conversion:<source>"`
- [ ] All CT2 models marked `verified: true`
- [ ] File lists accurate and complete

### Registry
- [ ] CT2 models registered with correct `model_id`
- [ ] `backend: "ctranslate2"` for all CT2 models
- [ ] `optimal_device` set appropriately (cpu for int8)
- [ ] `supported_pairs` inherited from source
- [ ] `min_ram_gb` reduced to ~60% of source

### Functionality
- [ ] CT2 models translate correctly
- [ ] CT2 models run on intended device (CPU)
- [ ] CT2 models can run on non-optimal device (CUDA)
- [ ] Performance improvements observed (2-3x faster on CPU)
- [ ] Memory usage reduced (~60% of original)
- [ ] Translation quality acceptable (<1% quality loss)

### CLI Commands
- [ ] `convert-ct2 --model <id>` works
- [ ] `convert-ct2 --all-multilingual` works
- [ ] `convert-ct2 --force` reconverts
- [ ] `list-ct2` shows correct status
- [ ] `list-ct2 --show-potential` shows unconverted models

---

## Expected Results Summary

### Disk Usage (After Full Conversion)

```
models/
├── m2m100_418M/           1,600 MB (source)
├── m2m100_1.2b/           4,800 MB (source)
├── nllb_200_600m/         2,400 MB (source)
├── nllb_200_1.3b/         5,200 MB (source)
└── ct2/
    ├── m2m100_418m__int8/         480 MB (30%)
    ├── m2m100_1.2b__int8/       1,440 MB (30%)
    ├── nllb_200_600m__int8/       720 MB (30%)
    └── nllb_200_1.3b__int8/     1,560 MB (30%)

Total source: 14,000 MB (14 GB)
Total CT2:     4,200 MB ( 4 GB)
Total:        18,200 MB (18 GB)

Savings: 30% of original size per model
```

### Performance Improvements

| Metric | HuggingFace (Original) | CT2 INT8 | Improvement |
|--------|------------------------|----------|-------------|
| Inference Speed (CPU) | 100 tokens/sec | 250 tokens/sec | 2.5x faster |
| Memory Usage | 4.0 GB | 2.4 GB | 40% reduction |
| Model Size | 1,600 MB | 480 MB | 70% reduction |
| Translation Quality | 100% (baseline) | 99.5% | -0.5% (minimal) |

---

## Troubleshooting

### Issue: "ctranslate2 not installed"
**Solution:** `pip install ctranslate2` or `pip install .[gpu]`

### Issue: "Source model not found"
**Solution:** Download model first with `model_cli download --model-id <id>`

### Issue: "Conversion failed"
**Solution:** Check model architecture compatibility with CT2. Some Opus models may not be supported.

### Issue: "Out of memory during conversion"
**Solution:** Use smaller batch size or convert on machine with more RAM.

### Issue: "CT2 model slower than HuggingFace"
**Solution:** CT2 optimized for CPU; ensure running on CPU, not CUDA with INT8.

---

## Cleanup (Optional)

```bash
# Remove CT2 models to free space
rm -rf models/ct2/

# Remove from manifest
.venv/Scripts/python -c "
from src.model_runtime.model_store import ModelManifest
from pathlib import Path

manifest = ModelManifest(Path('models/model_manifest.json'))
# Manual cleanup would require manifest API extension
print('Cleanup would remove CT2 entries from manifest')
"
```

---

**Test Plan Status:** Ready for execution
**Prerequisites:** ctranslate2 installed, models downloaded
**Estimated Time:** 30-60 minutes (depending on model sizes)
**Risk Level:** Low (conversions are isolated, source models unchanged)
