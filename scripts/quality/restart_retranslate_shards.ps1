# Restart products.aspose.org retranslation shards as detached Windows processes.
# Uses Start-Process so shards survive shell/Claude Code session expiry.
# Run: pwsh -File scripts/quality/restart_retranslate_shards.ps1
# Optional args: -RunId 20260703_monitored -Resume

param(
    [string]$RunId = "20260703_monitored",
    [switch]$Resume,
    [switch]$RetryFailed,
    [switch]$Force   # Kill existing shard processes before starting
)

$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Script = Join-Path $Root "scripts\quality\products_org_governed_retranslate.py"

$Shards = @(
    @{ Id = "s1"; Locales = "ar,bg,ca,cs,da,de,el,es,fa" },
    @{ Id = "s2"; Locales = "fi,fr,he,hi,hr,hu,id,it,ja" },
    @{ Id = "s3"; Locales = "ko,lt,lv,ms,nl,no,pl,pt,ro" },
    @{ Id = "s4"; Locales = "ru,sk,sr,sv,th,tr,uk,vi,zh" }
)

# Optionally kill running shard processes
if ($Force) {
    Write-Host "Stopping existing shard processes..."
    Get-Process python -ErrorAction SilentlyContinue | ForEach-Object {
        $cmd = (Get-WmiObject Win32_Process -Filter "ProcessId=$($_.Id)").CommandLine
        if ($cmd -match "products_org_governed_retranslate" -and $cmd -match "--shard-id") {
            Write-Host "  Killing PID=$($_.Id)"
            $_ | Stop-Process -Force
        }
    }
    Start-Sleep -Seconds 2
}

# Check for already-running shards
$running = @{}
Get-Process python -ErrorAction SilentlyContinue | ForEach-Object {
    $cmd = (Get-WmiObject Win32_Process -Filter "ProcessId=$($_.Id)").CommandLine
    foreach ($s in $Shards) {
        if ($cmd -match "products_org_governed_retranslate" -and $cmd -match "--shard-id $($s.Id)") {
            $running[$s.Id] = $_.Id
        }
    }
}

foreach ($shard in $Shards) {
    if ($running.ContainsKey($shard.Id)) {
        Write-Host "SKIP shard=$($shard.Id) already running PID=$($running[$shard.Id])"
        continue
    }

    $LogFile = Join-Path $Root ".local\shard_$($shard.Id).log"
    $Args = @(
        $Script,
        "--model", "professionalize_llm",
        "--run-id", $RunId,
        "--shard-id", $shard.Id,
        "--only-locales", $shard.Locales
    )
    if ($Resume) { $Args += "--resume" }
    if ($RetryFailed) { $Args += "--retry-failed" }

    # Start-Process with -NoNewWindow + output redirect keeps it detached from current shell
    $proc = Start-Process `
        -FilePath $Python `
        -ArgumentList $Args `
        -WorkingDirectory $Root `
        -RedirectStandardOutput $LogFile `
        -RedirectStandardError "$LogFile.err" `
        -NoNewWindow `
        -PassThru

    Write-Host "STARTED shard=$($shard.Id) PID=$($proc.Id) locales=$($shard.Locales)"
}

Write-Host ""
Write-Host "Monitor with:"
Write-Host "  tail -f .local/shard_s1.log .local/shard_s2.log .local/shard_s3.log .local/shard_s4.log"
