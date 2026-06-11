# Phase 4 - Healed Implementation Plan

Same as Phase 3 plan with these refinements:

1. **L1-1**: Add separate `_COMMENT_RE` pattern for `{{/* */}}` and merge results in `_extract_structured()`. Also add backward-compat `_extract_shortcodes()` returning list of normalized raw strings.
2. **L1-2**: Change extra-shortcode detection from ERROR to WARNING. Keep missing/reduced as ERROR.
3. **L2-1**: Fix TestShortcodeExtraction class to use `_extract_shortcodes()` (now a compat wrapper). Fix TestShortcodePreservationValidator and TestValidationResultStructure to match new behavior (comments detected, extras are warnings).
4. **L5-1/L5-2**: Run ruff --fix for auto-fixable violations.
5. **L1-3**: Fix deprecated method call in l3_semantic.py.
6. **L3-1**: Create minimal local gate script.

Execution order: L5 (ruff fix) -> L1 (source fixes) -> L2 (test fixes) -> L3 (local gate) -> L7 (verification)
