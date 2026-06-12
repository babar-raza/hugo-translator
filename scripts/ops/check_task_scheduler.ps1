<#
.SYNOPSIS
    TC-SYS-03: Read-only diagnostic — dump HugoTranslator Task Scheduler task states.

.DESCRIPTION
    Queries Get-ScheduledTask for all tasks under \HugoTranslator\ and prints each
    task's state to stdout. Non-admin sessions will receive a graceful warning.

    Output format per task:
      [OK]   TaskName    Ready
      [WARN] TaskName    Disabled   <- unexpected state

.EXAMPLE
    # Run as admin for full access:
    .\scripts\check_task_scheduler.ps1

    # Exit code: 0 = all Ready, 1 = one or more unexpected states, 2 = probe unavailable
#>

$TaskSchedulerPath          = '\HugoTranslator\'
$ExpectedTasks              = @('ContentWorker', 'TMWorker', 'Watchdog', 'AutonomousVerification')
$CampaignExemptTasks        = @('ContentWorker')

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$LogDir      = Join-Path $ProjectRoot 'data\logs'

Write-Host "Checking Task Scheduler tasks under: $TaskSchedulerPath"
Write-Host ''

try {
    $tasks = Get-ScheduledTask -TaskPath $TaskSchedulerPath -ErrorAction Stop
} catch {
    Write-Host "[WARN] Task Scheduler probe unavailable: $_"
    Write-Host "       Run this script from an elevated (admin) PowerShell session."
    exit 2
}

$taskMap = @{}
foreach ($t in $tasks) {
    $taskMap[$t.TaskName] = $t.State.ToString()
}

# Also show any tasks in the path that are not in our expected list
$extraTasks = $tasks | Where-Object { $ExpectedTasks -notcontains $_.TaskName }

$anyWarn = $false

foreach ($name in $ExpectedTasks) {
    if (-not $taskMap.ContainsKey($name)) {
        Write-Host "[WARN] $name  -- NOT FOUND in $TaskSchedulerPath"
        $anyWarn = $true
        continue
    }
    $tState = $taskMap[$name]
    $isExempt = $CampaignExemptTasks -contains $name

    # Check if a campaign_disabled sentinel is active for this task
    $sentinelFiles = @()
    if (Test-Path $LogDir) {
        $sentinelFiles = Get-ChildItem -Path $LogDir -Filter '*.campaign_disabled' -File -ErrorAction SilentlyContinue
    }
    $sentinelActive = $false
    foreach ($sf in $sentinelFiles) {
        if ($name -ilike "*$($sf.BaseName.Split('.')[0])*") {
            $sentinelActive = $true
            break
        }
    }

    if ($tState -eq 'Ready' -or $tState -eq 'Running') {
        Write-Host ("[OK]   {0,-30} {1}" -f $name, $tState)
    } elseif ($tState -eq 'Disabled' -and ($isExempt -or $sentinelActive)) {
        Write-Host ("[OK]   {0,-30} {1} (campaign-exempt)" -f $name, $tState)
    } else {
        Write-Host ("[WARN] {0,-30} {1}  <- expected Ready" -f $name, $tState)
        $anyWarn = $true
    }
}

if ($extraTasks.Count -gt 0) {
    Write-Host ''
    Write-Host "Additional tasks found (not in expected list):"
    foreach ($t in $extraTasks) {
        Write-Host ("       {0,-30} {1}" -f $t.TaskName, $t.State.ToString())
    }
}

Write-Host ''
if ($anyWarn) {
    Write-Host "[SUMMARY] One or more tasks are not in the expected state."
    exit 1
} else {
    Write-Host "[SUMMARY] All expected tasks are OK."
    exit 0
}
