# Troubleshooting

This page lists common issues and mitigation steps for Hugo Translator verification runs.

## AST E2E language purity fallback warnings

### Symptoms
- "Language purity check FAILED" or "HIGH FALLBACK RATE DETECTED" lines in AST E2E output.

### Cause
The AST batch translator rejects a batch when any unit appears to be in the wrong target language. It falls back to per-unit translation to enforce language purity.

### Impact
- Increased runtime due to fallback.
- Potential quality variance if language detection misclassifies short segments.

### Mitigation
- Reduce AST batch sizes or token limits in the site profile.
- Re-evaluate model selection for the target language.
- Spot-check translated output files for mixed-language fragments.

### Evidence
- reports/user-guide/run_artifacts/script-validate_ast_e2e/run.txt
- reports/user-guide/run_artifacts/script-validate_ast_e2e/report.md
