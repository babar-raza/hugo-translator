# Phase 3 - Implementation Plan

## Lane 1: Source and Workflow Behavior Healing

### L1-1: Fix ShortcodePreservationValidator regex to match comment shortcodes
- **File**: src/translation_engine/validation/shortcode_preservation_validator.py
- **Issue**: Regex `[<%]` doesn't match `{{/* */}}` comments
- **Fix**: Add comment pattern or extend regex to handle `/*...*/`
- **Impact**: Functional Clarity +0.5, Test Confidence (enables test fixes)

### L1-2: Fix extra-shortcode severity from ERROR to WARNING
- **File**: src/translation_engine/validation/shortcode_preservation_validator.py
- **Issue**: Extra shortcodes marked as ERROR causing false rejections
- **Fix**: Use WARNING for unexpected extra shortcodes (hallucination is suspicious but not critical as source shortcodes are preserved)
- **Impact**: Functional Clarity +0.5

### L1-3: Fix FutureWarning in L3 Semantic TM
- **File**: src/tm/l3_semantic.py line 132
- **Issue**: `get_sentence_embedding_dimension` deprecated
- **Fix**: Rename to `get_embedding_dimension`
- **Impact**: Code Quality +0.25

## Lane 2: Tests and Regression Coverage

### L2-1: Fix 25 failing shortcode preservation tests
- **File**: tests/unit/validation/test_shortcode_preservation_validator.py
- **Issue**: Tests call removed `_extract_shortcodes()` method and expect WARNING for extras
- **Fix**: Update tests to use new `_extract_structured()` API or add backward-compat method
- **Impact**: Test Confidence +1.5

## Lane 3: Validators and Local Gates

### L3-1: Add local validation gate script
- **File**: scripts/ci/run_local_gate.py (new)
- **Purpose**: Run ruff check + targeted tests as pre-commit/pre-push gate
- **Impact**: Operational Maturity +0.5

## Lane 4: CI Gate Hardening

### L4-1: No changes planned (CI is already well-structured with release_gate.yml)

## Lane 5: Code Quality (ruff auto-fix)

### L5-1: Fix 29 auto-fixable ruff violations in src/
- **Command**: ruff check src/ --fix
- **Impact**: Code Quality +0.5

### L5-2: Fix 36 auto-fixable ruff violations in tests/
- **Command**: ruff check tests/ --fix
- **Impact**: Code Quality +0.25

## Lane 6: Agentic/Governance Hardening

### L6-1: No changes planned (AGENTS.md adequate, orchestrator functional)

## Lane 7: Verification

### L7-1: Re-run all affected test suites after fixes
### L7-2: Re-run ruff after auto-fix
### L7-3: Verify shortcode comment validation works
### L7-4: Final git status and diff review
