# Worker Watchdog Script
# Checks if autonomous workers are alive and restarts them if dead or stuck.
# Designed to run every 1 hour via Windows Task Scheduler.
#
# Workers monitored:
#   - content_worker       (autonomous_content_translation_worker)
#   - tm_worker            (tm_improvement_worker)
#   - verification_worker  (autonomous_verification_worker)
#
# Inputs:
#   PID files:       data/logs/<worker>.pid          (written by G2 heartbeat)
#   Heartbeat files: data/logs/<worker>.heartbeat     (written by G2 heartbeat)
#
# Outputs:
#   Watchdog log:    data/logs/watchdog.log
#   State file:      data/logs/watchdog_state.json    (circuit breaker state)
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/worker_watchdog.ps1

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
$ProjectRoot       = Split-Path -Parent $PSScriptRoot
$LogDir            = Join-Path $ProjectRoot "data\logs"
$WatchdogLog       = Join-Path $LogDir "watchdog.log"
$StateFile         = Join-Path $LogDir "watchdog_state.json"
$HealthCheckScript = Join-Path $ProjectRoot "scripts\health_check.py"
$VenvPython        = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

$HeartbeatStaleMinutes  = 15
$CircuitBreakerMaxRestarts = 5
$CircuitBreakerWindowMinutes = 60
$TelemetryApiUrl = if ($env:TELEMETRY_API_URL) { $env:TELEMETRY_API_URL } else { "http://localhost:8765" }

# Telemetry circuit breaker: after this many consecutive POST failures the
# breaker opens and POSTs are suppressed for TelemetryBreakerSkipCycles cycles.
# State is persisted across watchdog invocations in watchdog_state.json.
$TelemetryBreakerFailureThreshold  = 3
$TelemetryBreakerSkipCycles        = 5   # cycles × Task Scheduler interval = 75 min suppression
$TelemetryWatchdogIntervalMinutes  = 15  # must match Task Scheduler trigger interval

# TC-SYS-04: Git dirty check — warn if tracked files in src/ have uncommitted changes.
# Set to $false to disable (e.g. during active development sessions).
$GitDirtyCheckEnabled    = $true
$GitDirtyCheckTimeoutSec = 2

# Worker definitions -- each entry drives detection, heartbeat, and restart.
$Workers = @(
    @{
        Name           = "content_worker"
        PidFile        = Join-Path $LogDir "content_worker.pid"
        HeartbeatFile  = Join-Path $LogDir "content_worker.heartbeat"
        StartScript    = Join-Path $ProjectRoot "scripts\start_content_worker.bat"
        ProcessPattern = "autonomous_content_translation_worker"
    },
    @{
        Name           = "tm_worker"
        PidFile        = Join-Path $LogDir "tm_worker.pid"
        HeartbeatFile  = Join-Path $LogDir "tm_worker.heartbeat"
        StartScript    = Join-Path $ProjectRoot "scripts\start_tm_worker.bat"
        ProcessPattern = "tm_improvement_worker"
    },
    @{
        Name           = "verification_worker"
        PidFile        = Join-Path $LogDir "verification_worker.pid"
        HeartbeatFile  = Join-Path $LogDir "verification_worker.heartbeat"
        StartScript    = Join-Path $ProjectRoot "scripts\start_verification_worker.bat"
        ProcessPattern = "autonomous_verification_worker"
    }
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

function Send-TelemetryEvent {
    <#
    .SYNOPSIS
        Fire-and-forget POST to the local telemetry API.
        Non-fatal: errors are logged but never halt the watchdog.

        Includes a persistent circuit breaker (TC-SYS-01):
        After TelemetryBreakerFailureThreshold consecutive failures the breaker
        opens and all POSTs are suppressed for TelemetryBreakerSkipCycles watchdog
        cycles (~75 min by default).  The breaker state is carried in $State so it
        survives across Task Scheduler invocations via watchdog_state.json.
    #>
    param(
        [Parameter(Mandatory)][string]$JobType,
        [string]$Status = "success",
        [hashtable]$Metrics = @{},
        [string]$ErrorSummary = $null,
        # Pass the current watchdog $state hashtable so the breaker is persisted.
        [hashtable]$State = $null
    )

    # --- Circuit breaker gate ---
    if ($State -ne $null -and $State.telemetry_skip_until) {
        try {
            $skipUntilUtc = [datetime]::Parse($State.telemetry_skip_until).ToUniversalTime()
            if ([datetime]::UtcNow -lt $skipUntilUtc) {
                # Breaker is open — suppress POST silently (no WARN spam)
                return
            } else {
                # Window expired — reset and allow this attempt
                $State.telemetry_skip_until = $null
                $State.telemetry_failures   = 0
            }
        } catch {
            # Corrupt skip_until value — reset and allow
            $State.telemetry_skip_until = $null
            $State.telemetry_failures   = 0
        }
    }

    $eventId = [guid]::NewGuid().ToString()
    $now = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.ffffffZ")
    $envName = if ($env:HUGO_TRANSLATOR_ENV) { $env:HUGO_TRANSLATOR_ENV } else { "dev" }

    $body = @{
        event_id     = $eventId
        run_id       = "$now-watchdog-$JobType-$($eventId.Substring(0,8))"
        agent_name   = "watchdog"
        job_type     = $JobType
        trigger_type = "scheduled"
        status       = $Status
        start_time   = $now
        end_time     = $now
        duration_ms  = 0
        host         = $env:COMPUTERNAME
        environment  = $envName
    }

    if ($Metrics.Count -gt 0) {
        $body["metrics_json"] = $Metrics
    }
    if ($ErrorSummary) {
        $body["error_summary"] = $ErrorSummary
    }

    try {
        $jsonBody = $body | ConvertTo-Json -Depth 4
        Invoke-RestMethod -Uri "$TelemetryApiUrl/api/v1/runs" `
                         -Method Post `
                         -ContentType "application/json" `
                         -Body $jsonBody `
                         -TimeoutSec 5 `
                         -ErrorAction Stop | Out-Null
        # Success — reset circuit breaker counter
        if ($State -ne $null) {
            $State.telemetry_failures   = 0
            $State.telemetry_skip_until = $null
        }
    }
    catch {
        Write-WatchdogLog "Telemetry POST failed (non-fatal): $_" -Level WARN
        if ($State -ne $null) {
            $State.telemetry_failures = [int]$State.telemetry_failures + 1
            if ([int]$State.telemetry_failures -ge $TelemetryBreakerFailureThreshold) {
                $suppressMinutes = $TelemetryBreakerSkipCycles * $TelemetryWatchdogIntervalMinutes
                $State.telemetry_skip_until = [datetime]::UtcNow.AddMinutes($suppressMinutes).ToString("o")
                Write-WatchdogLog ("Telemetry circuit breaker OPEN: {0} consecutive failures. " +
                    "Suppressing for {1} min (until {2} UTC)." -f
                    $State.telemetry_failures,
                    $suppressMinutes,
                    $State.telemetry_skip_until) -Level WARN
                $State.telemetry_failures = 0  # reset counter; skip_until is the guard now
            }
        }
    }
}

function Write-WatchdogLog {
    <#
    .SYNOPSIS
        Appends a timestamped line to the watchdog log and writes to the console.
    #>
    param(
        [Parameter(Mandatory)][string]$Message,
        [ValidateSet("INFO","WARN","ERROR","CRITICAL")]
        [string]$Level = "INFO"
    )
    $timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    $line = "$timestamp [$Level] $Message"
    Write-Host $line
    Add-Content -Path $WatchdogLog -Value $line -ErrorAction SilentlyContinue
}

function Get-WatchdogState {
    <#
    .SYNOPSIS
        Loads or initialises the watchdog state JSON (circuit breaker tracking).
        Returns a hashtable with a restarts array.
    #>
    if (Test-Path $StateFile) {
        try {
            $raw = Get-Content -Path $StateFile -Raw -ErrorAction Stop
            $state = $raw | ConvertFrom-Json
            # ConvertFrom-Json gives PSCustomObject -- normalise to hashtable list.
            $restarts = @()
            if ($state.restarts) {
                foreach ($entry in $state.restarts) {
                    $restarts += @{
                        worker    = $entry.worker
                        timestamp = $entry.timestamp
                    }
                }
            }
            # Telemetry circuit breaker fields (added TC-SYS-01)
            $telFailures  = if ($null -ne $state.telemetry_failures)  { [int]$state.telemetry_failures }  else { 0 }
            $telSkipUntil = if ($state.telemetry_skip_until)          { $state.telemetry_skip_until }      else { $null }
            return @{
                restarts              = $restarts
                telemetry_failures    = $telFailures
                telemetry_skip_until  = $telSkipUntil
            }
        } catch {
            $errMsg = "Failed to parse state file, reinitialising: $_"
            Write-WatchdogLog $errMsg -Level WARN
        }
    }
    return @{ restarts = @(); telemetry_failures = 0; telemetry_skip_until = $null }
}

function Save-WatchdogState {
    <#
    .SYNOPSIS
        Persists the watchdog state hashtable to JSON.
    #>
    param(
        [Parameter(Mandatory)][hashtable]$State
    )
    try {
        $State | ConvertTo-Json -Depth 4 | Set-Content -Path $StateFile -Force -ErrorAction Stop
    } catch {
        $errMsg = "Failed to save state file: $_"
        Write-WatchdogLog $errMsg -Level ERROR
    }
}

function Test-CircuitBreakerOpen {
    <#
    .SYNOPSIS
        Returns $true if the circuit breaker has tripped (too many restarts).
        Prunes entries older than the window as a side-effect.
    #>
    param(
        [Parameter(Mandatory)][hashtable]$State
    )
    $cutoff = (Get-Date).AddMinutes(-$CircuitBreakerWindowMinutes)
    # Prune old entries
    $State.restarts = @($State.restarts | Where-Object {
        try { [datetime]$_.timestamp -ge $cutoff } catch { $false }
    })
    return ($State.restarts.Count -ge $CircuitBreakerMaxRestarts)
}

function Test-ProcessAliveByPid {
    <#
    .SYNOPSIS
        Reads a PID file and checks whether that process is still running.
        Returns a hashtable with alive, pid, and source fields.
    #>
    param(
        [Parameter(Mandatory)][hashtable]$Worker
    )
    $result = @{ alive = $false; pid = $null; source = "none" }

    # --- Strategy 1: PID file ---
    if (Test-Path $Worker.PidFile) {
        try {
            $pidText = (Get-Content -Path $Worker.PidFile -Raw -ErrorAction Stop).Trim()
            $workerPid = [int]$pidText
            $proc = Get-Process -Id $workerPid -ErrorAction SilentlyContinue
            if ($proc -and -not $proc.HasExited) {
                $result.alive  = $true
                $result.pid    = $workerPid
                $result.source = "pidfile"
                return $result
            }
            # PID file exists but process is gone -- stale PID file.
            $result.pid    = $workerPid
            $result.source = "pidfile"
            return $result
        } catch {
            $wName = $Worker.Name
            $errMsg = "Error reading PID file for ${wName}: $_"
            Write-WatchdogLog $errMsg -Level WARN
        }
    }

    # --- Strategy 2: Command-line pattern fallback (pre-G2 deployments) ---
    try {
        $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
                 Where-Object { $_.CommandLine -match [regex]::Escape($Worker.ProcessPattern) }
        if ($procs) {
            $first = $procs | Select-Object -First 1
            $result.alive  = $true
            $result.pid    = [int]$first.ProcessId
            $result.source = "fallback"
            return $result
        }
    } catch {
        $wName = $Worker.Name
        $errMsg = "Error during fallback process scan for ${wName}: $_"
        Write-WatchdogLog $errMsg -Level WARN
    }

    return $result
}

function Test-HeartbeatFresh {
    <#
    .SYNOPSIS
        Returns $true if the heartbeat file exists and its timestamp is within the
        staleness threshold. Returns $null if the file does not exist (skip check).
    #>
    param(
        [Parameter(Mandatory)][string]$HeartbeatFile
    )
    if (-not (Test-Path $HeartbeatFile)) {
        return $null   # No heartbeat file -- G2 not yet deployed; skip check.
    }
    try {
        $raw  = Get-Content -Path $HeartbeatFile -Raw -ErrorAction Stop
        $json = $raw | ConvertFrom-Json
        $ts   = [datetime]$json.timestamp
        $age  = (Get-Date) - $ts
        $status = $json.status

        # Grace period for workers in graceful shutdown
        if ($status -eq "shutting_down") {
            if ($age.TotalMinutes -gt 5) {
                return $false  # Shutdown took too long, treat as stale
            }
            return $true  # Still shutting down, leave it alone
        }

        if ($age.TotalMinutes -gt $HeartbeatStaleMinutes) {
            return $false
        }
        return $true
    } catch {
        $errMsg = "Error parsing heartbeat file ${HeartbeatFile}: $_"
        Write-WatchdogLog $errMsg -Level WARN
        return $null   # Cannot determine -- treat as absent.
    }
}

function Stop-StuckWorker {
    <#
    .SYNOPSIS
        Kills a worker process by PID (used when heartbeat is stale but process is alive).
    #>
    param(
        [Parameter(Mandatory)][int]$WorkerPid
    )
    try {
        $msg = "Killing stuck worker PID $WorkerPid"
        Write-WatchdogLog $msg -Level WARN
        Stop-Process -Id $WorkerPid -Force -ErrorAction Stop
        Start-Sleep -Seconds 2   # Brief pause to let OS reclaim.
    } catch {
        $errMsg = "Failed to kill PID ${WorkerPid}: $_"
        Write-WatchdogLog $errMsg -Level ERROR
    }
}

function Start-Worker {
    <#
    .SYNOPSIS
        Starts a worker via its .bat script in background mode.
    #>
    param(
        [Parameter(Mandatory)][hashtable]$Worker
    )
    $bat = $Worker.StartScript
    if (-not (Test-Path $bat)) {
        $errMsg = "Start script not found: $bat"
        Write-WatchdogLog $errMsg -Level ERROR
        return $false
    }
    try {
        $wName = $Worker.Name
        $msg = "Starting $wName via $bat"
        Write-WatchdogLog $msg
        Start-Process -FilePath "cmd.exe" -ArgumentList "/c `"$bat`"" `
                      -WorkingDirectory $ProjectRoot `
                      -WindowStyle Hidden `
                      -ErrorAction Stop
        return $true
    } catch {
        $wName = $Worker.Name
        $errMsg = "Failed to start ${wName}: $_"
        Write-WatchdogLog $errMsg -Level ERROR
        return $false
    }
}

function Invoke-GitDirtyCheck {
    <#
    .SYNOPSIS
        Warn if src/ contains uncommitted modifications to tracked files (TC-SYS-04).
        Workers run against the working tree, so uncommitted src/ changes make bug
        reproduction from git history impossible.
        Times out after GitDirtyCheckTimeoutSec to avoid blocking the watchdog cycle.
    #>
    if (-not $GitDirtyCheckEnabled) { return }

    try {
        $gitExe = "git"
        # Run git status with a hard timeout via a background job.
        $job = Start-Job -ScriptBlock {
            param($root)
            Set-Location $root
            & git status --porcelain -- src/ 2>&1
        } -ArgumentList $ProjectRoot

        $completed = Wait-Job $job -Timeout $GitDirtyCheckTimeoutSec
        if ($null -eq $completed) {
            Stop-Job $job | Out-Null
            Remove-Job $job -Force | Out-Null
            Write-WatchdogLog "  git-dirty check timed out after ${GitDirtyCheckTimeoutSec}s -- skipping" -Level WARN
            return
        }

        $lines = Receive-Job $job
        Remove-Job $job -Force | Out-Null

        # Filter to modified tracked files only (M prefix in first or second column)
        $dirtyLines = $lines | Where-Object { $_ -match '^.M|^M.' }
        $count = ($dirtyLines | Measure-Object).Count

        if ($count -gt 0) {
            Write-WatchdogLog ("  [WARN] Working tree has $count uncommitted change(s) in src/ -- " +
                "workers running against unreviewed code. Run: git diff --stat src/") -Level WARN
        } else {
            Write-WatchdogLog "  src/ working tree is clean"
        }
    } catch {
        Write-WatchdogLog "  git-dirty check failed: $_ -- skipping" -Level WARN
    }
}

function Invoke-HealthCheck {
    <#
    .SYNOPSIS
        Runs the Python health_check.py script and logs the result.
    #>
    param([hashtable]$State = $null)
    if (-not (Test-Path $HealthCheckScript)) {
        $msg = "Health check script not found: $HealthCheckScript"
        Write-WatchdogLog $msg -Level WARN
        return
    }

    $python = $VenvPython
    if (-not (Test-Path $python)) {
        # Fallback to system python if venv is not present.
        $python = "python"
    }

    try {
        Write-WatchdogLog "Running health check..."
        $output = & $python $HealthCheckScript --format text 2>&1
        $exitCode = $LASTEXITCODE
        foreach ($line in $output) {
            $logLine = "  health_check: $line"
            Write-WatchdogLog $logLine
        }
        switch ($exitCode) {
            0 { Write-WatchdogLog "Health check result: HEALTHY" }
            1 { Write-WatchdogLog "Health check result: DEGRADED" -Level WARN }
            2 { Write-WatchdogLog "Health check result: UNHEALTHY" -Level ERROR }
            default {
                $msg = "Health check exited with code $exitCode"
                Write-WatchdogLog $msg -Level WARN
            }
        }
        $hcStatus = switch ($exitCode) { 0 { "success" } 1 { "partial" } default { "failure" } }
        Send-TelemetryEvent -JobType "watchdog_health_check" -Status $hcStatus `
            -Metrics @{ exit_code = $exitCode } -State $State
    } catch {
        $errMsg = "Health check failed to execute: $_"
        Write-WatchdogLog $errMsg -Level ERROR
    }
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

function Invoke-Watchdog {
    <#
    .SYNOPSIS
        Main watchdog entry point -- runs once per invocation. Task Scheduler
        calls this script every 1 hour.
    #>

    # Ensure log directory exists.
    if (-not (Test-Path $LogDir)) {
        New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    }

    Write-WatchdogLog "======== Watchdog check started ========"

    # Load circuit-breaker state.
    $state = Get-WatchdogState

    if (Test-CircuitBreakerOpen -State $state) {
        $cbCount = $state.restarts.Count
        # Calculate when circuit breaker will auto-reset (oldest restart + window)
        $oldestRestart = ($state.restarts | ForEach-Object {
            try { [datetime]$_.timestamp } catch { [datetime]::MaxValue }
        } | Sort-Object | Select-Object -First 1)
        $resetTime = $oldestRestart.AddMinutes($CircuitBreakerWindowMinutes)
        $resetTimeStr = $resetTime.ToString("HH:mm:ss")

        $msg = "CIRCUIT BREAKER OPEN: $cbCount restarts in the last $CircuitBreakerWindowMinutes minutes. Skipping restart attempts. Will auto-reset at approximately $resetTimeStr."
        Write-WatchdogLog $msg -Level CRITICAL
        Send-TelemetryEvent -JobType "watchdog_circuit_breaker" -Status "failure" `
            -Metrics @{ restarts_count = $cbCount; window_minutes = $CircuitBreakerWindowMinutes } `
            -ErrorSummary "Circuit breaker open: $cbCount restarts in $CircuitBreakerWindowMinutes minutes" `
            -State $state
        Save-WatchdogState -State $state
        Invoke-HealthCheck -State $state
        Write-WatchdogLog "======== Watchdog check finished - circuit breaker open ========"
        return
    }

    foreach ($worker in $Workers) {
        $wName = $worker.Name
        Write-WatchdogLog "Checking worker: $wName"

        # Skip workers that are in campaign-mode (daemon disabled).
        $campaignFlag = Join-Path $LogDir "$wName.campaign_disabled"
        if (Test-Path $campaignFlag) {
            Write-WatchdogLog "  ${wName}: campaign mode disabled - skipping"
            continue
        }

        # 1. Is the process alive?
        $status = Test-ProcessAliveByPid -Worker $worker

        if ($status.alive) {
            $pidInfo = $status.pid
            $srcInfo = $status.source
            $msg = "  Process alive - PID $pidInfo, source=$srcInfo"
            Write-WatchdogLog $msg

            # 2. Is the heartbeat fresh?
            $hbFresh = Test-HeartbeatFresh -HeartbeatFile $worker.HeartbeatFile
            if ($null -eq $hbFresh) {
                Write-WatchdogLog "  No heartbeat file -- skipping staleness check"
            } elseif ($hbFresh) {
                Write-WatchdogLog "  Heartbeat is fresh"
            } else {
                $msg = "  Heartbeat STALE [>$HeartbeatStaleMinutes min] -- worker appears stuck"
                Write-WatchdogLog $msg -Level WARN
                # Kill the stuck process and restart.
                Stop-StuckWorker -WorkerPid $status.pid

                if (Test-CircuitBreakerOpen -State $state) {
                    $msg = "  Circuit breaker tripped during this run -- will not restart $wName"
                    Write-WatchdogLog $msg -Level CRITICAL
                    continue
                }

                $started = Start-Worker -Worker $worker
                if ($started) {
                    $state.restarts += @{
                        worker    = $wName
                        timestamp = (Get-Date).ToString("o")
                    }
                    $msg = "  Restarted $wName - stuck recovery"
                    Write-WatchdogLog $msg
                    Send-TelemetryEvent -JobType "watchdog_restart" `
                        -Metrics @{ worker = $wName; reason = "stuck_recovery" } -State $state
                }
            }
        } else {
            $srcInfo = $status.source
            $pidInfo = $status.pid
            $msg = "  Process NOT alive - source=$srcInfo, last PID=$pidInfo"
            Write-WatchdogLog $msg -Level WARN

            if (Test-CircuitBreakerOpen -State $state) {
                $msg = "  Circuit breaker tripped -- will not restart $wName"
                Write-WatchdogLog $msg -Level CRITICAL
                continue
            }

            $started = Start-Worker -Worker $worker
            if ($started) {
                $state.restarts += @{
                    worker    = $wName
                    timestamp = (Get-Date).ToString("o")
                }
                $msg = "  Restarted $wName - dead recovery"
                Write-WatchdogLog $msg
                Send-TelemetryEvent -JobType "watchdog_restart" `
                    -Metrics @{ worker = $wName; reason = "dead_recovery" } -State $state
            }
        }
    }

    # Persist updated state.
    Save-WatchdogState -State $state

    # TC-SYS-04: Warn if src/ has uncommitted modifications.
    Invoke-GitDirtyCheck

    # Run the system health check.
    Invoke-HealthCheck -State $state

    Write-WatchdogLog "======== Watchdog check finished ========"
}

# Entry point
Invoke-Watchdog
