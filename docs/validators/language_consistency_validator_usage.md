# LanguageConsistencyValidator Usage Guide

## Overview

The `LanguageConsistencyValidator` validates that translated content is in the correct target language using Google's langdetect library. It's production-ready, deterministic, and handles edge cases gracefully.

## Basic Usage

```python
from src.translation_engine.validation import LanguageConsistencyValidator

# Create validator with default confidence threshold (0.85)
validator = LanguageConsistencyValidator()

# Validate German translation
source_text = "This is the English source."
german_text = "Dies ist der deutsche Text über Technologie."
result = validator.validate(
    source=source_text,
    translation=german_text,
    context={'target_lang': 'de'}
)

if result.success:
    print(f"✓ Validation passed!")
    print(f"  Detected: {result.metadata['detected_language']}")
    print(f"  Confidence: {result.metadata['confidence']:.2%}")
else:
    print(f"✗ Validation failed with {result.error_count} error(s)")
    for issue in result.issues:
        print(f"  [{issue.severity.value.upper()}] {issue.message}")
```

## Custom Confidence Threshold

```python
# Use stricter threshold (95% confidence required)
strict_validator = LanguageConsistencyValidator(confidence_threshold=0.95)

# Use lenient threshold (70% confidence acceptable)
lenient_validator = LanguageConsistencyValidator(confidence_threshold=0.70)
```

## Supported Languages

The validator supports all languages that langdetect recognizes, including:
- `de` - German
- `fr` - French
- `es` - Spanish
- `it` - Italian
- `pt` - Portuguese
- `ru` - Russian
- `ar` - Arabic
- `zh-cn` - Simplified Chinese
- `zh-tw` - Traditional Chinese
- `ja` - Japanese
- `ko` - Korean
- And 40+ more languages

See [langdetect documentation](https://github.com/Mimino666/langdetect) for full list.

## Validation Results

### Success (Correct Language)
```python
result = validator.validate("", "Dies ist deutscher Text.", {'target_lang': 'de'})
# result.success = True
# result.metadata = {
#     'detected_language': 'de',
#     'confidence': 0.99,
#     'target_language': 'de'
# }
# result.issues = []
```

### Error (Wrong Language)
```python
result = validator.validate("", "This is English text.", {'target_lang': 'de'})
# result.success = False
# result.error_count = 1
# result.issues[0].severity = ValidationSeverity.ERROR
# result.issues[0].message = "Wrong language detected: en (expected de)"
```

### Warning (Low Confidence)
```python
validator = LanguageConsistencyValidator(confidence_threshold=0.95)
result = validator.validate("", "Text with mixed content.", {'target_lang': 'de'})
# If confidence < 0.95:
#   result.issues contains WARNING about low confidence
#   result.success may still be True (warnings don't fail validation)
```

### Info (Text Too Short)
```python
result = validator.validate("", "Short", {'target_lang': 'de'})
# result.success = True (too short to validate reliably)
# result.info_count = 1
# result.issues[0].message = "Text too short for reliable language detection"
```

## Text Cleaning

The validator automatically cleans text before detection to avoid false negatives:

```python
text = """
# German Article

Dies ist ein deutscher Artikel über Programmierung.

```python
def english_code():
    print("This code is ignored")
```

Der Artikel enthält `inline_code` und {{< shortcode param="value" >}}.
Siehe auch https://example.com/english-url für Details.
"""

# Validator cleans:
# - Code blocks (```)
# - Inline code (`)
# - URLs (https://)
# - Hugo shortcodes ({{< >}})
# - Placeholders ({PLACEHOLDER_N})
# - Markdown link URLs (keeps text)
# - Excessive whitespace

result = validator.validate("", text, {'target_lang': 'de'})
# Detects as German, ignoring English in code/URLs
```

## Integration with ValidationSuite

```python
from src.translation_engine.validation import ValidationSuite, LanguageConsistencyValidator

# Add to suite
suite = ValidationSuite()
suite.add_validator(LanguageConsistencyValidator(confidence_threshold=0.85))

# Validate with language check
result = suite.validate(
    source="English source",
    translation="Deutscher Text",
    context={'target_lang': 'de'}
)
```

## Error Handling

The validator handles all edge cases gracefully:

```python
# Missing target language - WARNING, validation passes
result = validator.validate("", "Text", {})
# result.success = True, WARNING issued

# Empty text - INFO, validation passes
result = validator.validate("", "", {'target_lang': 'de'})
# result.success = True, INFO issued

# Detection exception - WARNING, validation fails
result = validator.validate("", "!!!", {'target_lang': 'de'})
# result.success = False or True depending on case
```

## Performance

- **Speed**: ~10-50ms per validation (langdetect is fast)
- **Memory**: Minimal (library loads language profiles once)
- **Determinism**: Same input always produces same output (seed = 0)

## Best Practices

1. **Use default threshold (0.85)** for most cases
2. **Increase threshold (0.90-0.95)** for critical translations
3. **Decrease threshold (0.70-0.80)** for technical/mixed content
4. **Check metadata** for confidence even on success
5. **Handle INFO/WARNING** appropriately (don't fail on warnings)
6. **Provide target_lang** in context for accurate validation

## Troubleshooting

### False Negatives (Correct Language Marked Wrong)
- **Cause**: Text too technical, too short, or mixed language
- **Solution**: Lower confidence threshold or add more natural language content

### False Positives (Wrong Language Marked Correct)
- **Cause**: Languages too similar (e.g., Spanish vs. Portuguese)
- **Solution**: Increase confidence threshold, check confidence in metadata

### Low Confidence Warnings
- **Cause**: Mixed language, technical terms, short text
- **Solution**: Add more natural language text, or accept warning if expected

## Example: Batch Validation

```python
translations = [
    ("de", "Dies ist deutscher Text."),
    ("fr", "Ceci est un texte français."),
    ("es", "Este es un texto español."),
]

validator = LanguageConsistencyValidator()

for lang, text in translations:
    result = validator.validate("", text, {'target_lang': lang})
    status = "✓" if result.success else "✗"
    conf = result.metadata.get('confidence', 0)
    print(f"{status} {lang}: {conf:.0%} confidence")
```

## Reference

- **File**: `src/translation_engine/validation/language_consistency_validator.py`
- **Tests**: `tests/unit/validation/test_language_consistency_validator.py`
- **Base Class**: `PostTranslationValidator`
- **Library**: [langdetect](https://github.com/Mimino666/langdetect) (Google's language detection)
