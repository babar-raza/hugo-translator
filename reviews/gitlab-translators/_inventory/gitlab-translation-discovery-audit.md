# GitLab Translation Projects — Discovery Audit

## Search Configuration
- **GitLab instance:** `https://gitlab.recruitize.ai`
- **API endpoint pattern:** `/api/v4/search?scope=projects&search={term}&per_page=100`
- **Authentication:** env var `gitlab_pat` via `PRIVATE-TOKEN` header
- **Verification timestamp:** 2026-04-28T09:36:02Z

## Search Term Results (18 terms)

| # | Term | Endpoint | Results | Matched Project IDs |
|---|------|----------|---------|---------------------|
| 1 | `translate` | `/api/v4/search?scope=projects&search=translate&per_page=100` | 4 | 403, 321, 93, 51 |
| 2 | `translator` | `/api/v4/search?scope=projects&search=translator&per_page=100` | 15 | 579, 472, 313, 209, 170, 156, 150, 131, 123, 115, 88, 76, 44, 10, 3 |
| 3 | `translation` | `/api/v4/search?scope=projects&search=translation&per_page=100` | 7 | 454, 368, 318, 200, 144, 97, 95 |
| 4 | `localization` | `/api/v4/search?scope=projects&search=localization&per_page=100` | 1 | 698 |
| 5 | `localisation` | `/api/v4/search?scope=projects&search=localisation&per_page=100` | 0 | — |
| 6 | `i18n` | `/api/v4/search?scope=projects&search=i18n&per_page=100` | 1 | 33 |
| 7 | `l10n` | `/api/v4/search?scope=projects&search=l10n&per_page=100` | 0 | — |
| 8 | `locale` | `/api/v4/search?scope=projects&search=locale&per_page=100` | 1 | 166 |
| 9 | `multilingual` | `/api/v4/search?scope=projects&search=multilingual&per_page=100` | 3 | 626, 368, 200 |
| 10 | `resx` | `/api/v4/search?scope=projects&search=resx&per_page=100` | 2 | 321, 182 |
| 11 | `gettext` | `/api/v4/search?scope=projects&search=gettext&per_page=100` | 0 | — |
| 12 | `xliff` | `/api/v4/search?scope=projects&search=xliff&per_page=100` | 0 | — |
| 13 | `po` | `/api/v4/search?scope=projects&search=po&per_page=100` | 100 | (broad match — no new translation projects found beyond existing candidates) |
| 14 | `opus` | `/api/v4/search?scope=projects&search=opus&per_page=100` | 0 | — |
| 15 | `m2m100` | `/api/v4/search?scope=projects&search=m2m100&per_page=100` | 0 | — |
| 16 | `nllb` | `/api/v4/search?scope=projects&search=nllb&per_page=100` | 0 | — |
| 17 | `deepl` | `/api/v4/search?scope=projects&search=deepl&per_page=100` | 0 | — |
| 18 | `google translate` | `/api/v4/search?scope=projects&search=google+translate&per_page=100` | 0 | — |

## Deduplication Summary
- **Raw hits (excluding `po` noise):** 34 project references
- **Unique project IDs:** 31
- **Deduplication key:** project ID (primary), repo URL (secondary)
- **Duplicates resolved:** ID 368 (translation + multilingual), ID 200 (translation + multilingual), ID 321 (translate + resx)

## Candidate Funnel
| Stage | Count |
|-------|-------|
| Search terms executed | 18 |
| Raw results (non-`po`) | 34 |
| Deduplicated projects | 31 |
| Inspected via API (README + source) | 31 |
| Confirmed .md translators | 16 |
| Eliminated | 15 |

## Notes
- The `po` search term returned 100 results (API max) dominated by non-translation projects. All 100 were reviewed; no new translation-related projects were found beyond those already captured by other search terms.
- No projects matched: `localisation`, `l10n`, `gettext`, `xliff`, `opus`, `m2m100`, `nllb`, `deepl`, `google translate`.
- All classification decisions were based on README inspection + source code review via GitLab API, not name alone.
