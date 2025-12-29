# Benchmarking Data Sources Specification

**Version:** 1.0
**Status:** Production-Ready
**Last Updated:** 2025-12-28
**Parent:** [REQUIREMENTS.md](../REQUIREMENTS.md)

## Executive Summary

This specification defines the data sources, corpus construction, and file operation boundaries for the benchmarking system. It ensures that only real Aspose.net content is used for benchmarks and that write operations are strictly controlled.

## Table of Contents

1. [Data Source Requirements](#data-source-requirements)
2. [Corpus Construction](#corpus-construction)
3. [File Operation Boundaries](#file-operation-boundaries)
4. [Cache Scenarios](#cache-scenarios)
5. [Quality Dimensions](#quality-dimensions)
6. [Acceptance Criteria](#acceptance-criteria)
7. [Implementation Guidance](#implementation-guidance)

---

## Data Source Requirements

### SRC-001: Real Aspose.net Content Only
**Priority:** P0 (Critical)

All benchmarks and translations MUST use actual content from the Aspose.net repository at:
```
D:\onedrive\Documents\GitHub\aspose.net\content
```

**Prohibited Data Sources:**
- ❌ Synthetic/generated test data
- ❌ Lorem ipsum placeholder text
- ❌ Public datasets (WMT, OPUS, etc.)
- ❌ Manually created test cases

**Allowed Data Sources:**
- ✅ Markdown files from `aspose.net/content/**/*.md`
- ✅ Hugo shortcode-containing content
- ✅ Technical documentation with code blocks
- ✅ Blog posts, product pages, API references

**Rationale:**
- Production workload characteristics (terminology, formatting, shortcodes) cannot be replicated with synthetic data
- Real content reveals edge cases (e.g., nested shortcodes, multi-line code blocks)
- Benchmark results must predict actual production performance

### SRC-002: Content Diversity

Benchmark corpus MUST represent all content types found in Aspose.net:

| Content Type | Example Path | Min Segments | Characteristics |
|--------------|--------------|--------------|-----------------|
| **Product Pages** | `products/*/features.md` | 50 | Marketing copy, feature lists |
| **Technical Docs** | `docs/*/*.md` | 200 | Code examples, API descriptions |
| **Blog Posts** | `blog/*/*.md` | 100 | Conversational tone, mixed formatting |
| **API Reference** | `reference/*/*.md` | 150 | Structured data, technical terminology |
| **Knowledge Base** | `kb/*/*.md` | 50 | FAQ-style, short segments |
| **Legal Pages** | `about/*/legal.md` | 25 | Formal language, precise terminology |

**Total Minimum Corpus Size:** 575 segments per language

**Validation:**
```python
def validate_corpus_diversity(corpus):
    content_types = set()
    for segment in corpus:
        content_type = detect_content_type(segment.source_path)
        content_types.add(content_type)

    assert len(content_types) >= 5, "Corpus must include at least 5 content types"
    assert corpus.total_segments >= 575, "Corpus too small"
```

### SRC-003: Segment Extraction Rules

Segments MUST be extracted using production-grade segment extraction logic:

```python
from src.translation_engine.extractor.text_unit_extractor import TextUnitExtractor

extractor = TextUnitExtractor(config)
segments = extractor.extract_segments(markdown_content)
```

**Extraction Requirements:**
- Preserve Hugo shortcodes as placeholders
- Respect paragraph boundaries
- Split multi-sentence paragraphs intelligently
- Exclude code blocks from translation
- Maintain frontmatter integrity

**Example Segment:**
```markdown
Source: "Use {{% product-name %}} to convert {{% file-format %}} files efficiently."
Extracted: "Use <PH1/> to convert <PH2/> files efficiently."
Placeholders: {"PH1": "{{% product-name %}}", "PH2": "{{% file-format %}}"}
```

---

## Corpus Construction

### CORP-001: Corpus Configuration File
**Priority:** P0 (Critical)

Benchmark corpus MUST be defined in `config/benchmark_corpus.yaml`:

```yaml
corpus:
  name: "Aspose.net Production Corpus v1.0"
  version: "1.0.0"
  source_root: "D:\\onedrive\\Documents\\GitHub\\aspose.net\\content"
  min_segments_per_language: 575
  max_segments_per_language: 1000

  # Sampling strategy
  sampling:
    strategy: "stratified"  # Ensure all content types represented
    random_seed: 42  # Reproducibility

  # Content type weights
  content_types:
    - type: "product"
      weight: 0.15
      path_pattern: "products/**/*.md"
      min_segments: 50

    - type: "docs"
      weight: 0.35
      path_pattern: "docs/**/*.md"
      min_segments: 200

    - type: "blog"
      weight: 0.20
      path_pattern: "blog/**/*.md"
      min_segments: 100

    - type: "reference"
      weight: 0.25
      path_pattern: "reference/**/*.md"
      min_segments: 150

    - type: "kb"
      weight: 0.05
      path_pattern: "kb/**/*.md"
      min_segments: 50

  # Exclusions
  exclude_patterns:
    - "**/draft/**"
    - "**/archive/**"
    - "**/_index.md"  # Directory indexes
    - "**/test-*.md"

  # Segment length constraints
  segment_constraints:
    min_length_chars: 10
    max_length_chars: 500
    min_words: 3
    max_words: 100
```

### CORP-002: Corpus Builder

Implementation in `src/benchmarking/adaptive_corpus.py`:

```python
class CorpusBuilder:
    def build_corpus(self, config_path: str) -> BenchmarkCorpus:
        """Build a benchmark corpus from configuration."""
        config = self.load_config(config_path)
        segments = []

        for content_type in config.content_types:
            # Find matching files
            files = self.find_files(
                root=config.source_root,
                pattern=content_type.path_pattern,
                exclude=config.exclude_patterns
            )

            # Extract segments
            type_segments = self.extract_segments_from_files(files)

            # Sample according to weight
            sampled = self.stratified_sample(
                segments=type_segments,
                target_count=content_type.min_segments,
                seed=config.sampling.random_seed
            )

            segments.extend(sampled)

        # Verify constraints
        self.validate_corpus(segments, config)

        return BenchmarkCorpus(
            segments=segments,
            version=config.version,
            metadata=self.build_metadata(config)
        )
```

### CORP-003: Corpus Versioning

Corpus MUST be versioned using content hash:

```python
import hashlib

def compute_corpus_version(segments: List[Segment]) -> str:
    """Compute deterministic version hash."""
    content = "\n".join(sorted(seg.source_text for seg in segments))
    return hashlib.sha256(content.encode()).hexdigest()[:16]
```

**Benefits:**
- Reproducibility: Same corpus version → Same benchmark results
- Change detection: Corpus modifications trigger re-benchmarking
- Traceability: Link benchmark results to exact corpus content

**Database Storage:**
```sql
CREATE TABLE corpus_versions (
    version_hash TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    total_segments INTEGER NOT NULL,
    config_yaml TEXT NOT NULL,
    segment_list_json TEXT NOT NULL
);
```

---

## File Operation Boundaries

### OPS-001: Read-Only Source Content
**Priority:** P0 (Critical)

The system MUST NEVER write to the Aspose.net source directory:

**Read-Only Paths:**
```
D:\onedrive\Documents\GitHub\aspose.net\content\**\*
```

**Enforcement Mechanism:**
```python
import os
from pathlib import Path

SOURCE_ROOT = Path(r"D:\onedrive\Documents\GitHub\aspose.net\content")

def validate_write_path(path: Path):
    """Ensure write operations don't modify source content."""
    if path.is_relative_to(SOURCE_ROOT):
        # Check if this is a translation output
        if path.parent.name not in VALID_LANGUAGE_CODES:
            raise PermissionError(
                f"Attempted write to source directory: {path}\n"
                f"Source content is read-only. Use translation output paths only."
            )
```

**Audit Logging:**
```python
import logging

audit_logger = logging.getLogger("file_operations")

def audit_file_write(path: Path, operation: str):
    """Log all file write operations for security review."""
    audit_logger.info(
        "File write operation",
        extra={
            "operation": operation,
            "path": str(path),
            "is_source_dir": path.is_relative_to(SOURCE_ROOT),
            "timestamp": datetime.now().isoformat()
        }
    )
```

### OPS-002: Allowed Write Locations

The system MAY write to the following directories:

**Translation Outputs:**
```
D:\onedrive\Documents\GitHub\aspose.net\content\{language}\**\*
```
Where `{language}` is one of the 36 target languages (ar, bg, ca, ..., zh).

**Internal System Data:**
```
hugo-translator/
├── data/
│   ├── benchmarks/
│   │   ├── benchmarks.db       ✅ Writable (benchmark results)
│   │   └── production.db       ✅ Writable (production metrics)
│   ├── tm/
│   │   ├── l2_exact.db         ✅ Writable (translation memory)
│   │   └── l3_faiss/           ✅ Writable (semantic index)
│   └── logs/
│       └── hugo-translator.ndjson  ✅ Writable (application logs)
├── models/                     ✅ Writable (downloaded models)
└── backups/                    ✅ Writable (TM backups)
```

**Validation Function:**
```python
ALLOWED_WRITE_ROOTS = [
    Path(r"D:\onedrive\Documents\GitHub\aspose.net\content"),  # Only lang subdirs
    Path(r"C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\data"),
    Path(r"C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\models"),
    Path(r"C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\backups"),
]

def is_write_allowed(path: Path) -> bool:
    """Check if file write is permitted."""
    for allowed_root in ALLOWED_WRITE_ROOTS:
        if path.is_relative_to(allowed_root):
            # Special check for Aspose.net content
            if path.is_relative_to(SOURCE_ROOT):
                return is_language_subdirectory(path)
            return True
    return False
```

### OPS-003: Read Operation Traceability

All corpus file reads MUST be logged for reproducibility:

```python
class CorpusReader:
    def __init__(self):
        self.accessed_files = []

    def read_file(self, path: Path) -> str:
        """Read file and log access."""
        content = path.read_text(encoding="utf-8")
        self.accessed_files.append({
            "path": str(path),
            "size_bytes": len(content),
            "mtime": path.stat().st_mtime,
            "timestamp": datetime.now().isoformat()
        })
        return content

    def get_manifest(self) -> dict:
        """Return manifest of all accessed files."""
        return {
            "total_files": len(self.accessed_files),
            "files": self.accessed_files
        }
```

**Manifest Storage:**
```sql
CREATE TABLE corpus_file_manifest (
    corpus_version TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_size_bytes INTEGER NOT NULL,
    file_mtime REAL NOT NULL,
    accessed_at TEXT NOT NULL,
    PRIMARY KEY (corpus_version, file_path)
);
```

---

## Cache Scenarios

### CACHE-001: Uncached Benchmark (Cold Start)
**Priority:** P0 (Critical)

Uncached benchmarks MUST measure performance with an empty translation memory.

**Setup:**
1. Clear L1, L2, L3 caches before benchmark
2. Ensure no TM entries exist for test language
3. All segments require model inference

**Implementation:**
```python
def run_uncached_benchmark(model, language, corpus):
    # Clear all cache layers
    tm.clear_l1_cache()
    tm.clear_l2_cache(language)
    tm.clear_l3_index(language)

    # Verify empty TM
    assert tm.get_entry_count(language) == 0

    # Run benchmark
    results = run_benchmark(
        model=model,
        language=language,
        corpus=corpus,
        cache_status="uncached"
    )

    return results
```

**Expected Behavior:**
- Cache hit rate: 0%
- All segments translated via model
- Throughput: ~10-50 segments/sec (model-dependent)

### CACHE-002: Cached Benchmark (Warm Start)
**Priority:** P0 (Critical)

Cached benchmarks MUST measure performance with a pre-populated translation memory.

**Setup:**
1. Translate corpus once to populate TM
2. Verify TM entries exist
3. Re-translate same corpus (should hit cache)

**Implementation:**
```python
def run_cached_benchmark(model, language, corpus):
    # First pass: Populate TM
    for segment in corpus.segments:
        translation = model.translate(segment.source_text, language)
        tm.store(segment.source_text, translation, language)

    # Verify TM populated
    assert tm.get_entry_count(language) >= len(corpus.segments)

    # Second pass: Benchmark with warm cache
    results = run_benchmark(
        model=model,
        language=language,
        corpus=corpus,
        cache_status="cached"
    )

    return results
```

**Expected Behavior:**
- Cache hit rate: ~100% (exact matches)
- Minimal model inference
- Throughput: ~500-2000 segments/sec (cache-dependent)

### CACHE-003: Mixed Cache Scenario
**Priority:** P1 (High)

Mixed benchmarks MUST measure realistic production workload (partial cache hits).

**Setup:**
1. Populate TM with 60% of corpus
2. Remaining 40% requires model translation
3. Simulate incremental content updates

**Implementation:**
```python
def run_mixed_benchmark(model, language, corpus, cache_ratio=0.6):
    # Populate TM with subset
    cached_count = int(len(corpus.segments) * cache_ratio)
    for segment in corpus.segments[:cached_count]:
        translation = model.translate(segment.source_text, language)
        tm.store(segment.source_text, translation, language)

    # Benchmark full corpus
    results = run_benchmark(
        model=model,
        language=language,
        corpus=corpus,
        cache_status="mixed",
        expected_hit_rate=cache_ratio
    )

    return results
```

**Expected Behavior:**
- Cache hit rate: ~60%
- 60% of segments from cache (fast)
- 40% of segments from model (slow)
- Throughput: Weighted average of cached/uncached

### CACHE-004: Cache Contamination Prevention

Benchmarks MUST NOT be affected by previous runs:

**Isolation Strategy:**
```python
class BenchmarkRunner:
    def run_benchmark(self, model, language, corpus, cache_status):
        # Create isolated TM instance
        with TemporaryTranslationMemory() as tm:
            if cache_status == "cached":
                self.populate_tm(tm, corpus, language)
            elif cache_status == "uncached":
                pass  # Empty TM
            elif cache_status == "mixed":
                self.populate_tm_partial(tm, corpus, language, ratio=0.6)

            # Run isolated benchmark
            results = self.execute_benchmark(tm, model, language, corpus)

        # TM automatically cleaned up
        return results
```

---

## Quality Dimensions

### 1. Authenticity (5/5)
**Measurement:**
- [ ] 100% of corpus from Aspose.net repository
- [ ] Zero synthetic or test data
- [ ] Content diversity validated (6 content types)

**Validation Query:**
```sql
SELECT COUNT(*) AS synthetic_segments
FROM corpus_segments
WHERE source_path NOT LIKE 'D:\onedrive\Documents\GitHub\aspose.net\content\%';
-- Expected: 0
```

### 2. Write Safety (5/5)
**Measurement:**
- [ ] Zero writes to source directory (except language subdirs)
- [ ] All writes logged in audit trail
- [ ] File operation permissions enforced

**Audit Query:**
```sql
SELECT * FROM file_operations_log
WHERE operation = 'write'
  AND path NOT LIKE '%\data\%'
  AND path NOT LIKE '%\models\%'
  AND path NOT LIKE '%\backups\%'
  AND path NOT LIKE '%\ar\%'  -- Language subdirectories
  AND path NOT LIKE '%\bg\%'
  ...
-- Expected: 0 rows
```

### 3. Cache Accuracy (5/5)
**Measurement:**
- [ ] Uncached benchmarks show 0% cache hit rate
- [ ] Cached benchmarks show >95% cache hit rate
- [ ] Mixed benchmarks show hit rate within ±5% of target

**Validation:**
```python
def validate_cache_benchmark(results):
    if results.cache_status == "uncached":
        assert results.cache_hit_rate < 0.05, "Uncached benchmark has cache hits"
    elif results.cache_status == "cached":
        assert results.cache_hit_rate > 0.95, "Cached benchmark has cache misses"
    elif results.cache_status == "mixed":
        expected = 0.6
        assert abs(results.cache_hit_rate - expected) < 0.05
```

### 4. Reproducibility (5/5)
**Measurement:**
- [ ] Same corpus version → Same segments
- [ ] Random seed fixed for sampling
- [ ] File access manifest recorded

**Test:**
```python
def test_reproducibility():
    corpus1 = builder.build_corpus("config/benchmark_corpus.yaml")
    corpus2 = builder.build_corpus("config/benchmark_corpus.yaml")

    assert corpus1.version == corpus2.version
    assert len(corpus1.segments) == len(corpus2.segments)
    for seg1, seg2 in zip(corpus1.segments, corpus2.segments):
        assert seg1.source_text == seg2.source_text
```

### 5. Traceability (5/5)
**Measurement:**
- [ ] Every benchmark links to corpus version
- [ ] Corpus version links to file manifest
- [ ] File manifest includes modification times

**Database Schema:**
```sql
SELECT b.id, b.model_id, b.language, c.version_hash, f.file_path
FROM benchmark_runs b
JOIN corpus_versions c ON b.corpus_version = c.version_hash
JOIN corpus_file_manifest f ON c.version_hash = f.corpus_version;
```

---

## Acceptance Criteria

### Functional Acceptance

1. **Data Source Authenticity**
   - [ ] All corpus segments traced to Aspose.net source files
   - [ ] File manifest contains 100% real paths
   - [ ] Zero synthetic data detected

2. **Write Safety**
   - [ ] Source directory write attempts blocked
   - [ ] Audit log contains all write operations
   - [ ] Translation outputs written to correct language subdirectories

3. **Cache Scenarios**
   - [ ] Uncached benchmarks: <5% cache hit rate
   - [ ] Cached benchmarks: >95% cache hit rate
   - [ ] Mixed benchmarks: Hit rate within target ±5%

### Non-Functional Acceptance

4. **Reproducibility**
   - [ ] Same corpus config → Same segments (100% match)
   - [ ] Corpus version hash stable across builds

5. **Traceability**
   - [ ] Every benchmark result links to corpus version
   - [ ] Corpus version links to file access manifest
   - [ ] Manifest traceable to source files

---

## Implementation Guidance

### File Operation Guard

```python
# src/utils/file_guard.py

from pathlib import Path
from typing import Union

class FileOperationGuard:
    """Enforce read-only source directory constraint."""

    SOURCE_ROOT = Path(r"D:\onedrive\Documents\GitHub\aspose.net\content")
    VALID_LANGS = {"ar", "bg", "ca", ..., "zh"}  # 36 languages

    @classmethod
    def validate_write(cls, path: Union[str, Path]):
        """Raise exception if write not allowed."""
        path = Path(path).resolve()

        # Check if in source directory
        if path.is_relative_to(cls.SOURCE_ROOT):
            # Allow writes to language subdirectories
            relative = path.relative_to(cls.SOURCE_ROOT)
            if relative.parts[0] not in cls.VALID_LANGS:
                raise PermissionError(
                    f"Write denied: {path}\n"
                    f"Source directory is read-only.\n"
                    f"Translation outputs must be in language subdirectories: {cls.VALID_LANGS}"
                )

        # Allow writes to internal directories
        allowed = [
            Path("data"),
            Path("models"),
            Path("backups"),
        ]

        for allowed_root in allowed:
            if path.is_relative_to(allowed_root.resolve()):
                return  # Allowed

        raise PermissionError(f"Write denied: {path}\nPath not in allowed write locations.")

# Integrate with file write operations
original_open = open

def guarded_open(path, mode="r", *args, **kwargs):
    if "w" in mode or "a" in mode:
        FileOperationGuard.validate_write(path)
    return original_open(path, mode, *args, **kwargs)

# Monkey-patch (or use context manager for benchmarks)
```

### Corpus Configuration Example

```yaml
# config/benchmark_corpus.yaml

corpus:
  name: "Aspose.net Production Benchmark Corpus"
  version: "1.0.0"
  source_root: "D:\\onedrive\\Documents\\GitHub\\aspose.net\\content"

  sampling:
    strategy: "stratified"
    random_seed: 42
    min_total_segments: 575
    max_total_segments: 1000

  content_types:
    - type: "technical_docs"
      weight: 0.35
      path_pattern: "docs/**/*.md"
      min_segments: 200
      characteristics:
        - code_blocks
        - api_terminology
        - structured_data

    - type: "blog_posts"
      weight: 0.20
      path_pattern: "blog/**/*.md"
      min_segments: 100
      characteristics:
        - conversational_tone
        - mixed_formatting
        - headings

    - type: "product_pages"
      weight: 0.15
      path_pattern: "products/**/*.md"
      min_segments: 50
      characteristics:
        - marketing_copy
        - feature_lists
        - shortcodes

    - type: "api_reference"
      weight: 0.25
      path_pattern: "reference/**/*.md"
      min_segments: 150
      characteristics:
        - technical_jargon
        - parameter_descriptions
        - return_values

    - type: "knowledge_base"
      weight: 0.05
      path_pattern: "kb/**/*.md"
      min_segments: 50
      characteristics:
        - faq_style
        - short_segments
        - question_answer

  exclude_patterns:
    - "**/draft/**"
    - "**/archive/**"
    - "**/_index.md"
    - "**/test-*.md"
    - "**/.git/**"

  segment_constraints:
    min_length_chars: 10
    max_length_chars: 500
    min_words: 3
    max_words: 100
```

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-12-28 | System | Initial specification |

---

## Related Specifications

- [REQUIREMENTS.md](../REQUIREMENTS.md) - Parent requirements
- [COVERAGE_REQUIREMENTS.md](COVERAGE_REQUIREMENTS.md) - Benchmark execution
- [UI_DASHBOARD.md](UI_DASHBOARD.md) - Results visualization
