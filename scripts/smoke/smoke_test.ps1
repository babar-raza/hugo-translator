# Hugo Translation System - Smoke Test Script (Windows)
#
# This script runs basic smoke tests to verify the installation is working correctly.
#
# Usage:
#   .\smoke_test.ps1
#
# Prerequisites:
#   - Virtual environment created and activated
#   - Dependencies installed

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# Configuration
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
$FixtureFile = Join-Path $ScriptDir "fixtures\smoke_test.md"
$OutputDir = Join-Path $RepoRoot "work\smoke_test_output"

# Test results tracking
$Script:TestsPassed = 0
$Script:TestsFailed = 0

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

# Print test header
function Show-Header {
    Write-Host ""
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    Write-Host "Hugo Translation System - Smoke Tests"
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    Write-Host ""
}

# Print environment information
function Show-Environment {
    Write-Info "Environment Information:"
    Write-Host ""

    # Python version
    $pythonVersion = python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
    Write-Host "  Python: $pythonVersion"

    # Check if in virtual environment
    if ($env:VIRTUAL_ENV) {
        Write-Host "  Virtual Environment: $env:VIRTUAL_ENV"
    }
    else {
        Write-Warning "Not running in a virtual environment"
    }

    # PyTorch and CUDA info
    $torchInfo = @'
import torch
print(f"  PyTorch: {torch.__version__}")
print(f"  CUDA Available: {torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"  CUDA Version: {torch.version.cuda}")
    print(f"  GPU Count: {torch.cuda.device_count()}")
    if torch.cuda.device_count() > 0:
        print(f"  GPU Name: {torch.cuda.get_device_name(0)}")
'@
    python -c $torchInfo

    # FAISS info
    $faissInfo = @'
import sys
try:
    import faiss
    print(f"  FAISS: Available")
    try:
        res = faiss.StandardGpuResources()
        print(f"  FAISS GPU: Available")
    except Exception:
        print(f"  FAISS GPU: Not available (CPU mode)")
except ImportError:
    print(f"  FAISS: Not available", file=sys.stderr)
'@
    python -c $faissInfo 2>$null

    Write-Host ""
}

# Test helper function
function Invoke-Test {
    param(
        [string]$Name,
        [scriptblock]$TestScript
    )

    Write-Info "Test: $Name..."

    try {
        & $TestScript
        Write-Success "✓ $Name passed"
        $Script:TestsPassed++
        return $true
    }
    catch {
        Write-ErrorMsg "✗ $Name failed"
        Write-ErrorMsg "  Error: $_"
        $Script:TestsFailed++
        return $false
    }
}

# Test 1: CLI help command
function Test-CLIHelp {
    $output = translate-hugo --help 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "CLI help command failed with exit code $LASTEXITCODE"
    }
}

# Test 2: Python module imports
function Test-ModuleImports {
    $pythonCode = @'
from src.cli import main
from src.translation_engine import TranslationEngine
from src.tm import TranslationMemory
print("All core modules imported successfully")
'@

    python -c $pythonCode

    if ($LASTEXITCODE -ne 0) {
        throw "Module imports failed"
    }
}

# Test 3: Dry run translation
function Test-DryRun {
    if (-not (Test-Path $FixtureFile)) {
        throw "Fixture file not found: $FixtureFile"
    }

    # Clean output directory
    if (Test-Path $OutputDir) {
        Remove-Item -Recurse -Force $OutputDir
    }
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

    # Run translation in dry-run mode
    Write-Info "Running: translate-hugo --input $FixtureFile --target-langs de --dry-run"

    $logFile = Join-Path $env:TEMP "smoke_test_output.log"
    translate-hugo --input $FixtureFile --target-langs de --dry-run 2>&1 | Tee-Object -FilePath $logFile | Out-Host

    if ($LASTEXITCODE -ne 0) {
        throw "Dry-run translation failed with exit code $LASTEXITCODE. Check $logFile for details"
    }
}

# Test 4: Version check
function Test-VersionInfo {
    $pythonCode = @'
try:
    from importlib.metadata import version
    print(version("hugo-translation-system"))
except Exception:
    print("0.1.0")
'@

    $version = python -c $pythonCode

    Write-Host "  Package version: $version"
}

# Run all tests
function Invoke-AllTests {
    Invoke-Test "CLI Help Command" { Test-CLIHelp }
    Write-Host ""

    Invoke-Test "Module Imports" { Test-ModuleImports }
    Write-Host ""

    Invoke-Test "Version Info" { Test-VersionInfo }
    Write-Host ""

    Invoke-Test "Dry-Run Translation" { Test-DryRun }
    Write-Host ""
}

# Print summary
function Show-Summary {
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    if ($Script:TestsFailed -eq 0) {
        Write-Success "All smoke tests passed! ✓"
        Write-Host ""
        Write-Host "The Hugo Translation System is ready to use."
    }
    else {
        Write-ErrorMsg "$($Script:TestsFailed) test(s) failed"
        Write-Host ""
        Write-Host "Please check the error messages above and ensure:"
        Write-Host "  - Virtual environment is activated"
        Write-Host "  - Dependencies are installed correctly"
        Write-Host "  - Required models are available"
    }

    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    Write-Host ""
}

# Main execution
function Main {
    Push-Location $RepoRoot
    try {
        Show-Header
        Show-Environment
        Invoke-AllTests
        Show-Summary

        if ($Script:TestsFailed -gt 0) {
            exit 1
        }
    }
    finally {
        Pop-Location
    }
}

# Run main function
try {
    Main
}
catch {
    Write-ErrorMsg "Smoke tests failed with error: $_"
    Write-ErrorMsg $_.ScriptStackTrace
    exit 1
}
