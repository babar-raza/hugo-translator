# 36 Language Coverage Specification

**Version:** 1.0
**Status:** Production-Ready
**Last Updated:** 2025-12-28
**Parent:** [REQUIREMENTS.md](../REQUIREMENTS.md)

## Executive Summary

This specification defines the complete model coverage strategy for translating English content to all 36 target languages supported by the Hugo Translation System. It ensures every language has at least one functional translation model and provides guidance for optimal model selection per language.

> **Scope note:** this is a model/registry-level requirement — every
> language in the catalog must have a working model. It does not mean
> every site translates to all 36 languages. Aspose.org site profiles are
> restricted to a 25-target-locale subset (26 with the `en` source); see
> `docs/languages/ASPOSE_ORG_LOCALE_POLICY.md` for that per-site contract.

## Table of Contents

1. [Language Requirements](#language-requirements)
2. [Model Coverage Matrix](#model-coverage-matrix)
3. [Model Selection Strategy](#model-selection-strategy)
4. [Language-Specific Considerations](#language-specific-considerations)
5. [Quality Dimensions](#quality-dimensions)
6. [Acceptance Criteria](#acceptance-criteria)
7. [Implementation Guidance](#implementation-guidance)

---

## Language Requirements

### LANG-REQ-001: Complete Language Coverage
**Priority:** P0 (Critical)

The system MUST support translation from English (en) to all 36 target languages:

| Code | Language | Script | Family | Priority | Notes |
|------|----------|--------|--------|----------|-------|
| ar | Arabic | Arabic | Semitic | P0 | RTL, complex morphology |
| bg | Bulgarian | Cyrillic | Slavic | P1 | Cyrillic script |
| ca | Catalan | Latin | Romance | P2 | Similar to Spanish |
| cs | Czech | Latin | Slavic | P1 | Complex inflection |
| da | Danish | Latin | Germanic | P1 | Similar to Norwegian |
| de | German | Latin | Germanic | P0 | High-resource language |
| el | Greek | Greek | Hellenic | P1 | Unique script |
| es | Spanish | Latin | Romance | P0 | High-resource language |
| fa | Persian (Farsi) | Arabic | Iranian | P1 | RTL, different from Arabic |
| fi | Finnish | Latin | Uralic | P1 | Complex morphology |
| fr | French | Latin | Romance | P0 | High-resource language |
| he | Hebrew | Hebrew | Semitic | P1 | RTL |
| hi | Hindi | Devanagari | Indo-Aryan | P1 | Complex script |
| hr | Croatian | Latin | Slavic | P2 | Similar to Serbian |
| hu | Hungarian | Latin | Uralic | P1 | Complex morphology |
| id | Indonesian | Latin | Austronesian | P1 | Similar to Malay |
| it | Italian | Latin | Romance | P0 | High-resource language |
| ja | Japanese | Kanji/Kana | Japonic | P0 | Complex script, high-resource |
| ko | Korean | Hangul | Koreanic | P1 | Unique script |
| lt | Lithuanian | Latin | Baltic | P2 | Low-resource |
| lv | Latvian | Latin | Baltic | P2 | Low-resource |
| ms | Malay | Latin | Austronesian | P2 | Similar to Indonesian |
| nl | Dutch | Latin | Germanic | P1 | Similar to German |
| no | Norwegian | Latin | Germanic | P1 | Similar to Danish |
| pl | Polish | Latin | Slavic | P1 | Complex orthography |
| pt | Portuguese | Latin | Romance | P0 | High-resource language |
| ro | Romanian | Latin | Romance | P1 | Latin-based Romance |
| ru | Russian | Cyrillic | Slavic | P0 | High-resource language |
| sk | Slovak | Latin | Slavic | P2 | Similar to Czech |
| sr | Serbian | Cyrillic/Latin | Slavic | P2 | Dual script |
| sv | Swedish | Latin | Germanic | P1 | Similar to Norwegian |
| th | Thai | Thai | Tai-Kadai | P1 | Complex script, no spaces |
| tr | Turkish | Latin | Turkic | P1 | Agglutinative |
| uk | Ukrainian | Cyrillic | Slavic | P1 | Similar to Russian |
| vi | Vietnamese | Latin | Austroasiatic | P1 | Tonal, diacritics |
| zh | Chinese | Simplified Han | Sinitic | P0 | High-resource, ideographic |

**Language Priority Classification:**
- **P0 (Critical):** High-traffic languages (ar, de, es, fr, it, ja, pt, ru, zh) - 9 languages
- **P1 (High):** Medium-traffic languages - 18 languages
- **P2 (Medium):** Low-traffic or linguistically similar to P1 languages - 9 languages

**Total:** 36 languages

---

## Model Coverage Matrix

### MATRIX-001: Model-Language Compatibility

This matrix shows which models support which languages:

| Model ID | Coverage | Supported Languages | Notes |
|----------|----------|---------------------|-------|
| **Multilingual Models (Support All 36)** |
| `m2m100_418m` | All 36 | ✓ All | Default model, good balance |
| `m2m100_418m_ct2` | All 36 | ✓ All | Optimized version (2x faster) |
| `m2m100_418m_ct2_int8` | All 36 | ✓ All | Quantized (8x smaller, ~1% quality loss) |
| `m2m100_1.2b` | All 36 | ✓ All | Higher quality, requires GPU |
| `nllb_200_600m` | All 36 | ✓ All | Best for low-resource languages |
| `nllb_200_600m_ct2_int8` | All 36 | ✓ All | NLLB optimized |
| `nllb_200_1.3b` | All 36 | ✓ All | Highest quality, requires GPU |
| `small100` | All 36 | ✓ All | Compact multilingual model |
| **Specialized Models (Limited Coverage)** |
| `opus_en_fr` | 1 | fr | French only, very fast |
| `opus_en_es` | 1 | es | Spanish only, very fast |
| `opus_en_de` | 1 | de | German only, very fast |
| `marian_en_romance` | 5 | fr, es, it, pt, ro | Romance languages |

**Coverage Summary:**
- **8 models** support all 36 languages (multilingual)
- **4 models** support 1-5 languages (specialized)
- **Every language** has at least 8 model options

### MATRIX-002: Recommended Model per Language

Based on benchmarking data (expected), recommended models:

| Language | P0 Model (Default) | P1 Model (Quality) | P2 Model (Speed) | Notes |
|----------|-------------------|-------------------|------------------|-------|
| ar | m2m100_418m_ct2_int8 | nllb_200_600m | m2m100_418m_ct2 | NLLB better for Arabic |
| bg | m2m100_418m_ct2_int8 | nllb_200_600m | m2m100_418m_ct2 | |
| ca | m2m100_418m_ct2_int8 | marian_en_romance | m2m100_418m_ct2 | Marian if Romance-focused |
| cs | m2m100_418m_ct2_int8 | nllb_200_600m | m2m100_418m_ct2 | |
| da | m2m100_418m_ct2_int8 | m2m100_1.2b | m2m100_418m_ct2 | |
| de | opus_en_de | m2m100_1.2b | m2m100_418m_ct2 | Opus very fast for German |
| el | m2m100_418m_ct2_int8 | nllb_200_600m | m2m100_418m_ct2 | |
| es | opus_en_es | marian_en_romance | m2m100_418m_ct2 | Opus or Marian for Spanish |
| fa | nllb_200_600m_ct2_int8 | nllb_200_1.3b | m2m100_418m_ct2 | NLLB better for Persian |
| fi | m2m100_418m_ct2_int8 | nllb_200_600m | m2m100_418m_ct2 | |
| fr | opus_en_fr | marian_en_romance | m2m100_418m_ct2 | Opus very fast for French |
| he | nllb_200_600m_ct2_int8 | nllb_200_1.3b | m2m100_418m_ct2 | NLLB better for Hebrew |
| hi | nllb_200_600m_ct2_int8 | nllb_200_1.3b | m2m100_418m_ct2 | NLLB better for Hindi |
| hr | m2m100_418m_ct2_int8 | nllb_200_600m | m2m100_418m_ct2 | |
| hu | m2m100_418m_ct2_int8 | nllb_200_600m | m2m100_418m_ct2 | |
| id | m2m100_418m_ct2_int8 | nllb_200_600m | m2m100_418m_ct2 | |
| it | marian_en_romance | m2m100_1.2b | m2m100_418m_ct2 | Marian good for Italian |
| ja | m2m100_418m_ct2_int8 | m2m100_1.2b | m2m100_418m_ct2 | High-resource language |
| ko | m2m100_418m_ct2_int8 | nllb_200_600m | m2m100_418m_ct2 | |
| lt | nllb_200_600m_ct2_int8 | nllb_200_1.3b | m2m100_418m_ct2 | Low-resource, NLLB better |
| lv | nllb_200_600m_ct2_int8 | nllb_200_1.3b | m2m100_418m_ct2 | Low-resource, NLLB better |
| ms | m2m100_418m_ct2_int8 | nllb_200_600m | m2m100_418m_ct2 | |
| nl | m2m100_418m_ct2_int8 | m2m100_1.2b | m2m100_418m_ct2 | |
| no | m2m100_418m_ct2_int8 | m2m100_1.2b | m2m100_418m_ct2 | |
| pl | m2m100_418m_ct2_int8 | nllb_200_600m | m2m100_418m_ct2 | |
| pt | marian_en_romance | m2m100_1.2b | m2m100_418m_ct2 | Marian good for Portuguese |
| ro | marian_en_romance | nllb_200_600m | m2m100_418m_ct2 | Marian supports Romanian |
| ru | m2m100_418m_ct2_int8 | m2m100_1.2b | m2m100_418m_ct2 | High-resource language |
| sk | m2m100_418m_ct2_int8 | nllb_200_600m | m2m100_418m_ct2 | |
| sr | m2m100_418m_ct2_int8 | nllb_200_600m | m2m100_418m_ct2 | |
| sv | m2m100_418m_ct2_int8 | m2m100_1.2b | m2m100_418m_ct2 | |
| th | nllb_200_600m_ct2_int8 | nllb_200_1.3b | m2m100_418m_ct2 | NLLB better for Thai |
| tr | m2m100_418m_ct2_int8 | nllb_200_600m | m2m100_418m_ct2 | |
| uk | m2m100_418m_ct2_int8 | nllb_200_600m | m2m100_418m_ct2 | |
| vi | m2m100_418m_ct2_int8 | nllb_200_600m | m2m100_418m_ct2 | |
| zh | m2m100_418m_ct2_int8 | m2m100_1.2b | m2m100_418m_ct2 | High-resource language |

**Recommendation Logic:**
- **P0 (Default):** Best balance of speed, quality, memory (production default)
- **P1 (Quality):** Best quality for language (may require GPU/more resources)
- **P2 (Speed):** Fastest model for language (CPU-friendly)

---

## Model Selection Strategy

### STRATEGY-001: Fallback Chain

If a model fails to load or translate, fall back to next model in chain:

**Primary Fallback Chain (All Languages):**
1. `m2m100_418m_ct2_int8` (Default, fast, small)
2. `m2m100_418m_ct2` (Faster, slightly larger)
3. `m2m100_418m` (Original, larger, slower)
4. `nllb_200_600m_ct2_int8` (Alternative multilingual)
5. `small100` (Last resort, smallest)

**Language-Specific Fallback Examples:**

**French (fr):**
1. `opus_en_fr` (Specialized, fastest)
2. `marian_en_romance` (Romance languages)
3. `m2m100_418m_ct2_int8` (Default)
4. `m2m100_418m` (Fallback)

**Low-Resource Languages (lt, lv):**
1. `nllb_200_600m_ct2_int8` (Best for low-resource)
2. `nllb_200_1.3b` (Higher quality)
3. `m2m100_418m_ct2_int8` (Fallback)

**Implementation:**
```python
class ModelSelector:
    FALLBACK_CHAINS = {
        "fr": ["opus_en_fr", "marian_en_romance", "m2m100_418m_ct2_int8", "m2m100_418m"],
        "es": ["opus_en_es", "marian_en_romance", "m2m100_418m_ct2_int8", "m2m100_418m"],
        "de": ["opus_en_de", "m2m100_418m_ct2_int8", "m2m100_418m"],
        "default": ["m2m100_418m_ct2_int8", "m2m100_418m_ct2", "m2m100_418m", "nllb_200_600m_ct2_int8"]
    }

    def select_model(self, language, constraints=None):
        """Select best model for language based on constraints."""
        chain = self.FALLBACK_CHAINS.get(language, self.FALLBACK_CHAINS["default"])

        for model_id in chain:
            model = self.registry.get_model(model_id)

            # Check constraints (memory, device, etc.)
            if constraints and not self.meets_constraints(model, constraints):
                continue

            # Check if model supports language
            if model.supports_language(language):
                return model

        raise NoModelAvailableError(f"No model available for language: {language}")
```

### STRATEGY-002: Auto-Selection Based on Hardware

Select model based on available hardware:

**GPU Available (8GB+ VRAM):**
- High-resource languages (de, fr, es, zh, ja): `m2m100_1.2b` or `nllb_200_1.3b`
- Low-resource languages (lt, lv, fa, th): `nllb_200_1.3b`
- Other languages: `m2m100_418m` (GPU mode)

**GPU Available (4-8GB VRAM):**
- All languages: `m2m100_418m` or `nllb_200_600m` (GPU mode)

**CPU Only:**
- Specialized models if available (opus_en_fr, opus_en_es, opus_en_de)
- Otherwise: `m2m100_418m_ct2_int8` (fastest on CPU)

**Low Memory (<8GB RAM):**
- All languages: `m2m100_418m_ct2_int8` or `small100`

**Implementation:**
```python
def auto_select_model(language, hardware_info):
    """Auto-select best model based on hardware."""
    if hardware_info.gpu_available and hardware_info.vram_gb >= 8:
        # High-end GPU
        if language in ["de", "fr", "es", "zh", "ja", "ru"]:
            return "m2m100_1.2b"
        elif language in ["lt", "lv", "fa", "th", "ar", "he", "hi"]:
            return "nllb_200_1.3b"
        else:
            return "m2m100_418m"

    elif hardware_info.gpu_available and hardware_info.vram_gb >= 4:
        # Mid-range GPU
        if language in ["lt", "lv", "fa", "th"]:
            return "nllb_200_600m"
        else:
            return "m2m100_418m"

    else:
        # CPU only
        specialized = {
            "fr": "opus_en_fr",
            "es": "opus_en_es",
            "de": "opus_en_de"
        }

        if language in specialized:
            return specialized[language]
        else:
            return "m2m100_418m_ct2_int8"
```

---

## Language-Specific Considerations

### LANG-001: Right-to-Left (RTL) Languages

Languages: **ar, fa, he**

**Considerations:**
- Text directionality in output files
- Special handling for mixed RTL/LTR content (e.g., English terms in Arabic text)
- NLLB models generally perform better for RTL languages

**Recommendation:**
- Prefer `nllb_200_600m_ct2_int8` or `nllb_200_1.3b`
- Fallback to `m2m100_418m` if NLLB unavailable

### LANG-002: Low-Resource Languages

Languages: **lt, lv, ms, sr, sk, ca, hr**

**Considerations:**
- Limited training data in most models
- NLLB (No Language Left Behind) specifically designed for low-resource languages
- Higher risk of hallucination or poor quality

**Recommendation:**
- Primary: `nllb_200_600m_ct2_int8` or `nllb_200_1.3b`
- Fallback: `m2m100_418m`
- Quality monitoring: Track BLEU scores and manual reviews

### LANG-003: Complex Scripts

Languages: **ar, fa, he** (Arabic script), **hi** (Devanagari), **ja** (Kanji/Kana), **ko** (Hangul), **th** (Thai), **zh** (Simplified Han), **el** (Greek)

**Considerations:**
- Tokenization complexity
- Character encoding (UTF-8 critical)
- Model must have strong training data for script

**Recommendation:**
- High-resource scripts (ja, zh, ko, hi): `m2m100_418m` or `m2m100_1.2b`
- Others: `nllb_200_600m` (better script handling)

### LANG-004: Romance Languages

Languages: **fr, es, it, pt, ro, ca**

**Considerations:**
- High linguistic similarity
- Specialized model available: `marian_en_romance`
- Can share translation memory across Romance languages

**Recommendation:**
- If translating multiple Romance languages: `marian_en_romance`
- For single language: Specialized models (`opus_en_fr`, `opus_en_es`)
- Fallback: `m2m100_418m_ct2_int8`

### LANG-005: Slavic Languages

Languages: **ru, pl, cs, bg, uk, hr, sr, sk**

**Considerations:**
- Complex morphology and inflection
- Cyrillic vs Latin script (bg, ru, uk use Cyrillic; others use Latin)
- Serbian uses both scripts

**Recommendation:**
- High-resource (ru, pl): `m2m100_418m` or `m2m100_1.2b`
- Others: `nllb_200_600m` (better morphology handling)

---

## Quality Dimensions

### 1. Completeness (5/5)
**Measurement:**
- [ ] All 36 languages have at least one working model
- [ ] All 36 languages tested in benchmarks
- [ ] No language left without translation capability

**Validation:**
```python
def test_language_coverage():
    required_languages = {"ar", "bg", "ca", ..., "zh"}  # 36 languages
    covered_languages = set()

    for model in registry.get_all_models():
        if model.supported_pairs == "all":
            covered_languages.update(required_languages)
        else:
            for (src, tgt) in model.supported_pairs:
                if src == "en":
                    covered_languages.add(tgt)

    assert covered_languages == required_languages, f"Missing: {required_languages - covered_languages}"
```

### 2. Quality (4/5)
**Measurement:**
- [ ] High-resource languages achieve BLEU ≥30
- [ ] Low-resource languages achieve BLEU ≥20
- [ ] Manual review: ≥80% translations acceptable

**Benchmarking:**
- Collect BLEU scores for all 36 languages
- Compare across models to identify best per language

### 3. Flexibility (5/5)
**Measurement:**
- [ ] Users can override model selection per language
- [ ] Fallback mechanism prevents translation failures
- [ ] Hardware-aware auto-selection supported

**Configuration Example:**
```yaml
# config/site_profiles/custom.yaml
language_model_overrides:
  fr: opus_en_fr        # Use specialized French model
  es: opus_en_es        # Use specialized Spanish model
  default: m2m100_418m  # All other languages
```

### 4. Maintainability (5/5)
**Measurement:**
- [ ] New models added via registry only (no code changes)
- [ ] New languages added via site profiles only
- [ ] Model recommendations data-driven (benchmarks)

### 5. Reliability (5/5)
**Measurement:**
- [ ] Fallback chain prevents zero-coverage scenarios
- [ ] Model load failures do not crash system
- [ ] Language code validation prevents invalid requests

**Error Handling:**
```python
try:
    model = selector.select_model(language="fr")
except NoModelAvailableError:
    logger.error("No model available for French, using fallback")
    model = selector.select_model(language="fr", fallback=True)
```

---

## Acceptance Criteria

### Functional Acceptance

1. **Complete Coverage**
   - [ ] All 36 languages translatable with at least one model
   - [ ] Benchmark data collected for all 36 languages
   - [ ] No language shows zero translation results

2. **Model Selection**
   - [ ] Auto-selection chooses optimal model based on hardware
   - [ ] Fallback chain prevents translation failures
   - [ ] Language-specific overrides functional

3. **Quality Validation**
   - [ ] High-resource languages: BLEU ≥30 (avg)
   - [ ] Low-resource languages: BLEU ≥20 (avg)
   - [ ] Manual review: ≥80% acceptable quality

### Non-Functional Acceptance

4. **Performance**
   - [ ] Model selection completes in <100ms
   - [ ] Fallback chain traversal in <50ms per model

5. **Usability**
   - [ ] Users can query best model for language via CLI
   - [ ] Dashboard shows recommended models per language

6. **Maintainability**
   - [ ] Add new model: Update registry only (zero code changes)
   - [ ] Add new language: Update site profile only

---

## Implementation Guidance

### Model Selection API

```python
# src/model_runtime/selector.py

from dataclasses import dataclass
from typing import Optional, List

@dataclass
class HardwareInfo:
    gpu_available: bool
    vram_gb: float
    ram_gb: float
    cpu_cores: int

class ModelSelector:
    def __init__(self, registry_path="config/model_registry.yaml"):
        self.registry = ModelRegistry.load(registry_path)

    def select_best_model(
        self,
        language: str,
        priority: str = "balanced",  # balanced, speed, quality, memory
        hardware: Optional[HardwareInfo] = None
    ) -> str:
        """Select best model for language and priority."""
        if hardware is None:
            hardware = self.detect_hardware()

        if priority == "balanced":
            return self._select_balanced(language, hardware)
        elif priority == "speed":
            return self._select_fastest(language, hardware)
        elif priority == "quality":
            return self._select_best_quality(language, hardware)
        elif priority == "memory":
            return self._select_smallest(language, hardware)
        else:
            raise ValueError(f"Unknown priority: {priority}")

    def _select_balanced(self, language, hardware):
        """Select best balance of speed, quality, memory."""
        # Check for specialized models first
        specialized = {
            "fr": "opus_en_fr",
            "es": "opus_en_es",
            "de": "opus_en_de"
        }

        if language in specialized:
            return specialized[language]

        # Low-resource languages: Prefer NLLB
        low_resource = {"lt", "lv", "fa", "th", "ar", "he", "hi"}
        if language in low_resource:
            return "nllb_200_600m_ct2_int8"

        # Default: M2M100 INT8 (best balance)
        return "m2m100_418m_ct2_int8"

    def get_fallback_chain(self, language: str) -> List[str]:
        """Get fallback model chain for language."""
        # Language-specific chains
        specialized_chains = {
            "fr": ["opus_en_fr", "marian_en_romance", "m2m100_418m_ct2_int8"],
            "es": ["opus_en_es", "marian_en_romance", "m2m100_418m_ct2_int8"],
            "de": ["opus_en_de", "m2m100_418m_ct2_int8"],
            "it": ["marian_en_romance", "m2m100_418m_ct2_int8"],
            "pt": ["marian_en_romance", "m2m100_418m_ct2_int8"],
            "ro": ["marian_en_romance", "m2m100_418m_ct2_int8"],
        }

        if language in specialized_chains:
            return specialized_chains[language]

        # Default fallback chain
        return [
            "m2m100_418m_ct2_int8",
            "m2m100_418m_ct2",
            "m2m100_418m",
            "nllb_200_600m_ct2_int8",
            "small100"
        ]
```

### CLI Query Command

```bash
# Query best model for language
translate-hugo model-query --language fr
# Output:
# Best Model for French (fr):
#   Model ID:     opus_en_fr
#   Backend:      HuggingFace
#   Size:         300 MB
#   Device:       CPU
#   Throughput:   ~85 seg/sec (CPU)
#   BLEU Score:   ~36.5
#   Fallback:     marian_en_romance, m2m100_418m_ct2_int8

# Query with priority
translate-hugo model-query --language ja --priority quality
# Output:
# Best Model for Japanese (ja) [Quality Priority]:
#   Model ID:     m2m100_1.2b
#   Backend:      HuggingFace
#   Size:         4.8 GB
#   Device:       GPU (recommended)
#   Throughput:   ~42 seg/sec (GPU)
#   BLEU Score:   ~38.2
#   Note:         Requires GPU with ≥6GB VRAM

# Query all languages
translate-hugo model-query --all --format csv > language_coverage.csv
```

### Language Coverage Report

```python
# scripts/generate_coverage_report.py

from src.model_runtime.registry import ModelRegistry
from src.model_runtime.selector import ModelSelector

def generate_coverage_report():
    """Generate language coverage report."""
    registry = ModelRegistry.load("config/model_registry.yaml")
    selector = ModelSelector()

    languages = ["ar", "bg", "ca", ..., "zh"]  # 36 languages

    print("Language Coverage Report")
    print("=" * 80)
    print(f"{'Language':<12} {'ISO':<6} {'Model Count':<15} {'Recommended Model':<30}")
    print("-" * 80)

    for lang in languages:
        # Count supporting models
        model_count = 0
        for model in registry.get_all_models():
            if model.supports_language(lang):
                model_count += 1

        # Get recommended model
        recommended = selector.select_best_model(lang, priority="balanced")

        lang_name = LANGUAGE_NAMES.get(lang, lang)
        print(f"{lang_name:<12} {lang:<6} {model_count:<15} {recommended:<30}")

    print("=" * 80)
    print(f"Total Languages: {len(languages)}")
    print(f"Total Models: {len(registry.get_all_models())}")
```

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-12-28 | System | Initial specification |

---

## Related Specifications

- [REQUIREMENTS.md](../REQUIREMENTS.md) - Parent requirements
- [ORGANIZATION.md](ORGANIZATION.md) - Model directory structure
- [COVERAGE_REQUIREMENTS.md](../benchmarking/COVERAGE_REQUIREMENTS.md) - Benchmark coverage
