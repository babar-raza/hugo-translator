# Unit tests for Get-WorkerStatus in scripts/check_worker_health.ps1
# No Pester required - plain PS1 with simple assertions.
#
# Run:  powershell -NonInteractive -File tests/unit/scripts/test_check_worker_health_status.ps1
# Exit: 0 = all pass, 1 = any fail

$ErrorActionPreference = "Stop"

# Dot-source helpers without running the main body
$ScriptPath = Join-Path $PSScriptRoot "..\..\..\scripts\check_worker_health.ps1"
. $ScriptPath -LoadHelpersOnly

$pass = 0
$fail = 0

function Assert-Status {
    param([string]$TestName, $hb, $state, [string]$Expected)
    $actual = Get-WorkerStatus $hb $state
    if ($actual -eq $Expected) {
        Write-Host "  PASS: $TestName" -ForegroundColor Green
        $script:pass++
    } else {
        Write-Host "  FAIL: $TestName -- expected $Expected, got $actual" -ForegroundColor Red
        $script:fail++
    }
}

Write-Host "=== Get-WorkerStatus tests ===" -ForegroundColor Cyan

# 1. Heartbeat missing (AgeMinutes = "UNKNOWN") -> CRIT
Assert-Status "Heartbeat missing -> CRIT" `
    @{ AgeMinutes = "UNKNOWN" } `
    @{ State = "run_completed"; LastErrorTs = "UNKNOWN"; LastSuccessTs = "UNKNOWN"; UpdatedAt = "UNKNOWN" } `
    "CRIT"

# 2. Heartbeat age > HeartbeatCritMinutes (15) -> CRIT
Assert-Status "Heartbeat age 20min -> CRIT" `
    @{ AgeMinutes = 20.0 } `
    @{ State = "run_completed"; LastErrorTs = "UNKNOWN"; LastSuccessTs = "UNKNOWN"; UpdatedAt = "UNKNOWN" } `
    "CRIT"

# 3. Heartbeat age > HeartbeatWarnMinutes (5) but <= 15 -> WARN
Assert-Status "Heartbeat age 7min -> WARN" `
    @{ AgeMinutes = 7.0 } `
    @{ State = "run_completed"; LastErrorTs = "UNKNOWN"; LastSuccessTs = "UNKNOWN"; UpdatedAt = "UNKNOWN" } `
    "WARN"

# 4. last_error_ts newer than last_success_ts -> WARN (genuine recent failure)
Assert-Status "last_error newer than last_success -> WARN" `
    @{ AgeMinutes = 1.0 } `
    @{ State = "run_completed"; LastErrorTs = (Get-Date).AddHours(-1).ToString("o"); LastSuccessTs = (Get-Date).AddHours(-2).ToString("o"); UpdatedAt = "UNKNOWN" } `
    "WARN"

# 5. last_success_ts newer than last_error_ts -> OK  (TM worker false-alarm fix)
Assert-Status "last_success newer than last_error -> OK" `
    @{ AgeMinutes = 1.0 } `
    @{ State = "run_completed"; LastErrorTs = (Get-Date).AddDays(-10).ToString("o"); LastSuccessTs = (Get-Date).AddHours(-1).ToString("o"); UpdatedAt = "UNKNOWN" } `
    "OK"

# 6. state = fatal_failure -> CRIT regardless of timestamps
Assert-Status "state=fatal_failure -> CRIT" `
    @{ AgeMinutes = 1.0 } `
    @{ State = "fatal_failure"; LastErrorTs = "UNKNOWN"; LastSuccessTs = (Get-Date).AddHours(-2).ToString("o"); UpdatedAt = "UNKNOWN" } `
    "CRIT"

# 7. last_success_ts age > SuccessCritHours (50) -> CRIT
Assert-Status "last_success 55h ago -> CRIT" `
    @{ AgeMinutes = 1.0 } `
    @{ State = "run_completed"; LastErrorTs = "UNKNOWN"; LastSuccessTs = (Get-Date).AddHours(-55).ToString("o"); UpdatedAt = "UNKNOWN" } `
    "CRIT"

# 8. last_success_ts age > SuccessWarnHours (26) but <= 50 -> WARN
Assert-Status "last_success 30h ago -> WARN" `
    @{ AgeMinutes = 1.0 } `
    @{ State = "run_completed"; LastErrorTs = "UNKNOWN"; LastSuccessTs = (Get-Date).AddHours(-30).ToString("o"); UpdatedAt = "UNKNOWN" } `
    "WARN"

# 9. state=starting + fresh heartbeat + UpdatedAt 1h ago -> OK (normal mid-run, <= MaxRunHours=6)
Assert-Status "state=starting, run 1h old -> OK (normal mid-run)" `
    @{ AgeMinutes = 1.0 } `
    @{ State = "starting"; LastErrorTs = "UNKNOWN"; LastSuccessTs = (Get-Date).AddHours(-1).ToString("o"); UpdatedAt = (Get-Date).AddHours(-1).ToString("o") } `
    "OK"

# 10. state=starting + fresh heartbeat + UpdatedAt 8h ago -> WARN (stuck run, > MaxRunHours=6)
Assert-Status "state=starting, run 8h old -> WARN (stuck)" `
    @{ AgeMinutes = 1.0 } `
    @{ State = "starting"; LastErrorTs = "UNKNOWN"; LastSuccessTs = (Get-Date).AddHours(-8).ToString("o"); UpdatedAt = (Get-Date).AddHours(-8).ToString("o") } `
    "WARN"

$total = $pass + $fail
Write-Host ""
if ($fail -eq 0) {
    Write-Host "$pass/$total tests passed" -ForegroundColor Green
} else {
    Write-Host "$pass/$total tests passed" -ForegroundColor Red
}

if ($fail -gt 0) {
    exit 1
}
exit 0
