

# Segment Extractor Documentation

**Module**: `src.translation_engine.extractor`
**Phase**: 2
**Task**: 2.2

---

## Overview

The Segment Extractor module extracts translatable segments from parsed Hugo documents based on Site Profile rules. It handles frontmatter extraction, body text extraction, and placeholder protection for non-translatable content like Hugo shortcodes and code blocks.

---

## Architecture

### Components

1. **Segment Model** (`segment_extractor.py`)
   - Represents a translatable unit with context
   - Unique ID generation based on content and context
   - Placeholder mapping for protected content

2. **SegmentContext** (`segment_extractor.py`)
   - Context information for each segment
   - Type, node ID, frontmatter key tracking
   - Parent node and depth information

3. **SegmentExtractor** (`segment_extractor.py`)
   - Main extraction engine
   - Applies site profile rules
   - Coordinates placeholder protection

4. **PlaceholderManager** (`placeholder_manager.py`)
   - Protects non-translatable content
   - Pattern-based replacement with placeholders
   - Restoration of original content

---

## Key Classes

### SegmentContextType (Enum)

Defines types of segment contexts:

```python
class SegmentContextType(str, Enum):
    FRONTMATTER = "frontmatter"
    BODY_TEXT = "body_text"
    HEADING = "heading"
    LIST_ITEM = "list_item"
```

### SegmentContext (Dataclass)

Context information for a segment:

```python
@dataclass
class SegmentContext:
    context_type: SegmentContextType
    node_id: Optional[str] = None
    frontmatter_key: Optional[str] = None
    parent_node_type: Optional[NodeType] = None
    depth: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
```

**Attributes**:
- `context_type`: Type of segment (frontmatter, body, heading, etc.)
- `node_id`: AST node ID for body segments
- `frontmatter_key`: Key path for frontmatter segments (e.g., "banner.title")
- `parent_node_type`: Type of parent AST node
- `depth`: Nesting depth in AST
- `metadata`: Additional context information

### Segment (Dataclass)

A translatable unit:

```python
@dataclass
class Segment:
    id: str
    source_text: str
    context: SegmentContext
    site_id: str
    source_lang: str
    placeholder_map: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
```

**Attributes**:
- `id`: Unique segment identifier (SHA-256 hash)
- `source_text`: Text to translate (with placeholders)
- `context`: Segment context information
- `site_id`: Site identifier
- `source_lang`: Source language code
- `placeholder_map`: Mapping of placeholders to protected content
- `metadata`: Additional segment metadata

**Methods**:

#### `create_id(text: str, context: SegmentContext, site_id: str) -> str`

Generate a stable, unique segment ID:

```python
seg_id = Segment.create_id("Hello World", context, "test-site")
# Returns: "a3b4c5d6e7f8g9h0"  (16-char hex hash)
```

**Algorithm**:
1. Combine text, context type, site ID
2. Add frontmatter key or node ID if present
3. SHA-256 hash the combined string
4. Return first 16 hex characters

**Stability**: Same input always produces same ID, enabling consistent segment tracking.

### SegmentExtractor

Main extraction engine:

```python
class SegmentExtractor:
    def __init__(self, site_profile: SiteProfile):
        """Initialize with site-specific rules."""

    def extract_all(
        self,
        doc: HugoDocument,
        source_lang: Optional[str] = None
    ) -> List[Segment]:
        """Extract all segments from document."""

    def extract_from_frontmatter(
        self,
        frontmatter: Dict[str, Any],
        source_lang: str
    ) -> List[Segment]:
        """Extract segments from frontmatter."""

    def extract_from_body(
        self,
        ast: List[ASTNode],
        source_lang: str
    ) -> List[Segment]:
        """Extract segments from body AST."""
```

**Initialization**:
```python
from utils.models import SiteProfile
from translation_engine.extractor import SegmentExtractor

profile = config_service.get_site_profile("test-site")
extractor = SegmentExtractor(profile)
```

**Key Features**:
- Applies frontmatter rules (translate, passthrough, list, ignore)
- Respects body preserve rules (skip code blocks, etc.)
- Protects Hugo shortcodes and patterns
- Handles nested frontmatter with dot notation
- Tracks segment context for reconstruction

### PlaceholderManager

Protects non-translatable content:

```python
class PlaceholderManager:
    def protect(
        self,
        text: str,
        patterns: List[str]
    ) -> Tuple[str, Dict[str, str]]:
        """Replace protected content with placeholders."""

    def restore(
        self,
        text: str,
        placeholder_map: Dict[str, str]
    ) -> str:
        """Restore placeholders to original content."""

    def extract_placeholders(self, text: str) -> List[str]:
        """Extract all placeholder tokens from text."""
```

**Usage**:
```python
pm = PlaceholderManager()
patterns = [r"\{\{<.*?>\}\}", r"`[^`]+`"]

# Protect
text = "Text {{< shortcode >}} and `code`"
protected, mapping = pm.protect(text, patterns)
# protected: "Text {PLACEHOLDER_0} and {PLACEHOLDER_1}"
# mapping: {"{PLACEHOLDER_0}": "{{< shortcode >}}", "{PLACEHOLDER_1}": "`code`"}

# Restore
restored = pm.restore(protected, mapping)
# restored: "Text {{< shortcode >}} and `code`"
```

---

## Usage Examples

### Basic Extraction

```python
from translation_engine.parser import HugoParser
from translation_engine.extractor import SegmentExtractor
from utils.config_loader import ConfigService

# Load configuration
config_service = ConfigService("config")
profile = config_service.get_site_profile("test-site")

# Parse document
parser = HugoParser()
doc = parser.parse_file("content/blog/post.md")

# Extract segments
extractor = SegmentExtractor(profile)
segments = extractor.extract_all(doc)

# Process segments
for segment in segments:
    print(f"ID: {segment.id}")
    print(f"Text: {segment.source_text}")
    print(f"Context: {segment.context.context_type}")
    print(f"Language: {segment.source_lang}")
    print()
```

### Frontmatter Extraction

```python
# Site profile with frontmatter rules
profile = SiteProfile(
    site_id="test",
    frontmatter={
        "title": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
        "tags": FrontmatterRule(mode=FrontmatterMode.TRANSLATE_LIST),
        "draft": FrontmatterRule(mode=FrontmatterMode.PASSTHROUGH),
        "banner.title": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
    },
    # ... other config
)

# Document with frontmatter
content = """---
title: "My Page"
draft: false
tags:
  - tag1
  - tag2
banner:
  title: "Banner Title"
---

Content here.
"""

doc = parser.parse_string(content)
extractor = SegmentExtractor(profile)
segments = extractor.extract_from_frontmatter(doc.frontmatter, "en")

# Results:
# - 1 segment for "title": "My Page"
# - 2 segments for tags: "tag1", "tag2"
# - 1 segment for "banner.title": "Banner Title"
# - No segment for "draft" (passthrough mode)
# Total: 4 segments
```

### Body Extraction with Filtering

```python
# Profile with body rules
profile = SiteProfile(
    site_id="test",
    body=BodyRules(
        translate_markdown=True,
        preserve_blocks=["block_code", "inline_code"],
        preserve_patterns=[],
        placeholder_syntax=[r"\{\{<.*?>\}\}", r"\{\{%.*?%\}\}"],
    ),
    # ... other config
)

content = """# Heading

Paragraph with {{< shortcode >}} embedded.

```python
def code():
    pass
```

Another paragraph.
"""

doc = parser.parse_string(content)
extractor = SegmentExtractor(profile)
segments = extractor.extract_from_body(doc.ast, "en")

# Results:
# - 1 segment for heading: "Heading"
# - 1 segment for paragraph: "Paragraph with {PLACEHOLDER_0} embedded."
# - 0 segments for code block (preserved)
# - 1 segment for second paragraph: "Another paragraph."
# Total: 3 segments
```

### Working with Placeholders

```python
# Extract with placeholders
segments = extractor.extract_all(doc)

for seg in segments:
    if seg.placeholder_map:
        print(f"Segment: {seg.source_text}")
        print(f"Placeholders: {seg.placeholder_map}")

        # Simulate translation
        translated = translate_text(seg.source_text)  # Your translation function

        # Restore placeholders
        pm = PlaceholderManager()
        final_text = pm.restore(translated, seg.placeholder_map)
        print(f"Final: {final_text}")
```

### Filtering by Context Type

```python
segments = extractor.extract_all(doc)

# Get only frontmatter segments
fm_segments = [
    s for s in segments
    if s.context.context_type == SegmentContextType.FRONTMATTER
]

# Get only heading segments
heading_segments = [
    s for s in segments
    if s.context.context_type == SegmentContextType.HEADING
]

# Get body text segments
body_segments = [
    s for s in segments
    if s.context.context_type == SegmentContextType.BODY_TEXT
]
```

---

## Extraction Rules

### Frontmatter Rules

#### TRANSLATE Mode

Extract single string value:

```yaml
frontmatter:
  title:
    mode: translate
```

Input:
```yaml
---
title: "Hello World"
---
```

Output: 1 segment with text "Hello World"

#### TRANSLATE_LIST Mode

Extract each list item as separate segment:

```yaml
frontmatter:
  tags:
    mode: translate_list
```

Input:
```yaml
---
tags:
  - python
  - hugo
  - translation
---
```

Output: 3 segments ("python", "hugo", "translation")

#### PASSTHROUGH Mode

Do not extract (copy as-is):

```yaml
frontmatter:
  draft:
    mode: passthrough
```

Input:
```yaml
---
draft: false
date: 2024-01-01
---
```

Output: 0 segments (will be copied unchanged during reconstruction)

#### IGNORE Mode

Skip entirely:

```yaml
frontmatter:
  internal_id:
    mode: ignore
```

#### Nested Fields (Dot Notation)

```yaml
frontmatter:
  banner.title:
    mode: translate
  banner.subtitle:
    mode: translate
```

Input:
```yaml
---
banner:
  title: "Main Title"
  subtitle: "Subtitle Here"
---
```

Output: 2 segments

### Body Rules

#### Preserve Blocks

Skip specific node types:

```yaml
body:
  preserve_blocks:
    - block_code      # Skip fenced code blocks
    - inline_code     # Skip inline `code`
```

#### Preserve Patterns

Protect with placeholders using regex:

```yaml
body:
  preserve_patterns:
    - "https?://[^\\s]+"     # URLs
    - "\\d{4}-\\d{2}-\\d{2}"  # Dates
```

#### Placeholder Syntax

Protect Hugo shortcodes:

```yaml
body:
  placeholder_syntax:
    - "\\{\\{<.*?>\\}\\}"    # {{< shortcode >}}
    - "\\{\\{%.*?%\\}\\}"    # {{% shortcode %}}
```

---

## Segment ID Algorithm

### Purpose

Stable, unique identifiers for segments enable:
- Consistent TM lookups across runs
- Change detection (same ID = unchanged segment)
- Reconstruction mapping (segment ID → AST node)

### Implementation

```python
def create_id(text: str, context: SegmentContext, site_id: str) -> str:
    content = f"{site_id}:{context.context_type}:{text}"
    if context.frontmatter_key:
        content += f":{context.frontmatter_key}"
    if context.node_id:
        content += f":{context.node_id}"

    return hashlib.sha256(content.encode()).hexdigest()[:16]
```

### Properties

**Stability**: Same input → same ID
```python
# Both calls produce same ID
id1 = Segment.create_id("Hello", context, "site1")
id2 = Segment.create_id("Hello", context, "site1")
assert id1 == id2
```

**Uniqueness**: Different input → different ID
```python
id1 = Segment.create_id("Hello", context, "site1")
id2 = Segment.create_id("World", context, "site1")
id3 = Segment.create_id("Hello", context, "site2")
assert id1 != id2 != id3
```

**Collision Resistance**: SHA-256 ensures minimal collisions

### ID Format

- Length: 16 hexadecimal characters
- Example: `"a3b4c5d6e7f8g9h0"`
- Range: 16^16 = 18.4 quintillion possible IDs

---

## Integration with Translation Pipeline

### Upstream (Input)

**From Hugo Parser**:
```python
# Parse document
parser = HugoParser()
doc = parser.parse_file("content/post.md")

# doc.frontmatter: Dict[str, Any]
# doc.ast: List[ASTNode]
```

### Extraction Phase

```python
# Load profile
profile = config_service.get_site_profile("test-site")

# Extract segments
extractor = SegmentExtractor(profile)
segments = extractor.extract_all(doc, source_lang="en")

# segments: List[Segment]
```

### Downstream (Output)

**To Translation Memory**:
```python
for segment in segments:
    # Check TM for existing translation
    tm_result = tm_service.lookup(
        text=segment.source_text,
        source_lang=segment.source_lang,
        target_lang="es",
        context=segment.context,
    )
```

**To Translation Model**:
```python
# Segments without TM matches
untranslated = [s for s in segments if not tm_service.has_translation(s)]

# Send to model
translations = model_service.translate_batch(
    segments=untranslated,
    target_lang="es",
)
```

**To Content Reconstructor** (Task 2.3):
```python
# Collect translations
translation_map = {seg.id: translated_text for seg, translated_text in ...}

# Reconstruct document
reconstructor = MarkdownReconstructor(profile)
translated_doc = reconstructor.reconstruct_document(
    doc=doc,
    translations=translation_map,
    target_lang="es",
)
```

---

## Performance Considerations

### Extraction Speed

- **Target**: <50ms for 10KB document
- **Actual**: ~10-20ms for typical documents
- **Bottlenecks**: Regex pattern matching (placeholder protection)

### Memory Usage

- **Segments**: ~500 bytes per segment (text + context + placeholders)
- **Typical Document**: 20-50 segments = 10-25 KB
- **Large Documents**: 200+ segments = 100+ KB

### Optimization Strategies

1. **Pattern Compilation**: Compile regex patterns once during initialization
2. **Lazy Extraction**: Only extract frontmatter or body if needed
3. **Streaming**: Process large ASTs in chunks (future enhancement)

---

## Testing

### Test Coverage

**File**: `tests/unit/phase-2/test_segment_extractor.py`
**Tests**: 16
**Coverage**: 90% (segment_extractor.py), 93% (placeholder_manager.py)

### Test Categories

1. **PlaceholderManager Tests** (3 tests)
   - Protect and restore
   - Multiple patterns
   - Extract placeholders

2. **Segment Model Tests** (1 test)
   - ID generation stability and uniqueness

3. **SegmentExtractor Tests** (12 tests)
   - Initialization
   - Frontmatter extraction (simple, list, nested)
   - Body extraction (paragraphs, inline code, shortcodes)
   - Code block skipping
   - Full document extraction
   - Fixture file testing
   - Empty document handling
   - Segment ID uniqueness

### Running Tests

```bash
# Run all extractor tests
pytest tests/unit/phase-2/test_segment_extractor.py -v

# Run with coverage
pytest tests/unit/phase-2/test_segment_extractor.py --cov=src/translation_engine/extractor

# Run specific test class
pytest tests/unit/phase-2/test_segment_extractor.py::TestSegmentExtractor -v
```

---

## Error Handling

### Invalid Patterns

```python
# Invalid regex pattern
patterns = [r"[invalid(regex"]

# PlaceholderManager handles gracefully
pm = PlaceholderManager()
protected, mapping = pm.protect(text, patterns)
# Returns text unchanged if pattern is invalid
```

### Missing Frontmatter Keys

```python
# Profile references non-existent key
profile.frontmatter = {
    "nonexistent.key": FrontmatterRule(mode=FrontmatterMode.TRANSLATE)
}

# Extractor handles gracefully
segments = extractor.extract_from_frontmatter(frontmatter, "en")
# Returns empty list for missing keys (no error)
```

### Empty or Whitespace-Only Text

```python
# Document with empty paragraphs
content = "# Heading\n\n   \n\nText"

# Only non-empty segments extracted
segments = extractor.extract_from_body(ast, "en")
# Skips whitespace-only nodes
```

---

## Best Practices

### Profile Configuration

1. **Be Explicit**: Define all frontmatter fields you want to translate
2. **Use PASSTHROUGH**: For fields that should be copied (dates, slugs, etc.)
3. **Protect Code**: Always include code blocks in `preserve_blocks`
4. **Pattern Testing**: Test regex patterns with sample content first

### Segment Processing

1. **Check Placeholders**: Always restore placeholders after translation
2. **Preserve Order**: Maintain segment order for reconstruction
3. **Handle Missing**: Account for segments without translations

### Performance

1. **Batch Processing**: Extract from multiple documents before translating
2. **Cache Profiles**: Reuse `SegmentExtractor` instances for same site
3. **Filter Early**: Skip extraction if document is up-to-date

---

## Limitations and Future Work

### Current Limitations

1. **No Image Alt Text**: Image nodes not yet implemented
2. **No Link Titles**: Link nodes not yet implemented
3. **No Table Cells**: Table parsing not yet implemented
4. **No Emphasis Text**: Bold/italic text treated as plain text

### Planned Enhancements (Task 2.3+)

1. **Link Extraction**: Parse and extract link text and titles
2. **Image Alt Text**: Extract translatable alt attributes
3. **Table Support**: Extract table cell content
4. **Emphasis Preservation**: Track and restore bold/italic formatting
5. **Smart Segmentation**: Split long paragraphs at sentence boundaries

---

## References

- Site Profile Schema (phase-1 archived)
- Hugo Parser Documentation (planned — not yet created)
- [Hugo Shortcode Reference](https://gohugo.io/content-management/shortcodes/)
- [Regex Pattern Reference](https://docs.python.org/3/library/re.html)

---

**Last Updated**: 2025-01-19
**Status**: ✅ Complete
**Test Coverage**: 90%
**Next Task**: 2.3 - Content Reconstructor
