# HugoDoc Translator (ID 150)

## Metadata
- **GitLab path:** gulou-cells/fengge/hugodoc-translator
- **Web URL:** https://gitlab.recruitize.ai/gulou-cells/fengge/hugodoc-translator
- **Repository URL:** https://gitlab.recruitize.ai/gulou-cells/fengge/hugodoc-translator.git
- **Default branch:** master
- **Inspected commit:** 30f18946f1c20e91d0bd47812c395f325c8e7dda
- **Last activity:** 2025-12-18
- **Language/runtime:** C# .NET
- **Inspection status:** Complete
- **Confidence:** High

## Purpose
A Hugo documentation translator with line-by-line Markdown parsing, keyword protection via numeric placeholders, and SQLite-based translation caching. Parses Markdown into chunk types (header, code, shortcode), replaces protected keywords with random numbers before translation, and caches translations for reuse.

## Evidence Summary
- `HugoDoc.Translator/MarkdownParser.cs` -- Line-by-line parser with chunk type detection (header, code, shortcode)
- `HugoDoc.Translator/KeywordProtector.cs` -- Replaces keywords from `keywords.txt` with numeric placeholders before translation
- `HugoDoc.Translator/TranslationService.cs` -- SQLite-based translation cache via `TranslationProxy` and `TranslationCache`
- `HugoDoc.Translator/TranslationValidator.cs` -- Translation validation
- `HugoDoc.Translator/MarkdownGenerator.cs` -- Reconstructs translated Markdown
- `HugoDoc.Translator/MarkdownNodeParser.cs` -- Node-level parsing
- `HugoDoc.Translator/FilePathResolver.cs` -- Multiple path resolution strategies
- `HugoDoc.Translator/Translator.cs` -- Main translator orchestration
- `HugoDoc.Translator/keywords.txt` -- Protected keywords list
- `HugoDoc.Translator/Prompts/system.txt` -- System prompt for LLM

## Architecture
| Area | Finding | Evidence |
|------|---------|----------|
| Entrypoint(s) | `Program.cs` | Program.cs |
| Key modules | MarkdownParser, KeywordProtector, TranslationService, MarkdownGenerator, Translator | HugoDoc.Translator/ |
| Config | `TranslatorConfig.cs`, `AppConfigs.cs` | TranslatorConfig.cs, AppConfigs.cs |
| Dependencies | .NET, Newtonsoft.Json, System.Data.SQLite | HugoDoc.Translator.csproj |
| CI/CD | None | No CI files found |
| Tests | None | No test files found |
| Examples | None | Default GitLab README |

## Translation Capabilities Checklist
| Capability | Status | Evidence | Notes |
|------------|--------|----------|-------|
| Markdown translation | Yes | Translator.cs, MarkdownParser.cs | Line-by-line parsing with chunk type awareness |
| Hugo content/frontmatter | Yes | MarkdownParser.cs:51-65 | Detects `---` header blocks, marks as non-translatable chunk |
| Code block protection | Yes | MarkdownParser.cs:67-77 | Detects ``` code blocks, marks as non-translatable chunk |
| Shortcode protection | Yes | MarkdownParser.cs:51 | Detects `{{<` shortcodes, marks as non-translatable chunk |
| Placeholder protection | Yes | KeywordProtector.cs:162-183 | Replaces keywords with random numeric placeholders |
| HTML tag preservation | No | -- | No explicit HTML handling |
| YAML/frontmatter preservation | Yes | MarkdownParser.cs:52-55 | Header chunk type preserves frontmatter |
| AST or parser-based handling | Partial | MarkdownParser.cs:30-81 | Line-by-line parsing with chunk type state machine (not full AST) |
| Batch translation | Yes | TranslationService.cs:103-106 | `TranslateBatch` method for batch processing |
| Translation memory/cache | Yes | TranslationService.cs:92-132 | SQLite-based cache with `TranslationProxy` (check cache before LLM) |
| Glossary/terminology | Yes | KeywordProtector.cs, keywords.txt | Keywords from file protected via numeric placeholder replacement |
| Multilingual folder generation | Yes | FilePathResolver.cs | Multiple path resolution strategies for output |
| LLM-based translation | Yes | TranslationService.cs:100-101, ILlmClient.cs | LLM client for translation |
| MT model usage | No | -- | LLM only |
| Retry/backoff | No | -- | No retry logic found |
| Progress logging | Partial | -- | Basic console output |
| Validation/QA | Yes | TranslationValidator.cs | Translation validation |
| Resumability | Yes | TranslationService.cs | SQLite cache enables resume (cached translations not re-translated) |
| Dry-run/safety mode | No | -- | No dry-run |

## Key Implementation Details
- **Line-by-line chunk parser**: MarkdownParser processes each line, tracking state (header, code, shortcode). Lines within non-translatable chunks are skipped. Uses `IsTranslatableChunkType()` and `IsTranslatableText()` to determine translatability.
- **Keyword protection**: KeywordProtector loads keywords from `keywords.txt`, replaces them with random numeric placeholders before translation, restores after. Maintains persistent keyword-to-number mappings in the cache.
- **SQLite translation cache**: TranslationProxy checks cache before calling LLM. Cache keyed by source text hash + language. Supports batch translation, keyword mapping storage, and cache management (delete by key/ID).
- **URL rewriting**: MarkdownParser.Clear() rewrites URLs to include language prefix (e.g., `/{product}/` → `/{product}/{lang}/`).
- **Multiple path resolution strategies**: FilePathResolver supports different output path patterns.

## Strengths
- SQLite-based translation cache is the most persistent caching mechanism among GitLab projects (comparable to hugo-translator's L2 LMDB).
- Keyword protection via numeric placeholders is a practical approach.
- Line-by-line chunk parser handles frontmatter, code blocks, and shortcodes.
- Cache enables resumability across runs.
- URL rewriting for language-specific paths.

## Weaknesses and Gaps
- No tests, no CI/CD.
- No retry logic.
- Line-by-line parsing is less robust than AST (can miss inline formatting).
- Default GitLab README (no project documentation).
- No multi-layer cache (single SQLite layer).
- Random numeric placeholders could collide with actual numbers in content.
- No formal validation suite beyond TranslationValidator.
- Static fields in TranslationService (not ideal for concurrency).

## Relevance to hugo-translator
**Classification:** Highly relevant

The SQLite-based translation cache is the most comparable caching approach to hugo-translator's L2 LMDB layer. The keyword protection via numeric placeholders is a simpler but effective alternative to hugo-translator's placeholder_manager. The line-by-line chunk parser's approach to detecting frontmatter, code blocks, and shortcodes is worth studying for comparison.

## Production Risk Notes
- Static fields in TranslationService prevent concurrent use.
- Random numeric placeholders could collide with actual content numbers.
- No error handling for SQLite failures.
- Relative path `../../../Cache` for cache directory is fragile.

## Final Recommendation
**Study first** -- The SQLite translation cache, keyword protection system, and line-by-line chunk parser are all worth reviewing. The caching approach is the most persistent among GitLab projects and directly comparable to hugo-translator's L2 layer.
