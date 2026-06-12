# AST Batch Translation Fix Rollback Procedure

**Last Updated:** 2025-12-19
**Version:** 1.0
**Status:** Active

## Overview

This document describes the rollback procedure for AST batch translation fixes (AST-FIX-01 through AST-FIX-06 and SR-01 through SR-07).

If issues are encountered with the AST batch translation system in production, this procedure will safely revert to the traditional segment-by-segment translation method.

## When to Rollback

Execute rollback if ANY of these conditions occur:

### Critical Issues (Immediate Rollback)
- **Delimiter corruption rate > 10%** - Batch delimiters failing to preserve
- **Translation failures > 5%** - Systematic translation errors
- **Mixed-language output** - Translations containing source language text
- **Process hangs** - Translation pipeline not completing
- **Data loss** - Content missing from translated output

### Warning Signs (Monitor, Consider Rollback)
- **Fallback rate > 20%** - High percentage of batches falling back to individual translation
- **Translation quality degradation** - User reports of poor translation quality
- **Performance regression** - Translation slower than baseline
- **Memory issues** - Excessive memory consumption

## Rollback Impact

**What Changes:**
- Switches from AST-based batch translation back to traditional segment-by-segment translation
- Batch translation disabled, all units translated individually
- Language purity checks still active (sentence-level validator)

**What Stays the Same:**
- Parsing (HugoParser still used)
- Frontmatter handling
- Post-translation validation
- Translation Memory
- All other pipeline components

**Performance Impact:**
- **Speed:** ~30-50% slower translation (individual vs batch)
- **Quality:** No change (traditional method is proven baseline)
- **Reliability:** Increases (proven stable method)

## Rollback Procedure

### Step 1: Disable AST Body Reconstruction

**File:** [config/site_profiles/kb.aspose.net.yaml](../../config/site_profiles/kb.aspose.net.yaml)

**Change:**
```yaml
# BEFORE (AST translation enabled)
use_ast_body_reconstruction: true

# AFTER (rollback to traditional)
use_ast_body_reconstruction: false
```

**Location:** Line ~118

**How to Apply:**
```bash
# 1. Open config file
nano config/site_profiles/kb.aspose.net.yaml

# 2. Find use_ast_body_reconstruction setting
# 3. Change from true to false
# 4. Save file

# 5. Restart translation service (if applicable)
# No code deployment needed - config change takes effect immediately
```

### Step 2: Verify Rollback

**Verify config change:**
```bash
# Check current setting
grep "use_ast_body_reconstruction" config/site_profiles/kb.aspose.net.yaml
```

Expected output:
```yaml
use_ast_body_reconstruction: false  # Disabled for rollback
```

**Run smoke test:**
```bash
# Test that traditional translation still works
python scripts/smoke/smoke_test_ast_fixes.py
```

Expected result: All tests should pass (module imports, traditional translation path)

### Step 3: Monitor

After rollback, monitor for **1 hour** to confirm stability:

**Metrics to Watch:**
- Translation success rate (should be >99%)
- Translation time (baseline: segment-by-segment timing)
- Memory usage (should stabilize)
- Error logs (should be minimal)
- User reports (should decrease)

**Grafana Dashboard:**

> **Note:** The Grafana dashboard and metrics mentioned below may not exist in your environment yet. If they are not available, monitor via logs and system metrics instead. See Appendix B for guidance on setting up these metrics.

```
Translation Engine > AST Translation Metrics
- Check "Translation Method" = "traditional" (not "ast")
- Monitor "Translation Success Rate"
- Monitor "Average Translation Time"
```

**Log Validation:**
```bash
# Check for AST translation being disabled
grep "AST body reconstruction: disabled" logs/translation.log

# Verify no batch translation attempts
grep "batch_translate_units" logs/translation.log
# Should return no results (or very few from before rollback)
```

### Step 4: Document Incident

Create incident report with:
1. **Time of rollback**
2. **Triggering issue** (which condition from "When to Rollback" section)
3. **Metrics at time of rollback**
4. **Verification results**
5. **Next steps** (investigation, permanent fix, etc.)

**Template:**
```markdown
# AST Translation Rollback Incident

**Date:** YYYY-MM-DD HH:MM
**Executed By:** [Name]
**Reason:** [Critical issue description]

## Triggering Metrics
- Delimiter corruption rate: X%
- Fallback rate: Y%
- Translation failures: Z%

## Rollback Actions
1. Changed use_ast_body_reconstruction: false
2. Verified config change
3. Smoke test: PASS/FAIL
4. Monitoring period: 1 hour

## Post-Rollback Metrics
- Translation success rate: X%
- Translation time: Y seconds avg
- Memory usage: Z MB avg

## Next Steps
[ ] Investigate root cause
[ ] Create fix plan
[ ] Test fix in staging
[ ] Schedule re-deployment

## Resolution
[To be filled after fix]
```

## Re-enabling AST Translation

After fixing the issue:

### Prerequisites
1. Root cause identified and fixed
2. Fix tested in staging environment
3. All unit tests passing
4. All integration tests passing
5. Smoke test passing
6. Manual validation with real files

### Re-enable Procedure

**Step 1: Update Code**
```bash
# Deploy fixed code
git pull origin main
# Restart services as needed
```

**Step 2: Enable AST Translation**

**File:** [config/site_profiles/kb.aspose.net.yaml](../../config/site_profiles/kb.aspose.net.yaml)

```yaml
# Change back to AST translation
use_ast_body_reconstruction: true
```

**Step 3: Gradual Rollout**

Don't enable for all files immediately. Use phased approach:

**Phase 1: Single File (1 hour)**
```bash
# Test with single file
translate-hugo \
  --input tests/fixtures/ast_integration_test.md \
  --output /tmp/test_output.md \
  --source-lang en \
  --target-lang de \
  --site-profile kb.aspose.net

# Verify:
# - No delimiter corruption
# - Language purity 100%
# - Structure preserved
```

**Phase 2: Small Batch (4 hours)**
```bash
# Test with ~10 files
# Monitor metrics closely
```

**Phase 3: Full Rollout (24 hours)**
```bash
# Enable for all files
# Continuous monitoring
```

**Step 4: Monitor Success Criteria**

**After 24 hours, verify:**
- Delimiter corruption rate < 5%
- Fallback rate < 10%
- Translation success rate > 99%
- No mixed-language output
- Performance maintained or improved

## Emergency Contact

If rollback fails or causes additional issues:

1. **Escalate to:** Project Tech Lead
2. **Slack Channel:** #translation-engine
3. **On-Call:** [rotation schedule]
4. **Fallback:** Disable entire translation pipeline, manual translation only

## Testing This Procedure

**Dry Run (Staging):**
```bash
# 1. Enable AST translation in staging
# 2. Execute rollback procedure
# 3. Verify traditional translation works
# 4. Re-enable AST translation
# 5. Verify AST translation works
```

**Frequency:** Quarterly, or after major changes to AST translation system

## Appendix A: Config File Reference

**Full path:** `config/site_profiles/kb.aspose.net.yaml`

**Relevant settings:**
```yaml
# AST Translation Settings (lines 115-125)
use_ast_body_reconstruction: true  # Main toggle

# Batch Translation Settings
ast_translation_max_units_per_batch: 20
ast_translation_max_tokens_per_batch: 512
ast_translation_token_safety_margin: 0.5
```

## Appendix B: Monitoring Queries

> **Important:** The metrics and queries below assume a Prometheus/Grafana monitoring setup. These metrics may not exist in your environment yet. If they are not available:
> - Monitor rollback success via application logs and system metrics
> - Set up metrics by instrumenting the translation engine code with prometheus_client
> - Key metrics to implement: `translation_method_total`, `batch_translation_success_total`, `batch_translation_attempts_total`, `delimiter_corruption_total`
> - See the observability documentation for full instrumentation guidance

**Grafana Queries:**

**Translation Method Distribution:**
```promql
sum(rate(translation_method_total{method="ast"}[5m]))
sum(rate(translation_method_total{method="traditional"}[5m]))
```

**Batch Success Rate:**
```promql
sum(rate(batch_translation_success_total[5m])) /
sum(rate(batch_translation_attempts_total[5m]))
```

**Delimiter Corruption Rate:**
```promql
sum(rate(delimiter_corruption_total[5m])) /
sum(rate(batch_translation_attempts_total[5m]))
```

## Appendix C: Verification Checklist

**Post-Rollback Verification:**
```
[ ] Config file updated (use_ast_body_reconstruction: false)
[ ] Smoke test passing
[ ] Traditional translation working
[ ] No AST batch translation in logs
[ ] Translation success rate >99%
[ ] Monitoring dashboards show traditional method
[ ] Incident documented
[ ] Team notified

**Post-Re-enable Verification:**
[ ] Code deployed
[ ] Config file updated (use_ast_body_reconstruction: true)
[ ] Smoke test passing
[ ] Single file test successful
[ ] Small batch test successful
[ ] Metrics within acceptable ranges
[ ] No delimiter corruption
[ ] No mixed-language output
[ ] Team notified of successful re-enablement
```

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-12-19 | Claude | Initial rollback procedure (VLD-07) |

## Related Documents

- [AST_FIX_IMPLEMENTATION_SUMMARY.md](../../reports/AST_FIX_IMPLEMENTATION_SUMMARY.md) - Implementation details
- [AST_FIX_VALIDATION.md](../../plans/healing/AST_FIX_VALIDATION.md) - Validation plan
- [AST_FIX_CORRECTIONS.md](../../plans/healing/AST_FIX_CORRECTIONS.md) - Bug fixes plan
- [TROUBLESHOOTING.md](../TROUBLESHOOTING.md) - General troubleshooting guide
