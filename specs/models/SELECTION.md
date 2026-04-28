# Language-Aware Model Selection

**Feature ID:** PROD-004
**Agent:** Agent-E (Feature Development)
**Status:** IMPLEMENTED
**Date:** 2026-01-17

---

## Overview

The Language-Aware Model Selector automatically chooses the best translation model for each language pair, considering:
- Language-specific Opus models (preferred for supported pairs)
- Multilingual models (fallback for unsupported language pairs)
- Hardware constraints (RAM, VRAM, device compatibility)
- Quality vs speed trade-offs

This eliminates the need for manual model specification and provides optimal translation quality for each language.

---

## Selection Strategy

The selector follows a priority-based selection strategy:

### Priority 1: Opus-Specific Model
**When:** Language pair has a dedicated Opus model (e.g., opus_en_fr for EN→FR)
**Why:** Highest quality for supported language pairs
**Applies to:** French (fr), Spanish (es), German (de) in production registry

### Priority 2: Multilingual Fallback
**When:** No Opus model available for language pair
**Why:** Supports all language pairs with acceptable quality
**Applies to:** All other 33 languages (Croatian, Korean, Polish, etc.)
**Models:** m2m100, nllb families

### Priority 3: Global Fallback
**When:** No Opus or multilingual models found, but global fallback configured
**Why:** Last resort to ensure translation succeeds
**Configuration:** `fallback_model` in global config

### Priority 4: Error
**When:** No suitable models found after all strategies
**Result:** ValueError with helpful suggestions

---

## Supported Languages

### Opus Models Available (Production Registry)
- **French (fr):** opus_en_fr
- **Spanish (es):** opus_en_es
- **German (de):** opus_en_de

### Multilingual Fallback (All Languages)
All 36 target languages supported via multilingual models:
- Arabic (ar), Bulgarian (bg), Catalan (ca), Czech (cs), Danish (da)
- Greek (el), Persian (fa), Finnish (fi), Hebrew (he), Hindi (hi)
- Croatian (hr), Hungarian (hu), Indonesian (id), Italian (it), Japanese (ja)
- Korean (ko), Lithuanian (lt), Latvian (lv), Malay (ms), Dutch (nl)
- Norwegian (no), Polish (pl), Portuguese (pt), Romanian (ro), Russian (ru)
- Slovak (sk), Serbian (sr), Swedish (sv), Thai (th), Turkish (tr)
- Ukrainian (uk), Vietnamese (vi), Chinese (zh)

---

## Usage

### CLI Flag

```bash
# Auto-select model for target language
translate-hugo --source input.md --target-langs fr --auto-select-model

# Auto-select for multiple languages
translate-hugo --source input.md --target-langs fr,hr,ko --auto-select-model

# Manual model override (backward compatible)
translate-hugo --source input.md --target-langs fr --model nllb_200_600m
```

### Programmatic Usage

```python
from src.model_runtime.selector import LanguageAwareModelSelector
from src.model_runtime.registry import ModelRegistry
from src.model_runtime.hardware import HardwareDetector

# Initialize selector
registry = ModelRegistry("config/model_registry.yaml")
hardware = HardwareDetector().detect()
selector = LanguageAwareModelSelector(registry, hardware)

# Select model for French (will use opus_en_fr if available)
selection = selector.select_for_language_pair("en", "fr")
print(f"Selected: {selection.model_info.model_id}")
print(f"Strategy: {selection.selection_strategy}")
print(f"Rationale: {selection.rationale}")

# Select model for Croatian (will use multilingual fallback)
selection = selector.select_for_language_pair("en", "hr")
print(f"Selected: {selection.model_info.model_id}")
```

---

## Selection Algorithm Details

### Hardware Filtering

All model candidates are filtered by hardware constraints:

**RAM Constraint:**
- Model `min_ram_gb` must be ≤ available system RAM
- Example: 2GB system excludes nllb_200_1.3b (requires 10GB)

**Device Compatibility:**
- CPU systems: Can run any model (will be slower for GPU-optimized models)
- GPU systems: Can run any model (CPU models also acceptable)
- Model `optimal_device` is a preference, not a hard requirement

**VRAM Constraint:**
- GPU models checked against available VRAM (if specified)
- Enforced via GPUManager during model loading

### Quality vs Speed Trade-offs

**Default (prefer_quality=False):**
- Prefers smaller, faster models
- Prioritizes CTranslate2 backend for CPU systems (2-4x speedup)
- Selects smallest model that fits constraints

**Quality Mode (prefer_quality=True):**
- Prefers larger models with more parameters
- Accepts slower inference for better translation quality
- Selects largest model that fits constraints

### CTranslate2 Optimization

For CPU systems, the selector strongly prefers CTranslate2 backend:
- **m2m100_418m_ct2** preferred over **m2m100_418m**
- 2x faster inference with 50% less memory
- Same quality, optimized for CPU execution

---

## Examples

### Example 1: French Translation (Opus Available)

```bash
$ translate-hugo --source doc.md --target-langs fr --auto-select-model
```

**Selection:**
- Model: `opus_en_fr`
- Strategy: `opus-specific`
- Rationale: "Language-specific Opus model for en→fr. Size: 300MB, Device: cpu"

### Example 2: Croatian Translation (No Opus)

```bash
$ translate-hugo --source doc.md --target-langs hr --auto-select-model
```

**Selection:**
- Model: `m2m100_418m_ct2`
- Strategy: `multilingual-fallback`
- Rationale: "Multilingual fallback (speed-optimized (CTranslate2)). Supports all language pairs. Size: 800MB, Backend: ctranslate2"

### Example 3: Multiple Languages

```bash
$ translate-hugo --source doc.md --target-langs fr,hr,ko --auto-select-model
```

**Selections:**
- **French:** `opus_en_fr` (Opus-specific)
- **Croatian:** `m2m100_418m_ct2` (Multilingual fallback)
- **Korean:** `m2m100_418m_ct2` (Multilingual fallback)

### Example 4: Low RAM System (2GB)

**System:** 2GB RAM, CPU-only

**Selection for French:**
- Model: `opus_en_fr` (1GB requirement, fits)
- Rejects: nllb_200_1.3b (10GB requirement, doesn't fit)

**Selection for Croatian:**
- Model: `m2m100_418m_ct2` (2GB requirement, fits)
- Rejects: m2m100_418m (4GB requirement, doesn't fit)
- Rejects: nllb_200_600m (6GB requirement, doesn't fit)

---

## Error Handling

### No Suitable Model Found

**Error Message:**
```
ValueError: No suitable model found for language pair: en→hr

Attempted strategies:
  1. Opus-specific model: Not found in registry
  2. Multilingual model: Not found or doesn't fit hardware constraints
  3. Global fallback: Not configured

Suggestions:
  - Install multilingual model (m2m100_418m or nllb_200_600m)
  - Increase hardware resources (current RAM: 2.0GB)
  - Manually specify model with --model flag
```

**Resolution:**
1. Install a multilingual model
2. Upgrade system RAM
3. Use `--model` flag to manually specify a model

### Conflicting Flags

**Error:**
```
Cannot use both --auto-select-model and --model flags. Please choose one.
```

**Resolution:**
Choose either auto-selection or manual model specification, not both.

---

## Configuration

### Registry Configuration

The selector uses `config/model_registry.yaml` for model definitions:

```yaml
models:
  - model_id: opus_en_fr
    supported_pairs: [["en", "fr"], ["fr", "en"]]
    min_ram_gb: 1.0
    # ...

  - model_id: m2m100_418m
    supported_pairs: all  # Multilingual
    min_ram_gb: 4.0
    # ...
```

### Global Fallback

Configure global fallback in `config/global.yaml`:

```yaml
model_defaults:
  fallback_model: m2m100_418m
```

---

## Limitations

### Current Limitations

1. **Opus Coverage:** Only 3 languages have Opus models in production registry (fr, es, de)
   - Auto-generated registry has 36 Opus models but is not loaded by default
   - Other 33 languages use multilingual fallback

2. **Model Download:** Selector doesn't download models automatically
   - User must have models downloaded before translation
   - Clear error message if model not found on disk

3. **Benchmark Integration:** Not yet integrated with benchmark-based selection
   - Future: Use historical benchmark data to refine selection

### Future Enhancements

1. **Load opus_autogen registry** to support all 36 languages with Opus models
2. **Benchmark-backed selection** using historical performance data
3. **Automatic model download** when selected model not found
4. **Multi-model ensemble** for critical translations
5. **Cost-aware selection** considering inference cost vs quality

---

## Backward Compatibility

### Manual Model Selection (Unchanged)

```bash
# Still works - manual model specification
translate-hugo --source input.md --target-langs fr --model nllb_200_600m
```

### Default Behavior (Unchanged)

```bash
# Still works - uses registry.recommend_model()
translate-hugo --source input.md --target-langs fr
```

### New Auto-Selection (Opt-In)

```bash
# New feature - requires explicit --auto-select-model flag
translate-hugo --source input.md --target-langs fr --auto-select-model
```

---

## Testing

### Unit Tests

All selector logic tested in `tests/unit/model_runtime/test_selector.py`:
- 11 comprehensive tests
- Coverage: Opus selection, multilingual fallback, hardware constraints, errors
- All tests passing

### Integration Tests

Tested with production registry and real hardware configurations:
- CPU systems (2GB, 8GB, 16GB RAM)
- GPU systems (with CUDA)
- All 36 target languages

### Manual Testing

```bash
# Test 1: Auto-select for French (should use Opus)
translate-hugo --source input.md --target-langs fr --auto-select-model

# Test 2: Auto-select for Croatian (should use multilingual)
translate-hugo --source input.md --target-langs hr --auto-select-model

# Test 3: Manual override still works
translate-hugo --source input.md --target-langs fr --model nllb_200_600m
```

---

## Performance

### Selection Overhead

- **Typical selection time:** <10ms
- **Negligible impact** on translation latency (model loading dominates)

### Memory Impact

- **Selector memory footprint:** <1MB
- **No model loading** during selection (metadata only)

---

## Related Documentation

- **Implementation Plan:** `reports/agents/agent-e/prod-004/plan.md`
- **Code Changes:** `reports/agents/agent-e/prod-004/changes.md`
- **Test Evidence:** `reports/agents/agent-e/prod-004/evidence.md`
- **Model Registry:** `config/model_registry.yaml`
- **Agent-A Discovery:** `reports/agents/agent-a/prod-000/verification_report.md`

---

**Last Updated:** 2026-01-17
**Status:** PRODUCTION READY
