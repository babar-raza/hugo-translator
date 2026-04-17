$logFile = Join-Path $PSScriptRoot "..\data\logs\scheduler_setup.log"
$setupScript = Join-Path $PSScriptRoot "setup_task_scheduler.ps1"

try {
    & $setupScript *>&1 | Tee-Object -FilePath $logFile
} catch {
    "ERROR: $_" | Out-File -FilePath $logFile -Append
    Write-Host "ERROR: $_" -ForegroundColor Red
}
