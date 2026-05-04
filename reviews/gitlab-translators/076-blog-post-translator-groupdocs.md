# Blog Post Translator GroupDocs (ID 076)

## Metadata
- **GitLab path:** groupdocs-cloud/vlitvinchik/blog-post-translator-groupdocs
- **Web URL:** https://gitlab.recruitize.ai/groupdocs-cloud/vlitvinchik/blog-post-translator-groupdocs
- **Repository URL:** https://gitlab.recruitize.ai/groupdocs-cloud/vlitvinchik/blog-post-translator-groupdocs.git
- **Default branch:** master
- **Inspected commit:** cf2b9a9dd40e6443ba1abdc2b5d4c1abd0e4a5ad
- **Last activity:** 2026-03-15
- **Language/runtime:** Python 3.x
- **Inspection status:** Complete
- **Confidence:** High

## Purpose
A modular three-tool translation system for GroupDocs blog posts: a missing-translations scanner, an LLM-powered translator with structural checks and cross-model review, and a translation validator. Designed to work as a pipeline where scanner and validator output feed directly into the translator. Optimized through 22 automated prompt experiments.

## Evidence Summary
- `blog-post-translator/translate_posts.py` -- Main translator with structural checks and LLM review
- `blog-post-translator/process_translation_output.py` -- Post-processing of translation output
- `blog-post-translator/create_translation_issue.py` -- GitHub issue creation for translated posts
- `blog-post-translator/requirements.txt` -- Minimal dependencies (openai, pyyaml)
- `missing-translations-scanner/scan_missing_translations.py` -- Scanner with declarative filters
- `translation-validator/validate_translations.py` -- Structural and content validation (9 checks)
- `.github/workflows/translate-blog-posts.yml` -- CI workflow
- `.github/workflows/scan-missing-translations.yml` -- Scan workflow
- `README.md` -- Comprehensive documentation with architecture diagrams

## Architecture
| Area | Finding | Evidence |
|------|---------|----------|
| Entrypoint(s) | `translate_posts.py`, `scan_missing_translations.py`, `validate_translations.py` | translate_posts.py:683, scan_missing_translations.py:573, validate_translations.py:422 |
| Key modules | translate_posts (translator), scan_missing_translations (scanner), validate_translations (validator) | Three separate tools |
| Config | Environment variables for API keys/models; YAML config.yml for expected languages | translate_posts.py:31-46 |
| Dependencies | openai>=1.0.0, pyyaml>=6.0 | blog-post-translator/requirements.txt:1-2 |
| CI/CD | GitHub Actions: scan workflow (scheduled cron) + translate workflow (manual) | .github/workflows/ |
| Tests | none | No test files found |
| Examples | CLI usage examples in READMEs and argparse epilogs | blog-post-translator/README.md |

## Translation Capabilities Checklist
| Capability | Status | Evidence | Notes |
|------------|--------|----------|-------|
| Markdown translation | Yes | translate_posts.py:131-181 | Full body translation via LLM with markdown preservation rules in prompt |
| Hugo content/frontmatter | Yes | translate_posts.py:314-386 | Batch JSON front-matter translation (title, seoTitle, description, summary, cover.alt/caption) in single API call |
| Code block protection | Yes | translate_posts.py:214-216 | Structural check counts ``` markers; prompt instructs to preserve code blocks |
| Shortcode protection | Yes | translate_posts.py:226-230 | Structural check verifies `{{< >}}` shortcodes preserved; prompt says "copy Hugo shortcodes verbatim" |
| Placeholder protection | No | - | No explicit placeholder system |
| HTML tag preservation | Partial | translate_posts.py:150 | Prompt says "Preserve markdown formatting exactly" but no explicit HTML handling |
| YAML/frontmatter preservation | Yes | translate_posts.py:78-101, 314-386 | yaml.safe_load parsing; batch JSON translation of front-matter fields |
| AST or parser-based handling | No | - | Regex and string-based, no AST |
| Batch translation | Yes | translate_posts.py:314-386 | Front-matter fields translated as single JSON batch (1 API call instead of 6-7) |
| Translation memory/cache | No | - | No caching |
| Glossary/terminology | Yes | translate_posts.py:157-163 | Explicit product name glossary in prompt: GroupDocs.*, .NET, NuGet, C#, net6.0, Free Support Forum |
| Multilingual folder generation | Yes | translate_posts.py:504-534 | Generates index.{lang}.md files |
| LLM-based translation | Yes | translate_posts.py:131-181 | OpenAI-compatible API (professionalize.com), model configurable via env var |
| MT model usage | No | - | LLM only |
| Retry/backoff | Yes | translate_posts.py:585-679 | Up to 3 retries with feedback context from previous failures (structural issues, review issues) |
| Progress logging | Yes | translate_posts.py:804-817 | Per-post, per-language progress with checkmark/cross indicators |
| Validation/QA | Yes | translate_posts.py:206-258, validate_translations.py:74-142 | 8 structural checks + 3 content checks; cross-model LLM review |
| Resumability | Partial | - | Reads from JSON report of missing translations; no checkpoint within a run |
| Dry-run/safety mode | Yes | translate_posts.py:768-774 | `--dry-run` flag shows what would be translated without executing |

## Key Implementation Details
- Translation flow per post: (1) translate front-matter as JSON batch, (2) translate body, (3) structural checks (free, no LLM), (4) optional cross-model LLM review, (5) retry with specific feedback if issues found, (6) save and verify.
- Structural checks (translate_posts.py:206-258): code_blocks_mismatch, headers_mismatch, shortcodes_missing, link_refs_missing, likely_truncated, prompt_leakage, product_names_missing.
- Cross-model review (translate_posts.py:264-311): uses a second model (PROFESSIONALIZE_REVIEWER_MODEL env var) to review translations, producing PASS/FAIL with issue list.
- Prompt leakage detection and stripping (_strip_prompt_leakage at line 104-128) handles model echoing translation instructions.
- Validator (validate_translations.py:74-142) runs 9 structural checks (links, code_blocks, headers, tables, length, products, shortcodes, link_refs, no_prompt_leakage) returning normalized 0-1 scores.
- Scanner uses declarative PostFilter pattern (scan_missing_translations.py:97-222) for filtering archived posts and date ranges.

## Strengths
- Best-documented project in this batch: clear architecture diagrams, detailed README with experiment findings.
- Sophisticated retry loop with context-aware feedback from failed structural checks and LLM review.
- Cross-model quality review (different model reviews a different model's translation).
- Batch front-matter translation reduces API calls from ~7 to 2 per language.
- Prompt leakage detection and removal is a practical production concern handled well.
- Dry-run mode available.
- Validator output is directly compatible with translator input (same JSON schema), enabling pipeline composition.
- Minimal dependencies (just openai + pyyaml for the translator).

## Weaknesses and Gaps
- No tests.
- No translation memory or caching.
- No AST-based markdown parsing.
- No explicit placeholder protection system.
- Environment variable-based configuration without defaults file or schema validation.
- Scanner hardcodes min_year=2025 as default filter, which may become stale.
- No rate limiting or exponential backoff for API calls (only time.sleep between retries).

## Relevance to hugo-translator
**Classification:** Directly relevant

This is the most well-designed translator in the batch. Several patterns are worth studying:
- The structural check system (translate_posts.py:206-258) provides a lightweight, no-LLM validation layer that catches 87% of issues per the README. This pattern complements hugo-translator's purity-based validation.
- The cross-model review pattern (using a different model to review translations) is a robust quality signal that hugo-translator could adopt.
- The retry-with-feedback pattern (including specific issue descriptions from previous attempts in the retry prompt) is superior to blind retries.
- Prompt leakage detection and stripping is a practical concern that hugo-translator should address.
- The batch JSON front-matter translation pattern reduces API calls efficiently.

Do NOT reuse: the scanner/validator are GroupDocs-specific and would need significant adaptation.

## Production Risk Notes
- No input sanitization on file paths from JSON reports.
- Translations are written to disk immediately; no rollback mechanism if a batch partially fails.
- Cross-model review adds latency and cost per translation; no circuit breaker if review model is unavailable.
- Direct push to default branch in CI workflow without PR review.

## Final Recommendation
**Study first** -- This is the highest-quality translator in this batch. The structural check system, cross-model review, retry-with-feedback, prompt leakage handling, and batch front-matter translation are all patterns worth studying and potentially adapting for hugo-translator. The validator's 9-check structural scoring system is also well-designed.
