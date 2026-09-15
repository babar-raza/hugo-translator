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
    $receiptPath = Join-Path $ledger "$campaign\acceptance_receipts.jsonl"
    $failurePath = Join-Path $ledger "$campaign\failure_metadata.jsonl"
    $callsPath = Join-Path $ledger "$campaign\llm_calls.jsonl"
    $count = { param($p) if (Test-Path -LiteralPath $p) { (Get-Content -LiteralPath $p | Measure-Object -Line).Lines } else { 0 } }
    $commitLedger = Join-Path $ledger "$campaign\commit_batches.jsonl"
    $committed = 0
    if (Test-Path -LiteralPath $commitLedger) {
        $committed = @((Get-Content -LiteralPath $commitLedger | Where-Object { $_ -match '"status"\s*:\s*"COMMITTED"' } | ForEach-Object { ($_ | ConvertFrom-Json).outputs.Count } | Measure-Object -Sum).Sum)[0]
        if ($null -eq $committed) { $committed = 0 }
    }
    $accepted = & $count $receiptPath
    [pscustomobject]@{
        live_processes = (Get-CampaignProcesses | ForEach-Object ProcessId) -join ', '
        accepted       = $accepted
        failures       = & $count $failurePath
        llm_events     = & $count $callsPath
        committed      = $committed
        pending_commit = $accepted - $committed
        remaining      = 114636 - $accepted
    } | Format-List
}

if ($Action -eq 'Status') { Show-Status; exit 0 }
if ($Action -eq 'Watch') { while ($true) { Clear-Host; Get-Date; Show-Status; Start-Sleep -Seconds 15 } }

Assert-NoCampaignProcess

if ($Action -eq 'Drain') {
    do {
        & $py -m src.workers.tm_intent_writer --repository-root $repo --spool-path $spool --no-l3 --limit 500 --owner "$campaign-manual-writer"
        if ($LASTEXITCODE -ne 0) { throw 'TM writer failed.' }
        $stats = & $py -c "from pathlib import Path; from src.tm.intent_spool import TMIntentSpool; print(TMIntentSpool(Path(r'$spool')).stats())"
        $stats
    } while ($stats -match "'PENDING': (?!0)")
    Show-Status
    exit 0
}

if ($MaxWorkers -lt 1 -or $MaxWorkers -gt 4) { throw 'MaxWorkers must be 1..4.' }
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

Write-Host 'Campaign launcher completed. Run this script again with -Action Drain after confirming status.'
Show-Status
