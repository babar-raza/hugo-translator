#!/bin/bash
# Backup Script for Hugo Translation System
# Creates backups of TM data, configuration, and logs

set -euo pipefail

BACKUP_ROOT="${BACKUP_ROOT:-./backups}"
BACKUP_DIR="$BACKUP_ROOT/$(date +%Y%m%d_%H%M%S)"
TIMESTAMP=$(date +%Y-%m-%d\ %H:%M:%S)

echo "=== Hugo Translation System Backup ==="
echo "Starting backup at: $TIMESTAMP"
echo "Backup directory: $BACKUP_DIR"

mkdir -p "$BACKUP_DIR"

# Backup TM data
echo "Backing up Translation Memory..."
if docker ps | grep -q translator-orchestrator; then
    docker exec translator-orchestrator tar -czf - /data/tm 2>/dev/null > "$BACKUP_DIR/tm_data.tar.gz" || echo "TM data not found"
else
    tar -czf "$BACKUP_DIR/tm_data.tar.gz" data/tm 2>/dev/null || echo "TM data not found"
fi

# Backup configuration
echo "Backing up configuration..."
tar -czf "$BACKUP_DIR/config.tar.gz" config/ 2>/dev/null || echo "Config not found"

# Backup environment
if [ -f .env.production ]; then
    cp .env.production "$BACKUP_DIR/.env.production.backup"
fi

# Backup model registry
cp config/model_registry.yaml "$BACKUP_DIR/model_registry.yaml" 2>/dev/null || true

# Create manifest
cat > "$BACKUP_DIR/manifest.txt" <<MANIFEST
Backup Date: $TIMESTAMP
System: Hugo Translation System
TM Data: tm_data.tar.gz
Configuration: config.tar.gz
Environment: .env.production.backup
Model Registry: model_registry.yaml
MANIFEST

# Calculate sizes
echo "" >> "$BACKUP_DIR/manifest.txt"
echo "File Sizes:" >> "$BACKUP_DIR/manifest.txt"
du -h "$BACKUP_DIR"/* >> "$BACKUP_DIR/manifest.txt"

echo "Backup completed successfully: $BACKUP_DIR"
echo "Total backup size: $(du -sh "$BACKUP_DIR" | cut -f1)"

# Cleanup old backups (keep last 7 days)
find "$BACKUP_ROOT" -type d -mtime +7 -name "20*" -exec rm -rf {} + 2>/dev/null || true

exit 0
