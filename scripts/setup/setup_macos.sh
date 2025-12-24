#!/usr/bin/env bash
# Hugo Translation System - macOS Setup Script
#
# This script automates the installation and configuration of the Hugo Translation System on macOS.
# macOS does not support CUDA, so this script always installs CPU-only dependencies.
# For Apple Silicon Macs, PyTorch will use Metal Performance Shaders (MPS) where supported.
#
# Usage:
#   ./setup_macos.sh
#
# Requirements:
#   - Python 3.10 or higher
#   - git
#   - macOS 10.15+ (Catalina or later recommended)

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
VENV_DIR="${REPO_ROOT}/venv"
MIN_PYTHON_VERSION="3.10"

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

# Check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Compare version strings
version_ge() {
    printf '%s\n%s\n' "$2" "$1" | sort -V -C
}

# Detect system information
detect_system() {
    log_info "Detecting system configuration..."

    OS_TYPE="$(uname -s)"
    ARCH="$(uname -m)"
    MACOS_VERSION="$(sw_vers -productVersion)"

    log_info "OS: ${OS_TYPE} (macOS ${MACOS_VERSION})"
    log_info "Architecture: ${ARCH}"

    if [ "${ARCH}" = "arm64" ]; then
        log_info "Apple Silicon (M1/M2/M3) detected - MPS acceleration may be available"
        IS_APPLE_SILICON=true
    else
        log_info "Intel Mac detected"
        IS_APPLE_SILICON=false
    fi

    # macOS does not support CUDA
    GPU_MODE="cpu"
    log_info "Note: macOS does not support CUDA - using CPU mode"
    if [ "${IS_APPLE_SILICON}" = true ]; then
        log_info "PyTorch may use Metal Performance Shaders (MPS) for acceleration"
    fi
}

# Check Python version
check_python() {
    log_info "Checking Python installation..."

    # Try python3 first, then python
    PYTHON_CMD=""
    if command_exists python3; then
        PYTHON_CMD="python3"
    elif command_exists python; then
        PYTHON_CMD="python"
    else
        log_error "Python is not installed"
        log_error "Please install Python ${MIN_PYTHON_VERSION} or higher"
        log_error ""
        log_error "Recommended installation methods:"
        log_error "  - Homebrew: brew install python@3.11"
        log_error "  - Python.org: https://www.python.org/downloads/"
        exit 1
    fi

    PYTHON_VERSION=$($PYTHON_CMD -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
    log_info "Found Python ${PYTHON_VERSION} (${PYTHON_CMD})"

    if ! version_ge "${PYTHON_VERSION}" "${MIN_PYTHON_VERSION}"; then
        log_error "Python ${MIN_PYTHON_VERSION} or higher is required (found ${PYTHON_VERSION})"
        log_error "Please upgrade Python using Homebrew or download from python.org"
        exit 1
    fi

    log_success "Python version check passed"
}

# Create virtual environment
create_venv() {
    log_info "Setting up Python virtual environment..."

    if [ -d "${VENV_DIR}" ]; then
        log_warning "Virtual environment already exists at ${VENV_DIR}"
        read -p "Remove and recreate? (y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            log_info "Removing existing virtual environment..."
            rm -rf "${VENV_DIR}"
        else
            log_info "Using existing virtual environment"
            return 0
        fi
    fi

    log_info "Creating virtual environment at ${VENV_DIR}..."
    $PYTHON_CMD -m venv "${VENV_DIR}"

    log_success "Virtual environment created"
}

# Activate virtual environment
activate_venv() {
    log_info "Activating virtual environment..."
    # shellcheck source=/dev/null
    source "${VENV_DIR}/bin/activate"

    # Upgrade pip
    log_info "Upgrading pip..."
    pip install --upgrade pip wheel setuptools

    log_success "Virtual environment activated"
}

# Install dependencies
install_dependencies() {
    log_info "Installing CPU-optimized dependencies..."

    cd "${REPO_ROOT}"

    # Install CPU requirements
    log_info "Installing requirements from requirements/cpu.txt..."
    pip install -r requirements/cpu.txt

    # Install the package in editable mode
    log_info "Installing hugo-translation-system package..."
    pip install -e .

    log_success "Dependencies installed successfully"
}

# Verify installation
verify_installation() {
    log_info "Verifying installation..."

    # Check if translate-hugo command is available
    if ! command_exists translate-hugo; then
        log_error "translate-hugo command not found in PATH"
        log_error "Installation may have failed"
        exit 1
    fi

    # Test import of key modules
    log_info "Testing Python imports..."
    python -c "
import sys
try:
    import torch
    import transformers
    import sentence_transformers
    print(f'✓ Core ML libraries loaded')
    print(f'  - PyTorch: {torch.__version__}')
    print(f'  - MPS available: {torch.backends.mps.is_available() if hasattr(torch.backends, \"mps\") else False}')
except ImportError as e:
    print(f'✗ Import failed: {e}', file=sys.stderr)
    sys.exit(1)

try:
    import faiss
    print(f'✓ FAISS loaded')
except ImportError as e:
    print(f'✗ FAISS import failed: {e}', file=sys.stderr)
    sys.exit(1)
" || {
        log_error "Python import verification failed"
        exit 1
    }

    log_success "Installation verified successfully"
}

# Print setup summary
print_summary() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo -e "${GREEN}Setup completed successfully!${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "Configuration Summary:"
    echo "  Mode: CPU (macOS)"
    echo "  Python: ${PYTHON_VERSION}"
    echo "  Architecture: ${ARCH}"
    if [ "${IS_APPLE_SILICON}" = true ]; then
        echo "  Note: MPS acceleration may be available for some operations"
    fi
    echo "  Virtual Environment: ${VENV_DIR}"
    echo ""
    echo "To activate the environment:"
    echo "  source venv/bin/activate"
    echo ""
    echo "To run smoke tests:"
    echo "  ./scripts/smoke/smoke_test.sh"
    echo ""
    echo "To start translating:"
    echo "  translate-hugo --help"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# Main execution
main() {
    log_info "Hugo Translation System - Setup Script (macOS)"
    log_info "==============================================="
    echo ""

    detect_system
    check_python
    create_venv
    activate_venv
    install_dependencies
    verify_installation
    print_summary
}

# Run main function
main "$@"
