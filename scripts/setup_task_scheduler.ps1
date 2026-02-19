# PowerShell Script to Configure Windows Task Scheduler for Autonomous Workers
# Run this script as Administrator to set up automatic worker startup
#
# HARDENED 2026-02-06: Fixed 3 critical issues:
#   RC-1: Use python.exe directly instead of .bat wrappers (Task Scheduler needs .exe)
#   RC-2: Use current user with Interactive logon (not SYSTEM/ServiceAccount)
#   RC-3: Add error tracking, post-registration verification, and transcript logging

# Configuration
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$LogDir = Join-Path $ProjectRoot "data\logs"
$LogFile = Join-Path $LogDir "scheduler_setup.log"

# Ensure log directory exists
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

# Start transcript logging
Start-Transcript -Path $LogFile -Force | Out-Null

$failCount = 0

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "Windows Task Scheduler Setup for Autonomous Workers" -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host ""

# Verify running as Administrator
$currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
$isAdmin = $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host "[ERROR] This script must be run as Administrator!" -ForegroundColor Red
    Write-Host "Right-click PowerShell and select 'Run as Administrator', then run this script again." -ForegroundColor Yellow
    Stop-Transcript | Out-Null
    exit 1
}

Write-Host "[OK] Running with Administrator privileges" -ForegroundColor Green

# Get current user for task principal (matches working HugoTranslator-AutonomousVerification pattern)
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
Write-Host "[OK] Tasks will run as: $currentUser" -ForegroundColor Green
Write-Host ""

# Display configuration
Write-Host "Configuration:" -ForegroundColor Yellow
Write-Host "  Project Root: $ProjectRoot"
Write-Host "  Python: $VenvPython"
Write-Host ""

# Verify python.exe exists
if (-not (Test-Path $VenvPython)) {
    Write-Host "[ERROR] Virtual environment Python not found: $VenvPython" -ForegroundColor Red
    Write-Host "[FAIL] Setup aborted due to missing python.exe" -ForegroundColor Red
    Stop-Transcript | Out-Null
    exit 1
}

Write-Host "[OK] Python executable found: $VenvPython" -ForegroundColor Green
Write-Host ""

# Create Scheduled Tasks
Write-Host "Creating Scheduled Tasks..." -ForegroundColor Yellow
Write-Host ""

# ============================================================================
# Task 1: Autonomous Content Translation Worker
# Pattern: python.exe -m module (matches working HugoTranslator-AutonomousVerification)
# ============================================================================
Write-Host "[1/4] Creating task: HugoTranslator-ContentWorker" -ForegroundColor Cyan

$contentWorkerArgs = "-m src.workers.autonomous_content_translation_worker --mode daemon --runs-per-day 12 --window-start 07:00 --window-end 23:00 --timezone America/Los_Angeles --jitter-minutes 5 --device cuda --max-gpu-memory-percent 50 --log-level INFO"

$action1 = New-ScheduledTaskAction `
    -Execute $VenvPython `
    -Argument $contentWorkerArgs `
    -WorkingDirectory $ProjectRoot

$trigger1 = New-ScheduledTaskTrigger -AtStartup
$principal1 = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
$settings1 = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5)

Write-Host "  Execute: $VenvPython"
Write-Host "  Args: $contentWorkerArgs"
Write-Host "  WorkDir: $ProjectRoot"
Write-Host "  User: $currentUser (Interactive)"

try {
    # Remove existing task if it exists
    $existingTask1 = Get-ScheduledTask -TaskName "HugoTranslator-ContentWorker" -ErrorAction SilentlyContinue
    if ($existingTask1) {
        Write-Host "  Removing existing task..." -ForegroundColor Yellow
        Unregister-ScheduledTask -TaskName "HugoTranslator-ContentWorker" -Confirm:$false
    }

    # Create new task
    Register-ScheduledTask -TaskName "HugoTranslator-ContentWorker" `
        -Action $action1 -Trigger $trigger1 -Principal $principal1 -Settings $settings1 `
        -Description "Autonomous Content Translation Worker - Runs 4 times daily with CUDA support" | Out-Null
    Write-Host "  [OK] Task created successfully" -ForegroundColor Green
} catch {
    Write-Host "  [ERROR] Failed to create task: $_" -ForegroundColor Red
    $failCount++
}

Write-Host ""

# ============================================================================
# Task 2: TM Improvement Worker
# Pattern: python.exe -m module (matches working HugoTranslator-AutonomousVerification)
# ============================================================================
Write-Host "[2/4] Creating task: HugoTranslator-TMWorker" -ForegroundColor Cyan

$tmWorkerArgs = "-m src.workers.tm_improvement_worker --mode daemon --runs-per-day 4 --window-start 08:00 --window-end 23:00 --timezone America/Los_Angeles --jitter-minutes 15 --device cuda --max-gpu-memory-percent 50 --llm-provider ollama --llm-model qwen3:14b --candidates-per-run 50 --max-llm-calls-per-run 200 --max-seconds-per-run 900 --log-level INFO"

$action2 = New-ScheduledTaskAction `
    -Execute $VenvPython `
    -Argument $tmWorkerArgs `
    -WorkingDirectory $ProjectRoot

$trigger2 = New-ScheduledTaskTrigger -AtStartup
$principal2 = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
$settings2 = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5)

Write-Host "  Execute: $VenvPython"
Write-Host "  Args: $tmWorkerArgs"
Write-Host "  WorkDir: $ProjectRoot"
Write-Host "  User: $currentUser (Interactive)"

try {
    # Remove existing task if it exists
    $existingTask2 = Get-ScheduledTask -TaskName "HugoTranslator-TMWorker" -ErrorAction SilentlyContinue
    if ($existingTask2) {
        Write-Host "  Removing existing task..." -ForegroundColor Yellow
        Unregister-ScheduledTask -TaskName "HugoTranslator-TMWorker" -Confirm:$false
    }

    # Create new task
    Register-ScheduledTask -TaskName "HugoTranslator-TMWorker" `
        -Action $action2 -Trigger $trigger2 -Principal $principal2 -Settings $settings2 `
        -Description "TM Improvement Worker - Runs 4 times daily with CUDA support and LLM improvements" | Out-Null
    Write-Host "  [OK] Task created successfully" -ForegroundColor Green
} catch {
    Write-Host "  [ERROR] Failed to create task: $_" -ForegroundColor Red
    $failCount++
}

Write-Host ""

# ============================================================================
# Task 3: Worker Watchdog (runs every 1 hour)
# Pattern: powershell.exe -File (already correct)
# ============================================================================
Write-Host "[3/4] Creating task: HugoTranslator-Watchdog" -ForegroundColor Cyan

$watchdogScript = Join-Path $PSScriptRoot "worker_watchdog.ps1"
if (-not (Test-Path $watchdogScript)) {
    Write-Host "  [WARN] Watchdog script not found: $watchdogScript" -ForegroundColor Yellow
    Write-Host "  Skipping watchdog task creation" -ForegroundColor Yellow
} else {
    $action3 = New-ScheduledTaskAction `
        -Execute "powershell.exe" `
        -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$watchdogScript`"" `
        -WorkingDirectory $ProjectRoot

    $trigger3 = New-ScheduledTaskTrigger -Once -At (Get-Date) `
        -RepetitionInterval (New-TimeSpan -Hours 1) `
        -RepetitionDuration (New-TimeSpan -Days 9999)

    $principal3 = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
    $settings3 = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

    Write-Host "  Execute: powershell.exe"
    Write-Host "  Script: $watchdogScript"
    Write-Host "  User: $currentUser (Interactive)"

    try {
        $existingTask3 = Get-ScheduledTask -TaskName "HugoTranslator-Watchdog" -ErrorAction SilentlyContinue
        if ($existingTask3) {
            Write-Host "  Removing existing task..." -ForegroundColor Yellow
            Unregister-ScheduledTask -TaskName "HugoTranslator-Watchdog" -Confirm:$false
        }

        Register-ScheduledTask -TaskName "HugoTranslator-Watchdog" `
            -Action $action3 -Trigger $trigger3 -Principal $principal3 -Settings $settings3 `
            -Description "Worker Watchdog - checks worker health every 1 hour and restarts dead workers" | Out-Null
        Write-Host "  [OK] Task created successfully" -ForegroundColor Green
    } catch {
        Write-Host "  [ERROR] Failed to create task: $_" -ForegroundColor Red
        $failCount++
    }
}

Write-Host ""

# ============================================================================
# Task 4: Autonomous Verification Worker
# Pattern: python.exe -m module
# ============================================================================
Write-Host "[4/4] Creating task: HugoTranslator-AutonomousVerification" -ForegroundColor Cyan

$verificationWorkerArgs = "-m src.workers.autonomous_verification_worker --mode daemon --runs-per-day 4 --window-start 08:00 --window-end 23:00 --timezone America/Los_Angeles --jitter-minutes 15 --log-level INFO"

$action4 = New-ScheduledTaskAction `
    -Execute $VenvPython `
    -Argument $verificationWorkerArgs `
    -WorkingDirectory $ProjectRoot

$trigger4 = New-ScheduledTaskTrigger -AtStartup
$principal4 = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
$settings4 = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5)

Write-Host "  Execute: $VenvPython"
Write-Host "  Args: $verificationWorkerArgs"
Write-Host "  WorkDir: $ProjectRoot"
Write-Host "  User: $currentUser (Interactive)"

try {
    $existingTask4 = Get-ScheduledTask -TaskName "HugoTranslator-AutonomousVerification" -ErrorAction SilentlyContinue
    if ($existingTask4) {
        Write-Host "  Removing existing task..." -ForegroundColor Yellow
        Unregister-ScheduledTask -TaskName "HugoTranslator-AutonomousVerification" -Confirm:$false
    }

    Register-ScheduledTask -TaskName "HugoTranslator-AutonomousVerification" `
        -Action $action4 -Trigger $trigger4 -Principal $principal4 -Settings $settings4 `
        -Description "Autonomous Verification Worker - scheduled verification and audit pass" | Out-Null
    Write-Host "  [OK] Task created successfully" -ForegroundColor Green
} catch {
    Write-Host "  [ERROR] Failed to create task: $_" -ForegroundColor Red
    $failCount++
}

Write-Host ""

# ============================================================================
# Post-Registration Verification
# ============================================================================
Write-Host "================================================================================" -ForegroundColor Yellow
Write-Host "Verifying task registration..." -ForegroundColor Yellow
Write-Host "================================================================================" -ForegroundColor Yellow
Write-Host ""

$expectedTasks = @(
    "HugoTranslator-ContentWorker",
    "HugoTranslator-TMWorker",
    "HugoTranslator-Watchdog",
    "HugoTranslator-AutonomousVerification"
)
$verifiedCount = 0

foreach ($taskName in $expectedTasks) {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($task) {
        $action = $task.Actions[0]
        Write-Host "  [OK] $taskName : $($task.State)" -ForegroundColor Green
        Write-Host "        Execute: $($action.Execute)" -ForegroundColor Gray
        Write-Host "        Args: $($action.Arguments.Substring(0, [Math]::Min(80, $action.Arguments.Length)))..." -ForegroundColor Gray
        $verifiedCount++
    } else {
        Write-Host "  [FAIL] $taskName : NOT FOUND" -ForegroundColor Red
        $failCount++
    }
}

Write-Host ""

# ============================================================================
# Final Summary
# ============================================================================
if ($failCount -eq 0 -and $verifiedCount -eq $expectedTasks.Count) {
    Write-Host "================================================================================" -ForegroundColor Cyan
    Write-Host "Setup Complete! All $verifiedCount tasks registered successfully." -ForegroundColor Green
    Write-Host "================================================================================" -ForegroundColor Cyan
} else {
    Write-Host "================================================================================" -ForegroundColor Red
    Write-Host "Setup INCOMPLETE: $failCount error(s), $verifiedCount/$($expectedTasks.Count) tasks verified" -ForegroundColor Red
    Write-Host "================================================================================" -ForegroundColor Red
    Write-Host "Check $LogFile for details" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Scheduled Tasks:" -ForegroundColor Yellow
Write-Host "  1. HugoTranslator-ContentWorker" -ForegroundColor White
Write-Host "     - Runs: 4 times per day (08:00-23:00 Pacific Time)"
Write-Host "     - Device: CUDA (GPU)"
Write-Host "     - Trigger: At system startup"
Write-Host ""
Write-Host "  2. HugoTranslator-TMWorker" -ForegroundColor White
Write-Host "     - Runs: 4 times per day (08:00-23:00 Pacific Time)"
Write-Host "     - Device: CUDA (GPU)"
Write-Host "     - LLM: Ollama/qwen3:14b"
Write-Host "     - Trigger: At system startup"
Write-Host ""
Write-Host "  3. HugoTranslator-Watchdog" -ForegroundColor White
Write-Host "     - Runs: Every 1 hour"
Write-Host "     - Checks worker liveness and auto-restarts dead workers"
Write-Host "     - Circuit breaker: Max 5 restarts per hour"
Write-Host ""
Write-Host "  4. HugoTranslator-AutonomousVerification" -ForegroundColor White
Write-Host "     - Runs: 4 times per day (08:00-23:00 Pacific Time)"
Write-Host "     - Verifies scheduled worker readiness and emits audit telemetry"
Write-Host "     - Trigger: At system startup"
Write-Host ""
Write-Host "All tasks will:" -ForegroundColor Yellow
Write-Host "  - Start automatically when the system boots"
Write-Host "  - Run as current user ($currentUser)"
Write-Host "  - Restart automatically on failure (up to 3 times)"
Write-Host "  - Self-schedule runs throughout the day"
Write-Host ""
Write-Host "Management Commands:" -ForegroundColor Yellow
Write-Host "  View tasks:    taskschd.msc" -ForegroundColor White
Write-Host "  Start now:     Start-ScheduledTask -TaskName 'HugoTranslator-ContentWorker'" -ForegroundColor White
Write-Host "                 Start-ScheduledTask -TaskName 'HugoTranslator-TMWorker'" -ForegroundColor White
Write-Host "                 Start-ScheduledTask -TaskName 'HugoTranslator-Watchdog'" -ForegroundColor White
Write-Host "                 Start-ScheduledTask -TaskName 'HugoTranslator-AutonomousVerification'" -ForegroundColor White
Write-Host "  Stop:          Stop-ScheduledTask -TaskName 'HugoTranslator-ContentWorker'" -ForegroundColor White
Write-Host "                 Stop-ScheduledTask -TaskName 'HugoTranslator-TMWorker'" -ForegroundColor White
Write-Host "                 Stop-ScheduledTask -TaskName 'HugoTranslator-Watchdog'" -ForegroundColor White
Write-Host "                 Stop-ScheduledTask -TaskName 'HugoTranslator-AutonomousVerification'" -ForegroundColor White
Write-Host "  Disable:       Disable-ScheduledTask -TaskName 'HugoTranslator-ContentWorker'" -ForegroundColor White
Write-Host "                 Disable-ScheduledTask -TaskName 'HugoTranslator-TMWorker'" -ForegroundColor White
Write-Host "                 Disable-ScheduledTask -TaskName 'HugoTranslator-Watchdog'" -ForegroundColor White
Write-Host "                 Disable-ScheduledTask -TaskName 'HugoTranslator-AutonomousVerification'" -ForegroundColor White
Write-Host "  Remove:        Unregister-ScheduledTask -TaskName 'HugoTranslator-ContentWorker'" -ForegroundColor White
Write-Host "                 Unregister-ScheduledTask -TaskName 'HugoTranslator-TMWorker'" -ForegroundColor White
Write-Host "                 Unregister-ScheduledTask -TaskName 'HugoTranslator-Watchdog'" -ForegroundColor White
Write-Host "                 Unregister-ScheduledTask -TaskName 'HugoTranslator-AutonomousVerification'" -ForegroundColor White
Write-Host ""
Write-Host "Log file: $LogFile" -ForegroundColor Cyan
Write-Host "NOTE: Workers will start on next system boot, or you can start them manually now." -ForegroundColor Cyan
Write-Host ""

Stop-Transcript | Out-Null

if ($failCount -gt 0) {
    exit 1
}
exit 0
