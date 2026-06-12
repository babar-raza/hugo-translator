# Autonomous Operation Verification Script
# Runs all Phase 7 verification checks from the implementation plan
# Created: 2026-01-21

Write-Host ""
Write-Host "=============================================================================" -ForegroundColor Cyan
Write-Host "Hugo Translator - Autonomous Operation Verification" -ForegroundColor Cyan
Write-Host "=============================================================================" -ForegroundColor Cyan
Write-Host ""

$projectRoot = Split-Path -Parent $PSScriptRoot
$allPassed = $true
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

# Verification Report
$report = @"
# Autonomous Operation Verification Report
Generated: $timestamp

"@

# Check 7.1: Task Scheduler Verification
Write-Host "[7.1] Task Scheduler Verification" -ForegroundColor Yellow
Write-Host ""

$report += "## 7.1 Task Scheduler Verification`n`n"

$tasks = Get-ScheduledTask -TaskName "HugoTranslator-*" -ErrorAction SilentlyContinue

if ($tasks) {
    $tasksPass = $true
    foreach ($task in $tasks) {
        $taskInfo = Get-ScheduledTaskInfo -TaskName $task.TaskName
        Write-Host "  Task: $($task.TaskName)" -ForegroundColor Cyan
        Write-Host "    State: $($task.State)"
        Write-Host "    Last Run: $($taskInfo.LastRunTime)"
        Write-Host "    Last Result: $($taskInfo.LastTaskResult)"
        Write-Host ""

        $report += "- **Task**: $($task.TaskName)`n"
        $report += "  - State: $($task.State)`n"
        $report += "  - Last Run: $($taskInfo.LastRunTime)`n"
        $report += "  - Last Result: $($taskInfo.LastTaskResult)`n`n"

        if ($task.State -ne "Running" -and $task.State -ne "Ready") {
            Write-Host "  [FAIL] Task is not in Running or Ready state" -ForegroundColor Red
            $tasksPass = $false
        }
    }

    if ($tasksPass) {
        Write-Host "[PASS] 7.1: Task Scheduler configuration verified" -ForegroundColor Green
        $report += "**Result**: PASS`n`n"
    } else {
        Write-Host "[FAIL] 7.1: Some tasks are not properly configured" -ForegroundColor Red
        $report += "**Result**: FAIL - Some tasks not in correct state`n`n"
        $allPassed = $false
    }
} else {
    Write-Host "[FAIL] 7.1: No Hugo Translator tasks found" -ForegroundColor Red
    Write-Host "  Run SETUP_AUTOSTART.bat to create tasks" -ForegroundColor Yellow
    $report += "**Result**: FAIL - No tasks found`n`n"
    $allPassed = $false
}
Write-Host ""

# Check 7.2: Process Verification
Write-Host "[7.2] Process Verification" -ForegroundColor Yellow
Write-Host ""

$report += "## 7.2 Process Verification`n`n"

$workers = Get-Process python -ErrorAction SilentlyContinue |
    Where-Object {
        $cmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId = $($_.Id)" -ErrorAction SilentlyContinue).CommandLine
        $cmdLine -like "*autonomous_content_translation_worker*" -or
        $cmdLine -like "*tm_improvement_worker*"
    }

if ($workers) {
    Write-Host "[PASS] 7.2: Worker processes found" -ForegroundColor Green
    foreach ($worker in $workers) {
        $cmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId = $($worker.Id)").CommandLine
        $workerType = "Unknown"
        if ($cmdLine -like "*autonomous_content_translation_worker*") {
            $workerType = "Content Translation Worker"
        } elseif ($cmdLine -like "*tm_improvement_worker*") {
            $workerType = "TM Improvement Worker"
        }

        Write-Host "  PID $($worker.Id): $workerType" -ForegroundColor Cyan
        $report += "- **PID $($worker.Id)**: $workerType`n"
    }
    $report += "`n**Result**: PASS`n`n"
} else {
    Write-Host "[INFO] 7.2: No worker processes currently running" -ForegroundColor Cyan
    Write-Host "  This is normal between scheduled runs (4x per day)" -ForegroundColor Gray
    Write-Host "  Workers are self-scheduling and will start at next run time" -ForegroundColor Gray
    $report += "**Result**: INFO - No processes running (normal between scheduled runs)`n`n"
}
Write-Host ""

# Check 7.3: Log Verification
Write-Host "[7.3] Log Verification" -ForegroundColor Yellow
Write-Host ""

$report += "## 7.3 Log Verification`n`n"

$logFiles = @(
    @{Name="worker_startup.log"; Path="data\logs\worker_startup.log"},
    @{Name="content_worker_console.log"; Path="data\logs\content_worker_console.log"},
    @{Name="tm_worker_console.log"; Path="data\logs\tm_worker_console.log"},
    @{Name="hugo-translator.ndjson"; Path="data\logs\hugo-translator.ndjson"}
)

$logsPass = $true
foreach ($logFile in $logFiles) {
    $fullPath = Join-Path $projectRoot $logFile.Path
    if (Test-Path $fullPath) {
        $size = (Get-Item $fullPath).Length
        $sizeKB = [math]::Round($size / 1KB, 2)
        Write-Host "  [PASS] $($logFile.Name) ($sizeKB KB)" -ForegroundColor Green

        # Check for errors in startup log
        if ($logFile.Name -eq "worker_startup.log") {
            $content = Get-Content $fullPath -Tail 50 -ErrorAction SilentlyContinue
            $errorCount = ($content | Select-String -Pattern "ERROR|Exception|FAIL").Count
            if ($errorCount -gt 0) {
                Write-Host "    [WARN] Found $errorCount error entries in recent log" -ForegroundColor Yellow
                $logsPass = $false
            }
        }

        $report += "- **$($logFile.Name)**: $sizeKB KB`n"
    } else {
        Write-Host "  [INFO] $($logFile.Name) not created yet" -ForegroundColor Cyan
        $report += "- **$($logFile.Name)**: Not created yet`n"
    }
}

if ($logsPass) {
    Write-Host "[PASS] 7.3: Logs present and no errors found" -ForegroundColor Green
    $report += "`n**Result**: PASS`n`n"
} else {
    Write-Host "[WARN] 7.3: Logs contain errors (see details above)" -ForegroundColor Yellow
    $report += "`n**Result**: WARN - Errors found in logs`n`n"
}
Write-Host ""

# Check 7.4: Git Verification
Write-Host "[7.4] Git Verification" -ForegroundColor Yellow
Write-Host ""

$report += "## 7.4 Git Verification`n`n"

try {
    Set-Location $projectRoot
    $gitLog = git log --oneline -5 2>&1
    if ($gitLog -match "translate|chore") {
        Write-Host "[PASS] 7.4: Recent git commits found with translation messages" -ForegroundColor Green
        Write-Host "  Recent commits:" -ForegroundColor Gray
        $gitLog | ForEach-Object { Write-Host "    $_" -ForegroundColor Gray }
        $report += "**Recent Commits**:`n``````n$gitLog`n```````n`n**Result**: PASS`n`n"
    } else {
        Write-Host "[INFO] 7.4: No recent translation commits found yet" -ForegroundColor Cyan
        Write-Host "  Automated commits will appear after first translation run" -ForegroundColor Gray
        $report += "**Result**: INFO - No translation commits yet (normal for new setup)`n`n"
    }
} catch {
    Write-Host "[WARN] 7.4: Could not check git log" -ForegroundColor Yellow
    $report += "**Result**: WARN - Could not verify git`n`n"
}
Write-Host ""

# Check 7.5: GPU Verification
Write-Host "[7.5] GPU Verification" -ForegroundColor Yellow
Write-Host ""

$report += "## 7.5 GPU Verification`n`n"

$structuredLog = Join-Path $projectRoot "data\logs\hugo-translator.ndjson"
if (Test-Path $structuredLog) {
    $vramEntries = Select-String -Path $structuredLog -Pattern "VRAM|GPU|gpu_memory" | Select-Object -Last 5
    if ($vramEntries) {
        Write-Host "[PASS] 7.5: GPU/VRAM management messages found in logs" -ForegroundColor Green
        Write-Host "  Recent GPU log entries:" -ForegroundColor Gray
        $vramEntries | ForEach-Object { Write-Host "    $_" -ForegroundColor Gray }
        $report += "**GPU Log Entries Found**: Yes`n`n**Result**: PASS`n`n"
    } else {
        Write-Host "[INFO] 7.5: No GPU entries in logs yet" -ForegroundColor Cyan
        Write-Host "  GPU management messages will appear during translation runs" -ForegroundColor Gray
        $report += "**Result**: INFO - No GPU entries yet`n`n"
    }
} else {
    Write-Host "[INFO] 7.5: Structured log not created yet" -ForegroundColor Cyan
    $report += "**Result**: INFO - Log file not created yet`n`n"
}
Write-Host ""

# Overall Summary
Write-Host "=============================================================================" -ForegroundColor Cyan
if ($allPassed) {
    Write-Host "Verification: PASSED" -ForegroundColor Green
    Write-Host ""
    Write-Host "Autonomous operation is correctly configured!" -ForegroundColor Green
    $report += "## Overall Result: PASSED`n`n"
    $report += "Autonomous operation is correctly configured.`n"
} else {
    Write-Host "Verification: FAILED" -ForegroundColor Red
    Write-Host ""
    Write-Host "Some verification checks failed (see details above)" -ForegroundColor Red
    $report += "## Overall Result: FAILED`n`n"
    $report += "Some verification checks failed. See details above.`n"
}
Write-Host "=============================================================================" -ForegroundColor Cyan
Write-Host ""

# Save report
$reportPath = Join-Path $projectRoot "reports\autonomous_operation_verification_$(Get-Date -Format 'yyyyMMdd_HHmmss').md"
$report | Out-File -FilePath $reportPath -Encoding utf8
Write-Host "Verification report saved to:" -ForegroundColor Cyan
Write-Host "  $reportPath" -ForegroundColor White
Write-Host ""
