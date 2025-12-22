# File Contracts

Source of truth: `src/translation_engine/parser/hugo_parser.py`, `src/translation_engine/engine.py:_get_output_path()`

Input and output file formats, directory structures, and data contracts for the Hugo Translation System.

## Input Contracts

### Hugo Markdown Files

**File Extension**: `.md`, `.markdown`

**Encoding**: UTF-8

**Structure**:
```
---
frontmatter: yaml_block
---

# Body content (markdown)

Paragraphs, lists, code blocks, etc.
```

#### Frontmatter Format

- **Delimiter**: `---` (three dashes)
- **Format**: YAML 1.2 compliant
- **Fields**: Key-value pairs, nested objects supported
- **Validation**: Parsed and validated before translation

**Example**:
```yaml
---
title: "Getting Started with Aspose.Words"
description: "Learn how to use Aspose.Words for .NET"
date: 2024-01-15
draft: false
tags:
  - tutorial
  - .NET
categories:
  - documentation
---
```

#### Body Format

- **Format**: CommonMark markdown with Hugo extensions
- **Shortcodes**: `{{< shortcode >}}` and `{{% shortcode %}}`
- **Code blocks**: Fenced with backticks or indented
- **Links**: Relative and absolute URLs supported
- **Images**: Standard markdown image syntax

**Preserved Elements**:
- Hugo shortcodes (exactly as written)
- Code blocks and inline code
- Links and image references
- HTML tags (if present)
- Frontmatter structure

### Directory Structure (Input)

**Site Content Roots**:
- Defined in `site_profile.content_roots[]`
- Multiple roots supported
- Recursive scanning: `**/*.md`

**Example Structure**:
```
content/
├── _index.md
├── about/
│   ├── _index.md
│   └── team.md
├── products/
│   ├── words/
│   │   ├── _index.md
│   │   └── features.md
│   └── cells/
│       ├── _index.md
│       └── tutorial.md
```

## Output Contracts

### Translated Files

**Structure**: Identical to input
```
---
translated_frontmatter
---

Translated body content
```

**Preservation Guarantees**:
- Frontmatter YAML structure maintained
- Hugo shortcodes preserved exactly
- Code blocks and formatting intact
- Links and references preserved
- File encoding: UTF-8

### Directory Structure (Output)

**Per-Language Folders** (Hugo standard):
```
output/
├── en/           # Source language (if copied)
│   └── docs/
│       └── tutorial.md
├── de/           # German translations
│   └── docs/
│       └── tutorial.md
├── fr/           # French translations
│   └── docs/
│       └── tutorial.md
```

**Pattern-Based** (configurable):
```yaml
output_layout:
  per_language_folders: false
  pattern: "{path}.{lang}.md"
```

**Result**:
```
output/
├── docs/tutorial.en.md
├── docs/tutorial.de.md
├── docs/tutorial.fr.md
```

### File Naming

**Source Preservation**: Output files maintain source directory structure and filenames

**Language Integration**:
- Per-language folders: `/{lang}/{path}`
- File-based: `{path}.{lang}{ext}` or `{lang}/{path}`

**Examples**:
- Input: `content/docs/tutorial.md`
- Output (per-language): `output/de/docs/tutorial.md`
- Output (file-based): `output/docs/tutorial.de.md`

## Data Contracts

### Translation Units

**Segments**: Extracted translatable text units
- **Source**: Original text from markdown body
- **Context**: Node type, frontmatter keys, surrounding structure
- **Placeholders**: Protected content (shortcodes, code, links)

**Translation Map**:
```python
{
    "segment_id": "translated_text",
    # ...
}
```

### Validation Results

**Issue Format**:
```python
{
    "severity": "error|warning|info",
    "rule": "validator_name",
    "message": "human_readable_description",
    "location": "file_path or segment_id"
}
```

### Statistics Contract

**TranslationStats**:
```python
{
    "total_segments": int,
    "tm_hits": int,
    "translated_segments": int,
    "duration_seconds": float,
    "tokens_input": int,
    "tokens_output": int,
    "validation_errors": int,
    "validation_warnings": int
}
```

## Directory Contracts

### Configuration Directories

| Directory | Purpose | Required |
|-----------|---------|----------|
| `config/` | All configuration files | Yes |
| `config/site_profiles/` | Per-site profiles | Yes |
| `data/tm/` | Translation Memory data | No (created) |
| `data/models/` | Model cache | No (created) |
| `data/artifacts/` | Debug artifacts | No (created) |
| `data/logs/` | Application logs | No (created) |
| `backups/` | TM backups | No (created) |

### Runtime Directories

**Created Automatically**:
- `data/tm/l2_lmdb/` - LMDB database
- `data/tm/l3_faiss/` - FAISS index
- `output/{lang}/` - Per-language output

**Permissions**: Read/write access required

## Validation Contracts

### Input Validation

**File-Level Checks**:
- File exists and readable
- UTF-8 encoding
- Size < `max_file_size_mb`
- Extension in `allowed_extensions`

**Content Checks**:
- Valid YAML frontmatter
- Parseable markdown
- No corrupted Hugo syntax

### Output Validation

**Structure Preservation**:
- Frontmatter YAML validity
- Markdown structure integrity
- Hugo shortcode preservation
- Link/reference integrity

**Content Quality**:
- Language consistency
- Terminology preservation
- Completeness (100% coverage)

## Error Handling

### File Processing Errors

**Parse Failures**: Logged, file skipped
**Write Failures**: Logged, partial success possible
**Validation Failures**: Configurable (accept/retry/reject)

### Directory Errors

**Missing Roots**: Configuration error, system fails
**Permission Denied**: Runtime error, operation fails
**Disk Full**: Runtime error, graceful degradation

## Migration Contracts

### Version Compatibility

**Configuration**: Backward compatible within major versions
**File Formats**: Stable within major versions
**APIs**: Versioned, deprecated with warnings

### Breaking Changes

**Major Versions**: May change contracts
**Migration Path**: Provided via `guides/migration.md`
**Deprecation**: 2-version deprecation cycle
