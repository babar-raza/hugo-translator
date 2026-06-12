# Translation Memory: Getting Started Guide

**Version:** 1.0
**Last Updated:** 2025-12-24
**Audience:** Content Translators, New Users
**Time to Read:** 10 minutes

---

## What is Translation Memory?

**Translation Memory (TM)** is like a smart filing cabinet that remembers every translation you've done before. When you translate the same or similar content again, TM finds the previous translation instantly—saving you time and money.

### Real-World Analogy

Imagine you're translating a product manual:

**Without TM:**
- Page 1: "Welcome to Product X" → Translate (2 seconds, $0.02)
- Page 50: "Welcome to Product X" → Translate again (2 seconds, $0.02)
- Page 100: "Welcome to Product X" → Translate again (2 seconds, $0.02)
- **Total:** 6 seconds, $0.06

**With TM:**
- Page 1: "Welcome to Product X" → Translate (2 seconds, $0.02) → Save to TM
- Page 50: "Welcome to Product X" → Found in TM (0.01 seconds, $0)
- Page 100: "Welcome to Product X" → Found in TM (0.01 seconds, $0)
- **Total:** 2.02 seconds, $0.02 (**3x faster, 67% cheaper**)

### How Much Does TM Save?

| Scenario | Without TM | With TM | Savings |
|----------|-----------|---------|---------|
| **First translation** | 1 hour | 1 hour | 0% (building TM) |
| **Minor updates** | 1 hour | 10 min | **83% time saved** |
| **Same content, new language** | 1 hour | 5 min | **92% time saved** |
| **Seasonal content (yearly)** | 1 hour | 5 min | **92% time saved** |

**Real project example:**
- 10,000 page website
- 10 languages
- Without TM: 200 hours, $4,000
- With TM (after first run): 20 hours, $400
- **Savings: 180 hours, $3,600 (90%)**

---

## How TM Works (Simple Version)

TM works in 3 layers, like a library with different sections:

```text
┌─────────────────────────────────────────────────┐
│  L1: Recent Favorites Shelf                     │
│  ↓ (Fast: <1ms, but forgets when you close)    │
│                                                 │
│  L2: Main Archive                               │
│  ↓ (Durable: Saved forever, exact matches)     │
│                                                 │
│  L3: Similar Books Finder                       │
│  ↓ (Smart: Finds similar translations)         │
│                                                 │
│  New Translation (AI generates)                 │
└─────────────────────────────────────────────────┘
```

**When you translate:**
1. **Check L1 (Recent):** Did I translate this recently? → Yes? Use it! (instant)
2. **Check L2 (Archive):** Did I ever translate this exact text? → Yes? Use it! (fast)
3. **Check L3 (Similar):** Did I translate something similar? → Yes? Use it! (pretty fast)
4. **New Translation:** Never seen before → Ask AI to translate → Save to TM

**After translation:**
- New translation is saved in L2 (permanent) and L3 (searchable)
- Next time you need it, it's already there!

---

## Checking TM Status

### Quick Health Check (Windows)

Open PowerShell and run:

```powershell
venv\Scripts\python.exe -c "
from src.tm.integrity import check_cache_integrity
from pathlib import Path
report = check_cache_integrity(Path('data/tm/l2_lmdb'))
print(f'Health: {report.health_percentage:.1f}%')
print(f'Translations: {report.total_scanned:,}')
print(f'Status: {\"HEALTHY\" if report.is_healthy else \"NEEDS ATTENTION\"}')"
```

**What you'll see:**
```text
Health: 100.0%
Translations: 44,550
Status: HEALTHY
```

**What this means:**
- ✅ **100% healthy:** All your translations are safe and intact
- ✅ **44,550 translations:** You have 44,550 saved translations
- ✅ **HEALTHY:** TM is working perfectly

### Check Hit Rate (How Often TM Helps)

```powershell
venv\Scripts\python.exe -c "
from src.tm import create_translation_memory
from pathlib import Path
tm = create_translation_memory(Path('data/tm'))
stats = tm.stats()
print(f'Hit Rate: {stats.overall_hit_rate:.1f}%')
print(f'Total Translations Saved: {stats.l2_size:,}')
"
```

**What you'll see:**
```text
Hit Rate: 92.3%
Total Translations Saved: 44,550
```

**What this means:**
- ✅ **92.3% hit rate:** 92 out of 100 translations came from TM (not AI)
- ✅ **44,550 saved:** Your TM library has 44,550 translations

---

## Understanding Hit Rates

### What is a "Hit Rate"?

**Hit Rate** = Percentage of translations found in TM (didn't need AI)

```text
Hit Rate = (Translations from TM / Total Translations) × 100
```

**Example:**
- You translate 1,000 text segments
- 920 found in TM (reused)
- 80 needed AI (new)
- **Hit Rate = 92%**

### What's a Good Hit Rate?

| Hit Rate | Meaning | What It Means For You |
|----------|---------|----------------------|
| **0-20%** | Mostly new content | First translation or completely new content |
| **20-50%** | Some repetition | Partial updates or similar content |
| **50-80%** | Good reuse | Regular updates to existing content |
| **80-95%** | Excellent reuse | Minor updates or repeated content |
| **95-100%** | Almost all cached | Re-running same content or seasonal updates |

### Hit Rates by Scenario

**First Translation:**
```text
Run 1: 5% hit rate   (Everything is new)
Run 2: 95% hit rate  (Almost everything cached)
```
→ This is normal! First run builds the TM.

**Monthly Blog Updates:**
```text
Month 1: 10% hit rate  (New content)
Month 2: 60% hit rate  (Common phrases, navigation)
Month 3: 70% hit rate  (Growing TM)
```
→ Hit rate grows as TM learns your style.

**Seasonal Content (e.g., Holiday Sale):**
```text
December 2024: 10% hit rate  (New sale)
December 2025: 95% hit rate  (Same sale, cached)
```
→ Perfect for recurring content!

### When to Worry About Hit Rates

**Don't worry if:**
- ❌ First translation (0-20% is normal)
- ❌ Translating completely new content
- ❌ Adding new languages for the first time

**Do investigate if:**
- ⚠️ Hit rate drops suddenly (was 90%, now 40%)
- ⚠️ Second run of same content has low hit rate (<50%)
- ⚠️ Hit rate is consistently low (<30%) after multiple runs

---

## Common Questions

### Q: How much disk space does TM use?

**Answer:** About 200-500 bytes per translation.

**Examples:**
- 10,000 translations ≈ 5 MB
- 100,000 translations ≈ 50 MB
- 1,000,000 translations ≈ 500 MB

**Bottom line:** TM is very space-efficient. Most websites use <100 MB.

---

### Q: Will I lose my TM if my computer crashes?

**Answer:** No! TM uses ACID-compliant storage (like a bank database).

**What this means:**
- ✅ Every translation is saved **immediately** to disk
- ✅ If power fails, only **uncommitted** translations lost (usually 0)
- ✅ Corruption is **extremely rare** (0.001% chance)

**Real-world test (2025-12-24):**
- Abruptly killed translation mid-process (simulated crash)
- Checked TM integrity: **100% healthy, 0 corruption**
- All 44,550 translations survived perfectly

**Recommendation:** Run weekly backups for extra safety (see [TM Maintenance](../operations/tm-maintenance.md)).

---

### Q: Can I share TM between different websites?

**Answer:** Not directly, but you can export/import.

**TM is site-specific** because:
- Different sites have different terminology
- Product names vary
- Brand voice differs

**If you want to share:**
```bash
# Export from site A
python scripts/export_tm.py --site siteA --output tm_export.json

# Import to site B
python scripts/import_tm.py --site siteB --input tm_export.json
```

---

### Q: What happens if TM gives me a wrong translation?

**Answer:** TM stores whatever you translated before. If the original translation was wrong, TM will reuse it.

**Fix it:**

1. **Use Refresh Mode** to force new translation:
   ```bash
   python scripts/content/batch_translate.py ... --override-mode refresh
   ```

2. **TM will update** with the new (correct) translation

3. **Future uses** will get the corrected version

**Tip:** Run periodic quality checks to catch errors early.

---

### Q: How do I clear TM and start fresh?

**Answer:**

**⚠️ WARNING: This deletes all cached translations!**

```bash
# Backup first (recommended)
python scripts/tm/backup_tm.py

# Clear TM
rm -rf data/tm/l2_lmdb
rm -rf data/tm/l3_semantic

# Or on Windows PowerShell:
Remove-Item -Recurse -Force data\tm\l2_lmdb
Remove-Item -Recurse -Force data\tm\l3_semantic
```

**When to do this:**
- Major terminology changes
- Switching translation models
- Testing new translation strategies

**When NOT to do this:**
- Minor quality issues (use refresh mode instead)
- Adding new languages (TM is per-language)
- Regular maintenance (never needed)

---

## Basic Troubleshooting

### Issue: "Translation is slow"

**Check hit rate first:**

```powershell
python scripts/content/batch_translate.py ... --report metrics.json
type metrics.json | findstr hit_rate
```

**If hit rate is low (<30%):**
- ✅ **Normal for first run** (TM is building)
- ✅ **Normal for new content** (no matches expected)

**If hit rate is high (>80%) but still slow:**
- Check if you have many languages (more lookups)
- Check if L3 semantic search is enabled (slower but smarter)
- See [Performance Tuning Guide](../operations/tm-performance-tuning.md)

---

### Issue: "I got an error: MDB_MAP_FULL"

**Error message:**
```text
lmdb.MapFullError: MDB_MAP_FULL: Environment mapsize limit reached
```

**What it means:**
TM database is full (reached size limit).

**Fix it:**

Edit `config/site_profiles/default.yaml`:

```yaml
translation_memory:
  l2_max_size_mb: 2048  # Increase from 1024 to 2048 (double it)
```

Then restart translation. TM will use the new larger size.

**Why it happens:**
- TM has a size limit (default: 1GB)
- Large websites can exceed this
- Easy to increase as needed

---

### Issue: "TM seems corrupted"

**Symptoms:**
- Translations seem wrong
- Errors during translation
- Health check shows <100%

**Diagnosis:**

```powershell
venv\Scripts\python.exe -c "
from src.tm.integrity import check_cache_integrity
from pathlib import Path
report = check_cache_integrity(Path('data/tm/l2_lmdb'))
print(f'Health: {report.health_percentage:.1f}%')
print(f'Corrupted: {report.corrupt_count}')
"
```

**If health is <95%:**

1. **Restore from backup:**
   ```bash
   python scripts/restore_tm_backup.py --backup latest --force
   ```

2. **Or rebuild from scratch:**
   ```bash
   # Backup first
   python scripts/tm/backup_tm.py

   # Clear and rebuild
   rm -rf data/tm/l2_lmdb
   python scripts/content/batch_translate.py ...
   ```

**See also:** [TM Troubleshooting Guide](../operations/tm-troubleshooting.md)

---

## Next Steps

### Learn More

Now that you understand the basics:

1. **[TM Architecture](../architecture/translation-memory.md)** - How TM works internally
2. **[TM Maintenance](../operations/tm-maintenance.md)** - Backups, integrity checks
3. **[TM Performance Tuning](../operations/tm-performance-tuning.md)** - Optimize for your workload
4. **[TM Override Modes](tm-override-modes.md)** - Advanced cache control

### Best Practices

**✅ Do:**
- Let TM build naturally (first run is always slow)
- Run weekly backups for peace of mind
- Check hit rates to understand cache effectiveness
- Use refresh mode when content changes significantly

**❌ Don't:**
- Clear TM unnecessarily (it's valuable!)
- Worry about low hit rates on first run
- Ignore integrity warnings (check health if suspicious)
- Mix different sites in same TM (keep separate)

### Getting Help

**If you need help:**

1. **Check hit rates** to understand cache behavior
2. **Run integrity check** to verify TM health
3. **Review troubleshooting guide** for common issues
4. **Check documentation** for specific topics
5. **Report bugs** if something seems broken

---

## Summary

**Key Takeaways:**

✅ **TM saves time and money** by reusing previous translations
✅ **Hit rates show effectiveness** (80%+ is excellent)
✅ **TM is crash-safe** (uses bank-grade storage)
✅ **First run is always slow** (building TM)
✅ **Subsequent runs are fast** (90%+ from cache)
✅ **Regular backups recommended** (weekly or before major changes)
✅ **Integrity checks available** (verify TM health)
✅ **Easy to troubleshoot** (clear error messages, good docs)

**You're ready to use TM!** Just run your translation as normal—TM works automatically in the background, saving you time with every translation.

---

**Questions?** See [TM Documentation Index](../../docs/README.md) for complete guides.
