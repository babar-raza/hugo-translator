# Blog Filtering Test Fixtures

This directory contains test fixtures for validating source file filtering in file-based localization scenarios (blog.aspose.net pattern).

## Test Pattern

File-based localization uses the pattern: `{filename}.{lang}{ext}`

- Source files: `index.md`, `tutorial.md`, `_index.md` (no language code)
- Translated files: `index.es.md`, `tutorial.da.md` (language code present)

## Files

- **index.md**: Source file in English (should be translated)
- **index.es.md**: Existing Spanish translation (should be skipped)
- **tutorial.md**: Source file in English (should be translated)
- **_index.md**: Hugo special file in English (should be translated)

## Expected Behavior

When translating this directory to languages [da, fr]:

**Should translate**:
- index.md → index.da.md, index.fr.md
- tutorial.md → tutorial.da.md, tutorial.fr.md
- _index.md → _index.da.md, _index.fr.md

**Should skip**:
- index.es.md (already translated to Spanish)

**Should NOT create**:
- index.es.da.md (double-language file)
- index.es.fr.md (double-language file)

## Usage

```bash
pytest tests/integration/test_source_file_filtering_e2e.py -xvs
```
