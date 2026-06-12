#!/usr/bin/env bash
#
# Rollback Script - Hugo Translation System
#
# Safely rollback from new system to legacy system or previous backup state.
#
# Usage:
#   ./scripts/rollback.sh [--backup <path>] [--to-legacy] [--force]
#
# Options:
#   --backup <path>    Restore from specific backup directory
#   --to-legacy        Rollback to legacy system (archive new system)
#   --force            Skip confirmation prompts
#   --help             Show this help message
#
# Examples:
#   # Rollback to legacy system
#   ./scripts/rollback.sh --to-legacy
#
#   # Restore from specific backup
#   ./scripts/rollback.sh --backup backups/20251121_120000
#
#   # Force rollback without prompts
#   ./scripts/rollback.sh --to-legacy --force
#

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Default values
BACKUP_PATH=""
TO_LEGACY=false
FORCE=false
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --backup)
            BACKUP_PATH="$2"
            shift 2
            ;;
        --to-legacy)
            TO_LEGACY=true
            shift
            ;;
        --force)
            FORCE=true
            shift
            ;;
        --help)
            grep '^#' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

confirm() {
    if [ "$FORCE" = true ]; then
        return 0
    fi

    read -p "$1 (yes/no): " response
    case "$response" in
        yes|YES|y|Y) return 0 ;;
        *) return 1 ;;
    esac
}

check_prerequisites() {
    log_info "Checking prerequisites..."

    # Check if Docker is running (for new system)
    if command -v docker-compose &> /dev/null; then
        if docker-compose ps &> /dev/null; then
            log_info "Docker Compose available"
        fi
    fi

    # Check if backup directory exists (if specified)
    if [ -n "$BACKUP_PATH" ] && [ ! -d "$BACKUP_PATH" ]; then
        log_error "Backup directory not found: $BACKUP_PATH"
        exit 1
    fi

    # Check if legacy directory exists (if rolling back to legacy)
    if [ "$TO_LEGACY" = true ] && [ ! -d "legacy" ]; then
        log_error "Legacy directory not found"
        exit 1
    fi
}

create_pre_rollback_backup() {
    log_info "Creating pre-rollback backup..."

    BACKUP_DIR="backups/pre_rollback_${TIMESTAMP}"
    mkdir -p "$BACKUP_DIR"

    # Backup new system state
    if [ -d "data/tm" ]; then
        log_info "  Backing up Translation Memory..."
        cp -r data/tm "$BACKUP_DIR/"
    fi

    if [ -d "config" ]; then
        log_info "  Backing up configuration..."
        cp -r config "$BACKUP_DIR/"
    fi

    if [ -f ".env.production" ]; then
        log_info "  Backing up environment..."
        cp .env.production "$BACKUP_DIR/"
    fi

    # Create manifest
    cat > "$BACKUP_DIR/manifest.txt" << EOF
Hugo Translation System - Pre-Rollback Backup
Created: $(date)
Backup Type: Pre-Rollback Safety
Rollback Target: ${TO_LEGACY:+Legacy System}${BACKUP_PATH:+$BACKUP_PATH}

Contents:
$(find "$BACKUP_DIR" -type f -exec ls -lh {} \;)

Total Size: $(du -sh "$BACKUP_DIR" | cut -f1)
EOF

    log_info "Pre-rollback backup created: $BACKUP_DIR"
}

stop_new_system() {
    log_info "Stopping new system..."

    if command -v docker-compose &> /dev/null; then
        if docker-compose ps &> /dev/null 2>&1; then
            log_info "  Stopping Docker services..."
            docker-compose down
            log_info "  Docker services stopped"
        fi
    fi

    # Kill any running Python processes (be careful!)
    if pgrep -f "src.orchestrator" > /dev/null; then
        log_warn "  Stopping orchestrator process..."
        pkill -f "src.orchestrator" || true
    fi

    if pgrep -f "src.workers" > /dev/null; then
        log_warn "  Stopping worker processes..."
        pkill -f "src.workers" || true
    fi
}

rollback_to_legacy() {
    log_info "Rolling back to legacy system..."

    # Archive new system
    ARCHIVE_DIR="archive/new_system_${TIMESTAMP}"
    mkdir -p "$ARCHIVE_DIR"

    log_info "  Archiving new system to: $ARCHIVE_DIR"

    if [ -d "src" ]; then
        mv src "$ARCHIVE_DIR/" || cp -r src "$ARCHIVE_DIR/"
    fi

    if [ -d "data/tm" ]; then
        mv data/tm "$ARCHIVE_DIR/" || cp -r data/tm "$ARCHIVE_DIR/"
    fi

    # Restore legacy cache if exists in backup
    if [ -d "backups/legacy_cache" ]; then
        log_info "  Restoring legacy cache..."
        cp -r backups/legacy_cache/translation ./ || true
    fi

    # Verify legacy scripts are executable
    if [ -d "legacy" ]; then
        log_info "  Verifying legacy scripts..."
        chmod +x legacy/*.py || true

        # Test legacy system
        if python legacy/ast-creator.py --help &> /dev/null; then
            log_info "  ✓ Legacy system verified"
        else
            log_warn "  ⚠ Legacy system may need verification"
        fi
    fi

    log_info "Rollback to legacy complete"
    log_info ""
    log_info "Legacy scripts available in: ./legacy/"
    log_info "New system archived in: $ARCHIVE_DIR"
}

restore_from_backup() {
    log_info "Restoring from backup: $BACKUP_PATH"

    if [ ! -f "$BACKUP_PATH/manifest.txt" ]; then
        log_error "Invalid backup: manifest.txt not found"
        exit 1
    fi

    log_info "Backup information:"
    cat "$BACKUP_PATH/manifest.txt"
    echo ""

    if ! confirm "Restore from this backup?"; then
        log_info "Rollback cancelled"
        exit 0
    fi

    # Restore TM data
    if [ -d "$BACKUP_PATH/tm" ]; then
        log_info "  Restoring Translation Memory..."
        rm -rf data/tm
        mkdir -p data
        cp -r "$BACKUP_PATH/tm" data/
    fi

    # Restore configuration
    if [ -d "$BACKUP_PATH/config" ]; then
        log_info "  Restoring configuration..."
        cp -r "$BACKUP_PATH/config"/* config/
    fi

    # Restore environment
    if [ -f "$BACKUP_PATH/.env.production" ]; then
        log_info "  Restoring environment..."
        cp "$BACKUP_PATH/.env.production" .
    fi

    log_info "Restore from backup complete"
}

restart_system() {
    log_info "Restarting system..."

    if [ "$TO_LEGACY" = true ]; then
        log_info "Legacy system ready to use"
        log_info "Use legacy scripts in ./legacy/ directory"
        return
    fi

    # Restart new system
    if command -v docker-compose &> /dev/null; then
        if [ -f "docker-compose.yml" ]; then
            log_info "  Starting Docker services..."
            docker-compose up -d

            sleep 5

            log_info "  Checking service health..."
            docker-compose ps
        fi
    fi
}

verify_rollback() {
    log_info "Verifying rollback..."

    if [ "$TO_LEGACY" = true ]; then
        # Verify legacy system
        if [ -f "legacy/ast-creator.py" ]; then
            log_info "  ✓ Legacy scripts available"
        else
            log_error "  ✗ Legacy scripts not found"
            exit 1
        fi

        if [ -d "translation" ] || [ -d "backups/legacy_cache/translation" ]; then
            log_info "  ✓ Legacy cache available"
        else
            log_warn "  ⚠ Legacy cache not found (may need to restore)"
        fi
    else
        # Verify new system
        if [ -d "data/tm" ]; then
            log_info "  ✓ Translation Memory restored"
        else
            log_error "  ✗ Translation Memory missing"
            exit 1
        fi

        if [ -f "config/global.yaml" ]; then
            log_info "  ✓ Configuration restored"
        else
            log_error "  ✗ Configuration missing"
            exit 1
        fi

        # Check Docker services if applicable
        if command -v docker-compose &> /dev/null; then
            if docker-compose ps | grep -q "Up"; then
                log_info "  ✓ Services running"
            else
                log_warn "  ⚠ Services may need manual restart"
            fi
        fi
    fi
}

print_summary() {
    echo ""
    echo "═══════════════════════════════════════════════════════"
    echo "  Rollback Complete"
    echo "═══════════════════════════════════════════════════════"
    echo ""

    if [ "$TO_LEGACY" = true ]; then
        echo "System state: LEGACY"
        echo "Legacy scripts: ./legacy/"
        echo "New system archived: archive/new_system_${TIMESTAMP}/"
        echo ""
        echo "To use legacy system:"
        echo "  python legacy/ast-creator.py --input ./content"
        echo "  python legacy/ast-translator.py --target_languages de,es,fr"
    else
        echo "System state: NEW SYSTEM (restored from backup)"
        echo "Backup used: $BACKUP_PATH"
        echo ""
        echo "To verify:"
        echo "  docker-compose ps"
        echo "  curl http://localhost:9090/metrics"
    fi

    echo ""
    echo "Pre-rollback backup: backups/pre_rollback_${TIMESTAMP}/"
    echo ""
    echo "═══════════════════════════════════════════════════════"
}

# Main execution
main() {
    echo "═══════════════════════════════════════════════════════"
    echo "  Hugo Translation System - Rollback"
    echo "═══════════════════════════════════════════════════════"
    echo ""

    # Validate options
    if [ "$TO_LEGACY" = false ] && [ -z "$BACKUP_PATH" ]; then
        log_error "Must specify either --to-legacy or --backup <path>"
        echo "Use --help for usage information"
        exit 1
    fi

    # Show warning
    log_warn "⚠️  WARNING: This will rollback the system"
    if [ "$TO_LEGACY" = true ]; then
        log_warn "    Target: Legacy system"
    else
        log_warn "    Target: Backup at $BACKUP_PATH"
    fi
    echo ""

    if ! confirm "Are you sure you want to proceed?"; then
        log_info "Rollback cancelled"
        exit 0
    fi

    echo ""

    # Execute rollback
    check_prerequisites
    create_pre_rollback_backup
    stop_new_system

    if [ "$TO_LEGACY" = true ]; then
        rollback_to_legacy
    else
        restore_from_backup
    fi

    restart_system
    verify_rollback
    print_summary

    log_info "✓ Rollback completed successfully"
}

# Run main
main
