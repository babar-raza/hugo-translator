<#
.SYNOPSIS
TC-PORT-LLM-012: reusable campaign-process detection and orphan cleanup.

.DESCRIPTION
start_portfolio_missing_sweep_autonomous.ps1's own Test-CampaignLive answers
"is a campaign process already live" (a refuse-to-double-launch guard) but
nothing anywhere acts on a HUNG orphan -- confirmed: the launcher
(Start-Process, no job-object/breakaway wiring) is a plain child process, so
killing only its parent (rather than a full reboot) leaves it and its gate5
worker grandchildren running untracked, and every subsequent scheduled run
just refuses to start forever with no alert beyond a generic task failure.

Dot-source this file to get:
  Get-CampaignLiveProcesses [-CampaignId <string>]
      Returns one object per live launcher/worker process: ProcessId,
      ParentProcessId, CommandLine, CreationDate, AgeMinutes. Optionally
      filtered to processes whose command line contains -CampaignId, for a
      host running more than one campaign.

  Stop-CampaignOrphanProcesses -Processes <object[]> -Reason <string> [-LogPath <string>]
      Hard-kills (Stop-Process -Force) every process passed in, logging
      PID/command-line/age/reason to -LogPath first (if given) so the
      evidence bundle shows what was cleaned up and why -- never a silent
      kill. Does not decide what counts as "orphaned"; the caller (the
      TC-PORT-LLM-014 watchdog) makes that call using AgeMinutes plus its own
      liveness/progress cross-check, because a process merely existing is not
      evidence it is hung (a fresh launch can legitimately take 90-120s
      before its first log line, per project/loop-prompt.md field notes).
#>

function Get-CampaignLiveProcesses {
    [CmdletBinding()]
    param(
        [string]$CampaignId
    )
    $now = Get-Date
    $matches = @(Get-CimInstance Win32_Process | Where-Object {
        $_.Name -match '^python(?:\.exe)?$' -and
        $_.CommandLine -match 'launch_parallel_campaign_shards\.py|run_gate5_batch\.py' -and
        $_.ProcessId -ne $PID -and
        (-not $CampaignId -or $_.CommandLine -match [regex]::Escape($CampaignId))
    })
    foreach ($proc in $matches) {
        $created = $proc.CreationDate
        $ageMinutes = if ($created) { [math]::Round((New-TimeSpan -Start $created -End $now).TotalMinutes, 1) } else { $null }
        [pscustomobject]@{
            ProcessId       = $proc.ProcessId
            ParentProcessId = $proc.ParentProcessId
            CommandLine     = $proc.CommandLine
            CreationDate    = $created
            AgeMinutes      = $ageMinutes
            Role            = if ($proc.CommandLine -match 'launch_parallel_campaign_shards\.py') { 'launcher' } else { 'worker' }
        }
    }
}

function Stop-CampaignOrphanProcesses {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [object[]]$Processes,
        [Parameter(Mandatory)] [string]$Reason,
        [string]$LogPath
    )
    $stopped = @()
    foreach ($proc in $Processes) {
        $entry = "$(Get-Date -Format o) orphan_kill pid=$($proc.ProcessId) role=$($proc.Role) age_minutes=$($proc.AgeMinutes) reason=`"$Reason`" cmdline=`"$($proc.CommandLine)`""
        if ($LogPath) {
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $LogPath) -ErrorAction SilentlyContinue | Out-Null
            $entry | Add-Content -LiteralPath $LogPath
        } else {
            Write-Warning $entry
        }
        try {
            Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
            $stopped += $proc.ProcessId
        } catch {
            $failMsg = "$(Get-Date -Format o) orphan_kill_failed pid=$($proc.ProcessId) error=`"$($_.Exception.Message)`""
            if ($LogPath) { $failMsg | Add-Content -LiteralPath $LogPath } else { Write-Warning $failMsg }
        }
    }
    return $stopped
}
