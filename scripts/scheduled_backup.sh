#!/bin/bash
# Scheduled backup script for Linux/Unix systems
# Run via cron: 0 2 * * * /path/to/scheduled_backup.sh

set -e

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="${PROJECT_DIR}/backups"
TM_DATA_DIR="${PROJECT_DIR}/data/tm"
CONFIG_DIR="${PROJECT_DIR}/config"
KEEP_BACKUPS=7  # Keep last 7 backups
LOG_FILE="${PROJECT_DIR}/data/logs/backup.log"

# Create backup directory if needed
mkdir -p "$BACKUP_DIR"
mkdir -p "$(dirname "$LOG_FILE")"

# Generate backup filename with timestamp
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/tm_${TIMESTAMP}.tar.gz"

# Log function
log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "========== Starting scheduled backup =========="
log "Backup file: $BACKUP_FILE"
log "TM data: $TM_DATA_DIR"
log "Config: $CONFIG_DIR"
log "Keep: $KEEP_BACKUPS backups"

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    log "ERROR: python3 not found"
    exit 1
fi

# Run backup
log "Running backup..."
if python3 "${SCRIPT_DIR}/backup_tm.py" \
    --output "$BACKUP_FILE" \
    --tm-data "$TM_DATA_DIR" \
    --config "$CONFIG_DIR" \
    --rotate "$KEEP_BACKUPS" \
    >> "$LOG_FILE" 2>&1; then
    log "Backup completed successfully"
    log "Backup size: $(du -h "$BACKUP_FILE" | cut -f1)"
else
    log "ERROR: Backup failed"
    exit 1
fi

# Verify backup
log "Verifying backup..."
if python3 "${SCRIPT_DIR}/restore_tm.py" \
    --backup "$BACKUP_FILE" \
    --verify \
    --dry-run \
    >> "$LOG_FILE" 2>&1; then
    log "Backup verification successful"
else
    log "WARNING: Backup verification failed"
fi

log "========== Backup completed =========="
