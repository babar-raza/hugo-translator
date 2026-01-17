# Audit Summary - Hugo-Translator

**Date:** 2026-01-17
**Branch:** main
**Commit:** d0343a6

## Quick Overview

**Status:** ❌ CRITICAL GAPS FOUND

**Blocker Issues:** 1
**High Priority:** 3
**Medium Priority:** 4

---

## Critical Finding

🔴 **BLOCKER: Benchmarking System Hardcodes Language to EN→RU**

The benchmarking system in [src/benchmarking/runner.py:331-338](../../src/benchmarking/runner.py#L331) hardcodes `src_lang='en', tgt_lang='ru'` instead of iterating over all 36 target languages defined in [config/target_languages.yaml](../../config/target_languages.yaml).

**Impact:**
- Only Russian translation performance is measured
- Other 35 languages are never benchmarked
- Benchmark-based model recommendations are invalid for non-Russian languages
- Violates original spec of "36 languages × models × devices" matrix

---

## High Priority Gaps

1. **Database Schema Missing Language Columns**
   - Table `benchmark_results` has no `src_lang` or `tgt_lang` columns
   - Cannot query or analyze performance by language pair
   - File: [src/benchmarking/storage.py:249](../../src/benchmarking/storage.py#L249)

2. **No Automated Model Download**
   - Spec defines `python -m src.cli download-models --all` command
   - No implementation exists
   - Spec: [specs/models/ORGANIZATION.md:DL-001](../../specs/models/ORGANIZATION.md#DL-001)

3. **CT2 Conversion Not Automated**
   - CTranslate2 conversion is manual CLI only
   - No auto-convert on model load
   - File: [src/model_runtime/ct2_converter.py](../../src/model_runtime/ct2_converter.py)

---

## Medium Priority Gaps

1. **No Language-Aware Model Selection** - Loader accepts exact model_id only
2. **Model Manifest Missing** - No `models/model_manifest.json` tracking downloads
3. **Auto-Discovery Incomplete** - Produces metadata with zeros/hardcoded values
4. **No Checksum Verification** - Model integrity not verified after download

---

## What's Working ✅

- ✅ Test infrastructure (pytest with unit/integration/smoke/contract tests)
- ✅ E2E pipeline (translation → commit → telemetry)
- ✅ 36 target languages defined in config
- ✅ Model registry structure matches spec
- ✅ CT2 conversion tool exists (manual mode)

---

## Recommended Action Plan

### Phase 1: Fix Blocker (CRITICAL)
**Estimated Time:** 2-3 days

1. Add `src_lang`, `tgt_lang` to database schema (migration v10)
2. Parametrize `runner.run_benchmark()` with language args
3. Add CLI flags: `--source-lang`, `--target-lang`, `--all-languages`
4. Implement language iteration loop
5. Test all 36 languages

**Acceptance:** `python -m src.benchmarking.cli run --model m2m100_418m --all-languages` benchmarks all 36 languages

### Phase 2: Model Download (HIGH)
**Estimated Time:** 3-4 days

1. Create `ModelDownloader` class
2. Implement HuggingFace Hub download with resumption
3. Add model manifest management
4. Create CLI: `python -m src.cli download-models`
5. Add checksum verification

**Acceptance:** Models downloaded, verified, tracked in manifest

### Phase 3: CT2 Automation (HIGH)
**Estimated Time:** 2 days

1. Create `CT2EnsureStep` class
2. Auto-convert PyTorch→CT2 on first load
3. Cache converted models for reuse

**Acceptance:** Loading CT2 model auto-converts if not present

### Phase 4: Model Selection (MEDIUM)
**Estimated Time:** 1-2 days

1. Implement language-aware model selection
2. Prefer specialized models (e.g., opus_en_fr for EN→FR)
3. Fallback to multilingual models

**Acceptance:** Best model auto-selected per language pair

---

## Risk Assessment

- **Phase 1:** 🟢 LOW - Backward-compatible, well-tested
- **Phase 2:** 🟡 MEDIUM - Network dependencies, but mockable
- **Phase 3:** 🟢 LOW - Isolated change, existing converter proven
- **Phase 4:** 🟢 LOW - Optional feature

**Total Estimated Time:** 8-11 days (1.5-2 weeks)

---

## Files Examined

**Core Benchmarking:**
- src/benchmarking/runner.py (611 lines)
- src/benchmarking/storage.py (1120 lines)
- src/benchmarking/cli.py (partial)

**Model Management:**
- src/model_runtime/loader.py (949 lines)
- src/model_runtime/ct2_converter.py (301 lines)
- scripts/discover_hf_cache_models.py (136 lines)

**Specifications:**
- specs/models/ORGANIZATION.md (828 lines)
- config/model_registry.yaml
- config/target_languages.yaml

**Translation Engine:**
- src/translation_engine/engine.py (partial)
- src/cli.py (partial)

**Total Files Read:** 10+
**Total Lines Analyzed:** 4000+

---

## Next Steps

1. **Review** this audit with team
2. **Approve** implementation plan (or request changes)
3. **Begin** Phase 1 implementation
4. **Gate** each phase with tests before proceeding

---

For detailed analysis, see [AUDIT.md](./AUDIT.md)
For command history, see [COMMANDS_USED.txt](./COMMANDS_USED.txt)
