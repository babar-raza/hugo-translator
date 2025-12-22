# TM Override Modes Guide

## Overview

Translation Memory (TM) Override Modes provide fine-grained control over how the Hugo Translation System interacts with its multi-layer translation cache. These modes allow operators to selectively bypass, refresh, or validate cached translations based on specific requirements.

## TM Architecture

The system uses a 3-layer TM architecture:

- **L1 Cache**: In-memory cache for frequently accessed translations
- **L2 Persistent**: LMDB-based persistent storage for all translations
- **L3 Semantic**: FAISS-based semantic similarity search for fuzzy matches

## Override Modes

### Normal Mode (Default)

**Behavior**: Standard TM operation with full cache utilization.

- **Lookup**: Searches all TM layers (L1 → L2 → L3)
- **Update**: Stores new translations in all layers
- **Use Case**: Standard production translation

**CLI Usage**:
```bash
# Explicit normal mode (default behavior)
python scripts/batch_translate.py --input ./content --output ./output --site products.aspose.net --override-mode normal
```

### Bypass Mode

**Behavior**: Completely skips TM lookup and storage.

- **Lookup**: No TM queries performed
- **Update**: No translations stored in TM
- **Use Case**: Fresh translation testing, content validation, or when cache is suspected to be corrupted

**CLI Usage**:
```bash
# Bypass TM entirely - always translate fresh
python scripts/batch_translate.py --input ./content --output ./output --site products.aspose.net --override-mode bypass
```

### Refresh Mode

**Behavior**: Bypasses TM lookup but forces cache updates with new translations.

- **Lookup**: Skips TM search, always translates
- **Update**: Overwrites existing TM entries with new translations
- **Use Case**: Content updates, terminology changes, or cache refresh operations

**CLI Usage**:
```bash
# Force fresh translation and update TM
python scripts/batch_translate.py --input ./content --output ./output --site products.aspose.net --override-mode refresh
```

### Validate Mode

**Behavior**: Uses TM for lookup but also performs fresh translation for comparison.

- **Lookup**: Normal TM search and retrieval
- **Update**: No cache updates performed
- **Translation**: Always performs fresh translation regardless of cache hits
- **Use Case**: Cache validation, quality assurance, or comparing model performance

**CLI Usage**:
```bash
# Use cache but also translate for comparison
python scripts/batch_translate.py --input ./content --output ./output --site products.aspose.net --override-mode validate
```

## Override Filters

Filters allow selective application of override modes to specific content segments.

### Source Pattern Filters

Match segments based on text content using regex patterns.

```bash
# Apply refresh mode only to segments containing "Aspose"
python scripts/batch_translate.py --input ./content --output ./output --site products.aspose.net \
  --override-mode refresh \
  --override-filter-patterns "Aspose"
```

### Target Language Filters

Apply override only to specific target languages.

```bash
# Refresh TM only for German translations
python scripts/batch_translate.py --input ./content --output ./output --site products.aspose.net \
  --langs de fr es \
  --override-mode refresh \
  --override-filter-langs de
```

### Frontmatter Key Filters

Apply override based on frontmatter field names.

```bash
# Bypass cache for title fields only
python scripts/batch_translate.py --input ./content --output ./output --site products.aspose.net \
  --override-mode bypass \
  --override-filter-keys title
```

### Combined Filters

Multiple filter types can be combined for precise control.

```bash
# Refresh TM for German titles containing "Aspose"
python scripts/batch_translate.py --input ./content --output ./output --site products.aspose.net \
  --override-mode refresh \
  --override-filter-langs de \
  --override-filter-keys title \
  --override-filter-patterns "Aspose"
```

## Usage Examples

### Cache Validation Workflow

```bash
# 1. Validate cache quality by comparing cached vs fresh translations
python scripts/batch_translate.py --input ./content --output ./validation_output --site products.aspose.net \
  --override-mode validate --report validation_report.json

# 2. Review validation report for cache accuracy
cat validation_report.json

# 3. Refresh problematic segments if needed
python scripts/batch_translate.py --input ./content --output ./refreshed_output --site products.aspose.net \
  --override-mode refresh --override-filter-patterns "problematic_term"
```

### Content Update Scenario

```bash
# After updating product names or terminology
python scripts/batch_translate.py --input ./content --output ./updated_output --site products.aspose.net \
  --override-mode refresh --override-filter-patterns "old_product_name|new_product_name"
```

### Fresh Translation Testing

```bash
# Test translation quality without cache interference
python scripts/batch_translate.py --input ./samples --output ./test_output --site products.aspose.net \
  --override-mode bypass --langs de fr
```

### Selective Cache Bypass

```bash
# Bypass cache for dynamic content (dates, version numbers) but use cache for static content
python scripts/batch_translate.py --input ./content --output ./output --site products.aspose.net \
  --override-mode bypass --override-filter-keys date version
```

## Statistics and Monitoring

Override operations provide detailed statistics:

```bash
# Run with override mode and check stats
python scripts/batch_translate.py --input ./content --output ./output --site products.aspose.net \
  --override-mode refresh --report stats.json

# Stats include:
# - Mode used
# - Segments bypassed/refreshed
# - Filter matches
# - Performance impact
```

## API Integration

### Programmatic Usage

```python
from src.translation_engine import TranslationEngine
from src.tm.override_controller import OverrideMode

# Configure override mode
engine.set_override_mode(
    mode="refresh",
    filters={
        "source_patterns": ["Aspose\.Words"],
        "target_langs": ["de", "fr"]
    }
)

# Translate with override behavior
result = engine.translate_file("products.aspose.net", file_path, ["de", "fr"])
```

### Engine Initialization

```python
# Initialize engine with override mode
engine = TranslationEngine(
    config_service=config,
    tm=tm,
    model_loader=loader,
    override_mode="bypass",  # Set at initialization
    override_filters={"target_langs": ["de"]}
)
```

## Best Practices

### When to Use Each Mode

- **Normal**: Standard production use, maximum efficiency
- **Bypass**: Testing new models, validating content, debugging
- **Refresh**: Content updates, terminology changes, cache maintenance
- **Validate**: Quality assurance, cache validation, performance comparison

### Performance Considerations

- **Bypass/Refresh**: Significantly slower due to forced translation
- **Validate**: ~2x slower due to dual translation (cache + fresh)
- **Normal**: Optimal performance with full cache utilization

### Filter Usage Tips

- Use specific patterns to minimize performance impact
- Combine filters for surgical precision
- Test filters with `--dry-run` first
- Monitor statistics to verify filter effectiveness

### Cache Maintenance

- Regular validation runs help identify cache degradation
- Refresh mode useful for bulk terminology updates
- Bypass mode for complete cache rebuilds

## Troubleshooting

### Common Issues

**Override mode not taking effect**:
- Verify CLI arguments are correctly formatted
- Check that filters match expected content
- Use `--dry-run` to preview behavior

**Performance degradation**:
- Narrow filters to reduce override scope
- Consider parallel processing for large batches
- Monitor TM statistics for optimization opportunities

**Unexpected cache behavior**:
- Use validate mode to compare cache vs fresh translations
- Check TM statistics for hit/miss patterns
- Verify filter regex patterns are correct

## Related Documentation

- [Translation Memory Architecture](../architecture/translation-engine.md)
- [Batch Translation Script](../../scripts/batch_translate.py)
- [CLI Reference](../reference/cli.md)
- [Configuration Reference](../reference/config.md)
c
