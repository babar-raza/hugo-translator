#!/usr/bin/env bash
# Watchdog for aspose.org translation campaign
# Monitors site workers and auto-restarts any stalled process (>15 min inactivity)
# Skips sites that are already 100% complete
# Guards against duplicate worker spawning

cd /c/Users/prora/OneDrive/Documents/GitHub/hugo-translator
source .venv/Scripts/activate
VENV_PY=".venv/Scripts/python.exe"

DATE=$(date +%Y%m%d)
SITES="products.aspose.org docs.aspose.org kb.aspose.org reference.aspose.org blog.aspose.org"
STALL_THRESHOLD=900  # 15 minutes (accounts for model initialization time)

worker_running_for_site() {
  # Check if a oneshot worker is already running for this site
  local site=$1
  $VENV_PY -c "
import psutil
for p in psutil.process_iter(['pid','cmdline']):
    try:
        cmd = ' '.join(p.info['cmdline'] or [])
        if 'autonomous_content_translation_worker' in cmd and '--site $site' in cmd and 'psutil' not in cmd:
            print(p.info['pid'])
            exit(0)
    except: pass
exit(1)
" 2>/dev/null
}

while true; do
  echo "=== Watchdog check: $(date) ==="

  for site in $SITES; do
    shortname=$(echo $site | cut -d. -f1)
    logfile="data/logs/${shortname}_run_${DATE}.log"
    lockfile="C:/Users/prora/AppData/Local/Temp/hugo-translator/locks/${site}.lock"

    # Check completion: count EN vs translated files
    pct=$($VENV_PY -c "
import glob
content = 'D:/onedrive/Documents/GitHub/aspose.org/content'
langs = 'ar bg ca cs da de el es fa fi fr he hi hr hu id it ja ko lt lv ms nl no pl pt ro ru sk sr sv th tr uk vi zh'.split()
en = len(glob.glob(f'{content}/$site/en/**/*.md', recursive=True))
if en == 0:
    print(0)
else:
    non_en = len(glob.glob(f'{content}/$site/**/*.md', recursive=True)) - en
    target = en * len(langs)
    print(non_en*100//target if target else 0)
" 2>/dev/null || echo 0)

    if [ "$pct" -ge 100 ]; then
      echo "  $site: COMPLETE (100%) - skipping"
      continue
    fi

    # Check if worker already running for this site
    existing_pid=$(worker_running_for_site $site)

    if [ ! -f "$logfile" ]; then
      if [ -n "$existing_pid" ]; then
        echo "  $site: no log but worker running (PID $existing_pid), skipping"
        continue
      fi
      echo "  $site: no log ($pct% done), starting..."
      nohup env PYTHONUNBUFFERED=1 $VENV_PY -u -m src.workers.autonomous_content_translation_worker --mode oneshot --site $site > "$logfile" 2>&1 &
      echo "  Started $site (PID: $!)"
      continue
    fi

    age=$($VENV_PY -c "import os,time; print(int(time.time()-os.path.getmtime('$logfile')))" 2>/dev/null || echo 9999)
    files=$(grep -c "Written translated file\|Purity fallback SUCCESS" "$logfile" 2>/dev/null || echo 0)

    echo "  $site: $pct% done, $files files written, log age: ${age}s"

    if [ "$age" -gt "$STALL_THRESHOLD" ]; then
      if [ -n "$existing_pid" ]; then
        echo "  STALL DETECTED but worker PID $existing_pid exists. Killing it first..."
        $VENV_PY -c "import os; os.kill($existing_pid, 9)" 2>/dev/null
        sleep 2
      fi
      echo "  STALL DETECTED: $site (${age}s). Restarting..."
      # Clear lock if exists
      $VENV_PY -c "import os; os.remove('$lockfile')" 2>/dev/null && echo "  Cleared lock for $site"
      # Restart with venv python and unbuffered output
      nohup env PYTHONUNBUFFERED=1 $VENV_PY -u -m src.workers.autonomous_content_translation_worker --mode oneshot --site $site >> "$logfile" 2>&1 &
      echo "  Restarted $site (PID: $!)"
    fi
  done

  echo "  Sleeping 5 minutes..."
  sleep 300
done
