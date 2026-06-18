# Translation Engine Architecture

📋 Reported: Updated 2026-06-17 to reflect 5-component decomposition from commit `0a684b8` (refactor: decompose TranslationEngine god-class). See [ADR-004](../adr/004-engine-decomposition.md) when created.

**Status**: Core system component - orchestrates complete translation workflow

## Overview

The Hugo Translation System implements a comprehensive translation pipeline that converts Hugo Markdown content while preserving structure, terminology, and quality. The engine was refactored in commit `0a684b8` from a single monolithic class into five collaborating components with clear separation of concerns.

## Core Architecture

### System Components

```
┌─────────────────┐    ┌─────────────────┐
│   CLI Layer     │    │  Worker Layer   │
│ src/cli.py      │    │ src/workers/    │
└────────┬────────┘    └────────┬────────┘
         │                      │
         └──────────┬───────────┘
                    │
         ┌──────────▼──────────┐
         │  TranslationEngine  │   engine.py — orchestrator shell
         │  (entry point only) │   delegates to 4 specialist components
         └──────────┬──────────┘
                    │
      ┌─────────────┼─────────────┐
      │             │             │
┌─────▼──────┐ ┌────▼────┐ ┌────▼──────────┐
│EngineBuilder│ │FilePipe-│ │SegmentTrans-  │
│engine_      │ │line     │ │lator          │
│builder.py   │ │file_    │ │segment_       │
│             │ │pipeline │ │translator.py  │
│Construction │ │.py      │ │               │
│logic: deps, │ │Per-file │ │Segment-level  │
│validation,  │ │retry,   │ │translation:   │
│TM, models   │ │pipeline │ │TM lookup,     │
└─────────────┘ └────┬────┘ │model calls,   │
                     │      │validation     │
                ┌────▼────┐ └───────────────┘
                │WriteGate│
                │Evaluator│
                │write_   │
                │gate.py  │
                │         │
                │Output   │
                │safety:  │
                │accept/  │
                │reject   │
                └─────────┘
                    │
         ┌──────────▼──────────┐
         │   Storage Layer     │
         │                     │
         │ • TM (L1/L2/L3)     │
         │ • Models (M2M100)   │
         │ • Content Hashes    │
         └─────────────────────┘
```

### Five Engine Components (post-refactor, commit `0a684b8`)

| File | Class | Responsibility |
|------|-------|---------------|
| `engine.py` | `TranslationEngine` | Entry point / orchestration shell; delegates to 4 components |
| `engine_builder.py` | `EngineBuilder` | Construction logic: loads TM, models, validators, site config |
| `file_pipeline.py` | `FileTranslationPipeline` | Per-file retry/validation/correction pipeline per language |
| `segment_translator.py` | `SegmentTranslator` | Segment-level translation: TM lookup → model call → validation |
| `write_gate.py` | `WriteGateEvaluator` | Output safety gate: accept/reject/reroute based on quality |

### Data Flow

1. **Input Processing**: Hugo Markdown files with YAML frontmatter
2. **Parsing**: Convert to AST representation
3. **Segmentation**: Extract translatable text units
4. **Translation Memory**: Lookup existing translations
5. **Model Translation**: Generate new translations
6. **Validation**: Quality checks and corrections
7. **Reconstruction**: Rebuild formatted output
8. **Output**: Translated Hugo files

## Component Details

### Parser (`src/translation_engine/parser/`)

**Purpose**: Convert Hugo Markdown to internal AST representation

**Key Classes**:
- `HugoParser`: Main parsing class using `markdown-it-py`
- `HugoDocument`: Parsed document with frontmatter and AST
- `ASTNode`: Hierarchical node structure with types and metadata

**Features**:
- YAML frontmatter extraction
- CommonMark-compliant Markdown parsing
- Unique node ID generation for tracking
- Support for code blocks, headings, links, lists
- Encoding detection (UTF-8 with latin-1 fallback)

**Integration**:
```python
parser = HugoParser()
doc = parser.parse_file(Path("content/post.md"))
# Result: HugoDocument with frontmatter dict and AST nodes
```

### Segment Extractor (`src/translation_engine/extractor/`)

**Purpose**: Extract translatable text segments from AST

**Key Classes**:
- `SegmentExtractor`: Main extraction logic
- `TextUnitExtractor`: Advanced AST-based extraction
- `Segment`: Individual translatable unit with context

**Features**:
- Context-aware extraction (frontmatter vs body)
- Placeholder protection for shortcodes, links, code
- Multiline content handling
- Terminology protection integration
- AST-based node addressing

**Integration**:
```python
extractor = SegmentExtractor(site_profile)
segments = extractor.extract_all(doc, source_lang)
# Result: List of Segment objects ready for translation
```

### Translation Memory (`src/tm/`)

**Purpose**: Store and retrieve translations for reuse

**Architecture**: 3-layer system

#### L1 Cache (In-Memory)
- **Purpose**: Fast access for recent translations
- **Implementation**: `L1Cache` with LRU eviction
- **Size**: Configurable (default: 10,000 entries)
- **Performance**: Sub-millisecond lookups

#### L2 Persistent (LMDB)
- **Purpose**: Persistent storage for all translations
- **Implementation**: `L2PersistentTM` using LMDB database
- **Features**: ACID transactions, concurrent access
- **Size**: Limited by disk space (default: 1GB max)

#### L3 Semantic (FAISS)
- **Purpose**: Fuzzy matching using embeddings
- **Implementation**: `L3SemanticTM` with FAISS index
- **Features**: Cosine similarity, batch processing
- **Models**: Sentence transformers for embedding generation

**Integration**:
```python
tm = TranslationMemory(l1_cache, l2_persistent, l3_semantic)
result = tm.lookup(site_id, src_lang, tgt_lang, text)
if result.hit:
    translation = result.translation
```

### Model Runtime (`src/model_runtime/`)

**Purpose**: Manage translation models and hardware

**Key Classes**:
- `ModelLoader`: Load and manage models
- `ModelRegistry`: Catalog of available models
- `HardwareDetector`: GPU/CPU detection and optimization

**Supported Models**:
- **HuggingFace Transformers**: M2M100, NLLB, etc.
- **CTranslate2**: Optimized inference (faster, lower memory)
- **Local LLMs**: Ollama integration

**Hardware Optimization**:
- Automatic GPU detection
- CPU optimization for large batches
- Memory management and cleanup

**Integration**:
```python
registry = ModelRegistry(Path("config/model_registry.yaml"))
loader = ModelLoader(registry, device="auto")
model = loader.load_model("m2m100_418m")
```

### Validation System (`src/translation_engine/validation/`)

**Purpose**: Ensure translation quality before output

**Architecture**: 10 validators with decision engine

#### Validators

1. **YAMLValidator**: Frontmatter syntax
2. **PlaceholderValidator**: Placeholder integrity
3. **StructureValidator**: Markdown structure preservation
4. **LinkValidator**: Link preservation
5. **CompletenessValidator**: 100% segment coverage
6. **LanguageConsistencyValidator**: Target language detection
7. **ShortcodePreservationValidator**: Hugo shortcode integrity
8. **FrontmatterProtectionValidator**: Field-level rules
9. **TerminologyPreservationValidator**: Term protection
10. **FilePlacementValidator**: Output structure validation

#### Decision Engine

**Logic**: ACCEPT/RETRY/REJECT based on configurable rules

```python
# Decision priority (highest to lowest)
if critical_validator_failed:
    return REJECT
if error_count >= threshold:
    return REJECT
if no_errors:
    return ACCEPT
if retries_available:
    return RETRY
return ACCEPT  # best effort after retries
```

**Integration**:
```python
suite = ValidationSuite()
results = suite.validate_aggregated(source, translated, context)
decision = decision_engine.make_decision(results)
```

### Reconstructor (`src/translation_engine/reconstructor/`)

**Purpose**: Rebuild Hugo Markdown from translated segments

**Key Classes**:
- `MarkdownReconstructor`: Legacy segment-based reconstruction
- `ASTRenderer`: Node-addressed AST reconstruction
- `YAMLFormatter`: Frontmatter formatting

**Features**:
- AST-based reconstruction for perfect structure preservation
- Frontmatter translation with field rules
- Placeholder restoration
- Output path generation

**Integration**:
```python
reconstructor = MarkdownReconstructor(site_profile)
translated_doc = reconstructor.reconstruct(doc, translations, target_lang)
```

## Advanced Features

### AST-Based Translation

**Purpose**: Perfect structure preservation through node-addressed translation

**Process**:
1. Parse to AST with node IDs
2. Extract TextUnits with node addressing
3. Translate units (batch + fallback)
4. Apply translations back to AST
5. Render to Markdown

**Benefits**:
- 100% structure preservation
- No line count drift
- Perfect formatting retention
- Complex content support

### Multiline Structure Preservation

**Purpose**: Handle content with multiple lines (lists, structured text)

**Features**:
- Line-by-line translation with structure preservation
- Bullet point and numbering retention
- Indentation preservation
- Empty line handling

**Integration**:
```python
handler = MultilineHandler()
result = handler.translate(text, translate_fn)
# Preserves line count and formatting
```

### Terminology Protection

**Purpose**: Prevent mistranslation of critical terms

**Methods**:
- **Protection**: Replace terms with placeholders before translation
- **Validation**: Check term presence after translation
- **Patterns**: Regex support for dynamic terminology

**Example**:
```
Source: "Aspose.Words for .NET"
Protected: "{TERM_0} for {TERM_1}"
Translated: "{TERM_0} für {TERM_1}"
Restored: "Aspose.Words für .NET"
```

### Post-Translation Verification

**Purpose**: Detect quality issues after main processing

**Checks**:
- Language detection (is output in target language?)
- Content filtering (skip technical terms)
- Confidence thresholds
- Integration with validation retry logic

**Requires**: `langdetect` library

## Configuration Integration

### Site Profiles

Each site has configuration for:
- Content roots and output patterns
- Frontmatter translation rules
- TM preferences (semantic threshold, etc.)
- Validation overrides
- Terminology settings

### Global Configuration

System-wide settings in `config/global.yaml`:
- TM defaults (cache sizes, thresholds)
- Model defaults (fallback model, device)
- Hardware settings (GPU memory, CPU optimization)
- Validation rules and modes
- Terminology patterns

## Performance Characteristics

### Memory Usage
- **L1 Cache**: ~50MB for 10K entries
- **Models**: 2-16GB depending on model size
- **AST Processing**: Minimal additional memory
- **Batch Processing**: Scales with batch size

### Throughput
- **Single file**: 1-5 seconds depending on length
- **Batch processing**: 10-50 files/minute
- **Parallel workers**: Scales with CPU cores
- **GPU acceleration**: 2-5x faster for supported models

### Optimization Features
- Model caching and reuse
- TM hit rate optimization
- CPU batch size optimization
- Memory cleanup between batches

## Error Handling

### Validation Failures
- **RETRY**: Attempt retranslation with feedback
- **REJECT**: Discard translation, log error
- **ACCEPT**: Proceed with warnings

### System Errors
- Graceful degradation (CPU fallback for GPU failures)
- TM unavailability handling
- Model loading error recovery
- File I/O error handling

### Logging and Monitoring
- Structured logging with context
- Telemetry integration
- Metrics collection
- Health check endpoints

## Testing Strategy

### Unit Tests
- Component isolation testing
- Mock external dependencies
- Edge case coverage
- Performance regression detection

### Integration Tests
- End-to-end workflow testing
- Component interaction validation
- Configuration testing
- Error scenario testing

### Performance Tests
- Benchmarking against baselines
- Memory usage monitoring
- Scalability testing
- Load testing

## Future Enhancements

### Planned Features
- **Enhanced AST support**: Tables, footnotes, complex structures
- **Model fine-tuning**: Domain-specific adaptation
- **Active learning**: Continuous improvement from corrections
- **Multi-language batching**: Cross-language optimization

### Scalability Improvements
- **Distributed processing**: Multi-node translation clusters
- **Streaming processing**: Large file handling
- **Incremental updates**: Partial content translation
- **Caching optimization**: Advanced cache strategies

## Integration Points

### CLI Interface
- Command-line translation execution
- Configuration override support
- Progress reporting and logging

### MCP Server
- API-based translation requests
- Distributed worker management
- Health monitoring and statistics

### Orchestrator
- Automated file watching
- Batch processing coordination
- Scheduling and queue management

## Related Documentation

- [Parser Architecture](parser.md) - Detailed parsing implementation
- [Validation Guide](../guides/quality-improvement.md) - Quality assurance system
- [Configuration Reference](../reference/config.md) - Complete config options
- [CLI Reference](../reference/cli.md) - Command-line interface
- [API Reference](../reference/api.md) - Programmatic interfaces
