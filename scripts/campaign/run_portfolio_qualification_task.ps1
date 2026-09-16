[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$controlRepo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$runtimeRepo = Join-Path $controlRepo '.local\portfolio-runtime-writable'
$campaign = 'portfolio-missing-sweep-llm-only-20260914'
$evidence = Join-Path $controlRepo "reports\campaigns\$campaign\evidence\recovery-qualification-20260915T1945-five-write-canary"

& (Join-Path $PSScriptRoot 'start_portfolio_missing_sweep_autonomous.ps1') `
    -RuntimeRepo $runtimeRepo `
    -ControlRepo $controlRepo `
    -MaxWorkers 4 `
    -ShardList (Join-Path $evidence 'soak10.shards.txt') `
    -WatchdogState (Join-Path $evidence 'soak-task-watchdog.json') `
    -SkipStaleReceiptInvalidation

exit $LASTEXITCODE
