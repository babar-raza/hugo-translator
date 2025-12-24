# Hugo Translation System - Windows Setup Script
#
# This script automates the installation and configuration of the Hugo Translation System.
# It detects GPU capabilities and installs appropriate dependencies (CUDA or CPU mode).
#
# Usage:
#   .\setup.ps1           # Auto-detect GPU and install appropriate dependencies
#   .\setup.ps1 -CPU      # Force CPU-only mode
#   .\setup.ps1 -CUDA     # Force CUDA mode (requires compatible GPU)
#
# Requirements:
#   - Python 3.10 or higher
#   - git
#   - PowerShell 5.1+ (PowerShell 7+ recommended)

[CmdletBinding()]
param(
    [switch]$CPU,
    [switch]$CUDA,
    [switch]$Help
)

# Script configuration
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
$VenvDir = Join-Path $RepoRoot "venv"
$MinPythonVersion = [Version]"3.10.0"
$MinVRAM_GB = 8
$MinVRAM_MiB = $MinVRAM_GB * 1024

# Color output functions
function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Blue
}

function Write-Success {
    param([string]$Message)
    Write-Host "[SUCCESS] $Message" -ForegroundColor Green
}

function Write-Warning {
    param([string]$Message)
    Write-Host "[WARNING] $Message" -ForegroundColor Yellow
}

function Write-ErrorMsg {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
}

# Show help
function Show-Help {
    Write-Host @"
Hugo Translation System - Windows Setup Script

Usage: .\setup.ps1 [OPTIONS]

Options:
  -CPU      Force CPU-only mode
  -CUDA     Force CUDA mode (requires compatible GPU)
  -Help     Show this help message

Examples:
  .\setup.ps1          # Auto-detect and install
  .\setup.ps1 -CPU     # Force CPU mode
  .\setup.ps1 -CUDA    # Force CUDA mode
"@
    exit 0
}

# Check if running with sufficient privileges (not required, just informational)
function Test-AdminPrivileges {
    $currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    return $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# Detect system configuration
function Get-SystemInfo {
    Write-Info "Detecting system configuration..."

    $osInfo = Get-CimInstance Win32_OperatingSystem
    $cpuInfo = Get-CimInstance Win32_Processor | Select-Object -First 1

    Write-Info "OS: $($osInfo.Caption) ($($osInfo.Version))"
    Write-Info "Architecture: $($env:PROCESSOR_ARCHITECTURE)"
    Write-Info "CPU: $($cpuInfo.Name)"

    $isAdmin = Test-AdminPrivileges
    if (-not $isAdmin) {
        Write-Info "Running without administrator privileges (not required for setup)"
    }
}

# Check Python installation and version
function Test-PythonInstallation {
    Write-Info "Checking Python installation..."

    # Try to find python
    $pythonCmd = $null
    foreach ($cmd in @("python", "python3", "py")) {
        try {
            $ver = & $cmd --version 2>&1
            if ($LASTEXITCODE -eq 0) {
                $pythonCmd = $cmd
                break
            }
        }
        catch {
            continue
        }
    }

    if (-not $pythonCmd) {
        Write-ErrorMsg "Python is not installed or not in PATH"
        Write-ErrorMsg "Please install Python $MinPythonVersion or higher from:"
        Write-ErrorMsg "  https://www.python.org/downloads/"
        Write-ErrorMsg ""
        Write-ErrorMsg "Make sure to check 'Add Python to PATH' during installation"
        exit 1
    }

    # Get Python version
    $versionOutput = & $pythonCmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
    $pythonVersion = [Version]$versionOutput

    Write-Info "Found Python $pythonVersion ($pythonCmd)"

    if ($pythonVersion -lt $MinPythonVersion) {
        Write-ErrorMsg "Python $MinPythonVersion or higher is required (found $pythonVersion)"
        Write-ErrorMsg "Please upgrade Python from https://www.python.org/downloads/"
        exit 1
    }

    Write-Success "Python version check passed"

    return @{
        Command = $pythonCmd
        Version = $pythonVersion
    }
}

# Detect GPU and VRAM
function Get-GPUInfo {
    Write-Info "Detecting GPU capabilities..."

    $gpuMode = "cpu"
    $gpuVRAM = 0
    $gpuName = "None"

    # Check if nvidia-smi is available
    $nvidiaSmi = Get-Command nvidia-smi -ErrorAction SilentlyContinue

    if ($nvidiaSmi) {
        try {
            # Query GPU memory in MiB
            $vramOutput = nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>&1 | Select-Object -First 1
            $gpuVRAM = [int]$vramOutput.Trim()

            $gpuNameOutput = nvidia-smi --query-gpu=name --format=csv,noheader 2>&1 | Select-Object -First 1
            $gpuName = $gpuNameOutput.Trim()

            $gpuVRAM_GB = [math]::Floor($gpuVRAM / 1024)

            Write-Info "GPU detected: $gpuName"
            Write-Info "GPU VRAM: $gpuVRAM MiB (~$gpuVRAM_GB GB)"

            if ($gpuVRAM -ge $MinVRAM_MiB) {
                $gpuMode = "cuda"
                Write-Success "GPU has sufficient VRAM (>= $MinVRAM_GB GB) - CUDA mode recommended"
            }
            else {
                Write-Warning "GPU VRAM ($gpuVRAM_GB GB) is below $MinVRAM_GB GB threshold - CPU mode recommended"
            }
        }
        catch {
            Write-Warning "nvidia-smi found but failed to query GPU - defaulting to CPU mode"
            Write-Info "Error: $_"
        }
    }
    else {
        Write-Info "No NVIDIA GPU detected (nvidia-smi not found)"
    }

    Write-Info "Selected mode: $gpuMode"

    return @{
        Mode = $gpuMode
        VRAM = $gpuVRAM
        Name = $gpuName
    }
}

# Create virtual environment
function New-VirtualEnvironment {
    param($PythonInfo)

    Write-Info "Setting up Python virtual environment..."

    if (Test-Path $VenvDir) {
        Write-Warning "Virtual environment already exists at $VenvDir"
        $response = Read-Host "Remove and recreate? (y/N)"

        if ($response -eq 'y' -or $response -eq 'Y') {
            Write-Info "Removing existing virtual environment..."
            Remove-Item -Recurse -Force $VenvDir
        }
        else {
            Write-Info "Using existing virtual environment"
            return
        }
    }

    Write-Info "Creating virtual environment at $VenvDir..."
    & $PythonInfo.Command -m venv $VenvDir

    if ($LASTEXITCODE -ne 0) {
        Write-ErrorMsg "Failed to create virtual environment"
        exit 1
    }

    Write-Success "Virtual environment created"
}

# Activate virtual environment and upgrade pip
function Initialize-VirtualEnvironment {
    Write-Info "Activating virtual environment..."

    $activateScript = Join-Path $VenvDir "Scripts\Activate.ps1"

    if (-not (Test-Path $activateScript)) {
        Write-ErrorMsg "Virtual environment activation script not found"
        Write-ErrorMsg "Expected: $activateScript"
        exit 1
    }

    # Activate the virtual environment
    & $activateScript

    # Upgrade pip
    Write-Info "Upgrading pip..."
    python -m pip install --upgrade pip wheel setuptools

    if ($LASTEXITCODE -ne 0) {
        Write-ErrorMsg "Failed to upgrade pip"
        exit 1
    }

    Write-Success "Virtual environment activated"
}

# Install dependencies
function Install-Dependencies {
    param([string]$Mode)

    Write-Info "Installing dependencies for $Mode mode..."

    Push-Location $RepoRoot
    try {
        if ($Mode -eq "cuda") {
            Write-Info "Installing CUDA-enabled dependencies..."

            # Install PyTorch with CUDA support
            Write-Info "Installing PyTorch with CUDA 12.1 support..."
            python -m pip install torch --index-url https://download.pytorch.org/whl/cu121

            if ($LASTEXITCODE -ne 0) {
                Write-Warning "Failed to install CUDA PyTorch, falling back to CPU mode..."
                $Mode = "cpu"
            }
            else {
                # Install GPU requirements
                Write-Info "Installing GPU-specific requirements..."
                python -m pip install -r requirements/gpu.txt

                if ($LASTEXITCODE -ne 0) {
                    Write-ErrorMsg "Failed to install GPU requirements"
                    exit 1
                }

                Write-Success "CUDA dependencies installed"
            }
        }

        if ($Mode -eq "cpu") {
            Write-Info "Installing CPU-only dependencies..."

            # Install CPU requirements
            python -m pip install -r requirements/cpu.txt

            if ($LASTEXITCODE -ne 0) {
                Write-ErrorMsg "Failed to install CPU requirements"
                exit 1
            }

            Write-Success "CPU dependencies installed"
        }

        # Install the package in editable mode
        Write-Info "Installing hugo-translation-system package..."
        python -m pip install -e .

        if ($LASTEXITCODE -ne 0) {
            Write-ErrorMsg "Failed to install package"
            exit 1
        }

        Write-Success "Package installed successfully"
    }
    finally {
        Pop-Location
    }

    return $Mode
}

# Verify installation
function Test-Installation {
    Write-Info "Verifying installation..."

    # Check if translate-hugo command is available
    $translateCmd = Get-Command translate-hugo -ErrorAction SilentlyContinue
    if (-not $translateCmd) {
        Write-ErrorMsg "translate-hugo command not found in PATH"
        Write-ErrorMsg "Installation may have failed"
        exit 1
    }

    # Test import of key modules
    Write-Info "Testing Python imports..."
    python -c @"
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
"@

    if ($LASTEXITCODE -ne 0) {
        Write-ErrorMsg "Python import verification failed"
        exit 1
    }

    Write-Success "Installation verified successfully"
}

# Print setup summary
function Show-Summary {
    param($PythonInfo, $GPUInfo, $FinalMode)

    Write-Host ""
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    Write-Success "Setup completed successfully!"
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    Write-Host ""
    Write-Host "Configuration Summary:"
    Write-Host "  Mode: $FinalMode"
    Write-Host "  Python: $($PythonInfo.Version)"
    Write-Host "  GPU: $($GPUInfo.Name)"
    if ($GPUInfo.VRAM -gt 0) {
        Write-Host "  VRAM: $($GPUInfo.VRAM) MiB"
    }
    Write-Host "  Virtual Environment: $VenvDir"
    Write-Host ""
    Write-Host "To activate the environment:"
    Write-Host "  .\venv\Scripts\Activate.ps1"
    Write-Host ""
    Write-Host "To run smoke tests:"
    Write-Host "  .\scripts\smoke\smoke_test.ps1"
    Write-Host ""
    Write-Host "To start translating:"
    Write-Host "  translate-hugo --help"
    Write-Host ""
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# Main execution
function Main {
    Write-Info "Hugo Translation System - Setup Script (Windows)"
    Write-Info "================================================="
    Write-Host ""

    # Show help if requested
    if ($Help) {
        Show-Help
    }

    # Validate mutual exclusivity
    if ($CPU -and $CUDA) {
        Write-ErrorMsg "Cannot specify both -CPU and -CUDA flags"
        exit 1
    }

    # Detect system
    Get-SystemInfo

    # Check Python
    $pythonInfo = Test-PythonInstallation

    # Detect GPU
    $gpuInfo = Get-GPUInfo

    # Determine final mode
    $finalMode = $gpuInfo.Mode
    if ($CPU) {
        Write-Warning "Forcing CPU mode (override)"
        $finalMode = "cpu"
    }
    elseif ($CUDA) {
        Write-Warning "Forcing CUDA mode (override)"
        $finalMode = "cuda"
    }

    # Create and activate venv
    New-VirtualEnvironment -PythonInfo $pythonInfo
    Initialize-VirtualEnvironment

    # Install dependencies
    $actualMode = Install-Dependencies -Mode $finalMode

    # Verify installation
    Test-Installation

    # Show summary
    Show-Summary -PythonInfo $pythonInfo -GPUInfo $gpuInfo -FinalMode $actualMode
}

# Run main function
try {
    Main
}
catch {
    Write-ErrorMsg "Setup failed with error: $_"
    Write-ErrorMsg $_.ScriptStackTrace
    exit 1
}
