# Content Reconstructor Documentation

**Module**: `src.translation_engine.reconstructor`
**Phase**: 2
**Task**: 2.3

---

## Overview

The Content Reconstructor module rebuilds Hugo Markdown documents from translated segments and the original AST. It applies site profile rules to handle different frontmatter modes and preserves document structure during reconstruction.

---

## Architecture

### Components

1. **MarkdownReconstructor** (`markdown_reconstructor.py`)
   - Main reconstruction engine
   - Applies frontmatter rules
   - Rebuilds Markdown from AST
   - Manages segment-to-node mapping

2. **YAMLFormatter** (`yaml_formatter.py`)
   - YAML frontmatter formatting
   - Nested dictionary operations
   - Hugo-compatible output

---

## Key Classes

### YAMLFormatter

Utility class for YAML operations:

```python
class YAMLFormatter:
    @staticmethod
    def format_frontmatter(data: Dict[str, Any]) -> str:
        """Format frontmatter with --- delimiters."""

    @staticmethod
    def set_nested_value(data: Dict, key: str, value: Any) -> None:
        """Set value using dot notation (e.g., 'banner.title')."""

    @staticmethod
    def get_nested_value(data: Dict, key: str, default=None) -> Any:
        """Get value using dot notation."""
```

### MarkdownReconstructor

Main reconstruction class:

```python
class MarkdownReconstructor:
    def __init__(self, site_profile: SiteProfile):
        """Initialize with site-specific rules."""

    def reconstruct_document(
        self,
        doc: HugoDocument,
        translations: Dict[str, str],
        target_lang: str,
        segment_map: Optional[Dict[str, str]] = None,
    ) -> str:
        """Reconstruct complete Hugo document."""

    def reconstruct_frontmatter(
        self,
        original: Dict[str, Any],
        translations: Dict[str, str],
        target_lang: str,
    ) -> Dict[str, Any]:
        """Reconstruct frontmatter with translations."""

    def reconstruct_body(
        self,
        original_ast: List[ASTNode],
        translations: Dict[str, str],
        target_lang: str,
    ) -> str:
        """Reconstruct Markdown body from AST."""
```

---

## Usage Examples

### Basic Reconstruction

```python
from translation_engine.parser import HugoParser
from translation_engine.extractor import SegmentExtractor
from translation_engine.reconstructor import MarkdownReconstructor
from utils.config_loader import ConfigService

# Load configuration
config_service = ConfigService("config")
profile = config_service.get_site_profile("test-site")

# Parse original document
parser = HugoParser()
doc = parser.parse_file("content/post.md")

# Extract segments
extractor = SegmentExtractor(profile)
segments = extractor.extract_all(doc, "en")

# Get translations (from TM or translation model)
translations = {}
segment_map = {}
for seg in segments:
    if seg.context.node_id:
        segment_map[seg.context.node_id] = seg.id
    translations[seg.id] = get_translation(seg)  # Your translation function

# Reconstruct document
reconstructor = MarkdownReconstructor(profile)
translated_doc = reconstructor.reconstruct_document(
    doc, translations, "es", segment_map
)

# Write to file
output_path = Path("content/es/post.md")
output_path.write_text(translated_doc, encoding="utf-8")
```

### Frontmatter Reconstruction

```python
# Profile with different frontmatter modes
profile = SiteProfile(
    site_id="test",
    frontmatter={
        "title": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
        "tags": FrontmatterRule(mode=FrontmatterMode.TRANSLATE_LIST),
        "draft": FrontmatterRule(mode=FrontmatterMode.PASSTHROUGH),
        "lang": FrontmatterRule(mode=FrontmatterMode.COMPUTED),
        "internal_id": FrontmatterRule(mode=FrontmatterMode.IGNORE),
    },
    # ... other config
)

# Original frontmatter
original = {
    "title": "Hello World",
    "tags": ["python", "hugo"],
    "draft": False,
    "internal_id": "12345",
}

reconstructor = MarkdownReconstructor(profile)
result = reconstructor.reconstruct_frontmatter(
    original, translations, "es"
)

# Result:
# {
#     "title": "Hola Mundo",           # TRANSLATE: translated
#     "tags": ["pitón", "hugo"],       # TRANSLATE_LIST: each item translated
#     "draft": False,                  # PASSTHROUGH: copied as-is
#     "lang": "es",                    # COMPUTED: generated
#     # "internal_id" removed (IGNORE mode)
# }
```

### Body Reconstruction

```python
# Parse document
content = """# Heading

This is a paragraph.

```python
def code():
    pass
```

Another paragraph.
"""

doc = parser.parse_string(content)
segments = extractor.extract_all(doc, "en")

# Create translations
translations = {}
segment_map = {}
for seg in segments:
    if seg.context.node_id:
        segment_map[seg.context.node_id] = seg.id
    # Translate segment
    translations[seg.id] = translate(seg.source_text, "es")

# Reconstruct body
reconstructor = MarkdownReconstructor(profile)
reconstructor._segment_map = segment_map
result = reconstructor.reconstruct_body(doc.ast, translations, "es")

# Result:
# # Título
#
# Este es un párrafo.
#
# ```python
# def code():
#     pass
# ```
#
# Otro párrafo.
```

---

## Frontmatter Modes

### TRANSLATE

Translate single string field:

```python
# Rule: title → translate
original: {"title": "Hello"}
translated: {"title": "Hola"}
```

### TRANSLATE_LIST

Translate each list item:

```python
# Rule: tags → translate_list
original: {"tags": ["tag1", "tag2"]}
translated: {"tags": ["etiqueta1", "etiqueta2"]}
```

### PASSTHROUGH

Copy unchanged:

```python
# Rule: draft → passthrough
original: {"draft": False, "date": "2024-01-01"}
translated: {"draft": False, "date": "2024-01-01"}  # Same
```

### COMPUTED

Generate value:

```python
# Rule: lang → computed
original: {"title": "Hello"}
translated: {"title": "Hola", "lang": "es"}  # lang added
```

Supported computed fields:
- `lang`: Set to target language

### IGNORE

Remove from output:

```python
# Rule: internal_id → ignore
original: {"title": "Hello", "internal_id": "123"}
translated: {"title": "Hola"}  # internal_id removed
```

---

## Translation Lookup

### Segment Map

The reconstructor uses a segment map to find translations for body nodes:

```python
# Build segment map during extraction
segment_map = {}
for segment in segments:
    if segment.context.node_id:
        segment_map[segment.context.node_id] = segment.id

# Use during reconstruction
reconstructor.reconstruct_document(doc, translations, "es", segment_map)
```

**Why Needed**: Segment IDs are SHA-256 hashes, not directly containing node IDs. The segment map bridges AST nodes to their translated segments.

### Frontmatter Lookup

Frontmatter translations are found by recreating the segment ID:

```python
# Reconstructor recreates segment ID from original text + context
context = SegmentContext(
    context_type=SegmentContextType.FRONTMATTER,
    frontmatter_key="title",
)
segment_id = Segment.create_id(original_text, context, site_id)

# Look up translation
translation = translations[segment_id]
```

---

## Structure Preservation

### Heading Levels

```python
# Original
# # Heading 1
# ## Heading 2
# ### Heading 3

# Reconstructed (preserves levels)
# # Título 1
# ## Título 2
# ### Título 3
```

### Code Blocks

```python
# Original
```python
def hello():
    return "Hello"
```

# Reconstructed (unchanged)
```python
def hello():
    return "Hello"
```
```

### Inline Code

```python
# Original: "Use the `function()` here"
# Reconstructed: "Usa la `function()` aquí"
# (inline code preserved in segment)
```

---

## Integration with Pipeline

### Full Translation Pipeline

```python
# 1. Parse
parser = HugoParser()
doc = parser.parse_file("content/post.md")

# 2. Extract
extractor = SegmentExtractor(profile)
segments = extractor.extract_all(doc, "en")

# 3. Build segment map
segment_map = {seg.context.node_id: seg.id
               for seg in segments if seg.context.node_id}

# 4. Translate (via TM or model)
translations = {}
for seg in segments:
    # Check TM
    tm_result = tm_service.lookup(seg)
    if tm_result:
        translations[seg.id] = tm_result
    else:
        # Translate with model
        translations[seg.id] = model.translate(seg.source_text, "es")

# 5. Reconstruct
reconstructor = MarkdownReconstructor(profile)
output = reconstructor.reconstruct_document(
    doc, translations, "es", segment_map
)

# 6. Write output
output_path.write_text(output, encoding="utf-8")
```

---

## Testing

### Test Coverage

**File**: `tests/unit/phase-2/test_markdown_reconstructor.py`
**Tests**: 14
**Coverage**: 64% (markdown_reconstructor.py), 90% (yaml_formatter.py)

### Test Categories

1. **YAMLFormatter Tests** (3 tests)
   - Format frontmatter
   - Set nested values
   - Get nested values

2. **MarkdownReconstructor Tests** (8 tests)
   - Frontmatter reconstruction (translate, list, computed)
   - Body reconstruction (paragraphs, code blocks)
   - Full document reconstruction
   - No translations fallback

3. **Roundtrip Tests** (3 tests)
   - Simple roundtrip with identity translation
   - Roundtrip with code blocks
   - Formatting preservation

### Running Tests

```bash
# Run all reconstructor tests
pytest tests/unit/phase-2/test_markdown_reconstructor.py -v

# Run with coverage
pytest tests/unit/phase-2/test_markdown_reconstructor.py --cov=src/translation_engine/reconstructor
```

---

## Best Practices

### Building Segment Maps

Always build segment maps during extraction:

```python
segments = extractor.extract_all(doc, "en")
segment_map = {seg.context.node_id: seg.id
               for seg in segments if seg.context.node_id}
```

### Translation Fallbacks

Handle missing translations gracefully:

```python
for seg in segments:
    if seg.id in translations:
        # Use translation
        pass
    else:
        # Fallback to original
        translations[seg.id] = seg.source_text
```

### Computed Fields

Implement site-specific computed field logic:

```python
def _compute_field(self, key, frontmatter, target_lang):
    if key == "lang":
        return target_lang
    elif key == "slug":
        return slugify(frontmatter.get("title", ""))
    # Add more as needed
```

---

## Limitations and Future Work

### Current Limitations

1. **Limited Computed Fields**: Only `lang` currently supported
2. **No Link Reconstruction**: Link nodes not yet implemented
3. **No Image Alt Text**: Image nodes not yet implemented
4. **Basic List Support**: Nested lists not fully tested

### Planned Enhancements

1. **Enhanced Computed Fields**
   - Slug generation from title
   - URL generation with lang prefix
   - Date formatting per locale

2. **Advanced Formatting**
   - Table reconstruction
   - Definition list support
   - Footnote handling

3. **Placeholder Restoration**
   - Currently simplified
   - Need proper placeholder map integration

---

## References

- [Hugo Parser Documentation](hugo-parser.md)
- [Segment Extractor Documentation](segment-extractor.md)
- [Site Profile Schema](../phase-1/site-profile-schema.md)
- [Hugo Frontmatter Reference](https://gohugo.io/content-management/front-matter/)

---

**Last Updated**: 2025-01-19
**Status**: ✅ Complete
**Test Coverage**: 64%
**Next Phase**: 3 - Translation Memory
