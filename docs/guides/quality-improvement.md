# Translation Quality Improvement Guide
**Goal:** Achieve production-ready translations (8+/10 quality)
**Current State:** Draft-level (6.5/10 average)
**Target Audience:** Technical implementation team

---

## Executive Summary

To move from draft-level to production-ready translations, implement improvements in **three phases**:

1. **Quick Wins (1-3 days):** Terminology protection, post-processing filters, quality gates
2. **Medium-Term (1-2 weeks):** Model upgrade, hybrid workflow, quality scoring
3. **Long-Term (1+ months):** Fine-tuning, specialized models, feedback loops

**Expected Improvement:**
- Phase 1: 6.5/10 → 7.5/10 (+15% quality)
- Phase 2: 7.5/10 → 8.5/10 (+13% quality)
- Phase 3: 8.5/10 → 9.0/10 (+6% quality)

---

## Phase 1: Quick Wins (1-3 Days)

### 1.1 Implement Terminology Protection System

**Problem:** Technical terms incorrectly translated
- "namespace" → "nomespace" (French)
- "deployment" → "desplegadores" (Spanish - means "deployers")
- ".NET Framework" → ".Net Frames" (German)

**Solution:** Pre-translation term protection

#### Implementation:

**File:** `src/translation_engine/terminology/protection.py`

```python
"""Terminology protection for translation."""

from typing import Dict, List, Set
import re

class TerminologyProtector:
    """Protect technical terms from translation."""

    def __init__(self, terminology_config: Dict):
        self.protected_terms = self._load_protected_terms(terminology_config)
        self.placeholder_map = {}

    def _load_protected_terms(self, config: Dict) -> Set[str]:
        """Load terms that should not be translated."""
        terms = set()

        # Brand names
        terms.update([
            "Aspose.Slides", "Azure", "AWS", "GCP", "Docker", "Kubernetes",
            "PowerPoint", "Microsoft", "GitHub"
        ])

        # Technical terms
        terms.update([
            "namespace", "deployment", "boilerplate", "callback",
            "endpoint", "webhook", "middleware", "container"
        ])

        # Framework names
        terms.update([
            ".NET Framework", ".NET Core", ".NET 6.0", ".NET 7.0", ".NET 8.0",
            "NuGet", "C#", "VB.NET"
        ])

        # Programming constructs (case-sensitive)
        terms.update([
            "async", "await", "Task", "IEnumerable", "List",
            "Dictionary", "StringBuilder"
        ])

        # Load from config
        if "custom_terms" in config:
            terms.update(config["custom_terms"])

        return terms

    def protect(self, text: str) -> str:
        """Replace protected terms with placeholders before translation."""
        protected_text = text
        self.placeholder_map.clear()

        # Sort by length (longest first) to avoid partial matches
        sorted_terms = sorted(self.protected_terms, key=len, reverse=True)

        for idx, term in enumerate(sorted_terms):
            # Case-insensitive search for brands/frameworks
            # Case-sensitive for code identifiers
            if term[0].isupper() or "." in term:
                pattern = re.escape(term)
            else:
                pattern = re.escape(term)
                pattern = r'\b' + pattern + r'\b'

            placeholder = f"__PROTECTED_{idx}__"

            def replace_func(match):
                self.placeholder_map[placeholder] = match.group(0)
                return placeholder

            protected_text = re.sub(pattern, replace_func, protected_text, flags=re.IGNORECASE)

        return protected_text

    def restore(self, translated_text: str) -> str:
        """Restore protected terms after translation."""
        restored_text = translated_text

        for placeholder, original in self.placeholder_map.items():
            restored_text = restored_text.replace(placeholder, original)

        return restored_text


# Integration with TranslationEngine
class ProtectedTranslationEngine(TranslationEngine):
    """TranslationEngine with terminology protection."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.protector = TerminologyProtector(
            self.site_profile.terminology or {}
        )

    def _translate_segment(self, segment: str, source_lang: str, target_lang: str) -> str:
        """Translate with term protection."""
        # Protect terms
        protected_segment = self.protector.protect(segment)

        # Translate
        translated = super()._translate_segment(protected_segment, source_lang, target_lang)

        # Restore terms
        restored = self.protector.restore(translated)

        return restored
```

**Configuration:** Update `config/terminology/global.yaml`

```yaml
protected_terms:
  brands:
    - Aspose.Slides
    - Azure Blob Storage
    - PowerPoint

  technical:
    - namespace
    - deployment
    - boilerplate
    - callback

  frameworks:
    - .NET Framework
    - .NET Core
    - NuGet

  programming:
    - async
    - await
    - Task
```

**Expected Impact:** Fixes 40% of terminology issues
**Effort:** 4-6 hours implementation + 2 hours testing

---

### 1.2 Add Post-Processing Language Filter

**Problem:** Spanish contaminated with Portuguese ("Exemplo" instead of "Ejemplo")

**Solution:** Language-specific correction filters

#### Implementation:

**File:** `src/translation_engine/post_processing/filters.py`

```python
"""Post-processing filters for translation corrections."""

from typing import Dict, List
import re

class LanguageFilter:
    """Apply language-specific corrections."""

    # Language contamination patterns
    CONTAMINATION_PATTERNS = {
        "es": {  # Spanish filters
            # Portuguese contamination
            r'\bExemplo\b': 'Ejemplo',
            r'\bExemplos\b': 'Ejemplos',
            r'\bexemplo\b': 'ejemplo',
            r'\bexemplos\b': 'ejemplos',

            # Common errors
            r'\bCompleto\s+(\w+a)\b': r'Completa \1',  # Gender agreement
            r'Menos Código': 'Menos código',  # Capitalization
        },

        "de": {  # German filters
            # Common mistranslations
            r'\bEntführern\b': 'Einsätzen',  # kidnappers → deployments
            r'\bKomplizieren Sie\b': 'Bewältigen Sie',  # complicate → accomplish
            r'\bPressenverarbeitung\b': 'Präsentationsverarbeitung',
            r'\.Net Frames': '.NET Framework',
            r'\bPickfälle\b': 'Fallstricke',  # pitfalls
        },

        "fr": {  # French filters
            # Common typos
            r'\bmémerie\b': 'mémoire',
            r'\bnomespace\b': 'espace de noms',
            r'\.Net Frames': '.NET Framework',
        }
    }

    # Missing accents (Spanish)
    ACCENT_CORRECTIONS = {
        "es": {
            r'\bMetrica\b': 'Métrica',
            r'\bCodigo\b': 'Código',
            r'\boptimizacion\b': 'optimización',
        }
    }

    @classmethod
    def apply_filters(cls, text: str, target_lang: str) -> str:
        """Apply all filters for target language."""
        filtered_text = text

        # Apply contamination filters
        if target_lang in cls.CONTAMINATION_PATTERNS:
            for pattern, replacement in cls.CONTAMINATION_PATTERNS[target_lang].items():
                filtered_text = re.sub(pattern, replacement, filtered_text)

        # Apply accent corrections
        if target_lang in cls.ACCENT_CORRECTIONS:
            for pattern, replacement in cls.ACCENT_CORRECTIONS[target_lang].items():
                filtered_text = re.sub(pattern, replacement, filtered_text)

        return filtered_text


# Integration
def post_process_translation(translated_text: str, target_lang: str) -> str:
    """Apply post-processing filters."""
    # Apply language filters
    filtered = LanguageFilter.apply_filters(translated_text, target_lang)

    # Additional processing
    # - Spell checking (optional)
    # - Grammar checking (optional)

    return filtered
```

**Expected Impact:** Fixes 80% of language contamination issues
**Effort:** 3-4 hours implementation + 1 hour testing

---

### 1.3 Implement Quality Scoring Gate

**Problem:** No automatic detection of low-quality translations

**Solution:** Quality scoring with automatic flagging

#### Implementation:

**File:** `src/translation_engine/quality/scoring.py`

```python
"""Translation quality scoring."""

from typing import Dict, List, Tuple
import re
from langdetect import detect, DetectorFactory

# Make langdetect deterministic
DetectorFactory.seed = 0

class QualityScorer:
    """Score translation quality and flag issues."""

    @staticmethod
    def score_translation(
        source_text: str,
        translated_text: str,
        target_lang: str
    ) -> Dict[str, any]:
        """
        Score translation quality.

        Returns:
            {
                'score': float (0-1),
                'issues': List[str],
                'passed': bool,
                'details': Dict
            }
        """
        issues = []
        details = {}

        # 1. Language detection
        try:
            detected_lang = detect(translated_text)
            lang_match = (detected_lang == target_lang)
            details['detected_language'] = detected_lang
            details['language_match'] = lang_match

            if not lang_match:
                issues.append(f"Language mismatch: expected {target_lang}, detected {detected_lang}")
        except:
            issues.append("Language detection failed")
            lang_match = False

        # 2. Length ratio check (translated should be 0.8-1.5x source)
        length_ratio = len(translated_text) / len(source_text) if source_text else 0
        details['length_ratio'] = length_ratio

        if length_ratio < 0.5 or length_ratio > 2.0:
            issues.append(f"Unusual length ratio: {length_ratio:.2f}")

        # 3. Untranslated placeholders check
        placeholder_count = translated_text.count('__PROTECTED_')
        if placeholder_count > 0:
            issues.append(f"Untranslated placeholders found: {placeholder_count}")
            details['untranslated_placeholders'] = placeholder_count

        # 4. Code block preservation
        source_code_blocks = source_text.count('```')
        translated_code_blocks = translated_text.count('```')
        details['code_blocks_preserved'] = (source_code_blocks == translated_code_blocks)

        if source_code_blocks != translated_code_blocks:
            issues.append(f"Code block count mismatch: {source_code_blocks} → {translated_code_blocks}")

        # 5. Markdown structure check
        for marker in ['##', '###', '####', '-', '*', '|']:
            source_count = source_text.count(marker)
            translated_count = translated_text.count(marker)
            if abs(source_count - translated_count) > source_count * 0.1:  # 10% tolerance
                issues.append(f"Markdown structure '{marker}' count differs significantly")

        # 6. Language contamination check (Spanish/Portuguese)
        if target_lang == 'es':
            if re.search(r'\bExemplo[s]?\b', translated_text):
                issues.append("Portuguese contamination detected: 'Exemplo' found in Spanish")

        # Calculate score
        base_score = 1.0
        base_score -= 0.3 if not lang_match else 0
        base_score -= 0.1 * len(issues)
        base_score = max(0.0, min(1.0, base_score))

        return {
            'score': base_score,
            'issues': issues,
            'passed': base_score >= 0.7,  # 70% threshold
            'details': details
        }

    @staticmethod
    def flag_for_review(score_result: Dict) -> bool:
        """Determine if translation should be flagged for human review."""
        return (
            score_result['score'] < 0.7 or
            len(score_result['issues']) >= 3
        )


# Integration
def translate_with_quality_gate(
    segment: str,
    source_lang: str,
    target_lang: str,
    model
) -> Tuple[str, Dict]:
    """Translate with quality scoring."""
    # Translate
    translated = model.translate(segment, source_lang, target_lang)

    # Score
    quality = QualityScorer.score_translation(segment, translated, target_lang)

    # Flag if needed
    if QualityScorer.flag_for_review(quality):
        logger.warning(f"Translation flagged for review: score={quality['score']:.2f}, issues={quality['issues']}")

    return translated, quality
```

**Expected Impact:** Catches 70% of quality issues automatically
**Effort:** 4-5 hours implementation + 2 hours testing

---

### 1.4 Summary: Phase 1 Deliverables

**Implementation Order:**
1. Post-processing filters (highest ROI, lowest effort)
2. Quality scoring gate (high visibility, moderate effort)
3. Terminology protection (high impact, moderate effort)

**Total Effort:** 11-15 hours (2 days)
**Expected Quality Improvement:** 6.5/10 → 7.5/10

**Acceptance Criteria:**
- ✅ No Portuguese contamination in Spanish translations
- ✅ Technical terms preserved (namespace, deployment, etc.)
- ✅ Quality scores logged for all translations
- ✅ Translations flagged when score < 0.7

---

## Phase 2: Medium-Term Improvements (1-2 Weeks)

### 2.1 Upgrade Translation Model

**Current:** facebook/m2m100_418M (418M parameters)
**Problem:** Smaller model, lower quality, language confusion

**Options:**

#### Option A: M2M100-1.2B (Recommended)
**Pros:**
- Same architecture, better quality
- Direct upgrade path
- Supports same 100 languages
- Better at technical content

**Cons:**
- 3x larger (1.2B vs 418M parameters)
- Slower inference (2-3x)
- Higher memory usage (6GB vs 2GB)

**Implementation:**
```python
# src/model_runtime/registry.py
MODELS = {
    "facebook/m2m100_1.2B": {
        "type": "huggingface",
        "repo_id": "facebook/m2m100_1.2B",
        "min_gpu_memory": "6GB",
        "quality_tier": "high"
    }
}
```

**Expected Quality:** 7.5/10 → 8.5/10
**Effort:** 2-3 hours (download, test, validate)

---

#### Option B: NLLB-200-3.3B (Best Quality)
**Pros:**
- State-of-the-art multilingual model
- Supports 200 languages
- Specialized for low-resource languages
- Better technical content handling

**Cons:**
- 8x larger than current model
- Requires 16GB+ GPU memory
- Different tokenization (integration effort)

**Implementation:**
```python
MODELS = {
    "facebook/nllb-200-3.3B": {
        "type": "huggingface",
        "repo_id": "facebook/nllb-200-3.3B",
        "min_gpu_memory": "16GB",
        "quality_tier": "premium"
    }
}
```

**Expected Quality:** 7.5/10 → 9.0/10
**Effort:** 1 week (integration, testing, validation)

---

#### Option C: Hybrid - M2M100-1.2B + Commercial API Fallback

**Strategy:** Use M2M100-1.2B for bulk, DeepL/Google for flagged segments

```python
class HybridTranslationEngine:
    """Hybrid engine using local model + commercial API."""

    def translate_segment(self, segment, source_lang, target_lang):
        # Try local model first
        local_translation, quality = self.local_model.translate(segment)

        # If quality low, use commercial API
        if quality['score'] < 0.8:
            logger.info(f"Using commercial API for low-quality segment")
            return self.commercial_api.translate(segment)

        return local_translation
```

**Expected Quality:** 7.5/10 → 8.8/10
**Effort:** 3-4 days (API integration, fallback logic, testing)

---

**Recommendation:** Start with **Option A (M2M100-1.2B)** for immediate improvement, then evaluate **Option C (Hybrid)** for cost-effective premium quality.

---

### 2.2 Implement Context-Aware Translation

**Problem:** Model translates sentence-by-sentence without document context

**Solution:** Provide context to model

#### Implementation:

```python
class ContextAwareTranslator:
    """Translator with document-level context."""

    def __init__(self, model, max_context_length=512):
        self.model = model
        self.max_context_length = max_context_length

    def translate_with_context(
        self,
        segments: List[str],
        source_lang: str,
        target_lang: str
    ) -> List[str]:
        """Translate with preceding context."""
        translations = []
        context_window = []

        for segment in segments:
            # Build context (previous 2-3 sentences)
            context = " ".join(context_window[-3:])

            # Combine context + segment
            if context:
                input_text = f"{context} {segment}"
            else:
                input_text = segment

            # Translate
            translation = self.model.translate(input_text, source_lang, target_lang)

            # Extract only the new segment's translation
            # (last sentence of output)
            if context:
                translation = self._extract_last_sentence(translation)

            translations.append(translation)
            context_window.append(segment)

        return translations
```

**Expected Impact:** Improves coherence, better pronoun resolution, consistent terminology
**Effort:** 2-3 days

---

### 2.3 Add Human-in-the-Loop Review Workflow

**Solution:** Flag low-quality translations for human review

#### Implementation:

```python
class ReviewWorkflow:
    """Manage human review workflow."""

    def __init__(self, output_dir="review_queue"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

    def queue_for_review(
        self,
        source_text: str,
        translated_text: str,
        quality_score: Dict,
        metadata: Dict
    ):
        """Queue translation for human review."""
        review_item = {
            "source": source_text,
            "translation": translated_text,
            "quality_score": quality_score,
            "issues": quality_score['issues'],
            "metadata": metadata,
            "status": "pending_review"
        }

        # Write to review queue
        review_file = self.output_dir / f"review_{metadata['file_id']}_{metadata['lang']}.json"
        with open(review_file, 'w', encoding='utf-8') as f:
            json.dump(review_item, f, indent=2, ensure_ascii=False)

        logger.info(f"Queued for review: {review_file}")

    def apply_corrections(self, review_file: Path):
        """Apply human corrections and learn from them."""
        with open(review_file) as f:
            review = json.load(f)

        if review['status'] == 'approved':
            # Log correction for future learning
            self._log_correction(
                review['source'],
                review['translation'],
                review.get('corrected_translation')
            )
```

**Integration with CI/CD:**
```yaml
# .github/workflows/translation-review.yml
name: Translation Review
on:
  push:
    paths:
      - 'translations/**'

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - name: Check Quality Scores
        run: |
          python scripts/check_translation_quality.py

      - name: Create Review Issues
        if: quality_issues_found
        uses: actions/create-issue@v2
        with:
          title: "Translation Review Required: ${{ matrix.language }}"
          body: "Low-quality translations detected. Review required."
```

**Expected Impact:** Ensures quality gate, builds correction database
**Effort:** 3-4 days

---

### 2.4 Summary: Phase 2 Deliverables

**Implementation Order:**
1. Model upgrade (M2M100-1.2B) - immediate quality boost
2. Human-in-the-loop workflow - quality assurance
3. Context-aware translation - coherence improvement

**Total Effort:** 1-2 weeks
**Expected Quality Improvement:** 7.5/10 → 8.5/10

---

## Phase 3: Long-Term Strategies (1+ Months)

### 3.1 Fine-Tune Model on Technical Documentation

**Approach:** Adapt M2M100 to technical domain

#### Dataset Collection:
```python
# Collect parallel corpus
corpus = {
    "sources": [
        "Microsoft .NET documentation (EN→ES,DE,FR)",
        "Azure documentation (EN→ES,DE,FR)",
        "Technical blog posts",
        "API documentation",
        "Software tutorials"
    ],
    "size_target": "50K-100K sentence pairs per language"
}
```

#### Fine-Tuning:
```python
# Use HuggingFace Trainer
from transformers import M2M100ForConditionalGeneration, Trainer, TrainingArguments

model = M2M100ForConditionalGeneration.from_pretrained("facebook/m2m100_1.2B")

training_args = TrainingArguments(
    output_dir="./m2m100-technical-finetuned",
    num_train_epochs=3,
    per_device_train_batch_size=4,
    learning_rate=5e-5,
    warmup_steps=500,
    logging_steps=100,
)

trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=technical_dataset,
    eval_dataset=eval_dataset,
)

trainer.train()
```

**Expected Impact:** +10-15% quality on technical content
**Effort:** 4-6 weeks (data collection, training, validation)
**Resources:** GPU cluster (A100 or V100)

---

### 3.2 Implement Active Learning Loop

**Approach:** Learn from corrections

```python
class ActiveLearner:
    """Learn from human corrections."""

    def __init__(self, correction_db_path):
        self.corrections = self._load_corrections(correction_db_path)
        self.terminology_updates = []

    def analyze_corrections(self):
        """Analyze correction patterns."""
        # Find common errors
        error_patterns = self._extract_patterns(self.corrections)

        # Update terminology rules
        for pattern in error_patterns:
            if pattern['frequency'] > 10:
                self.terminology_updates.append({
                    'incorrect': pattern['before'],
                    'correct': pattern['after'],
                    'language': pattern['lang']
                })

        # Update post-processing filters
        self._update_filters(self.terminology_updates)

    def retrain_model(self, min_corrections=1000):
        """Retrain model when enough corrections accumulated."""
        if len(self.corrections) >= min_corrections:
            logger.info(f"Retraining with {len(self.corrections)} corrections")
            # Fine-tune on correction corpus
            self._fine_tune_on_corrections()
```

**Expected Impact:** Continuous quality improvement
**Effort:** 2-3 weeks initial setup, ongoing maintenance

---

### 3.3 Build Translation Memory System

**Approach:** Reuse high-quality translations

```python
class TranslationMemory:
    """Store and retrieve high-quality translations."""

    def __init__(self, tm_db_path):
        self.db = self._init_database(tm_db_path)
        self.embedder = SentenceTransformer('all-MiniLM-L6-v2')

    def store_translation(
        self,
        source: str,
        translation: str,
        lang: str,
        quality_score: float
    ):
        """Store high-quality translation."""
        if quality_score >= 0.9:  # Only store excellent translations
            embedding = self.embedder.encode(source)
            self.db.insert({
                'source': source,
                'translation': translation,
                'lang': lang,
                'embedding': embedding,
                'quality': quality_score
            })

    def retrieve_match(self, source: str, lang: str, threshold=0.85):
        """Retrieve similar translation from memory."""
        query_embedding = self.embedder.encode(source)
        matches = self.db.search_similar(query_embedding, lang, threshold)

        if matches:
            best_match = matches[0]
            logger.info(f"TM hit: similarity={best_match['similarity']:.2f}")
            return best_match['translation']

        return None
```

**Expected Impact:** Instant reuse of proven translations, consistency
**Effort:** 2-3 weeks

---

### 3.4 Summary: Phase 3 Deliverables

**Long-term investments:**
1. Fine-tuned model on technical corpus
2. Active learning from corrections
3. Translation memory system

**Total Effort:** 2-3 months
**Expected Quality Improvement:** 8.5/10 → 9.0-9.5/10

---

## Implementation Roadmap

### Week 1: Quick Wins
- Day 1-2: Post-processing filters + terminology protection
- Day 3: Quality scoring gate
- Day 4-5: Testing and validation

### Week 2-3: Model Upgrade
- Day 1-3: Download and test M2M100-1.2B
- Day 4-5: Benchmark and validate
- Day 6-7: Deploy to production

### Week 4-5: Human-in-Loop
- Week 4: Build review workflow
- Week 5: Integrate with CI/CD, test

### Month 2-3: Advanced Features
- Context-aware translation
- Active learning setup
- Translation memory

### Month 3+: Fine-Tuning
- Corpus collection
- Model fine-tuning
- Validation and deployment

---

## Success Metrics

### Quality Metrics:
- **Overall Quality Score:** 6.5/10 → 9.0/10
- **Terminology Accuracy:** 60% → 95%
- **Grammar Correctness:** 70% → 90%
- **Language Contamination:** 10% → 0%

### Operational Metrics:
- **Human Review Rate:** 100% → 20%
- **Translation Speed:** Baseline → 1.5x slower (larger model)
- **Cost per Translation:** Baseline → 1.2x (hybrid approach)

### Process Metrics:
- **Time to Production:** 2 weeks → 3 days (with TM hits)
- **Rework Rate:** 40% → 10%

---

## Cost-Benefit Analysis

### Phase 1 (Quick Wins):
- **Cost:** 2 days engineering time
- **Benefit:** +15% quality, immediate
- **ROI:** Very High

### Phase 2 (Model Upgrade):
- **Cost:** 2 weeks engineering + infrastructure ($500/month GPU)
- **Benefit:** +13% quality, reduced review burden
- **ROI:** High

### Phase 3 (Fine-Tuning):
- **Cost:** 3 months engineering + training compute ($5K)
- **Benefit:** +6% quality, long-term advantage
- **ROI:** Medium (strategic investment)

---

## Recommended Action Plan

**For Immediate Improvement (This Week):**
1. ✅ Implement post-processing language filters
2. ✅ Add terminology protection
3. ✅ Deploy quality scoring gate
**Target:** 7.5/10 quality

**For Production-Ready (Next Month):**
1. ✅ Upgrade to M2M100-1.2B
2. ✅ Add human review workflow
3. ✅ Implement context-aware translation
**Target:** 8.5/10 quality

**For Excellence (3+ Months):**
1. ✅ Fine-tune model on technical corpus
2. ✅ Build translation memory system
3. ✅ Implement active learning
**Target:** 9.0+/10 quality

---

## Conclusion

Moving from draft-level (6.5/10) to production-ready (8.5+/10) translation quality is achievable through a **phased approach**:

- **Phase 1** provides immediate wins with minimal effort
- **Phase 2** delivers production-quality through better models and workflows
- **Phase 3** achieves excellence through specialization and learning

**Start with Phase 1 this week** to see immediate improvement, then plan Phase 2 for next month.
