#!/bin/bash
set -e
echo "Checking for L3 path inconsistencies..."
FAILURES=0

# Check for dot notation in runtime code (exclude binary files, __pycache__, and this script)
if grep -rn "l3\.faiss" src/ scripts/ --exclude-dir=__pycache__ --exclude="*.pyc" --exclude="lint_l3_paths.sh" 2>/dev/null | grep -v "Binary file"; then
  echo "❌ FAIL: Found dot notation in runtime code"
  FAILURES=$((FAILURES + 1))
fi

# Check for underscore notation exists
if ! grep -rq "l3_faiss" src/orchestration/health_monitor.py 2>/dev/null; then
  echo "❌ FAIL: health_monitor.py doesn't reference l3_faiss"
  FAILURES=$((FAILURES + 1))
fi

# Check config has l3_index_dir
if ! grep -q "l3_index_dir" config/global.yaml 2>/dev/null; then
  echo "❌ FAIL: config/global.yaml missing l3_index_dir"
  FAILURES=$((FAILURES + 1))
fi

if [ $FAILURES -eq 0 ]; then
  echo "✅ PASS: All L3 paths consistent"
  exit 0
else
  echo "❌ FAIL: $FAILURES issues found"
  exit 1
fi
