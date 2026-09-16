<#
.SYNOPSIS
TC-PORT-LLM-014: general-purpose production entrypoint, replacing the
narrow, hardcoded single-probe-shard run_portfolio_qualification_task.ps1
as the unattended launch path.

.DESCRIPTION
run_portfolio_qualification_task.ps1 hardcodes one specific 1-shard recovery
probe (-MaxWorkers 1, a fixed -ShardList, -RecoveryQualification,
-SkipStaleReceiptInvalidation) -- it is a diagnostic tool, not a portfolio
entrypoint, and was never meant to be relaunched repeatedly by a real
scheduler. start_portfolio_missing_sweep_autonomous.ps1 underneath it is
already fully general (ShardList is optional; omitting it processes the
full remaining manifest scope) -- this is a thin wrapper around that proven
path with production defaults, not a rewrite of the engine invocation.

Intended caller: scripts/ops/campaign_watchdog.ps1, via Start-Process,
non-blocking. Not meant to be run twice concurrently for the same
CampaignId -- start_portfolio_missing_sweep_autonomous.ps1's own
Test-CampaignLive guard refuses a second launch if one is already live.
#>
[CmdletBinding()]
param(
    [ValidateRange(1, 4)] [int]$MaxWorkers = 1,
    [string]$CampaignId = 'portfolio-missing-sweep-llm-only-20260914'
)

$ErrorActionPreference = 'Stop'
$controlRepo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$runtimeRepo = Join-Path $controlRepo '.local\portfolio-runtime-writable'
$taskLog = Join-Path $controlRepo "reports\campaigns\$CampaignId\runtime\sweep-task.log"
$watchdogState = Join-Path $controlRepo "data\campaigns\$CampaignId\watchdog_state.json"

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $taskLog) | Out-Null
"$(Get-Date -Format o) sweep task host started pid=$PID max_workers=$MaxWorkers campaign=$CampaignId" |
    Add-Content -LiteralPath $taskLog

try {
    & (Join-Path $PSScriptRoot 'start_portfolio_missing_sweep_autonomous.ps1') `
        -RuntimeRepo $runtimeRepo `
        -ControlRepo $controlRepo `
        -MaxWorkers $MaxWorkers `
        -WatchdogState $watchdogState `
        -CampaignId $CampaignId
    $code = $LASTEXITCODE
    "$(Get-Date -Format o) sweep task host completed exit=$code" | Add-Content -LiteralPath $taskLog
    exit $code
} catch {
    "$(Get-Date -Format o) sweep task host FAILED $($_.Exception.Message)" | Add-Content -LiteralPath $taskLog
    throw
}
