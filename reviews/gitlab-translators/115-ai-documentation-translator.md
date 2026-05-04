# AI Documentation Translator (ID 115)

## Metadata
- **GitLab path:** kraik/batumi-slides/maksim-churyumov/documentation-translator
- **Web URL:** https://gitlab.recruitize.ai/kraik/batumi-slides/maksim-churyumov/documentation-translator
- **Repository URL:** https://gitlab.recruitize.ai/kraik/batumi-slides/maksim-churyumov/documentation-translator.git
- **Default branch:** master
- **Inspected commit:** d78a10a99f28d4e927e617ba666fb68e6fdf3bf8
- **Last activity:** 2026-03-31
- **Language/runtime:** C# .NET 8 Web API
- **Inspection status:** Complete
- **Confidence:** High

## Purpose
A .NET 8 Web API service that automates translation of Hugo Markdown documentation stored in GitHub repositories. Downloads files within a specified commit range, translates them using AI (Llama), commits the results, and creates a pull request. Clean architecture with 4 projects: API, GitDocumentationTranslator (orchestrator), GitRepoManager (GitHub API via Octokit), and HugoMarkdownTranslator (parser + AI engine).

## Evidence Summary
- `DocumentationTranslator/HugoMarkdownTranslator/Services/HugoMarkdownTranslator.cs` -- Main translator: parse, translate body + YAML + code blocks, post-process, validate
- `DocumentationTranslator/HugoMarkdownTranslator/Services/MarkdownProcessor.cs` -- Regex-based extraction of YAML frontmatter and code blocks with GUID placeholders
- `DocumentationTranslator/HugoMarkdownTranslator/Services/MarkdownPostProcessor.cs` -- Post-processing: URL rewriting, YAML updates, Unicode cleanup
- `DocumentationTranslator/HugoMarkdownTranslator/Services/AITranslationEngine.cs` -- AI translation via Llama
- `DocumentationTranslator/HugoMarkdownTranslator/Services/TranslationValidator.cs` -- Validates YAML and code block preservation
- `DocumentationTranslator/GitRepoManager/Services/GitManager.cs` -- GitHub operations via Octokit (compare, download, branch, commit, PR, auto-merge)
- `DocumentationTranslator/GitDocumentationTranslator/Services/DocumentationTranslationCoordinator.cs` -- Orchestration
- `DocumentationTranslator/GitDocumentationTranslator/Services/TrackingChatClient.cs` -- AI usage tracking
- Test suite: HugoMarkdownTranslatorTests, MarkdownProcessorTests, MarkdownPostProcessorTests, AITranslationEngineTests, GitDocumentationTranslatorTests

## Architecture
| Area | Finding | Evidence |
|------|---------|----------|
| Entrypoint(s) | Web API endpoint via `InternalServicesController.cs` | Api/Controllers/InternalServicesController.cs |
| Key modules | HugoMarkdownTranslator, MarkdownProcessor, AITranslationEngine, GitManager | HugoMarkdownTranslator/Services/ |
| Config | `appsettings.json` with GitHub token, AI credentials, language config | Api/appsettings.DocumentationTranslator.json |
| Dependencies | .NET 8, Octokit (GitHub), AI client (Llama), System.Text.RegularExpressions | Various .csproj files |
| CI/CD | Designed for GitHub Actions integration | README:GitHub Action Script section |
| Tests | 5 test classes covering core components | GitDocumentationTranslator.Tests/ |
| Examples | AGENTS.md, README with request payload examples | README.md |

## Translation Capabilities Checklist
| Capability | Status | Evidence | Notes |
|------------|--------|----------|-------|
| Markdown translation | Yes | HugoMarkdownTranslator.cs:811 | Full Markdown body translation |
| Hugo content/frontmatter | Yes | HugoMarkdownTranslator.cs:813-814 | YAML parts extracted and translated individually |
| Code block protection | Yes | MarkdownProcessor.cs:841-870 | GUID placeholder extraction with regex, restored after translation |
| Shortcode protection | No | -- | No explicit shortcode handling |
| Placeholder protection | Yes | MarkdownProcessor.cs:865-870 | GUID-based placeholder system for YAML and code blocks |
| HTML tag preservation | No | -- | No explicit HTML handling |
| YAML/frontmatter preservation | Yes | MarkdownProcessor.cs:847, HugoMarkdownTranslator.cs:813-814 | Regex extraction, per-part translation, restoration |
| AST or parser-based handling | No | -- | Regex-based extraction with GUID placeholders |
| Batch translation | No | -- | File-by-file within commit range |
| Translation memory/cache | No | -- | No caching layer |
| Glossary/terminology | No | -- | No glossary |
| Multilingual folder generation | Yes | GitManager.cs | Creates branches, commits, and PRs for translated content |
| LLM-based translation | Yes | AITranslationEngine.cs | Llama-based AI translation |
| MT model usage | No | -- | LLM only (Llama) |
| Retry/backoff | No | -- | No explicit retry logic |
| Progress logging | Yes | HugoMarkdownTranslator.cs | Logging via ILogger |
| Validation/QA | Yes | TranslationValidator.cs, HugoMarkdownTranslator.cs:828-830 | Validates YAML parts and code blocks preserved correctly |
| Resumability | Partial | -- | Commit range-based: processes only files changed between two commits |
| Dry-run/safety mode | No | -- | No dry-run flag |

## Key Implementation Details
- **GUID placeholder system**: MarkdownProcessor extracts YAML frontmatter and code blocks using regex, replaces them with `{{GUID}}` placeholders, sends body to AI, then restores original blocks. Elegant and simple.
- **Commit-range processing**: Translates only files modified between two Git commits (compare via Octokit).
- **PR workflow**: Creates branch, commits translations, creates PR, optionally auto-merges.
- **Post-processing pipeline**: UpdateYaml (language segment in URL), UpdateLinks (link rewriting), CleanupUnicodeSymbols.
- **Validation**: After translation, validates that YAML parts and code blocks are preserved (compares counts/content).
- **AI usage tracking**: TrackingChatClient wraps AI calls for usage metrics.
- Designed as a microservice (Web API) that can be called by GitHub Actions or other systems.

## Strengths
- Clean .NET architecture with proper separation of concerns (4 projects).
- GUID placeholder system for code block and YAML protection is elegant.
- Post-processing pipeline (URL rewriting, YAML updates, Unicode cleanup) is well-structured.
- Validation of YAML and code block preservation after translation.
- PR-based workflow (not direct push) is safer.
- Test coverage for core components.
- Commit-range processing avoids unnecessary re-translation.
- AI usage tracking for cost monitoring.

## Weaknesses and Gaps
- No shortcode protection.
- No translation memory or caching.
- No retry/backoff for AI calls.
- No formal glossary system.
- LLM-only (Llama), no MT model fallback.
- No multi-validator suite (single TranslationValidator).
- No explicit rate limiting.

## Relevance to hugo-translator
**Classification:** Highly relevant

The GUID placeholder system for protecting YAML and code blocks during translation is a clean, simple approach. The post-processing pipeline (URL rewriting, YAML language segment injection, Unicode cleanup) addresses real Hugo-specific concerns. The commit-range processing pattern and PR-based output are worth studying. The validation of YAML/code block preservation is a focused validation approach.

## Production Risk Notes
- Web API requires hosting infrastructure.
- GitHub token stored in appsettings.json (should use secrets).
- No rate limiting on AI calls.
- Single AI provider (Llama) -- no fallback.

## Final Recommendation
**Study first** -- The GUID placeholder system, post-processing pipeline, and commit-range processing are well-engineered patterns. The clean .NET architecture and PR-based workflow represent best practices. Worth reviewing for placeholder protection and post-processing ideas.
