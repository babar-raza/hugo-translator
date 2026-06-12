# BM-001: Model Benchmarking System

**Feature:** Comprehensive benchmarking for translation models (speed + quality metrics)
**Status:** 🔴 CRITICAL_GAPS (Zero real data, theoretical docs, failed executions)
**Last Updated:** 2025-12-27
**Priority:** P0 (Blocks production credibility)

---

## Summary

Multi-dimensional benchmarking system to measure translation model performance across speed (throughput, latency, memory) and quality (BLEU, COMET, chrF++) metrics. Supports comparative analysis across 12+ registered models with configurable test matrices. All benchmarks must be real-world measurements on actual hardware—zero theoretical or fabricated data permitted.

**Critical Context:** Current state has zero real benchmark data despite infrastructure being fully built. All published performance numbers are theoretical estimates from literature, misleading users about actual system performance.

---

## User Requirements (Non-Negotiable)

### REQ-BM-01: Benchmark All Open-Source Translation Models

**Requirement:** System MUST support benchmarking all open-source translation models specialized for translation, not just the 3/12 currently tested.

**Rationale:** Users need comparative data across all available models to make informed decisions about which model to deploy for their use case.

**Current Gap:** Only m2m100_418m, opus_en_fr, nllb_200_600m have test coverage (25% of registered models).

**Evidence Required:**
- Database query `SELECT COUNT(DISTINCT model_id) FROM benchmark_runs` returns ≥12
- All models in `config/model_registry.yaml` have corresponding benchmark_runs entries

---

### REQ-BM-02: Try Many Specialized Translation Models

**Requirement:** System MUST actively discover and test many translation-specialized models from HuggingFace Hub and other sources, not just manually curated models.

**Rationale:** Translation model landscape evolves rapidly. Manual curation misses new high-quality models. Automated discovery ensures comprehensive coverage.

**Current Gap:** No model discovery system. Registry is static with 12 hardcoded entries.

**Evidence Required:**
- `scripts/models/discover_models.py` exists and can discover ≥50 models from HuggingFace
- Registry updated with discovered models marked `discovered: true`
- Benchmarks executed for discovered models

---

### REQ-BM-03: Benchmark Speed AND Quality

**Requirement:** Benchmarking MUST measure both:
1. **Speed metrics:** Throughput (tokens/sec), latency (sec/sample), memory usage (MB)
2. **Quality metrics:** BLEU scores, COMET scores, chrF++ scores

**Rationale:** Speed-only benchmarks are insufficient. A fast model with poor translation quality is useless. Users need multi-dimensional data.

**Current Gap:**
- Speed benchmarking infrastructure exists but has zero real data
- Quality benchmarking completely missing (no BLEU/COMET implementation)

**Evidence Required:**
- Database schema includes `bleu_score`, `comet_score`, `chrf_score` columns
- Query `SELECT model_id, AVG(bleu_score), AVG(throughput_tokens_per_sec) FROM benchmark_results GROUP BY model_id` returns data for all models
- Quality corpus with reference translations exists at `data/quality_corpus/`

---

### REQ-BM-04: Real Data Only - Zero Theoretical Values

**Requirement:** All documented benchmarks MUST be based on actual measurements on real hardware running this system. Zero theoretical, imaginary, or literature-derived values permitted in documentation.

**Rationale:** Theoretical benchmarks mislead users. RTX 3060 numbers from Facebook's paper don't reflect this system's actual performance. Users deploy based on documented numbers and get surprised by reality.

**Current Gap:**
- `docs/guides/model-selection-criteria.md` contains theoretical throughput tables (lines 228-250)
- `docs/performance/cpu-benchmarks.md` contains fabricated ranges (lines 72-158)
- Database has 0 rows despite infrastructure being ready

**Evidence Required:**
- Every performance number in docs has source: `Measured on <hardware> on <date>`
- Grep `docs/ -r "tokens/sec|BLEU"` returns zero unsourced performance claims
- Database `benchmark_runs.timestamp_utc` shows recent execution dates

---

### REQ-BM-05: No Hardcoded Model Names in Tests

**Requirement:** Test code MUST NOT hardcode specific model IDs like "m2m100_418m". Tests must use configurable fixtures or config-driven model selection to work with any model.

**Rationale:** Hardcoded model names make tests brittle and prevent testing with different models. When a new model is added, tests should automatically work with it.

**Current Gap:** 28+ test files hardcode `model_id = "m2m100_418m"`, `"opus_en_fr"`, etc.

**Evidence Required:**
- Grep `tests/ -r 'model_id.*=.*"m2m100|opus|nllb"'` (excluding conftest/examples) returns 0 results
- `pytest --test-model=small100` runs successfully
- `tests/conftest.py` contains `@pytest.fixture def test_model_id()` pulling from config

---

### REQ-BM-06: Model Storage Strategy is Critical

**Requirement:** System MUST have documented, implemented, and tested strategy for:
1. Where downloaded models are stored (HuggingFace cache, local, CT2 conversions)
2. How much disk space is required
3. How to manage cache (list, cleanup, verify)
4. How to migrate models between systems

**Rationale:** Models are 400MB-5GB files. Without clear storage strategy, users run out of disk, cache bloats, CI/CD breaks, production deployments fail.

**Current Gap:**
- No documentation of where models are stored
- No cache management utilities
- No disk space requirements documented
- Tests may download models unpredictably

**Evidence Required:**
- `docs/operations/model-storage.md` exists with storage architecture
- `scripts/manage_model_cache.py --list` shows all cached models with sizes
- Config `global.yaml` has `model_cache` section with `cache_dir`, `max_size_gb` settings
- `.gitignore` excludes model cache directories

---

## Entry Points

### Benchmarking Execution

**Primary Script:** `scripts/bench/benchmark_cpu_comprehensive.py`
**GPU Script:** `scripts/bench/benchmark_production_optimized.py`
**Quality Script:** `scripts/bench/benchmark_quality.py` (to be implemented)

**Integration:**
- Uses: `BenchmarkRunner` from `src/benchmarking/runner.py`
- Stores to: `BenchmarkDatabase` in `src/benchmarking/storage.py`
- Models from: `ModelRegistry` in `src/model_runtime/registry.py`

### Model Discovery

**Primary Script:** `scripts/models/discover_models.py` (to be implemented)

**Integration:**
- Uses: `ModelDiscovery` from `src/model_runtime/discovery.py` (to be implemented)
- Updates: `config/model_registry.yaml`

### Cache Management

**Primary Script:** `scripts/manage_model_cache.py` (to be implemented)

**Integration:**
- Inspects: `~/.cache/huggingface/`, `models/ct2/`, `models/custom/`
- Config: `config/global.yaml` → `model_cache` section

---

## Inputs/Outputs

### Speed Benchmark Execution

```bash
python scripts/bench/benchmark_cpu_comprehensive.py \
  --models m2m100_418m,m2m100_418m_ct2 \
  --batch-sizes 4,8,16 \
  --iterations 3 \
  --corpus small \
  --save-to-db data/benchmarks/benchmarks.db
```

**Inputs:**
- `--models`: Comma-separated model IDs (or "all" for all registered)
- `--batch-sizes`: List of batch sizes to test
- `--iterations`: Number of runs per config (for statistical significance)
- `--corpus`: Corpus tier (tiny/small/medium/large)

**Outputs:**
- Database rows in `benchmark_runs` table (run metadata)
- Database rows in `benchmark_results` table (per-sample metrics)
- Markdown report at `reports/benchmark_*.md`

**Side Effects:**
- Downloads models if not cached
- Consumes disk space for database (~10-100MB depending on runs)
- GPU memory allocation during execution

---

### Quality Benchmark Execution

```bash
python scripts/bench/benchmark_quality.py \
  --models m2m100_418m \
  --corpus data/quality_corpus/wmt_newstest_2022.json \
  --metrics bleu,comet,chrf \
  --save-to-db data/benchmarks/benchmarks.db
```

**Inputs:**
- `--models`: Models to evaluate
- `--corpus`: JSON file with source + reference translations
- `--metrics`: Comma-separated list (bleu, comet, chrf)

**Outputs:**
- Quality scores in `benchmark_results.bleu_score`, `comet_score`, `chrf_score`
- Aggregate report showing quality vs speed tradeoffs

**Corpus Format:**
```json
[
  {
    "id": "wmt22_001",
    "source": "English source text",
    "source_lang": "en",
    "target_lang": "fr",
    "references": {
      "fr": ["French reference 1", "French reference 2"]
    }
  }
]
```

---

### Model Discovery

```bash
python scripts/models/discover_models.py \
  --task translation \
  --min-downloads 1000 \
  --limit 50 \
  --auto-register
```

**Inputs:**
- `--task`: HuggingFace task filter (translation)
- `--min-downloads`: Minimum download count threshold (popularity filter)
- `--limit`: Maximum models to discover

**Outputs:**
- Appends discovered models to `config/model_registry.yaml`
- Creates cache at `data/model_discovery_cache.json`
- Prints discovered model list to stdout

---

### Cache Management

```bash
# List cached models
python scripts/manage_model_cache.py --list

# Cleanup old models (dry run)
python scripts/manage_model_cache.py --cleanup --older-than 30d --dry-run

# Cleanup (execute)
python scripts/manage_model_cache.py --cleanup --older-than 30d
```

**Inputs:**
- `--list`: Show all cached models
- `--cleanup`: Remove old models
- `--older-than`: Age threshold (e.g., "30d", "90d")
- `--dry-run`: Preview deletions without executing

**Outputs:**
- List of models with sizes (MB/GB)
- Cleanup report (models removed, space freed)

---

## Invariants

### Must (Critical)

1. **Real data only:**
   - Benchmark results MUST come from actual model inference, not fabricated
   - Evidence: Database `benchmark_runs.timestamp_utc` is recent, system_info populated
   - Rationale: REQ-BM-04 mandates zero theoretical data

2. **Quality AND speed metrics:**
   - Every benchmarked model MUST have both speed metrics (throughput, latency, memory) AND quality metrics (BLEU, COMET, chrF)
   - Evidence: Database schema has all metric columns, queries return non-NULL for both metric types
   - Rationale: REQ-BM-03 requires multi-dimensional benchmarking

3. **Model-agnostic tests:**
   - Test code MUST NOT hardcode model IDs; use fixtures/config
   - Evidence: `grep -r 'model_id.*=.*"m2m100"' tests/` returns 0 (excluding conftest/examples)
   - Rationale: REQ-BM-05 ensures tests work with any model

4. **Comprehensive model coverage:**
   - ALL models in registry MUST have benchmark data
   - Evidence: `SELECT COUNT(*) FROM (SELECT model_id FROM models LEFT JOIN benchmark_runs USING(model_id) WHERE benchmark_runs.model_id IS NULL)` returns 0
   - Rationale: REQ-BM-01 requires all models benchmarked

5. **Documented storage strategy:**
   - Model storage locations, disk requirements, cleanup procedures MUST be documented
   - Evidence: `docs/operations/model-storage.md` exists with cache locations, space requirements, cleanup commands
   - Rationale: REQ-BM-06 prevents operational failures

6. **Discovery automation:**
   - System MUST support automated discovery of translation models from HuggingFace
   - Evidence: `scripts/models/discover_models.py` exists, can discover ≥50 models
   - Rationale: REQ-BM-02 requires trying many models, manual curation insufficient

### Should (Important)

7. **Benchmark reproducibility:**
   - Benchmarks SHOULD be reproducible with `--seed` flag
   - Evidence: Deterministic corpus sampling, fixed random seeds
   - Rationale: Compare results across runs, detect regressions

8. **Statistical significance:**
   - Each benchmark configuration SHOULD run ≥3 iterations
   - Evidence: Default `iterations=3` in benchmark scripts
   - Rationale: Single runs have high variance; averaging reduces noise

9. **Multiple batch sizes:**
   - Speed benchmarks SHOULD test ≥3 batch sizes (e.g., 4, 8, 16)
   - Evidence: Default `--batch-sizes 4,8,16` in scripts
   - Rationale: Batch size significantly affects throughput; users need data for their memory constraints

10. **Reference corpus quality:**
    - Quality benchmarks SHOULD use professionally translated references (e.g., WMT newstest)
    - Evidence: `data/quality_corpus/wmt_newstest_2022.json` sourced from WMT
    - Rationale: Synthetic references inflate scores; real references reflect production quality

### May (Optional)

11. **Cloud benchmarking:**
   - System MAY support running benchmarks on cloud instances (AWS, GCP, Azure)
   - Evidence: Cloud instance recommendations in docs
   - Rationale: Users deploy on cloud; benchmarks on matching hardware more relevant

12. **Continuous benchmarking:**
   - System MAY run nightly benchmarks to detect performance regressions
   - Evidence: CI/CD pipeline includes benchmark job
   - Rationale: Prevent accidental performance degradation

---

## Database Schema

### benchmark_runs Table

```sql
CREATE TABLE benchmark_runs (
    run_id TEXT PRIMARY KEY,
    model_id TEXT NOT NULL,
    device TEXT NOT NULL,  -- cpu, cuda, cuda:0, mps
    batch_sizes TEXT NOT NULL,  -- JSON array
    iterations INTEGER NOT NULL,
    corpus_category TEXT,  -- tiny, small, medium, large
    purpose TEXT NOT NULL,  -- development, regression, production, comparison
    tags TEXT,  -- JSON array
    total_duration_seconds REAL NOT NULL,
    timestamp_utc TEXT NOT NULL,
    metadata TEXT,  -- JSON object
    FOREIGN KEY (model_id) REFERENCES models(model_id)
);
```

### benchmark_results Table

```sql
CREATE TABLE benchmark_results (
    result_id INTEGER PRIMARY KEY,
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
    bleu_score REAL,  -- BM-04: Quality metrics
    comet_score REAL,
    chrf_score REAL,
    errors TEXT,  -- JSON array
    FOREIGN KEY (run_id) REFERENCES benchmark_runs(run_id)
);
```

### system_info Table

```sql
CREATE TABLE system_info (
    run_id TEXT PRIMARY KEY,
    cpu_model TEXT NOT NULL,
    cpu_cores INTEGER NOT NULL,
    total_ram_gb REAL NOT NULL,
    gpu_name TEXT,
    gpu_memory_gb REAL,
    os_name TEXT NOT NULL,
    python_version TEXT NOT NULL,
    pytorch_version TEXT NOT NULL,
    transformers_version TEXT NOT NULL,
    timestamp_utc TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES benchmark_runs(run_id)
);
```

---

## Configuration

### config/benchmarking.yaml

```yaml
# Database configuration
database:
  path: "data/benchmarks/benchmarks.db"
  production_path: "data/benchmarks/production.db"

# Production metrics integration
production:
  record_enabled: false  # OPT-IN: Must be explicitly enabled
  min_segments_to_record: 10
  drift_detection_enabled: true
  drift_threshold_percent: 20

# Resource-aware scheduling
scheduler:
  max_cpu_percent: 80
  max_memory_percent: 85
  max_gpu_memory_percent: 90
  min_available_memory_mb: 1024
  default_timeout_seconds: 3600
  poll_interval_seconds: 5

# Quality benchmarking (BM-04)
quality:
  default_corpus: "data/quality_corpus/wmt_newstest_2022.json"
  metrics: [bleu, comet, chrf]
  min_samples_per_language: 100
```

### config/global.yaml (Model Cache)

```yaml
# Model storage and caching (REQ-BM-06)
model_cache:
  cache_dir: null  # null = use platform default (~/.cache/huggingface/)
  max_size_gb: 50
  auto_cleanup: true
  preserve_days: 30  # Keep models used in last 30 days
```

### config/test_models.yaml (Parameterized Tests)

```yaml
# Test model selection (REQ-BM-05)
default_test_model: m2m100_418m
alternative_test_models:
  - opus_en_fr
  - small100
  - nllb_200_600m

test_model_requirements:
  min_languages: 2
  max_size_mb: 2000
```

---

## Evidence Requirements

### For REQ-BM-01 (All Models Benchmarked)

**Query:**
```sql
SELECT
    m.model_id,
    COUNT(br.run_id) as benchmark_runs,
    MAX(br.timestamp_utc) as last_benchmarked
FROM models m
LEFT JOIN benchmark_runs br ON m.model_id = br.model_id
GROUP BY m.model_id;
```

**Expected:** Every model has ≥1 run, last_benchmarked within 90 days

---

### For REQ-BM-03 (Speed AND Quality)

**Query:**
```sql
SELECT
    model_id,
    COUNT(*) as total_results,
    AVG(throughput_tokens_per_sec) as avg_throughput,
    AVG(bleu_score) as avg_bleu,
    AVG(comet_score) as avg_comet
FROM benchmark_results
WHERE bleu_score IS NOT NULL  -- Quality metrics populated
GROUP BY model_id;
```

**Expected:** All models have non-NULL quality scores, throughput > 0

---

### For REQ-BM-04 (Real Data Only)

**Documentation Audit:**
```bash
# Find any performance claims without source attribution
grep -r "tokens/sec\|BLEU score\|throughput" docs/ \
  | grep -v "Measured on" \
  | grep -v "Source:" \
  | grep -v "TBD"
```

**Expected:** Zero results (all claims sourced or marked TBD)

**Database Check:**
```sql
SELECT COUNT(*) FROM benchmark_runs
WHERE timestamp_utc > date('now', '-30 days');
```

**Expected:** > 0 (recent benchmark runs exist)

---

### For REQ-BM-05 (No Hardcoded Models)

**Test Audit:**
```bash
grep -rn 'model_id.*=.*"m2m100\|opus\|nllb"' tests/ \
  | grep -v conftest.py \
  | grep -v "# Example"
```

**Expected:** 0 results

**Pytest Override:**
```bash
pytest tests/unit/phase-4/test_loader.py --test-model=small100 -v
```

**Expected:** All tests pass with different model

---

### For REQ-BM-06 (Storage Strategy)

**Documentation:**
```bash
test -f docs/operations/model-storage.md && echo "EXISTS" || echo "MISSING"
```

**Expected:** EXISTS

**Cache Management:**
```bash
python scripts/manage_model_cache.py --list | grep -E "Cache location|Total cache size"
```

**Expected:** Shows cache location and total size

---

## Known Issues & Gaps

### Critical (Blocking)

1. **BM-G01: Zero real benchmark data**
   - Status: Database initialized, schema v5, but 0 rows
   - Impact: Users have no performance data
   - Fix: Execute BM-01 (first real benchmark suite)

2. **BM-G02: Theoretical benchmarks in docs**
   - Status: All perf numbers in docs are fabricated/estimated
   - Impact: Misleading users about actual performance
   - Fix: Execute BM-02 (remove theoretical data)

3. **BM-G03: GPU benchmarks failing**
   - Status: 4/4 GPU configs crashed on 2025-12-20
   - Impact: Cannot benchmark GPU performance
   - Fix: Execute BM-03 (debug subprocess failures)

4. **BM-G04: No quality metrics**
   - Status: BLEU/COMET not implemented
   - Impact: Cannot evaluate translation accuracy
   - Fix: Execute BM-04 (implement quality metrics)

### High Priority

5. **BM-G05: Hardcoded model names in tests**
   - Status: 28+ test files hardcode "m2m100_418m"
   - Impact: Tests brittle, don't work with new models
   - Fix: Execute BM-05 (parameterize tests)

6. **BM-G06: Limited model coverage**
   - Status: Only 3/12 models tested (25%)
   - Impact: Incomplete comparative data
   - Fix: Execute BM-06 (model discovery), BM-07 (comprehensive benchmarks)

7. **BM-G07: No model storage docs**
   - Status: Users don't know where models stored
   - Impact: Disk space issues, cache bloat
   - Fix: Execute BM-08 (storage strategy)

8. **BM-G08: No model discovery**
   - Status: Static registry, manual curation only
   - Impact: Missing new high-quality models
   - Fix: Execute BM-06 (discovery system)

9. **BM-G09: No reference corpus**
   - Status: No WMT/quality corpus for BLEU scoring
   - Impact: Cannot compute quality metrics
   - Fix: Execute BM-09 (create quality corpus)

---

## Success Criteria

### Phase 1: Foundation (Week 1)

- [ ] BM-01: Database populated with ≥10 real benchmark runs
- [ ] BM-02: All theoretical benchmarks removed from docs
- [ ] BM-03: GPU benchmarks execute without crashes
- [ ] BM-09: WMT newstest corpus downloaded and validated

**Exit Criteria:** Database query shows real data, docs show "TBD" or sourced data only

### Phase 2: Quality Metrics (Week 2)

- [ ] BM-04: BLEU/COMET/chrF implemented and tested
- [ ] All models have quality scores in database
- [ ] Quality vs speed comparison report generated

**Exit Criteria:** Query returns quality scores for all models

### Phase 3: Comprehensive Coverage (Week 3)

- [ ] BM-05: Tests parameterized, pytest --test-model works
- [ ] BM-06: Model discovery finds ≥50 HF models
- [ ] BM-07: All registered models benchmarked (speed + quality)
- [ ] BM-08: Model storage guide published, cache management working

**Exit Criteria:** All 6 user requirements met, database has 100+ runs

---

## Related Documentation

- [Model Selection Criteria](../../docs/guides/model-selection-criteria.md) - Model comparison (currently theoretical)
- [CPU Benchmarks](../../docs/performance/cpu-benchmarks.md) - CPU performance (currently theoretical)
- [Benchmarking Operations](../../docs/operations/benchmarking-operations.md) - Operational procedures
- [Model Storage](../../docs/operations/model-storage.md) - Storage strategy (to be created)

---

## References

- User requirements specified 2025-12-27
- Gap analysis from system inquiry (model layer exploration)
- Failed benchmark attempts: reports/benchmark_production_20251220_210900.md
- WMT datasets: https://www.statmt.org/wmt22/
- HuggingFace Hub API: https://huggingface.co/docs/huggingface_hub
- sacrebleu (BLEU scoring): https://github.com/mjpost/sacrebleu
- COMET (quality estimation): https://github.com/Unbabel/COMET

---

**Last Review:** 2025-12-27
**Next Review:** After BM-01 through BM-09 completion
