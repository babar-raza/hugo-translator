# LMDB Test Conventions

## Why this matters

On Windows, `lmdb.open(map_size=N)` **immediately pre-allocates** `data.mdb` at `N` bytes. The production default `max_size_mb=1536` creates a **1.5 GB file per test instance**. Without explicit small sizes, a test run can waste tens of GB in `%TEMP%`.

## Rules

1. **Every `L2PersistentTM()` call in tests MUST include `max_size_mb`.**
   Use `max_size_mb=20` (or `max_size_mb=10` where neighbouring calls use 10).

2. **If a test genuinely needs >100 MB**, add a justification comment on the line above (or up to 3 lines above):
   ```python
   # LMDB_MAX_SIZE_JUSTIFIED: capacity stress test; expected data: 150 MB; owner: tm
   tm = L2PersistentTM(db, max_size_mb=200)
   ```

3. **Use `TEST_L2_MAX_SIZE_MB` from conftest** where convenient:
   ```python
   from tests.conftest import TEST_L2_MAX_SIZE_MB
   tm = L2PersistentTM(db_path, max_size_mb=TEST_L2_MAX_SIZE_MB)
   ```

4. **Do not modify `src/tm/l2_persistent.py` defaults.** The 1536 MB default is correct for production.

## CI Scanner

The AST-based scanner detects violations automatically:

```bash
python scripts/ci/check_lmdb_test_map_size.py tests/
```

- Exit 0 = all compliant
- Exit 1 = violations found (prints file:line: reason)

The scanner checks:
- Missing `max_size_mb` keyword → violation
- `max_size_mb` > 100 without `LMDB_MAX_SIZE_JUSTIFIED` comment → violation
- Strings and comments containing `L2PersistentTM` are ignored (no false positives)

## Cleanup

### Per-test (automatic)
The `_cleanup_test_lmdb` autouse fixture in `tests/conftest.py` cleans LMDB directories in `tmp_path` after each test on Windows.

### Orphaned temp files
```bash
# Preview what would be deleted
python scripts/tm/cleanup_orphaned_lmdb_temp.py --dry-run

# Actually delete (only after reviewing dry-run output)
python scripts/tm/cleanup_orphaned_lmdb_temp.py --apply
```

### Production store and legacy compatibility directory

The only active production L2 store is `data/tm/l2.lmdb`.  The sibling
`data/tm/l2_lmdb` is inactive legacy/test-compatibility data: it is neither
read nor written by normal campaign operation. Do not delete or migrate it as
part of a campaign. Runtime split-write diagnostics intentionally ignore that
one classified inactive directory, but still warn (or fail in strict mode) for
any other unexpected `l2*` sibling.

### Historical migration utility
```bash
# Historical utility only; do not run for the classified inactive l2_lmdb store
python scripts/migrate_l2_lmdb.py --dry-run

# Apply (requires workers stopped)
python scripts/migrate_l2_lmdb.py --apply
```
