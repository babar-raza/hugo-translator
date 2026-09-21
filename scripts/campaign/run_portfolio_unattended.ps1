[CmdletBinding()]
param(
    [string]$RuntimeRepo = '.local\portfolio-runtime-writable',
    [string]$ControlRepo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,
    [ValidateRange(30, 900)] [int]$RetryDelaySeconds = 120
)

$ErrorActionPreference = 'Stop'
$ControlRepo = (Resolve-Path $ControlRepo).Path
$RuntimeRepo = (Resolve-Path (Join-Path $ControlRepo $RuntimeRepo)).Path
$campaign = 'portfolio-missing-sweep-llm-only-20260914'
$statePath = Join-Path $ControlRepo "data\campaigns\$campaign\watchdog_state.json"
$controller = Join-Path $ControlRepo 'scripts\campaign\start_portfolio_missing_sweep_autonomous.ps1'

while ($true) {
    & $controller -RuntimeRepo $RuntimeRepo -ControlRepo $ControlRepo
    $exitCode = $LASTEXITCODE
    if (-not (Test-Path $statePath)) { throw "Campaign ended without watchdog state (exit $exitCode)." }
    $state = Get-Content $statePath -Raw | ConvertFrom-Json
    if ($state.status -eq 'COMPLETED_WITH_BACKLOG') { exit 0 }
    $isTransientCheckpointLock = $state.status -eq 'PAUSED_CHECKPOINT_FAILURE' -and
        [string]$state.reason -match 'receipt-commit\.lock|Failed to acquire lock'
    if (-not $isTransientCheckpointLock) {
        throw "Campaign paused: $($state.status): $($state.reason)"
    }
    Add-Content -LiteralPath (Join-Path $ControlRepo "reports\campaigns\$campaign\runtime\controller.log") "$(Get-Date -Format o) transient receipt-commit lock; retrying in $RetryDelaySeconds seconds"
    Start-Sleep -Seconds $RetryDelaySeconds
}
