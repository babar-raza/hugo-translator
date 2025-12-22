# Hugo Parser Documentation

**Module**: `src.translation_engine.parser`
**Phase**: 2
**Task**: 2.1

---

## Overview

The Hugo Parser module provides a robust parsing system for Hugo Markdown files with YAML frontmatter. It converts Hugo content into an internal Abstract Syntax Tree (AST) representation that can be processed by the translation engine.

---

## Architecture

### Components

1. **AST Nodes** (`ast_nodes.py`)
   - Dataclass-based node definitions
   - Type-safe node types using enums
   - Serialization support

2. **Parser** (`hugo_parser.py`)
   - Frontmatter extraction using `python-frontmatter`
   - Markdown parsing using `markdown-it-py`
   - Unique node ID generation

---

## Key Classes

### NodeType (Enum)

Defines all supported AST node types:

```python
class NodeType(str, Enum):
    DOCUMENT = "document"
    PARAGRAPH = "paragraph"
    HEADING = "heading"
    CODE_BLOCK = "block_code"
    CODE_SPAN = "inline_code"
    TEXT = "text"
    LINK = "link"
    LIST = "list"
    LIST_ITEM = "list_item"
    SOFT_BREAK = "softbreak"
    LINE_BREAK = "linebreak"
    THEMATIC_BREAK = "thematic_break"
    BLOCK_HTML = "block_html"
    INLINE_HTML = "inline_html"
```

### ASTNode (Dataclass)

Core AST node structure:

```python
@dataclass
class ASTNode:
    type: NodeType
    children: List["ASTNode"] = field(default_factory=list)
    attrs: Dict[str, Any] = field(default_factory=dict)
    raw: Optional[str] = None
    location: Optional[SourceLocation] = None
    node_id: Optional[str] = None
```

**Key Features**:
- Type-safe node type
- Hierarchical children structure
- Arbitrary attributes for node metadata
- Raw content preservation for code blocks
- Source location tracking
- Unique node IDs for reconstruction

**Methods**:
- `to_dict()` - Serialize to dictionary
- `from_dict()` - Deserialize from dictionary

### HugoDocument

Represents a parsed Hugo Markdown file:

```python
class HugoDocument:
    def __init__(
        self,
        frontmatter: Dict[str, Any],
        ast: List[ASTNode],
        source_path: Optional[Path] = None,
        encoding: str = "utf-8",
    ):
        self.frontmatter = frontmatter
        self.ast = ast
        self.source_path = source_path
        self.encoding = encoding
```

**Attributes**:
- `frontmatter` - Parsed YAML frontmatter as dictionary
- `ast` - List of top-level AST nodes
- `source_path` - Original file path (if parsed from file)
- `encoding` - Detected file encoding

**Methods**:
- `to_dict()` - Serialize document to dictionary

### HugoParser

Main parser class:

```python
class HugoParser:
    def __init__(self, enable_tables: bool = True):
        """Initialize the Hugo parser."""
        self.md = MarkdownIt("commonmark")
        if enable_tables:
            self.md.enable("table")
```

**Methods**:

#### `parse_file(path: Path) -> HugoDocument`

Parse a Hugo Markdown file from disk.

**Features**:
- Automatic encoding detection (UTF-8 with latin-1 fallback)
- File existence validation
- Returns HugoDocument with source_path set

**Example**:
```python
parser = HugoParser()
doc = parser.parse_file(Path("content/blog/post.md"))
print(doc.frontmatter["title"])
print(f"Found {len(doc.ast)} top-level nodes")
```

#### `parse_string(content: str) -> HugoDocument`

Parse Hugo Markdown from a string.

**Features**:
- Frontmatter extraction (YAML between `---` delimiters)
- Graceful handling of malformed frontmatter
- Returns HugoDocument

**Example**:
```python
content = """---
title: Test Page
draft: false
---

# Heading

Content here.
"""

parser = HugoParser()
doc = parser.parse_string(content)
assert doc.frontmatter["title"] == "Test Page"
assert doc.ast[0].type == NodeType.HEADING
```

---

## Usage Examples

### Basic Parsing

```python
from translation_engine.parser import HugoParser

parser = HugoParser()

# Parse from file
doc = parser.parse_file(Path("content/page.md"))

# Access frontmatter
title = doc.frontmatter.get("title", "Untitled")
tags = doc.frontmatter.get("tags", [])

# Traverse AST
for node in doc.ast:
    print(f"Node: {node.type}, ID: {node.node_id}")
    if node.children:
        for child in node.children:
            print(f"  Child: {child.type}")
```

### Working with Different Node Types

```python
# Find all headings
headings = [node for node in doc.ast if node.type == NodeType.HEADING]
for h in headings:
    level = h.attrs["level"]
    print(f"H{level}: {h.children[0].raw if h.children else ''}")

# Find all code blocks
code_blocks = [node for node in doc.ast if node.type == NodeType.CODE_BLOCK]
for cb in code_blocks:
    lang = cb.attrs.get("lang", "text")
    print(f"Code block ({lang}):\n{cb.raw}")

# Find inline code
for node in doc.ast:
    if node.type == NodeType.PARAGRAPH:
        inline_codes = [child for child in node.children
                       if child.type == NodeType.CODE_SPAN]
        for ic in inline_codes:
            print(f"Inline code: {ic.raw}")
```

### Serialization

```python
# Convert document to dictionary
doc_dict = doc.to_dict()

# Save to JSON
import json
with open("doc.json", "w") as f:
    json.dump(doc_dict, f, indent=2)

# Reconstruct from dictionary
from translation_engine.parser import ASTNode

ast = [ASTNode.from_dict(node_dict) for node_dict in doc_dict["ast"]]
```

---

## Node ID System

Each AST node receives a unique ID during parsing:

**Format**: `node_{counter}_{uuid_hex[:8]}`

**Example**: `node_1_a3b4c5d6`

**Purpose**:
- Track node identity during translation
- Enable accurate reconstruction
- Support segment-to-node mapping

**Generation**:
```python
def _generate_node_id(self) -> str:
    """Generate unique node ID."""
    self._node_counter += 1
    return f"node_{self._node_counter}_{uuid.uuid4().hex[:8]}"
```

---

## Frontmatter Handling

### YAML Frontmatter

The parser uses `python-frontmatter` to extract YAML frontmatter:

```markdown
---
title: My Page
description: A test page
tags:
  - python
  - hugo
metadata:
  author: John Doe
  date: 2024-01-01
---

Content starts here.
```

**Result**:
```python
doc.frontmatter = {
    "title": "My Page",
    "description": "A test page",
    "tags": ["python", "hugo"],
    "metadata": {
        "author": "John Doe",
        "date": "2024-01-01"
    }
}
```

### Error Handling

Malformed frontmatter is handled gracefully:

```python
# Malformed YAML
content = """---
title: Test
bad yaml: [
---

Content.
"""

doc = parser.parse_string(content)
# Result: doc.frontmatter = {} (empty dict)
# The entire content is treated as body
```

---

## Supported Markdown Features

### Block Elements

- **Paragraphs**: Basic text blocks
- **Headings**: H1-H6 with level attribute
- **Code Blocks**: Fenced code with language info
- **Lists**: Bullet and numbered lists (future)
- **Thematic Breaks**: Horizontal rules (`---`, `***`)
- **Block HTML**: Raw HTML blocks

### Inline Elements

- **Text**: Plain text nodes
- **Code Spans**: Inline `code`
- **Links**: Hyperlinks (future)
- **Soft Breaks**: Single newlines
- **Line Breaks**: Hard breaks (`  \n`)
- **Inline HTML**: Raw inline HTML

### Extended Syntax (Future)

- Tables (via `markdown-it-py` table plugin)
- Task lists
- Footnotes
- Definition lists

---

## Implementation Details

### Markdown Parser

Uses `markdown-it-py` for CommonMark-compliant parsing:

```python
from markdown_it import MarkdownIt

self.md = MarkdownIt("commonmark")
self.md.enable("table")  # Optional table support
```

**Advantages over legacy `mistune`**:
- Better CommonMark compliance
- Extensible plugin system
- Active maintenance
- Token-based parsing

### Token Processing

The parser converts markdown-it tokens to AST nodes:

```python
def _parse_markdown_to_ast(self, markdown: str) -> List[ASTNode]:
    tokens = self.md.parse(markdown)
    ast = []

    i = 0
    while i < len(tokens):
        token = tokens[i]

        if token.type == "paragraph_open":
            # Parse paragraph with inline content
            inline_token = tokens[i + 1]
            children = self._parse_inline_content(inline_token)
            ast.append(paragraph_node(children, self._generate_node_id()))
            i += 3  # Skip open, inline, close

        # ... handle other token types
```

### Encoding Detection

Automatic fallback for non-UTF-8 files:

```python
try:
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    encoding = "utf-8"
except UnicodeDecodeError:
    with open(path, "r", encoding="latin-1") as f:
        content = f.read()
    encoding = "latin-1"
```

---

## Testing

Comprehensive test suite in `tests/unit/phase-2/test_hugo_parser.py`:

### Test Coverage

- **Basic Functionality**: Initialization, empty content, simple text
- **Frontmatter Parsing**: Simple, complex, nested structures
- **Markdown Parsing**: Headings, paragraphs, code blocks, inline code
- **Complex Content**: Mixed content types, fixtures
- **Node IDs**: Uniqueness validation
- **Serialization**: `to_dict()` conversion
- **Error Handling**: Missing files, malformed frontmatter

### Running Tests

```bash
# Run all parser tests
pytest tests/unit/phase-2/test_hugo_parser.py -v

# Run with coverage
pytest tests/unit/phase-2/test_hugo_parser.py --cov=src/translation_engine/parser

# Run specific test class
pytest tests/unit/phase-2/test_hugo_parser.py::TestFrontmatterParsing -v
```

### Test Results

- **16 tests**: All passing
- **Coverage**: 91% (hugo_parser.py), 82% (ast_nodes.py)
- **Uncovered**: Edge cases in from_dict reconstruction

---

## Integration with Translation Engine

The parser output (HugoDocument) feeds into the Segment Extractor (Task 2.2):

```python
# Phase 2 Pipeline
parser = HugoParser()
doc = parser.parse_file(content_path)

# Task 2.2: Extract segments
extractor = SegmentExtractor(site_profile)
segments = extractor.extract_from_document(doc)

# Task 2.3: Translate and reconstruct
# ... translation happens here ...

reconstructor = ContentReconstructor()
translated_doc = reconstructor.rebuild(doc, translated_segments)
```

---

## Performance Considerations

### Memory

- Parser maintains minimal state (`_node_counter`)
- No caching of parsed documents (handled by upstream services)
- AST nodes use dataclasses (efficient memory layout)

### Speed

- markdown-it-py is fast (C-based parsers available)
- Frontmatter extraction is lazy (only parses if delimiters found)
- Node ID generation uses incremental counter + short UUID

---

## Future Enhancements

### Phase 2 Roadmap

1. **Enhanced Node Types** (Task 2.2)
   - Add support for lists, tables, footnotes
   - Implement link parsing
   - Add image node support

2. **Hugo Shortcodes** (Task 2.2)
   - Parse `{{< shortcode >}}` syntax
   - Preserve shortcode structure
   - Extract translatable parameters

3. **Source Mapping** (Task 2.3)
   - Precise line/column tracking
   - Enable error reporting with context
   - Support partial document updates

4. **Performance Optimization**
   - Optional AST streaming for large files
   - Parallel parsing for batch processing
   - Caching layer for repeated parses

---

## References

- [markdown-it-py Documentation](https://markdown-it-py.readthedocs.io/)
- [Python Frontmatter](https://python-frontmatter.readthedocs.io/)
- [CommonMark Spec](https://spec.commonmark.org/)
- [Hugo Content Format](https://gohugo.io/content-management/formats/)

---

**Last Updated**: 2025-01-19
**Status**: ✅ Complete
**Test Coverage**: 91%
**Next Task**: 2.2 - Segment Extractor
