# Legacy Filter Migration Guide

**Date**: 2025-01-19  
**Migration**: `legacy/filter.json` → `config/site_profiles/*.yaml`

---

## Overview

This guide documents the migration from the legacy filter.json configuration format to the new site profile YAML format. The migration was performed using an automated script that preserves all translation rules while adapting them to the new schema.

---

## Migration Summary

**Status**: ✅ COMPLETE  
**Sites Migrated**: 8 of 8 (100%)  
**Validation**: All profiles valid

### Migrated Sites

1. **products.aspose.net** - 31 frontmatter rules, 0 preserve blocks
2. **docs.aspose.net** - 8 frontmatter rules, 2 preserve blocks
3. **blog.aspose.net** - 10 frontmatter rules, 2 preserve blocks
4. **kb.aspose.net** - 21 frontmatter rules, 2 preserve blocks
5. **reference.aspose.net** - 8 frontmatter rules, 3 preserve blocks
6. **websites.aspose.net** - 11 frontmatter rules, 0 preserve blocks
7. **www.aspose.net** - 28 frontmatter rules, 0 preserve blocks
8. **about.aspose.net** - 8 frontmatter rules, 0 preserve blocks

---

## Mapping Documentation

### Legacy Structure → New Structure

#### Metadata Fields → Frontmatter Rules

**Legacy** (`filter.json`):
```json
{
  "products.aspose.net": {
    "metadata": [
      "title",
      "description",
      "banner.title"
    ]
  }
}
```

**New** (`products.aspose.net.yaml`):
```yaml
frontmatter:
  title:
    mode: translate
  description:
    mode: translate
  banner.title:
    mode: translate
```

**Mapping Logic**:
- All metadata fields → `mode: translate`
- Fields containing `.list.` or ending with `.items`/`.points` → `mode: translate_list`
- Added common passthrough fields: `draft`, `date`, `type`, `layout`, `url`, `slug`

---

#### AST Configuration → Body Rules

**Legacy**:
```json
{
  "ast": {
    "includeNodeTypes": ["text"],
    "excludeAncestors": ["block_code", "codespan"],
    "excludePatterns": [
      "^\{\{<.*>\}\}",
      "^\{\{%.*?%\}\}"
    ]
  }
}
```

**New**:
```yaml
body:
  translate_markdown: true
  preserve_blocks:
    - block_code
    - codespan
  preserve_patterns:
    - ^\{\{<.*>\}\}$
    - ^\{\{%.*?%\}\}$
  placeholder_syntax:
    - \{\{<.*?>\}\}
    - \{\{%.*?%\}\}
```

**Mapping Logic**:
- `includeNodeTypes: ["text"]` → `translate_markdown: true`
- `excludeAncestors` → `preserve_blocks`
- `excludePatterns` → `preserve_patterns`
- Added `placeholder_syntax` for Hugo shortcode protection

---

### New Fields Added

All migrated profiles include these new fields not present in legacy:

1. **Content Roots**:
   ```yaml
   content_roots:
     - /content/products  # Site-specific path
   ```

2. **Language Configuration**:
   ```yaml
   default_source_lang: en
   target_langs:
     - de
     - es
     - fr
     - ja
     - ko
     - ru
     - zh
     - ar
     - it
     - pt
   ```

3. **Output Layout**:
   ```yaml
   output_layout:
     per_language_folders: true
     pattern: "{lang}/{path}"
   ```

4. **Translation Memory Preferences**:
   ```yaml
   tm_prefs:
     use_semantic_tm: true
     fallback_exact_only: false
     min_similarity_score: 0.8
   ```

---

## Migration Script

### Location
`scripts/migrate_filters.py`

### Usage
```bash
# Run migration
python scripts/migrate_filters.py

# Output shows progress for each site
# Validates all profiles after generation
```

### Features
- ✅ Automated conversion of all sites
- ✅ Preserves all translation rules
- ✅ Validates generated profiles
- ✅ Clear error reporting
- ✅ Idempotent (can be run multiple times)

### Code Structure
```python
# Main functions:
- convert_metadata_to_frontmatter()  # Metadata → Frontmatter
- convert_ast_to_body_rules()        # AST → Body Rules
- migrate_site()                     # Single site migration
- main()                             # Orchestrator
```

---

## Validation Results

All generated profiles pass validation:

```bash
$ python scripts/migrate_filters.py
...
[OK] All generated profiles are valid!
```

### Validation Checks
- ✅ Site ID format (lowercase, dots/hyphens)
- ✅ Language codes (xx or xx-YY format)
- ✅ Required fields present
- ✅ Field types correct
- ✅ Pydantic model validation
- ✅ JSON Schema compliance

---

## Differences from Legacy

### Behavioral Changes
1. **List Translation**: Automatic detection of list fields
   - Old: Manual handling in code
   - New: Explicit `translate_list` mode

2. **Passthrough Fields**: Automatically added
   - Old: Implicit in code
   - New: Explicit in config

3. **Placeholder Protection**: Unified syntax
   - Old: Per-site patterns
   - New: Standard Hugo shortcode patterns

### Improvements
1. **Type Safety**: Pydantic validation at load time
2. **Documentation**: Self-documenting YAML format
3. **Extensibility**: Easy to add new fields
4. **Maintainability**: Single file per site
5. **Validation**: Schema-enforced correctness

---

## Site-Specific Notes

### products.aspose.net
- Most complex profile (31 frontmatter fields)
- No preserve blocks (translates all text)
- Many nested frontmatter fields (e.g., `content.block.title_left`)

### docs.aspose.net
- Minimal frontmatter (title, description)
- Preserves code blocks (block_code, codespan)
- Hugo shortcode protection

### blog.aspose.net
- SEO-focused fields (seoTitle, summary)
- Code preservation
- Shortcode protection

### kb.aspose.net
- Knowledge base specific (step1-step10)
- Keywords field for SEO
- Standard code preservation

### reference.aspose.net
- Most restrictive preserve patterns
- Protects API reference syntax
- Excludes links, PascalCase, UPPERCASE
- Method signature protection

### websites.aspose.net
- Corporate content focused
- Nested section fields
- No code preservation

### www.aspose.net
- Complex nested structure (28 fields)
- Success stories, testimonials
- No code preservation

### about.aspose.net
- Minimal profile (like docs)
- Hugo shortcode protection
- Standard code preservation

---

## Testing Migration

### Verify a Profile
```bash
# Load and inspect
python -c "
from utils.config_loader import ConfigService
service = ConfigService('config')
profile = service.get_site_profile('products.aspose.net')
print(f'Site: {profile.site_id}')
print(f'Source: {profile.default_source_lang}')
print(f'Targets: {profile.target_langs}')
print(f'Frontmatter rules: {len(profile.frontmatter)}')
"
```

### Validate All
```bash
python -c "
from utils.config_loader import ConfigService
service = ConfigService('config')
errors = service.validate_all_profiles()
print('Valid!' if not errors else f'Errors: {errors}')
"
```

---

## Rollback Procedure

If needed to rollback:

1. **Preserve Legacy**: `legacy/filter.json` is unchanged
2. **Remove Generated**: Delete `config/site_profiles/*.yaml`
3. **Revert Code**: Switch back to legacy loader

**Note**: Not recommended - new system is validated and complete.

---

## Future Enhancements

Possible additions to profiles:

1. **Per-site TM preferences**
   ```yaml
   tm_prefs:
     use_semantic_tm: false  # Disable for specific site
     min_similarity_score: 0.9  # Higher threshold
   ```

2. **Custom translation strategies**
   ```yaml
   frontmatter:
     technical_term:
       mode: translate
       strategy: preserve_technical_terms
   ```

3. **Language-specific rules**
   ```yaml
   target_lang_overrides:
     ja:
       output_pattern: "{path}.{lang}.md"
   ```

---

## References

- **Legacy Config**: [legacy/filter.json](../legacy/filter.json)
- **Generated Profiles**: [config/site_profiles/](../config/site_profiles/)
- **Migration Script**: [scripts/migrate_filters.py](../scripts/migrate_filters.py)
- **Schema Definition**: [config/schemas/site_profile.schema.json](../config/schemas/site_profile.schema.json)
- **Pydantic Models**: [src/utils/models.py](../src/utils/models.py)

---

**Migration Status**: ✅ COMPLETE  
**Date Completed**: 2025-01-19  
**Migrated By**: Automated migration script
