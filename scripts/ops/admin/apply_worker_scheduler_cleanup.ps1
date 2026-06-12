# apply_worker_scheduler_cleanup.ps1
# TC-14: Idempotent script to disable/enable HugoTranslator Task Scheduler tasks.
#
# Usage:
#   # Dry-run (no changes, no admin needed):
#   powershell -ExecutionPolicy Bypass -File scripts/ops/admin/apply_worker_scheduler_cleanup.ps1 -Mode dry-run -WorkersToDisable ContentWorker,TMWorker,AutonomousVerification
#
#   # Apply (requires admin / UAC):
#   Start-Process powershell -Verb RunAs -ArgumentList '-ExecutionPolicy Bypass', '-File', 'scripts/ops/admin/apply_worker_scheduler_cleanup.ps1', '-Mode', 'apply', '-WorkersToDisable', 'ContentWorker,TMWorker,AutonomousVerification'

param(
    [ValidateSet('dry-run', 'apply')]
    [string]$Mode = 'dry-run',

    [string[]]$WorkersToDisable = @(),

    [string]$RunId = (Get-Date -Format 'yyyyMMdd-HHmmss'),

    [string]$TaskPath = '\'
)

# Handle comma-separated string passed from CLI (e.g., "A,B,C" -> @("A","B","C"))
if ($WorkersToDisable.Count -eq 1 -and $WorkersToDisable[0] -match ',') {
    $WorkersToDisable = $WorkersToDisable[0] -split ','
}

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$ReportDir = Join-Path $ProjectRoot "workspace\runs\$RunId"

if (-not (Test-Path $ReportDir)) {
    New-Item -ItemType Directory -Path $ReportDir -Force | Out-Null
}

Write-Host "=== Worker Scheduler Cleanup ===" -ForegroundColor Cyan
Write-Host "Mode:     $Mode"
Write-Host "RunId:    $RunId"
Write-Host "TaskPath: $TaskPath"
Write-Host "Workers:  $($WorkersToDisable -join ', ')"
Write-Host "Report:   $ReportDir"
Write-Host ""

# 1. Capture before-state
Write-Host "--- Before State ---" -ForegroundColor Yellow
try {
    $before = Get-ScheduledTask -TaskPath $TaskPath -ErrorAction Stop
    $beforeTable = $before | Format-Table TaskName, State -AutoSize | Out-String
    Write-Host $beforeTable
    $beforeTable | Out-File (Join-Path $ReportDir "scheduler_before.txt") -Encoding utf8
} catch {
    Write-Host "[ERROR] Cannot read Task Scheduler (TaskPath=$TaskPath): $_" -ForegroundColor Red
    Write-Host "  This may mean:" -ForegroundColor Yellow
    Write-Host "    1. The task path does not exist" -ForegroundColor Yellow
    Write-Host "    2. Admin elevation is needed" -ForegroundColor Yellow
    Write-Host "    3. Tasks were never registered" -ForegroundColor Yellow
    "[ERROR] Cannot read Task Scheduler: $_" | Out-File (Join-Path $ReportDir "scheduler_before.txt") -Encoding utf8
    exit 1
}

# 2. Plan changes
Write-Host "--- Planned Changes ---" -ForegroundColor Yellow
$changes = @()
foreach ($taskName in $WorkersToDisable) {
    $current = $before | Where-Object { $_.TaskName -eq $taskName }
    if ($null -eq $current) {
        Write-Host "[SKIP] $taskName -- not found in Task Scheduler" -ForegroundColor DarkYellow
        $changes += @{ Task = $taskName; Action = 'SKIP'; Reason = 'not found' }
    } elseif ($current.State.ToString() -eq 'Disabled') {
        Write-Host "[SKIP] $taskName -- already Disabled" -ForegroundColor DarkGray
        $changes += @{ Task = $taskName; Action = 'SKIP'; Reason = 'already disabled' }
    } else {
        Write-Host "[PLAN] Disable: $taskName (currently $($current.State))" -ForegroundColor White
        $changes += @{ Task = $taskName; Action = 'DISABLE'; Reason = "was $($current.State)" }
    }
}

if ($Mode -eq 'dry-run') {
    Write-Host ""
    Write-Host "DRY-RUN complete. No changes applied." -ForegroundColor Green
    # Write report
    $report = @"
# Scheduler Cleanup Report (dry-run)
# Run ID: $RunId
# Date: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')

## Planned changes:
$($changes | ForEach-Object { "- $($_.Task): $($_.Action) ($($_.Reason))" } | Out-String)
"@
    $report | Out-File (Join-Path $ReportDir "scheduler_cleanup_report.md") -Encoding utf8
    exit 0
}

# 3. Apply changes (admin required)
Write-Host ""
Write-Host "--- Applying Changes ---" -ForegroundColor Yellow
$applied = @()
foreach ($change in $changes) {
    if ($change.Action -ne 'DISABLE') { continue }
    $taskName = $change.Task
    try {
        Disable-ScheduledTask -TaskName $taskName -TaskPath $TaskPath -ErrorAction Stop
        Write-Host "[APPLIED] Disabled: $taskName" -ForegroundColor Green
        $applied += $taskName
    } catch {
        Write-Host "[FAILED] Could not disable ${taskName}: $_" -ForegroundColor Red
    }
}

# 4. Capture after-state
Write-Host ""
Write-Host "--- After State ---" -ForegroundColor Yellow
try {
    $after = Get-ScheduledTask -TaskPath $TaskPath -ErrorAction Stop
    $afterTable = $after | Format-Table TaskName, State -AutoSize | Out-String
    Write-Host $afterTable
    $afterTable | Out-File (Join-Path $ReportDir "scheduler_after.txt") -Encoding utf8
} catch {
    Write-Host "[WARN] Cannot read after-state: $_" -ForegroundColor Yellow
}

# 5. Write report
$report = @"
# Scheduler Cleanup Report
# Run ID: $RunId
# Date: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
# Mode: $Mode

## Changes applied:
$($applied | ForEach-Object { "- Disabled: $_" } | Out-String)

## All planned changes:
$($changes | ForEach-Object { "- $($_.Task): $($_.Action) ($($_.Reason))" } | Out-String)
"@
$report | Out-File (Join-Path $ReportDir "scheduler_cleanup_report.md") -Encoding utf8

Write-Host ""
Write-Host "Done. $($applied.Count) task(s) disabled. Reports in: $ReportDir" -ForegroundColor Green
