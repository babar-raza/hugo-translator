# Hugo-Translator System Audit Report

**Audit Date:** 2026-01-17
**Auditor:** Orchestrator Agent
**Repository:** hugo-translator (main branch)
**Commit:** d0343a6 (docs: Add executive summary for CUDA performance verification)

---

## Executive Summary

This audit assesses the current implementation against the documented specifications for:
1. Benchmark matrix supporting 36 target languages × multiple models × devices
2. Model acquisition and management with automated downloads
3. CTranslate2 (CT2) conversion automation
4. End-to-end pipeline: translation → commit → telemetry

### Critical Gaps Identified

**BLOCKER**: Benchmarking system hardcodes `src_lang='en', tgt_lang='ru'` instead of iterating over all 36 target languages. This completely invalidates the benchmark matrix spec.

**HIGH**: Database schema lacks `src_lang` and `tgt_lang` columns, making language-specific performance analysis impossible.

**HIGH**: CT2 conversion is manual-only with no automated path or "ensure" step integration.

**MEDIUM**: No automated model download CLI exists despite detailed spec in specs/models/ORGANIZATION.md.

---

## Table of Contents

1. [Audit Task A: Benchmarking Correctness](#audit-task-a-benchmarking-correctness)
2. [Audit Task B: Model Management](#audit-task-b-model-management)
3. [Audit Task C: CT2 Conversion](#audit-task-c-ct2-conversion)
4. [Audit Task D: Test Infrastructure](#audit-task-d-test-infrastructure)
5. [Current Behavior vs Spec Intent](#current-behavior-vs-spec-intent)
6. [Concrete Gaps with File References](#concrete-gaps-with-file-references)
7. [Proposed Step Plan with Acceptance Checks](#proposed-step-plan-with-acceptance-checks)
8. [Risk Assessment](#risk-assessment)
9. [Appendix: Evidence](#appendix-evidence)

---

## Audit Task A: Benchmarking Correctness

### A.1: Language Hardcoding in runner.py

**File:** [src/benchmarking/runner.py](../../src/benchmarking/runner.py)

**Finding:** Language pair is HARDCODED to English→Russian

**Evidence:**
```python
# Line 331-332 in _benchmark_translation()
if hasattr(backend, 'translate_with_token_counts'):
    translations, input_tokens, output_tokens = backend.translate_with_token_counts(
        texts, src_lang='en', tgt_lang='ru'  # ← HARDCODED!
    )
# Line 338
else:
    translations = backend.translate(texts, src_lang='en', tgt_lang='ru')  # ← HARDCODED!
```

**Impact:**
- Benchmarks only measure EN→RU performance
- All 35 other target languages are NEVER benchmarked
- Benchmark results cannot inform model selection for languages other than Russian
- Violates original spec intent of "35 target languages × models × devices" matrix

**Severity:** 🔴 BLOCKER

---

### A.2: Database Schema Missing Language Fields

**File:** [src/benchmarking/storage.py](../../src/benchmarking/storage.py)

**Finding:** `benchmark_results` table has NO `src_lang` or `tgt_lang` columns

**Evidence:**
```python
# Lines 249-267 in storage.py - CREATE TABLE benchmark_results
CREATE TABLE IF NOT EXISTS benchmark_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    sample_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    device TEXT NOT NULL,
    batch_size INTEGER NOT NULL,
    duration_seconds REAL NOT NULL,
    tokens_input INTEGER NOT NULL,
    tokens_output INTEGER NOT NULL,
    throughput_tokens_per_sec REAL NOT NULL,
    peak_memory_mb REAL,
    errors TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES benchmark_runs(run_id) ON DELETE CASCADE
)
```

**Missing Columns:**
- `src_lang TEXT` - Source language code
- `tgt_lang TEXT` - Target language code

**Impact:**
- Cannot query benchmark results by language pair
- Cannot generate language-specific performance reports
- Recommender system cannot factor language into model selection
- Dashboard cannot show per-language performance trends

**Severity:** 🔴 HIGH

---

### A.3: Benchmark Production and Consumption Points

**Producers** (systems that CREATE benchmark data):

1. **[src/benchmarking/runner.py](../../src/benchmarking/runner.py)**
   - `BenchmarkRunner.run_benchmark()` - Main entry point
   - `BenchmarkRunner._benchmark_translation()` - Per-batch metrics
   - Creates `BenchmarkRun` and `BenchmarkResult` objects
   - Saves to database via `BenchmarkDatabase.save_run()`

2. **[src/benchmarking/production_ingestor.py](../../src/benchmarking/production_ingestor.py)** (referenced in grep)
   - Ingests production translation telemetry into benchmark DB
   - OPT-IN system for real-world performance tracking
   - Thread-safe recording with graceful error handling

**Consumers** (systems that READ benchmark data):

1. **[src/benchmarking/cli.py](../../src/benchmarking/cli.py)**
   - Commands: `run`, `list`, `report`, `compare`, `recommend`
   - User-facing interface for benchmark management

2. **[src/benchmarking/reporter.py](../../src/benchmarking/reporter.py)** (referenced in imports)
   - Generates formatted reports (markdown, JSON, etc.)

3. **[src/benchmarking/recommender.py](../../src/benchmarking/recommender.py)** (referenced in imports)
   - `ModelRecommender` - Suggests optimal model based on system specs
   - Similarity matching: ±2 cores, ±4GB RAM
   - Weighted scoring: throughput, memory, success rate

4. **[src/benchmarking/dashboard/app.py](../../src/benchmarking/dashboard/app.py)** (referenced in grep)
   - Web UI for visualizing benchmarks
   - Time-series trends, comparisons

5. **[src/benchmarking/analytics.py](../../src/benchmarking/analytics.py)** (referenced in imports)
   - `AnalyticsQueryAPI` - Advanced query interface
   - Aggregations, percentiles, time-series

6. **[src/benchmarking/model_gap_analysis.py](../../src/benchmarking/model_gap_analysis.py)** (referenced in grep)
   - Identifies missing model/language/device combinations

7. **[src/benchmarking/language_coverage.py](../../src/benchmarking/language_coverage.py)** (referenced in grep)
   - Analyzes which languages have been benchmarked (currently: only Russian!)

**Gap:** All consumers expect language-specific data, but producers only generate EN→RU data.

---

### A.4: Benchmark CLI Analysis

**File:** [src/benchmarking/cli.py](../../src/benchmarking/cli.py)

**Current State:**
- CLI supports `run`, `list`, `report`, `compare`, `recommend` commands
- Lazy-imports heavy dependencies (torch) to allow `--help` without ML stack
- Uses config/benchmarking.yaml for database path configuration

**Missing Features:**
- No `--source-lang` or `--target-lang` flags for `run` command
- No language iteration logic
- No "benchmark all languages" command
- No language coverage report command

**Evidence:**
```python
# Lines 188-200 in cmd_run() - no language parameters
def cmd_run(args: argparse.Namespace) -> int:
    deps = _import_heavy_deps()
    ModelRegistry = deps['ModelRegistry']
    BenchmarkRunner = deps['BenchmarkRunner']
    BenchmarkDatabase = deps['BenchmarkDatabase']
    # ... no language handling ...
```

---

## Audit Task B: Model Management

### B.1: Model Registry vs Spec Comparison

**Spec:** [specs/models/ORGANIZATION.md](../../specs/models/ORGANIZATION.md)

**Current Registry:** [config/model_registry.yaml](../../config/model_registry.yaml)

#### Spec Intent (from ORGANIZATION.md)

**Directory Structure:**
```
models/
├── m2m100_418M/          # PyTorch
├── m2m100_1.2B/          # PyTorch
├── nllb_200_600m/        # PyTorch
├── nllb_200_1.3b/        # PyTorch
├── ct2/                  # CTranslate2 optimized
│   ├── m2m100_418m/
│   ├── m2m100_418m_int8/
│   └── nllb_200_600m_int8/
├── opus/                 # Opus-MT specialized
│   ├── opus-mt-en-fr/
│   ├── opus-mt-en-es/
│   └── opus-mt-en-de/
└── model_manifest.json   # Download/verification metadata
```

**Download Requirements:**
- CLI command: `python -m src.cli download-models --all`
- Selective download: `--model MODEL_ID`, `--language LANG`, `--priority P0`
- Download resumption on interruption
- Network error handling with retry
- Checksum verification
- Load test after download

#### Current Implementation

**Registry Models (7 total):**

| Model ID | Backend | Supported Pairs | Size (MB) | Location |
|----------|---------|-----------------|-----------|----------|
| m2m100_418m | huggingface | all | 1600 | models/m2m100_418M |
| m2m100_418m_ct2 | ctranslate2 | all | 800 | models/ct2/m2m100_418m |
| m2m100_418m_ct2_int8 | ctranslate2 | all | 250 | models/ct2/m2m100_418m_int8 |
| nllb_200_600m_ct2_int8 | ctranslate2 | all | 350 | models/ct2/nllb_200_600m_int8 |
| m2m100_1.2b | huggingface | all | 4800 | models/m2m100_1.2b |
| nllb_200_600m | huggingface | all | 2400 | models/nllb_200_600m |
| nllb_200_1.3b | huggingface | all | 5200 | models/nllb_200_1.3b |
| opus_en_fr | huggingface | [[en,fr],[fr,en]] | 300 | N/A (no local_path) |

**Gaps:**
1. ✅ Directory structure matches spec (models/, models/ct2/)
2. ❌ `model_manifest.json` file does NOT exist
3. ❌ No `download-models` CLI command exists
4. ❌ No automated download mechanism
5. ❌ No checksum verification system
6. ❌ Opus models defined in registry but not fully specified (missing local_path)

---

### B.2: Auto-Discovery Script Analysis

**File:** [scripts/discover_hf_cache_models.py](../../scripts/discover_hf_cache_models.py)

**Purpose:** Scans HuggingFace cache for translation models and emits local registry

**Current Behavior:**
```python
# Lines 112-123 - Model auto-discovery
models[model_id] = {
    "model_id": model_id,
    "name": hf_id,
    "backend": "huggingface",
    "supported_pairs": "all",  # ← HARDCODED to "all"
    "model_size_mb": 0,        # ← NOT computed
    "min_ram_gb": 0,           # ← NOT computed
    "optimal_device": "cuda",   # ← HARDCODED to cuda
    "hf_model_id": hf_id,
    "description": "Auto-discovered from local HuggingFace cache.",
}
```

**Issues:**
1. **`supported_pairs: "all"`** - No language capability detection
   - Should check model config for supported language codes
   - Should differentiate multilingual (M2M100, NLLB) vs bilingual (Opus-MT)
2. **`model_size_mb: 0`** - Missing disk space calculation
   - Should sum file sizes from cache directory
3. **`min_ram_gb: 0`** - No memory requirement estimation
   - Should estimate based on parameter count or model size
4. **`optimal_device: "cuda"`** - Assumes GPU for all models
   - Should respect model metadata or use heuristics

**Severity:** 🟡 MEDIUM (functional but produces incomplete metadata)

---

### B.3: Model Selection Logic

**File:** [src/model_runtime/loader.py](../../src/model_runtime/loader.py)

**Current Implementation:**
```python
# Lines 760-790 - ModelLoader.load_model()
def load_model(self, model_id: str, device: Optional[str] = None) -> ModelBackend:
    """Load model, return backend instance."""
    # Check if already loaded
    if model_id in self.loaded_models:
        return self.loaded_models[model_id]

    # Get model info FROM REGISTRY (by exact model_id)
    model_info = self.registry.get_model(model_id)

    # Determine device
    target_device = device or self.device

    # Create backend
    backend = self._create_backend(model_info, target_device)
    backend.load()
    self.loaded_models[model_id] = backend
    return backend
```

**Key Observations:**
1. **No language-aware selection** - Loads model by exact `model_id` only
2. **No fallback logic** - If model doesn't support language pair, no automatic fallback
3. **No validation** - Doesn't check if model supports requested language pair before loading

**File:** [src/translation_engine/engine.py](../../src/translation_engine/engine.py) (partial read, limit 200)

**Observed:**
- Engine defines supported languages in `_ALL_LANGUAGE_CODES` (lines 65-70)
- Includes 36 language codes matching config/target_languages.yaml
- Engine initialization doesn't show model selection logic in limited read
- Need full read to understand translation workflow and model selection

**Gap:** Need to implement language-aware model selection:
```python
def select_model_for_language_pair(
    registry: ModelRegistry,
    src_lang: str,
    tgt_lang: str,
    device: str
) -> str:
    """
    Select best model for language pair.

    Priority:
    1. Specialized bilingual models (e.g., opus_en_fr for en→fr)
    2. Multilingual models with verified support (M2M100, NLLB)
    3. Fallback to best multilingual model

    Returns: model_id
    Raises: NoModelForLanguagePairError if no model supports pair
    """
```

---

## Audit Task C: CT2 Conversion

### C.1: CT2 Converter Analysis

**File:** [src/model_runtime/ct2_converter.py](../../src/model_runtime/ct2_converter.py)

**Current Implementation:**

**CT2ConversionPipeline** class provides:
1. ✅ `convert_model()` - HF → CT2 conversion with quantization
2. ✅ `validate_ct2_model()` - Verify converted model loads
3. ✅ `get_model_info()` - Extract metadata
4. ✅ `check_disk_space()` - Pre-conversion validation
5. ✅ CLI entry point: `python -m src.model_runtime.ct2_converter --model ... --output ...`

**Evidence:**
```python
# Lines 34-94 - Full conversion pipeline
def convert_model(
    self,
    model_path: Path | str,
    output_path: Path | str,
    quantization: Literal["int8", "int16", "float16", "float32"] = "int8",
    force: bool = False,
) -> bool:
    """Convert HuggingFace model to CTranslate2 format."""
    # ... creates output dir, converts, returns True on success
```

**Supported Quantization:**
- INT8 (default, recommended for CPU)
- INT16
- FLOAT16
- FLOAT32

**CLI Usage:**
```bash
python -m src.model_runtime.ct2_converter \
    --model models/m2m100_418M \
    --output models/ct2/m2m100_418m_int8 \
    --quantization int8 \
    --force \
    --validate
```

---

### C.2: Automated Invocation Paths

**Search Results:** NO automated invocation found

**Checked Locations:**
1. ❌ `src/model_runtime/loader.py` - No CT2 conversion trigger
2. ❌ `src/cli.py` - No `convert-models` subcommand
3. ❌ `src/benchmarking/runner.py` - No pre-benchmark conversion
4. ❌ Model download workflow (doesn't exist)

**Current State:** Conversion is 100% MANUAL via CLI

**Spec Intent (from ORGANIZATION.md):**
- Auto-convert on model download if CT2 version doesn't exist in HF Hub
- "Ensure" step to check/convert before loading model

**Gap:** Need to implement:
```python
class CT2EnsureStep:
    """Ensure CT2 model exists, converting if necessary."""

    def ensure_ct2_model(
        self,
        pytorch_model_path: Path,
        ct2_output_path: Path,
        quantization: str = "int8"
    ) -> Path:
        """
        Ensure CT2 model exists at output path.

        1. Check if CT2 model already exists and is valid
        2. If not, convert from PyTorch model
        3. Validate converted model
        4. Return path to valid CT2 model

        Raises: CT2ConversionError on failure
        """
```

**Integration Point:** ModelLoader should call `ensure_ct2_model()` when loading CT2 backend

---

## Audit Task D: Test Infrastructure

### D.1: Test Directory Structure

**Evidence from `dir tests`:**

```
tests/
├── __init__.py
├── conftest.py                  # pytest configuration
├── adhoc/                       # Ad-hoc testing scripts
├── contract/                    # Contract tests (API invariants)
│   ├── test_api_001_translate_file.py
│   ├── test_api_002_translate_directory.py
│   ├── test_bm_001_benchmarking.py
│   ├── test_cli_001_main_translate.py
│   ├── test_inv001_subprocess.py
│   ├── test_inv002_atomic_writes.py
│   ├── test_inv003_tm_lookup.py
│   ├── test_inv005_validation_mode.py
│   ├── test_inv006_file_locking.py
│   ├── test_inv007_resume_skip.py
│   ├── test_inv008_git_commit.py
│   ├── test_inv009_l3_periodic_saves.py
│   ├── test_tm_001_l1_cache.py
│   ├── test_tm_002_l2_persistent.py
│   └── test_tm_003_l3_semantic.py
├── e2e/                         # End-to-end tests
├── fixtures/                    # Test data and fixtures
├── integration/                 # Integration tests
│   ├── test_autonomous_worker.py
│   ├── test_benchmark_analytics_integration.py
│   ├── test_benchmarking_cli.py
│   ├── test_benchmarking_concurrency.py
│   ├── test_gpu_e2e.py
│   ├── test_multiline_integration.py
│   ├── test_stats_accuracy.py
│   ├── test_telemetry_field_extraction.py
│   ├── test_telemetry_skip_integration.py
│   ├── test_tm_improvement_integration.py
│   └── test_verification_integration.py
├── performance/                 # Performance/benchmark tests
│   └── test_benchmark_scaling.py
├── smoke/                       # Smoke tests (critical paths)
│   ├── test_critical_paths.py
│   ├── test_default_model_e2e.py
│   └── test_integration_smoke.py
├── unit/                        # Unit tests (100+ files)
│   ├── benchmarking/
│   │   ├── test_cli.py
│   │   ├── test_query.py
│   │   ├── test_recommender_negative.py
│   │   ├── test_scheduler.py
│   │   ├── test_schema_migration.py
│   │   ├── test_schema_migrations_v8.py
│   │   └── test_storage_negative.py
│   ├── hardware/
│   ├── model_runtime/
│   ├── observability/
│   ├── tm/
│   ├── translation_engine/
│   ├── verification/
│   └── workers/
└── validation/                  # Validation tests

Scripts:
scripts/
├── run_all_tests.py            # Master test runner
├── run_smoke_tests.py          # Smoke test runner
├── run_tests.py                # Basic test runner
└── run_tests_coverage.py       # Coverage test runner
```

**Test Categories:**

1. **Contract Tests** (13 files)
   - API contracts: file/directory translation
   - Invariants: atomic writes, file locking, TM lookup
   - Benchmarking: test_bm_001_benchmarking.py ← **CRITICAL for audit**

2. **Unit Tests** (100+ files)
   - Benchmarking unit tests: cli, query, recommender, scheduler, schema, storage
   - Model runtime, hardware, TM, translation engine, verification

3. **Integration Tests** (12 files)
   - test_benchmarking_cli.py
   - test_benchmarking_concurrency.py
   - test_benchmark_analytics_integration.py

4. **Smoke Tests** (3 files)
   - Critical path validation
   - Default model E2E
   - Integration smoke

5. **Performance Tests**
   - test_benchmark_scaling.py

**Assessment:**
- ✅ Comprehensive pytest-based test infrastructure
- ✅ Clear test categorization (unit/integration/contract/smoke)
- ✅ Benchmarking-specific tests exist
- ⚠️ Need to verify if existing benchmark tests check language iteration
- ⚠️ Need to add tests for language matrix coverage

---

### D.2: Test Runner Scripts

**Files Found:**
1. `scripts/run_all_tests.py` - Master runner
2. `scripts/run_smoke_tests.py` - Smoke tests only
3. `scripts/run_tests.py` - Basic runner
4. `scripts/run_tests_coverage.py` - With coverage reporting

**Invocation:**
```bash
# Full test suite
python scripts/run_all_tests.py

# Smoke tests only
python scripts/run_smoke_tests.py

# With coverage
python scripts/run_tests_coverage.py

# Specific category
pytest tests/contract/
pytest tests/unit/benchmarking/
```

**Gap:** Need to verify test coverage for:
- Benchmark language iteration
- CT2 conversion automation
- Model download workflow

---

## Current Behavior vs Spec Intent

| Feature | Spec Intent | Current Behavior | Status |
|---------|-------------|------------------|--------|
| **Benchmark Language Coverage** | 36 target languages × models × devices | HARDCODED to en→ru only | ❌ BLOCKER |
| **Database Schema** | Stores src_lang, tgt_lang for each result | Missing language columns | ❌ HIGH |
| **Language Iteration** | CLI iterates over all languages | No iteration, single hardcoded pair | ❌ HIGH |
| **Model Registry** | 10+ models with complete metadata | 7 models, some incomplete | ⚠️ PARTIAL |
| **Model Download CLI** | `download-models --all` | Does not exist | ❌ HIGH |
| **Model Manifest** | models/model_manifest.json tracking | File does not exist | ❌ MEDIUM |
| **CT2 Auto-Convert** | Auto-convert on download/load | Manual CLI only | ❌ HIGH |
| **CT2 Ensure Step** | Check/convert before model load | Not implemented | ❌ MEDIUM |
| **Model Selection** | Language-aware selection logic | Loads exact model_id only | ❌ MEDIUM |
| **Model Size Calc** | Auto-discovery computes sizes | Hardcoded to 0 | ⚠️ MEDIUM |
| **Download Resumption** | Resume interrupted downloads | N/A (no downloader) | ❌ MEDIUM |
| **Checksum Verification** | SHA256 verification | Not implemented | ❌ MEDIUM |
| **Load Test After DL** | Verify model loads after download | Not implemented | ❌ LOW |
| **E2E Pipeline** | Translation → Commit → Telemetry | ✅ Exists (verified by git status, telemetry files) | ✅ WORKING |
| **Test Infrastructure** | pytest with unit/integration/smoke | ✅ Comprehensive test suite | ✅ WORKING |
| **36 Target Languages** | Config defines all languages | ✅ config/target_languages.yaml | ✅ WORKING |

**Legend:**
- ✅ WORKING - Implemented and matches spec
- ⚠️ PARTIAL - Partially implemented
- ❌ BLOCKER - Missing, blocks core functionality
- ❌ HIGH - Missing, important for spec compliance
- ❌ MEDIUM - Missing, degrades functionality
- ❌ LOW - Missing, nice-to-have

---

## Concrete Gaps with File References

### Gap 1: Benchmark Language Hardcoding (BLOCKER)

**Files:**
- [src/benchmarking/runner.py:331](../../src/benchmarking/runner.py#L331) - `src_lang='en', tgt_lang='ru'`
- [src/benchmarking/runner.py:338](../../src/benchmarking/runner.py#L338) - `src_lang='en', tgt_lang='ru'`

**Fix Required:**
1. Add `src_lang` and `tgt_lang` parameters to `BenchmarkRunner.run_benchmark()`
2. Pass languages to `_benchmark_translation()`
3. CLI: Add `--source-lang`, `--target-lang`, and `--all-languages` flags
4. CLI: Implement language iteration loop for `--all-languages`

**Acceptance Criteria:**
- `python -m src.benchmarking.runner --model m2m100_418m --device cpu --all-languages` benchmarks all 36 languages
- Each benchmark result stores correct src_lang and tgt_lang

---

### Gap 2: Database Schema Missing Language Columns (HIGH)

**Files:**
- [src/benchmarking/storage.py:249-267](../../src/benchmarking/storage.py#L249) - CREATE TABLE benchmark_results

**Fix Required:**
1. Create schema migration (v10) to add columns:
   ```sql
   ALTER TABLE benchmark_results ADD COLUMN src_lang TEXT;
   ALTER TABLE benchmark_results ADD COLUMN tgt_lang TEXT;
   CREATE INDEX idx_results_lang_pair ON benchmark_results(src_lang, tgt_lang);
   ```
2. Update `BenchmarkResult` dataclass to include `src_lang`, `tgt_lang` fields
3. Update `save_run()` and `get_run()` to persist/load language fields
4. Update `compare_runs()` to support language filtering

**Acceptance Criteria:**
- `db.get_run(run_id).results[0].src_lang == 'en'`
- `db.get_run(run_id).results[0].tgt_lang == 'fr'`
- Query: `SELECT * FROM benchmark_results WHERE src_lang='en' AND tgt_lang='fr'` works

---

### Gap 3: No Model Download CLI (HIGH)

**Files:**
- Spec: [specs/models/ORGANIZATION.md](../../specs/models/ORGANIZATION.md#DL-001)
- CLI: [src/cli.py](../../src/cli.py) - No `download-models` subcommand

**Fix Required:**
1. Create `src/model_runtime/downloader.py` with `ModelDownloader` class
2. Implement HuggingFace Hub download via `snapshot_download()`
3. Add download resumption support
4. Add checksum verification
5. Add CLI subcommand:
   ```bash
   python -m src.cli download-models --all
   python -m src.cli download-models --model m2m100_418m
   python -m src.cli download-models --language fr
   ```
6. Generate/update `models/model_manifest.json` on download

**Acceptance Criteria:**
- `python -m src.cli download-models --model m2m100_418m` downloads to `models/m2m100_418M/`
- `models/model_manifest.json` updated with download metadata
- Interrupted download resumes without re-downloading completed files

---

### Gap 4: CT2 Conversion Not Automated (HIGH)

**Files:**
- [src/model_runtime/ct2_converter.py](../../src/model_runtime/ct2_converter.py) - Standalone CLI only
- [src/model_runtime/loader.py](../../src/model_runtime/loader.py) - No conversion call

**Fix Required:**
1. Create `CT2EnsureStep` class in `ct2_converter.py`
2. Add `ensure_ct2_model()` method
3. Call from `ModelLoader._create_backend()` when backend is "ctranslate2":
   ```python
   if model_info.backend == "ctranslate2":
       # Check if CT2 model exists
       if not ct2_model_exists(model_info.local_path):
           # Auto-convert from PyTorch
           pytorch_path = infer_pytorch_source(model_info)
           converter = CT2ConversionPipeline()
           converter.convert_model(pytorch_path, model_info.local_path, quantization="int8")
       return CTranslate2Backend(model_info, device, self.max_memory_mb)
   ```

**Acceptance Criteria:**
- Loading a CT2 model auto-converts if not present
- Conversion only happens once (cached after first conversion)
- Validation runs after conversion

---

### Gap 5: No Language-Aware Model Selection (MEDIUM)

**Files:**
- [src/model_runtime/loader.py](../../src/model_runtime/loader.py) - No language checking
- [src/translation_engine/engine.py](../../src/translation_engine/engine.py) - Need full read to assess

**Fix Required:**
1. Add `select_model_for_language_pair()` function to `loader.py`
2. Check model's `supported_pairs` field:
   - If `"all"`: Use for any language pair
   - If list: Check if `[src_lang, tgt_lang]` in list
3. Priority order:
   - Specialized bilingual model (e.g., opus_en_fr for en→fr)
   - Best multilingual model (highest parameters, best benchmarks)
4. Fallback: Raise `NoModelForLanguagePairError` if no model supports pair

**Acceptance Criteria:**
- Translating en→fr prefers `opus_en_fr` over `m2m100_418m`
- Translating en→ar uses `m2m100_418m` or `nllb_200_600m` (no specialized model)
- Requesting unsupported language pair raises clear error

---

### Gap 6: Model Manifest Missing (MEDIUM)

**Files:**
- Spec: [specs/models/ORGANIZATION.md:DIR-002](../../specs/models/ORGANIZATION.md#DIR-002)
- Expected location: `models/model_manifest.json`

**Fix Required:**
1. Create manifest schema:
   ```json
   {
     "version": "1.0",
     "last_updated": "2026-01-17T14:30:00Z",
     "models": [
       {
         "model_id": "m2m100_418m",
         "local_path": "models/m2m100_418M",
         "download_source": "huggingface:facebook/m2m100_418M",
         "size_mb": 1600,
         "files": [
           {"name": "pytorch_model.bin", "size_bytes": 1677721600, "sha256": "abc123..."}
         ],
         "downloaded_at": "2026-01-17T10:00:00Z",
         "verified": true,
         "backend": "huggingface"
       }
     ]
   }
   ```
2. Update manifest on every download/conversion
3. Use manifest to check if model already downloaded
4. Use manifest for integrity verification

**Acceptance Criteria:**
- `models/model_manifest.json` exists and is valid JSON
- Contains all downloaded models with checksums
- `verify_model_integrity()` uses manifest checksums

---

## Proposed Step Plan with Acceptance Checks

### Phase 1: Critical Benchmark Fixes (BLOCKER) - 3 steps

**Goal:** Make benchmarking measure all 36 languages, not just Russian

**Step 1.1: Database Schema Migration**
- File: `src/benchmarking/storage.py`
- Action: Add schema v10 migration
  ```python
  if from_version < 10:
      conn.execute("ALTER TABLE benchmark_results ADD COLUMN src_lang TEXT")
      conn.execute("ALTER TABLE benchmark_results ADD COLUMN tgt_lang TEXT")
      conn.execute("CREATE INDEX idx_results_lang ON benchmark_results(src_lang, tgt_lang)")
      conn.execute("INSERT INTO schema_version VALUES (10, datetime('now'))")
  ```
- Acceptance:
  - ✅ `SELECT sql FROM sqlite_master WHERE name='benchmark_results'` shows new columns
  - ✅ `SELECT * FROM schema_version ORDER BY version DESC LIMIT 1` returns 10
  - ✅ Existing data preserved (src_lang and tgt_lang are NULL for old records)

**Step 1.2: Update BenchmarkResult Dataclass**
- File: `src/benchmarking/storage.py`
- Action: Add fields to dataclass
  ```python
  @dataclass
  class BenchmarkResult:
      # ... existing fields ...
      src_lang: str = "en"  # Default for backward compat
      tgt_lang: str = "unknown"  # Default for backward compat
  ```
- Acceptance:
  - ✅ `BenchmarkResult(sample_id="test", ..., src_lang="en", tgt_lang="fr")` works
  - ✅ Old code without language params still works (defaults)

**Step 1.3: Parametrize runner.py**
- File: `src/benchmarking/runner.py`
- Action:
  1. Add `src_lang` and `tgt_lang` params to `run_benchmark()`
  2. Pass to `_benchmark_translation()`
  3. Replace hardcoded `'en'`, `'ru'` with params
  4. Save to BenchmarkResult
- Changes:
  ```python
  def run_benchmark(
      self,
      model_id: str,
      device: str,
      batch_sizes: List[int],
      iterations: int,
      src_lang: str = "en",      # NEW
      tgt_lang: str = "ru",      # NEW (default for backward compat)
      corpus_filter: Optional[str] = None,
      # ... other params ...
  ) -> BenchmarkRun:
      # ...
      result = self._benchmark_translation(
          backend=backend,
          texts=texts,
          sample_ids=sample_ids,
          model_id=model_id,
          device=device,
          batch_size=batch_size,
          src_lang=src_lang,    # NEW
          tgt_lang=tgt_lang,    # NEW
      )

  def _benchmark_translation(
      self,
      backend,
      texts: List[str],
      sample_ids: List[str],
      model_id: str,
      device: str,
      batch_size: int,
      src_lang: str,            # NEW
      tgt_lang: str,            # NEW
  ) -> List[BenchmarkResult]:
      # ...
      translations, input_tokens, output_tokens = backend.translate_with_token_counts(
          texts, src_lang=src_lang, tgt_lang=tgt_lang  # FIXED
      )
      # ...
      result = BenchmarkResult(
          # ... existing fields ...
          src_lang=src_lang,   # NEW
          tgt_lang=tgt_lang,   # NEW
      )
  ```
- Acceptance:
  - ✅ `runner.run_benchmark(..., src_lang='en', tgt_lang='fr')` translates English to French
  - ✅ Result saved to DB with correct src_lang='en', tgt_lang='fr'
  - ✅ Backward compat: calling without lang params defaults to en→ru

**Step 1.4: Add CLI Language Iteration**
- File: `src/benchmarking/cli.py`
- Action: Add `--source-lang`, `--target-lang`, `--all-languages` flags
  ```python
  parser.add_argument('--source-lang', default='en', help='Source language code')
  parser.add_argument('--target-lang', help='Target language code (required unless --all-languages)')
  parser.add_argument('--all-languages', action='store_true',
                     help='Benchmark all 36 target languages')

  def cmd_run(args):
      # ... load registry, runner ...

      # Load target languages
      with open('config/target_languages.yaml') as f:
          lang_config = yaml.safe_load(f)
      target_languages = [lang['iso_code'] for lang in lang_config['languages']]

      if args.all_languages:
          language_pairs = [(args.source_lang, tgt) for tgt in target_languages]
      elif args.target_lang:
          language_pairs = [(args.source_lang, args.target_lang)]
      else:
          raise ValueError("Must specify --target-lang or --all-languages")

      for src_lang, tgt_lang in language_pairs:
          logger.info(f"Benchmarking {src_lang} → {tgt_lang}")
          result = runner.run_benchmark(
              model_id=args.model,
              device=args.device,
              batch_sizes=batch_sizes,
              iterations=args.iterations,
              src_lang=src_lang,
              tgt_lang=tgt_lang,
              # ... other args ...
          )
  ```
- Acceptance:
  - ✅ `python -m src.benchmarking.cli run --model m2m100_418m --all-languages` benchmarks 36 languages
  - ✅ Each language saved to DB as separate run or results within same run
  - ✅ `python -m src.benchmarking.cli run --model m2m100_418m --target-lang fr` benchmarks only French

**Step 1.5: Testing**
- File: `tests/contract/test_bm_001_benchmarking.py` (or new file)
- Action: Add test for language matrix
  ```python
  def test_benchmark_all_languages():
      runner = BenchmarkRunner(registry, db_path)
      for lang in ASPOSE_LANGUAGES:
          run = runner.run_benchmark(
              model_id="m2m100_418m",
              device="cpu",
              batch_sizes=[4],
              iterations=1,
              src_lang="en",
              tgt_lang=lang,
              corpus_filter="tiny",
          )
          assert len(run.results) > 0
          assert run.results[0].src_lang == "en"
          assert run.results[0].tgt_lang == lang
  ```
- Acceptance:
  - ✅ Test passes for all 36 languages
  - ✅ Database contains results for all languages

**Phase 1 Completion Criteria:**
- ✅ Database schema updated to v10
- ✅ Benchmark runner accepts src_lang/tgt_lang
- ✅ CLI supports `--all-languages` flag
- ✅ Running `--all-languages` creates 36 benchmark results
- ✅ All results saved to DB with correct language codes
- ✅ Tests confirm language iteration works

**Estimated Risk:** LOW - Backward compatible changes, thorough testing

---

### Phase 2: Model Download Infrastructure (HIGH) - 4 steps

**Goal:** Automate model downloads with resumption and verification

**Step 2.1: Create ModelDownloader Class**
- File: `src/model_runtime/downloader.py` (NEW)
- Action: Implement downloader
  ```python
  from huggingface_hub import snapshot_download
  from concurrent.futures import ThreadPoolExecutor
  import hashlib

  class ModelDownloader:
      def __init__(self, registry: ModelRegistry, models_dir: Path = Path("models")):
          self.registry = registry
          self.models_dir = models_dir
          self.manifest_path = models_dir / "model_manifest.json"

      def download_model(self, model_id: str, max_retries: int = 3) -> Path:
          """Download single model with retry logic."""
          model_info = self.registry.get_model(model_id)

          # Check disk space
          self._check_disk_space(model_info.model_size_mb)

          # Download from HuggingFace Hub
          for attempt in range(max_retries):
              try:
                  local_path = snapshot_download(
                      repo_id=model_info.hf_model_id,
                      local_dir=str(self.models_dir / model_info.local_path),
                      local_dir_use_symlinks=False,
                      resume_download=True,
                  )

                  # Verify download
                  self._verify_model(model_id, local_path)

                  # Update manifest
                  self._update_manifest(model_id, local_path)

                  return Path(local_path)
              except Exception as e:
                  if attempt == max_retries - 1:
                      raise
                  time.sleep(2 ** attempt)  # Exponential backoff

      def download_all(self, max_workers: int = 5):
          """Download all models in parallel."""
          with ThreadPoolExecutor(max_workers=max_workers) as executor:
              futures = {
                  executor.submit(self.download_model, model.model_id): model
                  for model in self.registry.models.values()
              }
              for future in as_completed(futures):
                  model = futures[future]
                  try:
                      path = future.result()
                      print(f"✓ {model.model_id}: {path}")
                  except Exception as e:
                      print(f"✗ {model.model_id}: {e}")
  ```
- Acceptance:
  - ✅ `downloader.download_model("m2m100_418m")` downloads to `models/m2m100_418M/`
  - ✅ Interrupted download resumes from last checkpoint
  - ✅ Network errors retry with exponential backoff (up to max_retries)

**Step 2.2: Add Model Manifest Management**
- File: `src/model_runtime/downloader.py`
- Action: Implement manifest CRUD
  ```python
  def _load_manifest(self) -> dict:
      if not self.manifest_path.exists():
          return {"version": "1.0", "models": []}
      with open(self.manifest_path) as f:
          return json.load(f)

  def _update_manifest(self, model_id: str, local_path: Path):
      manifest = self._load_manifest()

      # Compute file checksums
      files = []
      for file in local_path.rglob("*"):
          if file.is_file():
              checksum = self._compute_sha256(file)
              files.append({
                  "name": file.name,
                  "size_bytes": file.stat().st_size,
                  "sha256": checksum,
              })

      # Add/update model entry
      model_entry = {
          "model_id": model_id,
          "local_path": str(local_path),
          "download_source": f"huggingface:{self.registry.get_model(model_id).hf_model_id}",
          "size_mb": sum(f["size_bytes"] for f in files) / (1024 ** 2),
          "files": files,
          "downloaded_at": datetime.now(UTC).isoformat(),
          "verified": True,
          "backend": self.registry.get_model(model_id).backend,
      }

      # Update manifest
      manifest["models"] = [m for m in manifest["models"] if m["model_id"] != model_id]
      manifest["models"].append(model_entry)
      manifest["last_updated"] = datetime.now(UTC).isoformat()

      with open(self.manifest_path, "w") as f:
          json.dump(manifest, f, indent=2)

  def _compute_sha256(self, file_path: Path) -> str:
      sha = hashlib.sha256()
      with open(file_path, "rb") as f:
          for chunk in iter(lambda: f.read(8192), b""):
              sha.update(chunk)
      return sha.hexdigest()
  ```
- Acceptance:
  - ✅ `models/model_manifest.json` created on first download
  - ✅ Manifest updated on each download
  - ✅ Checksums match downloaded files

**Step 2.3: Add CLI Subcommand**
- File: `src/cli.py`
- Action: Add `download-models` subcommand
  ```python
  @click.group()
  def cli():
      """Hugo Translation System CLI."""
      pass

  @cli.command()
  @click.option('--all', is_flag=True, help='Download all models')
  @click.option('--model', help='Download specific model by ID')
  @click.option('--parallel', default=5, help='Max parallel downloads')
  def download_models(all, model, parallel):
      """Download translation models."""
      registry = ModelRegistry("config/model_registry.yaml")
      downloader = ModelDownloader(registry)

      if all:
          downloader.download_all(max_workers=parallel)
      elif model:
          downloader.download_model(model)
      else:
          click.echo("Specify --all or --model MODEL_ID")
  ```
- Acceptance:
  - ✅ `python -m src.cli download-models --all` downloads all models
  - ✅ `python -m src.cli download-models --model m2m100_418m` downloads single model
  - ✅ Progress bars shown during download

**Step 2.4: Testing**
- File: `tests/integration/test_model_download.py` (NEW)
- Action: Add download tests
  ```python
  def test_download_single_model(tmp_path, mock_registry):
      downloader = ModelDownloader(mock_registry, models_dir=tmp_path)
      path = downloader.download_model("test_model")

      assert path.exists()
      assert (path / "config.json").exists()

      manifest = downloader._load_manifest()
      assert len(manifest["models"]) == 1
      assert manifest["models"][0]["model_id"] == "test_model"

  def test_download_resumption(tmp_path, mock_registry):
      # Start download
      downloader = ModelDownloader(mock_registry, models_dir=tmp_path)

      # Simulate interruption
      with pytest.raises(NetworkError):
          downloader.download_model("test_model", interrupt_at=0.5)

      # Resume
      path = downloader.download_model("test_model")
      assert path.exists()
  ```
- Acceptance:
  - ✅ Download tests pass
  - ✅ Resumption test confirms no re-download

**Phase 2 Completion Criteria:**
- ✅ ModelDownloader implemented
- ✅ Manifest management working
- ✅ CLI command functional
- ✅ Download resumption works
- ✅ Checksum verification works
- ✅ Tests pass

**Estimated Risk:** MEDIUM - External dependencies (HuggingFace Hub), network reliability

---

### Phase 3: CT2 Automation (HIGH) - 2 steps

**Goal:** Auto-convert PyTorch models to CT2 on-demand

**Step 3.1: Create CT2EnsureStep**
- File: `src/model_runtime/ct2_converter.py`
- Action: Add ensure logic
  ```python
  class CT2EnsureStep:
      def __init__(self, converter: CT2ConversionPipeline):
          self.converter = converter

      def ensure_ct2_model(
          self,
          ct2_model_path: Path,
          pytorch_model_id: str,
          registry: ModelRegistry,
          quantization: str = "int8",
      ) -> Path:
          """
          Ensure CT2 model exists, converting if necessary.

          Returns: Path to validated CT2 model
          Raises: CT2ConversionError on failure
          """
          # Check if already exists and valid
          if ct2_model_path.exists():
              if self.converter.validate_ct2_model(ct2_model_path):
                  logger.info(f"CT2 model exists and valid: {ct2_model_path}")
                  return ct2_model_path
              else:
                  logger.warning(f"CT2 model invalid, re-converting: {ct2_model_path}")
                  shutil.rmtree(ct2_model_path)

          # Find source PyTorch model
          pytorch_model = registry.get_model(pytorch_model_id)
          if not pytorch_model:
              raise CT2ConversionError(f"Source model not found: {pytorch_model_id}")

          pytorch_path = Path(pytorch_model.local_path)
          if not pytorch_path.exists():
              raise CT2ConversionError(
                  f"PyTorch model not downloaded: {pytorch_model_id}. "
                  f"Run: python -m src.cli download-models --model {pytorch_model_id}"
              )

          # Convert
          logger.info(f"Converting {pytorch_model_id} to CT2 ({quantization})...")
          success = self.converter.convert_model(
              model_path=pytorch_path,
              output_path=ct2_model_path,
              quantization=quantization,
              force=False,
          )

          if not success:
              raise CT2ConversionError(f"Conversion failed: {pytorch_model_id}")

          # Validate
          if not self.converter.validate_ct2_model(ct2_model_path):
              raise CT2ConversionError(f"Validation failed: {ct2_model_path}")

          logger.info(f"CT2 model ready: {ct2_model_path}")
          return ct2_model_path
  ```
- Acceptance:
  - ✅ `ensure_ct2_model()` converts if not present
  - ✅ Second call skips conversion (already exists)
  - ✅ Invalid cached model triggers re-conversion
  - ✅ Missing PyTorch source raises clear error

**Step 3.2: Integrate with ModelLoader**
- File: `src/model_runtime/loader.py`
- Action: Call ensure before loading CT2 backend
  ```python
  def _create_backend(self, model_info: ModelInfo, device: str) -> ModelBackend:
      if model_info.backend == "ctranslate2":
          # Ensure CT2 model exists (auto-convert if needed)
          converter = CT2ConversionPipeline()
          ensure_step = CT2EnsureStep(converter)

          # Infer source PyTorch model from CT2 model_id
          # e.g., "m2m100_418m_ct2_int8" → "m2m100_418m"
          pytorch_model_id = model_info.model_id.replace("_ct2", "").replace("_int8", "")

          ct2_model_path = ensure_step.ensure_ct2_model(
              ct2_model_path=Path(model_info.local_path),
              pytorch_model_id=pytorch_model_id,
              registry=self.registry,
              quantization="int8",  # TODO: Infer from model_id suffix
          )

          return CTranslate2Backend(model_info, device, self.max_memory_mb)

      elif model_info.backend == "huggingface":
          # ... existing code ...
  ```
- Acceptance:
  - ✅ Loading `m2m100_418m_ct2_int8` auto-converts if not present
  - ✅ Subsequent loads skip conversion
  - ✅ Error if source PyTorch model not downloaded

**Step 3.3: Testing**
- File: `tests/unit/model_runtime/test_ct2_ensure.py` (NEW)
- Action: Test auto-conversion
  ```python
  def test_ct2_ensure_converts_on_first_load(tmp_path, registry):
      # Download PyTorch model
      # ... download m2m100_418m ...

      # Load CT2 model (should auto-convert)
      loader = ModelLoader(registry)
      backend = loader.load_model("m2m100_418m_ct2_int8", device="cpu")

      # Verify conversion happened
      assert Path("models/ct2/m2m100_418m_int8").exists()
      assert backend.loaded

  def test_ct2_ensure_skips_if_exists(tmp_path):
      # Pre-create valid CT2 model
      # ... create CT2 model ...

      # Load (should skip conversion)
      loader = ModelLoader(registry)
      backend = loader.load_model("m2m100_418m_ct2_int8")

      # Verify no conversion attempted (check logs)
      assert "Converting" not in caplog.text
  ```
- Acceptance:
  - ✅ Tests pass
  - ✅ Conversion only happens once

**Phase 3 Completion Criteria:**
- ✅ CT2EnsureStep implemented
- ✅ ModelLoader calls ensure before CT2 load
- ✅ Auto-conversion works
- ✅ Cached models reused
- ✅ Tests confirm behavior

**Estimated Risk:** LOW - Well-isolated change, existing CT2 converter proven

---

### Phase 4: Model Selection Enhancement (MEDIUM) - 2 steps

**Goal:** Select best model for each language pair

**Step 4.1: Implement Language-Aware Selection**
- File: `src/model_runtime/model_selector.py` (NEW)
- Action: Create selection logic
  ```python
  class ModelSelector:
      def __init__(self, registry: ModelRegistry):
          self.registry = registry

      def select_model_for_language_pair(
          self,
          src_lang: str,
          tgt_lang: str,
          device: str = "cpu",
          prefer_specialized: bool = True,
      ) -> str:
          """
          Select best model for language pair.

          Priority:
          1. Specialized bilingual models (if prefer_specialized=True)
          2. Multilingual models with explicit support
          3. Multilingual models with "all" support

          Returns: model_id
          Raises: NoModelForLanguagePairError if no model supports pair
          """
          candidates = []

          for model in self.registry.models.values():
              # Check device compatibility
              if device != model.optimal_device and model.optimal_device != "both":
                  # Deprioritize but still allow
                  score_penalty = 0.5
              else:
                  score_penalty = 1.0

              # Check language support
              if model.supported_pairs == "all":
                  # Multilingual catch-all
                  candidates.append((model.model_id, 1.0 * score_penalty))
              elif isinstance(model.supported_pairs, list):
                  for pair in model.supported_pairs:
                      if pair == [src_lang, tgt_lang]:
                          # Exact match (specialized model)
                          if prefer_specialized:
                              candidates.append((model.model_id, 10.0 * score_penalty))
                          else:
                              candidates.append((model.model_id, 2.0 * score_penalty))

          if not candidates:
              raise NoModelForLanguagePairError(
                  f"No model supports {src_lang} → {tgt_lang}"
              )

          # Sort by score (highest first)
          candidates.sort(key=lambda x: x[1], reverse=True)
          return candidates[0][0]
  ```
- Acceptance:
  - ✅ `select_model_for_language_pair("en", "fr")` returns `opus_en_fr`
  - ✅ `select_model_for_language_pair("en", "ar")` returns multilingual model
  - ✅ Unsupported pair raises `NoModelForLanguagePairError`

**Step 4.2: Integrate with TranslationEngine**
- File: `src/translation_engine/engine.py`
- Action: Use selector if model_id not specified
  ```python
  def __init__(
      self,
      config_service: ConfigService,
      tm: TranslationMemory,
      model_loader: ModelLoader,
      model_id: Optional[str] = None,  # Allow None for auto-selection
      # ... other params ...
  ):
      self.config = config_service.config
      self.tm = tm
      self.model_loader = model_loader

      # Auto-select model if not specified
      if model_id is None:
          selector = ModelSelector(model_loader.registry)
          self.model_id = selector.select_model_for_language_pair(
              src_lang=self.config.get("source_language", "en"),
              tgt_lang=self.config.get("target_language", "fr"),  # Default
              device=model_loader.device,
          )
          logger.info(f"Auto-selected model: {self.model_id}")
      else:
          self.model_id = model_id
  ```
- Acceptance:
  - ✅ Not specifying model_id auto-selects best model
  - ✅ Explicit model_id overrides auto-selection

**Phase 4 Completion Criteria:**
- ✅ ModelSelector implemented
- ✅ TranslationEngine uses selector
- ✅ Tests confirm correct model selection

**Estimated Risk:** LOW - Optional feature, doesn't break existing explicit selection

---

## Risk Assessment

### Implementation Risks

| Phase | Risk Level | Mitigation |
|-------|-----------|------------|
| Phase 1: Benchmark Language Iteration | 🟢 LOW | Backward-compatible changes, thorough testing, schema migration proven |
| Phase 2: Model Download | 🟡 MEDIUM | Mock HuggingFace Hub in tests, retry logic, disk space checks |
| Phase 3: CT2 Automation | 🟢 LOW | Existing converter proven, well-isolated change |
| Phase 4: Model Selection | 🟢 LOW | Optional feature, doesn't affect existing workflows |

### Rollback Plan

**Phase 1:**
- If issues: Schema migration is additive (won't break old queries)
- Rollback: Revert code, schema v10 remains (no data loss)

**Phase 2:**
- If issues: Download failures don't affect existing models
- Rollback: Delete manifest, continue manual model management

**Phase 3:**
- If issues: Conversion failures fall back to manual conversion
- Rollback: Remove ensure step, use manual CT2 conversion

**Phase 4:**
- If issues: Auto-selection errors
- Rollback: Always require explicit model_id

### Testing Strategy

**Unit Tests:**
- Database migrations (v10 schema)
- BenchmarkResult with language fields
- ModelDownloader download/resumption
- CT2EnsureStep conversion logic
- ModelSelector language matching

**Integration Tests:**
- Full benchmark run with language iteration
- Download → Convert → Load pipeline
- Model selection → Translation E2E

**Smoke Tests:**
- Benchmark 1 language (en→fr) end-to-end
- Download 1 model end-to-end
- Load CT2 model with auto-conversion

**Contract Tests:**
- API invariants: BenchmarkResult schema
- Database schema v10 structure
- Model manifest JSON schema

---

## Appendix: Evidence

### A.1: Hardcoded Language Evidence

**File:** src/benchmarking/runner.py:331-338

```python
# Try to use translate_with_token_counts if available (HuggingFace backend)
if hasattr(backend, 'translate_with_token_counts'):
    translations, input_tokens, output_tokens = backend.translate_with_token_counts(
        texts, src_lang='en', tgt_lang='ru'  # ← LINE 331: HARDCODED
    )
    # Distribute tokens across batch (rough estimate)
    tokens_per_sample_in = input_tokens // len(texts) if texts else 0
    tokens_per_sample_out = output_tokens // len(texts) if texts else 0
else:
    # Fallback for CT2 backend: use heuristic token estimation
    translations = backend.translate(texts, src_lang='en', tgt_lang='ru')  # ← LINE 338: HARDCODED
```

### A.2: Target Languages Spec

**File:** config/target_languages.yaml

**Total Languages:** 36 (not 35 as originally stated)

```yaml
languages:
  - iso_code: ar    # Arabic
  - iso_code: bg    # Bulgarian
  - iso_code: ca    # Catalan
  - iso_code: cs    # Czech
  - iso_code: da    # Danish
  - iso_code: de    # German
  - iso_code: el    # Greek
  - iso_code: es    # Spanish
  - iso_code: fa    # Persian
  - iso_code: fi    # Finnish
  - iso_code: fr    # French
  - iso_code: he    # Hebrew
  - iso_code: hi    # Hindi
  - iso_code: hr    # Croatian
  - iso_code: hu    # Hungarian
  - iso_code: id    # Indonesian
  - iso_code: it    # Italian
  - iso_code: ja    # Japanese
  - iso_code: ko    # Korean
  - iso_code: lt    # Lithuanian
  - iso_code: lv    # Latvian
  - iso_code: ms    # Malay
  - iso_code: nl    # Dutch
  - iso_code: no    # Norwegian
  - iso_code: pl    # Polish
  - iso_code: pt    # Portuguese
  - iso_code: ro    # Romanian
  - iso_code: ru    # Russian
  - iso_code: sk    # Slovak
  - iso_code: sr    # Serbian
  - iso_code: sv    # Swedish
  - iso_code: th    # Thai
  - iso_code: tr    # Turkish
  - iso_code: uk    # Ukrainian
  - iso_code: vi    # Vietnamese
  - iso_code: zh    # Chinese
```

### A.3: Database Schema Evidence

**File:** src/benchmarking/storage.py:249-267

```python
# v1 schema - benchmark_results table
conn.execute(
    """
    CREATE TABLE IF NOT EXISTS benchmark_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL,
        sample_id TEXT NOT NULL,
        model_id TEXT NOT NULL,
        device TEXT NOT NULL,
        batch_size INTEGER NOT NULL,
        duration_seconds REAL NOT NULL,
        tokens_input INTEGER NOT NULL,
        tokens_output INTEGER NOT NULL,
        throughput_tokens_per_sec REAL NOT NULL,
        peak_memory_mb REAL,
        errors TEXT NOT NULL,
        FOREIGN KEY (run_id) REFERENCES benchmark_runs(run_id) ON DELETE CASCADE
    )
"""
)
# ← No src_lang or tgt_lang columns!
```

**Migrations v2-9:** Checked storage.py lines 283-583
- v2: Composite indices
- v3: recommendation_feedback table
- v4: recommendation_weights table
- v5: Extended SystemInfo fields
- v6: Quality metrics (BLEU, COMET)
- v7: Cache tracking
- v8: Analytics tables
- v9: Query optimization indices

**None add src_lang/tgt_lang to benchmark_results!**

### A.4: Model Registry Evidence

**File:** config/model_registry.yaml:1-100

Current models:
1. m2m100_418m (HF, all, 1600MB)
2. m2m100_418m_ct2 (CT2, all, 800MB)
3. m2m100_418m_ct2_int8 (CT2, all, 250MB)
4. nllb_200_600m_ct2_int8 (CT2, all, 350MB)
5. m2m100_1.2b (HF, all, 4800MB)
6. nllb_200_600m (HF, all, 2400MB)
7. nllb_200_1.3b (HF, all, 5200MB)
8. opus_en_fr (HF, [[en,fr],[fr,en]], 300MB, NO local_path!)

---

## Conclusion

This audit has identified **critical gaps** between the documented specifications and current implementation:

**BLOCKER:**
- Benchmarking system hardcodes EN→RU, ignoring 35 other target languages

**HIGH Priority:**
- Database schema lacks language fields for performance analysis
- No automated model download mechanism
- CT2 conversion is manual-only

**MEDIUM Priority:**
- Model selection doesn't consider language support
- Auto-discovery produces incomplete metadata

The proposed 4-phase implementation plan addresses all gaps with:
- ✅ Backward-compatible changes
- ✅ Clear acceptance criteria per step
- ✅ Comprehensive testing strategy
- ✅ Low-medium risk profile with rollback plans

**Next Steps:**
1. Review this audit with stakeholders
2. Approve phase plan or request modifications
3. Begin Phase 1 implementation (benchmark language iteration)
4. Execute phases sequentially with testing gates

---

**End of Audit Report**
