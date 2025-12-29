# Test Fixtures for Source File Filtering

This directory contains test fixtures for validating source file filtering logic.

## Purpose

These fixtures help test the filtering system that prevents double-language translation bugs (e.g., `index.es.da.md`).

## File Patterns

### Source Files (Should be translated)
- `index.md` - Standard source file
- `_index.md` - Hugo special file (source)
- `tutorial.md` - Regular content
- `README.md` - Documentation

### Translated Files (Should be filtered out)
- `index.es.md` - Spanish translation
- `index.da.md` - Danish translation
- `tutorial.fr.md` - French translation
- `post.pt-BR.md` - Brazilian Portuguese (region code)

### Edge Cases
- `index.md.backup` - Backup file (not a markdown file)
- `business.es.md` - Contains "es" but IS a translation
- `espanol.md` - Contains "es" but NOT a translation

## Usage

Tests in `tests/unit/test_source_file_filtering.py` use these patterns to validate:
1. Helper function `_is_translated_filename()` correctness
2. Method `_filter_source_files()` integration
3. Edge case handling (extensions, capitalization, region codes)

## Expected Behavior

For blog.aspose.net pattern (`per_language_folders: false`, `pattern: '{filename}.{lang}{ext}'`):
- **Translate**: Files without language codes (index.md, tutorial.md)
- **Skip**: Files with language codes (index.es.md, tutorial.de.md)
- **Prevent**: Double-language files (index.es.da.md) from being created
