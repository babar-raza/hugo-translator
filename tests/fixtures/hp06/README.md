# HP-06 Test Fixtures

This directory contains test fixtures for HP-06 (AST-Based Complete Body Reconstruction) implementation and validation.

## Purpose

These fixtures serve as:
1. **Baseline corpus** for testing the new AST-based translation approach
2. **Regression tests** to ensure HP-06 maintains or improves quality
3. **Edge case validation** for comprehensive testing of formatting preservation

## Current Code Architecture (TC-00 Findings)

### Entry Points Documented

#### Extraction Flow:
```
TranslationEngine (src/translation_engine/engine.py)
  └── SegmentExtractor.extract_all() (src/translation_engine/extractor/segment_extractor.py:91)
      ├── extract_from_frontmatter() (line 118)
      └── extract_from_body() (line 114)
          └── _extract_from_node() - recursively extracts text from AST nodes
```

**Current Limitation**: `SegmentExtractor` flattens AST structure to plain text, losing formatting context.

#### Reconstruction Flow:
```
TranslationEngine (src/translation_engine/engine.py)
  └── MarkdownReconstructor.reconstruct_document() (src/translation_engine/reconstructor/markdown_reconstructor.py:37)
      ├── reconstruct_frontmatter() (line 97)
      └── reconstruct_body() (line 65)
          └── _render_node() - renders AST nodes back to markdown
```

**Current Limitation**: Relies on placeholders to preserve formatting, which MT models corrupt.

#### AST Structure:
```
HugoParser (src/translation_engine/parser/hugo_parser.py)
  └── parse_string() (line 92) - Creates HugoDocument with:
      ├── frontmatter: Dict (YAML metadata)
      └── ast: List[ASTNode] (markdown body structure)
```

**AST Node Types** (from ast_nodes.py):
- `TEXT`: Plain text content
- `HEADING`: Heading with level
- `PARAGRAPH`: Paragraph container
- `STRONG`: Bold formatting
- `EMPHASIS`: Italic formatting
- `CODE_BLOCK`: Code block
- `CODE_SPAN`: Inline code
- `LINK`: Hyperlink with URL
- `IMAGE`: Image with src
- `LIST`: Ordered/unordered list
- `LIST_ITEM`: List item
- `TABLE`: Table structure
- etc.

### HP-06 Changes Required

**New Components** (will be added in TC-01 through TC-05):
- `TextUnit` data model (TC-01)
- `BodyTranslationPlan` data model (TC-01)
- Node addressing system (TC-02)
- `TextUnitExtractor` (TC-03)
- AST renderer with translation application (TC-04)
- Engine integration behind feature flag (TC-05)

## Test Coverage

This fixture corpus covers:

### 1. Basic Formatting Elements
- [ ] Bold text (`**text**`)
- [ ] Italic text (`*text*` and `_text_`)
- [ ] Inline code (`` `code` ``)
- [ ] Nested formatting (`**bold *and italic***`)

### 2. Links and Images
- [ ] Simple links (`[text](url)`)
- [ ] Links with titles (`[text](url "title")`)
- [ ] Images (`![alt](src)`)
- [ ] Formatted link text (`**[bold link](url)**`)
- [ ] Link references (`[text][ref]`, `[ref]: url`)
- [ ] Autolinks (`<https://example.com>`)

### 3. Structure Elements
- [ ] Headings (levels 1-6)
- [ ] Ordered lists
- [ ] Unordered lists
- [ ] Nested lists
- [ ] Code blocks (fenced and indented)
- [ ] Tables
- [ ] Blockquotes

### 4. Edge Cases
- [ ] Nested emphasis (`***bold italic***`)
- [ ] HTML blocks (`<div>content</div>`)
- [ ] Escaped characters (`\*not italic\*`)
- [ ] Hard line breaks (2 trailing spaces)
- [ ] Mixed inline elements
- [ ] Empty elements
- [ ] Unicode content (emojis, CJK, RTL)

### 5. Aspose-Specific Content
- [ ] Product names (Aspose.Slides, Aspose.Cells)
- [ ] API references (SaveFormat.Pptx)
- [ ] Code examples with product names
- [ ] Technical documentation patterns

## Test Files

### Basic Elements
- **01_basic_formatting.md**: Bold, italic, inline code, and combinations
- **02_links_images.md**: Links, images, reference-style links, autolinks
- **03_nested_formatting.md**: Complex nesting of bold, italic, code, and links

### Structure Elements
- **04_lists.md**: Ordered, unordered, nested lists with formatting
- **05_tables.md**: Tables with formatting, links, and alignment
- **06_code_blocks.md**: Fenced and indented code blocks
- **07_headings.md**: All heading levels with formatting

### Edge Cases
- **08_edge_cases.md**: Escaped chars, HTML blocks, unicode, special characters
- **09_aspose_content.md**: Product names, API references, technical patterns
- **10_yaml_only.md**: YAML frontmatter with no body content

### Complex Examples
- **11_blockquotes.md**: Blockquotes with nested formatting
- **12_mixed_content.md**: Realistic mixed content with all element types

## Baseline Failure Analysis

**Status**: Completed

See `BASELINE_FAILURES.md` for:
- Quantitative failure metrics (manual analysis of 2 production files)
- Smart Segmentation corpus analysis and fluency distribution validation
- Current TM performance baseline (requires database access)
- Real-world corruption patterns documented from production

**Key Findings**:
- 100% of analyzed files have formatting or link corruption
- Main landing page is broken, impacting all users
- Broken links: ~15-30% (estimated from sample)
- Formatting loss: ~40-60% (estimated from sample)
- Product name corruption: ~5-10% (estimated from sample)

## Product Name Detection

**Status**: Completed

See `PRODUCT_NAME_TESTS.md` for:
- Comprehensive test cases for Aspose products, APIs, tools, and frameworks
- Detection strategies (regex, dictionary, context-aware)
- Expected behavior and edge cases
- Target metrics: >99% preservation rate

## M2M100 Delimiter Testing

**Status**: Framework created (skeleton)

See `tests/unit/translation_engine/extractor/test_m2m100_batching.py` for:
- Adversarial test cases for delimiter corruption
- Test framework structure
- Acceptance criteria: ≥95% delimiter survival rate
- Full implementation in TC-03 after TextUnitExtractor is created
