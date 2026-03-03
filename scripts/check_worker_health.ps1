param([switch]$LoadHelpersOnly)

# Read-only worker health check with auditable provenance
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $ProjectRoot "data\logs"
$SharedLogPaths = @(
    (Join-Path $LogDir "hugo-translator.ndjson"),
    (Join-Path $LogDir "worker_startup.log")
)

$Workers = @(
    @{
        Name = "content_worker"
        TaskName = "HugoTranslator-ContentWorker"
        HeartbeatFile = Join-Path $LogDir "content_worker.heartbeat"
        PidFile = Join-Path $LogDir "content_worker.pid"
        StateFile = Join-Path $LogDir "content_worker.state.json"
        DefaultLogPath = Join-Path $LogDir "content_worker.log"
        ConsoleLogPath = Join-Path $LogDir "content_worker_console.log"
    },
    @{
        Name = "tm_worker"
        TaskName = "HugoTranslator-TMWorker"
        HeartbeatFile = Join-Path $LogDir "tm_worker.heartbeat"
        PidFile = Join-Path $LogDir "tm_worker.pid"
        StateFile = Join-Path $LogDir "tm_worker.state.json"
        DefaultLogPath = Join-Path $LogDir "tm_worker.log"
        ConsoleLogPath = Join-Path $LogDir "tm_worker_console.log"
    },
    @{
        Name = "verification_worker"
        TaskName = "HugoTranslator-AutonomousVerification"
        HeartbeatFile = Join-Path $LogDir "verification_worker.heartbeat"
        PidFile = Join-Path $LogDir "verification_worker.pid"
        StateFile = Join-Path $LogDir "verification_worker.state.json"
        DefaultLogPath = Join-Path $LogDir "verification_worker.log"
        ConsoleLogPath = Join-Path $LogDir "verification_worker_console.log"
    }
)

# --- Health status thresholds (used by Get-WorkerStatus; must be at module scope) ---
$HeartbeatWarnMinutes  = 5    # WARN if heartbeat older than 5 min
$HeartbeatCritMinutes  = 15   # CRIT if heartbeat older than 15 min
$SuccessWarnHours      = 26   # WARN if last_success_ts older than 26 h (1 day + 2 h margin)
$SuccessCritHours      = 50   # CRIT if last_success_ts older than 50 h (~2 days)
$MaxRunHours           = 6    # WARN if state="starting" longer than 6 h (stuck run)

function Get-HeartbeatInfo {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        return @{
            Present = $false
            Status = "UNKNOWN"
            Timestamp = "UNKNOWN"
            AgeMinutes = "UNKNOWN"
        }
    }

    try {
        $raw = Get-Content -Path $Path -Raw -ErrorAction Stop
        $json = $raw | ConvertFrom-Json
        $ts = [datetime]$json.timestamp
        $ageMinutes = [math]::Round(((Get-Date) - $ts).TotalMinutes, 2)
        return @{
            Present = $true
            Status = if ($json.status) { [string]$json.status } else { "UNKNOWN" }
            Timestamp = $ts.ToString("s")
            AgeMinutes = $ageMinutes
        }
    } catch {
        return @{
            Present = $true
            Status = "UNKNOWN"
            Timestamp = "UNKNOWN"
            AgeMinutes = "UNKNOWN"
        }
    }
}

function Get-PidInfo {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        return @{
            Present = $false
            Pid = "UNKNOWN"
            Alive = "UNKNOWN"
            StartTime = "UNKNOWN"
        }
    }

    try {
        $pidText = (Get-Content -Path $Path -Raw -ErrorAction Stop).Trim()
        $workerPid = [int]$pidText
        $proc = Get-Process -Id $workerPid -ErrorAction SilentlyContinue
        if ($proc) {
            return @{
                Present = $true
                Pid = $workerPid
                Alive = "ALIVE"
                StartTime = $proc.StartTime.ToString("s")
            }
        }
        return @{
            Present = $true
            Pid = $workerPid
            Alive = "DEAD"
            StartTime = "UNKNOWN"
        }
    } catch {
        return @{
            Present = $true
            Pid = "UNKNOWN"
            Alive = "UNKNOWN"
            StartTime = "UNKNOWN"
        }
    }
}

function Get-StateInfo {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        return @{
            Present = $false
            State = "UNKNOWN"
            LastSuccessTs = "UNKNOWN"
            LastErrorTs = "UNKNOWN"
            LogPath = "UNKNOWN"
            UpdatedAt = "UNKNOWN"
        }
    }

    try {
        $raw = Get-Content -Path $Path -Raw -ErrorAction Stop
        $json = $raw | ConvertFrom-Json
        return @{
            Present = $true
            State = if ($json.state) { [string]$json.state } else { "UNKNOWN" }
            LastSuccessTs = if ($json.last_success_ts) { [string]$json.last_success_ts } else { "UNKNOWN" }
            LastErrorTs = if ($json.last_error_ts) { [string]$json.last_error_ts } else { "UNKNOWN" }
            LogPath = if ($json.log_path) { [string]$json.log_path } else { "UNKNOWN" }
            UpdatedAt = if ($json.updated_at) { [string]$json.updated_at } else { "UNKNOWN" }
        }
    } catch {
        return @{
            Present = $true
            State = "UNKNOWN"
            LastSuccessTs = "UNKNOWN"
            LastErrorTs = "UNKNOWN"
            LogPath = "UNKNOWN"
            UpdatedAt = "UNKNOWN"
        }
    }
}

function Get-TaskInfo {
    param([string]$TaskName)
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $task) {
        return @{
            Present = $false
            State = "MISSING"
            LastRunTime = "UNKNOWN"
            LastResult = "UNKNOWN"
        }
    }

    $taskInfo = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction SilentlyContinue
    return @{
        Present = $true
        State = [string]$task.State
        LastRunTime = if ($taskInfo.LastRunTime) { $taskInfo.LastRunTime.ToString("s") } else { "UNKNOWN" }
        LastResult = if ($taskInfo.LastTaskResult -ne $null) { [string]$taskInfo.LastTaskResult } else { "UNKNOWN" }
    }
}

function Resolve-LogPath {
    param(
        [string]$StateLogPath,
        [hashtable]$Worker
    )

    $candidates = @()
    if ($StateLogPath -and $StateLogPath -ne "UNKNOWN") {
        $candidates += $StateLogPath
    }
    if ($Worker.DefaultLogPath) {
        $candidates += $Worker.DefaultLogPath
    }
    if ($Worker.ConsoleLogPath) {
        $candidates += $Worker.ConsoleLogPath
    }
    $candidates += $SharedLogPaths

    $seen = @{}
    foreach ($candidate in $candidates) {
        if (-not $candidate) {
            continue
        }
        if ($seen.ContainsKey($candidate)) {
            continue
        }
        $seen[$candidate] = $true
        if (Test-Path $candidate) {
            return $candidate
        }
    }

    return "UNKNOWN"
}

function Get-WorkerStatus {
    param($hb, $state)

    # CRIT: heartbeat missing (UNKNOWN age) or completely stale (> CritMinutes)
    if ($hb.AgeMinutes -eq "UNKNOWN" -or
        ($hb.AgeMinutes -ne "UNKNOWN" -and [double]$hb.AgeMinutes -gt $HeartbeatCritMinutes)) {
        return "CRIT"
    }
    # WARN: heartbeat mildly stale
    if ($hb.AgeMinutes -ne "UNKNOWN" -and [double]$hb.AgeMinutes -gt $HeartbeatWarnMinutes) {
        return "WARN"
    }
    # WARN: last_error_ts is NEWER than last_success_ts (genuine error, not historical)
    if ($state.LastErrorTs -ne "UNKNOWN" -and $state.LastSuccessTs -ne "UNKNOWN") {
        try {
            $errDt = [datetime]::Parse($state.LastErrorTs)
            $okDt  = [datetime]::Parse($state.LastSuccessTs)
            if ($errDt -gt $okDt) { return "WARN" }
        } catch {}
    }
    # CRIT/WARN: last_success_ts too old (worker not producing output).
    # Exception: state="starting" + fresh heartbeat + run started recently → mid-run (OK).
    # But state="starting" + fresh heartbeat + run started > MaxRunHours ago → stuck (WARN).
    $midRun = $false
    if ($state.State -eq "starting" -and
        $hb.AgeMinutes -ne "UNKNOWN" -and
        [double]$hb.AgeMinutes -le $HeartbeatWarnMinutes) {
        $runAgeHours = 0
        if ($state.UpdatedAt -ne "UNKNOWN") {
            try {
                $startDt = [datetime]::Parse($state.UpdatedAt)
                $runAgeHours = ((Get-Date) - $startDt).TotalHours
            } catch {
                # UpdatedAt unparseable → conservative: treat as over limit
                $runAgeHours = $MaxRunHours + 1
            }
        } else {
            # No UpdatedAt in state JSON → conservative: do not suppress WARN
            $runAgeHours = $MaxRunHours + 1
        }
        $midRun = ($runAgeHours -le $MaxRunHours)
    }
    if (-not $midRun -and $state.LastSuccessTs -ne "UNKNOWN") {
        try {
            $okDt = [datetime]::Parse($state.LastSuccessTs)
            $ageH = ((Get-Date) - $okDt).TotalHours
            if ($ageH -gt $SuccessCritHours) { return "CRIT" }
            if ($ageH -gt $SuccessWarnHours) { return "WARN" }
        } catch {}
    }
    # WARN: state="starting" + stuck (run exceeds MaxRunHours, fresh heartbeat confirms alive)
    if ($state.State -eq "starting" -and -not $midRun -and
        $hb.AgeMinutes -ne "UNKNOWN" -and [double]$hb.AgeMinutes -le $HeartbeatWarnMinutes) {
        return "WARN"
    }
    if ($state.State -eq "fatal_failure" -or $state.State -eq "fatal_preflight_failure") {
        return "CRIT"
    }
    return "OK"
}

if (-not $LoadHelpersOnly) {
    Write-Host "=== Worker Health Check ===" -ForegroundColor Cyan
    Write-Host "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    Write-Host "ProjectRoot: $ProjectRoot"
    Write-Host "LogDir: $LogDir"
    Write-Host ""

    $rows = @()
    foreach ($worker in $Workers) {
        $hb = Get-HeartbeatInfo -Path $worker.HeartbeatFile
        $pidInfo = Get-PidInfo -Path $worker.PidFile
        $state = Get-StateInfo -Path $worker.StateFile
        $task = Get-TaskInfo -TaskName $worker.TaskName

        $logPath = Resolve-LogPath -StateLogPath $state.LogPath -Worker $worker

        $effectiveState = $state.State
        if ($effectiveState -eq "UNKNOWN" -and $hb.Status -ne "UNKNOWN") {
            $effectiveState = $hb.Status
        }

        $healthStatus = Get-WorkerStatus -hb $hb -state $state

        $rows += [PSCustomObject]@{
            Status = $healthStatus
            Component = $worker.Name
            Task = $worker.TaskName
            TaskState = $task.State
            Pid = $pidInfo.Pid
            HeartbeatAgeMin = $hb.AgeMinutes
            State = $effectiveState
            last_success_ts = $state.LastSuccessTs
            last_error_ts = $state.LastErrorTs
            log_path = $logPath
        }
    }

    Write-Host "--- Worker Summary ---" -ForegroundColor Yellow
    $rows | Format-Table -AutoSize
    Write-Host ""

    # Overall status line
    $overallStatus = "OK"
    if ($rows | Where-Object { $_.Status -eq "CRIT" }) { $overallStatus = "CRIT" }
    elseif ($rows | Where-Object { $_.Status -eq "WARN" }) { $overallStatus = "WARN" }
    $statusColor = @{ "OK" = "Green"; "WARN" = "Yellow"; "CRIT" = "Red" }[$overallStatus]
    Write-Host "==> Overall: $overallStatus" -ForegroundColor $statusColor
    Write-Host ""

    Write-Host "--- Worker Provenance ---" -ForegroundColor Yellow
    foreach ($row in $rows) {
        $c = @{ "OK" = "Green"; "WARN" = "Yellow"; "CRIT" = "Red" }[$row.Status]
        Write-Host "  [$($row.Status)] $($row.Component): state=$($row.State) hb_age=$($row.HeartbeatAgeMin)min last_success=$($row.last_success_ts) last_error=$($row.last_error_ts)" -ForegroundColor $c
    }
    Write-Host ""

    Write-Host "--- Python Processes ---" -ForegroundColor Yellow
    $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue
    if ($procs) {
        foreach ($proc in $procs) {
            $cmd = if ($proc.CommandLine.Length -gt 120) { $proc.CommandLine.Substring(0, 120) + "..." } else { $proc.CommandLine }
            Write-Host "  PID $($proc.ProcessId): $cmd"
        }
    } else {
        Write-Host "  No python processes running"
    }
    Write-Host ""

    Write-Host "--- Watchdog Log (last 20 lines) ---" -ForegroundColor Yellow
    $watchdogLog = Join-Path $LogDir "watchdog.log"
    if (Test-Path $watchdogLog) {
        Get-Content $watchdogLog -Tail 20
    } else {
        Write-Host "  UNKNOWN: watchdog.log not found"
    }
    Write-Host ""

    Write-Host "--- Ollama Status ---" -ForegroundColor Yellow
    try {
        $resp = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 3
        $models = if ($resp.models) { $resp.models.Count } else { 0 }
        Write-Host "  Ollama: RUNNING ($models models)"
    } catch {
        Write-Host "  Ollama: NOT RUNNING"
    }
}
