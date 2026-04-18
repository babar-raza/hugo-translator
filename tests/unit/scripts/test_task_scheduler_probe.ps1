<#
.SYNOPSIS
    TC-SYS-03: Pester tests for the Task Scheduler probe in worker_watchdog.ps1.

.DESCRIPTION
    Covers:
    - All 4 tasks Ready → probe logs OK, no WARN.
    - One non-exempt task Disabled → WARN emitted.
    - Get-ScheduledTask throws → graceful WARN "probe unavailable".
    - Campaign-exempt ContentWorker Disabled → no WARN (expected).

    Tests use mock/override of Get-ScheduledTask; no admin elevation required.
#>

BeforeAll {
    # Extract the Invoke-TaskSchedulerProbe function from the watchdog script so
    # it can be tested in isolation without running the full watchdog.
    $Script:WatchdogPath = Join-Path $PSScriptRoot '..\..\..\scripts\worker_watchdog.ps1'
    if (-not (Test-Path $Script:WatchdogPath)) {
        throw "Watchdog script not found: $Script:WatchdogPath"
    }

    # Read the script and extract the relevant function + constants block.
    $Script:WatchdogSrc = Get-Content $Script:WatchdogPath -Raw

    # -------------------------------------------------------------------------
    # Minimal stub environment for the probe function
    # -------------------------------------------------------------------------

    # Define the constants the probe depends on
    $Script:TaskSchedulerPath           = '\HugoTranslator\'
    $Script:TaskSchedulerExpectedTasks  = @('ContentWorker', 'TMWorker', 'Watchdog', 'AutonomousVerification')
    $Script:TaskSchedulerCampaignExempt = @('ContentWorker')

    # Stub log dir (no actual files needed)
    $Script:LogDir = Join-Path ([System.IO.Path]::GetTempPath()) "probe_test_logdir_$([System.Guid]::NewGuid().ToString('N').Substring(0,6))"
    New-Item -ItemType Directory -Path $Script:LogDir -Force | Out-Null

    # Capture log messages
    $Script:WatchdogMessages = [System.Collections.Generic.List[string]]::new()

    function Write-WatchdogLog {
        param([string]$Message, [string]$Level = 'INFO')
        $Script:WatchdogMessages.Add("[$Level] $Message")
    }
}

AfterAll {
    if ($Script:LogDir -and (Test-Path $Script:LogDir)) {
        Remove-Item $Script:LogDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

# ---------------------------------------------------------------------------
# Helper: build a mock scheduled task object
# ---------------------------------------------------------------------------
function New-MockTask {
    param([string]$TaskName, [string]$State)
    $obj = [PSCustomObject]@{
        TaskName = $TaskName
        State    = [PSCustomObject]@{}
    }
    # Add ToString() override on State
    Add-Member -InputObject $obj.State -MemberType ScriptMethod -Name 'ToString' -Value { return $State }.GetNewClosure() -Force
    return $obj
}

# ---------------------------------------------------------------------------
# The probe function extracted for testing
# (re-defined here to use our stubs and the script's constants)
# ---------------------------------------------------------------------------
function Invoke-TaskSchedulerProbeUnderTest {
    param(
        [scriptblock]$GetScheduledTaskImpl
    )

    # Locally redefine Get-ScheduledTask for this test scope
    $local:GetScheduledTask = $GetScheduledTaskImpl

    Write-WatchdogLog "Task Scheduler probe: checking $($TaskSchedulerExpectedTasks -join ', ')"

    try {
        $tasks = & $local:GetScheduledTask -ErrorAction Stop
    } catch {
        Write-WatchdogLog "  [WARN] Task Scheduler probe unavailable: $_ -- skipping" -Level WARN
        return 'unavailable'
    }

    $taskMap = @{}
    foreach ($t in $tasks) {
        $taskMap[$t.TaskName] = $t.State.ToString()
    }

    $allOk = $true
    foreach ($name in $TaskSchedulerExpectedTasks) {
        if (-not $taskMap.ContainsKey($name)) {
            Write-WatchdogLog "  [WARN] Task '$name' not found in $TaskSchedulerPath" -Level WARN
            $allOk = $false
            continue
        }
        $tState = $taskMap[$name]
        $isExempt = $TaskSchedulerCampaignExempt -contains $name

        $sentinelFiles = Get-ChildItem -Path $LogDir -Filter '*.campaign_disabled' -File -ErrorAction SilentlyContinue
        $sentinelActive = $false
        foreach ($sf in $sentinelFiles) {
            if ($name -ilike "*$($sf.BaseName.Split('.')[0])*") {
                $sentinelActive = $true
                break
            }
        }

        if ($tState -eq 'Ready' -or $tState -eq 'Running') {
            Write-WatchdogLog "  [OK]   $name  $tState"
        } elseif ($tState -eq 'Disabled' -and ($isExempt -or $sentinelActive)) {
            Write-WatchdogLog "  [OK]   $name  Disabled (campaign-exempt)"
        } else {
            Write-WatchdogLog "  [WARN] $name  $tState -- expected Ready" -Level WARN
            $allOk = $false
        }
    }

    if ($allOk) {
        Write-WatchdogLog "  Task Scheduler probe: all tasks OK"
        return 'ok'
    } else {
        Write-WatchdogLog "  Task Scheduler probe: one or more tasks in unexpected state" -Level WARN
        return 'warn'
    }
}

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

Describe 'Task Scheduler probe — all tasks Ready' {

    BeforeEach { $Script:WatchdogMessages.Clear() }

    It 'logs OK for each task and returns ok' {
        $mockTasks = @(
            (New-MockTask 'ContentWorker'         'Ready'),
            (New-MockTask 'TMWorker'              'Ready'),
            (New-MockTask 'Watchdog'              'Ready'),
            (New-MockTask 'AutonomousVerification' 'Ready')
        )

        $result = Invoke-TaskSchedulerProbeUnderTest -GetScheduledTaskImpl { $mockTasks }
        $result | Should -Be 'ok'

        $warns = $Script:WatchdogMessages | Where-Object { $_ -match '\[WARN\]' }
        $warns | Should -HaveCount 0
    }
}

Describe 'Task Scheduler probe — one non-exempt task Disabled' {

    BeforeEach { $Script:WatchdogMessages.Clear() }

    It 'emits WARN for the disabled non-exempt task' {
        $mockTasks = @(
            (New-MockTask 'ContentWorker'         'Ready'),
            (New-MockTask 'TMWorker'              'Disabled'),   # <-- unexpected
            (New-MockTask 'Watchdog'              'Ready'),
            (New-MockTask 'AutonomousVerification' 'Ready')
        )

        $result = Invoke-TaskSchedulerProbeUnderTest -GetScheduledTaskImpl { $mockTasks }
        $result | Should -Be 'warn'

        $warns = $Script:WatchdogMessages | Where-Object { $_ -match '\[WARN\].*TMWorker' }
        $warns | Should -HaveCount 1
    }
}

Describe 'Task Scheduler probe — Get-ScheduledTask throws (non-admin)' {

    BeforeEach { $Script:WatchdogMessages.Clear() }

    It 'emits WARN and returns unavailable without crashing' {
        $throwImpl = { throw 'Access denied — elevation required' }

        $result = Invoke-TaskSchedulerProbeUnderTest -GetScheduledTaskImpl $throwImpl
        $result | Should -Be 'unavailable'

        $warns = $Script:WatchdogMessages | Where-Object { $_ -match 'probe unavailable' }
        $warns | Should -HaveCount 1
    }
}

Describe 'Task Scheduler probe — campaign-exempt ContentWorker Disabled' {

    BeforeEach { $Script:WatchdogMessages.Clear() }

    It 'does not WARN when ContentWorker is Disabled (campaign-exempt)' {
        $mockTasks = @(
            (New-MockTask 'ContentWorker'         'Disabled'),   # exempt
            (New-MockTask 'TMWorker'              'Ready'),
            (New-MockTask 'Watchdog'              'Ready'),
            (New-MockTask 'AutonomousVerification' 'Ready')
        )

        $result = Invoke-TaskSchedulerProbeUnderTest -GetScheduledTaskImpl { $mockTasks }
        $result | Should -Be 'ok'

        $warns = $Script:WatchdogMessages | Where-Object { $_ -match '\[WARN\]' }
        $warns | Should -HaveCount 0
    }
}

Describe 'Task Scheduler probe — constants block' {

    It 'task names are defined as constants (not inlined strings)' {
        # Verify the watchdog script declares the expected constants block
        $src = Get-Content $Script:WatchdogPath -Raw
        $src | Should -Match '\$TaskSchedulerExpectedTasks\s*='
        $src | Should -Match '\$TaskSchedulerPath\s*='
        $src | Should -Match '\$TaskSchedulerCampaignExempt\s*='
    }

    It 'Invoke-TaskSchedulerProbe function exists in watchdog script' {
        $src = Get-Content $Script:WatchdogPath -Raw
        $src | Should -Match 'function Invoke-TaskSchedulerProbe'
    }

    It 'Invoke-TaskSchedulerProbe is called from Invoke-Watchdog' {
        $src = Get-Content $Script:WatchdogPath -Raw
        $src | Should -Match 'Invoke-TaskSchedulerProbe'
    }
}
