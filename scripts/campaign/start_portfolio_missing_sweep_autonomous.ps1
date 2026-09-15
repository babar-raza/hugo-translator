[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$RuntimeRepo,
    [string]$ControlRepo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,
    [ValidateRange(1, 4)] [int]$MaxWorkers = 4,
    [string]$SessionId = 'fc3ec89c-a06a-47e6-b846-9e37a8d37fac'
)

$ErrorActionPreference = 'Stop'
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

if (-not (Test-Path $py)) { throw "Python interpreter missing: $py" }
if (Test-CampaignLive) { throw 'A campaign process is already live; refusing a second launcher.' }

# A config-policy advance invalidates old acceptance decisions. Preserve the
# metadata evidence, demote those receipts, and declare their current files as
# exact-hash replacements so the zero-defect pipeline regenerates them.
Set-Location $RuntimeRepo
& $py "$ControlRepo\scripts\campaign\invalidate_stale_campaign_receipts.py" --manifest $manifest --ledger-root $ledger --execute
if ($LASTEXITCODE -ne 0) { throw 'Stale receipt recovery failed.' }

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
$args = @(
    'scripts\campaign\launch_parallel_campaign_shards.py', '--campaign-manifest', $manifest,
    '--ledger-root', $ledger, '--child', 'gate5', '--max-workers', $MaxWorkers, '--wait',
    '--tm-intent-spool-path', $spool, '--no-force-serialize', '--progress-interval-seconds', '30',
    '--session-id', $SessionId
)
# Keep the Python launcher attached to this persistent PowerShell host.  A
# hidden detached console delivered CTRL_CLOSE_EVENT to the Intel/Fortran
# runtime before child startup (forrtl error 200), leaving no child logs.
# The controller is intentionally run in a dedicated foreground PowerShell
# window; it may be minimized, but must remain open for unattended operation.
$launcher = Start-Process -FilePath $py -WorkingDirectory $ControlRepo -ArgumentList $args -NoNewWindow -RedirectStandardOutput $launcherLog -RedirectStandardError $launcherErr -PassThru
try {
    while (-not $launcher.HasExited) {
        if (-not (Invoke-Reconcile)) {
            & "$env:SystemRoot\System32\taskkill.exe" /PID $launcher.Id /T /F | Out-Null
            throw 'Receipt-to-commit reconciliation failed; launcher stopped with receipts preserved.'
        }
        Show-Progress
        Start-Sleep -Seconds 30
        $launcher.Refresh()
    }
    if ($launcher.ExitCode -ne 0) { throw "Campaign launcher exited $($launcher.ExitCode). See $launcherErr" }
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
