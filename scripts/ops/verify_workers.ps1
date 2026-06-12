# Verify-Fix-Verify Worker Test Script
# Stops existing workers, starts test workers, and monitors execution

param(
    [int]$TestOffset1 = 2,      # Minutes from now for first test
    [int]$TestOffset2 = 10,     # Minutes from now for second test
    [string]$Worker = "both"    # "tm", "content", or "both"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path $PSScriptRoot -Parent

Write-Host "=" * 80 -ForegroundColor Cyan
Write-Host "AUTONOMOUS WORKERS - VERIFY-FIX-VERIFY TEST" -ForegroundColor Cyan
Write-Host "=" * 80 -ForegroundColor Cyan
Write-Host ""

# Step 1: Check for and stop existing worker processes
Write-Host "STEP 1: Checking for existing worker processes..." -ForegroundColor Yellow

$workerProcesses = Get-Process python -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -like "*tm_improvement_worker*" -or
    $_.CommandLine -like "*autonomous_content_translation_worker*"
}

if ($workerProcesses) {
    Write-Host "Found $($workerProcesses.Count) running worker(s):" -ForegroundColor Yellow
    foreach ($proc in $workerProcesses) {
        Write-Host "  - PID $($proc.Id): Started at $($proc.StartTime)" -ForegroundColor Gray
    }

    Write-Host "Stopping existing workers..." -ForegroundColor Yellow
    $workerProcesses | Stop-Process -Force
    Start-Sleep -Seconds 2

    Write-Host "✓ Workers stopped" -ForegroundColor Green
} else {
    Write-Host "✓ No existing workers found" -ForegroundColor Green
}

Write-Host ""

# Step 2: Calculate test times
Write-Host "STEP 2: Calculating test times..." -ForegroundColor Yellow

# Get current time in LA timezone
$laTime = [System.TimeZoneInfo]::ConvertTimeBySystemTimeZoneId(
    (Get-Date),
    'Pacific Standard Time'
)

$testTime1 = $laTime.AddMinutes($TestOffset1)
$testTime2 = $laTime.AddMinutes($TestOffset2)

Write-Host "  Current LA Time: $($laTime.ToString('yyyy-MM-dd HH:mm:ss')) PST" -ForegroundColor Gray
Write-Host "  Test 1: $($testTime1.ToString('yyyy-MM-dd HH:mm:ss')) PST (+$TestOffset1 min)" -ForegroundColor Cyan
Write-Host "  Test 2: $($testTime2.ToString('yyyy-MM-dd HH:mm:ss')) PST (+$TestOffset2 min)" -ForegroundColor Cyan
Write-Host ""

# Step 3: Start test execution
Write-Host "STEP 3: Starting test workers..." -ForegroundColor Yellow
Write-Host ""

# Activate virtual environment
$venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "ERROR: Virtual environment not found at $venvPython" -ForegroundColor Red
    exit 1
}

# Create logs directory
$logsDir = Join-Path $ProjectRoot "logs"
if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir | Out-Null
}

# Start workers based on parameter
$startedWorkers = @()

if ($Worker -eq "tm" -or $Worker -eq "both") {
    Write-Host "Starting TM Improvement Worker..." -ForegroundColor Cyan

    $tmLogFile = Join-Path $logsDir "tm_worker_test.log"
    $tmArgs = @(
        "-m", "src.workers.tm_improvement_worker",
        "--mode", "daemon",
        "--runs-per-day", "2",
        "--window-start", $testTime1.ToString("HH:mm"),
        "--window-end", $testTime2.AddMinutes(30).ToString("HH:mm"),
        "--timezone", "America/Los_Angeles",
        "--jitter-minutes", "0",
        "--device", "cuda",
        "--max-gpu-memory-percent", "50",
        "--llm-provider", "ollama",
        "--llm-model", "llama2",
        "--candidates-per-run", "10",
        "--max-llm-calls-per-run", "50",
        "--max-seconds-per-run", "300",
        "--log-level", "INFO"
    )

    $tmProc = Start-Process -FilePath $venvPython `
        -ArgumentList $tmArgs `
        -WorkingDirectory $ProjectRoot `
        -RedirectStandardOutput $tmLogFile `
        -RedirectStandardError $tmLogFile `
        -PassThru `
        -WindowStyle Hidden

    $startedWorkers += @{
        Name = "TM Worker"
        Process = $tmProc
        LogFile = $tmLogFile
    }

    Write-Host "  ✓ Started (PID: $($tmProc.Id))" -ForegroundColor Green
    Write-Host "  Log: $tmLogFile" -ForegroundColor Gray
    Write-Host ""
}

if ($Worker -eq "content" -or $Worker -eq "both") {
    Write-Host "Starting Content Translation Worker..." -ForegroundColor Cyan

    $contentLogFile = Join-Path $logsDir "content_worker_test.log"
    $contentArgs = @(
        "-m", "src.workers.autonomous_content_translation_worker",
        "--mode", "daemon",
        "--runs-per-day", "2",
        "--window-start", $testTime1.ToString("HH:mm"),
        "--window-end", $testTime2.AddMinutes(30).ToString("HH:mm"),
        "--timezone", "America/Los_Angeles",
        "--jitter-minutes", "0",
        "--device", "cuda",
        "--max-gpu-memory-percent", "50",
        "--log-level", "INFO"
    )

    $contentProc = Start-Process -FilePath $venvPython `
        -ArgumentList $contentArgs `
        -WorkingDirectory $ProjectRoot `
        -RedirectStandardOutput $contentLogFile `
        -RedirectStandardError $contentLogFile `
        -PassThru `
        -WindowStyle Hidden

    $startedWorkers += @{
        Name = "Content Worker"
        Process = $contentProc
        LogFile = $contentLogFile
    }

    Write-Host "  ✓ Started (PID: $($contentProc.Id))" -ForegroundColor Green
    Write-Host "  Log: $contentLogFile" -ForegroundColor Gray
    Write-Host ""
}

# Step 4: Wait for initialization
Write-Host "STEP 4: Waiting for workers to initialize..." -ForegroundColor Yellow
Start-Sleep -Seconds 5

# Check worker status
foreach ($worker in $startedWorkers) {
    if ($worker.Process.HasExited) {
        Write-Host "  ✗ $($worker.Name): EXITED (code: $($worker.Process.ExitCode))" -ForegroundColor Red
    } else {
        Write-Host "  ✓ $($worker.Name): RUNNING (PID: $($worker.Process.Id))" -ForegroundColor Green
    }
}

Write-Host ""

# Step 5: Monitor execution
Write-Host "=" * 80 -ForegroundColor Cyan
Write-Host "MONITORING TEST EXECUTION" -ForegroundColor Cyan
Write-Host "=" * 80 -ForegroundColor Cyan
Write-Host ""

Write-Host "Waiting for Test 1 execution at $($testTime1.ToString('HH:mm:ss'))..." -ForegroundColor Yellow
Write-Host "Press Ctrl+C to stop monitoring" -ForegroundColor Gray
Write-Host ""

# Monitor logs in real-time
$monitorDuration = 900  # 15 minutes total monitoring
$startMonitor = Get-Date
$lastPositions = @{}

foreach ($worker in $startedWorkers) {
    $lastPositions[$worker.LogFile] = 0
}

try {
    while (((Get-Date) - $startMonitor).TotalSeconds -lt $monitorDuration) {
        foreach ($worker in $startedWorkers) {
            $logFile = $worker.LogFile

            if (Test-Path $logFile) {
                $content = Get-Content $logFile -Raw -ErrorAction SilentlyContinue
                if ($content) {
                    $newContent = $content.Substring([Math]::Min($lastPositions[$logFile], $content.Length))
                    $lastPositions[$logFile] = $content.Length

                    if ($newContent) {
                        $lines = $newContent -split "`n"
                        foreach ($line in $lines) {
                            if ($line -match "(SCHEDULED RUN|Sleeping until|completed:|ERROR|WARNING|DAEMON MODE)") {
                                $timestamp = Get-Date -Format "HH:mm:ss"
                                Write-Host "[$timestamp] $($worker.Name): $line" -ForegroundColor Cyan
                            }
                        }
                    }
                }
            }
        }

        Start-Sleep -Milliseconds 500
    }
} catch {
    Write-Host "`nMonitoring interrupted" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=" * 80 -ForegroundColor Cyan
Write-Host "TEST COMPLETE" -ForegroundColor Cyan
Write-Host "=" * 80 -ForegroundColor Cyan
Write-Host ""

# Final status
Write-Host "Worker Status:" -ForegroundColor Yellow
foreach ($worker in $startedWorkers) {
    if ($worker.Process.HasExited) {
        Write-Host "  $($worker.Name): Exited (code: $($worker.Process.ExitCode))" -ForegroundColor Red
    } else {
        Write-Host "  $($worker.Name): Still running (PID: $($worker.Process.Id))" -ForegroundColor Green
        Write-Host "    To stop: Stop-Process -Id $($worker.Process.Id) -Force" -ForegroundColor Gray
    }
}

Write-Host ""
Write-Host "Log Files:" -ForegroundColor Yellow
foreach ($worker in $startedWorkers) {
    Write-Host "  $($worker.Name): $($worker.LogFile)" -ForegroundColor Gray
}

Write-Host ""
Write-Host "To view full logs:" -ForegroundColor Yellow
foreach ($worker in $startedWorkers) {
    Write-Host "  Get-Content '$($worker.LogFile)' -Tail 50" -ForegroundColor Gray
}

Write-Host ""
Write-Host "Test execution complete!" -ForegroundColor Green
