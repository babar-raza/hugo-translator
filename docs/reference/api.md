# API Reference

Source of truth: `src/workers/translation_worker.py`, `src/translation_engine/engine.py`

Public APIs for programmatic access to the Hugo Translation System.

## MCP Server API

The system provides an MCP (Model Context Protocol) server for distributed translation processing. The MCP server exposes translation operations as tools that can be called by MCP clients.

### Server Setup

**Location**: `src/workers/translation_worker.py`

**Entry Point**:
```bash
python -m src.workers.translation_worker
```

**Environment Variables**:
- `CONFIG_PATH`: Path to global config (default: `config/global.yaml`)
- `SITE_PROFILES_DIR`: Site profiles directory (default: `config/site_profiles`)
- `TM_PATH`: Translation memory path (default: `data/tm`)
- `WORKER_ID`: Optional worker identifier

### Available Tools

#### translate_hugo_file

Translate a single Hugo markdown file to target languages.

**Input Schema**:
```json
{
  "type": "object",
  "properties": {
    "site_id": {
      "type": "string",
      "description": "Site profile ID (e.g., 'products.aspose.net')"
    },
    "file_path": {
      "type": "string",
      "description": "Path to Hugo markdown file"
    },
    "target_langs": {
      "type": "array",
      "items": {"type": "string"},
      "description": "Target language codes (e.g., ['fr', 'de'])"
    }
  },
  "required": ["site_id", "file_path", "target_langs"]
}
```

**Output**: TranslationResult as JSON
```json
{
  "status": "success",
  "file_path": "/path/to/file.md",
  "target_langs": ["fr", "de"],
  "result": {
    "success": true,
    "outputs": {
      "fr": "/path/to/file.fr.md",
      "de": "/path/to/file.de.md"
    },
    "stats": {...},
    "errors": []
  }
}
```

**Usage Examples**:

Translate a product FAQ to French and German:
```json
{
  "site_id": "products.aspose.net",
  "file_path": "samples/products.aspose.net/en/faq-product-catalog-overview.md",
  "target_langs": ["fr", "de"]
}
```

Translate a documentation file to multiple languages:
```json
{
  "site_id": "docs.aspose.net",
  "file_path": "content/docs/getting-started.md",
  "target_langs": ["es", "it", "pt", "ru"]
}
```

#### translate_directory

Translate all Hugo markdown files in a directory.

**Input Schema**:
```json
{
  "type": "object",
  "properties": {
    "site_id": {
      "type": "string",
      "description": "Site profile ID"
    },
    "directory_path": {
      "type": "string",
      "description": "Path to directory containing markdown files"
    },
    "target_langs": {
      "type": "array",
      "items": {"type": "string"},
      "description": "Target language codes"
    },
    "recursive": {
      "type": "boolean",
      "description": "Process subdirectories recursively",
      "default": true
    }
  },
  "required": ["site_id", "directory_path", "target_langs"]
}
```

**Output**: DirectoryResult as JSON
```json
{
  "status": "success",
  "directory_path": "/path/to/content",
  "result": {
    "success": true,
    "total_files": 10,
    "successful_files": 9,
    "failed_files": 1,
    "aggregate_stats": {...}
  }
}
```

**Usage Examples**:

Translate all product documentation to Spanish:
```json
{
  "site_id": "products.aspose.net",
  "directory_path": "samples/products.aspose.net/en",
  "target_langs": ["es"],
  "recursive": true
}
```

Translate a blog content directory to multiple languages:
```json
{
  "site_id": "blog.aspose.net",
  "directory_path": "content/blog/posts",
  "target_langs": ["fr", "de", "it"],
  "recursive": false
}
```

#### tm_exact_lookup

Look up exact translation from Translation Memory.

**Input Schema**:
```json
{
  "type": "object",
  "properties": {
    "site_id": {"type": "string"},
    "source_text": {"type": "string"},
    "source_lang": {"type": "string"},
    "target_lang": {"type": "string"}
  },
  "required": ["site_id", "source_text", "source_lang", "target_lang"]
}
```

**Output**:
```json
{
  "status": "found|not_found",
  "source_text": "Hello World",
  "target_text": "Bonjour le monde",  // Only if found
  "source": "l2_exact|l3_semantic"     // TM layer that provided result
}
```

**Usage Examples**:

Look up an exact translation for a common phrase:
```json
{
  "site_id": "products.aspose.net",
  "source_text": "Product Catalog",
  "source_lang": "en",
  "target_lang": "fr"
}
```

Check if a technical term has been translated before:
```json
{
  "site_id": "docs.aspose.net",
  "source_text": "Application Programming Interface",
  "source_lang": "en",
  "target_lang": "de"
}
```

#### tm_semantic_lookup

Find similar translations using semantic search.

**Input Schema**:
```json
{
  "type": "object",
  "properties": {
    "site_id": {"type": "string"},
    "source_text": {"type": "string"},
    "source_lang": {"type": "string"},
    "target_lang": {"type": "string"},
    "k": {
      "type": "integer",
      "description": "Number of results to return",
      "default": 5
    }
  },
  "required": ["site_id", "source_text", "source_lang", "target_lang"]
}
```

**Output**:
```json
{
  "status": "success",
  "source_text": "Hello everyone",
  "candidates": [
    {
      "target_text": "Bonjour tout le monde",
      "similarity": 0.92,
      "source": "l3_semantic"
    }
  ]
}
```

**Usage Examples**:

Find similar translations for a greeting:
```json
{
  "site_id": "blog.aspose.net",
  "source_text": "Welcome to our blog",
  "source_lang": "en",
  "target_lang": "es",
  "k": 3
}
```

Get semantic matches for a technical description:
```json
{
  "site_id": "docs.aspose.net",
  "source_text": "Convert documents to PDF format",
  "source_lang": "en",
  "target_lang": "fr",
  "k": 5
}
```

#### health_check

Check worker health and status.

**Input Schema**: `{}` (empty object)

**Output**:
```json
{
  "status": "healthy|initializing",
  "worker_id": "worker-12345",
  "initialized": true,
  "running": true,
  "tm_status": "connected",
  "model_loaded": true
}
```

**Usage Example**:

Check worker health before submitting translation jobs:
```json
{}
```

#### get_stats

Get worker statistics and metrics.

**Input Schema**: `{}` (empty object)

**Output**:
```json
{
  "worker_id": "worker-12345",
  "initialized": true,
  "tm_stats": {...},
  "loaded_models": ["m2m100_418m"],
  "metrics": {...}
}
```

**Usage Example**:

Get detailed worker statistics and performance metrics:
```json
{}
```

## Python API

### TranslationEngine

**Location**: `src/translation_engine/engine.py`

#### translate_file(site_id, file_path, target_langs, **kwargs)

Translate a single Hugo markdown file.

**Parameters**:
- `site_id` (str): Site profile identifier
- `file_path` (Path): Path to source markdown file
- `target_langs` (List[str]): Target language codes
- `force` (bool): Bypass TM lookup (default: False)
- `validate` (bool): Enable validation (default: engine setting)

**Returns**: `TranslationResult`

**Example**:
```python
from pathlib import Path
from src.translation_engine.engine import TranslationEngine

engine = TranslationEngine(config_service, tm, model_loader)
result = engine.translate_file(
    site_id="myblog",
    file_path=Path("content/post.md"),
    target_langs=["fr", "es"]
)

if result.success:
    print(f"Translated to: {list(result.outputs.keys())}")
else:
    print(f"Errors: {result.errors}")
```

#### translate_directory(site_id, directory, target_langs, **kwargs)

Translate all markdown files in a directory.

**Parameters**:
- `site_id` (str): Site profile identifier
- `directory` (Path): Directory containing markdown files
- `target_langs` (List[str]): Target language codes
- `recursive` (bool): Process subdirectories (default: True)
- `parallel` (bool): Enable parallel processing (default: True)
- `max_workers` (int): Maximum parallel workers (default: auto)

**Returns**: `DirectoryResult`

**Example**:
```python
result = engine.translate_directory(
    site_id="myblog",
    directory=Path("content/posts"),
    target_langs=["fr", "de"],
    recursive=True,
    parallel=True
)

print(f"Processed {result.successful_files}/{result.total_files} files")
```

#### extract_segments(site_id, file_path)

Extract translatable segments without translating.

**Parameters**:
- `site_id` (str): Site profile identifier
- `file_path` (Path): Path to markdown file

**Returns**: `List[Segment]`

**Example**:
```python
segments = engine.extract_segments("myblog", Path("content/post.md"))
for segment in segments:
    print(f"Segment: {segment.source_text[:50]}...")
```

### TranslationMemory

**Location**: `src/tm/translation_memory.py`

#### lookup(site_id, src_lang, tgt_lang, text, **kwargs)

Look up translation in TM (all layers).

**Parameters**:
- `site_id` (str): Site identifier
- `src_lang` (str): Source language code
- `tgt_lang` (str): Target language code
- `text` (str): Source text to look up

**Returns**: `LookupResult`

#### store(site_id, src_lang, tgt_lang, text, translation, **kwargs)

Store translation in TM.

**Parameters**:
- `site_id` (str): Site identifier
- `src_lang` (str): Source language code
- `tgt_lang` (str): Target language code
- `text` (str): Source text
- `translation` (str): Translated text

### ConfigService

**Location**: `src/utils/config_loader.py`

#### get_site_profile(site_id)

Load site profile configuration.

**Parameters**:
- `site_id` (str): Site profile identifier

**Returns**: `SiteProfile`

#### list_sites()

List all available site profiles.

**Returns**: `List[str]`

## Data Models

### TranslationResult

**Location**: `src/translation_engine/models.py`

```python
@dataclass
class TranslationResult:
    success: bool
    file_path: Path
    outputs: Dict[str, Path]  # lang -> output_path
    stats: TranslationStats
    errors: List[str]
    warnings: List[str]
    validation_result: Optional[ValidationResult]
    validation_decision: Optional[ValidationDecision]
    decision_reason: Optional[str]
    retry_attempts: int
    retry_history: List[Dict[str, Any]]
    verification_result: Optional[Any]  # VA-03
```

### DirectoryResult

```python
@dataclass
class DirectoryResult:
    success: bool
    directory: Path
    file_results: List[TranslationResult]
    total_files: int
    successful_files: int
    failed_files: int
    duration_seconds: float

    @property
    def aggregate_stats(self) -> TranslationStats:
        # Aggregated statistics across all files
```

### ValidationResult

```python
@dataclass
class ValidationResult:
    valid: bool
    issues: List[ValidationIssue]

    @property
    def errors(self) -> List[ValidationIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> List[ValidationIssue]:
        return [i for i in self.issues if i.severity == "warning"]
```

## Error Handling

All APIs follow consistent error handling:

- **Validation errors**: Return results with `success=False` and populated `errors` list
- **System errors**: Raise appropriate exceptions (`TranslationRejectedError`, `TranslationRetryableError`)
- **MCP errors**: Return error messages in tool response text

## Authentication

Currently, the MCP server does not implement authentication. Access control should be handled at the infrastructure level (networking, containers).

## Rate Limiting

No built-in rate limiting. Implement at the client or infrastructure level for production deployments.

## Monitoring

MCP workers expose metrics via the `get_stats` tool and integrate with the telemetry system for distributed tracing.
