# PowerShell Script to Configure Windows Task Scheduler for Autonomous Workers
# Run this script as Administrator to set up automatic worker startup

# Configuration
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$ContentWorkerScript = Join-Path $ProjectRoot "scripts\start_content_worker.bat"
$TMWorkerScript = Join-Path $ProjectRoot "scripts\start_tm_worker.bat"

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "Windows Task Scheduler Setup for Autonomous Workers" -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host ""

# Verify running as Administrator
$currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
$isAdmin = $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host "[ERROR] This script must be run as Administrator!" -ForegroundColor Red
    Write-Host "Right-click PowerShell and select 'Run as Administrator', then run this script again." -ForegroundColor Yellow
    exit 1
}

Write-Host "[OK] Running with Administrator privileges" -ForegroundColor Green
Write-Host ""

# Display configuration
Write-Host "Configuration:" -ForegroundColor Yellow
Write-Host "  Project Root: $ProjectRoot"
Write-Host "  Python: $VenvPython"
Write-Host "  Content Worker Script: $ContentWorkerScript"
Write-Host "  TM Worker Script: $TMWorkerScript"
Write-Host ""

# Verify files exist
$allFilesExist = $true

if (-not (Test-Path $VenvPython)) {
    Write-Host "[ERROR] Virtual environment Python not found: $VenvPython" -ForegroundColor Red
    $allFilesExist = $false
}

if (-not (Test-Path $ContentWorkerScript)) {
    Write-Host "[ERROR] Content worker script not found: $ContentWorkerScript" -ForegroundColor Red
    $allFilesExist = $false
}

if (-not (Test-Path $TMWorkerScript)) {
    Write-Host "[ERROR] TM worker script not found: $TMWorkerScript" -ForegroundColor Red
    $allFilesExist = $false
}

if (-not $allFilesExist) {
    Write-Host ""
    Write-Host "[FAIL] Setup aborted due to missing files" -ForegroundColor Red
    exit 1
}

Write-Host "[OK] All required files exist" -ForegroundColor Green
Write-Host ""

# Create Scheduled Tasks
Write-Host "Creating Scheduled Tasks..." -ForegroundColor Yellow
Write-Host ""

# Task 1: Autonomous Content Translation Worker
Write-Host "[1/2] Creating task: HugoTranslator-ContentWorker" -ForegroundColor Cyan

$action1 = New-ScheduledTaskAction -Execute $ContentWorkerScript -WorkingDirectory $ProjectRoot
$trigger1 = New-ScheduledTaskTrigger -AtStartup
$principal1 = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings1 = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5)

try {
    # Remove existing task if it exists
    $existingTask1 = Get-ScheduledTask -TaskName "HugoTranslator-ContentWorker" -ErrorAction SilentlyContinue
    if ($existingTask1) {
        Write-Host "  Removing existing task..." -ForegroundColor Yellow
        Unregister-ScheduledTask -TaskName "HugoTranslator-ContentWorker" -Confirm:$false
    }

    # Create new task
    Register-ScheduledTask -TaskName "HugoTranslator-ContentWorker" -Action $action1 -Trigger $trigger1 -Principal $principal1 -Settings $settings1 -Description "Autonomous Content Translation Worker - Runs 4 times daily with CUDA support" | Out-Null
    Write-Host "  [OK] Task created successfully" -ForegroundColor Green
} catch {
    Write-Host "  [ERROR] Failed to create task: $_" -ForegroundColor Red
}

Write-Host ""

# Task 2: TM Improvement Worker
Write-Host "[2/2] Creating task: HugoTranslator-TMWorker" -ForegroundColor Cyan

$action2 = New-ScheduledTaskAction -Execute $TMWorkerScript -WorkingDirectory $ProjectRoot
$trigger2 = New-ScheduledTaskTrigger -AtStartup
$principal2 = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings2 = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5)

try {
    # Remove existing task if it exists
    $existingTask2 = Get-ScheduledTask -TaskName "HugoTranslator-TMWorker" -ErrorAction SilentlyContinue
    if ($existingTask2) {
        Write-Host "  Removing existing task..." -ForegroundColor Yellow
        Unregister-ScheduledTask -TaskName "HugoTranslator-TMWorker" -Confirm:$false
    }

    # Create new task
    Register-ScheduledTask -TaskName "HugoTranslator-TMWorker" -Action $action2 -Trigger $trigger2 -Principal $principal2 -Settings $settings2 -Description "TM Improvement Worker - Runs 4 times daily with CUDA support and LLM improvements" | Out-Null
    Write-Host "  [OK] Task created successfully" -ForegroundColor Green
} catch {
    Write-Host "  [ERROR] Failed to create task: $_" -ForegroundColor Red
}

Write-Host ""
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "Setup Complete!" -ForegroundColor Green
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Scheduled Tasks Created:" -ForegroundColor Yellow
Write-Host "  1. HugoTranslator-ContentWorker" -ForegroundColor White
Write-Host "     - Runs: 4 times per day (08:00-23:00 Pacific Time)"
Write-Host "     - Device: CUDA (GPU)"
Write-Host "     - Trigger: At system startup"
Write-Host ""
Write-Host "  2. HugoTranslator-TMWorker" -ForegroundColor White
Write-Host "     - Runs: 4 times per day (08:00-23:00 Pacific Time)"
Write-Host "     - Device: CUDA (GPU)"
Write-Host "     - LLM: Ollama/llama2"
Write-Host "     - Trigger: At system startup"
Write-Host ""
Write-Host "Both tasks will:" -ForegroundColor Yellow
Write-Host "  - Start automatically when the system boots"
Write-Host "  - Run with SYSTEM privileges"
Write-Host "  - Restart automatically on failure (up to 3 times)"
Write-Host "  - Self-schedule runs throughout the day"
Write-Host ""
Write-Host "Management Commands:" -ForegroundColor Yellow
Write-Host "  View tasks:    taskschd.msc" -ForegroundColor White
Write-Host "  Start now:     Start-ScheduledTask -TaskName 'HugoTranslator-ContentWorker'" -ForegroundColor White
Write-Host "                 Start-ScheduledTask -TaskName 'HugoTranslator-TMWorker'" -ForegroundColor White
Write-Host "  Stop:          Stop-ScheduledTask -TaskName 'HugoTranslator-ContentWorker'" -ForegroundColor White
Write-Host "                 Stop-ScheduledTask -TaskName 'HugoTranslator-TMWorker'" -ForegroundColor White
Write-Host "  Disable:       Disable-ScheduledTask -TaskName 'HugoTranslator-ContentWorker'" -ForegroundColor White
Write-Host "                 Disable-ScheduledTask -TaskName 'HugoTranslator-TMWorker'" -ForegroundColor White
Write-Host "  Remove:        Unregister-ScheduledTask -TaskName 'HugoTranslator-ContentWorker'" -ForegroundColor White
Write-Host "                 Unregister-ScheduledTask -TaskName 'HugoTranslator-TMWorker'" -ForegroundColor White
Write-Host ""
Write-Host "NOTE: Workers will start on next system boot, or you can start them manually now." -ForegroundColor Cyan
Write-Host ""
