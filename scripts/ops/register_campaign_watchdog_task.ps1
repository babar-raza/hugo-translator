<#
.SYNOPSIS
TC-PORT-LLM-014: the one human-run, elevated, one-time setup command for
unattended operation. Everything after this runs without further elevation
or human action.

.DESCRIPTION
register_portfolio_qualification_task.ps1 (the existing task for the narrow
recovery probe) triggers only -AtLogOn (no periodic recurrence) and has no
restart-on-failure setting -- confirmed live: LastTaskResult=1, and the
day's real relaunch cycles were driven by a human/agent manually
re-invoking it, not by the task's own trigger. This registers a proper
periodic task for scripts/ops/campaign_watchdog.ps1 instead: a repeating
trigger (so it actually self-schedules), IgnoreNew (a tick that finds the
prior tick still running -- e.g. a slow orphan kill -- skips rather than
piling up), and a restart policy (so a single crashed tick doesn't silently
stop all future supervision).

Also registers the "HugoTranslatorCampaignWatchdog" Event Log source here,
while running elevated -- New-EventLog requires admin; Write-EventLog to an
already-registered source does not, so this is the only place in the whole
unattended path that needs it. Confirmed live: without this, the watchdog's
alert still lands correctly in its plain-text ALERTS.log (the alerting
design never depends on the Event Log alone), but the Event Log channel
silently no-ops.
#>
[CmdletBinding()]
param(
    [switch]$Start,
    [int]$IntervalMinutes = 5,
    [string]$CampaignId = 'portfolio-missing-sweep-llm-only-20260914',
    # Defaults to 4: the configuration TC-PORT-LLM-009's real soak runs
    # proved clean (zero unhandled crashes, zero orphans) after the
    # concurrency-safety fixes landed. Without this parameter the task was
    # silently registered at campaign_watchdog.ps1's own default of 1 worker
    # -- a real, needless throughput regression found live 2026-09-17.
    [ValidateRange(1, 4)] [int]$MaxWorkers = 4
)

$ErrorActionPreference = 'Stop'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Administrator elevation is required to register the campaign watchdog task.'
}

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$taskName = 'HugoTranslatorCampaignWatchdog'
$entrypoint = Join-Path $repo 'scripts\ops\campaign_watchdog.ps1'
$powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name

$eventSource = 'HugoTranslatorCampaignWatchdog'
if (-not [System.Diagnostics.EventLog]::SourceExists($eventSource)) {
    New-EventLog -LogName Application -Source $eventSource
    Write-Output "Registered Event Log source '$eventSource'."
} else {
    Write-Output "Event Log source '$eventSource' already registered."
}

$action = New-ScheduledTaskAction `
    -Execute $powershell `
    -Argument ("-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$entrypoint`" -CampaignId `"$CampaignId`" -MaxWorkers $MaxWorkers") `
    -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) -RepetitionDuration ([TimeSpan]::MaxValue)
$taskPrincipal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -WakeToRun `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $taskPrincipal `
    -Settings $settings `
    -Description 'Deterministic campaign watchdog: start/monitor/resume/alert, no Claude/Codex/agent in the loop.' `
    -Force | Out-Null

if ($Start) {
    Start-ScheduledTask -TaskName $taskName
}

$task = Get-ScheduledTask -TaskName $taskName
$info = Get-ScheduledTaskInfo -TaskName $taskName
[pscustomobject]@{
    TaskName        = $task.TaskName
    State           = [string]$task.State
    LastRunTime     = $info.LastRunTime
    NextRunTime     = $info.NextRunTime
    LastTaskResult  = $info.LastTaskResult
    IntervalMinutes = $IntervalMinutes
    MaxWorkers      = $MaxWorkers
    RunLevel        = [string]$task.Principal.RunLevel
} | Format-List
