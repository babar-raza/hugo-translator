# Blogs.BlogPostTranslator (ID 131)

## Metadata
- **GitLab path:** moscow-groupdocs-cloud/blogs-blogpost-translator
- **Web URL:** https://gitlab.recruitize.ai/moscow-groupdocs-cloud/blogs-blogpost-translator
- **Repository URL:** https://gitlab.recruitize.ai/moscow-groupdocs-cloud/blogs-blogpost-translator.git
- **Default branch:** master
- **Inspected commit:** 8b6ee2ba190871e20116e598f87df33f46d7ea14
- **Last activity:** 2026-01-10
- **Language/runtime:** C# .NET 8
- **Inspection status:** Complete
- **Confidence:** High

## Purpose
A console application for translating English blog posts to 18 target languages using AI. Two-stage pipeline: Translate then Correct. Sequential language processing with skip-if-exists logic. Uses shared `AIAgents.Common` library with GPT service proxied through professionalize.com.

## Evidence Summary
- `AI.Agents.Cloud.BlogPostTranslator/Translator.cs` -- Main translator: 18 hardcoded languages, sequential processing, skip-if-exists
- `AI.Agents.Cloud.BlogPostTranslator/Translate.cs` -- Translation stage
- `AI.Agents.Cloud.BlogPostTranslator/Correct.cs` -- Correction/review stage
- `AI.Agents.Cloud.BlogPostTranslator/Program.cs` -- CLI entry point
- `.gitmodules` -- References AIAgents.Common shared library

## Architecture
| Area | Finding | Evidence |
|------|---------|----------|
| Entrypoint(s) | `Program.cs` (CLI: `exe <file.md> <blog-id>`) | Program.cs |
| Key modules | Translator, Translate, Correct | Translator.cs, Translate.cs, Correct.cs |
| Config | CLI args + appsettings | README.md:438-441 |
| Dependencies | .NET 8, AIAgents.Common (git submodule), YamlDotNet v16.2.1 | .csproj, .gitmodules |
| CI/CD | None | No CI files found |
| Tests | None | No test files found |
| Examples | CLI usage in README | README.md:438-441 |

## Translation Capabilities Checklist
| Capability | Status | Evidence | Notes |
|------------|--------|----------|-------|
| Markdown translation | Yes | Translate.cs | Full content translation via LLM |
| Hugo content/frontmatter | Yes | Translator.cs | YamlDotNet for frontmatter handling |
| Code block protection | No | -- | No explicit code block protection |
| Shortcode protection | No | -- | No shortcode handling |
| Placeholder protection | No | -- | No placeholder mechanism |
| HTML tag preservation | No | -- | No explicit HTML preservation |
| YAML/frontmatter preservation | Yes | Translator.cs | YamlDotNet parsing |
| AST or parser-based handling | No | -- | No AST parsing |
| Batch translation | No | -- | Single file, sequential languages |
| Translation memory/cache | No | -- | No caching |
| Glossary/terminology | No | -- | No glossary |
| Multilingual folder generation | Yes | Translator.cs | Generates translated files per language |
| LLM-based translation | Yes | Translate.cs, AIAgents.Common | GPT via professionalize.com proxy |
| MT model usage | No | -- | LLM only |
| Retry/backoff | No | -- | No retry logic |
| Progress logging | Yes | Translator.cs | Console logging |
| Validation/QA | Partial | Correct.cs | Two-stage: translate then correct via separate LLM call |
| Resumability | Partial | Translator.cs | Skip if target file already exists |
| Dry-run/safety mode | No | -- | No dry-run |

## Key Implementation Details
- **Two-stage pipeline**: First translates, then sends to a separate LLM call for correction/quality review.
- 18 hardcoded target languages in an array.
- Sequential language processing (one language at a time).
- Skip-if-exists logic: checks if target file already exists, skips translation.
- Uses `AIAgents.Common` shared library (git submodule) with `GptService.LlmProxy` for professionalize.com.
- YamlDotNet for frontmatter parsing.
- Simple CLI: `exe <en_file_path.md> <blog-post-id>`.

## Strengths
- Two-stage translate+correct pipeline is a simple but effective quality measure.
- Skip-if-exists prevents redundant work.
- Shared `AIAgents.Common` library promotes code reuse across projects.
- YamlDotNet for proper YAML parsing (not regex).

## Weaknesses and Gaps
- No code block, shortcode, or placeholder protection.
- No translation memory or caching.
- No tests, no CI/CD.
- Hardcoded language list.
- Sequential processing (slow for many languages).
- No retry logic.
- Minimal error handling.

## Relevance to hugo-translator
**Classification:** Low relevance

The two-stage translate+correct pattern is a simple quality idea, but hugo-translator's 10-validator suite and retranslation queue are far more sophisticated. The `AIAgents.Common` shared library pattern is interesting for organizational code reuse but not directly applicable.

## Production Risk Notes
- No error handling for API failures.
- Sequential processing is slow.
- Git submodule dependency on AIAgents.Common.
- No CI/CD pipeline.

## Final Recommendation
**Study later** -- The two-stage translate+correct pattern is a minor idea worth noting. The implementation is too basic to offer significant value beyond that concept.
