#!/bin/bash
# Sequential one-shot translation for all aspose.org subdomains
# Waits for products.aspose.org to finish, then runs remaining sites

set -euo pipefail

CD="c:/Users/prora/OneDrive/Documents/GitHub/hugo-translator"
PYTHON="$CD/.venv/Scripts/python.exe"
LOGDIR="$CD/data/logs"
LOCKDIR="/c/Users/prora/AppData/Local/Temp/hugo-translator/locks"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

# Read the live target_langs count for the completion threshold below,
# instead of hardcoding it -- adapts automatically if the profile changes.
PRODUCTS_LANG_COUNT=$("$PYTHON" -c "
from src.utils.config_loader import ConfigService
print(len(ConfigService('config').get_site_profile('products.aspose.org').target_langs))
")

run_site() {
    local site="$1"
    local logfile="$LOGDIR/${site}_${TIMESTAMP}.log"

    # Clean locks
    rm -f "$LOCKDIR/${site}.lock" 2>/dev/null || true

    log "=== Starting $site ==="
    log "Log: $logfile"

    "$PYTHON" -m src.cli \
        --site "$site" \
        --device cuda \
        >> "$logfile" 2>&1

    local exit_code=$?
    local file_count=$(grep -c "Written translated file" "$logfile" 2>/dev/null || echo 0)
    local completed=$(grep -c "Directory translation completed" "$logfile" 2>/dev/null || echo 0)
    local errors=$(grep -c "CRITICAL\|FATAL\|Traceback" "$logfile" 2>/dev/null || echo 0)

    log "=== $site finished (exit=$exit_code, files=$file_count, langs_completed=$completed, errors=$errors) ==="
    echo ""
}

# --- Wait for products.aspose.org to finish ---
PRODUCTS_LOG="$LOGDIR/products_inc005fix_20260321_095050.log"
if [ -f "$PRODUCTS_LOG" ]; then
    log "Waiting for products.aspose.org to finish..."
    while true; do
        completed=$(grep -c "Directory translation completed" "$PRODUCTS_LOG" 2>/dev/null || echo 0)
        # Check if parent process is still running (look for the specific log file being written)
        last_mod=$(stat -c %Y "$PRODUCTS_LOG" 2>/dev/null || echo 0)
        now=$(date +%s)
        age=$(( now - last_mod ))

        if [ "$completed" -ge "$PRODUCTS_LANG_COUNT" ]; then
            log "products.aspose.org complete ($completed/$PRODUCTS_LANG_COUNT languages)"
            break
        elif [ "$age" -gt 600 ]; then
            # Log hasn't been updated in 10 minutes — process likely done or dead
            log "products.aspose.org log stale (${age}s since last update, $completed/$PRODUCTS_LANG_COUNT languages). Proceeding."
            break
        else
            log "products.aspose.org: $completed/$PRODUCTS_LANG_COUNT languages done, log updated ${age}s ago. Checking again in 120s..."
            sleep 120
        fi
    done
fi

# --- Run remaining subdomains sequentially ---

# Small sites first (quick wins)
log "========================================="
log "Starting aspose.org subdomain translations"
log "========================================="

run_site "www.aspose.org"
run_site "blog.aspose.org"
run_site "websites.aspose.org"
run_site "docs.aspose.org"
run_site "kb.aspose.org"
run_site "reference.aspose.org"

log "========================================="
log "All aspose.org subdomains complete!"
log "========================================="
