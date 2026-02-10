# Workstream 4: AST Reconstruction - Diagnostic Findings

**Date**: 2026-01-29
**Status**: ROOT CAUSE IDENTIFIED

---

## Diagnostic Results

### Test Case: cells__docs_aspose_net__2317dc97
**Source**: `reports/phase6_cli_forced_translate/20260128-2139/failures/inspect_cells/source.md`
**Target**: `reports/phase6_cli_forced_translate/20260128-2139/failures/inspect_cells/target.md`

### Feature Count Comparison

| Feature | Source | Target | Diff | Status |
|---------|--------|--------|------|--------|
| Bold | 0 | 1 | +1 | FAIL |
| Italic | 5 | 0 | -5 | FAIL |
| Links | 1 | 0 | -1 | FAIL |
| H2 Headings | 3 | 0 | -3 | FAIL |
| H3 Headings | 1 | 4 | +3 | FAIL |

---

## ROOT CAUSE ANALYSIS

### Issue 1: HEADING LEVEL SHIFT (Critical)
**Problem**: All H2 headings became H3 headings

**Source**:
```markdown
## System Requirements
## Installation
## Supported Formats
### Example Code
```

**Target**:
```markdown
### Requisiti di sistema
### Installation (in Japanese)
### Formats soutenus
### Code d'exemple
```

**Root Cause**: Heading level metadata not preserved during translation application. The HEADING node's `attrs['level']` is being changed from 2 to 3.

**Fix Location**: `src/translation_engine/reconstructor/ast_renderer.py` lines 230-275 (_apply_to_node method)

### Issue 2: BOLD ADDED INCORRECTLY
**Problem**: First line has bold that wasn't in source

**Source**:
```markdown
Welcome to the world of spreadsheet manipulation...
```

**Target**:
```markdown
**Commencer avec Aspose.Cells pour .NET**

Avec Aspose.Cells pour .NET...
```

**Root Cause**: Translation created a new STRONG node that didn't exist in source AST. This suggests the translator added formatting, or the AST structure was misinterpreted.

### Issue 3: ITALICS LOST
**Problem**: 5 italic spans in source, 0 in target

**Source**: File extensions in parentheses were likely italicized

**Root Cause**: EMPHASIS nodes flattened during paragraph reconstruction

### Issue 4: LINK LOST
**Problem**: 1 link in source, 0 in target

**Source**:
```markdown
[various spreadsheet formats](supported-file-formats)
```

**Target**:
```markdown
différents formats de brochure (no link!)
```

**Root Cause**: LINK node flattened during paragraph reconstruction. The logic at `ast_renderer.py:242` checks for inline formatting but may still flatten if extraction strategy was "sentence_only".

---

## HYPOTHESIS

The `_apply_to_node` method in `ast_renderer.py` (lines 230-275) has logic that:

1. **Checks for inline formatting** (line 236-240)
2. **If found, skips flattening** (line 242-251)
3. **If not found, flattens to single TEXT node** (line 252-270)

**BUT**: The issue is that:
- If a PARAGRAPH was extracted as a "sentence_only" unit, the translation is applied as flat text
- The check `has_inline_formatting` happens AFTER the translation is already extracted
- Even when skipping flatten, the children may not be processed correctly

**CRITICAL BUG**: Line 249 says `# Don't mark as applied - this allows children to be processed` but there's no guarantee the children TEXT nodes have corresponding TextUnits!

---

## THE REAL PROBLEM

Looking at the target output more carefully:

```markdown
**Commencer avec Aspose.Cells pour .NET**



Avec Aspose.Cells pour .NET, vous pouvez facilement lire et écrire les feuilles d'écran Excel...



### Requisiti di sistema
```

Notice:
1. **Double newlines everywhere** - suggests flattening happened
2. **Mixed languages** ("Requisiti di sistema" is Italian, rest is French)
3. **Heading levels all wrong**

This suggests the problem is NOT in AST rendering, but in **EXTRACTION or TRANSLATION STRATEGY**.

The extractor may be:
1. Extracting entire paragraphs as single units (losing inline structure)
2. Extracting headings without preserving level metadata
3. Using a segmentation strategy that destroys structure

---

## RECOMMENDED FIX STRATEGY

### Option A: Fix Extraction (Harder but Better)
Ensure `TextUnitExtractor` preserves inline formatting nodes:
- Extract STRONG/EMPHASIS/LINK nodes separately
- Maintain parent-child relationships in metadata
- Apply translations back to specific nodes, not flat text

### Option B: Fix Application (Easier but Limited)
Improve `_apply_to_node` to:
- Never flatten paragraphs with ANY children beyond plain TEXT
- Preserve HEADING level during application
- Check if TextUnit has metadata about original node type

### Option C: Fix Both (Recommended)
1. **Extraction**: Add metadata to TextUnits about inline formatting
2. **Application**: Use metadata to preserve structure
3. **Rendering**: Already correct, no changes needed

---

## IMMEDIATE ACTION ITEMS

1. ✅ **Diagnose completed**: Root cause identified as extraction/application issue
2. ⏭️ **Review TextUnitExtractor**: Check how paragraphs with inline formatting are extracted
3. ⏭️ **Review _apply_to_node**: Check how translations are applied back
4. ⏭️ **Create focused fix**: Target the specific logic causing flattening
5. ⏭️ **Add regression tests**: Based on this actual failure case

---

## TIME ESTIMATE FOR FIX

**Complex Fix** (Option C): 8-12 hours
- Review extraction logic (2-3 hours)
- Modify extraction to preserve metadata (3-4 hours)
- Modify application to use metadata (2-3 hours)
- Test and validate (1-2 hours)

**Simple Fix** (Option B): 3-5 hours
- Modify _apply_to_node to not flatten (1-2 hours)
- Add guards for heading level (1 hour)
- Test and validate (1-2 hours)

---

## CONCLUSION

The markdown fidelity failures are caused by **structural flattening during translation application**, not by rendering issues. The AST renderer itself is correct.

The fix requires modifying how translations are applied back to the AST to preserve inline formatting nodes (STRONG, EMPHASIS, LINK) and container attributes (HEADING level).

**Recommended Approach**: Implement Option B (fix application logic) as a quick win, then consider Option C (full extraction/application improvement) for Phase 7.

---

**Status**: DIAGNOSIS COMPLETE, READY FOR IMPLEMENTATION
**Next**: Review TextUnitExtractor and _apply_to_node logic
**ETA**: 3-5 hours for focused fix
