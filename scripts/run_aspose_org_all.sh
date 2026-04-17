#!/usr/bin/env bash
# Run translation for all aspose.org sites sequentially, looping until all done.
# Each site runs oneshot (processes one chunk of 20 files, commits, exits).
# The outer loop re-runs sites until no new translations are produced.
# Resilient: worker crashes don't kill the loop — logs the exit code and moves on.

set -uo pipefail
cd "$(dirname "$0")/.."

SITES=(
  blog.aspose.org
  docs.aspose.org
  kb.aspose.org
  products.aspose.org
  reference.aspose.org
  websites.aspose.org
  www.aspose.org
)

LOGDIR="data/logs"
mkdir -p "$LOGDIR"

PASS=0
while true; do
  PASS=$((PASS + 1))
  ANY_WORK=0
  echo "========== Pass $PASS — $(date) =========="

  for SITE in "${SITES[@]}"; do
    LOGFILE="$LOGDIR/${SITE}_pass${PASS}_$(date +%H%M%S).log"
    echo "--- $SITE ---"

    EXIT_CODE=0
    .venv/Scripts/python.exe -m src.workers.autonomous_content_translation_worker \
      --mode oneshot \
      --site "$SITE" \
      --device cuda \
      --max-gpu-memory-percent 50 \
      --log-level INFO \
      > "$LOGFILE" 2>&1 || EXIT_CODE=$?

    if [ "$EXIT_CODE" -ne 0 ]; then
      echo "  -> Worker exited with code $EXIT_CODE. Check $LOGFILE"
      # Clear stale lock so next site/pass isn't blocked
      rm -f ".translation_progress/locks/${SITE}.lock" 2>/dev/null
      continue
    fi

    # Check if any files were translated (look for commit or successful output)
    if grep -q "Chunk.*committed\|committed.*files\|successful_files.*[1-9]" "$LOGFILE" 2>/dev/null; then
      ANY_WORK=1
      echo "  -> Translated files, committed."
    else
      echo "  -> No new translations needed."
    fi
  done

  if [ "$ANY_WORK" -eq 0 ]; then
    echo "========== All sites up to date. Done. =========="
    break
  fi

  echo "========== Pass $PASS complete, starting next pass =========="
  sleep 5
done
