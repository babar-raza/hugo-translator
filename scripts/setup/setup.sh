#!/usr/bin/env bash
# Hugo Translation System - Linux Setup Script
#
# This script automates the installation and configuration of the Hugo Translation System.
# It detects GPU capabilities and installs appropriate dependencies (CUDA or CPU mode).
#
# Usage:
#   ./setup.sh           # Auto-detect GPU and install appropriate dependencies
#   ./setup.sh --cpu     # Force CPU-only mode
#   ./setup.sh --cuda    # Force CUDA mode (requires compatible GPU)
#
# Requirements:
#   - Python 3.10 or higher
#   - git
#   - bash

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
VENV_DIR="${REPO_ROOT}/venv"
MIN_PYTHON_VERSION="3.10"
MIN_VRAM_GB=8
MIN_VRAM_MIB=$((MIN_VRAM_GB * 1024))

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

# Detect OS and architecture
detect_system() {
    log_info "Detecting system configuration..."

    OS_TYPE="$(uname -s)"
    ARCH="$(uname -m)"

    log_info "OS: ${OS_TYPE}"
    log_info "Architecture: ${ARCH}"

    # Check if running in WSL
    if grep -qEi "(Microsoft|WSL)" /proc/version 2>/dev/null; then
        log_info "Running in WSL environment"
        IS_WSL=true
    else
        IS_WSL=false
    fi
}

# Check Python version
check_python() {
    log_info "Checking Python installation..."

    if ! command_exists python3; then
        log_error "Python 3 is not installed"
        log_error "Please install Python ${MIN_PYTHON_VERSION} or higher"
        exit 1
    fi

    PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
    log_info "Found Python ${PYTHON_VERSION}"

    if ! version_ge "${PYTHON_VERSION}" "${MIN_PYTHON_VERSION}"; then
        log_error "Python ${MIN_PYTHON_VERSION} or higher is required (found ${PYTHON_VERSION})"
        exit 1
    fi

    log_success "Python version check passed"
}

# Detect GPU and VRAM
detect_gpu() {
    log_info "Detecting GPU capabilities..."

    GPU_MODE="cpu"
    GPU_VRAM=0
    GPU_NAME="None"

    if command_exists nvidia-smi; then
        # Try to get GPU memory in MiB
        if GPU_VRAM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1); then
            GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 || echo "NVIDIA GPU")
            GPU_VRAM_GB=$((GPU_VRAM / 1024))

            log_info "GPU detected: ${GPU_NAME}"
            log_info "GPU VRAM: ${GPU_VRAM} MiB (~${GPU_VRAM_GB} GB)"

            if [ "${GPU_VRAM}" -ge "${MIN_VRAM_MIB}" ]; then
                GPU_MODE="cuda"
                log_success "GPU has sufficient VRAM (>= ${MIN_VRAM_GB} GB) - CUDA mode recommended"
            else
                log_warning "GPU VRAM (${GPU_VRAM_GB} GB) is below ${MIN_VRAM_GB} GB threshold - CPU mode recommended"
            fi
        else
            log_warning "nvidia-smi found but failed to query GPU - defaulting to CPU mode"
        fi
    else
        log_info "No NVIDIA GPU detected (nvidia-smi not found)"
        if [ "${IS_WSL}" = true ]; then
            log_info "WSL detected: Ensure NVIDIA drivers are installed on Windows host and WSL GPU support is enabled"
        fi
    fi

    log_info "Selected mode: ${GPU_MODE}"
}

# Parse command line arguments
parse_args() {
    FORCE_MODE=""

    while [[ $# -gt 0 ]]; do
        case $1 in
            --cpu)
                FORCE_MODE="cpu"
                shift
                ;;
            --cuda)
                FORCE_MODE="cuda"
                shift
                ;;
            --help|-h)
                echo "Usage: $0 [OPTIONS]"
                echo ""
                echo "Options:"
                echo "  --cpu      Force CPU-only mode"
                echo "  --cuda     Force CUDA mode (requires compatible GPU)"
                echo "  --help     Show this help message"
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                log_error "Use --help for usage information"
                exit 1
                ;;
        esac
    done

    if [ -n "${FORCE_MODE}" ]; then
        log_warning "Forcing ${FORCE_MODE} mode (override)"
        GPU_MODE="${FORCE_MODE}"
    fi
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
    python3 -m venv "${VENV_DIR}"

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
    log_info "Installing dependencies for ${GPU_MODE} mode..."

    cd "${REPO_ROOT}"

    if [ "${GPU_MODE}" = "cuda" ]; then
        log_info "Installing CUDA-enabled dependencies..."

        # Install PyTorch with CUDA support
        log_info "Installing PyTorch with CUDA 12.1 support..."
        pip install torch --index-url https://download.pytorch.org/whl/cu121

        # Install GPU requirements
        log_info "Installing GPU-specific requirements..."
        pip install -r requirements/gpu.txt

        log_success "CUDA dependencies installed"
    else
        log_info "Installing CPU-only dependencies..."

        # Install CPU requirements
        pip install -r requirements/cpu.txt

        log_success "CPU dependencies installed"
    fi

    # Install the package in editable mode
    log_info "Installing hugo-translation-system package..."
    pip install -e .

    log_success "Package installed successfully"
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
    python3 -c "
import sys
try:
    import torch
    import transformers
    import sentence_transformers
    print(f'✓ Core ML libraries loaded')
    print(f'  - PyTorch: {torch.__version__}')
    print(f'  - CUDA available: {torch.cuda.is_available()}')
    if torch.cuda.is_available():
        print(f'  - CUDA version: {torch.version.cuda}')
        print(f'  - GPU devices: {torch.cuda.device_count()}')
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
    echo "  Mode: ${GPU_MODE}"
    echo "  Python: ${PYTHON_VERSION}"
    echo "  GPU: ${GPU_NAME}"
    if [ "${GPU_VRAM}" -gt 0 ]; then
        echo "  VRAM: ${GPU_VRAM} MiB"
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
    log_info "Hugo Translation System - Setup Script (Linux)"
    log_info "================================================"
    echo ""

    detect_system
    check_python
    detect_gpu
    parse_args "$@"
    create_venv
    activate_venv
    install_dependencies
    verify_installation
    print_summary
}

# Run main function
main "$@"
