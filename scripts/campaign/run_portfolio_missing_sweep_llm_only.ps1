[CmdletBinding()]
param(
    [ValidateSet('Run', 'Drain', 'Status', 'Watch')]
    [string]$Action = 'Run',
    [int]$MaxWorkers = 4
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $repo
$py = Join-Path $repo '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $py)) { throw "Python interpreter missing: $py" }

$campaign = 'portfolio-missing-sweep-llm-only-20260914'
$manifest = "data\campaigns\manifests\$campaign.yaml"
$spool = "data\tm\campaign-spools\$campaign.sqlite3"
$ledger = 'data\campaigns'
$contentRepo = 'D:\onedrive\Documents\GitHub\aspose.org'
$pattern = 'portfolio-missing-sweep-llm-only-20260914.yaml|run_gate5_batch|launch_parallel_campaign|tm_intent_writer'

function Get-CampaignProcesses {
    @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match $pattern })
}

function Assert-NoCampaignProcess {
    $live = Get-CampaignProcesses
    if ($live.Count -gt 0) {
        $ids = ($live | ForEach-Object ProcessId) -join ', '
        throw "Campaign/TM process is already live (PID(s): $ids). Refusing a second launch."
    }
}

function Assert-TmSpoolDrained {
    $state = & $py -c "from pathlib import Path; from src.tm.intent_spool import TMIntentSpool; import json; print(json.dumps(TMIntentSpool(Path(r'$spool')).stats()))"
    if ($LASTEXITCODE -ne 0) { throw 'Could not inspect TM intent spool.' }
    $parsed = $state | ConvertFrom-Json
    if ([int]$parsed.PENDING -ne 0 -or [int]$parsed.CLAIMED -ne 0) {
        throw "TM spool must be drained before a translation wave (PENDING=$($parsed.PENDING), CLAIMED=$($parsed.CLAIMED)). Run -Action Drain first."
    }
}

function Drain-TmSpool {
    do {
        & $py -m src.workers.tm_intent_writer --repository-root $repo --spool-path $spool --no-l3 --limit 500 --owner "$campaign-manual-writer"
        if ($LASTEXITCODE -ne 0) { throw 'TM writer failed; new wave remains paused.' }
        $stats = & $py -c "from pathlib import Path; from src.tm.intent_spool import TMIntentSpool; print(TMIntentSpool(Path(r'$spool')).stats())"
        $stats
    } while ($stats -match "'PENDING': (?!0)")
}

function Release-StaleFamilyClaim {
    # This runs only after the OS-process check above. It releases the actual
    # current owner rather than relying on a stale pid-derived session id.
    $claimCode = @"
from pathlib import Path
from src.workers.work_claims import active_claim, release_claim
path = Path(r'$ledger/claims.jsonl')
key = 'family:$campaign'
claim = active_claim(key, claims_path=path)
if claim:
    release_claim(key, claim['session_id'], claims_path=path)
    print('released stale claim from ' + claim['session_id'])
else:
    print('no live family claim')
"@
    & $py -c $claimCode
    if ($LASTEXITCODE -ne 0) { throw 'Could not inspect/release family claim.' }
}

function Show-Status {
    $payload = & $py scripts\campaign\campaign_progress.py --manifest $manifest --ledger-root $ledger --spool $spool | ConvertFrom-Json
    [pscustomobject]@{
        live_processes = (Get-CampaignProcesses | ForEach-Object ProcessId) -join ', '
        accepted       = $payload.accepted; failures = $payload.failures; rate_per_minute = $payload.rate_per_minute
        remaining      = $payload.remaining; eta_minutes = $payload.eta_minutes; committed = $payload.committed
        pending_commit = $payload.pending_commit; tm_spool = ($payload.spool | ConvertTo-Json -Compress)
        i18n_hits      = $payload.metrics.i18n_hits; tm_hits = $payload.metrics.tm_hits
        ast_batches    = $payload.metrics.ast_batches; validation_retries = $payload.metrics.validation_retries
    } | Format-List
}

if ($Action -eq 'Status') { Show-Status; exit 0 }
if ($Action -eq 'Watch') { while ($true) { Clear-Host; Get-Date; Show-Status; Start-Sleep -Seconds 15 } }

Assert-NoCampaignProcess

if ($Action -eq 'Drain') {
    Drain-TmSpool
    Show-Status
    exit 0
}

if ($MaxWorkers -lt 1 -or $MaxWorkers -gt 8) { throw 'MaxWorkers must be 1..8.' }
if ($MaxWorkers -gt 4) {
    $calibration = "reports\campaigns\$campaign\evidence\professionalize-concurrency-calibration.json"
    $allowed = & $py -c "import json; from pathlib import Path; p=Path(r'$calibration'); d=json.loads(p.read_text(encoding='utf-8')); r=d.get('calibration',{}).get('concurrency_ramp',[]); base=next((x for x in r if x.get('level')==4),None); target=next((x for x in r if x.get('level')==$MaxWorkers),None); ok=bool(base and target and target.get('errors',1)==0 and target.get('rate_limited',1)==0 and target.get('p95',float('inf')) <= 1.5*base.get('p95',0)); print('true' if ok else 'false')"
    if ($allowed -ne 'true') { throw "MaxWorkers $MaxWorkers is not qualified by a clean calibration result. Use 1..4 until the 1,2,4,8,16 probe passes." }
}
Assert-TmSpoolDrained
Release-StaleFamilyClaim

& $py scripts\campaign\build_campaign_manifest.py --content-repo $contentRepo --translator-repo . --inventory-output "reports\campaigns\$campaign\baseline\inventory.json" --manifest-output $manifest --campaign-id $campaign --missing-only --professionalize-only --max-parallel-jobs $MaxWorkers
if ($LASTEXITCODE -ne 0) { throw 'Manifest build failed.' }

$preflight = "from pathlib import Path; from src.workers.campaign_manifest import CampaignManifest; m=CampaignManifest.load(r'$manifest'); m.verify_environment(translator_repo=Path.cwd(), require_clean=True); print({'campaign':m.campaign_id,'outputs':m.expected_output_count,'retry':m.retry_policy})"
& $py -c $preflight
if ($LASTEXITCODE -ne 0) { throw 'Manifest preflight failed.' }

# Deliberately no TM writer here: writer and reader/enqueuer children cannot
# hold the Windows L2 environment lease concurrently.
& $py scripts\campaign\launch_parallel_campaign_shards.py --campaign-manifest $manifest --ledger-root $ledger --child gate5 --max-workers $MaxWorkers --wait --tm-intent-spool-path $spool --no-force-serialize
if ($LASTEXITCODE -ne 0) { throw 'Campaign launcher failed; inspect child logs before draining TM.' }

Write-Host 'Campaign launcher completed. Draining the single-writer TM spool before any next wave.'
Drain-TmSpool
Show-Status
