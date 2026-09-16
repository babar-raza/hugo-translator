[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$RuntimeRepo,
    [string]$ControlRepo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,
    [ValidateRange(1, 4)] [int]$MaxWorkers = 4,
    [string]$SessionId = ([guid]::NewGuid().ToString()),
    [string]$ShardList,
    [string]$WatchdogState,
    [switch]$SkipStaleReceiptInvalidation
)

$ErrorActionPreference = 'Stop'

# The unattended Windows host must not be cancelled by synthetic CTRL+C events
# emitted when a short-lived console/process shim closes. Passing a null
# handler with Add=true enables the documented per-process ignore flag, which
# is inherited by launcher/worker children. Watchdog pauses and taskkill /T /F
# remain authoritative governed shutdown paths.
if ($env:OS -eq 'Windows_NT') {
    # Reuse the framework's existing P/Invoke rather than compiling Add-Type
    # source at runtime (production temp-directory policy can block csc files).
    $native = [string].Assembly.GetType('Microsoft.Win32.Win32Native')
    $setHandler = $native.GetMethod(
        'SetConsoleCtrlHandler',
        [Reflection.BindingFlags]'Static,NonPublic'
    )
    if (-not $setHandler -or -not $setHandler.Invoke($null, @($null, $true))) {
        throw 'Could not install the unattended Windows console-control guard.'
    }
}

$RuntimeRepo = (Resolve-Path $RuntimeRepo).Path
$ControlRepo = (Resolve-Path $ControlRepo).Path
$py = Join-Path $ControlRepo '.venv\Scripts\python.exe'
$campaign = 'portfolio-missing-sweep-llm-only-20260914'
$manifest = Join-Path $ControlRepo "data\campaigns\manifests\$campaign.yaml"
$ledger = Join-Path $ControlRepo 'data\campaigns'
$spool = Join-Path $ControlRepo "data\tm\campaign-spools\$campaign.sqlite3"
$contentRepo = 'D:\onedrive\Documents\GitHub\aspose.org'
$env:ASPOSE_ORG_CONTENT = Join-Path $contentRepo 'content'
$env:CAMPAIGN_IDENTITY_DIR = Join-Path $ControlRepo 'data\runtime\llm_identity'
$logRoot = Join-Path $ControlRepo "reports\campaigns\$campaign\runtime"
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null
$launcherLog = Join-Path $logRoot 'launcher.log'
$launcherErr = Join-Path $logRoot 'launcher.err.log'
$controllerLog = Join-Path $logRoot 'controller.log'
$WatchdogState = if ($WatchdogState) { [IO.Path]::GetFullPath($WatchdogState) } else { Join-Path $ledger "$campaign\watchdog_state.json" }
$env:PYTHONPATH = $RuntimeRepo

# The runtime clone is revision-pinned and may be ACL-restricted when launched
# elevated.  Run children from ControlRepo so immutable FastText/HF caches are
# readable, while --translator-repo preserves runtime SHA/config verification.
if (-not (Test-Path (Join-Path $ControlRepo 'data\models\fasttext\lid.176.bin'))) {
    throw 'FastText model missing from the control repository.'
}

function Write-Controller([string]$Message) {
    $line = "$(Get-Date -Format o) $Message"
    $line | Tee-Object -FilePath $controllerLog -Append
}
function Test-CampaignLive {
    @(Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -match 'launch_parallel_campaign_shards.py|run_gate5_batch.py' -and
        $_.ProcessId -ne $PID
    })
}
function Invoke-Preflight {
    Set-Location $RuntimeRepo
    $receipts = Join-Path $ledger "$campaign\acceptance_receipts.jsonl"
    & $py -c "import json; from pathlib import Path; from src.workers.campaign_manifest import CampaignManifest; m=CampaignManifest.load(Path(r'$manifest')); accepted={json.loads(x)['output_path'] for x in Path(r'$receipts').read_text(encoding='utf-8').splitlines() if x.strip()}; m.verify_environment(translator_repo=Path(r'$RuntimeRepo'), require_clean=True, allow_existing_accepted=accepted, allow_campaign_tm_drift=True); print(m.translator_repo_sha)"
    return $LASTEXITCODE -eq 0
}
function Invoke-Reconcile {
    Set-Location $RuntimeRepo
    & $py "$ControlRepo\scripts\campaign\reconcile_receipted_commits.py" --manifest $manifest --content-repo $contentRepo --ledger-root $ledger --max-files 25 --execute --session-id $SessionId
    return $LASTEXITCODE -eq 0
}
function Show-Progress {
    Set-Location $RuntimeRepo
    $progress = & $py "$ControlRepo\scripts\campaign\campaign_progress.py" --manifest $manifest --ledger-root $ledger --spool $spool
    Write-Controller "progress $progress"
}
function Get-SpoolState {
    Set-Location $RuntimeRepo
    $json = & $py -c "from pathlib import Path; from src.tm.intent_spool import TMIntentSpool; import json; print(json.dumps(TMIntentSpool(Path(r'$spool')).stats()))"
    if ($LASTEXITCODE -ne 0) { throw 'Could not inspect TM intent spool.' }
    return ($json | ConvertFrom-Json)
}
function Invoke-PreWaveSpoolDrain {
    $state = Get-SpoolState
    Write-Controller "tm_spool_pre_wave_before $($state | ConvertTo-Json -Compress)"
    if ([int]$state.CLAIMED -gt 0) {
        throw "TM spool has $($state.CLAIMED) active claim(s); refusing to race another writer or wait indefinitely."
    }
    while ([int]$state.PENDING -gt 0) {
        $pendingBefore = [int]$state.PENDING
        Set-Location $RuntimeRepo
        & $py -m src.workers.tm_intent_writer --repository-root $RuntimeRepo --spool-path $spool --no-l3 --limit 500 --owner "$campaign-autonomous-predrain"
        if ($LASTEXITCODE -ne 0) { throw 'TM writer failed during mandatory pre-wave drain.' }
        $state = Get-SpoolState
        Write-Controller "tm_spool_pre_wave_progress $($state | ConvertTo-Json -Compress)"
        if ([int]$state.CLAIMED -gt 0 -or [int]$state.PENDING -ge $pendingBefore) {
            throw "TM pre-wave drain made no safe progress (PENDING=$($state.PENDING), CLAIMED=$($state.CLAIMED))."
        }
    }
    if ([int]$state.PENDING -ne 0 -or [int]$state.CLAIMED -ne 0) {
        throw "TM spool is not drained (PENDING=$($state.PENDING), CLAIMED=$($state.CLAIMED))."
    }
    Write-Controller "tm_spool_pre_wave_ready $($state | ConvertTo-Json -Compress)"
}

if (-not (Test-Path $py)) { throw "Python interpreter missing: $py" }
if (Test-CampaignLive) { throw 'A campaign process is already live; refusing a second launcher.' }

# Translation waves only read/enqueue TM intents.  Drain all prior intents
# through the single writer before workers start so every wave sees the latest
# exact TM state and a crashed writer cannot be hidden by fresh work.
Invoke-PreWaveSpoolDrain

# A config-policy advance invalidates old acceptance decisions. Preserve the
# metadata evidence, demote those receipts, and declare their current files as
# exact-hash replacements so the zero-defect pipeline regenerates them.
Set-Location $RuntimeRepo
if (-not $SkipStaleReceiptInvalidation) {
    & $py "$ControlRepo\scripts\campaign\invalidate_stale_campaign_receipts.py" --manifest $manifest --ledger-root $ledger --execute
    if ($LASTEXITCODE -ne 0) { throw 'Stale receipt recovery failed.' }
}

# The manifest builder is allowed to run before this controller.  Wait for its
# revision-bound output, but do not bypass its preflight if it fails.
$deadline = (Get-Date).AddMinutes(30)
while (-not (Invoke-Preflight)) {
    if ((Get-Date) -ge $deadline) { throw 'Manifest preflight did not become valid within 30 minutes.' }
    Write-Controller 'waiting for valid manifest preflight'
    Start-Sleep -Seconds 30
}

Write-Controller "starting Professionalize-only launcher workers=$MaxWorkers"
Set-Location $RuntimeRepo
$launcherScript = Join-Path $RuntimeRepo 'scripts\campaign\launch_parallel_campaign_shards.py'
$args = @(
    $launcherScript, '--campaign-manifest', $manifest,
    '--ledger-root', $ledger, '--child', 'gate5', '--max-workers', $MaxWorkers, '--wait',
    '--tm-intent-spool-path', $spool, '--no-force-serialize', '--progress-interval-seconds', '30',
    '--session-id', $SessionId, '--watchdog-state', $WatchdogState
)
if ($ShardList) {
    $resolvedShardList = (Resolve-Path $ShardList).Path
    $args += @('--shard-list', $resolvedShardList)
}
# A prior terminal watchdog record must not masquerade as the state of this
# controller run.  Preserve it as evidence, then publish the new run identity
# before the launcher starts.  The launcher atomically replaces this state if
# its acceptance watchdog pauses the wave.
if (Test-Path $WatchdogState) {
    $archive = "$WatchdogState.previous-$(Get-Date -Format 'yyyyMMddTHHmmssfff').json"
    Move-Item -LiteralPath $WatchdogState -Destination $archive
}
@{
    status = 'RUNNING'
    reason = $null
    session_id = $SessionId
    started_at = (Get-Date -Format o)
    accepted_current_run = 0
    rejected_current_run = 0
} | ConvertTo-Json | Set-Content -LiteralPath $WatchdogState -Encoding UTF8
# Give the launcher a separate, persistent console/process group. Sharing the
# controller console via -NoNewWindow let short-lived progress probes deliver
# a Windows control event to the launcher and all workers. A fully hidden,
# detached process previously triggered the Intel/Fortran runtime, so use a
# real minimized console owned by the persistent controller instead.
$launcher = Start-Process -FilePath $py -WorkingDirectory $ControlRepo -ArgumentList $args -WindowStyle Minimized -RedirectStandardOutput $launcherLog -RedirectStandardError $launcherErr -PassThru
try {
    while ($true) {
        $launcher.Refresh()
        $liveFamily = @(Test-CampaignLive)
        if ($launcher.HasExited -and $liveFamily.Count -eq 0) { break }
        # Do not reconcile commits while worker children are writing campaign
        # receipts/failures. Both operations serialize through the campaign
        # ledger lock; racing them caused a reconciliation failure followed by
        # an avoidable launcher-tree kill. The bounded wave is reconciled once,
        # immediately after every child exits and its receipts are frozen.
        Show-Progress
        Start-Sleep -Seconds 30
    }
    # The Windows venv executable can be a short-lived shim whose process exit
    # precedes the real interpreter.  The family wait above is authoritative;
    # the shim's exit code is useful only when non-zero.
    if ($launcher.ExitCode -ne 0) { throw "Campaign launcher shim exited $($launcher.ExitCode). See $launcherErr" }
    $watchdog = Get-Content -LiteralPath $WatchdogState -Raw | ConvertFrom-Json
    if ($watchdog.status -ne 'RUNNING') {
        throw "Campaign launcher stopped under watchdog state $($watchdog.status): $($watchdog.reason)"
    }
    if (-not (Invoke-Reconcile)) { throw 'Final receipt-to-commit reconciliation failed.' }
    do {
        Set-Location $RuntimeRepo
        & $py -m src.workers.tm_intent_writer --repository-root $RuntimeRepo --spool-path $spool --no-l3 --limit 500 --owner "$campaign-autonomous-writer"
        if ($LASTEXITCODE -ne 0) { throw 'TM writer failed after launcher completion.' }
        $state = & $py -c "from pathlib import Path; from src.tm.intent_spool import TMIntentSpool; import json; print(json.dumps(TMIntentSpool(Path(r'$spool')).stats()))"
        Write-Controller "tm_spool $state"
    } while ([int](($state | ConvertFrom-Json).PENDING) -gt 0)
    Show-Progress
    Write-Controller 'campaign launcher and final TM drain completed'
} catch {
    Write-Controller "FAILED $($_.Exception.Message)"
    throw
}
