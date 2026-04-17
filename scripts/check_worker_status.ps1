# Check Worker Status Script
# Displays Hugo Translator autonomous worker status
# Created: 2026-01-21

Write-Host ""
Write-Host "=============================================================================" -ForegroundColor Cyan
Write-Host "Hugo Translator - Autonomous Worker Status" -ForegroundColor Cyan
Write-Host "=============================================================================" -ForegroundColor Cyan
Write-Host ""

# Check scheduled tasks
Write-Host "[1] Checking Task Scheduler..." -ForegroundColor Yellow
Write-Host ""

$tasks = Get-ScheduledTask -TaskName "HugoTranslator-*" -ErrorAction SilentlyContinue

if ($tasks) {
    foreach ($task in $tasks) {
        $taskInfo = Get-ScheduledTaskInfo -TaskName $task.TaskName
        $status = $task.State
        $lastRun = $taskInfo.LastRunTime
        $lastResult = $taskInfo.LastTaskResult
        $nextRun = $taskInfo.NextRunTime

        # Color code status
        $statusColor = "White"
        if ($status -eq "Running") { $statusColor = "Green" }
        elseif ($status -eq "Ready") { $statusColor = "Yellow" }
        elseif ($status -eq "Disabled") { $statusColor = "Red" }

        Write-Host "  Task: $($task.TaskName)" -ForegroundColor $statusColor
        Write-Host "    State: $status" -ForegroundColor $statusColor
        Write-Host "    Last Run: $lastRun"

        # Interpret result code
        if ($lastResult -eq 0) {
            Write-Host "    Last Result: 0 (Success)" -ForegroundColor Green
        } elseif ($lastResult -eq 267009) {
            Write-Host "    Last Result: 267009 (Task currently running)" -ForegroundColor Yellow
        } else {
            Write-Host "    Last Result: $lastResult (Error - check logs)" -ForegroundColor Red
        }

        if ($nextRun) {
            Write-Host "    Next Run: $nextRun"
        }
        Write-Host ""
    }
} else {
    Write-Host "  No Hugo Translator tasks found!" -ForegroundColor Red
    Write-Host "  Run SETUP_AUTOSTART.bat as Administrator to configure tasks." -ForegroundColor Yellow
    Write-Host ""
}

# Check for running Python worker processes
Write-Host "[2] Checking Running Processes..." -ForegroundColor Yellow
Write-Host ""

$workers = Get-Process python -ErrorAction SilentlyContinue |
    Where-Object {
        $cmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId = $($_.Id)" -ErrorAction SilentlyContinue).CommandLine
        $cmdLine -like "*autonomous_content_translation_worker*" -or
        $cmdLine -like "*tm_improvement_worker*"
    }

if ($workers) {
    Write-Host "  Running Worker Processes:" -ForegroundColor Green
    foreach ($worker in $workers) {
        $cmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId = $($worker.Id)").CommandLine
        $workerType = "Unknown"
        if ($cmdLine -like "*autonomous_content_translation_worker*") {
            $workerType = "Content Translation Worker"
        } elseif ($cmdLine -like "*tm_improvement_worker*") {
            $workerType = "TM Improvement Worker"
        }

        Write-Host "    PID $($worker.Id): $workerType" -ForegroundColor Green
        Write-Host "      Started: $($worker.StartTime)"
        Write-Host "      CPU Time: $($worker.CPU) seconds"
    }
} else {
    Write-Host "  No worker processes currently running" -ForegroundColor Yellow
    Write-Host "  (This is normal between scheduled runs)" -ForegroundColor Gray
}
Write-Host ""

# Display log file locations
Write-Host "[3] Log File Locations:" -ForegroundColor Yellow
Write-Host ""

$projectRoot = Split-Path -Parent $PSScriptRoot
$logFiles = @(
    @{Name="Worker Startup Log"; Path="data\logs\worker_startup.log"},
    @{Name="Content Worker Console"; Path="data\logs\content_worker_console.log"},
    @{Name="TM Worker Console"; Path="data\logs\tm_worker_console.log"},
    @{Name="Structured Logs (NDJSON)"; Path="data\logs\hugo-translator.ndjson"}
)

foreach ($logFile in $logFiles) {
    $fullPath = Join-Path $projectRoot $logFile.Path
    if (Test-Path $fullPath) {
        $size = (Get-Item $fullPath).Length
        $sizeKB = [math]::Round($size / 1KB, 2)
        Write-Host "  $($logFile.Name): " -NoNewline
        Write-Host "$fullPath" -ForegroundColor Cyan
        Write-Host "    Size: $sizeKB KB"
    } else {
        Write-Host "  $($logFile.Name): " -NoNewline
        Write-Host "Not created yet" -ForegroundColor Gray
    }
}

Write-Host ""
Write-Host "=============================================================================" -ForegroundColor Cyan
Write-Host "Quick Commands:" -ForegroundColor Yellow
Write-Host "  View logs:         .\scripts\view_logs.ps1 -LogType all" -ForegroundColor White
Write-Host "  Start workers:     START_WORKERS_NOW.bat" -ForegroundColor White
Write-Host "  Stop workers:      Stop-ScheduledTask -TaskName 'HugoTranslator-ContentWorker'" -ForegroundColor White
Write-Host "  View Task Scheduler: taskschd.msc" -ForegroundColor White
Write-Host "=============================================================================" -ForegroundColor Cyan
Write-Host ""
