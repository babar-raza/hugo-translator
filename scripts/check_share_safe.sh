#!/usr/bin/env bash
# Validate that the repository is share-safe before pushing.
# Run: bash scripts/check_share_safe.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

ERRORS=0

echo "=== Share-Safe Repository Check ==="
echo ""

# 1. Check for personal paths in tracked files (excluding known dev scripts)
echo "1. Checking for personal paths in core tracked files..."
HITS=$(git ls-files -- src/ config/ .github/ .env.example data/benchmark_corpus/ docs/ | \
  xargs grep -l 'C:\\Users\\prora\|C:/Users/prora\|D:\\onedrive\|D:/onedrive' 2>/dev/null || true)
if [ -n "$HITS" ]; then
  echo "   FAIL: Personal paths found in core files:"
  echo "$HITS" | sed 's/^/     /'
  ERRORS=$((ERRORS + 1))
else
  echo "   OK: No personal paths in core files"
fi

# 2. Check for tracked files in directories that should be gitignored
echo "2. Checking for tracked files in gitignored directories..."
LEAKED=$(git ls-files -- runs/ output/ plans/ logs/ 2>/dev/null || true)
if [ -n "$LEAKED" ]; then
  echo "   FAIL: Tracked files found in directories that should be ignored:"
  echo "$LEAKED" | sed 's/^/     /'
  ERRORS=$((ERRORS + 1))
else
  echo "   OK: No tracked files in gitignored directories"
fi

# 3. Check for large tracked binary files (> 500 KB)
echo "3. Checking for large tracked files (> 500 KB)..."
LARGE=""
while IFS= read -r -d '' file; do
  size=$(wc -c < "$file" 2>/dev/null || echo 0)
  if [ "$size" -gt 512000 ] 2>/dev/null; then
    LARGE="${LARGE}     ${size} bytes: ${file}\n"
  fi
done < <(git ls-files -z)
if [ -n "$LARGE" ]; then
  echo "   WARN: Large tracked files found:"
  echo -e "$LARGE"
else
  echo "   OK: No large tracked binary files"
fi

# 4. Check .env is not tracked
echo "4. Checking .env is not tracked..."
if git ls-files --error-unmatch .env >/dev/null 2>&1; then
  echo "   FAIL: .env is tracked!"
  ERRORS=$((ERRORS + 1))
else
  echo "   OK: .env is not tracked"
fi

# 5. Check .env.example exists
echo "5. Checking .env.example exists..."
if [ -f .env.example ]; then
  echo "   OK: .env.example exists"
else
  echo "   FAIL: .env.example missing"
  ERRORS=$((ERRORS + 1))
fi

# 6. Summary
echo ""
if [ "$ERRORS" -eq 0 ]; then
  echo "=== ALL CHECKS PASSED ==="
else
  echo "=== $ERRORS CHECK(S) FAILED ==="
  exit 1
fi
