<#
.SYNOPSIS
  TC-APT-048 -- OS-level liveness watchdog for the aspose-org-full-portfolio-translation-20260901
  mission loop (plan §0.4). Registered as a Windows Scheduled Task so it survives the loop's own
  hosting process/terminal going away -- exactly the failure mode confirmed on 2026-09-04 (the
  session's last action was a clean, successful ScheduleWakeup call; the scheduled wake never fired
  because the hosting process was gone).

.DESCRIPTION
  Every time this script runs it:
    1. Skips if a previously-launched relaunch is still running (lock file + live PID).
    2. Computes "minutes since last mission activity" from the more recent of the mission branch's
       last commit and the taskcard_status.json mtime.
    3. If idle beyond the threshold, resumes the mission's Claude Code session headlessly
       (`claude --resume <id> -p ... --permission-mode bypassPermissions`) for exactly one bounded
       iteration, and writes a lock file so overlapping relaunches can't happen.
  This does not replace the loop's own ScheduleWakeup pacing -- it is a backstop that only acts when
  that pacing has stopped producing activity for longer than a normal wake cycle should ever take.

.PARAMETER DryRun
  Log what would happen (idle time, decision) without actually launching claude. Safe to run any time.
#>

param(
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

$RepoRoot          = "c:\Users\prora\OneDrive\Documents\GitHub\hugo-translator"
$MissionBranch     = "mission/aspose-org-full-portfolio-translation-20260901"
$MissionId         = "aspose-org-full-portfolio-translation-20260901"
$SessionId         = "d18689cf-ac87-4bcb-b33f-655ef2b84358"
$TaskcardStatus    = Join-Path $RepoRoot ".supervisor\state\$MissionId\taskcard_status.json"
$LogDir            = Join-Path $RepoRoot "logs"
$LogFile           = Join-Path $LogDir "watchdog.log"
$LockFile          = Join-Path $LogDir "watchdog.lock"
$IdleThresholdMinutes = 8

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-Log {
    param([string]$Message)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$ts  $Message" | Add-Content -Path $LogFile -Encoding utf8
}

Set-Location $RepoRoot

# --- 1. Is a previously-launched relaunch still running? ---
if (Test-Path $LockFile) {
    $lockedPid = Get-Content $LockFile -ErrorAction SilentlyContinue | Select-Object -First 1
    $existing = if ($lockedPid) { Get-Process -Id $lockedPid -ErrorAction SilentlyContinue } else { $null }
    if ($existing) {
        Write-Log "Relaunch already in flight (PID $lockedPid, $($existing.ProcessName)). Skipping this check."
        return
    } else {
        Write-Log "Stale lock file (PID $lockedPid not running). Clearing it."
        Remove-Item $LockFile -Force -ErrorAction SilentlyContinue
    }
}

# --- 2. Compute idle time from the two cheapest, most reliable liveness signals ---
$lastCommitEpoch = git -C $RepoRoot log -1 --format=%ct $MissionBranch 2>$null
$lastCommitTime = if ($lastCommitEpoch) {
    [DateTimeOffset]::FromUnixTimeSeconds([int64]$lastCommitEpoch).LocalDateTime
} else {
    Get-Date "1970-01-01"
}

$taskcardTime = if (Test-Path $TaskcardStatus) {
    (Get-Item $TaskcardStatus).LastWriteTime
} else {
    Get-Date "1970-01-01"
}

$lastActivity = if ($lastCommitTime -gt $taskcardTime) { $lastCommitTime } else { $taskcardTime }
$idleMinutes = (New-TimeSpan -Start $lastActivity -End (Get-Date)).TotalMinutes

Write-Log ("Last commit: {0:yyyy-MM-dd HH:mm:ss} | taskcard_status.json mtime: {1:yyyy-MM-dd HH:mm:ss} | idle: {2:N1} min" -f $lastCommitTime, $taskcardTime, $idleMinutes)

if ($idleMinutes -lt $IdleThresholdMinutes) {
    Write-Log "Within threshold ($IdleThresholdMinutes min). No action."
    return
}

Write-Log ("Idle {0:N1} min >= threshold ($IdleThresholdMinutes min)." -f $idleMinutes)

if ($DryRun) {
    Write-Log "DryRun: would relaunch session $SessionId now. Taking no action."
    return
}

# --- 3. Relaunch the stalled session headlessly for exactly one bounded iteration ---
$resumePrompt = "Continue the aspose.org mission per project/loop-prompt.md. Run exactly one bounded iteration and exit."

$stdOutLog = Join-Path $LogDir "watchdog_relaunch_stdout.log"
$stdErrLog = Join-Path $LogDir "watchdog_relaunch_stderr.log"

$proc = Start-Process -FilePath "claude" `
    -ArgumentList @("--resume", $SessionId, "-p", $resumePrompt, "--permission-mode", "bypassPermissions") `
    -WorkingDirectory $RepoRoot `
    -RedirectStandardOutput $stdOutLog `
    -RedirectStandardError $stdErrLog `
    -WindowStyle Hidden `
    -PassThru

$proc.Id | Set-Content -Path $LockFile -Encoding ascii
Write-Log "Relaunched session $SessionId as PID $($proc.Id). stdout/stderr -> $stdOutLog / $stdErrLog"
