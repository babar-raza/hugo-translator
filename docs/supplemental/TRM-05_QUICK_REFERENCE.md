# TRM-05 Quick Reference Guide

## What Changed

### Segment Dataclass (New Fields)
```python
@dataclass
class Segment:
    # ... existing fields ...
    protected_terms: List[Any] = field(default_factory=list)
    protection_metadata: Dict[str, Any] = field(default_factory=dict)
```

### SegmentExtractor (Updated)

**Constructor:**
```python
# Old way (still works)
extractor = SegmentExtractor(site_profile)

# New way (with terminology protection)
extractor = SegmentExtractor(site_profile, terminology_manager)
```

**New Methods:**
```python
# Internal - called automatically during extraction
extractor._protect_terminology(segment)

# Public - call on translated text before reconstruction
restored_text = extractor.restore_terminology(translated_text, segment)
```

## Usage Patterns

### Pattern 1: Extract with Protection
```python
from translation_engine.extractor import SegmentExtractor
from translation_engine.terminology import TerminologyManager

# Setup
manager = TerminologyManager("config/terminology.yaml")
extractor = SegmentExtractor(site_profile, manager)

# Extract (automatic protection)
segments = extractor.extract_all(doc)

# Check protection
for seg in segments:
    if seg.protected_terms:
        print(f"Protected: {seg.protection_metadata['terms_protected']} terms")
```

### Pattern 2: Restore After Translation
```python
# After translating segment
translated_text = translate_service.translate(segment.source_text)

# Restore terminology
final_text = extractor.restore_terminology(translated_text, segment)

# Use in reconstruction
doc.reconstruct(final_text)
```

### Pattern 3: Backward Compatible (No Manager)
```python
# Works exactly as before
extractor = SegmentExtractor(site_profile)
segments = extractor.extract_all(doc)
# No protection occurs, segments work normally
```

## Data Flow

### Extraction Flow
```
Original Text: "Aspose.Words for .NET"
     ↓
_protect_content() → Shortcode protection
     ↓
Protected: "Aspose.Words for .NET"
     ↓
_protect_terminology() → Term protection
     ↓
Final: "{TERM_0} for {TERM_1}"

Stored in segment:
  - source_text = "{TERM_0} for {TERM_1}"
  - protected_terms = [ProtectedSegment(...)]
  - protection_metadata = {terms_protected: 2, ...}
```

### Restoration Flow
```
Translated: "{TERM_0} pour {TERM_1}"
     ↓
restore_terminology()
     ↓
Restored: "Aspose.Words pour .NET"
```

## Testing

### Run TRM-05 Tests
```bash
pytest tests/unit/phase-2/test_segment_extractor_terminology.py -v
```

### Test Coverage
- Frontmatter segment protection
- Body segment protection
- Metadata preservation
- Restoration after translation
- Backward compatibility (no manager)
- Edge cases (empty text, special chars, overlaps)

### Quick Validation
```bash
python validate_trm05.py
```

## Debugging

### Check if Protection Occurred
```python
if segment.protected_terms:
    print(f"Protected {len(segment.protected_terms)} term sets")
    print(f"Metadata: {segment.protection_metadata}")
else:
    print("No terms protected")
```

### Inspect Protected Terms
```python
for protected_seg in segment.protected_terms:
    for term_id, detected_term in protected_seg.term_mapping.items():
        print(f"  {term_id}: {detected_term.term_text}")
        print(f"     Category: {detected_term.rule.category}")
        print(f"     Position: {detected_term.start_pos}-{detected_term.end_pos}")
```

### Check Restoration
```python
# Before
print(f"Before: {translated_text}")

# After
restored = extractor.restore_terminology(translated_text, segment)
print(f"After: {restored}")

# Verify placeholders removed
assert "{TERM_" not in restored
```

## Common Issues

### Issue: Terms not being protected
**Check:**
1. Is `terminology_manager` passed to SegmentExtractor?
2. Are terms defined in terminology.yaml?
3. Is site_id matching the config?

### Issue: Restoration not working
**Check:**
1. Are you calling `restore_terminology()` on the right segment?
2. Is the translated text preserving placeholders?
3. Are there protected_terms in the segment?

### Issue: Backward compatibility broken
**Check:**
1. Is `terminology_manager` optional (default=None)?
2. Are new fields defaulting to empty list/dict?
3. Are existing tests still passing?

## Integration Points

### With TerminologyManager (TRM-04)
```python
# TerminologyManager provides:
manager.protect(text, site) → ProtectedSegment
manager.restore(protected_segment) → str

# SegmentExtractor uses:
extractor._protect_terminology() → calls manager.protect()
extractor.restore_terminology() → calls manager.restore()
```

### With Translation Engine
```python
# 1. Extract with protection
segments = extractor.extract_all(doc)

# 2. Translate (placeholders preserved)
for seg in segments:
    translated = engine.translate(seg.source_text)

    # 3. Restore before reconstruction
    restored = extractor.restore_terminology(translated, seg)

    # 4. Use restored text
    reconstructed_doc.add_segment(restored)
```

## API Reference

### Segment Fields
- `protected_terms: List[ProtectedSegment]` - List of protected term sets
- `protection_metadata: Dict[str, Any]` - Debugging info
  - `original_text: str` - Text before protection
  - `terms_protected: int` - Number of terms protected
  - `term_categories: List[str]` - Categories of protected terms

### SegmentExtractor Methods
- `__init__(site_profile, terminology_manager=None)` - Constructor
- `_protect_terminology(segment)` - Internal protection (auto-called)
- `restore_terminology(translated_text, segment) -> str` - Public restoration

## Files Modified/Created

**Modified:**
- `src/translation_engine/extractor/segment_extractor.py`

**Created:**
- `tests/unit/phase-2/test_segment_extractor_terminology.py`
- `TRM-05_IMPLEMENTATION_SUMMARY.md`
- `TRM-05_QUICK_REFERENCE.md` (this file)
- `validate_trm05.py`

## Next Steps

1. **Verify with pytest**: Run full test suite
2. **Integration test**: Test with real TerminologyManager
3. **Backward compat**: Run existing segment_extractor tests
4. **Type check**: Run mypy on modified files

## Support

For issues or questions:
- See detailed implementation: `TRM-05_IMPLEMENTATION_SUMMARY.md`
- Run validation: `python validate_trm05.py`
- Check tests: `tests/unit/phase-2/test_segment_extractor_terminology.py`
