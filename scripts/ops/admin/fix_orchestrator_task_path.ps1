# fix_orchestrator_task_path.ps1
#
# Fixes the "HugoTranslatorGitlab-Orchestrator" scheduled task, which has
# been pointing at a stale sibling clone (hugo-translator-gitlab, last
# touched 2026-07-04) instead of the active repo (hugo-translator) since at
# least that date. The task's logon trigger has been firing on every reboot
# and failing with ERROR_FILE_NOT_FOUND (LastTaskResult 2147942402) instead
# of relaunching the worker orchestrator -- confirmed as a contributing
# factor in three multi-hour outages this session (2026-07-17, 2026-07-18 x2)
# where nothing auto-resumed after a reboot.
#
# This also points the task at the new scripts/ops/startup_recovery.py
# wrapper instead of calling worker_orchestrator directly, so a single
# logon trigger recovers BOTH the production worker system (content_worker,
# tm_improvement_worker, verification_worker) AND the ad-hoc GPU heal
# campaign infrastructure (.local/scheduler.py, thermal_watchdog.py) that
# previously had no recovery mechanism at all.
#
# Usage:
#   # Dry-run (shows current + planned state, no changes, no admin needed):
#   powershell -ExecutionPolicy Bypass -File scripts/ops/admin/fix_orchestrator_task_path.ps1 -Mode dry-run
#
#   # Apply (requires admin / UAC):
#   Start-Process powershell -Verb RunAs -ArgumentList '-ExecutionPolicy Bypass', '-File', 'scripts/ops/admin/fix_orchestrator_task_path.ps1', '-Mode', 'apply'

param(
    [ValidateSet('dry-run', 'apply')]
    [string]$Mode = 'dry-run',

    [string]$TaskName = 'HugoTranslatorGitlab-Orchestrator'
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
$CorrectPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$CorrectScript = 'scripts\ops\startup_recovery.py'

Write-Host "=== Orchestrator Scheduled Task Path Fix ===" -ForegroundColor Cyan
Write-Host "Mode:     $Mode"
Write-Host "TaskName: $TaskName"
Write-Host ""

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Host "[ERROR] Task '$TaskName' not found." -ForegroundColor Red
    exit 1
}

$info = Get-ScheduledTaskInfo -TaskName $TaskName
$currentAction = $task.Actions | Select-Object -First 1

Write-Host "--- Current State ---" -ForegroundColor Yellow
Write-Host "Execute:          $($currentAction.Execute)"
Write-Host "Arguments:        $($currentAction.Arguments)"
Write-Host "WorkingDirectory: $($currentAction.WorkingDirectory)"
Write-Host "LastTaskResult:   $($info.LastTaskResult)  (2147942402 = ERROR_FILE_NOT_FOUND)"
Write-Host "LastRunTime:      $($info.LastRunTime)"
Write-Host ""

Write-Host "--- Planned State ---" -ForegroundColor Yellow
Write-Host "Execute:          $CorrectPython"
Write-Host "Arguments:        $CorrectScript"
Write-Host "WorkingDirectory: $ProjectRoot"
Write-Host ""

if ($Mode -eq 'dry-run') {
    Write-Host "DRY-RUN complete. No changes applied." -ForegroundColor Green
    exit 0
}

if (-not (Test-Path $CorrectPython)) {
    Write-Host "[ERROR] $CorrectPython does not exist -- refusing to apply." -ForegroundColor Red
    exit 1
}

$newAction = New-ScheduledTaskAction -Execute $CorrectPython -Argument $CorrectScript -WorkingDirectory $ProjectRoot
Set-ScheduledTask -TaskName $TaskName -Action $newAction | Out-Null

Write-Host "--- After ---" -ForegroundColor Yellow
$after = (Get-ScheduledTask -TaskName $TaskName).Actions | Select-Object -First 1
Write-Host "Execute:          $($after.Execute)"
Write-Host "Arguments:        $($after.Arguments)"
Write-Host "WorkingDirectory: $($after.WorkingDirectory)"
Write-Host ""
Write-Host "Done. Task will now correctly recover the full stack (worker_orchestrator + .local/scheduler.py + thermal_watchdog.py) on next logon." -ForegroundColor Green
