# Blog Post Translator Lahore (ID 010)

## Metadata
- **GitLab path:** sialkot/lahore-aspose/lahore-blogs-team/blog-post-translator
- **Web URL:** https://gitlab.recruitize.ai/sialkot/lahore-aspose/lahore-blogs-team/blog-post-translator
- **Repository URL:** https://gitlab.recruitize.ai/sialkot/lahore-aspose/lahore-blogs-team/blog-post-translator.git
- **Default branch:** master
- **Inspected commit:** bff7b80d97b13c795e4d3e1eff9c735aa4ce9c59
- **Last activity:** 2026-03-31
- **Language/runtime:** Python 3.13
- **Inspection status:** Complete
- **Confidence:** High

## Purpose
A comprehensive multi-domain blog translation system with scanning, translation, quality validation, and retranslation capabilities. Covers 6 blog domains (Aspose, GroupDocs, Conholdate -- .com and .cloud) with 22 target languages, Google Sheets reporting, and GitHub Actions CI/CD. Also includes a quality agent pipeline (scanner, validator, retranslator) using OpenAI Agents SDK.

## Evidence Summary
- `tools/translation_agent/translator.py` -- Main translation orchestrator (~700+ lines)
- `tools/translation_agent/config.py` -- Domain/language/product configuration
- `tools/translation_agent/scan_missing_translations.py` -- Missing translations scanner
- `tools/translation_agent/io_google_spreadsheet.py` -- Google Sheets integration
- `tools/translation_agent/utils.py` -- Metrics reporting
- `tools/translation_agent/git_repo_utils.py` -- Git clone/pull helper
- `tools/translation_agent/translation_files_managers.py` -- Deletion of invalid translation files
- `tools/quality_agent/quality_scanner.py` -- Heuristic quality scanning
- `tools/quality_agent/quality_validator.py` -- LLM-based quality validation
- `tools/quality_agent/quality_retranslator.py` -- Automated retranslation of poor-quality files
- `tools/quality_agent/lang_guard.py` -- Language validation utilities
- `.github/workflows/translate-blogs.yml` -- Translation workflow
- `.github/workflows/scan-missing-translations.yml` -- Daily scan workflow

## Architecture
| Area | Finding | Evidence |
|------|---------|----------|
| Entrypoint(s) | `translator.py` (translation), `scan_missing_translations.py` (scanning) | translator.py:1, scan_missing_translations.py:449 |
| Key modules | FrontmatterTranslatorAgent, ContentTranslatorAgent, TranslationOrchestrator | translator.py:298-432 |
| Config | Hardcoded domain/language config in config.py | config.py:1-469 |
| Dependencies | openai, openai-agents, pyyaml, gspread, gitpython, openpyxl | requirements.txt:1-10 |
| CI/CD | 8 GitHub Actions workflows (daily scan + per-domain translation + manual dispatch) | .github/workflows/translate-blogs.yml, scan-missing-translations.yml |
| Tests | none | No test files found |
| Examples | none | Usage documented in readme.md |

## Translation Capabilities Checklist
| Capability | Status | Evidence | Notes |
|------------|--------|----------|-------|
| Markdown translation | Yes | translator.py:454-499 | Paragraph-by-paragraph chunking with code block awareness |
| Hugo content/frontmatter | Yes | translator.py:298-430 | FrontmatterTranslatorAgent handles title, seoTitle, description, summary, cover.alt/caption, steps, faqs |
| Code block protection | Yes | translator.py:478-497 | Code blocks detected by ``` markers, combined across paragraphs, not sent for translation |
| Shortcode protection | Partial | lang_guard.py:141-147 | should_skip_validation skips `{{< >}}` shortcodes in quality checks, but translator does not explicitly protect them |
| Placeholder protection | No | - | No placeholder protection mechanism |
| HTML tag preservation | No | - | No explicit HTML preservation |
| YAML/frontmatter preservation | Yes | translator.py:214-243 | parse_markdown_file parses YAML frontmatter; write_markdown_file reconstructs it |
| AST or parser-based handling | No | - | Regex-based paragraph splitting, no AST parsing |
| Batch translation | Partial | translator.py:454-499 | Translates paragraph-by-paragraph, not true batching of multiple files |
| Translation memory/cache | No | - | No caching layer |
| Glossary/terminology | Partial | translator.py:396-401 | Product name examples in prompt (Aspose.PDF, GroupDocs.Comparison etc.), not a formal glossary |
| Multilingual folder generation | Yes | translator.py:278-291 | Generates index.{lang}.md files in same directory |
| LLM-based translation | Yes | translator.py:79-118 | Uses OpenAI-compatible API (professionalize.com) |
| MT model usage | No | - | LLM only, no machine translation models |
| Retry/backoff | Partial | scan_missing_translations.py:249-266 | Retry for Google Sheets writes with random delay; no explicit retry for translation API calls |
| Progress logging | Yes | translator.py:466-476 | Per-paragraph progress with token usage tracking |
| Validation/QA | Yes | quality_scanner.py:209-252, quality_validator.py:279-341 | 3-phase quality pipeline: heuristic scan, LLM validation, retranslation |
| Resumability | Partial | - | Skips already-translated files by checking existence on disk |
| Dry-run/safety mode | No | - | No dry-run flag |

## Key Implementation Details
- Uses Professionalize LLM (llm.professionalize.com/v1) with model "gpt-oss" for translation.
- Token tracking via TokenTracker dataclass records prompt/completion/total tokens per LLM call.
- Quality agent uses OpenAI Agents SDK (function_tool decorator) to wrap scanning/validation/retranslation as agent tools.
- Heuristic quality check compares original vs translated paragraph text (word-set diff), flagging untranslated content.
- LLM quality validation sends sampled paragraphs to a secondary LLM call asking for SCORE/UNTRANSLATED structured response.
- Google Sheets integration reports missing translations and quality scores per domain.
- Metrics are sent to a Google Apps Script endpoint for agent tracking.

## Strengths
- Most comprehensive project in this batch: covers scanning, translation, quality validation, and retranslation.
- 3-phase quality pipeline (heuristic scan -> LLM validation -> retranslation) is well-designed.
- Detailed token usage tracking per LLM call.
- GitHub Actions workflows cover all 6 blog domains with both scheduled and manual triggers.
- Google Sheets reporting provides visibility into translation status.
- Language guard module (lang_guard.py) provides reusable utilities for language validation and translation quality heuristics.

## Weaknesses and Gaps
- No tests at all.
- API key exposed in config.py (`METRICS_TOKEN` at line 436) -- not a translation API key but still a credential in source.
- Hardcoded local Mac paths in git_repo_utils.py (line 7: `/Users/Apple/Work/Aspose/keys/github/pat.txt`, lines 14-45).
- Translation files manager (`translation_files_managers.py`) includes a `delete_translation_files` function that deletes files based on language code -- risky for production content repos.
- No explicit shortcode protection in the translator itself (only quality agent skips them).
- No retry logic for translation API calls; only Google Sheets writes have retry.
- Paragraph-by-paragraph translation loses cross-paragraph context.
- No formal glossary system beyond product name examples in prompts.
- PRODUCTION_ENV flag (config.py:8) defaults to False -- metrics and production writes are conditional on this.

## Relevance to hugo-translator
**Classification:** Partially relevant

The quality agent pipeline (quality_scanner.py, quality_validator.py, quality_retranslator.py, lang_guard.py) is well-structured and could inform quality validation approaches. The 3-phase scan-validate-retranslate pattern is similar to what hugo-translator already implements. The lang_guard.py `appears_translated()` heuristic and `should_skip_validation()` logic are worth studying. The translation agent itself is simpler than hugo-translator's engine and does not offer AST-based parsing, TM layers, or MT model support. The Google Sheets reporting pattern could be useful for external visibility, though hugo-translator already has its own reporting.

## Production Risk Notes
- Hardcoded local paths in git_repo_utils.py would fail in CI unless overridden.
- Google Sheets credential file path (`utils/gsheetapi-missing-translations-sk.json`) is a local fallback path.
- `translation_files_managers.py` has a destructive `delete_translation_files()` function.
- No input validation on CLI args for domain/product names beyond basic existence checks.
- Auto-commit workflow pushes directly to default branch (master/main) without PR review.
- No rate limiting or backoff for LLM API calls.

## Final Recommendation
**Study first** -- The quality agent pipeline (scanner/validator/retranslator) and lang_guard.py are worth reviewing for quality validation patterns. The translation agent itself is less sophisticated than hugo-translator but the overall architecture of scanning + translating + validating in a CI pipeline is well-organized.
