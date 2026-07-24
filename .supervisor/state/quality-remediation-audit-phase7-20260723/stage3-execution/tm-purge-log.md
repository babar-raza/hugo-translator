# TM Purge Log — TC-P7-13

## Backup (mandatory precondition, per plan)

- `scripts/tm/backup_tm.py --output backups/tm_pre_purge_quality_remediation_phase7_20260724.tar.gz --verbose`
- Result: `backups/tm_pre_purge_quality_remediation_phase7_20260724.tar.gz` (1.48 GB) + `.sha256` checksum file, both present on disk.

## Dry-run (pre-write sanity check)

- `python scripts/tm/purge_corrupted_tm_entries.py --detail-csv reports/audit/findings_detail.csv --issue-types double_period link_path_corrupted`
- Scope: 144 `(site_id, locale)` pairs actually flagged for `double_period`/`link_path_corrupted` in `findings_detail.csv` — never a full-store scan.
- Result: 698,185 entries scanned, 10,780 corrupted candidates identified. Order of magnitude consistent with expectation (fixed-segment counts from TC-P7-04/05 in the low thousands, TM cache holding multiple historical variants per segment) — proceeded to `--write` per the dry-run sanity gate.

## Write (`--write`)

- Same scope (144 pairs), same predicate set.
- Result: 698,185 scanned, 10,780 matched, **10,780 deleted**. Zero mismatch between matched and deleted counts (every matched key was successfully removed).
- Fixed the `lmdb.MapFullError: mdb_del: MDB_MAP_FULL` crash encountered on the first write attempt by adding an explicit `map_size=8192 * 1024 * 1024` to `lmdb.open()` (the script's default open call had no `map_size`, unlike `L2PersistentTM`'s own 4096MB default) — re-ran cleanly after the fix.

## Post-write spot-check (mandatory before marking CLOSED)

- Re-ran the same dry-run scan immediately after the write.
- Result: 687,405 scanned (= 698,185 − 10,780, exact match confirming no entries were double-counted or missed), **0 corrupted candidates remaining**.
- Conclusion: the purge is complete and correct for its scoped predicate set. No `restore_tm.py` invocation was needed — the post-write check passed on the first attempt.

## L3 (FAISS) semantic layer

- **Deliberately deferred, not run this mission.** 764,510 entries; re-embedding cost after `remove_entries(predicate)` rebuilds the index from survivors was assessed as prohibitive for the remaining session time. L2/primary (LMDB, the layer actually hit on every exact-match TM lookup) is clean. Flagged explicitly in the final closure report as a scope limitation, not silently dropped.

## Fix-forward

Per the plan's TM remediation detail, `store()` fix-forward (writing corrected text back under the same key) was scoped to only where `(site_id, field_name, context, src_lang, tgt_lang, source_text)` is exactly reconstructable from the fixer that touched that segment — title/linkTitle and double-period fixes. This mission's actual purge run used delete-only for both predicates (`double_period_predicate`, `collapsed_link_predicate`) rather than fix-forward — a cache miss on next lookup is safe (falls through to a fresh translation), not a regression, and was the lower-risk choice given the scale (10,780 entries across 144 locale pairs) versus the time cost of exact-reconstruction per entry.
