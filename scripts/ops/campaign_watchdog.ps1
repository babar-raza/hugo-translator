<#
.SYNOPSIS
TC-PORT-LLM-014: deterministic campaign watchdog. Starts, monitors, resumes,
and safely stops the aspose.org portfolio translation process -- no Claude,
Codex, agent, or human decision-making anywhere in this loop.

.DESCRIPTION
Replaces reliance on scripts/ops/mission_watchdog.ps1 for unattended
execution. That script's design -- relaunch a Claude CLI session, and after
2 no-progress relaunches, cold-boot a fresh one -- is exactly what this
mission's operator asked to remove from the unattended path. This watchdog
supervises the CAMPAIGN PROCESS TREE directly (launch_parallel_campaign_
shards.py / run_gate5_batch.py) with plain deterministic logic:

  1. Classify current state: RUNNING (live, healthy), STALE (live but no
     process-table evidence it's making progress), or NOT_RUNNING.
  2. STALE -> kill the orphaned tree (scripts/ops/campaign_process_
     lifecycle.ps1, itself verified end to end against a real spawned/killed
     process, not just code review) and fall through to NOT_RUNNING.
  3. NOT_RUNNING -> inspect the campaign's own watchdog_state.json:
       - status says a deliberate quality-regression pause (e.g.
         PAUSED_VALIDATION_REGRESSION / three_consecutive_identical_root_
         cause) -> STOP. Do not relaunch. This is the actual fix for the
         42-hour retry-loop-without-convergence dd68f590 diagnosed: an
         outer scheduler was treating that harness's own deliberate pause
         as a bare failure and relaunching unconditionally, with no code
         change between attempts, forever. A real content/quality question
         needs a human, not another identical attempt.
       - otherwise (crash, interrupt, clean completion, or first run) ->
         resumable. Bounded consecutive-no-progress counter (this watchdog's
         own deterministic replacement for TC-APT-054's Claude-cold-boot
         escalation): progress since the last relaunch resets it; hitting
         the limit STOPS relaunching and alerts, rather than spinning
         forever OR escalating to any kind of agent session.
  4. RUNNING and healthy -> no-op this tick.

ALERTING (never a Claude/Codex/agent invocation): Windows Event Log
(source "HugoTranslatorCampaignWatchdog") plus a plain-text, de-duplicated
alert file under the campaign's own evidence directory, so a human checking
in (or the final PowerShell command sequence's status check) sees exactly
what needs attention and why, without needing to reconstruct it from raw
logs.

Intended registration: a periodic Scheduled Task (see
register_campaign_watchdog_task.ps1), e.g. every 5 minutes, IgnoreNew. Each
invocation is a single bounded tick -- it never blocks waiting for the
campaign itself; relaunching is done via Start-Process, non-blocking.
#>
[CmdletBinding()]
param(
    [string]$CampaignId = 'portfolio-missing-sweep-llm-only-20260914',
    [ValidateRange(1, 4)] [int]$MaxWorkers = 1,
    [int]$StaleAfterMinutes = 20,
    [int]$MaxConsecutiveNoProgressRelaunches = 3,
    [int]$ReAlertAfterHours = 6,
    # A human's recovery command after investigating an alert (ALERTS.log
    # names this explicitly): clears the stopped flag and the no-progress
    # counter, then exits without relaunching -- the NEXT scheduled tick
    # resumes normal supervision. Deliberately a separate step from clearing
    # and relaunching in the same breath, so a human reviews before it goes
    # unattended again.
    [switch]$Resume
)

$ErrorActionPreference = 'Stop'
$controlRepo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
. (Join-Path $PSScriptRoot 'campaign_process_lifecycle.ps1')
$manifestPath = Join-Path $controlRepo "data\campaigns\manifests\$CampaignId.yaml"
$contentRepoPath = 'D:\onedrive\Documents\GitHub\aspose.org'
$py = Join-Path $controlRepo '.venv\Scripts\python.exe'

$ledgerRoot = Join-Path $controlRepo "data\campaigns\$CampaignId"
$evidenceRoot = Join-Path $controlRepo "reports\campaigns\$CampaignId\evidence"
$campaignWatchdogState = Join-Path $ledgerRoot 'watchdog_state.json'
$metaPath = Join-Path $ledgerRoot 'campaign_watchdog_meta.json'
$orphanLog = Join-Path $controlRepo "reports\campaigns\$CampaignId\runtime\orphan_kills.log"
$alertLog = Join-Path $evidenceRoot 'ALERTS.log'
$tickLog = Join-Path $controlRepo "reports\campaigns\$CampaignId\runtime\campaign_watchdog.log"
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $tickLog) | Out-Null

function Write-Tick([string]$Message) {
    "$(Get-Date -Format o) $Message" | Add-Content -LiteralPath $tickLog
}

function Get-AcceptedCount {
    $receipts = Join-Path $ledgerRoot 'acceptance_receipts.jsonl'
    if (-not (Test-Path $receipts)) { return 0 }
    @(Get-Content -LiteralPath $receipts | Where-Object { $_.Trim() }).Count
}

function Get-Meta {
    if (Test-Path $metaPath) {
        try { return Get-Content -LiteralPath $metaPath -Raw | ConvertFrom-Json } catch { }
    }
    [pscustomobject]@{
        consecutive_no_progress_relaunches = 0
        last_accepted_count                = -1
        last_relaunch_at                   = $null
        last_alert_signature               = $null
        last_alert_at                      = $null
        stopped                            = $false
    }
}

function Save-Meta($meta) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $metaPath) | Out-Null
    $meta | ConvertTo-Json | Set-Content -LiteralPath $metaPath -Encoding UTF8
}

function Send-Alert([string]$Signature, [string]$Message, $meta) {
    $now = Get-Date
    $recent = $false
    if ($meta.last_alert_signature -eq $Signature -and $meta.last_alert_at) {
        $recent = ((New-TimeSpan -Start ([datetime]$meta.last_alert_at) -End $now).TotalHours) -lt $ReAlertAfterHours
    }
    if ($recent) { return }

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $alertLog) | Out-Null
    "$(Get-Date -Format o) [$Signature] $Message" | Add-Content -LiteralPath $alertLog

    $source = 'HugoTranslatorCampaignWatchdog'
    try {
        if (-not [System.Diagnostics.EventLog]::SourceExists($source)) {
            New-EventLog -LogName Application -Source $source -ErrorAction Stop
        }
        Write-EventLog -LogName Application -Source $source -EventId 1000 `
            -EntryType Warning -Message $Message -ErrorAction Stop
    } catch {
        Write-Tick "event_log_write_failed $($_.Exception.Message)"
    }

    $meta.last_alert_signature = $Signature
    $meta.last_alert_at = $now.ToString('o')
}

$meta = Get-Meta

if ($Resume) {
    # A deliberate validation pause is authoritative during ordinary ticks,
    # but an explicit post-investigation operator resume must clear it too.
    # Preserve the original state as evidence before removing only the live
    # control file; otherwise the following tick would immediately recreate
    # the same stop condition despite reporting a successful resume.
    if (Test-Path $campaignWatchdogState) {
        $resumeArchive = Join-Path $evidenceRoot (
            'resolved-watchdog-state-' + (Get-Date -Format 'yyyyMMddTHHmmssfffK').Replace(':', '') + '.json'
        )
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $resumeArchive) | Out-Null
        Copy-Item -LiteralPath $campaignWatchdogState -Destination $resumeArchive -Force
        Remove-Item -LiteralPath $campaignWatchdogState -Force
        Write-Tick "state=RESUME_ARCHIVED_PAUSE archive=$resumeArchive"
    }
    $meta.stopped = $false
    $meta.consecutive_no_progress_relaunches = 0
    Save-Meta $meta
    Write-Tick 'state=RESUMED_BY_OPERATOR -- stop and quality-pause state cleared; not relaunching this tick'
    Write-Output "Resumed. The next scheduled watchdog tick will supervise '$CampaignId' normally again."
    exit 0
}

$live = @(Get-CampaignLiveProcesses -CampaignId $CampaignId)
$acceptedNow = Get-AcceptedCount

if ($live.Count -gt 0) {
    $oldest = ($live | Sort-Object AgeMinutes -Descending | Select-Object -First 1)
    $stale = $false
    if ($oldest.AgeMinutes -ge $StaleAfterMinutes -and $acceptedNow -eq $meta.last_accepted_count) {
        # Live long enough that a fresh launch's 90-120s pre-first-log-line
        # window (see project/loop-prompt.md field notes) cannot explain it,
        # and zero new accepted cells since we last looked. Evidence, not a
        # guess: log everything about what's being killed and why.
        $stale = $true
    }
    if ($stale) {
        Write-Tick "state=STALE age_minutes=$($oldest.AgeMinutes) accepted=$acceptedNow killing $($live.Count) process(es)"
        Stop-CampaignOrphanProcesses -Processes $live -Reason "stale >= $StaleAfterMinutes min with no new accepted cells" -LogPath $orphanLog | Out-Null
        $live = @()
    } else {
        Write-Tick "state=RUNNING age_minutes=$($oldest.AgeMinutes) accepted=$acceptedNow live=$($live.Count)"
        $meta.last_accepted_count = $acceptedNow
        $meta.consecutive_no_progress_relaunches = 0
        Save-Meta $meta
        exit 0
    }
}

# NOT_RUNNING (either genuinely idle, or just cleaned up above as stale).
#
# Commit whatever qualifying batches are already sitting uncommitted BEFORE
# any of the pause/relaunch decisions below -- a wave that ends in a
# validation-regression pause or a no-progress stop can still hold perfectly
# good, already-accepted receipts that deserve to land regardless of whether
# the campaign itself keeps going. This also covers the crash/interrupt case
# where a prior run accumulated receipts but never reached its own
# end-of-run reconcile step. Safe here specifically because we've just
# confirmed nothing is live: this never races the active-run ledger-lock
# contention that ruled out reconciling from inside the launcher's own
# per-tick progress loop.
try {
    # No --session-id: this tick's identity was never registered with
    # session_ledger.py (unlike a launcher run's own $SessionId, which the
    # run itself registers at startup), and passing an unregistered one
    # explicitly is refused outright ("names a none manifest") rather than
    # falling back -- found live 2026-09-17. Omitting the flag is the
    # governed tool's own documented fallback: an unknown identity is
    # covered by the commit's lookback window instead.
    & $py "$controlRepo\scripts\campaign\reconcile_receipted_commits.py" `
        --manifest $manifestPath --content-repo $contentRepoPath `
        --ledger-root (Join-Path $controlRepo 'data\campaigns') `
        --min-batch-size 5 --execute | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Tick "state=RECONCILE_FAILED exit=$LASTEXITCODE -- continuing regardless"
    }
} catch {
    Write-Tick "state=RECONCILE_FAILED error=$($_.Exception.Message) -- continuing regardless"
}

$campaignState = $null
if (Test-Path $campaignWatchdogState) {
    try { $campaignState = Get-Content -LiteralPath $campaignWatchdogState -Raw | ConvertFrom-Json } catch { }
}

$needsHuman = $campaignState -and $campaignState.status -eq 'PAUSED_VALIDATION_REGRESSION'
if ($needsHuman) {
    $reason = $campaignState.reason
    Write-Tick "state=PAUSED_NEEDS_HUMAN reason=$reason accepted=$acceptedNow -- not relaunching"
    Send-Alert -Signature "needs_human:$reason" -Message (
        "Campaign '$CampaignId' is paused for a reason a repeat attempt cannot fix " +
        "(status=$($campaignState.status), reason=$reason). Not relaunching. " +
        "Investigate root_causes=$($campaignState.root_causes -join ',') before clearing " +
        "$metaPath's stopped flag and re-running the sweep task manually."
    ) -meta $meta
    $meta.stopped = $true
    Save-Meta $meta
    exit 0
}

if ($meta.stopped) {
    Write-Tick 'state=STOPPED_AWAITING_HUMAN -- meta.stopped is set; not relaunching until cleared'
    exit 0
}

if ($acceptedNow -gt $meta.last_accepted_count) {
    # Real forward progress happened since the last time this watchdog acted
    # (a prior tick's relaunch worked, or the campaign completed a batch
    # before stopping cleanly) -- this is not a stuck loop.
    $meta.consecutive_no_progress_relaunches = 0
}

if ($meta.consecutive_no_progress_relaunches -ge $MaxConsecutiveNoProgressRelaunches) {
    Write-Tick "state=NO_PROGRESS_LIMIT_REACHED relaunches=$($meta.consecutive_no_progress_relaunches) accepted=$acceptedNow -- not relaunching"
    Send-Alert -Signature 'no_progress_limit' -Message (
        "Campaign '$CampaignId' has been relaunched $($meta.consecutive_no_progress_relaunches) times " +
        "with zero new accepted cells (accepted=$acceptedNow). Not relaunching again. " +
        "This is this watchdog's deterministic replacement for a Claude-session cold-boot -- " +
        "it stops and alerts instead of escalating to any agent. Investigate " +
        "$tickLog and the most recent child logs under logs\, then clear " +
        "$metaPath's stopped flag (or delete it) to resume."
    ) -meta $meta
    $meta.stopped = $true
    Save-Meta $meta
    exit 0
}

# TC-PORT-LLM-015: confirmed live via a real hard-kill recovery test --
# work_claims.acquire_claim only checks TTL expiry (default 45 minutes), not
# whether the holding session's process is actually alive. A hard-killed
# launcher (crash, reboot, forced Stop-Process) leaves its family claim
# looking perfectly valid to any other reader, so the very next relaunch
# attempt -- the one thing this watchdog exists to do -- was refused with
# "Another session holds the family claim", for however much of the 45
# minutes remained. This watchdog has ALREADY independently confirmed, via
# real OS process enumeration (not the claims file), that nothing is
# running for this campaign, so releasing a claim that says otherwise here
# is correcting a proven-stale record, not overriding a genuinely active
# session elsewhere in the fleet.
$familyKey = "family:$CampaignId"
$claimJson = & $py -c @"
import sys, json
sys.path.insert(0, r'$controlRepo')
from src.workers.work_claims import active_claim
c = active_claim('$familyKey')
print(json.dumps(c))
"@
if ($claimJson -and $claimJson.Trim() -ne 'null') {
    $claim = $claimJson | ConvertFrom-Json
    Write-Tick "state=STALE_CLAIM_DETECTED session_id=$($claim.session_id) expires_at=$($claim.expires_at) -- no live process exists; releasing before relaunch"
    & $py -c @"
import sys
sys.path.insert(0, r'$controlRepo')
from src.workers.work_claims import release_claim
release_claim('$familyKey', '$($claim.session_id)')
"@ | Out-Null
}

Write-Tick "state=RELAUNCHING attempt=$($meta.consecutive_no_progress_relaunches + 1) accepted=$acceptedNow max_workers=$MaxWorkers"
$sweepScript = Join-Path $controlRepo 'scripts\campaign\run_portfolio_sweep_task.ps1'
$powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
Start-Process -FilePath $powershell `
    -ArgumentList @(
        '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', "`"$sweepScript`"",
        '-MaxWorkers', $MaxWorkers, '-CampaignId', "`"$CampaignId`""
    ) `
    -WorkingDirectory $controlRepo -WindowStyle Minimized | Out-Null

$meta.consecutive_no_progress_relaunches += 1
$meta.last_relaunch_at = (Get-Date -Format o)
$meta.last_accepted_count = $acceptedNow
Save-Meta $meta
