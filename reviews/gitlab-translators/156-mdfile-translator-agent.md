# MDFile Translator Agent (ID 156)

## Metadata
- **GitLab path:** bryansk-pdf/core/mdfile-translator-agent
- **Web URL:** https://gitlab.recruitize.ai/bryansk-pdf/core/mdfile-translator-agent
- **Repository URL:** https://gitlab.recruitize.ai/bryansk-pdf/core/mdfile-translator-agent.git
- **Default branch:** master
- **Inspected commit:** ecf4ec7074e1ea2a4b0c391b85f91fad441a8344
- **Last activity:** 2025-12-18
- **Language/runtime:** C# (Cake build system) + PowerShell
- **Inspection status:** Complete
- **Confidence:** High

## Purpose
A documentation Markdown AI translator agent built on the Cake build system. Translates .md files with code extraction before translation, SEO metadata preservation, quality review via AI, language-specific model selection, and multi-LLM support (Claude, Gemini, Gemma, Llama, OpenAI, YandexGPT). Parallel language translation with configurable models per language.

## Evidence Summary
- `build/MDTranslatorAgent.cs` -- Main translator: parallel language processing, code extraction, retry, quality review
- `build/LLMRequests/AIClient.cs` -- Multi-LLM client dispatch
- `build/LLMRequests/LLMClaudeRequest.cs` -- Claude provider
- `build/LLMRequests/LLMGeminiRequest.cs` -- Gemini provider
- `build/LLMRequests/LLMGemmaRequest.cs` -- Gemma provider
- `build/LLMRequests/LLMLlamaRequest.cs` -- Llama provider
- `build/LLMRequests/LLMOpenAIRequest.cs` -- OpenAI provider
- `build/LLMRequests/LLMYandexGPTRequest.cs` -- YandexGPT provider
- `build/Helpers/MDFileUpdater.cs` -- Markdown file processing, code extraction
- `build/Helpers/MDMetadataUpdater.cs` -- Metadata/frontmatter handling
- `build/Helpers/SEOScriptUpdater.cs` -- SEO script preservation
- `build/Configurations/AIMDTranslationConfig.cs` -- Config model
- `build/Configurations/LanguageInfo.cs` -- Per-language model config
- `configs/aiMDTranslationConfig.json` -- Translation configuration
- `.gitlab-ci.yml` -- GitLab CI pipeline

## Architecture
| Area | Finding | Evidence |
|------|---------|----------|
| Entrypoint(s) | `build/Program.cs` via Cake build system | Program.cs, build.ps1, build.sh |
| Key modules | MDTranslatorAgent, AIClient, MDFileUpdater, MDMetadataUpdater, SEOScriptUpdater | build/ |
| Config | `configs/aiMDTranslationConfig.json` with languages, models, prompts | AIMDTranslationConfig.cs |
| Dependencies | Cake build, multiple LLM SDKs | Build.csproj |
| CI/CD | GitLab CI pipeline | .gitlab-ci.yml |
| Tests | None | No test files found |
| Examples | README configuration guide | README.md |

## Translation Capabilities Checklist
| Capability | Status | Evidence | Notes |
|------------|--------|----------|-------|
| Markdown translation | Yes | MDTranslatorAgent.cs:222-252 | Full Markdown translation with parallel language processing |
| Hugo content/frontmatter | Yes | MDMetadataUpdater.cs | Metadata extraction and preservation |
| Code block protection | Yes | MDFileUpdater.cs, MDTranslatorAgent.cs:254-264 | Extracts code examples before translation, restores after |
| Shortcode protection | No | -- | No explicit shortcode handling |
| Placeholder protection | Yes | MDFileUpdater.cs | Extracts non-translatable phrases and wraps in placeholders |
| HTML tag preservation | Partial | SEOScriptUpdater.cs | SEO scripts wrapped in random comments for preservation |
| YAML/frontmatter preservation | Yes | MDMetadataUpdater.cs | Metadata fields selectively translated |
| AST or parser-based handling | No | -- | Regex-based extraction |
| Batch translation | No | -- | Single file, parallel languages |
| Translation memory/cache | No | -- | No caching |
| Glossary/terminology | Partial | MDFileUpdater.cs | Non-translatable phrases extracted and protected |
| Multilingual folder generation | Yes | MDTranslatorAgent.cs:258 | Output folder per language |
| LLM-based translation | Yes | AIClient.cs, 6 LLM providers | Claude, Gemini, Gemma, Llama, OpenAI, YandexGPT |
| MT model usage | No | -- | LLM only (multiple providers) |
| Retry/backoff | Yes | MDTranslatorAgent.cs:262-264 | `maxAttempts` with `attemptsTimeout` between retries |
| Progress logging | Yes | MDTranslatorAgent.cs:239,245 | Cake build logging with ANSI color codes |
| Validation/QA | Yes | MDTranslatorAgent.cs:209-211, ReviewSavingType | AI-based quality review, creates remarks file for discrepancies |
| Resumability | No | -- | No resume capability |
| Dry-run/safety mode | No | -- | No dry-run |

## Key Implementation Details
- **6 LLM providers**: Claude, Gemini, Gemma, Llama, OpenAI, YandexGPT -- each with its own request class. Language-specific model selection via config.
- **Parallel language processing**: Uses `Task.WhenAll` to translate all languages concurrently for a single file.
- **Code extraction pipeline**: MDFileUpdater extracts code examples and non-translatable phrases before translation, restores them after.
- **SEO script preservation**: Wraps SEO scripts in random HTML comments before translation, restores original after.
- **Quality review**: Sends original + translated content to AI for quality assessment. Creates a separate remarks file if issues found.
- **Retry with timeout**: Configurable `MaxAttemptsToTranslate` and `SecondsBetweenTranslationAttempts`.
- **ConcurrentDictionary** for thread-safe review storage during parallel processing.
- Cake build system (unusual choice for a translation agent).

## Strengths
- Most LLM provider options (6 providers) among all GitLab projects.
- Language-specific model selection allows optimizing per language.
- Parallel language processing for speed.
- Code extraction before translation prevents corruption.
- AI-based quality review with remarks file output.
- SEO script preservation is unique.
- Retry logic with configurable attempts and timeout.
- GitLab CI pipeline for automation.

## Weaknesses and Gaps
- No translation memory or caching.
- No tests.
- Cake build system adds complexity.
- No shortcode protection.
- No resumability across runs.
- No formal glossary (only extracted non-translatable phrases).
- SEO script wrapping with random comments is fragile.

## Relevance to hugo-translator
**Classification:** Partially relevant

The multi-LLM provider approach with language-specific model selection is the most interesting pattern. Hugo-translator's model registry already supports multiple providers, but the per-language model optimization idea is worth noting. The code extraction + quality review pipeline is well-structured. The SEO script preservation pattern is unique but fragile.

## Production Risk Notes
- API keys configured per model in config file (security concern).
- Parallel processing without rate limiting could hit API limits.
- SEO script wrapping with random comments could break if comment markers appear in content.
- Cake build system is uncommon for this use case.

## Final Recommendation
**Mine for one component** -- The multi-LLM provider architecture with per-language model selection is worth studying. The quality review pattern (translate + review with remarks file) is a simple but effective QA approach.
