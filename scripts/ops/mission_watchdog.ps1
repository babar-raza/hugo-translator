<#
.SYNOPSIS
  TC-APT-048 + TC-APT-054/055 (v2) -- OS-level supervisor for the
  aspose-org-full-portfolio-translation-20260901 mission (plan §0.4/§0.6).

.DESCRIPTION
  v1 (TC-APT-048): idle-detect on the mission branch and headlessly resume ONE hardcoded session.
  v2 adds the two capabilities plan §0.6 identified as the remaining total-stall / silent-stall modes:

  1. MISSION-ANCHORED RECOVERY (TC-APT-054, closes G-33): the watchdog tracks progress between its
     own relaunches in logs/watchdog_state.json. If 2 consecutive relaunches produce no progress
     (no new mission-branch commit AND no taskcard_status.json mtime advance), it stops resuming
     the stored session and COLD-BOOTS a fresh session from the repo's own file state (which is
     fully sufficient by design), then adopts the newest transcript's session id as the future
     resume target.

  2. THROUGHPUT KPI (TC-APT-055, closes G-34): every run counts translated-locale files landed in
     the CONTENT repo over the trailing 24h. Liveness (commits of any kind) is no longer read as
     progress. If the count stays below the floor for a sustained window, one THROUGHPUT_BREACH
     row is appended to data/campaigns/ops_queue.jsonl, which the runbook reads FIRST every wake.

.PARAMETER DryRun
  Log decisions without launching anything or writing ops_queue. Safe any time.
#>

param(
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

$RepoRoot          = "c:\Users\prora\OneDrive\Documents\GitHub\hugo-translator"
$ContentRepo       = "D:\onedrive\Documents\GitHub\aspose.org"
$MissionBranch     = "mission/aspose-org-full-portfolio-translation-20260901"
$MissionId         = "aspose-org-full-portfolio-translation-20260901"
$DefaultSessionId  = "d18689cf-ac87-4bcb-b33f-655ef2b84358"
$TranscriptDir     = "C:\Users\prora\.claude\projects\c--Users-prora-OneDrive-Documents-GitHub-hugo-translator"
$ClaudeExe         = "C:/Users/prora/AppData/Roaming/npm/node_modules/@anthropic-ai/claude-code/bin/claude.exe"
$TaskcardStatus    = Join-Path $RepoRoot ".supervisor\state\$MissionId\taskcard_status.json"
$LogDir            = Join-Path $RepoRoot "logs"
$LogFile           = Join-Path $LogDir "watchdog.log"
$LockFile          = Join-Path $LogDir "watchdog.lock"
$StateFile         = Join-Path $LogDir "watchdog_state.json"
$OpsQueue          = Join-Path $RepoRoot "data\campaigns\ops_queue.jsonl"
$IdleThresholdMinutes = 8
$NoProgressRelaunchLimit = 2
$KpiFloorCells24h  = 25
$KpiBreachWindowHours = 6

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-Log {
    param([string]$Message)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$ts  $Message" | Add-Content -Path $LogFile -Encoding utf8
}

function Load-State {
    if (Test-Path $StateFile) {
        try { return Get-Content $StateFile -Raw | ConvertFrom-Json } catch { }
    }
    return [pscustomobject]@{
        target_session_id = $DefaultSessionId
        last_progress_commit = ""
        last_progress_taskcard_mtime = ""
        consecutive_relaunches_without_progress = 0
        kpi_cells_24h = -1
        kpi_below_floor_since = ""
        kpi_breach_open = $false
    }
}

function Save-State { param($s) $s | ConvertTo-Json | Set-Content -Path $StateFile -Encoding utf8 }

Set-Location $RepoRoot
$state = Load-State

# ---------------------------------------------------------------------------
# THROUGHPUT KPI (TC-APT-055): translated-locale files landed in content repo,
# trailing 24h. Counts added/modified files shaped like a locale target:
# index.<lang>.md (suffix layout) or /<lang>/....md with lang in the 25-set.
# ---------------------------------------------------------------------------
$langAlt = "ar|cs|de|el|es|fa|fr|he|hi|hu|id|it|ja|ko|nl|pl|pt|ro|ru|sv|th|tr|uk|vi|zh"
$kpiCount = 0
try {
    $files = git -C $ContentRepo log --since="24 hours ago" --name-only --pretty=format: -- content/ 2>$null |
        Where-Object { $_ -match "^content/" } | Sort-Object -Unique
    foreach ($f in $files) {
        if ($f -match "index\.($langAlt)\.md$") { $kpiCount++ }
        elseif ($f -match "^content/[^/]+/($langAlt)/.+\.md$") { $kpiCount++ }
    }
} catch { Write-Log "KPI: content-repo log failed: $($_.Exception.Message)" }
$state.kpi_cells_24h = $kpiCount

$now = Get-Date
if ($kpiCount -lt $KpiFloorCells24h) {
    if (-not $state.kpi_below_floor_since) {
        $state.kpi_below_floor_since = $now.ToString("o")
    } else {
        $since = [datetime]::Parse($state.kpi_below_floor_since)
        $hoursBelow = ($now - $since).TotalHours
        if ($hoursBelow -ge $KpiBreachWindowHours -and -not $state.kpi_breach_open) {
            $row = @{
                type = "THROUGHPUT_BREACH"; opened_at = $now.ToString("o")
                cells_24h = $kpiCount; floor = $KpiFloorCells24h
                below_floor_hours = [math]::Round($hoursBelow,1); status = "OPEN"
                required_action = "runbook SS2 item 0: write a SS10.1 first-principles record on the loop's own strategy, reference it here, set status CLOSED"
            } | ConvertTo-Json -Compress
            if ($DryRun) { Write-Log "KPI DryRun: would append THROUGHPUT_BREACH ($kpiCount cells/24h, ${hoursBelow}h below floor)." }
            else {
                New-Item -ItemType Directory -Force -Path (Split-Path $OpsQueue) | Out-Null
                Add-Content -Path $OpsQueue -Value $row -Encoding utf8
                $state.kpi_breach_open = $true
                Write-Log "KPI: THROUGHPUT_BREACH appended ($kpiCount cells/24h, $([math]::Round($hoursBelow,1))h below floor $KpiFloorCells24h)."
            }
        }
    }
} else {
    $state.kpi_below_floor_since = ""
    $state.kpi_breach_open = $false
}
Write-Log "KPI: $kpiCount translated-locale files in content repo, trailing 24h (floor $KpiFloorCells24h)."

# ---------------------------------------------------------------------------
# In-flight relaunch check (unchanged from v1)
# ---------------------------------------------------------------------------
if (Test-Path $LockFile) {
    $lockedPid = Get-Content $LockFile -ErrorAction SilentlyContinue | Select-Object -First 1
    $existing = $null
    if ($lockedPid) { $existing = Get-Process -Id $lockedPid -ErrorAction SilentlyContinue }
    if ($existing) {
        Write-Log "Relaunch already in flight (PID $lockedPid). Skipping."
        Save-State $state
        return
    } else {
        Remove-Item $LockFile -Force -ErrorAction SilentlyContinue
    }
}

# ---------------------------------------------------------------------------
# Idle detection (v1) + progress accounting between relaunches (TC-APT-054)
# ---------------------------------------------------------------------------
$headSha = (git -C $RepoRoot rev-parse $MissionBranch 2>$null)
$lastCommitEpoch = git -C $RepoRoot log -1 --format=%ct $MissionBranch 2>$null
$lastCommitTime = Get-Date "1970-01-01"
if ($lastCommitEpoch) { $lastCommitTime = [DateTimeOffset]::FromUnixTimeSeconds([int64]$lastCommitEpoch).LocalDateTime }
$taskcardTime = Get-Date "1970-01-01"
if (Test-Path $TaskcardStatus) { $taskcardTime = (Get-Item $TaskcardStatus).LastWriteTime }
$taskcardMtimeStr = $taskcardTime.ToString("o")

$lastActivity = $lastCommitTime
if ($taskcardTime -gt $lastActivity) { $lastActivity = $taskcardTime }
$idleMinutes = ((Get-Date) - $lastActivity).TotalMinutes
Write-Log ("Idle {0:N1} min | HEAD {1} | target session {2} | no-progress relaunches {3}" -f $idleMinutes, $headSha.Substring(0,7), $state.target_session_id.Substring(0,8), $state.consecutive_relaunches_without_progress)

if ($idleMinutes -lt $IdleThresholdMinutes) {
    # Activity since our last relaunch counts as progress: reset the counter.
    if ($headSha -ne $state.last_progress_commit -or $taskcardMtimeStr -ne $state.last_progress_taskcard_mtime) {
        $state.consecutive_relaunches_without_progress = 0
        $state.last_progress_commit = $headSha
        $state.last_progress_taskcard_mtime = $taskcardMtimeStr
    }
    Write-Log "Within threshold. No action."
    Save-State $state
    return
}

# Idle beyond threshold. Did the PREVIOUS relaunch produce any progress?
if ($headSha -eq $state.last_progress_commit -and $taskcardMtimeStr -eq $state.last_progress_taskcard_mtime) {
    # no progress since last relaunch marker (counter increments below on relaunch)
} else {
    $state.consecutive_relaunches_without_progress = 0
}
$state.last_progress_commit = $headSha
$state.last_progress_taskcard_mtime = $taskcardMtimeStr

$coldBoot = ($state.consecutive_relaunches_without_progress -ge $NoProgressRelaunchLimit)

if ($DryRun) {
    if ($coldBoot) { Write-Log "DryRun: would COLD-BOOT a fresh session (resume produced no progress $($state.consecutive_relaunches_without_progress)x)." }
    else { Write-Log "DryRun: would resume session $($state.target_session_id)." }
    Save-State $state
    return
}

$stdOutLog = Join-Path $LogDir "watchdog_relaunch_stdout.log"
$stdErrLog = Join-Path $LogDir "watchdog_relaunch_stderr.log"

if ($coldBoot) {
    # -----------------------------------------------------------------------
    # TC-APT-054: resume path is dead -- cold-boot a fresh session from files.
    # -----------------------------------------------------------------------
    Write-Log "COLD-BOOT: $($state.consecutive_relaunches_without_progress) consecutive no-progress relaunches of $($state.target_session_id). Starting a fresh session from repo state."
    $bootstrapPrompt = "You are executing the approved Aspose.org full-portfolio translation mission (mission ID $MissionId) from the hugo-translator repo ($RepoRoot) on branch $MissionBranch. This is a cold-boot recovery: a prior session became unresumable, and the mission's entire state lives in files. Read project/loop-prompt.md in that repo in full - it is the runbook of record - then run exactly one bounded iteration of it and exit. Never push, merge to main, deploy, delete content, touch www.aspose.org, or bypass a hook."
    $before = @(Get-ChildItem $TranscriptDir -Filter "*.jsonl" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name)
    $proc = Start-Process -FilePath $ClaudeExe `
        -ArgumentList @("-p", $bootstrapPrompt, "--permission-mode", "bypassPermissions") `
        -WorkingDirectory $RepoRoot -RedirectStandardOutput $stdOutLog -RedirectStandardError $stdErrLog `
        -WindowStyle Hidden -PassThru
    $proc.Id | Set-Content -Path $LockFile -Encoding ascii
    Start-Sleep -Seconds 20
    $newFile = Get-ChildItem $TranscriptDir -Filter "*.jsonl" -ErrorAction SilentlyContinue |
        Where-Object { $before -notcontains $_.Name } |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($newFile) {
        $state.target_session_id = [System.IO.Path]::GetFileNameWithoutExtension($newFile.Name)
        Write-Log "COLD-BOOT: fresh session $($state.target_session_id) adopted as new resume target (PID $($proc.Id))."
    } else {
        Write-Log "COLD-BOOT: fresh session launched (PID $($proc.Id)) but no new transcript detected yet; keeping old target for now."
    }
    $state.consecutive_relaunches_without_progress = 0
} else {
    $resumePrompt = "Continue the aspose.org mission per project/loop-prompt.md. Run exactly one bounded iteration and exit."
    $proc = Start-Process -FilePath $ClaudeExe `
        -ArgumentList @("--resume", $state.target_session_id, "-p", $resumePrompt, "--permission-mode", "bypassPermissions") `
        -WorkingDirectory $RepoRoot -RedirectStandardOutput $stdOutLog -RedirectStandardError $stdErrLog `
        -WindowStyle Hidden -PassThru
    $proc.Id | Set-Content -Path $LockFile -Encoding ascii
    $state.consecutive_relaunches_without_progress = [int]$state.consecutive_relaunches_without_progress + 1
    Write-Log "Relaunched session $($state.target_session_id) as PID $($proc.Id) (no-progress streak now $($state.consecutive_relaunches_without_progress); cold-boot at $NoProgressRelaunchLimit)."
}

Save-State $state
