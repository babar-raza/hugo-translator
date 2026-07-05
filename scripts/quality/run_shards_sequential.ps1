# Run all 4 retranslation shards sequentially (one at a time).
# Usage: .\run_shards_sequential.ps1 [-RunId <id>] [-Resume] [-RetryFailed]

param(
    [string]$RunId       = "20260703_monitored",
    [switch]$Resume,
    [switch]$RetryFailed
)

$Root    = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Python  = Join-Path $Root ".venv\Scripts\python.exe"
$Script  = Join-Path $Root "scripts\quality\products_org_governed_retranslate.py"
$LogDir  = Join-Path $Root ".local"

$Shards = @(
    @{ Id = "s1"; Locales = "ar,bg,ca,cs,da,de,el,es,fa" },
    @{ Id = "s2"; Locales = "fi,fr,he,hi,hr,hu,id,it,ja" },
    @{ Id = "s3"; Locales = "ko,lt,lv,ms,nl,no,pl,pt,ro" },
    @{ Id = "s4"; Locales = "ru,sk,sr,sv,th,tr,uk,vi,zh" }
)

foreach ($shard in $Shards) {
    $LogFile = Join-Path $LogDir "shard_$($shard.Id).log"
    $ErrFile = "$LogFile.err"

    $ShardArgs = @(
        $Script,
        "--model", "professionalize_llm",
        "--run-id", $RunId,
        "--shard-id", $shard.Id,
        "--only-locales", $shard.Locales
    )
    if ($Resume)      { $ShardArgs += "--resume" }
    if ($RetryFailed) { $ShardArgs += "--retry-failed" }

    Write-Host ""
    Write-Host "========================================"
    Write-Host "STARTING shard=$($shard.Id)  locales=$($shard.Locales)"
    Write-Host "Log: $LogFile"
    Write-Host "========================================"

    Set-Content -Path $LogFile -Value ""
    Set-Content -Path $ErrFile -Value ""

    $proc = Start-Process `
        -FilePath $Python `
        -ArgumentList $ShardArgs `
        -WorkingDirectory $Root `
        -RedirectStandardOutput $LogFile `
        -RedirectStandardError  $ErrFile `
        -NoNewWindow `
        -PassThru

    Write-Host "PID=$($proc.Id) waiting for completion..."

    $ckptBase = Join-Path $Root ".local\evidences\hugo-translator-retranslation-$RunId\checkpoints"

    while (-not $proc.HasExited) {
        Start-Sleep -Seconds 30
        $currentJson = Join-Path $ckptBase "current.$($shard.Id).json"
        if (Test-Path $currentJson) {
            try {
                $cur  = Get-Content $currentJson -Raw | ConvertFrom-Json
                $item = $cur.work_item
                Write-Host "  [$(Get-Date -Format 'HH:mm:ss')] $($item.locale)/$($item.relative_path)"
            } catch {
                # ignore parse errors
            }
        }
    }

    $exitCode = $proc.ExitCode
    Write-Host ""
    if ($exitCode -eq 0) {
        Write-Host "DONE shard=$($shard.Id) exit=0"
    } else {
        Write-Host "WARN shard=$($shard.Id) exit=$exitCode check $ErrFile"
    }

    Write-Host "--- last 5 lines of log ---"
    Get-Content $LogFile -Tail 5 -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "All shards complete."
