#!/bin/bash
# Golden Repro Harness - Lock Contention Fix Validation
# Tests that multi-language translation completes without cascading timeouts

set -e  # Exit on error

# Configuration
SITE="test.golden.repro.net"
LANGS="ar,bg,cs"
TIMEOUT_SECONDS=90
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
REPORT_DIR="reports/golden_repro"
REPORT_FILE="${REPORT_DIR}/execution_${TIMESTAMP}.log"

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Create report directory
mkdir -p "${REPORT_DIR}"

# Start logging
exec > >(tee "${REPORT_FILE}") 2>&1

echo "=========================================="
echo "GOLDEN REPRO HARNESS - LOCK CONTENTION FIX"
echo "=========================================="
echo ""
echo "Timestamp: ${TIMESTAMP}"
echo "Site: ${SITE}"
echo "Languages: ${LANGS}"
echo "Timeout: ${TIMEOUT_SECONDS}s"
echo ""

# Check 1: Environment setup
echo "=========================================="
echo "CHECK 1: Environment Setup"
echo "=========================================="
echo ""

# Check Python
if ! command -v python &> /dev/null; then
    echo -e "${RED}[FAIL]${NC} Python not found"
    exit 1
fi
echo -e "${GREEN}[PASS]${NC} Python: $(python --version)"

# Check source directory
if [ ! -f "src/cli.py" ]; then
    echo -e "${RED}[FAIL]${NC} Not in project root (src/cli.py not found)"
    exit 1
fi
echo -e "${GREEN}[PASS]${NC} Project root confirmed"

# Create test corpus
TEST_SOURCE="tests/fixtures/repro/source"
mkdir -p "${TEST_SOURCE}"

cat > "${TEST_SOURCE}/test1.md" << 'EOF'
# Test Document 1

This is a test document for the golden repro harness.

## Section 1

Hello world.

## Section 2

This tests multi-language translation.
EOF

cat > "${TEST_SOURCE}/test2.md" << 'EOF'
# Test Document 2

Another test document.

- Item 1
- Item 2
- Item 3

Testing lock contention fix.
EOF

echo -e "${GREEN}[PASS]${NC} Test corpus created"
echo ""

# Check 2: Clean state
echo "=========================================="
echo "CHECK 2: Clean State"
echo "=========================================="
echo ""

# Remove old output
TEST_OUTPUT="tests/fixtures/repro/output"
if [ -d "${TEST_OUTPUT}" ]; then
    rm -rf "${TEST_OUTPUT}"
    echo -e "${GREEN}[PASS]${NC} Removed old output"
else
    echo -e "${GREEN}[PASS]${NC} No old output to clean"
fi

# Check for existing lock
LOCK_FILE=".translation_progress/locks/${SITE}.lock"
if [ -f "${LOCK_FILE}" ]; then
    echo -e "${YELLOW}[WARN]${NC} Existing lock found, removing..."
    rm -f "${LOCK_FILE}"
fi
echo -e "${GREEN}[PASS]${NC} No lock file present"
echo ""

# Check 3: Run diagnostics (should show no lock)
echo "=========================================="
echo "CHECK 3: Pre-Translation Diagnostics"
echo "=========================================="
echo ""

python -m src.cli diagnose-lock --site "${SITE}" || true
echo ""

# Check 4: Execute multi-language translation
echo "=========================================="
echo "CHECK 4: Multi-Language Translation"
echo "=========================================="
echo ""

echo "Starting translation..."
echo "Expected: Complete in <60s (not 15+ minutes)"
echo ""

START_TIME=$(date +%s)

# Run translation with timeout
set +e  # Don't exit on error for this command
timeout "${TIMEOUT_SECONDS}" python -m src.cli \
    --site "${SITE}" \
    --source "${TEST_SOURCE}" \
    --output "${TEST_OUTPUT}" \
    --target-langs "${LANGS}" \
    --skip-tm \
    > "${REPORT_DIR}/translation_output_${TIMESTAMP}.txt" 2>&1

EXIT_CODE=$?
set -e

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

echo "Duration: ${DURATION}s"
echo ""

if [ ${EXIT_CODE} -eq 124 ]; then
    echo -e "${RED}[FAIL]${NC} Translation timed out after ${TIMEOUT_SECONDS}s"
    echo "This indicates cascading timeout bug is present"
    exit 1
elif [ ${EXIT_CODE} -ne 0 ]; then
    echo -e "${RED}[FAIL]${NC} Translation failed with exit code ${EXIT_CODE}"
    cat "${REPORT_DIR}/translation_output_${TIMESTAMP}.txt"
    exit 1
fi

echo -e "${GREEN}[PASS]${NC} Translation completed successfully"
echo ""

# Check 5: Verify performance (should be <60s, not 15+ minutes)
echo "=========================================="
echo "CHECK 5: Performance Verification"
echo "=========================================="
echo ""

if [ ${DURATION} -lt 60 ]; then
    echo -e "${GREEN}[PASS]${NC} Performance: ${DURATION}s (expected <60s)"
elif [ ${DURATION} -lt 120 ]; then
    echo -e "${YELLOW}[WARN]${NC} Performance: ${DURATION}s (slower than expected, but acceptable)"
else
    echo -e "${RED}[FAIL]${NC} Performance: ${DURATION}s (too slow, expected <60s)"
    exit 1
fi

# Calculate improvement (before: 3 langs × 300s timeout = 900s)
BEFORE_TIME=900  # 3 languages × 5 min timeout
IMPROVEMENT=$(( (BEFORE_TIME - DURATION) * 100 / BEFORE_TIME ))
echo "Improvement: ${IMPROVEMENT}% faster than cascading timeout scenario"
echo ""

# Check 6: Verify logs
echo "=========================================="
echo "CHECK 6: Log Verification"
echo "=========================================="
echo ""

TRANSLATION_LOG="${REPORT_DIR}/translation_output_${TIMESTAMP}.txt"

# Check for parent lock message
if grep -q "Site lock acquired by parent process" "${TRANSLATION_LOG}"; then
    echo -e "${GREEN}[PASS]${NC} Parent lock acquisition confirmed"
else
    echo -e "${RED}[FAIL]${NC} Parent lock message not found in logs"
    exit 1
fi

# Check for child skip messages
SKIP_COUNT=$(grep -c "Skipping site lock acquisition" "${TRANSLATION_LOG}" || echo "0")
if [ "${SKIP_COUNT}" -ge 3 ]; then
    echo -e "${GREEN}[PASS]${NC} Child skip messages found (${SKIP_COUNT} occurrences)"
else
    echo -e "${RED}[FAIL]${NC} Insufficient child skip messages (found ${SKIP_COUNT}, expected ≥3)"
    exit 1
fi

# Check for cascading timeout (should NOT be present)
if grep -q "Still waiting for lock.*300s elapsed" "${TRANSLATION_LOG}"; then
    echo -e "${RED}[FAIL]${NC} Cascading timeout detected in logs (bug present)"
    exit 1
else
    echo -e "${GREEN}[PASS]${NC} No cascading timeout messages (bug fixed)"
fi

echo ""

# Check 7: Verify output completeness
echo "=========================================="
echo "CHECK 7: Output Completeness"
echo "=========================================="
echo ""

IFS=',' read -ra LANG_ARRAY <<< "${LANGS}"
for LANG in "${LANG_ARRAY[@]}"; do
    LANG_DIR="${TEST_OUTPUT}/${SITE}/${LANG}"
    if [ ! -d "${LANG_DIR}" ]; then
        echo -e "${RED}[FAIL]${NC} Output directory for ${LANG} not found"
        exit 1
    fi

    if [ ! -f "${LANG_DIR}/test1.md" ] || [ ! -f "${LANG_DIR}/test2.md" ]; then
        echo -e "${RED}[FAIL]${NC} Translated files for ${LANG} missing"
        exit 1
    fi

    echo -e "${GREEN}[PASS]${NC} ${LANG}: output complete"
done
echo ""

# Check 8: Lock cleanup
echo "=========================================="
echo "CHECK 8: Lock Cleanup"
echo "=========================================="
echo ""

if [ -f "${LOCK_FILE}" ]; then
    echo -e "${RED}[FAIL]${NC} Lock file still exists after completion"
    python -m src.cli diagnose-lock --site "${SITE}"
    exit 1
else
    echo -e "${GREEN}[PASS]${NC} Lock file cleaned up"
fi
echo ""

# Final summary
echo "=========================================="
echo "FINAL SUMMARY"
echo "=========================================="
echo ""
echo -e "${GREEN}✓ ALL CHECKS PASSED${NC}"
echo ""
echo "Performance Metrics:"
echo "  - Before (cascading timeout): 900s (3 langs × 300s)"
echo "  - After (with fix): ${DURATION}s"
echo "  - Improvement: ${IMPROVEMENT}%"
echo ""
echo "Lock Pattern Verified:"
echo "  - Parent acquired site lock: YES"
echo "  - Children skipped lock: YES (${SKIP_COUNT} occurrences)"
echo "  - Cascading timeouts: NO"
echo "  - Lock cleaned up: YES"
echo ""
echo "Report saved to: ${REPORT_FILE}"
echo ""
echo "=========================================="
echo -e "${GREEN}GOLDEN REPRO HARNESS: SUCCESS${NC}"
echo "=========================================="

exit 0
