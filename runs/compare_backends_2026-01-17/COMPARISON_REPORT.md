# Model & Backend Comparison Report

**Date**: 2026-01-17
**Test Set**: docs.aspose.net slides content (en → fr)
**Max Files**: 15
**Device**: CUDA (RTX 4090)

---

## Executive Summary

Tested three configurations to compare model and backend performance:
1. **m2m100_418m** (HuggingFace, CUDA, batch=32)
2. **opus_en_fr** (HuggingFace, CUDA, batch=32) - Previous E2E winner
3. **CT2 backend** - NOT AVAILABLE (ctranslate2 not installed)

**Winner**: `opus_en_fr` with **6.4x faster throughput** than m2m100_418m

---

## Test Results

### 1. m2m100_418m (HuggingFace Backend)

**Configuration**:
- Model: facebook/m2m100_418M (418M parameters)
- Backend: HuggingFace Transformers
- Device: CUDA
- Batch size: 32
- Speed mode: True (use_cache=True, num_beams=1)

**Performance**:
- Total segments: 292
- Duration: 257.09 seconds
- **Throughput: 1.14 seg/sec**
- Files processed: 15/15 (100% success)
- Failures: 0

**Observations**:
- Multiline batching working: `MSP-02: backend_calls=1` confirmed
- AST batch translation: 4 batches, 100% success
- Larger model (418M params) → slower inference
- Good for multilingual support (100 languages)

---

### 2. opus_en_fr (HuggingFace Backend)

**Configuration**:
- Model: Helsinki-NLP/opus-mt-en-fr (77M parameters)
- Backend: HuggingFace Transformers
- Device: CUDA
- Batch size: 32
- Speed mode: True

**Performance** (from previous E2E):
- Total segments: 329
- Duration: 44.82 seconds
- **Throughput: 7.34 seg/sec**
- Files processed: 15/15 (100% success)
- Failures: 0

**Observations**:
- 5.4x smaller model (77M vs 418M parameters)
- 6.4x faster throughput (7.34 vs 1.14 seg/sec)
- Specialized for en↔fr translation
- Peak VRAM: 312 MB (very efficient)

---

### 3. CTranslate2 Backend

**Status**: ❌ NOT AVAILABLE

**Error**:
```
ModuleNotFoundError: No module named 'ctranslate2'
```

**Required Action**: Install ctranslate2 to enable CT2 backend tests
```bash
pip install ctranslate2
```

**Expected Benefits** (if available):
- 2-4x faster inference (INT8 quantization)
- 50-75% less memory usage
- CPU-optimized execution
- Model size reduction (418M → ~100-200 MB)

**Conversion Path**:
```python
from src.model_runtime.ct2_converter import CT2ConversionPipeline
pipeline = CT2ConversionPipeline()
pipeline.convert_model(
    'models/m2m100_418M/models--facebook--m2m100_418M/snapshots/<hash>',
    'models/ct2/m2m100_418m_int8',
    quantization='int8'
)
```

---

## Detailed Comparison

| Metric | m2m100_418m (HF) | opus_en_fr (HF) | Delta |
|---|---:|---:|---:|
| **Throughput (seg/sec)** | 1.14 | 7.34 | **+544%** |
| **Duration (seconds)** | 257.09 | 44.82 | -82.6% |
| **Segments/min** | 68.2 | 440.4 | +545% |
| **Model size (params)** | 418M | 77M | -82% |
| **Peak VRAM (MB)** | ~1886 | 312 | -83% |
| **Language pairs** | 100+ | en↔fr only | - |
| **Files processed** | 15 | 15 | - |
| **Success rate** | 100% | 100% | - |

---

## Performance Analysis

### Why opus_en_fr is 6.4x Faster

1. **Model Size**: 77M params vs 418M → Less compute per token
2. **Vocabulary**: Specialized en-fr vocabulary → Smaller output space
3. **Architecture**: Optimized for single language pair
4. **Memory Efficiency**: Lower VRAM usage → Better GPU utilization

### When to Use Each Model

**Use opus_en_fr when**:
- ✅ Translating English ↔ French only
- ✅ Speed is critical (7+ seg/sec)
- ✅ Limited GPU memory (<500 MB)
- ✅ Production workloads with high volume

**Use m2m100_418m when**:
- ✅ Need 100+ language support
- ✅ Quality is more important than speed
- ✅ Multi-language translation in same pipeline
- ✅ Sufficient GPU memory (2+ GB)

---

## Bottleneck Status (Post-Fix)

All critical bottlenecks remain fixed for both models:

| Bottleneck | Status | Evidence |
|---|---|---|
| **Multiline batching** | ✅ FIXED | `MSP-02: backend_calls=1` in logs |
| **KV cache** | ✅ ENABLED | `use_cache=True`, speed_mode=True |
| **GPU cache clearing** | ✅ OPTIMIZED | Only on OOM/unload, not success path |

Both models benefit equally from these optimizations.

---

## Recommendations

### Immediate Actions

1. **Production Deployment**:
   - Use `opus_en_fr` for en↔fr translation (7.34 seg/sec)
   - Use `m2m100_418m` only for other language pairs

2. **CT2 Backend** (Future):
   - Install ctranslate2: `pip install ctranslate2`
   - Convert m2m100_418m to CT2 INT8 format
   - Re-test with expected 2-4x speedup (target: 2-4 seg/sec)
   - Lower memory footprint for CPU deployments

3. **Model Organization**:
   ```
   models/
   ├── huggingface/              # HF models cache
   │   ├── m2m100_418M/
   │   └── opus-mt-en-fr/
   ├── ct2/                      # CT2 converted models
   │   ├── m2m100_418m_int8/     # Target: 2-4 seg/sec
   │   └── nllb_200_600m_int8/   # Target: 1-2 seg/sec
   └── cache/                    # Temporary cache
   ```

### Future Benchmarks

1. **Additional Opus Models**:
   - opus-mt-en-es (Spanish)
   - opus-mt-en-de (German)
   - Expected: Similar 7+ seg/sec performance

2. **CT2 Benchmark Matrix**:
   - m2m100_418m_ct2_int8 vs m2m100_418m (HF)
   - nllb_200_600m_ct2_int8 performance
   - CPU vs CUDA for CT2 models

3. **Quality Validation**:
   - BLEU/COMET scores for opus vs m2m100
   - Terminology preservation accuracy
   - Production quality gates

---

## Commands Used

### m2m100_418m (HF) Test
```bash
.venv/Scripts/python.exe -m src.cli \
  --site docs.aspose.net \
  --input "D:\onedrive\Documents\GitHub\aspose.net\content\docs.aspose.net\slides\en" \
  --target-langs fr \
  --device cuda \
  --model m2m100_418m \
  --batch-size 32 \
  --log-level INFO \
  --max-files 15 \
  --force-restart \
  --force-retranslate \
  --log-file "runs/compare_backends_2026-01-17/m2m100_hf.log" \
  --no-progress
```

### opus_en_fr (HF) Test
*(Completed in previous E2E run - see `runs/perf_cuda_2026-01-17_12-21/`)*

---

## Environment

- **Platform**: Windows 11
- **GPU**: RTX 4090 Laptop
- **CUDA**: Available ✓
- **ctranslate2**: Not installed ✗
- **Working Dir**: c:\Users\prora\OneDrive\Documents\GitHub\hugo-translator
- **Models Dir**: ./models/

---

## Artifacts

**Location**: `runs/compare_backends_2026-01-17/`

**Files**:
- `COMPARISON_REPORT.md` (this file)
- `m2m100_hf_console.log` (full test output)
- `m2m100_hf.log` (NDJSON telemetry)

**Previous E2E**: `runs/perf_cuda_2026-01-17_12-21/`
- `FINAL_REPORT.md` (comprehensive analysis)
- `leaderboard.md` (3-model benchmark)
- `benchmarks.db` (benchmark data)

---

## Conclusion

**opus_en_fr remains the clear winner** for English-French translation:
- **7.34 seg/sec** throughput (6.4x faster than m2m100_418m)
- **312 MB** peak VRAM (83% less than m2m100_418m)
- **100% success rate** on production data
- **Production-ready** with all bottlenecks fixed

For multilingual support beyond en↔fr, m2m100_418m provides 100+ language coverage at 1.14 seg/sec, which is still **2.9x faster** than the original 0.39 seg/sec baseline.

**Next step**: Install ctranslate2 to unlock 2-4x additional speedup on m2m100 with INT8 quantization.

---

**Report Generated**: 2026-01-17
**Author**: Claude Code
**Test Duration**: ~5 minutes (m2m100 test)
