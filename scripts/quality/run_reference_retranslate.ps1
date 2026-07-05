<#
.SYNOPSIS
    Single-process watchdog for reference.aspose.org governed retranslation.
    Runs ONE NLLB process at a time covering all 36 locales.
    Restarts on crash, commits new files between runs.

.NOTES
    Uses shard-id=latin-a (existing checkpoint with ar progress).
    All 36 locales are added; items not in checkpoint are new work.
#>

$ErrorActionPreference = "Continue"

$HugoDir     = "C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator"
$AsposeDir   = "C:\Users\prora\OneDrive\Documents\GitHub\aspose.org"
$Python      = "$HugoDir\.venv\Scripts\python.exe"
$Script      = "$HugoDir\scripts\quality\aspose_org_governed_retranslate.py"
$ContentRoot = "$AsposeDir\content\reference.aspose.org"
$RunId       = "aspose_org_multisite_20260704_012331"
$LogFile     = "$HugoDir\data\logs\reference_retranslate_single.log"

# All 36 locales, ar first (highest coverage, fastest to complete)
$AllLocales = "ar,el,bg,ca,cs,da,de,fa,fi,fr,he,hi,hr,hu,id,it,ja,ko,lt,lv,ms,nl,no,pl,pt,ro,ru,sk,sr,sv,th,tr,uk,vi,zh,es"

function Write-Log([string]$Msg) {
    $line = "[$(Get-Date -Format 'HH:mm:ss')] $Msg"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

function Commit-NewFiles {
    $changed = & git -C $AsposeDir status --short -- "content/reference.aspose.org/" 2>$null
    $files = @($changed | Where-Object { $_ -match '\S' })
    if ($files.Count -lt 1) {
        Write-Log "No new reference files to commit."
        return
    }

    & git -C $AsposeDir add "content/reference.aspose.org/" 2>$null

    $localeCounts = @{}
    foreach ($line in $files) {
        $path = ($line -split '\s+')[-1] -replace '\\','/'
        $parts = $path -split '/'
        for ($i = 0; $i -lt $parts.Length; $i++) {
            if ($parts[$i] -eq 'reference.aspose.org' -and ($i+1) -lt $parts.Length) {
                $loc = $parts[$i+1]
                if ($localeCounts.ContainsKey($loc)) { $localeCounts[$loc]++ }
                else { $localeCounts[$loc] = 1 }
                break
            }
        }
    }

    $n = $files.Count
    $langSummary = ($localeCounts.GetEnumerator() | Sort-Object Name |
        ForEach-Object { "$($_.Name) ($($_.Value))" }) -join ", "
    $localeKeys = ($localeCounts.Keys | Sort-Object) -join "/"

    $commitMsg = "chore(reference): translate $n reference pages $localeKeys`n`n$n translation files across reference.aspose.org.`n- Model: nllb_200_1.3b`n- Languages: $langSummary`n`nRun ID: ${RunId}:reference.aspose.org`nSite: reference.aspose.org`n`nCo-Authored-By: Hugo Translator <hugo-translator@aspose.net>"

    & git -C $AsposeDir commit -m $commitMsg 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Log "Committed $n files: $langSummary"
    } else {
        Write-Log "Commit failed (nothing staged or git error)"
    }
}

function Get-CheckpointStats {
    $cur = "$HugoDir\.local\evidences\reference.aspose.org\$RunId\checkpoints\current.latin-a.json"
    if (Test-Path $cur) {
        $d = Get-Content $cur -Raw | ConvertFrom-Json
        $wi = $d.work_item
        return "$($wi.locale) / $($wi.relative_path)"
    }
    return "(unknown)"
}

# ── Main Loop ──────────────────────────────────────────────────────────────────
Write-Log "=== reference.aspose.org single-process watchdog started ==="
Write-Log "Locales: $AllLocales"

$run = 0
while ($true) {
    $run++
    Write-Log "=== Run #$run ==="

    # Build argument list
    $argList = @(
        $Script,
        "--site", "reference.aspose.org",
        "--run-id", $RunId,
        "--resume", "--retry-failed",
        "--shard-id", "latin-a",
        "--only-locales", $AllLocales,
        "--model", "nllb_200_1.3b",
        "--content-root", $ContentRoot
    ) -join " "

    # Run synchronously, appending output to log
    $proc = Start-Process `
        -FilePath "cmd.exe" `
        -ArgumentList "/c `"$Python`" $argList >> `"$LogFile`" 2>&1" `
        -WorkingDirectory $HugoDir `
        -NoNewWindow -PassThru -Wait

    $exit = $proc.ExitCode
    Write-Log "Run #$run exited (code=$exit). Current item: $(Get-CheckpointStats)"

    # Commit any accumulated files
    Commit-NewFiles

    # Delay before restart
    if ($exit -eq 0) {
        Write-Log "Clean exit — waiting 120s before next run..."
        Start-Sleep -Seconds 120
    } else {
        Write-Log "Crash (exit=$exit) — restarting in 15s..."
        Start-Sleep -Seconds 15
    }
}
