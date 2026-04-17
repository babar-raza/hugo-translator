# Prerequisites Verification Script
# Verifies all requirements for autonomous worker setup
# Created: 2026-01-21

Write-Host ""
Write-Host "=============================================================================" -ForegroundColor Cyan
Write-Host "Hugo Translator - Prerequisites Verification" -ForegroundColor Cyan
Write-Host "=============================================================================" -ForegroundColor Cyan
Write-Host ""

$projectRoot = Split-Path -Parent $PSScriptRoot
$allPassed = $true

# Check 1: Python Virtual Environment
Write-Host "[1/6] Checking Python virtual environment..." -ForegroundColor Yellow
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (Test-Path $venvPython) {
    Write-Host "  [PASS] Virtual environment found: $venvPython" -ForegroundColor Green
    # Check Python version
    try {
        $pythonVersion = & $venvPython --version 2>&1
        Write-Host "  Python version: $pythonVersion" -ForegroundColor Gray
    } catch {
        Write-Host "  [WARN] Could not check Python version" -ForegroundColor Yellow
    }
} else {
    Write-Host "  [FAIL] Virtual environment not found at: $venvPython" -ForegroundColor Red
    Write-Host "  Run: python -m venv .venv" -ForegroundColor Yellow
    $allPassed = $false
}
Write-Host ""

# Check 2: Worker Scripts
Write-Host "[2/6] Checking worker scripts..." -ForegroundColor Yellow
$requiredScripts = @(
    "scripts\start_content_worker.bat",
    "scripts\start_tm_worker.bat",
    "scripts\start_content_worker_service.bat",
    "scripts\start_tm_worker_service.bat"
)

$scriptsPassed = $true
foreach ($script in $requiredScripts) {
    $fullPath = Join-Path $projectRoot $script
    if (Test-Path $fullPath) {
        Write-Host "  [PASS] $script" -ForegroundColor Green
    } else {
        Write-Host "  [FAIL] $script not found" -ForegroundColor Red
        $scriptsPassed = $false
        $allPassed = $false
    }
}

if ($scriptsPassed) {
    Write-Host "  All worker scripts found" -ForegroundColor Green
}
Write-Host ""

# Check 3: Configuration Files
Write-Host "[3/6] Checking configuration files..." -ForegroundColor Yellow
$configFiles = @(
    "config\global.yaml",
    "config\model_registry.yaml",
    "config\validation.yaml"
)

$configPassed = $true
foreach ($config in $configFiles) {
    $fullPath = Join-Path $projectRoot $config
    if (Test-Path $fullPath) {
        Write-Host "  [PASS] $config" -ForegroundColor Green
    } else {
        Write-Host "  [FAIL] $config not found" -ForegroundColor Red
        $configPassed = $false
        $allPassed = $false
    }
}

if ($configPassed) {
    Write-Host "  All configuration files found" -ForegroundColor Green
}
Write-Host ""

# Check 4: Site Profiles
Write-Host "[4/6] Checking site profiles..." -ForegroundColor Yellow
$siteProfilesDir = Join-Path $projectRoot "config\site_profiles"

if (Test-Path $siteProfilesDir) {
    $profileCount = (Get-ChildItem $siteProfilesDir -Filter "*.yaml").Count
    Write-Host "  [PASS] Site profiles directory found" -ForegroundColor Green
    Write-Host "  Found $profileCount site profiles" -ForegroundColor Gray
} else {
    Write-Host "  [FAIL] Site profiles directory not found" -ForegroundColor Red
    $allPassed = $false
}
Write-Host ""

# Check 5: Ollama (for TM worker)
Write-Host "[5/6] Checking Ollama (for TM Improvement Worker)..." -ForegroundColor Yellow

try {
    $ollamaResponse = Invoke-WebRequest -Uri "http://localhost:11434" -TimeoutSec 2 -ErrorAction Stop
    Write-Host "  [PASS] Ollama is running at http://localhost:11434" -ForegroundColor Green

    # Check for llama2 model
    try {
        $ollamaList = ollama list 2>&1
        if ($ollamaList -match "llama2") {
            Write-Host "  [PASS] llama2 model is available" -ForegroundColor Green
        } else {
            Write-Host "  [WARN] llama2 model not found" -ForegroundColor Yellow
            Write-Host "  Run: ollama pull llama2" -ForegroundColor Gray
            Write-Host "  Note: TM worker will fail without this model" -ForegroundColor Yellow
        }
    } catch {
        Write-Host "  [WARN] Could not check Ollama models (ollama command not in PATH)" -ForegroundColor Yellow
    }
} catch {
    Write-Host "  [WARN] Ollama not running or not accessible" -ForegroundColor Yellow
    Write-Host "  TM Improvement Worker requires Ollama" -ForegroundColor Gray
    Write-Host "  Install: https://ollama.ai/" -ForegroundColor Gray
    Write-Host "  Start: ollama serve" -ForegroundColor Gray
    Write-Host "  Note: Content Translation Worker will work without Ollama" -ForegroundColor Cyan
}
Write-Host ""

# Check 6: Log Directory
Write-Host "[6/6] Checking log directory..." -ForegroundColor Yellow
$logsDir = Join-Path $projectRoot "data\logs"

if (Test-Path $logsDir) {
    Write-Host "  [PASS] Log directory exists: $logsDir" -ForegroundColor Green
} else {
    Write-Host "  [INFO] Log directory will be created on first run" -ForegroundColor Cyan
}
Write-Host ""

# Summary
Write-Host "=============================================================================" -ForegroundColor Cyan
if ($allPassed) {
    Write-Host "Prerequisites Check: PASSED" -ForegroundColor Green
    Write-Host ""
    Write-Host "All required components are present." -ForegroundColor Green
    Write-Host "You are ready to run SETUP_AUTOSTART.bat to configure the workers." -ForegroundColor Cyan
} else {
    Write-Host "Prerequisites Check: FAILED" -ForegroundColor Red
    Write-Host ""
    Write-Host "Some required components are missing (see above)." -ForegroundColor Red
    Write-Host "Fix the issues before running SETUP_AUTOSTART.bat" -ForegroundColor Yellow
}
Write-Host "=============================================================================" -ForegroundColor Cyan
Write-Host ""
