# Rollback Notes

## Full Rollback
All sprint changes are file edits under the target project. To revert everything:

```bash
cd "C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator-gitlab"

# Revert all modified source and test files
git checkout -- src/ tests/

# Remove new files
rm scripts/ci/run_local_gate.py

# Remove evidence directory
rm -rf .local/rating-healing-runs/
```

## Partial Rollback

### Revert only the shortcode validator fix
```bash
git checkout -- src/translation_engine/validation/shortcode_preservation_validator.py
git checkout -- tests/unit/validation/test_shortcode_preservation_validator.py
```
**Warning**: This restores the broken regex and 25 failing tests.

### Revert only the ruff auto-fixes
```bash
git checkout -- src/model_runtime/ src/observability/ src/translation_engine/correction.py src/translation_engine/validation/frontmatter_integrity_validator.py src/translation_engine/validation/validation_suite.py
git checkout -- tests/benchmark_l3_search.py tests/integration/ tests/models/ tests/unit/formatting/ tests/unit/logging/ tests/unit/observability/ tests/unit/test_asset_sync.py tests/unit/test_ast_frontmatter_baseline.py tests/unit/test_ast_frontmatter_reconstruction.py tests/unit/test_batch_purity_skip_compensation.py tests/unit/test_code_block_content.py tests/unit/test_correction_scope.py tests/unit/test_git_changed_files.py tests/unit/test_llm_output_ratio.py tests/unit/test_quality_score.py tests/unit/test_review_cache.py tests/unit/tm/ tests/unit/translation_engine/test_repeated_feedback_guard.py tests/unit/validation/test_frontmatter_key_integrity.py tests/unit/validation/test_shortcode_hallucination.py tests/unit/workers/
```

### Revert only the L3 FutureWarning fix
```bash
git checkout -- src/tm/l3_semantic.py
```

## Pre-existing Uncommitted Changes (NOT from this sprint)
- config/site_profiles/docs.aspose.org.yaml
- config/site_profiles/reference.aspose.org.yaml

These were present before the sprint began and should NOT be reverted as part of rollback.
