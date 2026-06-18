# Backup and Restore Guide

This document describes how to backup and restore Translation Memory data and configuration files for disaster recovery and data protection.

## Overview

The backup system provides:

- **Automated backups** of TM data (L2 LMDB, L3 FAISS) and configuration
- **Integrity verification** using SHA256 checksums
- **Compression** to reduce storage space
- **Backup rotation** to manage old backups
- **Cross-platform support** (Windows and Linux)
- **Zero-downtime backups** (system can continue running)

## Architecture

```
┌─────────────────┐
│  Translation    │
│  System         │
│                 │
│  - L2 LMDB     │──┐
│  - L3 FAISS    │  │
│  - Config      │  │
└─────────────────┘  │
                     │
                     ├──> backup_tm.py ──> Compressed Backup
                     │                     + Checksum
                     │
                     └──> restore_tm.py <── Verified Restore
```

## Creating Backups

### Manual Backup

Create a one-time backup:

```bash
# Basic backup
python scripts/tm/backup_tm.py --output backups/tm_20250101.tar.gz

# Backup with rotation (keep last 7)
python scripts/tm/backup_tm.py \
    --output backups/tm_20250101.tar.gz \
    --rotate 7

# Backup with custom paths
python scripts/tm/backup_tm.py \
    --output backups/tm_20250101.tar.gz \
    --tm-data ./data/tm \
    --config ./config

# Uncompressed backup (faster)
python scripts/tm/backup_tm.py \
    --output backups/tm_20250101.tar \
    --compression none
```

### Scheduled Backups

#### Linux/Unix (cron)

1. Make script executable:
   ```bash
   chmod +x scripts/scheduled_backup.sh
   ```

2. Edit crontab:
   ```bash
   crontab -e
   ```

3. Add scheduled backup (daily at 2 AM):
   ```cron
   0 2 * * * /path/to/hugo-translator/scripts/scheduled_backup.sh
   ```

#### Windows (Task Scheduler)

1. Open Task Scheduler

2. Create new task:
   - **Name**: Translation System Backup
   - **Trigger**: Daily at 2:00 AM
   - **Action**: Start a program
     - **Program**: `C:\Path\To\scripts\scheduled_backup.bat`
     - **Start in**: `C:\Path\To\hugo-translator`

3. Configure settings:
   - Run whether user is logged on or not
   - Run with highest privileges

## Restoring Backups

### Basic Restore

Restore to original locations:

```bash
# Restore with verification
python scripts/tm/restore_tm.py \
    --backup backups/tm_20250101.tar.gz \
    --verify

# Restore without verification (faster)
python scripts/tm/restore_tm.py \
    --backup backups/tm_20250101.tar.gz
```

### Test Restore

Restore to a different location for testing:

```bash
# Restore to test location
python scripts/tm/restore_tm.py \
    --backup backups/tm_20250101.tar.gz \
    --target /tmp/test_restore \
    --verify
```

### Dry Run

See what would be restored without actually restoring:

```bash
python scripts/tm/restore_tm.py \
    --backup backups/tm_20250101.tar.gz \
    --dry-run
```

### Test Backup Integrity

Test if a backup is corrupted:

```bash
python scripts/tm/restore_tm.py \
    --backup backups/tm_20250101.tar.gz \
    --test
```

## Backup Contents

Each backup includes:

### Data Files

- **L2 LMDB Database**: Exact match translation memory
  - `data.mdb`: LMDB data file
  - `lock.mdb`: LMDB lock file

- **L3 FAISS Index**: Semantic match translation memory
  - `index.faiss`: FAISS vector index
  - `metadata.json`: Index metadata

### Configuration Files

- `global.yaml`: Global system configuration
- `model_registry.yaml`: Model configuration
- Other YAML/YML files in config directory

### Metadata

- `metadata.json`: Backup information
  - Timestamp
  - System version
  - Component sizes
  - File counts
  - Checksums

## Backup Verification

### Integrity Checks

Backups include multiple integrity checks:

1. **SHA256 Checksum**: Verifies backup file integrity
2. **Metadata Validation**: Confirms all components present
3. **Tarball Validation**: Ensures archive is valid

### Verification Process

When restoring with `--verify`:

1. Check backup file exists
2. Calculate SHA256 checksum
3. Compare with stored checksum
4. Read and validate metadata
5. Extract files
6. Verify all components restored

## Backup Rotation

### Automatic Rotation

Rotation automatically removes old backups:

```bash
# Keep last 7 backups
python scripts/tm/backup_tm.py \
    --output backups/tm_$(date +%Y%m%d).tar.gz \
    --rotate 7
```

### Rotation Logic

- Sorts backups by modification time
- Keeps N most recent backups
- Removes older backups and checksums
- Logs rotation actions

### Manual Cleanup

Remove old backups manually:

```bash
# Remove backups older than 30 days
find backups/ -name "tm_*.tar.gz" -mtime +30 -delete
find backups/ -name "tm_*.tar.gz.sha256" -mtime +30 -delete
```

## Backup Storage

### Local Storage

Store backups on same machine:

```bash
# Default location
./backups/

# Custom location
/var/backups/translation-system/
```

### Remote Storage

Copy backups to remote storage:

```bash
# SCP to remote server
scp backups/tm_20250101.tar.gz user@backup-server:/backups/

# AWS S3
aws s3 cp backups/tm_20250101.tar.gz s3://my-bucket/backups/

# rsync to remote
rsync -av backups/ user@backup-server:/backups/
```

### Backup Retention

Recommended retention policy:

- **Daily backups**: Keep last 7 days
- **Weekly backups**: Keep last 4 weeks
- **Monthly backups**: Keep last 12 months

## Disaster Recovery

### Complete System Loss

1. Reinstall system:
   ```bash
   git clone <repository>
   pip install -r requirements/base.txt
   ```

2. Restore most recent backup:
   ```bash
   python scripts/tm/restore_tm.py \
       --backup backups/tm_latest.tar.gz \
       --verify
   ```

3. Verify system:
   ```bash
   python scripts/health_check.py --verbose
   ```

4. Resume operations

### Partial Data Loss

Restore specific components:

```bash
# Restore to temporary location
python scripts/tm/restore_tm.py \
    --backup backups/tm_20250101.tar.gz \
    --target /tmp/restore \
    --verify

# Copy specific components
cp -r /tmp/restore/tm_data/l2_lmdb ./data/tm/
# or
cp -r /tmp/restore/tm_data/l3_faiss ./data/tm/
```

### Data Corruption

1. Stop translation system
2. Restore from last known good backup
3. Verify integrity
4. Restart system

## Performance Considerations

### Backup Performance

Typical backup times:

| TM Size | Compression | Time | Backup Size |
|---------|-------------|------|-------------|
| 1 GB | gzip | ~30s | ~300 MB |
| 5 GB | gzip | ~2m | ~1.5 GB |
| 10 GB | gzip | ~5m | ~3 GB |
| 10 GB | none | ~1m | ~10 GB |

### Optimization Tips

1. **Use compression** for long-term storage
2. **Skip compression** for faster backups
3. **Schedule backups** during low-traffic periods
4. **Use fast storage** (SSD) for backup destination
5. **Monitor disk space** to prevent backup failures

### Resource Usage

Backup process uses:

- **CPU**: Medium (compression)
- **Memory**: Low (~100-200 MB)
- **Disk I/O**: High (reading source files)
- **Network**: None (local backup)

## Backup Best Practices

### Frequency

- **Production systems**: Daily backups
- **Development systems**: Weekly backups
- **Before major changes**: Manual backup

### Testing

Test backups regularly:

```bash
# Monthly restore test
python scripts/tm/restore_tm.py \
    --backup backups/tm_latest.tar.gz \
    --target /tmp/test_restore \
    --verify
```

### Documentation

Document your backup procedure:

- Backup schedule
- Storage locations
- Retention policy
- Recovery procedures
- Contact information

### Monitoring

Monitor backup health:

- Check backup logs: `data/logs/backup.log`
- Verify backup sizes (should be consistent)
- Test restore periodically
- Monitor disk space

### Security

Protect backups:

- Restrict access permissions
- Encrypt sensitive backups
- Store off-site copies
- Use secure transfer (SSH/TLS)

## Troubleshooting

### Backup Fails

**Problem**: Backup script fails

**Solutions**:
1. Check disk space: `df -h`
2. Verify paths exist
3. Check permissions
4. Review logs: `data/logs/backup.log`

### Checksum Mismatch

**Problem**: Backup verification fails with checksum mismatch

**Solutions**:
1. Backup may be corrupted - create new backup
2. Don't modify backup files manually
3. Check for disk errors

### Restore Fails

**Problem**: Restore fails or incomplete

**Solutions**:
1. Verify backup integrity: `--test` flag
2. Check target directory permissions
3. Ensure sufficient disk space
4. Try dry run first: `--dry-run`

### Slow Backups

**Problem**: Backups take too long

**Solutions**:
1. Use faster compression: `--compression gz` instead of `bz2`
2. Skip compression: `--compression none`
3. Use faster storage (SSD)
4. Schedule during low-traffic periods

### Large Backup Files

**Problem**: Backup files too large

**Solutions**:
1. Use better compression: `--compression bz2` or `xz`
2. Clean old TM entries
3. Increase rotation frequency
4. Compress with external tool

## Advanced Usage

### Incremental Backups

For very large TM systems, consider incremental backups:

```bash
# Full backup (weekly)
python scripts/tm/backup_tm.py --output backups/full_20250101.tar.gz

# Then use rsync for daily incremental
rsync -av --link-dest=../full_20250101 \
    data/tm/ backups/incremental_20250102/
```

### Encrypted Backups

Encrypt sensitive backups:

```bash
# Create encrypted backup
python scripts/tm/backup_tm.py --output - | \
    gpg --encrypt --recipient backup@example.com \
    > backups/tm_20250101.tar.gz.gpg

# Restore encrypted backup
gpg --decrypt backups/tm_20250101.tar.gz.gpg | \
    python scripts/tm/restore_tm.py --backup - --target /tmp/restore
```

### Remote Backups

Backup directly to remote server:

```bash
# Backup and transfer
python scripts/tm/backup_tm.py --output - | \
    ssh user@backup-server "cat > /backups/tm_20250101.tar.gz"
```

## Command Reference

### backup_tm.py

```bash
python scripts/tm/backup_tm.py [OPTIONS]

Options:
  --output, -o PATH       Output backup file (required)
  --tm-data PATH          TM data directory [default: ./data/tm]
  --config PATH           Config directory [default: ./config]
  --rotate N              Keep last N backups
  --compression TYPE      Compression type: gz, bz2, xz, none [default: gz]
  --verbose, -v           Enable verbose logging
  --help, -h              Show help message
```

### restore_tm.py

```bash
python scripts/tm/restore_tm.py [OPTIONS]

Options:
  --backup, -b PATH       Backup file to restore (required)
  --target, -t PATH       Target directory [default: original paths]
  --verify                Verify integrity before restoring
  --dry-run               Show what would be restored
  --test                  Test if backup is corrupted
  --verbose, -v           Enable verbose logging
  --help, -h              Show help message
```

## See Also

- [Operations Guide](./README.md)
- [Disaster Recovery Runbook](./DISASTER_RECOVERY.md)
- Health Monitoring (archived)
- [Troubleshooting Guide](./troubleshooting.md)
