# Product Pages Translator Agent (ID 579)

## Metadata
- **GitLab path:** sialkot/islamabad-fileformat/product-pages-translator-agent
- **Web URL:** https://gitlab.recruitize.ai/sialkot/islamabad-fileformat/product-pages-translator-agent
- **Repository URL:** https://gitlab.recruitize.ai/sialkot/islamabad-fileformat/product-pages-translator-agent.git
- **Default branch:** master
- **Inspected commit:** a0665175302df755a08575356d29821aac8249af
- **Last activity:** 2026-04-23
- **Language/runtime:** Python (CrewAI)
- **Inspection status:** Complete
- **Confidence:** High

## Purpose
An autonomous CrewAI agent for translating fileformat.com product pages. Features smart chunking for large files, asset (image) synchronization across language folders, dynamic language recognition, and Hugo shortcode attribute extraction. Extracts translatable strings from frontmatter, shortcode attributes, and HTML tags, then reconstructs localized files by injecting translations.

## Evidence Summary
- `src/product_page_translator_agent/tools/translation_engine_tool.py` -- TranslationEngine: extract translatable strings (frontmatter, shortcodes, HTML tags), reconstruct localized files
- `src/product_page_translator_agent/tools/file_manager_tool.py` -- File management: recursive search, asset sync across language folders
- `src/product_page_translator_agent/crew.py` -- CrewAI orchestration
- `src/product_page_translator_agent/main.py` -- Entry point with orchestration layer
- `src/product_page_translator_agent/config/agents.yaml` -- Agent persona and goals
- `src/product_page_translator_agent/config/tasks.yaml` -- Task definitions
- `content/` -- Sample translated content (ar, az, bg, en subdirectories with images and .md files)
- `AGENTS.md` -- Agent documentation
- `knowledge/user_preference.txt` -- User preferences for translation

## Architecture
| Area | Finding | Evidence |
|------|---------|----------|
| Entrypoint(s) | `main.py` → `crew.py` | main.py, crew.py |
| Key modules | TranslationEngine, file_manager_tool, crew | tools/, config/ |
| Config | `.env`, `agents.yaml`, `tasks.yaml`, `en.json` | config/, .env |
| Dependencies | crewai, crewai-tools | pyproject.toml |
| CI/CD | None | No CI files found |
| Tests | None | No test files found |
| Examples | Translated content samples in `content/` | content/ar/, content/az/, etc. |

## Translation Capabilities Checklist
| Capability | Status | Evidence | Notes |
|------------|--------|----------|-------|
| Markdown translation | Yes | translation_engine_tool.py:702-755 | Extract strings → translate → reconstruct |
| Hugo content/frontmatter | Yes | translation_engine_tool.py:698-720 | Extracts frontmatter keys (title, description, keywords, ProductName, etc.) |
| Code block protection | No | -- | No code block handling |
| Shortcode protection | Yes | translation_engine_tool.py:722-730 | Extracts shortcode attributes (Image_H2_Text, Header_H1_Text, Header_H2_Text) |
| Placeholder protection | No | -- | No placeholder mechanism |
| HTML tag preservation | Yes | translation_engine_tool.py:732-740 | Extracts content from h1-h6, p, li tags for translation |
| YAML/frontmatter preservation | Yes | translation_engine_tool.py:710-720 | Regex frontmatter extraction, selective key translation |
| AST or parser-based handling | No | -- | Regex-based extraction |
| Batch translation | Yes | translation_engine_tool.py:744-755 | `extract_directory()` processes all .md files in directory |
| Translation memory/cache | No | -- | No caching |
| Glossary/terminology | No | -- | No glossary |
| Multilingual folder generation | Yes | file_manager_tool.py | Creates language folders with translated content and synced assets |
| LLM-based translation | Yes | crew.py | CrewAI with LLM via custom API endpoint |
| MT model usage | No | -- | LLM only |
| Retry/backoff | No | -- | No retry logic |
| Progress logging | Partial | -- | CrewAI agent logging |
| Validation/QA | No | -- | No validation |
| Resumability | Partial | -- | Recognizes previously translated files |
| Dry-run/safety mode | No | -- | No dry-run |

## Key Implementation Details
- **String extraction approach**: TranslationEngine extracts translatable strings from 3 sources:
  1. Frontmatter keys (title, description, keywords, ProductName, ListingPage_Short_Description)
  2. Hugo shortcode attributes (Image_H2_Text, Header_H1_Text, Header_H2_Text)
  3. HTML tag content (h1-h6, p, li)
- **File reconstruction**: `reconstruct_file()` reads source file, replaces extracted strings with translated versions, writes to target path. Source file serves as template.
- **Asset synchronization**: file_manager_tool copies images and non-markdown assets from English folder to all target language folders.
- **Smart chunking**: README mentions smart chunking for large files to handle context window limitations.
- **Directory-level extraction**: `extract_directory()` recursively scans all .md files, returns dict of relative paths → translatable strings.
- Sample translated output included in `content/` (ar, az, bg with OMR/Ruby product pages).
- `en.json` contains language code mappings.

## Strengths
- Most granular string extraction approach (frontmatter + shortcode attributes + HTML tags separately).
- Asset synchronization across language folders is unique and practical.
- File reconstruction from source template preserves structure.
- Directory-level batch extraction.
- Shortcode attribute extraction (Image_H2_Text, Header_H1_Text) is Hugo-aware.
- Sample output demonstrates working translations.

## Weaknesses and Gaps
- No code block protection.
- No translation memory or caching.
- No validation of translation output.
- No retry logic.
- No tests, no CI/CD.
- Regex-based extraction is fragile.
- CrewAI framework adds overhead.
- HTML tag extraction via regex can miss nested/complex structures.
- Shortcode attribute list is hardcoded (not configurable).

## Relevance to hugo-translator
**Classification:** Partially relevant

The granular string extraction approach (separate handling for frontmatter, shortcode attributes, and HTML tags) is the most interesting pattern. The asset synchronization across language folders is a practical feature that hugo-translator doesn't have. The file reconstruction from source template approach is a clean pattern for maintaining structure.

## Production Risk Notes
- Regex-based extraction is fragile for complex Markdown.
- No error handling for malformed content.
- CrewAI dependency.
- Hardcoded shortcode attribute names limit flexibility.

## Final Recommendation
**Mine for one component** -- The granular string extraction (frontmatter + shortcode attributes + HTML tags) and asset synchronization patterns are worth studying. The file reconstruction from source template is a clean approach.
