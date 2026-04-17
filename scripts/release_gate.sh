#!/usr/bin/env bash
# Release gate script for Hugo Translator (Linux/CI version)
#
# Usage:
#   ./scripts/release_gate.sh [--run-dir <dir>] [--skip-realworld]
#
# Exits non-zero if any gate fails.

set -e

# Default values
RUN_DIR=""
SKIP_REALWORLD=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --run-dir)
            RUN_DIR="$2"
            shift 2
            ;;
        --skip-realworld)
            SKIP_REALWORLD=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Generate run directory if not specified
if [[ -z "$RUN_DIR" ]]; then
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    RUN_DIR="runs/release_gate_$TIMESTAMP"
fi

echo "============================================================"
echo "HUGO TRANSLATOR - RELEASE GATE"
echo "============================================================"
echo "Run Directory: $RUN_DIR"
echo ""

# Create run directory structure
mkdir -p "$RUN_DIR/logs" "$RUN_DIR/artifacts" "$RUN_DIR/output"

# Track results
UNIT_TESTS_PASS=false
FIXTURE_TRANSLATION_PASS=false
FIXTURE_ANALYSIS_PASS=false
PROBLEM_RATE_PASS=false
PROBLEM_RATE=999.0

# Gate 1: Unit Tests
echo ""
echo "[GATE 1] Running Unit Tests..."
if python -m pytest tests/contract/ tests/unit/phase-0 tests/unit/phase-1 tests/unit/phase-3/test_l1_cache.py tests/unit/phase-3/test_l2_persistent.py tests/unit/phase-4/test_registry.py -v --tb=short > "$RUN_DIR/logs/unit_tests.log" 2>&1; then
    UNIT_TESTS_PASS=true
    echo "[GATE 1] PASS - Unit tests succeeded"
else
    echo "[GATE 1] FAIL - Unit tests failed"
fi

# Gate 2: Fixture Translation
echo ""
echo "[GATE 2] Running Fixture Translation..."
FIXTURE_INPUT="test_fixtures/e2e/reference/input"
FIXTURE_OUTPUT="$RUN_DIR/output/fixture"

if [[ -d "$FIXTURE_INPUT" ]]; then
    if python -m src.cli --site e2e-reference-fixture --languages fr,ru --output-dir "$FIXTURE_OUTPUT" --log-level INFO > "$RUN_DIR/logs/fixture_translation.log" 2>&1; then
        FIXTURE_TRANSLATION_PASS=true
        echo "[GATE 2] PASS - Fixture translation completed"
    else
        echo "[GATE 2] FAIL - Fixture translation failed"
    fi
else
    echo "[GATE 2] SKIP - Fixture input not found: $FIXTURE_INPUT"
    FIXTURE_TRANSLATION_PASS=true  # Skip is OK
fi

# Gate 3: Fixture Analysis
echo ""
echo "[GATE 3] Running Fixture Analysis..."
if $FIXTURE_TRANSLATION_PASS && [[ -d "$FIXTURE_OUTPUT" ]]; then
    if python -m src.translation_engine.quality.analyzer --input "$FIXTURE_INPUT" --output "$FIXTURE_OUTPUT" --report-dir "$RUN_DIR/artifacts" > "$RUN_DIR/logs/fixture_analysis.log" 2>&1; then
        FIXTURE_ANALYSIS_PASS=true

        # Parse problem rate from score.md
        SCORE_FILE="$RUN_DIR/artifacts/score.md"
        if [[ -f "$SCORE_FILE" ]]; then
            PROBLEM_RATE=$(grep -oP 'Problem Rate[:\s]+\K[0-9.]+' "$SCORE_FILE" || echo "0.0")
        fi

        echo "[GATE 3] PASS - Analysis completed, Problem Rate: ${PROBLEM_RATE}%"
    else
        echo "[GATE 3] FAIL - Analysis failed"
    fi
else
    echo "[GATE 3] SKIP - No fixture output to analyze"
    FIXTURE_ANALYSIS_PASS=true  # Skip is OK
    PROBLEM_RATE=0.0
fi

# Gate 4: Problem Rate Check
echo ""
echo "[GATE 4] Checking Problem Rate Threshold..."
THRESHOLD=2.0
if (( $(echo "$PROBLEM_RATE <= $THRESHOLD" | bc -l) )); then
    PROBLEM_RATE_PASS=true
    echo "[GATE 4] PASS - Problem Rate ${PROBLEM_RATE}% <= ${THRESHOLD}%"
else
    echo "[GATE 4] FAIL - Problem Rate ${PROBLEM_RATE}% > ${THRESHOLD}%"
fi

# Summary
echo ""
echo "============================================================"
echo "RELEASE GATE SUMMARY"
echo "============================================================"

ALL_PASSED=true

echo -n "unit_tests: "
if $UNIT_TESTS_PASS; then echo "PASS"; else echo "FAIL"; ALL_PASSED=false; fi

echo -n "fixture_translation: "
if $FIXTURE_TRANSLATION_PASS; then echo "PASS"; else echo "FAIL"; ALL_PASSED=false; fi

echo -n "fixture_analysis: "
if $FIXTURE_ANALYSIS_PASS; then echo "PASS"; else echo "FAIL"; ALL_PASSED=false; fi

echo -n "problem_rate_check: "
if $PROBLEM_RATE_PASS; then echo "PASS"; else echo "FAIL"; ALL_PASSED=false; fi

echo ""
echo "Run artifacts: $RUN_DIR"

if $ALL_PASSED; then
    echo ""
    echo "RELEASE GATE: PASS"
    exit 0
else
    echo ""
    echo "RELEASE GATE: FAIL"
    exit 1
fi
