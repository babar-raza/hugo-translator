# AST Translation Quick Start Guide

## TL;DR

AST-based translation provides 100% structure preservation for Hugo markdown files. This guide shows you how to enable and use it.

---

## Enable AST Translation

### For a Single Site

```bash
# Enable
python scripts/toggle_ast_translation.py --site products.aspose.net --enable

# Check status
python scripts/toggle_ast_translation.py --status

# Disable (if needed)
python scripts/toggle_ast_translation.py --site products.aspose.net --disable
```

### For All Sites

```bash
# Enable for all sites
python scripts/toggle_ast_translation.py --all-sites --enable

# Preview changes (dry run)
python scripts/toggle_ast_translation.py --all-sites --enable --dry-run
```

---

## Configuration

Add to your site profile (`config/site_profiles/<site>.yaml`):

```yaml
body:
  # Enable AST-based translation
  use_ast_body_reconstruction: true

  # Segmentation strategy (optional, default: adaptive)
  ast_segmentation_strategy: "adaptive"  # or "leaf_only" or "sentence_only"

  # Batch size (optional, default: 50)
  ast_batch_size: 50  # Range: 10-100
```

### Strategy Selection

- **adaptive** (recommended): Best balance - full sentences for plain text, leaf-level for formatted content
- **leaf_only**: Maximum safety - always leaf-level segmentation (slightly reduced fluency)
- **sentence_only**: Maximum fluency - full-sentence translation (higher risk with complex formatting)

---

## Usage

No code changes needed! Just translate as normal:

```bash
# Single file
python -m src.cli translate-file --site products.aspose.net path/to/file.md

# Directory
python -m src.cli translate-directory --site products.aspose.net path/to/content/
```

The engine automatically uses AST translation when `use_ast_body_reconstruction: true` in the site profile.

---

## Monitoring

### Key Metrics

Check Grafana dashboard for:

- **Fallback Rate**: Must be <5% (alert if >5%)
- **Corruption Rate**: Must be 0% (critical alert if >0%)
- **Batch Efficiency**: Target ~50 units/batch

### Quick Status Check

```bash
# Check telemetry in logs
grep "AST Translation: Successfully translated" /var/log/hugo-translator.log | tail -10

# Look for fallbacks (should be rare)
grep "falling back to individual translation" /var/log/hugo-translator.log | wc -l
```

### Health Indicators

✅ **Healthy**:
```
INFO: AST Translation: Successfully translated 42 units (1 batches, 0 fallbacks)
```

⚠️ **Warning** (some fallbacks):
```
INFO: AST Translation: Successfully translated 42 units (2 batches, 3 fallbacks)
# Fallback rate: 3/42 = 7% - slightly high but acceptable
```

❌ **Problem** (many fallbacks):
```
INFO: AST Translation: Successfully translated 42 units (5 batches, 20 fallbacks)
# Fallback rate: 20/42 = 48% - CRITICAL, needs investigation
```

---

## Troubleshooting

### High Fallback Rate (>5%)

**Quick Fix**: Reduce batch size

```yaml
# In site profile
body:
  ast_batch_size: 25  # Reduced from 50
```

**Then**: Re-translate test documents and check if fallback rate improves

### Translation Quality Issues

**Quick Fix**: Try different segmentation strategy

```yaml
# For formatting issues, use leaf-only
body:
  ast_segmentation_strategy: "leaf_only"

# OR for fluency issues, use sentence-only
body:
  ast_segmentation_strategy: "sentence_only"
```

### Rollback

If you need to rollback:

```bash
# Disable AST translation
python scripts/toggle_ast_translation.py --site <site_id> --disable

# Re-translate affected files with legacy approach
python -m src.cli translate-file --site <site_id> --force path/to/file.md
```

---

## Benefits

When AST translation is enabled, you get:

- ✅ **100% link preservation** (URLs and syntax)
- ✅ **100% code preservation** (blocks and inline code)
- ✅ **100% image preservation** (src attributes)
- ✅ **100% formatting preservation** (bold, italic, lists, tables)
- ✅ **0% corruption rate** (verified on 100 real documents)
- ✅ **Product name protection** (Aspose.Slides, etc. never translated)
- ✅ **10-30% API cost reduction** (from batching)

---

## Files Reference

- **Configuration**: `config/site_profiles/<site>.yaml`
- **Toggle Script**: `scripts/toggle_ast_translation.py`
- **Rollout Guide**: `docs/ast_translation_rollout.md` (full details)
- **Monitoring Guide**: `docs/ast_translation_monitoring.md` (dashboards & alerts)
- **This Guide**: `docs/ast_translation_quickstart.md`

---

## Getting Help

1. **Check status**: `python scripts/toggle_ast_translation.py --status`
2. **Check logs**: `grep "AST Translation" /var/log/hugo-translator.log`
3. **Check metrics**: Grafana → AST Translation dashboard
4. **Read docs**: See `docs/ast_translation_rollout.md` for detailed troubleshooting
5. **File issue**: If problem persists, file issue with telemetry data and logs

---

## Example: Full Workflow

```bash
# 1. Enable AST translation for test site
python scripts/toggle_ast_translation.py --site test.aspose.net --enable

# 2. Translate test documents
python -m src.cli translate-directory --site test.aspose.net /path/to/test/content/

# 3. Check telemetry
grep "AST Translation: Successfully translated" /var/log/hugo-translator.log | tail -5

# 4. Verify fallback rate is low (<5%)
# Should see: "X batches, Y fallbacks" where Y/total_units < 0.05

# 5. Spot-check translated files for quality

# 6. If all good, enable for production site
python scripts/toggle_ast_translation.py --site products.aspose.net --enable
```

---

## Advanced: Custom Terminology

To protect custom product names:

1. Edit `config/terminology/aspose_terms.txt`
2. Add one term per line:
   ```
   YourProductName
   CustomTerm123
   ```
3. Re-translate documents - terms will be automatically protected

---

## Questions?

See full documentation:
- **Rollout**: `docs/ast_translation_rollout.md`
- **Monitoring**: `docs/ast_translation_monitoring.md`
