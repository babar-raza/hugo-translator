#!/bin/bash
# Restore Script for Hugo Translation System

set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Usage: $0 <backup_directory>"
    echo "Example: $0 backups/20251121_120000"
    exit 1
fi

BACKUP_DIR="$1"

if [ ! -d "$BACKUP_DIR" ]; then
    echo "Error: Backup directory not found: $BACKUP_DIR"
    exit 1
fi

echo "=== Hugo Translation System Restore ==="
echo "Restoring from: $BACKUP_DIR"
echo ""

# Confirm
read -p "This will overwrite existing data. Continue? (yes/no): " confirm
if [ "$confirm" != "yes" ]; then
    echo "Restore cancelled."
    exit 0
fi

# Stop services if running
echo "Stopping services..."
docker-compose down 2>/dev/null || true

# Restore TM data
if [ -f "$BACKUP_DIR/tm_data.tar.gz" ]; then
    echo "Restoring Translation Memory..."
    mkdir -p data/tm
    tar -xzf "$BACKUP_DIR/tm_data.tar.gz" -C / 2>/dev/null || tar -xzf "$BACKUP_DIR/tm_data.tar.gz"
fi

# Restore configuration
if [ -f "$BACKUP_DIR/config.tar.gz" ]; then
    echo "Restoring configuration..."
    tar -xzf "$BACKUP_DIR/config.tar.gz"
fi

# Restore environment
if [ -f "$BACKUP_DIR/.env.production.backup" ]; then
    echo "Restoring environment configuration..."
    cp "$BACKUP_DIR/.env.production.backup" .env.production
fi

# Restart services
echo "Restarting services..."
docker-compose up -d

echo ""
echo "Restore completed successfully!"
echo "Services are starting. Check status with: docker-compose ps"

exit 0
