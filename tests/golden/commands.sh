#!/bin/bash
# Golden Test Suite Execution Script
# Task: P0-02-GOLDEN-TESTS
# Author: Agent C

set -e

echo "=========================================="
echo "Golden Test Suite - CLI Backward Compatibility"
echo "=========================================="
echo ""

# Check if pytest is available
if ! command -v pytest &> /dev/null; then
    echo "ERROR: pytest not found"
    echo "Install: pip install pytest pytest-mock pytest-asyncio"
    exit 1
fi

# Verify test file exists
if [ ! -f "tests/golden/test_cli_backward_compat.py" ]; then
    echo "ERROR: Test file not found"
    exit 1
fi

# Verify site profile exists
if [ ! -f "config/site_profiles/golden-test.yaml" ]; then
    echo "ERROR: Site profile 'golden-test.yaml' not found"
    exit 1
fi

# Verify test fixtures exist
if [ ! -f "tests/golden/fixtures/minimal_en.md" ]; then
    echo "ERROR: Test fixture 'minimal_en.md' not found"
    exit 1
fi

echo "✓ Pre-flight checks passed"
echo ""

# Run golden tests
echo "Running golden tests..."
echo ""
pytest tests/golden/test_cli_backward_compat.py -v "$@"

# Check exit code
if [ $? -eq 0 ]; then
    echo ""
    echo "✓ All golden tests passed"
    echo ""
    echo "Baseline snapshots location:"
    echo "  tests/golden/fixtures/expected_outputs/"
    echo ""
    ls -lh tests/golden/fixtures/expected_outputs/*.json 2>/dev/null || echo "  (No snapshots found - first run will create them)"
else
    echo ""
    echo "✗ Golden tests failed"
    echo ""
    echo "Troubleshooting:"
    echo "  1. Check diff output above to see what changed"
    echo "  2. Verify CLI dependencies are installed"
    echo "  3. Review test implementation for issues"
    echo "  4. If intentional change, update baselines:"
    echo "     rm tests/golden/fixtures/expected_outputs/*.json"
    echo "     pytest tests/golden/test_cli_backward_compat.py -v"
    exit 1
fi
