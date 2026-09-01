# TM Backup Manifest

The pre-purge TM backup itself (1.48 GB) is **not** included in this zip — referenced here by path and checksum instead, per the plan's evidence requirements ("TM backup+purge logs", not the backup binary itself).

- Path: `backups/tm_pre_purge_quality_remediation_phase7_20260724.tar.gz`
- Size: 1,482,265,490 bytes (1.48 GB)
- SHA-256: `b4c61a2ac3f40eb73fe961bd2666c890bdbcafc7be3bc3c40108291a17ef67c2`
- Created: 2026-07-24 17:03, via `scripts/tm/backup_tm.py --output backups/tm_pre_purge_quality_remediation_phase7_20260724.tar.gz --verbose`
- Purge logs and post-write spot-check: see `stage3-execution/tm-purge-log.md` and `raw-run-logs/tc_p7_13_*.txt` in this bundle.
- Not needed for the actual purge (which completed cleanly and passed its post-write spot-check) — retained per the plan's mandatory-backup-before-write rule as the rollback path (`scripts/tm/restore_tm.py`) in case a defect surfaces later.
