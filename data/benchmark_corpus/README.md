# Benchmark Corpus

**Purpose:** Synthetic corpus files for benchmarking translation models and testing pipeline performance.

---

## Files

| File | Segments | Tokens | Purpose |
|------|----------|--------|---------|
| [tiny.json](tiny.json) | 10 | ~25 | Smoke tests, quick validation |
| [small.json](small.json) | 50 | ~287 | Unit tests, model validation |
| [medium.json](medium.json) | 200 | ~1068 | Integration tests, benchmarking |

---

## File Format

Each corpus file is a JSON array of translation segments:

```json
[
  {
    "id": "segment_001",
    "text_en": "English source text here",
    "domain": "general"
  },
  {
    "id": "segment_002",
    "text_en": "Another segment with **markdown** formatting",
    "domain": "technical"
  }
]
```

### Fields

- **id** (string, required): Unique identifier for the segment
- **text_en** (string, required): English source text
- **domain** (string, required): Content category (`general`, `technical`, `documentation`)

---

## Usage

### Loading Corpus in Tests

```python
import json
from pathlib import Path

# Load tiny corpus
with open('data/benchmark_corpus/tiny.json') as f:
    corpus = json.load(f)

# Access segments
for segment in corpus:
    print(f"{segment['id']}: {segment['text_en']}")
```

### Benchmarking

```bash
# Run benchmark with tiny corpus
python -m src.benchmarking.runner \
  --model m2m100_418m \
  --device cpu \
  --batch-sizes 4 \
  --iterations 1 \
  --corpus tiny

# Run benchmark with small corpus
python -m src.benchmarking.runner \
  --model m2m100_418m \
  --device cpu \
  --batch-sizes 4,8 \
  --iterations 3 \
  --corpus small
```

---

## Data Governance

### Sanitization Status
✅ **All corpus files verified sanitized** (no proprietary content, no PII)

See [CORPUS_DISCOVERY.md](../../reports/benchmarking/CORPUS_DISCOVERY.md) for full verification report.

### Content Safety
- All samples use **synthetic/generated content**
- URLs use placeholder domains (example.com) per RFC 2606
- No real customer data or proprietary information
- Safe to commit to repositories

---

## Adding New Samples

### Procedure

1. **Create JSON file** following the format above
2. **Use synthetic content** or thoroughly sanitize real content
3. **Replace all URLs** with example.com placeholders
4. **Verify sanitization:**
   ```bash
   grep -r "aspose\.\(com\|net\)" data/benchmark_corpus/
   # Must return no matches
   ```
5. **Test loading:**
   ```bash
   python -c "import json; json.load(open('data/benchmark_corpus/your_file.json'))"
   ```
6. **Update README and discovery report**

### Sanitization Requirements

**Allowed:**
- ✅ example.com, example.org, example.net domains
- ✅ Generic names, placeholder data
- ✅ Synthetic/generated content
- ✅ Markdown formatting, code samples

**Forbidden:**
- ❌ Real URLs (aspose.com, customer sites, etc.)
- ❌ Customer data or proprietary content
- ❌ PII (names, emails, phone numbers, etc.)
- ❌ Sensitive business information

---

## Token Distribution

Current corpus files contain **short to medium segments** (1-20 tokens) which is appropriate for:
- Quick benchmarking iterations
- Model validation
- Performance testing
- Regression testing

For production benchmarking with real-world content, see BM-06 taskcard for .md corpus support.

---

## Maintenance

### Review Schedule
- **Next review:** 2025-06-20
- **Review triggers:** New files added, content modified, policy changes

### Corpus Updates
When adding or modifying corpus files:
1. Update segment counts in this README
2. Update token counts (run verification script)
3. Re-verify sanitization (grep checks)
4. Update discovery report timestamps

---

## Related Documentation

- [CORPUS_DISCOVERY.md](../../reports/benchmarking/CORPUS_DISCOVERY.md) - Full sanitization verification
- [Benchmarking Runner](../../src/benchmarking/runner.py) - Corpus loading implementation
- [Test Corpus Validation](../../tests/unit/benchmarking/test_corpus.py) - Corpus format tests

---

**Last Updated:** 2025-12-20
