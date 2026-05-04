# AI Translator Agent (ID 170)

## Metadata
- **GitLab path:** santiago-doconut/ai-translator-agent
- **Web URL:** https://gitlab.recruitize.ai/santiago-doconut/ai-translator-agent
- **Repository URL:** https://gitlab.recruitize.ai/santiago-doconut/ai-translator-agent.git
- **Default branch:** master
- **Inspected commit:** 8f93ae312053bd6e0e3b6b0d2266ad6756500fcf
- **Last activity:** 2025-12-23
- **Language/runtime:** C# .NET (Clean Architecture)
- **Inspection status:** Complete
- **Confidence:** High

## Purpose
A multi-format translation agent with clean architecture (Domain/Application/Infrastructure/Tests). Translates .md, .resx, and .json files. Features SHA256 dual-hash file-level caching, Markdown healing (validation), AI translation review, progress tracking, and review caching. Supports multiple AI clients: OpenAI, Ollama, DeepSeek, Gemini, Professionalize.

## Evidence Summary
- `AITranslator.Application/Orchestration/Strategies/MarkdownContentTranslator.cs` -- Markdown translation strategy with review, caching, progress tracking
- `AITranslator.Infrastructure/Services/FileTranslators/BaseCachingTranslator.cs` -- SHA256 dual-hash file-level caching (source text + language)
- `AITranslator.Application/Orchestration/Strategies/JsonContentTranslator.cs` -- JSON translation
- `AITranslator.Application/Orchestration/Strategies/ResxContentTranslator.cs` -- RESX translation
- `AITranslator.Application/Orchestration/ProjectTranslationOrchestrator.cs` -- Multi-project orchestrator
- `AITranslator.Application/Validation/MarkdownHealer.cs` -- Markdown healing/validation
- `AITranslator.Application/Translation/Reviewers/AiTranslationReviewer.cs` -- AI-based translation review
- `AITranslator.Infrastructure/Services/ProgressTrackerService.cs` -- Progress tracking
- `AITranslator.Infrastructure/Services/ReviewCacheService.cs` -- Review result caching with verification status
- `AITranslator.Application/Translation/PromptBuilders/TranslationPromptBuilder.cs` -- Prompt construction
- `AITranslator.Application/Translation/PromptBuilders/PromptSafetyRules.md` -- Safety rules for prompts
- `AITranslator.Infrastructure/AIClients/` -- 5 AI clients: OpenAI, Ollama, DeepSeek, Gemini, Professionalize
- Test suite: ProjectTranslationOrchestratorTests, JsonContentTranslatorTests, JsonSegmentationTests, PromptBuilderTests, JsonHealerTests, MarkdownHealerTests

## Architecture
| Area | Finding | Evidence |
|------|---------|----------|
| Entrypoint(s) | `AITranslator.Agent/Program.cs` (console app with DI) | Program.cs |
| Key modules | ProjectTranslationOrchestrator, MarkdownContentTranslator, BaseCachingTranslator, AiTranslationReviewer | Application/Orchestration/, Infrastructure/Services/ |
| Config | `appsettings.json` with site configs, AI provider settings | appsettings.json, SitesConfig.cs |
| Dependencies | .NET, Microsoft.Extensions.Hosting, HttpClientFactory | Various .csproj files |
| CI/CD | None | No CI files found |
| Tests | 6 test classes | AITranslator.Tests/ |
| Examples | README with NuGet packages, config examples | README.md |

## Translation Capabilities Checklist
| Capability | Status | Evidence | Notes |
|------------|--------|----------|-------|
| Markdown translation | Yes | MarkdownContentTranslator.cs:299-346 | Full Markdown file translation |
| Hugo content/frontmatter | Partial | MarkdownContentTranslator.cs | Translates .md files but no explicit Hugo frontmatter handling |
| Code block protection | No | -- | No explicit code block protection |
| Shortcode protection | No | -- | No shortcode handling |
| Placeholder protection | No | -- | No placeholder mechanism |
| HTML tag preservation | No | -- | No explicit HTML handling |
| YAML/frontmatter preservation | No | -- | No explicit YAML handling |
| AST or parser-based handling | No | -- | No AST parsing |
| Batch translation | Yes | MarkdownContentTranslator.cs:318-336 | Processes all files in source folder across all target languages |
| Translation memory/cache | Yes | BaseCachingTranslator.cs:375-406 | SHA256 dual-hash (text + language) file-level JSON cache |
| Glossary/terminology | No | -- | No glossary |
| Multilingual folder generation | Yes | MarkdownContentTranslator.cs | Writes to language-specific output folders |
| LLM-based translation | Yes | AIClients/: OpenAI, Ollama, DeepSeek, Gemini, Professionalize | 5 AI providers |
| MT model usage | No | -- | LLM only |
| Retry/backoff | No | -- | No retry logic |
| Progress logging | Yes | ProgressTrackerService.cs:320-321 | Per-file, per-language progress tracking |
| Validation/QA | Yes | MarkdownHealer.cs, AiTranslationReviewer.cs, ReviewCacheService.cs | Markdown healing + AI review + review caching |
| Resumability | Yes | BaseCachingTranslator.cs:375-379, ReviewCacheService.cs:344-346 | Cache check before translation; verification status tracking |
| Dry-run/safety mode | No | -- | No dry-run |

## Key Implementation Details
- **Clean Architecture**: Domain (interfaces, models), Application (orchestration, validation, prompts), Infrastructure (AI clients, caching, services), Tests. Proper DI with Microsoft.Extensions.Hosting.
- **SHA256 dual-hash caching**: BaseCachingTranslator combines `targetLanguage + "||" + inputText`, hashes with SHA256, stores as JSON file per language. Check cache before calling LLM.
- **Multi-format support**: ContentTranslatorFactory dispatches to MarkdownContentTranslator, JsonContentTranslator, or ResxContentTranslator based on file type.
- **AI translation review**: AiTranslationReviewer sends translated output for quality review via LLM.
- **Review caching**: ReviewCacheService stores verification status per file (`.verified.json`), tracks source changes via content hash comparison.
- **Master source verification**: Tracks source file changes to detect when retranslation is needed.
- **Prompt safety rules**: PromptSafetyRules.md embedded in prompt builder for safe translations.
- **5 AI providers**: OpenAI, Ollama, DeepSeek, Gemini, Professionalize -- all implementing BaseLanguageModelClient.
- **Progress tracking**: Per-site, per-language progress with file counts.

## Strengths
- Best clean architecture among all GitLab projects (proper DDD layers, DI, interfaces).
- SHA256 dual-hash caching provides reliable content-addressable cache.
- Multi-format support (.md, .resx, .json) with strategy pattern.
- AI translation review with review caching.
- Master source verification detects when retranslation is needed.
- 5 AI provider options with common base class.
- Test coverage for core orchestration and validation.
- Prompt safety rules are a thoughtful addition.

## Weaknesses and Gaps
- No Hugo-specific features (no frontmatter, shortcode, code block protection).
- No placeholder protection mechanism.
- No retry/backoff logic.
- No CI/CD pipeline.
- File-level caching (not segment-level like hugo-translator's TM).
- No formal glossary system.
- Markdown healing is limited compared to full validation suite.

## Relevance to hugo-translator
**Classification:** Highly relevant

The clean architecture pattern (Domain/Application/Infrastructure) is the most well-structured among GitLab projects. The SHA256 dual-hash caching, review caching with verification status, and master source verification are all patterns worth studying. The multi-provider AI client base class is a clean abstraction. The content-addressable cache approach is conceptually similar to hugo-translator's TM layers.

## Production Risk Notes
- No retry logic means API failures cause complete failure.
- File-level caching means any change to a file requires full retranslation.
- No rate limiting across providers.
- API keys in appsettings.json (should use secrets manager).

## Final Recommendation
**Study first** -- The clean architecture, SHA256 caching, review caching with verification status, and multi-provider abstraction are all worth reviewing. The master source verification pattern (detecting when retranslation is needed) is particularly valuable.
