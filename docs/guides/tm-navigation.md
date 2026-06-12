# Translation Memory Documentation Map

**Version:** 1.0
**Last Updated:** 2025-12-24
**Purpose:** Visual guide to TM documentation hierarchy and usage

## Overview

This map helps you navigate the Translation Memory documentation by showing the complete documentation structure and guiding you to the right resource for your needs.

## Documentation Structure

```text
Translation Memory Documentation
│
├── 📖 Getting Started (guides/)
│   ├── tm-getting-started.md          ← START HERE if you're new to TM
│   ├── tm-override-modes.md           ← Control cache behavior (bypass, refresh, validate)
│   └── tm-statistics-monitoring-guide.md  ← Monitor hit rates and performance
│
├── 🛠️ Operations (operations/)
│   ├── tm-maintenance.md              ← Daily/weekly maintenance, integrity checks
│   ├── tm-troubleshooting.md          ← Diagnose corruption and performance issues
│   └── tm-performance-tuning.md       ← Optimize L1/L2/L3 performance
│
├── 🏗️ Architecture (architecture/)
│   └── translation-memory.md          ← Deep dive: L1/L2/L3 design, ACID, crash safety
│
└── 💻 Reference (reference/)
    └── tm-api.md                      ← Programmatic API usage
```

## Quick Decision Tree

### I want to...

**Understand what TM is and how it works**
- 📄 Start: [TM Getting Started](tm-getting-started.md)
- 📄 Next: [TM Architecture](../architecture/translation-memory.md) (optional deep dive)

**Monitor TM performance**
- 📄 Start: [TM Statistics & Monitoring Guide](tm-statistics-monitoring-guide.md)
- 📄 Reference: [TM Maintenance](../operations/tm-maintenance.md) (scheduled checks)

**Control cache behavior (bypass, refresh, validate)**
- 📄 Guide: [TM Override Modes](tm-override-modes.md)
- 💡 Use Case: Content updates, testing new models, cache validation

**Maintain TM in production**
- 📄 Runbook: [TM Maintenance](../operations/tm-maintenance.md)
- 🔧 Tasks: Integrity checks, backups, compaction, monitoring setup

**Diagnose TM problems**
- 📄 Guide: [TM Troubleshooting](../operations/tm-troubleshooting.md)
- 💡 Issues: Corruption, low hit rates, slow lookups, disk space

**Optimize TM performance**
- 📄 Guide: [TM Performance Tuning](../operations/tm-performance-tuning.md)
- 🎯 Focus: L1 size tuning, L2 optimization, L3 semantic search configuration

**Use TM programmatically**
- 📄 API: [TM API Reference](../reference/tm-api.md)
- 💻 For: Integration, custom scripts, CI/CD automation

**Understand TM internals**
- 📄 Architecture: [Translation Memory Architecture](../architecture/translation-memory.md)
- 🔬 Topics: LMDB, FAISS, ACID guarantees, crash recovery, backup strategy

## By Persona

### 👤 Content Translator (User)

**Primary Docs:**
1. [TM Getting Started](tm-getting-started.md) - What is TM and why it matters
2. [TM Override Modes](tm-override-modes.md) - Control when to use cached translations

**Typical Tasks:**
- Check if TM is working
- Understand hit rates and cost savings
- Force fresh translation when content changes
- Validate cached translations

**Quick Commands:**
```powershell
# Check TM status (Windows)
venv\Scripts\python.exe -c "from src.tm import create_translation_memory; from pathlib import Path; print(create_translation_memory(Path('data/tm')).get_stats())"

# Translate with fresh cache (bypass mode)
venv\Scripts\python.exe scripts/content/batch_translate.py --input ./content --output ./output --site products.aspose.net --override-mode bypass
```

### 🛠️ Site Operator (Ops/SRE)

**Primary Docs:**
1. [TM Maintenance](../operations/tm-maintenance.md) - Daily/weekly runbook
2. [TM Statistics & Monitoring](tm-statistics-monitoring-guide.md) - Metrics and alerts
3. [TM Troubleshooting](../operations/tm-troubleshooting.md) - Problem diagnosis
4. [TM Performance Tuning](../operations/tm-performance-tuning.md) - Optimization

**Typical Tasks:**
- Run integrity checks (weekly)
- Create backups (daily)
- Monitor hit rates and health
- Diagnose corruption or performance degradation
- Optimize cache settings for workload

**Quick Commands:**
```powershell
# Integrity check (Windows)
venv\Scripts\python.exe -c "from src.tm.integrity import check_cache_integrity; from pathlib import Path; report = check_cache_integrity(Path('data/tm/l2_lmdb')); print(f'Health: {report.health_percentage:.1f}%')"

# Create backup (Windows)
venv\Scripts\python.exe -c "from src.tm.backup import create_tm_backup; from pathlib import Path; backup_path = create_tm_backup(Path('data/tm'), Path('backups')); print(f'Backup: {backup_path}')"
```

### 💻 System Contributor (Engineer)

**Primary Docs:**
1. [TM Architecture](../architecture/translation-memory.md) - Design and internals
2. [TM API Reference](../reference/tm-api.md) - Programmatic usage

**Typical Tasks:**
- Understand L1/L2/L3 layer design
- Integrate TM into custom workflows
- Extend TM functionality
- Debug TM issues at code level
- Review ACID guarantees and crash safety

**Quick Code:**
```python
from src.tm import create_translation_memory
from pathlib import Path

# Initialize TM
tm = create_translation_memory(Path("data/tm"))

# Lookup with semantic fallback
result = tm.lookup(
    site_id="products.aspose.net",
    src_lang="en",
    tgt_lang="fr",
    text="Welcome to our website",
    use_semantic=True,
    semantic_threshold=0.85
)

if result.hit:
    print(f"Found: {result.translation} (source: {result.source})")
```

## Documentation Depth Levels

### Level 1: Essentials (10 minutes)
- [TM Getting Started](tm-getting-started.md)

**You'll learn:**
- What TM is and how it saves time/cost
- How to check TM status
- Basic hit rate interpretation

### Level 2: Operations (30 minutes)
- [TM Statistics & Monitoring](tm-statistics-monitoring-guide.md)
- [TM Override Modes](tm-override-modes.md)
- [TM Maintenance](../operations/tm-maintenance.md)

**You'll learn:**
- Monitor TM health and performance
- Control cache behavior for different scenarios
- Run basic maintenance tasks

### Level 3: Advanced Operations (2 hours)
- [TM Troubleshooting](../operations/tm-troubleshooting.md)
- [TM Performance Tuning](../operations/tm-performance-tuning.md)

**You'll learn:**
- Diagnose and fix corruption
- Optimize for specific workloads
- Benchmark and measure improvements

### Level 4: Expert (4+ hours)
- [TM Architecture](../architecture/translation-memory.md)
- [TM API Reference](../reference/tm-api.md)

**You'll learn:**
- Deep understanding of L1/L2/L3 internals
- ACID guarantees and crash recovery
- Programmatic integration
- Code-level debugging

## Common Workflows

### Workflow 1: "TM seems broken" (Troubleshooting)

1. **Check health**: [TM Maintenance](../operations/tm-maintenance.md) → Run integrity check
2. **Review metrics**: [TM Statistics Guide](tm-statistics-monitoring-guide.md) → Check hit rates
3. **Diagnose**: [TM Troubleshooting](../operations/tm-troubleshooting.md) → Find root cause
4. **Fix**: Follow repair procedures or restore from backup
5. **Verify**: Re-run integrity check and monitor hit rates

### Workflow 2: "Content changed, need fresh translations" (Cache Control)

1. **Understand options**: [TM Override Modes](tm-override-modes.md)
2. **Choose mode**:
   - `bypass`: Fresh translation, don't update cache
   - `refresh`: Fresh translation, update cache
3. **Apply filters**: Target specific languages, keys, or patterns
4. **Execute**: Run translation with override mode
5. **Verify**: Check that updated content is properly translated

### Workflow 3: "TM is too slow" (Performance)

1. **Baseline**: [TM Statistics Guide](tm-statistics-monitoring-guide.md) → Capture current metrics
2. **Benchmark**: [TM Performance Tuning](../operations/tm-performance-tuning.md) → Run benchmarks
3. **Tune**: Adjust L1 size, L2 settings, L3 semantic search
4. **Measure**: Re-run benchmarks and compare
5. **Monitor**: Track improvements over time

### Workflow 4: "Implementing TM integration" (Development)

1. **Learn architecture**: [TM Architecture](../architecture/translation-memory.md)
2. **Review API**: [TM API Reference](../reference/tm-api.md)
3. **Write code**: Use TranslationMemory class or individual layers
4. **Test**: Verify lookups, updates, error handling
5. **Monitor**: Add instrumentation for hit rates and performance

## Quick Reference Matrix

| Task | User | Operator | Developer |
|------|------|----------|-----------|
| **Check TM status** | [Getting Started](tm-getting-started.md) | [Monitoring Guide](tm-statistics-monitoring-guide.md) | [API Reference](../reference/tm-api.md) |
| **Control cache** | [Override Modes](tm-override-modes.md) | [Override Modes](tm-override-modes.md) | [API Reference](../reference/tm-api.md) |
| **Run maintenance** | N/A | [Maintenance](../operations/tm-maintenance.md) | [API Reference](../reference/tm-api.md) |
| **Fix problems** | [Getting Started](tm-getting-started.md) → FAQ | [Troubleshooting](../operations/tm-troubleshooting.md) | [Architecture](../architecture/translation-memory.md) |
| **Optimize performance** | N/A | [Performance Tuning](../operations/tm-performance-tuning.md) | [Architecture](../architecture/translation-memory.md) |
| **Understand internals** | [Getting Started](tm-getting-started.md) | [Architecture](../architecture/translation-memory.md) | [Architecture](../architecture/translation-memory.md) |

## Document Relationships

### Cross-References

**From [TM Getting Started](tm-getting-started.md):**
- → [TM Architecture](../architecture/translation-memory.md) for technical deep dive
- → [TM Maintenance](../operations/tm-maintenance.md) for operator tasks
- → [TM Override Modes](tm-override-modes.md) for cache control

**From [TM Maintenance](../operations/tm-maintenance.md):**
- → [TM Troubleshooting](../operations/tm-troubleshooting.md) for problem diagnosis
- → [TM Statistics Guide](tm-statistics-monitoring-guide.md) for metrics
- → [TM Performance Tuning](../operations/tm-performance-tuning.md) for optimization

**From [TM Architecture](../architecture/translation-memory.md):**
- → [TM API Reference](../reference/tm-api.md) for programmatic usage
- → [TM Maintenance](../operations/tm-maintenance.md) for ACID/backup details

**From [TM Troubleshooting](../operations/tm-troubleshooting.md):**
- → [TM Maintenance](../operations/tm-maintenance.md) for repair procedures
- → [TM Performance Tuning](../operations/tm-performance-tuning.md) for optimization
- → [TM Architecture](../architecture/translation-memory.md) for root cause analysis

## Suggested Reading Paths

### Path 1: User Journey
1. [TM Getting Started](tm-getting-started.md) (15 min)
2. [TM Override Modes](tm-override-modes.md) (20 min)
3. [TM Statistics Guide](tm-statistics-monitoring-guide.md) (15 min)
4. **Total: 50 minutes**

### Path 2: Operator Journey
1. [TM Getting Started](tm-getting-started.md) (15 min)
2. [TM Maintenance](../operations/tm-maintenance.md) (45 min)
3. [TM Statistics Guide](tm-statistics-monitoring-guide.md) (30 min)
4. [TM Troubleshooting](../operations/tm-troubleshooting.md) (60 min)
5. [TM Performance Tuning](../operations/tm-performance-tuning.md) (90 min)
6. **Total: 4 hours**

### Path 3: Developer Journey
1. [TM Getting Started](tm-getting-started.md) (15 min)
2. [TM Architecture](../architecture/translation-memory.md) (2 hours)
3. [TM API Reference](../reference/tm-api.md) (1 hour)
4. [TM Maintenance](../operations/tm-maintenance.md) (30 min, focus on backup/integrity APIs)
5. **Total: 4 hours**

## Updates and Maintenance

### Keeping Documentation Current

**When to Update Documentation:**

1. **Code Changes**
   - API modifications → Update [TM API Reference](../reference/tm-api.md) and [Architecture](../architecture/translation-memory.md)
   - New features → Update [Getting Started](tm-getting-started.md) and relevant operation docs
   - Performance improvements → Update [Performance Tuning](../operations/tm-performance-tuning.md)
   - Bug fixes → Update [Troubleshooting](../operations/tm-troubleshooting.md)

2. **Incidents Occur**
   - Production issues → Add to [Troubleshooting](../operations/tm-troubleshooting.md) as case studies
   - Data corruption events → Update [Maintenance](../operations/tm-maintenance.md) recovery procedures
   - Performance degradation → Document in [Performance Tuning](../operations/tm-performance-tuning.md)

3. **Scheduled Reviews**
   - **Monthly**: Review documentation analytics, identify gaps from support tickets
   - **Quarterly**: Full documentation review (see checklist below)
   - **Annually**: Major version updates, architecture review

### Ownership Model

**By Persona:**
- **Getting Started & User Guides** → User-facing documentation team
  - [TM Getting Started](tm-getting-started.md)
  - [TM Override Modes](tm-override-modes.md)

- **Operations Runbooks** → SRE/DevOps team
  - [TM Maintenance](../operations/tm-maintenance.md)
  - [TM Troubleshooting](../operations/tm-troubleshooting.md)
  - [TM Performance Tuning](../operations/tm-performance-tuning.md)
  - [TM Statistics & Monitoring](tm-statistics-monitoring-guide.md)

- **Architecture & API** → Engineering team
  - [TM Architecture](../architecture/translation-memory.md)
  - [TM API Reference](../reference/tm-api.md)

**Collaboration:**
- All teams contribute to troubleshooting and maintenance documentation
- Engineers provide technical accuracy review for all docs
- Operators provide real-world usage feedback

### Quality Checks

**Pre-Commit Checks:**
```powershell
# Verify all code examples work (Windows)
venv\Scripts\python.exe scripts\verify_tm_docs.py

# Review documentation quality
venv\Scripts\python.exe scripts\review_tm_docs.py
```

**What Gets Verified:**
- ✅ All 180+ commands execute successfully
- ✅ Cross-references resolve correctly
- ✅ Code blocks have proper language labels
- ✅ Heading hierarchy is valid
- ✅ Version headers and dates are current

**Quality Gates:**
- **Critical**: Zero broken links, all commands verified working
- **High**: Code blocks labeled, consistent terminology
- **Minor**: Heading hierarchy, style consistency

**Review Process:**
1. Author updates documentation
2. Run automated verification (`verify_tm_docs.py`)
3. Run quality review (`review_tm_docs.py`)
4. Fix critical issues (broken links, failed commands)
5. Document or fix high-priority issues
6. Peer review by relevant team
7. Merge and deploy

### Known Style Variations

**Intentional Variations (Not Errors):**

These patterns appear in documentation by design for readability:

1. **TM Layer References**
   - "L1 Cache" (formal, first mention)
   - "L1" (shorthand in technical contexts)
   - "Level 1 Cache" (educational contexts)
   - **Rationale**: Varies by audience and context for better comprehension

2. **Code Block Labels**
   - Some blocks use `text` for output examples
   - Some blocks use `bash` vs `powershell` based on platform
   - **Rationale**: Accurate representation of content type

3. **Heading Depth**
   - Getting Started uses flatter hierarchy (more ##)
   - Architecture uses deeper nesting (###, ####)
   - **Rationale**: Matches content complexity and reading flow

**These are NOT bugs** - they're intentional choices for accessibility and readability.

**When in doubt**: Run quality checks and discuss with document owner before "fixing" variations.

### Quarterly Review Checklist

**Documentation Accuracy:**
- [ ] All code examples execute successfully (`verify_tm_docs.py`)
- [ ] Cross-references resolve correctly (`review_tm_docs.py`)
- [ ] Version numbers and dates updated
- [ ] Screenshots and diagrams current (if any)

**Content Completeness:**
- [ ] Recent features documented
- [ ] Known issues from support tickets addressed
- [ ] Troubleshooting expanded with real incidents
- [ ] Performance benchmarks updated

**Quality Standards:**
- [ ] Zero broken links
- [ ] All commands verified working
- [ ] Consistent terminology within each doc
- [ ] Proper heading hierarchy

**User Feedback:**
- [ ] Review support tickets for documentation gaps
- [ ] Analyze documentation usage analytics
- [ ] Incorporate operator/user suggestions
- [ ] Update FAQs based on common questions

---

**Next Steps:**
- New to TM? → [Start here](tm-getting-started.md)
- Need to maintain TM? → [Maintenance runbook](../operations/tm-maintenance.md)
- Want to understand internals? → [Architecture guide](../architecture/translation-memory.md)
- Building integrations? → [API reference](../reference/tm-api.md)
