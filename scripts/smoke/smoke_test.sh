#!/usr/bin/env bash
# Hugo Translation System - Smoke Test Script (Linux/macOS)
#
# This script runs basic smoke tests to verify the installation is working correctly.
#
# Usage:
#   ./smoke_test.sh
#
# Prerequisites:
#   - Virtual environment created and activated
#   - Dependencies installed

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
FIXTURE_FILE="${SCRIPT_DIR}/fixtures/smoke_test.md"
OUTPUT_DIR="${REPO_ROOT}/work/smoke_test_output"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $*"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $*"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $*"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $*"
}

# Print test header
print_header() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "Hugo Translation System - Smoke Tests"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
}

# Print environment information
print_environment() {
    log_info "Environment Information:"
    echo ""

    # Python version
    PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')
    echo "  Python: ${PYTHON_VERSION}"

    # Check if in virtual environment
    if [ -n "${VIRTUAL_ENV:-}" ]; then
        echo "  Virtual Environment: ${VIRTUAL_ENV}"
    else
        log_warning "Not running in a virtual environment"
    fi

    # PyTorch and CUDA info
    python3 -c "
import torch
print(f'  PyTorch: {torch.__version__}')
print(f'  CUDA Available: {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'  CUDA Version: {torch.version.cuda}')
    print(f'  GPU Count: {torch.cuda.device_count()}')
    if torch.cuda.device_count() > 0:
        print(f'  GPU Name: {torch.cuda.get_device_name(0)}')
elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
    print(f'  MPS Available: True')
"

    # FAISS info
    python3 -c "
import faiss
import sys
print(f'  FAISS: Available')
# Check if GPU FAISS is available
try:
    res = faiss.StandardGpuResources()
    print(f'  FAISS GPU: Available')
except Exception:
    print(f'  FAISS GPU: Not available (CPU mode)')
" 2>/dev/null || echo "  FAISS: Not available"

    echo ""
}

# Test 1: CLI help command
test_cli_help() {
    log_info "Test 1: Checking CLI help command..."

    if translate-hugo --help >/dev/null 2>&1; then
        log_success "✓ CLI help command works"
        return 0
    else
        log_error "✗ CLI help command failed"
        return 1
    fi
}

# Test 2: Python module import
test_module_imports() {
    log_info "Test 2: Testing Python module imports..."

    python3 -c "
import sys
from src.cli import main
from src.translation_engine import TranslationEngine
from src.tm import TranslationMemory
print('All core modules imported successfully')
" 2>&1

    if [ $? -eq 0 ]; then
        log_success "✓ Module imports successful"
        return 0
    else
        log_error "✗ Module import failed"
        return 1
    fi
}

# Test 3: Dry run translation
test_dry_run() {
    log_info "Test 3: Running dry-run translation..."

    if [ ! -f "${FIXTURE_FILE}" ]; then
        log_error "Fixture file not found: ${FIXTURE_FILE}"
        return 1
    fi

    # Clean output directory
    rm -rf "${OUTPUT_DIR}"
    mkdir -p "${OUTPUT_DIR}"

    # Run translation in dry-run mode
    log_info "Running: translate-hugo --input ${FIXTURE_FILE} --target-langs de --dry-run"

    if translate-hugo \
        --input "${FIXTURE_FILE}" \
        --target-langs de \
        --dry-run \
        2>&1 | tee /tmp/smoke_test_output.log; then
        log_success "✓ Dry-run translation completed"
        return 0
    else
        log_error "✗ Dry-run translation failed"
        log_error "Check /tmp/smoke_test_output.log for details"
        return 1
    fi
}

# Test 4: Version check
test_version_info() {
    log_info "Test 4: Checking package version..."

    VERSION=$(python3 -c "
try:
    from importlib.metadata import version
    print(version('hugo-translation-system'))
except Exception as e:
    print('0.1.0')
")

    echo "  Package version: ${VERSION}"
    log_success "✓ Version check completed"
    return 0
}

# Test 5: Real translation
test_real_translation() {
    log_info "Test 5: Running real translation (may download models on first run ~1-2GB)..."
    log_warning "First run downloads models from HuggingFace. Please be patient."

    if [ ! -f "${FIXTURE_FILE}" ]; then
        log_error "Fixture file not found: ${FIXTURE_FILE}"
        return 1
    fi

    # Clean output directory
    rm -rf "${OUTPUT_DIR}/de"
    mkdir -p "${OUTPUT_DIR}/de"

    # Run translation with timeout
    log_info "Running: translate-hugo --input ${FIXTURE_FILE} --target-langs de --output ${OUTPUT_DIR} --disable-validation"

    if timeout 300 translate-hugo \
        --input "${FIXTURE_FILE}" \
        --target-langs de \
        --output "${OUTPUT_DIR}" \
        --disable-validation \
        2>&1 | tee /tmp/smoke_test_real_translation.log; then

        # Verify output file exists and is not empty
        OUTPUT_FILE="${OUTPUT_DIR}/de/smoke_test.md"
        if [ -f "${OUTPUT_FILE}" ] && [ -s "${OUTPUT_FILE}" ]; then
            FILE_SIZE=$(wc -c < "${OUTPUT_FILE}")
            log_success "✓ Real translation completed (output: ${FILE_SIZE} bytes)"
            return 0
        else
            log_error "✗ Output file not created or empty: ${OUTPUT_FILE}"
            return 1
        fi
    else
        EXIT_CODE=$?
        if [ ${EXIT_CODE} -eq 124 ]; then
            log_error "✗ Translation timed out (>300s) - may be downloading models"
            log_error "Check /tmp/smoke_test_real_translation.log for details"
        else
            log_error "✗ Real translation failed"
            log_error "Check /tmp/smoke_test_real_translation.log for details"
        fi
        return 1
    fi
}

# Run all tests
run_tests() {
    local failed=0

    test_cli_help || ((failed++))
    echo ""

    test_module_imports || ((failed++))
    echo ""

    test_version_info || ((failed++))
    echo ""

    test_dry_run || ((failed++))
    echo ""

    test_real_translation || ((failed++))
    echo ""

    return $failed
}

# Print summary
print_summary() {
    local failed=$1

    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    if [ $failed -eq 0 ]; then
        log_success "All smoke tests passed! ✓"
        echo ""
        echo "The Hugo Translation System is ready to use."
    else
        log_error "$failed test(s) failed"
        echo ""
        echo "Please check the error messages above and ensure:"
        echo "  - Virtual environment is activated"
        echo "  - Dependencies are installed correctly"
        echo "  - Required models are available"
    fi
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""

    return $failed
}

# Main execution
main() {
    cd "${REPO_ROOT}"

    print_header
    print_environment

    run_tests
    local result=$?

    print_summary $result
    exit $result
}

# Run main function
main "$@"
