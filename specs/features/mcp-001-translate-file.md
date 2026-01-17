# MCP-001: translate_hugo_file Tool

**Feature:** MCP tool for single file translation
**Status:** 🔍 EVIDENCE_ONLY
**Last Updated:** 2025-12-26

---

## Summary

MCP (Model Context Protocol) tool exposed by translation worker for translating single Hugo markdown files. Enables distributed translation via MCP client-server communication.

---

## Entry Points

**MCP Tool Name:** `translate_hugo_file`

**Registration Site:**
- File: `src/workers/translation_worker.py`
- Lines: 186-211 (tool registration)
- Lines: 299-305 (tool call handler)
- Lines: 351-390 (implementation)

**Handler Symbol:** `TranslationWorker._translate_file()`

---

## Inputs/Outputs

### Input Schema

```json
{
  "type": "object",
  "properties": {
    "site_id": {
      "type": "string",
      "description": "Site profile ID (e.g., 'products.aspose.org')"
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

**Evidence:** Lines 190-211 in `src/workers/translation_worker.py`

### Output Format

**Success Response:**
```json
{
  "status": "success",
  "file_path": "/path/to/file.md",
  "target_langs": ["fr", "de"],
  "result": {
    "success": true,
    "outputs": {
      "fr": "/output/fr/file.md",
      "de": "/output/de/file.md"
    },
    "stats": {
      "total_segments": 50,
      "tm_hits": 35,
      "translated_segments": 15,
      "duration_seconds": 5.2
    }
  }
}
```

**Error Response:**
```json
{
  "status": "error",
  "file_path": "/path/to/file.md",
  "error": "TranslationRejectedError: Critical validation failures..."
}
```

**Return Type:** `List[TextContent]` (MCP protocol)
- Single element: `TextContent(type="text", text=str(result))`
- Evidence: Line 305 return statement

---

## Invariants

### Must (Critical)

1. **Worker initialization before execution:**
   - MUST call `self.setup()` if worker not initialized
   - Evidence: Lines 295-296
   ```python
   if not self._initialized:
       await self.setup()
   ```

2. **Metrics tracking:**
   - MUST increment `translations.files.started` on entry
   - MUST increment either `.completed` or `.failed` on exit
   - Evidence: Lines 362, 372, 383

3. **Error encapsulation:**
   - ALL exceptions MUST be caught and returned as error text (not raised)
   - Evidence: Lines 346-349 (global exception handler)
   ```python
   except Exception as e:
       error_msg = f"Error executing {name}: {str(e)}"
       logger.error(error_msg, exc_info=True)
       return [TextContent(type="text", text=error_msg)]
   ```

4. **TranslationEngine delegation:**
   - MUST call `self.engine.translate_file()` with same parameters
   - Evidence: Lines 365-369

### Should (Important)

5. **Logging:**
   - SHOULD log file path and site ID on entry
   - SHOULD log errors with full stack trace
   - Evidence: Lines 358, 385

6. **Result serialization:**
   - SHOULD serialize result using `.to_dict()` if available
   - Evidence: Line 378

### Never (Prohibited)

7. **NEVER expose internal exceptions:**
   - MCP clients should receive structured error text, not exception traces
   - Sensitive paths/data should be sanitized

---

## Errors and Edge Cases

### Error Handling

**Caught Exceptions:**
- `TranslationRejectedError` - Validation rejection
- `TranslationRetryableError` - Validation retry exhausted
- `ValueError` - Invalid site_id or parameters
- `Exception` - All other errors

**Error Flow:**
```
Tool invocation
  → _translate_file()
      → engine.translate_file()
          [Exception raised]
      ← Caught in try/except
      ← Metrics .failed incremented
      ← Returns {status: "error", error: "..."}
  ← MCP client receives error as text content
```

**Evidence:** Lines 381-390

### Edge Cases

**Worker not initialized:**
- Behavior: Auto-initialize on first tool call
- Evidence: Lines 295-296

**Empty target_langs:**
- Behavior: Passes to engine, likely returns empty result
- No explicit validation at MCP layer

**File path with spaces:**
- Behavior: Should work (JSON string escaping)
- Risk: Ensure proper path handling on worker filesystem

**Concurrent requests:**
- Behavior: Multiple files can be translated concurrently
- Limit: Depends on worker configuration (single-threaded vs multi-threaded)

---

## Config and Environment

### Worker Configuration

**Environment Variables:**
```bash
WORKER_ID=worker-123               # Unique worker identifier
CONFIG_PATH=/app/config            # Config directory
TM_PATH=/data/tm                   # Translation Memory path
WORKER_MODE=mcp                    # Enable MCP server mode
```

**Evidence:** `src/workers/translation_worker.py` lines 560-565

### Site Profile

Worker loads site profiles from `config/site_profiles/{site_id}.yaml`:
```yaml
site_id: products.aspose.net
content_roots: [...]
target_langs: [...]
output_dir: /output
```

---

## Side Effects

### File System

**Reads:**
- `config/site_profiles/{site_id}.yaml`
- Input markdown file at `file_path`
- TM data (`data/tm/l2_lmdb/`, `data/tm/l3_faiss/`)

**Writes:**
- Output files: `{output_dir}/{lang}/{filename}`
- TM updates: L1/L2/L3 caches
- Worker logs: Depends on logging configuration

### Translation Memory

**L1 (in-memory):**
- Updated per worker instance
- Shared: No (per-worker cache)

**L2 (LMDB persistent):**
- Updated on disk
- Shared: Yes (multiple workers access same LMDB)
- Concurrency: LMDB handles concurrent writes

**L3 (FAISS semantic):**
- Updated in memory
- Saved on worker shutdown
- Shared: Index file shared, but in-memory state per worker

### Metrics

**Incremented Counters:**
- `translations.files.started` (always)
- `translations.files.completed` (on success)
- `translations.files.failed` (on error)

**Evidence:** Lines 362, 372, 383

**Aggregation:** Worker metrics can be queried via `get_stats` tool

### Network

**MCP Communication:**
- Input: JSON-RPC request over stdio
- Output: JSON-RPC response with TextContent
- Protocol: MCP v0.9.0+

---

## Evidence

### Code Locations

| Component | File | Lines | Symbol |
|-----------|------|-------|--------|
| Tool registration | src/workers/translation_worker.py | 186-211 | list_tools() |
| Tool handler | src/workers/translation_worker.py | 292-349 | call_tool() |
| Implementation | src/workers/translation_worker.py | 351-390 | _translate_file() |
| Worker setup | src/workers/translation_worker.py | 83-158 | setup() |
| Worker initialization | src/workers/translation_worker.py | 44-81 | __init__() |

### MCP Integration

| Aspect | Evidence | Location |
|--------|----------|----------|
| Server creation | `Server("translation-worker")` | Line 74 |
| Tool registration decorator | `@self.mcp_server.list_tools()` | Line 186 |
| Tool call decorator | `@self.mcp_server.call_tool()` | Line 292 |
| stdio transport | `stdio_server()` context manager | Line 543 |

### Test Evidence

**Existing Tests:**
- MCP integration tests likely in `tests/integration/test_mcp_*.py` (not yet verified)

**Missing Contract Tests:**
- Tool schema validation
- Error response format
- Metrics tracking verification
- Concurrent request handling

---

## Verification Status

🔍 **EVIDENCE_ONLY**

**Verification Steps Required:**

1. **Create contract test:** `tests/contract/test_mcp_translate_file.py`
2. **Test invariants:**
   - Worker auto-initialization
   - Metrics increment on all paths
   - Error encapsulation (no raw exceptions)
   - TranslationEngine delegation
3. **Test MCP protocol:**
   - Input schema validation
   - Output format consistency
   - Error response format
4. **Test edge cases:**
   - Empty target_langs
   - Invalid site_id
   - Concurrent requests
   - Worker shutdown during execution
5. **Link to spec:** Add docstring reference

**Blockers:** None

---

## Related Specs

- [API-001: translate_file Method](api-001-translate-file.md) - Underlying implementation

<!-- NOTE: References to MCP-005, MCP-006, and SVC-002 removed 2026-01-15
     These were planned specs that were never implemented. References removed to
     eliminate broken links. See reports/agents/agent_d/wi002_wi003_docs/run_20260115_231500/ -->
