# start_workers.ps1 — Detached worker startup for Windows
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\start_workers.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\start_workers.ps1 -TmWorker
#
# Uses Start-Process for true Windows process detachment — survives parent shell exit.
# Idempotent: kills old workers by PID file before starting fresh ones.
# Includes --run-immediately so the worker runs once before sleeping to next slot.

param(
    [switch]$TmWorker,    # Also start the TM improvement worker
    [switch]$NoImmediate  # Skip --run-immediately (wait for first scheduled slot)
)

$project = Split-Path $PSScriptRoot -Parent
$python  = "$project\.venv\Scripts\python.exe"
$logsDir = "$project\data\logs"

if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
}

function Start-Worker {
    param($Name, [string[]]$WorkerArgs, $LogFile, $ErrFile, $PidFile, $SelfPidFile = $null)

    # Kill processes from ALL known PID files to prevent duplicate workers
    $killed = $false
    foreach ($pf in @($PidFile, $SelfPidFile) | Where-Object { $_ -ne $null }) {
        if (Test-Path $pf) {
            $oldPid = [int](Get-Content $pf -ErrorAction SilentlyContinue)
            if ($oldPid -gt 0) {
                $existing = Get-Process -Id $oldPid -ErrorAction SilentlyContinue
                if ($existing) {
                    Write-Host "Stopping $Name (PID $oldPid from $(Split-Path $pf -Leaf))..."
                    Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue
                    $killed = $true
                }
            }
            Remove-Item $pf -ErrorAction SilentlyContinue
        }
    }
    if ($killed) { Start-Sleep 2 }

    $proc = Start-Process `
        -FilePath $python `
        -ArgumentList $WorkerArgs `
        -WorkingDirectory $project `
        -RedirectStandardOutput $LogFile `
        -RedirectStandardError $ErrFile `
        -WindowStyle Hidden `
        -PassThru

    Start-Sleep 3
    if ($proc.HasExited) {
        Write-Host "ERROR: $Name exited immediately (exit code $($proc.ExitCode)). Check $ErrFile"
        return
    }

    $proc.Id | Out-File $PidFile -Encoding ascii -NoNewline
    Write-Host "$Name started: PID $($proc.Id)"
}

# --- Content Worker ---
$contentArgs = @(
    "-m", "src.workers.autonomous_content_translation_worker",
    "--mode", "daemon",
    "--runs-per-day", "12",
    "--window-start", "07:00",
    "--window-end", "23:00",
    "--timezone", "Asia/Karachi",
    "--jitter-minutes", "15",
    "--device", "cuda",
    "--max-gpu-memory-percent", "50",
    "--file-timeout-seconds", "600",
    "--max-seconds-per-run", "3600",
    "--log-level", "INFO"
)
if (-not $NoImmediate) {
    $contentArgs += "--run-immediately"
}

Start-Worker `
    -Name "content_worker" `
    -WorkerArgs $contentArgs `
    -LogFile "$logsDir\content_worker.log" `
    -ErrFile "$logsDir\content_worker_err.log" `
    -PidFile "$logsDir\content_worker_daemon.pid" `
    -SelfPidFile "$logsDir\content_worker.pid"

# --- TM Worker (optional) ---
if ($TmWorker) {
    $tmArgs = @(
        "-m", "src.workers.tm_improvement_worker",
        "--mode", "daemon",
        "--runs-per-day", "4",
        "--window-start", "08:00",
        "--window-end", "23:00",
        "--timezone", "Asia/Karachi",
        "--jitter-minutes", "15",
        "--device", "cuda",
        "--max-gpu-memory-percent", "50",
        "--candidates-per-run", "50",
        "--max-llm-calls-per-run", "200",
        "--max-seconds-per-run", "900",
        "--log-level", "INFO"
    )
    Start-Worker `
        -Name "tm_worker" `
        -WorkerArgs $tmArgs `
        -LogFile "$logsDir\tm_worker.log" `
        -ErrFile "$logsDir\tm_worker_err.log" `
        -PidFile "$logsDir\tm_worker_daemon.pid" `
        -SelfPidFile "$logsDir\tm_worker.pid"
}

Write-Host ""
Write-Host "Done. Monitor with: Get-Content '$logsDir\content_worker.log' -Wait -Tail 20"
