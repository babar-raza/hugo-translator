# Evidence Map

Maps each implementation change to its rating impact and proof.

| Change | Rating Dimension | Impact | Proof |
|--------|-----------------|--------|-------|
| Fixed shortcode regex (backreference bug) | Functional Clarity | +1.0 | Debug output: 0->1 shortcodes extracted from `{{< gist abc123 >}}`; 39/39 shortcode tests pass |
| Added comment shortcode support | Functional Clarity | (included above) | `{{/* comment */}}` now extracted; test_shortcodes_preserved_comment passes |
| Changed extra-shortcode severity to WARNING | Functional Clarity | (included above) | test_extra_shortcode_warning, test_extra_shortcode_added_to_existing pass |
| Added params whitespace normalization | Functional Clarity | (included above) | test_shortcode_with_newlines passes |
| Fixed 25 failing shortcode tests | Test Confidence | +1.5 | Before: 436/461 pass. After: 461/461 pass |
| Added `_extract_shortcodes()` compat method | Test Confidence | (included above) | TestShortcodeExtraction class (7 tests) all pass |
| Ruff auto-fix src/ (29 violations) | Code Quality | +1.0 | `ruff check src/` -> "All checks passed!" |
| Ruff auto-fix tests/ (36 violations) | Code Quality | (included above) | `ruff check tests/` -> "All checks passed!" |
| Fixed FutureWarning in l3_semantic.py | Code Quality | (included above) | Method renamed; 298 contract tests pass |
| Added local gate script | Operational Maturity | +0.5 | Gate ran: 3/3 gates pass (ruff, 1126 unit tests, 298 contract) |
| Lint-clean + local gate | Maintainability | +0.5 | All gates pass; 0 ruff violations |
| All tests pass + lint-clean + gate | Adoption Confidence | +0.5 | Local gate: ALL PASS (exit code 0) |
