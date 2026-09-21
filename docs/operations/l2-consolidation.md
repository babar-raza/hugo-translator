# L2 consolidation

Run `python scripts/tm/migrate_l2_lmdb.py --dry-run` for a read-only report.
Counts exclude the `by_config_fingerprint` named database descriptor; it is
metadata, not a translation. The report checks translation readability and
canonical lineage coverage as well as missing source keys.

Stop content, improvement, CLI and other TM writers before `--apply`.
L2 users hold OS leases; apply holds maintenance admission locks across both
stores and refuses active leases. PID-file and process checks cover older
workers which predate leases. New processes cannot open through L2 during
maintenance. Direct third-party LMDB writers must also be stopped.

`--apply` creates a compact LMDB snapshot under `data/tm/migration-backups/`
before changing canonical storage. It copies translation records in one
transaction, preserves canonical collision values, and rebuilds lineage from
those canonical values. Malformed translation records cause refusal. A map
capacity failure aborts the transaction; it does not partially merge or
silently grow the production store. Resolve capacity before retrying.

Run `--verify` afterward. It returns nonzero for missing keys, malformed
entries, or missing canonical lineage. Verification does not mean colliding
legacy translations equal canonical translations: canonical values win.

For recovery, keep both the legacy store and reported snapshot. An interrupted
transaction needs only a rerun. If an already committed merge must be rolled
back, stop all users, retain the post-merge directory under a separate recovery
name, and restore the snapshot to the exact canonical path. Never replace an
open environment. No automatic deletion or rollback is performed.

Only after successful verification should the legacy directory be archived
outside the `l2*` sibling namespace. Keep the archive recoverable. This step is
separate from merge, so a failed verification cannot remove the source.

## Current disposition

On 2026-09-09, after confirming no campaign or TM writer process was active,
the empty former `data/tm/l2_lmdb` environment was moved recoverably to
`data/tm/legacy-archives/l2_lmdb-20260909`. A subsequent `--verify` reported
0 legacy entries, 13,170 canonical entries, 0 invalid records, and 0 missing
lineage records. The canonical operational path is now only `data/tm/l2.lmdb`.
