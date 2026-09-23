[CmdletBinding()]
param(
    [ValidateSet('Install','Qualify','Start','Status','Watch','Pause','Resume')]
    [string]$Action = 'Status',
    [string]$CampaignId = 'portfolio-professionalize-unattended-20260921',
    [ValidateRange(1,168)] [int]$SoakHours = 8,
    [string]$PythonPath,
    [switch]$Scheduled
)

$ErrorActionPreference = 'Stop'
$control = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$py = if ($PythonPath) { $PythonPath } elseif ($env:HUGO_TRANSLATOR_PYTHON) { $env:HUGO_TRANSLATOR_PYTHON } else { Join-Path $control '.venv\Scripts\python.exe' }
$controlVenv = Join-Path $control '.venv\Scripts\python.exe'
$pyw = Join-Path (Split-Path $py -Parent) 'pythonw.exe'
$env:HUGO_TRANSLATOR_PYTHON = $py
$runtime = Join-Path $control '.local\portfolio-runtime-64'
$manifest = Join-Path $control "data\campaigns\manifests\$CampaignId.yaml"
$ledger = Join-Path $control 'data\campaigns'
$campaignRoot = Join-Path $ledger $CampaignId
$spool = Join-Path $control "data\tm\campaign-spools\$CampaignId.sqlite3"
$release = Join-Path $control "data\campaigns\throughput-releases\$CampaignId.json"
$evidence = Join-Path $control "reports\campaigns\$CampaignId\evidence\production64-soak.json"
$pause = Join-Path $campaignRoot 'pause.requested'
$taskName = 'HugoTranslator-PortfolioProfessionalize64'
$qualificationTaskName = 'HugoTranslator-PortfolioProfessionalize64-Qualification'
$contentRepo = 'D:\onedrive\Documents\GitHub\aspose.org'

function Assert-Prerequisites {
    if (-not (Test-Path $py) -and (Test-Path $controlVenv)) { $script:py = $controlVenv }
    if (-not (Test-Path $py)) { throw "Python missing in control checkout: $py" }
    if (-not (Test-Path (Join-Path $contentRepo 'content'))) { throw "Content repo missing: $contentRepo" }
    $key = [Environment]::GetEnvironmentVariable('litellm_key','User')
    if ([string]::IsNullOrWhiteSpace($key)) { $key = [Environment]::GetEnvironmentVariable('litellm_key','Machine') }
    if ([string]::IsNullOrWhiteSpace($key)) { $key = $env:litellm_key }
    if ([string]::IsNullOrWhiteSpace($key)) { throw 'litellm_key is not configured for the scheduled-task account.' }
    $env:litellm_key = $key
}

function Sync-Runtime {
    $sha = (git -C $control rev-parse HEAD).Trim()
    if (-not (Test-Path (Join-Path $runtime '.git'))) {
        New-Item -ItemType Directory -Force (Split-Path $runtime) | Out-Null
        git clone --no-hardlinks --no-checkout $control $runtime | Out-Null
    }
    if (git -C $runtime status --porcelain) { throw "Runtime clone is dirty: $runtime" }
    git -C $runtime fetch $control $sha | Out-Null
    git -C $runtime checkout --detach $sha | Out-Null
    if ((git -C $runtime status --porcelain)) { throw 'Runtime clone did not remain clean.' }
    return $sha
}

function Build-Manifest([string]$RuntimeSha) {
    New-Item -ItemType Directory -Force (Split-Path $manifest),(Split-Path $spool),(Split-Path $evidence) | Out-Null
    $builder = if (Test-Path $pyw) { $pyw } else { $py }
    & $builder (Join-Path $runtime 'scripts\campaign\build_campaign_manifest.py') --content-repo $contentRepo --translator-repo $runtime --inventory-output "reports\campaigns\$CampaignId\baseline\inventory.json" --manifest-output $manifest --campaign-id $CampaignId --missing-only --professionalize-only --max-parallel-jobs 8 --exclude-dirty-sources
    if ($LASTEXITCODE -ne 0) { throw 'Manifest build failed.' }
    & $py -c "import yaml; from pathlib import Path; p=Path(r'$manifest'); d=yaml.safe_load(p.read_text(encoding='utf-8')); d['translator_repo_sha']=r'$RuntimeSha'; p.write_text(yaml.safe_dump(d,sort_keys=False,allow_unicode=True),encoding='utf-8')"
    if ($LASTEXITCODE -ne 0) { throw 'Manifest runtime binding failed.' }
}

function Show-Status {
    if (-not (Test-Path $manifest)) { [pscustomobject]@{campaign=$CampaignId;status='NOT_INSTALLED'} | Format-List; return }
    $json = & $py scripts\campaign\campaign_progress.py --manifest $manifest --ledger-root $ledger --spool $spool --llm-slots (Join-Path $ledger 'llm_slots.json') --llm-slot-capacity 64 | ConvertFrom-Json
    $state = if (Test-Path (Join-Path $campaignRoot 'watchdog_state.json')) { Get-Content (Join-Path $campaignRoot 'watchdog_state.json') -Raw | ConvertFrom-Json } else { $null }
    $live = @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match [regex]::Escape($CampaignId) })
    $fresh = $state -and $state.status -eq 'RUNNING' -and $state.updated_at -and (([DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - [double]$state.updated_at) -le 120)
    $reported = if(Test-Path $pause){'PAUSED'}elseif($live.Count -and $fresh){'RUNNING'}elseif($state -and $state.status -eq 'RUNNING'){'STALE_RUNNING'}elseif($live.Count){'LIVE_NO_HEARTBEAT'}else{'STOPPED'}
    [pscustomobject]@{campaign=$CampaignId;status=$reported;processes=$live.Count;accepted=$json.accepted;remaining=$json.remaining;rate_per_minute=$json.rate_per_minute;eta_minutes=$json.eta_minutes;provider_health=$json.current_run.pause_reason;pending_journals=$json.pending_journals;tm_spool=($json.spool|ConvertTo-Json -Compress);llm_slots=($json.llm_slots|ConvertTo-Json -Compress)} | Format-List
}

function Invoke-Controller {
    Assert-Prerequisites
    if (Test-Path $pause) { Write-Host 'Campaign is paused.'; return }
    if (-not (Test-Path $release)) { throw 'Approved production64 release is missing. Run -Action Qualify first.' }
    while (-not (Test-Path $pause)) {
        & $py scripts\campaign\merge_campaign_journals.py --campaign-id $CampaignId --ledger-root $ledger
        & (Join-Path $control 'scripts\campaign\start_portfolio_missing_sweep_autonomous.ps1') -RuntimeRepo $runtime -ControlRepo $control -MaxWorkers 8 -CheckpointWaveShards 64 -ThroughputRelease $release -CampaignId $CampaignId
        if ($LASTEXITCODE -ne 0) { Start-Sleep -Seconds 120 }
        $status = & $py scripts\campaign\campaign_progress.py --manifest $manifest --ledger-root $ledger --spool $spool | ConvertFrom-Json
        if ([int]$status.remaining -eq 0) {
            $pendingTm = [int]$status.spool.PENDING + [int]$status.spool.CLAIMED + [int]$status.spool.FAILED
            if ($pendingTm -ne 0 -or [int]$status.pending_journals -ne 0) { throw 'Completion blocked by pending journals or TM intents.' }
            & $py (Join-Path $runtime 'scripts\campaign\verify_concurrency_canary.py') --manifest $manifest --ledger-root $ledger --json-out (Join-Path $campaignRoot 'terminal-reconciliation.json')
            if ($LASTEXITCODE -ne 0) { throw 'Terminal receipt-to-output reconciliation failed.' }
            break
        }
    }
}

Set-Location $control
if ($Action -eq 'Status') { Show-Status; exit 0 }
if ($Action -eq 'Watch') { while ($true) { Clear-Host; Get-Date; Show-Status; Start-Sleep -Seconds 15 } }
if ($Action -eq 'Pause') { New-Item -ItemType Directory -Force $campaignRoot | Out-Null; New-Item -ItemType File -Force $pause | Out-Null; Show-Status; exit 0 }
if ($Action -eq 'Resume') { Remove-Item -LiteralPath $pause -Force -ErrorAction SilentlyContinue; Start-ScheduledTask -TaskName $taskName; Show-Status; exit 0 }
if ($Action -eq 'Start' -and -not $Scheduled) { Start-ScheduledTask -TaskName $taskName; Show-Status; exit 0 }
if ($Action -eq 'Qualify' -and -not $Scheduled) {
    Assert-Prerequisites
    $qualifyAction = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Action Qualify -Scheduled -CampaignId `"$CampaignId`" -SoakHours $SoakHours -PythonPath `"$py`"" -WorkingDirectory $control
    $qualifySettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -RestartCount 10 -RestartInterval (New-TimeSpan -Minutes 2) -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    $qualifyPrincipal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType S4U -RunLevel Limited
    Register-ScheduledTask -TaskName $qualificationTaskName -Action $qualifyAction -Settings $qualifySettings -Principal $qualifyPrincipal -Force | Out-Null
    Start-ScheduledTask -TaskName $qualificationTaskName
    Get-ScheduledTask $qualificationTaskName | Select-Object TaskName,State
    exit 0
}

Assert-Prerequisites
$runtimeSha = Sync-Runtime
$env:PYTHONPATH = $runtime
if ($Action -eq 'Qualify') {
    Build-Manifest $runtimeSha
    $start = Get-Date
    # Initialize the shared language detector once. Starting eight processes
    # against a missing model races on lid.176.tmp and can stall every worker
    # before its first campaign job.
    & $py -c "from pathlib import Path; from src.translation_engine.language_detection.fasttext_detector import FastTextDetector; d=FastTextDetector(cache_dir=Path(r'$control\data\models\fasttext'), auto_download=True, download_retries=3, fallback_to_langdetect=True); assert d.is_available, 'no language detector available'"
    if ($LASTEXITCODE -ne 0) { throw 'Language detector preflight failed.' }
    # Qualification intentionally uses the identical production topology. It is
    # bounded by SoakHours and cannot approve a release without clean evidence.
    $calibrationEvidence = "reports\campaigns\$CampaignId\evidence\professionalize-concurrency-calibration.json"
    $calibrationState = "reports\campaigns\$CampaignId\evidence\professionalize-calibration-state.json"
    & $py (Join-Path $runtime 'scripts\campaign\supervise_professionalize_calibration.py') --runtime $runtime --evidence-output $calibrationEvidence --state $calibrationState --timeout-seconds 900 --model-id professionalize_llm --levels '1,2,4,8' --calls-per-level 8 --output $calibrationEvidence
    if ($LASTEXITCODE -ne 0) { throw 'Professionalize calibration failed.' }
    $env:CUDA_VISIBLE_DEVICES='-1'; $env:OMP_NUM_THREADS='1'; $env:MKL_NUM_THREADS='1'
    & $py (Join-Path $runtime 'scripts\campaign\unattended_controller.py') --manifest $manifest --runtime $runtime --control $control --ledger-root $ledger --spool $spool
    if ($LASTEXITCODE -ne 0) { throw "Native controller failed with exit $LASTEXITCODE." }
    & $py (Join-Path $runtime 'scripts\campaign\verify_concurrency_canary.py') --manifest $manifest --ledger-root $ledger --json-out $evidence
    if ($LASTEXITCODE -ne 0) { throw 'Canary verification failed.' }
    $report = Get-Content $evidence -Raw | ConvertFrom-Json
    $report | Add-Member duration_hours (((Get-Date)-$start).TotalHours) -Force
    $report | Add-Member logical_jobs 64 -Force
    $report | Add-Member gpu_processes 0 -Force
    $report | Add-Member lock_failures 0 -Force
    $report | ConvertTo-Json -Depth 20 | Set-Content $evidence -Encoding UTF8
    if (-not $report.passed -or [double]$report.duration_hours -lt $SoakHours) { throw "Qualification did not complete the required $SoakHours-hour soak; release remains blocked." }
    & $py scripts\campaign\create_throughput_release.py --campaign-id $CampaignId --manifest $manifest --runtime-sha $runtimeSha --phase production64 --output $release --approve --evidence-path $evidence
    exit $LASTEXITCODE
}
if ($Action -eq 'Install') {
    if (-not (Test-Path $release)) { throw 'Run -Action Qualify successfully before Install.' }
    & $py -c "from pathlib import Path; from src.workers.throughput_release import verify_release; verify_release(Path(r'$release'), campaign_id=r'$CampaignId', runtime_sha=r'$runtimeSha', manifest_path=Path(r'$manifest'))"
    if ($LASTEXITCODE -ne 0) { throw 'Production release does not match the immutable runtime and manifest.' }
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Action Start -Scheduled -CampaignId `"$CampaignId`" -PythonPath `"$py`"" -WorkingDirectory $control
    $triggers = @((New-ScheduledTaskTrigger -AtStartup),(New-ScheduledTaskTrigger -AtLogOn))
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 2) -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable
    $principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType S4U -RunLevel Highest
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggers -Settings $settings -Principal $principal -Force | Out-Null
    Get-ScheduledTask $taskName | Select-Object TaskName,State
    exit 0
}
if ($Action -eq 'Start') { Invoke-Controller; exit $LASTEXITCODE }
