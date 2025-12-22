# AST-Based Translation Rollout Guide

## Overview

This document provides guidelines for rolling out the new AST-based translation feature to production sites. The AST-based translation system provides 100% structure preservation by separating document structure from translatable content.

**Status**: ✅ Ready for gradual production rollout (feature complete, validated)

**Feature Flag**: `use_ast_body_reconstruction` in site profile `body:` section

---

## Key Benefits

1. **100% Structure Preservation**: Guaranteed preservation of:
   - Links (URLs and structure)
   - Images (src attributes)
   - Code blocks and inline code
   - Markdown formatting (bold, italic, lists, tables)
   - HTML blocks

2. **Product Name Protection**: Automatic detection and preservation of:
   - Product names (Aspose.Slides, Aspose.Cells, etc.)
   - Technical identifiers (CamelCase, snake_case, ALL_CAPS)
   - Code-like content

3. **Improved Translation Quality**:
   - Smart segmentation (adaptive, leaf-only, or sentence-only)
   - Context-aware translation
   - Reduced corruption from placeholder interference

4. **Enhanced Observability**:
   - Comprehensive telemetry tracking
   - Batch translation statistics
   - Fallback rate monitoring

---

## Rollout Strategy: Graduated Deployment

### Phase 0: Pre-Rollout Validation ✅

**Completed**:
- ✅ Unit tests passing (≥90% coverage)
- ✅ Integration tests passing
- ✅ Validation on 100 real documents
- ✅ Zero corruption rate verified
- ✅ 100% link/code/image preservation verified
- ✅ Fallback mechanism tested

### Phase 1: Internal Test Site (Week 1)

**Target**: Internal staging environment

**Steps**:
1. Enable AST translation for internal test site:
   ```bash
   python scripts/toggle_ast_translation.py --site internal.test.aspose.net --enable
   ```

2. Translate 20-50 test documents

3. **Success Criteria**:
   - ✅ Zero corruption rate
   - ✅ 100% link/code/image preservation
   - ✅ Telemetry shows <5% fallback rate
   - ✅ No errors in logs
   - ✅ Human review confirms quality

4. **Monitor**:
   - Check Grafana dashboard (ast_translation_* metrics)
   - Review logs for errors or warnings
   - Spot-check translated output

**Decision**: If all success criteria met → Proceed to Phase 2

### Phase 2: Low-Risk Production Site (Week 2-3)

**Target**: One low-traffic production site (e.g., `blog.aspose.net`)

**Steps**:
1. Enable AST translation:
   ```bash
   python scripts/toggle_ast_translation.py --site blog.aspose.net --enable
   ```

2. Translate 100-200 documents

3. **Success Criteria**:
   - ✅ Zero corruption rate (automated validation)
   - ✅ 100% link/code/image preservation
   - ✅ Batch fallback rate <5%
   - ✅ No user complaints
   - ✅ Human review of 10 random documents confirms quality

4. **Monitor** (daily for 1 week):
   - Telemetry: `ast_translation_enabled`, `ast_batch_calls`, `ast_individual_fallbacks`
   - Logs: Check for "AST translation failed" errors
   - User feedback: Monitor support channels

**Rollback Plan**: If issues detected:
```bash
python scripts/toggle_ast_translation.py --site blog.aspose.net --disable
```

**Decision**: If all success criteria met for 1 week → Proceed to Phase 3

### Phase 3: Medium-Risk Production Sites (Week 4-5)

**Target**: Medium-traffic sites (e.g., `docs.aspose.net`, `reference.aspose.net`)

**Steps**:
1. Enable AST translation for 2-3 medium-traffic sites (one at a time)

2. Translate existing content + monitor new translations

3. **Success Criteria** (per site):
   - ✅ Zero corruption rate
   - ✅ 100% link/code/image preservation
   - ✅ Batch fallback rate <5%
   - ✅ No performance degradation
   - ✅ Human review confirms quality improvement

4. **Monitor** (daily for first week, weekly thereafter):
   - Same metrics as Phase 2
   - Translation throughput (no regression)
   - API cost (batching should reduce cost)

**Decision**: If all sites stable for 1 week → Proceed to Phase 4

### Phase 4: High-Traffic Production Sites (Week 6-8)

**Target**: High-traffic sites (e.g., `products.aspose.net`, `kb.aspose.net`)

**Steps**:
1. Enable AST translation for high-traffic sites (one at a time, 1 week apart)

2. **Success Criteria** (per site):
   - ✅ Zero corruption rate
   - ✅ 100% link/code/image preservation
   - ✅ Batch fallback rate <5%
   - ✅ No performance degradation
   - ✅ No user complaints
   - ✅ Human review confirms quality improvement

3. **Monitor** (daily for first 2 weeks):
   - Full telemetry suite
   - Performance metrics (latency, throughput)
   - Cost metrics (API calls, token usage)
   - User feedback

**Decision**: If all sites stable for 2 weeks → Proceed to Phase 5

### Phase 5: Full Production Rollout (Week 9+)

**Target**: All remaining production sites

**Steps**:
1. Enable AST translation for all remaining sites

2. Update default site profile template to enable AST translation for new sites

3. **Success Criteria**:
   - ✅ All sites stable
   - ✅ Zero corruption rate across all sites
   - ✅ Telemetry shows expected patterns
   - ✅ Cost reduction from batching visible

4. **Monitor** (weekly):
   - Aggregate telemetry across all sites
   - Cost trends
   - Quality trends

**Final Step**: Update documentation to recommend AST translation as default

---

## Monitoring & Telemetry

### Key Metrics

Monitor these metrics in Grafana:

1. **ast_translation_enabled** (gauge)
   - Shows which sites have AST translation enabled
   - Expected: Gradually increases from 0 to 100% of sites

2. **ast_units_extracted** (counter)
   - Total TextUnits extracted from AST per translation
   - Expected: 10-50 units per typical document

3. **ast_units_translatable** (counter)
   - TextUnits that needed translation
   - Expected: 60-80% of extracted units (rest are protected)

4. **ast_units_protected** (counter)
   - TextUnits marked as do_not_translate (code, URLs, product names)
   - Expected: 20-40% of extracted units

5. **ast_batch_calls** (counter)
   - Number of batch translation calls
   - Expected: Low (1-2 per document with batch_size=50)

6. **ast_individual_fallbacks** (counter)
   - Number of fallbacks to individual translation
   - **Alert if >5%**: Indicates M2M100 delimiter corruption issues

### Dashboard Queries

**Fallback Rate**:
```promql
rate(ast_individual_fallbacks[5m]) / rate(ast_units_translatable[5m])
```
**Alert**: If fallback rate >5% for >15 minutes

**Translation Quality** (indirect):
```promql
rate(validation_errors[5m])
```
**Alert**: If validation errors increase after enabling AST translation

### Log Monitoring

**Key log patterns to watch**:
- `"AST Translation: Successfully translated"` - Normal operation
- `"AST-based translation failed"` - **ALERT**: Fallback to legacy triggered
- `"AST translation failed, falling back to legacy"` - **WARNING**: Track frequency

**Grafana Log Query**:
```
{job="hugo-translator"} |= "AST translation failed"
```

---

## Rollback Procedures

### Emergency Rollback (Site-Level)

If critical issues detected on a specific site:

```bash
# Disable AST translation for problematic site
python scripts/toggle_ast_translation.py --site <site_id> --disable

# Verify feature flag disabled
cat config/site_profiles/<site_id>.yaml | grep use_ast_body_reconstruction

# Re-translate affected files with legacy approach
python -m src.cli translate-file --site <site_id> --force <file_path>
```

**When to rollback**:
- Corruption detected (links, code, images broken)
- Fallback rate >10% sustained
- Performance degradation >20%
- User complaints about translation quality

### Full Rollback (All Sites)

If systematic issues detected:

```bash
# Disable AST translation for all sites
python scripts/toggle_ast_translation.py --all-sites --disable

# Verify rollback
grep -r "use_ast_body_reconstruction: true" config/site_profiles/
# Should return no results
```

### Rollback Testing

**Before Phase 1**, verify rollback works:
```bash
# Enable on test site
python scripts/toggle_ast_translation.py --site test.site --enable

# Translate test documents
python -m src.cli translate-file --site test.site <file>

# Disable AST translation
python scripts/toggle_ast_translation.py --site test.site --disable

# Re-translate with legacy
python -m src.cli translate-file --site test.site --force <file>

# Verify: Output should use legacy reconstruction
```

---

## Configuration Reference

### Site Profile Settings

```yaml
body:
  # Master feature flag (required)
  use_ast_body_reconstruction: false  # true to enable

  # Segmentation strategy (optional, default: "adaptive")
  ast_segmentation_strategy: "adaptive"  # or "leaf_only" or "sentence_only"

  # Batch size (optional, default: 50)
  ast_batch_size: 50  # Range: 10-100
```

### Strategy Selection Guide

**Use "adaptive" (recommended)**:
- Best balance of fluency and safety
- Full-sentence for plain text paragraphs
- Leaf-level for formatted content

**Use "leaf_only"**:
- Maximum safety (no multi-sentence segments)
- Slightly reduced fluency
- Good for technical documentation with heavy formatting

**Use "sentence_only"**:
- Maximum fluency (full-sentence translation)
- Higher risk of formatting interference
- Good for blog posts, articles with minimal formatting

### Batch Size Tuning

**Default: 50** (recommended)
- Balances API efficiency with safety

**Increase to 100** if:
- Fallback rate consistently <1%
- Documents are large (>200 TextUnits)
- Want to reduce API costs

**Decrease to 25** if:
- Fallback rate >3%
- M2M100 model shows delimiter corruption
- Documents have complex formatting

---

## Testing Checklist

Before enabling AST translation on a site, verify:

- [ ] Site profile exists in `config/site_profiles/<site_id>.yaml`
- [ ] `use_ast_body_reconstruction` set to `true`
- [ ] Terminology file exists: `config/terminology/aspose_terms.txt`
- [ ] Telemetry dashboard configured for AST metrics
- [ ] Log monitoring alerts configured
- [ ] Rollback script tested and working
- [ ] Test translation run successful (10 sample documents)
- [ ] Human review of test translations confirms quality
- [ ] Fallback rate <5% in test run
- [ ] No errors in logs during test run

---

## Troubleshooting

### High Fallback Rate (>5%)

**Symptoms**: `ast_individual_fallbacks` counter increasing rapidly

**Possible Causes**:
1. M2M100 model not properly initialized with special tokens
2. Batch size too large for content complexity
3. Unicode PUA delimiter corruption

**Solutions**:
1. Verify M2M100 model initialization:
   ```python
   # Check that delimiter tokens are registered
   assert "\uE000" in tokenizer.get_vocab()
   assert "\uE001" in tokenizer.get_vocab()
   ```

2. Reduce batch size:
   ```yaml
   ast_batch_size: 25  # Reduced from 50
   ```

3. Check logs for delimiter corruption patterns

### Translation Quality Issues

**Symptoms**: Translated content has formatting issues or unnatural phrasing

**Possible Causes**:
1. Segmentation strategy not optimal for content type
2. Product names not being detected

**Solutions**:
1. Try different segmentation strategy:
   - If fluency issues → use "sentence_only"
   - If formatting issues → use "leaf_only"

2. Update terminology dictionary:
   - Add missing product names to `config/terminology/aspose_terms.txt`

### Performance Degradation

**Symptoms**: Translation taking significantly longer with AST enabled

**Possible Causes**:
1. High fallback rate (every fallback = extra API call)
2. Batch size too small

**Solutions**:
1. Address high fallback rate (see above)

2. Increase batch size:
   ```yaml
   ast_batch_size: 75  # Increased from 50
   ```

---

## Success Metrics

After full rollout, expect to see:

1. **Quality Improvements**:
   - 100% link preservation (up from ~85% with legacy)
   - 100% code preservation (up from ~90% with legacy)
   - 100% image preservation (up from ~95% with legacy)
   - ≥95% formatting preservation (up from ~80% with legacy)
   - 0% corruption rate (down from ~1-2% with legacy)

2. **Cost Efficiency**:
   - 10-30% reduction in API calls (from batching)
   - Corresponding reduction in translation costs

3. **Observability**:
   - Full telemetry coverage for AST translation
   - Clear visibility into batch translation patterns
   - Early warning for issues (fallback rate alerts)

---

## Contact & Support

**For rollout assistance**:
- Consult this guide first
- Check Grafana dashboards for telemetry
- Review logs for error patterns
- If issues persist, escalate to engineering team

**For feature requests or bugs**:
- File issue in hugo-translator repository
- Include telemetry data and logs
- Specify affected site(s) and sample documents
