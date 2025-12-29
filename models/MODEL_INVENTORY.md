# Model Inventory

This document tracks all downloaded translation models for the Hugo Translation System.

**Last Updated:** 2025-12-28

## Summary

| Status | Count | Total Size |
|--------|-------|------------|
| ✓ Downloaded | 5 models | ~18 GB |
| 🔄 In Progress | 1 model | ~1.2 GB |
| Total | 6 models | ~19.2 GB |

## Language Coverage

All downloaded models support **all 36 target languages**:
- Arabic (ar), Bulgarian (bg), Catalan (ca), Czech (cs), Danish (da)
- German (de), Greek (el), Spanish (es), Persian (fa), Finnish (fi)
- French (fr), Hebrew (he), Hindi (hi), Croatian (hr), Hungarian (hu)
- Indonesian (id), Italian (it), Japanese (ja), Korean (ko), Lithuanian (lt)
- Latvian (lv), Malay (ms), Dutch (nl), Norwegian (no), Polish (pl)
- Portuguese (pt), Romanian (ro), Russian (ru), Slovak (sk), Serbian (sr)
- Swedish (sv), Thai (th), Turkish (tr), Ukrainian (uk), Vietnamese (vi)
- Chinese (zh)

## Downloaded Models

### 1. NLLB-200 600M (nllb_200_600m)

| Property | Value |
|----------|-------|
| **Status** | ✓ Downloaded |
| **Model ID** | nllb_200_600m |
| **HuggingFace ID** | facebook/nllb-200-distilled-600M |
| **Backend** | HuggingFace Transformers |
| **Size** | 2.3 GB (model.safetensors) |
| **Parameters** | 600M |
| **Languages** | 200+ (including all 36 targets) |
| **Optimal Device** | CUDA/GPU |
| **Min RAM** | 6 GB |
| **License** | CC-BY-NC-4.0 |
| **Local Path** | `models/nllb_200_600m/` |
| **Downloaded** | 2025-12-18 |

**Description:** No Language Left Behind distilled model. Best for low-resource languages. Excellent quality across all 200 languages.

**Files:**
- config.json
- generation_config.json
- model.safetensors (2.3 GB)
- sentencepiece.bpe.model
- tokenizer.json
- special_tokens_map.json
- tokenizer_config.json

---

### 2. NLLB-200 1.3B (nllb_200_1.3b)

| Property | Value |
|----------|-------|
| **Status** | ✓ Downloaded |
| **Model ID** | nllb_200_1.3b |
| **HuggingFace ID** | facebook/nllb-200-1.3B |
| **Backend** | HuggingFace Transformers |
| **Size** | 5.2 GB (two-part model) |
| **Parameters** | 1.3B |
| **Languages** | 200+ (including all 36 targets) |
| **Optimal Device** | CUDA/GPU |
| **Min RAM** | 10 GB |
| **License** | CC-BY-NC-4.0 |
| **Local Path** | `models/nllb_200_1.3b/` |
| **Downloaded** | 2025-12-19 |

**Description:** Larger NLLB model with excellent quality for 200 languages. Best quality option for low-resource languages.

**Files:**
- config.json
- generation_config.json
- model-00001-of-00002.safetensors (4.7 GB)
- model-00002-of-00002.safetensors (461 MB)
- model.safetensors.index.json
- sentencepiece.bpe.model
- tokenizer.json
- special_tokens_map.json
- tokenizer_config.json

---

### 3. M2M100 418M (m2m100_418m)

| Property | Value |
|----------|-------|
| **Status** | ✓ Downloaded |
| **Model ID** | m2m100_418m |
| **HuggingFace ID** | facebook/m2m100_418M |
| **Backend** | HuggingFace Transformers |
| **Size** | 1.9 GB (pytorch_model.bin) |
| **Parameters** | 418M |
| **Languages** | 100 (including all 36 targets) |
| **Optimal Device** | CUDA/GPU |
| **Min RAM** | 4 GB |
| **License** | MIT |
| **Local Path** | `models/m2m100_418M/` |
| **Downloaded** | 2025-12-16 |

**Description:** Multilingual translation model from Facebook. Supports 100 languages with good quality. Efficient baseline model.

**Storage Format:** HuggingFace cache with symlinks to blobs
**Files:**
- models--facebook--m2m100_418M/snapshots/{hash}/
  - config.json
  - generation_config.json
  - pytorch_model.bin (1.9 GB)
  - sentencepiece.bpe.model
  - vocab.json
  - special_tokens_map.json
  - tokenizer_config.json

---

### 4. M2M100 1.2B (m2m100_1.2b)

| Property | Value |
|----------|-------|
| **Status** | ✓ Downloaded |
| **Model ID** | m2m100_1.2b |
| **HuggingFace ID** | facebook/m2m100_1.2B |
| **Backend** | HuggingFace Transformers |
| **Size** | 4.7 GB (model.safetensors) |
| **Parameters** | 1.2B |
| **Languages** | 100 (including all 36 targets) |
| **Optimal Device** | CUDA/GPU |
| **Min RAM** | 8 GB |
| **License** | MIT |
| **Local Path** | `models/m2m100_1.2b/` |
| **Downloaded** | 2025-12-18 |

**Description:** Larger M2M100 model with higher quality. Requires good GPU for optimal performance.

**Files:**
- config.json
- generation_config.json
- model.safetensors (4.7 GB)
- sentencepiece.bpe.model
- added_tokens.json
- vocab.json
- special_tokens_map.json
- tokenizer_config.json

---

### 5. Small-100 300M (small100)

| Property | Value |
|----------|-------|
| **Status** | 🔄 Downloading |
| **Model ID** | small100 |
| **HuggingFace ID** | alirezamsh/small100 |
| **Backend** | HuggingFace Transformers |
| **Size** | ~1.2 GB (estimated) |
| **Parameters** | 300M |
| **Languages** | 100 (including all 36 targets) |
| **Optimal Device** | CPU |
| **Min RAM** | 3 GB |
| **License** | MIT |
| **Local Path** | `models/small100/` (pending) |
| **Download Started** | 2025-12-28 |

**Description:** Compact multilingual model. Good balance of size and quality, optimized for CPU inference.

**Expected Files:**
- config.json
- pytorch_model.bin or model.safetensors
- tokenizer files
- sentencepiece.bpe.model

---

## Model Selection Guide

### For Benchmarking All 36 Languages

| Use Case | Recommended Model | Size | Device |
|----------|-------------------|------|--------|
| **Baseline Performance** | m2m100_418m | 1.9 GB | CPU/GPU |
| **Best Quality (Low-Resource)** | nllb_200_1.3b | 5.2 GB | GPU |
| **CPU-Optimized** | small100 | 1.2 GB | CPU |
| **GPU-Optimized (Medium)** | m2m100_1.2b | 4.7 GB | GPU |
| **GPU-Optimized (Best)** | nllb_200_1.3b | 5.2 GB | GPU |

### Model Size Comparison

```
small100         ▓▓▓▓▓▓░░░░░░░░░░░░░░  1.2 GB (300M params)
m2m100_418m      ▓▓▓▓▓▓▓▓░░░░░░░░░░░░  1.9 GB (418M params)
nllb_200_600m    ▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░  2.3 GB (600M params)
m2m100_1.2b      ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░  4.7 GB (1.2B params)
nllb_200_1.3b    ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓  5.2 GB (1.3B params)
```

## Planned Models (Not Yet Downloaded)

### Specialized Models (Optional)

| Model ID | HF ID | Size | Languages | Priority |
|----------|-------|------|-----------|----------|
| opus_en_fr | Helsinki-NLP/opus-mt-en-fr | 300 MB | en↔fr | Medium |
| opus_en_es | Helsinki-NLP/opus-mt-en-es | 300 MB | en↔es | Medium |
| opus_en_de | Helsinki-NLP/opus-mt-en-de | 300 MB | en↔de | Medium |
| marian_en_romance | Helsinki-NLP/opus-mt-en-ROMANCE | 300 MB | en→{fr,es,it,pt,ro} | Medium |

**Note:** Specialized models provide faster inference for specific pairs but don't cover all 36 languages.

### CTranslate2 Models (Require Conversion)

| Model ID | Source | Size | Notes |
|----------|--------|------|-------|
| m2m100_418m_ct2 | m2m100_418m | ~800 MB | 2x faster, 50% less memory |
| m2m100_418m_ct2_int8 | m2m100_418m | ~250 MB | INT8 quantized, ~1% quality trade-off |
| nllb_200_600m_ct2_int8 | nllb_200_600m | ~350 MB | INT8 quantized, <0.5% quality trade-off |

**Note:** CTranslate2 models must be converted from HuggingFace models using `ct2-transformers-converter`.

## Disk Usage

```bash
# Check current disk usage
du -sh models/*

# Expected total after small100 download: ~19.2 GB
```

## Download Commands

### Download Individual Model
```bash
python scripts/download_models.py --model <model_id> --models-dir models
```

### Download All Models
```bash
python scripts/download_models.py --all --models-dir models
```

### Force Re-download
```bash
python scripts/download_models.py --model <model_id> --models-dir models --force
```

## Verification

### Check Model Files
```bash
# NLLB-200 600M
ls -lh models/nllb_200_600m/

# M2M100 418M
ls -lh models/m2m100_418M/models--facebook--m2m100_418M/snapshots/*/

# M2M100 1.2B
ls -lh models/m2m100_1.2b/

# NLLB-200 1.3B
ls -lh models/nllb_200_1.3b/

# Small-100
ls -lh models/small100/
```

### Test Model Loading
```python
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

# Test NLLB-200 600M
model = AutoModelForSeq2SeqLM.from_pretrained("models/nllb_200_600m")
tokenizer = AutoTokenizer.from_pretrained("models/nllb_200_600m")

# Test M2M100 418M
model = AutoModelForSeq2SeqLM.from_pretrained("facebook/m2m100_418M", cache_dir="models/m2m100_418M")
tokenizer = AutoTokenizer.from_pretrained("facebook/m2m100_418M", cache_dir="models/m2m100_418M")
```

## Benchmarking Strategy

### Phase 1: CPU Benchmarking (All Models)
- Run all 5 models on CPU for all 36 languages
- Measure: throughput (tok/s), latency, memory usage
- Expected runtime: ~24-36 hours

### Phase 2: GPU Benchmarking (GPU-Optimized Models)
- Run GPU-optimized models (nllb_200_600m, nllb_200_1.3b, m2m100_1.2b) on CUDA
- Compare GPU speedup vs CPU baseline
- Expected runtime: ~12-18 hours

### Phase 3: Quality Benchmarking
- Use reference corpus from `config/benchmark_corpus.yaml`
- Calculate BLEU, chrF, COMET scores
- Compare quality vs speed trade-offs

## Notes

- All models support English → [target language] translation
- NLLB-200 models excel at low-resource languages (ar, he, hi, th, vi)
- M2M100 models are MIT licensed (more permissive)
- CTranslate2 conversions should be done after initial benchmarking
- Keep at least 20 GB free disk space for model operations

## Changelog

### 2025-12-28
- Initial inventory created
- 4 models verified as downloaded (m2m100_418m, m2m100_1.2b, nllb_200_600m, nllb_200_1.3b)
- Started download of small100 model
- Total storage: ~18 GB → ~19.2 GB after small100

### 2025-12-18 to 2025-12-19
- Downloaded nllb_200_600m, m2m100_1.2b, nllb_200_1.3b

### 2025-12-16
- Downloaded m2m100_418m
