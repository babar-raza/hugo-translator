# Benchmarking Coverage Requirements Specification

**Version:** 1.0
**Status:** Production-Ready
**Last Updated:** 2025-12-28
**Parent:** [REQUIREMENTS.md](../REQUIREMENTS.md)

## Executive Summary

This specification defines the comprehensive coverage requirements for the benchmarking system, ensuring that all 36 languages, all available models, and both CPU and GPU execution modes are thoroughly tested and measured.

## Table of Contents

1. [Coverage Dimensions](#coverage-dimensions)
2. [Language Coverage](#language-coverage)
3. [Model Coverage](#model-coverage)
4. [Device Coverage](#device-coverage)
5. [Metrics Collection](#metrics-collection)
6. [Quality Dimensions](#quality-dimensions)
7. [Acceptance Criteria](#acceptance-criteria)
8. [Implementation Guidance](#implementation-guidance)

---

## Coverage Dimensions

The benchmarking system MUST provide complete coverage across three orthogonal dimensions:

```
Coverage Matrix = Languages × Models × Devices
                = 36 × N_models × 2 (CPU + GPU)
```

### Minimum Coverage Requirements

**Total Benchmark Runs Required:**
- **Minimum:** 36 languages × 4 models × 2 devices = **288 benchmark runs**
- **Recommended:** 36 languages × 10 models × 2 devices = **720 benchmark runs**

**Per Benchmark Run:**
- Minimum 100 segments translated
- Both cached and uncached scenarios
- Full metrics collection (see [Metrics Collection](#metrics-collection))

---

## Language Coverage

### LANG-001: All 36 Target Languages
**Priority:** P0 (Critical)

Every benchmark run MUST include results for all 36 target languages:

```yaml
required_languages:
  - ar  # Arabic
  - bg  # Bulgarian
  - ca  # Catalan
  - cs  # Czech
  - da  # Danish
  - de  # German
  - el  # Greek
  - es  # Spanish
  - fa  # Persian (Farsi)
  - fi  # Finnish
  - fr  # French
  - he  # Hebrew
  - hi  # Hindi
  - hr  # Croatian
  - hu  # Hungarian
  - id  # Indonesian
  - it  # Italian
  - ja  # Japanese
  - ko  # Korean
  - lt  # Lithuanian
  - lv  # Latvian
  - ms  # Malay
  - nl  # Dutch
  - no  # Norwegian
  - pl  # Polish
  - pt  # Portuguese
  - ro  # Romanian
  - ru  # Russian
  - sk  # Slovak
  - sr  # Serbian
  - sv  # Swedish
  - th  # Thai
  - tr  # Turkish
  - uk  # Ukrainian
  - vi  # Vietnamese
  - zh  # Chinese
```

### Language Script Diversity

Benchmarks MUST cover diverse script families:

| Script Family | Languages | Count |
|---------------|-----------|-------|
| Latin | es, fr, de, it, pt, nl, pl, cs, hr, da, fi, hu, id, lt, lv, ms, no, ro, sk, sr, sv, tr, vi, ca | 24 |
| Cyrillic | ru, bg, uk, sr | 4 |
| Arabic | ar, fa | 2 |
| CJK | zh, ja, ko | 3 |
| Indic | hi | 1 |
| Greek | el | 1 |
| Hebrew | he | 1 |

**Rationale:** Script diversity tests tokenization, character encoding, and right-to-left (RTL) rendering.

---

## Model Coverage

### MOD-001: All Registered Models
**Priority:** P0 (Critical)

Every model in `config/model_registry.yaml` MUST be benchmarked for all 36 languages.

**Current Model List (as of 2025-12-28):**

| Model ID | Type | Languages Supported | Benchmark Priority |
|----------|------|---------------------|-------------------|
| `m2m100_418m` | Multilingual | All 36 | P0 (Default model) |
| `m2m100_418m_ct2` | Multilingual (Optimized) | All 36 | P0 |
| `m2m100_418m_ct2_int8` | Multilingual (Quantized) | All 36 | P0 |
| `nllb_200_600m_ct2_int8` | Multilingual (Quantized) | All 36 | P0 |
| `m2m100_1.2b` | Multilingual | All 36 | P1 |
| `nllb_200_600m` | Multilingual | All 36 | P1 |
| `nllb_200_1.3b` | Multilingual | All 36 | P1 |
| `opus_en_fr` | Specialized (FR only) | fr | P2 |
| `opus_en_es` | Specialized (ES only) | es | P2 |
| `opus_en_de` | Specialized (DE only) | de | P2 |
| `marian_en_romance` | Multi-pair | fr, es, it, pt, ro | P2 |
| `small100` | Multilingual | All 36 | P2 |

**Benchmark Execution Strategy:**
1. P0 models: Benchmark immediately after download
2. P1 models: Benchmark during off-peak hours
3. P2 models: Benchmark on-demand or weekly batch

### MOD-002: Model-Specific Language Coverage

Specialized models (Opus, Marian) MUST only be benchmarked for their supported language pairs:

**Example:**
- `opus_en_fr`: Benchmark EN→FR only (1 language)
- `marian_en_romance`: Benchmark EN→{fr, es, it, pt, ro} (5 languages)

**Validation Rule:**
```python
def validate_model_language_coverage(model_id, language):
    model = registry.get_model(model_id)
    if model.supported_pairs == "all":
        return True  # Multilingual model
    else:
        return ("en", language) in model.supported_pairs
```

---

## Device Coverage

### DEV-001: CPU and GPU Benchmarking
**Priority:** P0 (Critical)

Every model MUST be benchmarked on both CPU and GPU (if GPU is available).

**Device Detection:**
```python
import torch

def get_available_devices():
    devices = ["cpu"]
    if torch.cuda.is_available():
        devices.append("cuda")
    return devices
```

**Fallback Behavior:**
- If GPU unavailable: Run CPU-only benchmarks, log warning
- If GPU fails (OOM, driver error): Fall back to CPU, record error

### DEV-002: Device-Specific Metrics

Metrics MUST be tagged with device type:

| Metric | CPU | GPU |
|--------|-----|-----|
| Memory Usage | System RAM (MB) | VRAM (MB) + System RAM (MB) |
| Throughput | Segments/sec | Segments/sec |
| Latency P50 | Milliseconds | Milliseconds |
| Latency P95 | Milliseconds | Milliseconds |
| Device Temperature | CPU temp (°C) | GPU temp (°C) |

**Database Schema:**
```sql
CREATE TABLE benchmark_runs (
    id INTEGER PRIMARY KEY,
    model_id TEXT NOT NULL,
    language TEXT NOT NULL,
    device TEXT NOT NULL,  -- "cpu" or "cuda"
    ...
);
```

### DEV-003: GPU Memory Profiling

For GPU benchmarks, MUST collect:
- Peak VRAM usage (MB)
- VRAM allocation timeline
- CUDA kernel execution time
- GPU utilization percentage

**Implementation:**
```python
import nvidia_smi

nvidia_smi.nvmlInit()
handle = nvidia_smi.nvmlDeviceGetHandleByIndex(0)

# During benchmark
info = nvidia_smi.nvmlDeviceGetMemoryInfo(handle)
vram_used_mb = info.used / 1024 / 1024
```

---

## Metrics Collection

### MET-001: Required Metrics

Every benchmark run MUST collect the following metrics:

#### Performance Metrics
| Metric | Unit | Definition |
|--------|------|------------|
| `throughput` | segments/sec | Total segments / total time |
| `latency_p50` | milliseconds | Median translation time per segment |
| `latency_p95` | milliseconds | 95th percentile translation time |
| `latency_p99` | milliseconds | 99th percentile translation time |
| `total_duration` | seconds | End-to-end benchmark duration |

#### Resource Metrics
| Metric | Unit | Definition |
|--------|------|------------|
| `peak_memory_mb` | megabytes | Maximum RAM usage during benchmark |
| `peak_vram_mb` | megabytes | Maximum VRAM usage (GPU only) |
| `avg_cpu_percent` | percent | Average CPU utilization |
| `avg_gpu_percent` | percent | Average GPU utilization (GPU only) |

#### Quality Metrics
| Metric | Unit | Definition |
|--------|------|------------|
| `bleu_score` | 0-100 | Translation quality (if reference available) |
| `cache_hit_rate` | percent | TM cache hits / total segments |
| `error_count` | count | Number of failed translations |

#### Context Metrics
| Metric | Type | Definition |
|--------|------|------------|
| `model_id` | string | Model identifier from registry |
| `language` | string | ISO 639-1 language code |
| `device` | string | "cpu" or "cuda" |
| `timestamp` | datetime | Benchmark start time (ISO 8601) |
| `corpus_version` | string | Version hash of benchmark corpus |
| `segments_translated` | integer | Number of segments in benchmark |

### MET-002: Cached vs Uncached Separation

Metrics MUST be split by cache status:

```sql
CREATE TABLE benchmark_metrics (
    run_id INTEGER REFERENCES benchmark_runs(id),
    cache_status TEXT NOT NULL,  -- "cached" or "uncached"
    throughput REAL,
    latency_p50 REAL,
    ...
);
```

**Example Results:**
| Run | Language | Cache Status | Throughput |
|-----|----------|--------------|------------|
| 1 | fr | uncached | 12.5 seg/sec |
| 1 | fr | cached | 850.0 seg/sec |

---

## Quality Dimensions

### 1. Completeness (5/5)
**Measurement:**
- [ ] All 36 languages benchmarked
- [ ] All registered models benchmarked
- [ ] Both CPU and GPU results present (or logged unavailability)
- [ ] All required metrics collected

**Query to Verify:**
```sql
SELECT COUNT(DISTINCT language) AS langs,
       COUNT(DISTINCT model_id) AS models,
       COUNT(DISTINCT device) AS devices
FROM benchmark_runs;
-- Expected: langs=36, models>=4, devices=2
```

### 2. Correctness (5/5)
**Measurement:**
- [ ] Device labels match actual execution device
- [ ] Cache status correctly separated
- [ ] Language codes are valid ISO 639-1
- [ ] Timestamps are accurate and monotonic

**Validation:**
```python
def validate_benchmark_result(result):
    assert result.language in VALID_ISO_639_1_CODES
    assert result.device in ["cpu", "cuda"]
    assert result.cache_hit_rate >= 0 and result.cache_hit_rate <= 1
    assert result.throughput > 0
```

### 3. Performance (4/5)
**Measurement:**
- [ ] Full benchmark suite (36 langs × 4 models × 2 devices) completes in < 8 hours
- [ ] Individual model benchmark completes in < 30 minutes per language
- [ ] Resource monitoring overhead < 5% of total benchmark time

**Target Timings:**
- M2M100 418M (CPU): ~2 min/language → 72 min total
- M2M100 418M (GPU): ~30 sec/language → 18 min total
- Full suite (288 runs): ~6 hours

### 4. Reliability (5/5)
**Measurement:**
- [ ] Benchmark failures do not corrupt database
- [ ] Partial results are saved (resume support)
- [ ] GPU OOM errors handled gracefully
- [ ] Resource exhaustion triggers pause, not crash

**Error Handling:**
```python
try:
    result = run_benchmark(model, language, device)
    storage.save_result(result)
except torch.cuda.OutOfMemoryError:
    logger.error("GPU OOM, falling back to CPU")
    result = run_benchmark(model, language, "cpu")
    storage.save_result(result)
```

### 5. Traceability (5/5)
**Measurement:**
- [ ] Every benchmark run has unique ID
- [ ] System information recorded (GPU model, CPU cores, RAM)
- [ ] Corpus version tracked
- [ ] Reproducibility: Same corpus + model + device → Same results ±5%

---

## Acceptance Criteria

### Functional Acceptance

1. **Language Coverage**
   - [ ] Database contains results for all 36 languages
   - [ ] No language has zero benchmark results
   - [ ] Script diversity validated (Latin, Cyrillic, CJK, Arabic, etc.)

2. **Model Coverage**
   - [ ] All P0 models benchmarked for all 36 languages
   - [ ] All P1 models benchmarked for all 36 languages
   - [ ] P2 models benchmarked for their supported languages only

3. **Device Coverage**
   - [ ] CPU results present for all models × languages
   - [ ] GPU results present for all models × languages (or unavailable logged)
   - [ ] Device type correctly labeled in results

4. **Metrics Completeness**
   - [ ] All required metrics collected for every run
   - [ ] No NULL values in required metric columns
   - [ ] Cached vs uncached metrics separated

### Non-Functional Acceptance

5. **Performance**
   - [ ] Full benchmark suite completes in < 8 hours
   - [ ] Individual benchmarks time out after 2 hours (safety)

6. **Reliability**
   - [ ] Zero database corruptions in 100 consecutive runs
   - [ ] GPU OOM errors handled without data loss
   - [ ] Resume support: Interrupted benchmarks can continue

7. **Usability**
   - [ ] Single command runs full suite: `python -m src.benchmarking.cli run --all-languages`
   - [ ] Progress bar shows completion percentage
   - [ ] ETA displayed based on historical run times

---

## Implementation Guidance

### Benchmark Runner Architecture

```python
class BenchmarkRunner:
    def run_full_coverage(self):
        """Run benchmarks for all languages, models, devices."""
        languages = get_target_languages()  # 36 languages
        models = registry.get_all_models()
        devices = get_available_devices()  # ["cpu", "cuda"]

        for model in models:
            for language in languages:
                if not model.supports_language(language):
                    continue  # Skip unsupported pairs

                for device in devices:
                    try:
                        self.run_single_benchmark(model, language, device)
                    except Exception as e:
                        logger.error(f"Benchmark failed: {e}")
                        storage.save_error(model, language, device, e)
```

### Database Schema

```sql
-- Main benchmark runs table
CREATE TABLE benchmark_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id TEXT NOT NULL,
    language TEXT NOT NULL,
    device TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    corpus_version TEXT NOT NULL,
    segments_translated INTEGER NOT NULL,
    total_duration_sec REAL NOT NULL,
    throughput REAL NOT NULL,
    peak_memory_mb REAL NOT NULL,
    peak_vram_mb REAL,  -- NULL for CPU runs
    bleu_score REAL,
    error_count INTEGER DEFAULT 0,
    system_info_json TEXT NOT NULL,
    UNIQUE(model_id, language, device, corpus_version)
);

-- Detailed metrics by cache status
CREATE TABLE benchmark_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES benchmark_runs(id),
    cache_status TEXT NOT NULL,  -- "cached" or "uncached"
    segments_count INTEGER NOT NULL,
    throughput REAL NOT NULL,
    latency_p50 REAL NOT NULL,
    latency_p95 REAL NOT NULL,
    latency_p99 REAL NOT NULL
);

-- System information snapshot
CREATE TABLE system_info (
    run_id INTEGER PRIMARY KEY REFERENCES benchmark_runs(id),
    cpu_model TEXT,
    cpu_cores INTEGER,
    ram_total_mb INTEGER,
    gpu_model TEXT,
    vram_total_mb INTEGER,
    cuda_version TEXT,
    pytorch_version TEXT,
    os_platform TEXT
);

-- Index for fast queries
CREATE INDEX idx_runs_model_lang_device ON benchmark_runs(model_id, language, device);
CREATE INDEX idx_metrics_run_cache ON benchmark_metrics(run_id, cache_status);
```

### CLI Commands

```bash
# Run full coverage benchmarks
python -m src.benchmarking.cli run --all-languages

# Run specific language
python -m src.benchmarking.cli run --language fr

# Run specific model
python -m src.benchmarking.cli run --model m2m100_418m

# Run CPU-only
python -m src.benchmarking.cli run --device cpu

# Run with custom corpus
python -m src.benchmarking.cli run --corpus config/custom_corpus.yaml

# Query results
python -m src.benchmarking.cli compare \
    --model m2m100_418m \
    --language fr \
    --device gpu \
    --format json
```

---

## Constraints and Edge Cases

### Resource Constraints

1. **GPU Memory Limits**
   - Large models (>1.2B params) may OOM on GPUs with <8GB VRAM
   - **Mitigation:** Batch size reduction, gradient checkpointing disabled

2. **Disk Space**
   - Benchmark database grows ~10MB per 1000 runs
   - **Mitigation:** Periodic cleanup of old benchmarks, compression

3. **Time Constraints**
   - Full suite (720 runs) may take 12+ hours on CPU-only systems
   - **Mitigation:** Parallel execution, priority-based scheduling

### Edge Cases

1. **Unsupported Language Pairs**
   - Specialized models (opus_en_fr) don't support all 36 languages
   - **Handling:** Skip with logged warning, do not mark as failure

2. **Cache Contamination**
   - Warm cache from previous runs affects "uncached" benchmarks
   - **Mitigation:** Flush TM before each benchmark run

3. **Thermal Throttling**
   - Prolonged GPU benchmarks trigger thermal limits
   - **Mitigation:** Monitor GPU temp, pause if >85°C, resume after cooldown

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-12-28 | System | Initial specification |

---

## Related Specifications

- [REQUIREMENTS.md](../REQUIREMENTS.md) - Parent requirements document
- [DATA_SOURCES.md](DATA_SOURCES.md) - Benchmark corpus definition
- [UI_DASHBOARD.md](UI_DASHBOARD.md) - Results visualization
- [36_LANGUAGE_COVERAGE.md](../models/36_LANGUAGE_COVERAGE.md) - Language pair model mapping
