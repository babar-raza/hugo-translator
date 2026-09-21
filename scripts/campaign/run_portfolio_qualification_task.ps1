[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$controlRepo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$runtimeRepo = Join-Path $controlRepo '.local\portfolio-runtime-writable'
$campaign = 'portfolio-missing-sweep-llm-only-20260914'
$evidence = Join-Path $controlRepo "reports\campaigns\$campaign\evidence\recovery-qualification-20260915T1945-five-write-canary"
$taskLog = Join-Path $controlRepo "reports\campaigns\$campaign\runtime\qualification-task.log"

"$(Get-Date -Format o) qualification task host started pid=$PID" | Add-Content -LiteralPath $taskLog

try {
    & (Join-Path $PSScriptRoot 'start_portfolio_missing_sweep_autonomous.ps1') `
        -RuntimeRepo $runtimeRepo `
        -ControlRepo $controlRepo `
        -MaxWorkers 1 `
        -ShardList (Join-Path $evidence 'repaired-it-probe.shards.txt') `
        -WatchdogState (Join-Path $evidence 'repaired-it-probe7-watchdog.json') `
        -RecoveryQualification `
        -SkipStaleReceiptInvalidation
    $code = $LASTEXITCODE
    "$(Get-Date -Format o) qualification task host completed exit=$code" | Add-Content -LiteralPath $taskLog
    exit $code
} catch {
    "$(Get-Date -Format o) qualification task host FAILED $($_.Exception.Message)" | Add-Content -LiteralPath $taskLog
    throw
}
