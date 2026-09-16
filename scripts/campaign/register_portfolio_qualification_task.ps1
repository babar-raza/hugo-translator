[CmdletBinding()]
param(
    [switch]$Start
)

$ErrorActionPreference = 'Stop'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Administrator elevation is required to register the qualification task.'
}

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$taskName = 'HugoTranslator-PortfolioQualification'
$entrypoint = Join-Path $repo 'scripts\campaign\run_portfolio_qualification_task.ps1'
$powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name

$action = New-ScheduledTaskAction `
    -Execute $powershell `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$entrypoint`"" `
    -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$taskPrincipal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -WakeToRun `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $taskPrincipal `
    -Settings $settings `
    -Description 'Bounded Professionalize-only portfolio recovery qualification; watchdog governed; no push.' `
    -Force | Out-Null

if ($Start) {
    Start-ScheduledTask -TaskName $taskName
}

$task = Get-ScheduledTask -TaskName $taskName
$info = Get-ScheduledTaskInfo -TaskName $taskName
[pscustomobject]@{
    TaskName = $task.TaskName
    State = [string]$task.State
    LastRunTime = $info.LastRunTime
    LastTaskResult = $info.LastTaskResult
    AllowStartIfOnBatteries = -not $task.Settings.DisallowStartIfOnBatteries
    DontStopIfGoingOnBatteries = -not $task.Settings.StopIfGoingOnBatteries
    ExecutionTimeLimit = [string]$task.Settings.ExecutionTimeLimit
    RunLevel = [string]$task.Principal.RunLevel
    WorkingDirectory = $task.Actions.WorkingDirectory
} | Format-List
