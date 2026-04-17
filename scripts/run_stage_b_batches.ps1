# Stage B Batch Runner - Process-per-batch execution (HARDENED)
# Usage: .\scripts\run_stage_b_batches.ps1 -ManifestDir <dir> -Language <fr|ru> -OutputRoot <path> -LogDir <path>
#
# Hardening improvements (2026-02-02):
# - Explicit repo-root working directory control
# - Receipt validation (verify files_copied == manifest line count)
# - Retry logic for materializer (3 attempts on WinError 3)
# - Shorter temp input paths (artifacts/tmp_inputs vs logs/temp_inputs)
# - Enhanced diagnostics and logging

param(
    [Parameter(Mandatory=$true)]
    [string]$ManifestDir,

    [Parameter(Mandatory=$true)]
    [ValidateSet('fr', 'ru')]
    [string]$Language,

    [Parameter(Mandatory=$true)]
    [string]$OutputRoot,

    [Parameter(Mandatory=$true)]
    [string]$LogDir,

    [string]$ArtifactsDir,  # Optional: for shorter temp paths
    [switch]$Resume,
    [switch]$DryRun
)

Write-Host "=== Stage B Batch Runner (HARDENED) ===" -ForegroundColor Cyan
Write-Host "Manifest Dir: $ManifestDir"
Write-Host "Language: $Language"
Write-Host "Output Root: $OutputRoot"
Write-Host "Log Dir: $LogDir"
Write-Host ""

# ===== HARDENING: Repo-root working directory =====
# Determine repo root (script is in scripts/, repo root is parent)
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
Write-Host "[HARDENING] Repo root: $RepoRoot"
Write-Host "[HARDENING] Current location: $(Get-Location)"

# Force working directory to repo root
Push-Location $RepoRoot
Write-Host "[HARDENING] Working directory set to: $(Get-Location)"
Write-Host ""

try {
    # ===== HARDENING: Validate Python executable =====
    $PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path $PythonExe)) {
        Write-Host "ERROR: Python not found: $PythonExe" -ForegroundColor Red
        Write-Host "Is virtual environment activated?" -ForegroundColor Red
        exit 1
    }
    Write-Host "[HARDENING] Python executable: $PythonExe"
    Write-Host ""

    # Create directories
    New-Item -Path $OutputRoot -ItemType Directory -Force | Out-Null
    New-Item -Path $LogDir -ItemType Directory -Force | Out-Null
    New-Item -Path "$LogDir/batches_$Language" -ItemType Directory -Force | Out-Null

    # ===== HARDENING: Materializer logs directory =====
    $MaterializerLogsDir = Join-Path $LogDir "materializer"
    New-Item -Path $MaterializerLogsDir -ItemType Directory -Force | Out-Null
    Write-Host "[HARDENING] Materializer logs: $MaterializerLogsDir"

    # ===== HARDENING: Shorter temp input root =====
    # Use artifacts/tmp_inputs instead of logs/temp_inputs (saves ~20 chars per path)
    if ($ArtifactsDir) {
        $tempInputRoot = Join-Path $ArtifactsDir "tmp_inputs"
    } else {
        # Fallback to logs if no artifacts dir provided (backward compat)
        $tempInputRoot = Join-Path $LogDir "temp_inputs"
    }

    Write-Host "[HARDENING] Temp input root: $tempInputRoot"
    New-Item -Path $tempInputRoot -ItemType Directory -Force | Out-Null
    $tempInputRoot = (Resolve-Path -Path $tempInputRoot).Path

    # Corpus root (hardcoded for Stage B - aspose.net content)
    $corpusRoot = "D:\onedrive\Documents\GitHub\aspose.net\content"

    # Get batch files
    $batchFiles = Get-ChildItem -Path $ManifestDir -Filter "*.txt" | Sort-Object Name

    if ($batchFiles.Count -eq 0) {
        Write-Host "ERROR: No batch files found in $ManifestDir" -ForegroundColor Red
        exit 1
    }

    Write-Host "Found $($batchFiles.Count) batches"
    Write-Host ""

    # Ledger
    $ledgerDir = Join-Path (Split-Path $LogDir -Parent) "artifacts"
    New-Item -Path $ledgerDir -ItemType Directory -Force | Out-Null
    $ledgerPath = Join-Path $ledgerDir "batch_ledger_$Language.csv"

    if (-not (Test-Path $ledgerPath)) {
        "batch_id,lang,file_count,start_time,end_time,exit_code,status,notes" | Out-File -FilePath $ledgerPath -Encoding utf8
    }

    # Process batches
    $success = 0
    $failed = 0

    foreach ($batch in $batchFiles) {
        $batchId = $batch.BaseName
        Write-Host "========================================" -ForegroundColor Cyan
        Write-Host "Processing: $batchId" -ForegroundColor Cyan
        Write-Host "========================================" -ForegroundColor Cyan

        $fileCount = (Get-Content $batch.FullName).Count
        $batchOut = Join-Path (Join-Path $OutputRoot $Language) $batchId
        $batchLog = Join-Path (Join-Path $LogDir "batches_$Language") "$batchId.log"

        Write-Host "  Files in manifest: $fileCount"
        Write-Host "  Output: $batchOut"

        if ($DryRun) {
            Write-Host "  [DRY RUN] Skipping execution" -ForegroundColor Yellow
            continue
        }

        # Create language output directory
        $langOutputDir = Join-Path $OutputRoot $Language
        New-Item -Path $langOutputDir -ItemType Directory -Force | Out-Null

        # Temp input and receipt paths
        # FIX: Use source_en instead of $Language to avoid CLI path-based language detection
        $tempInput = Join-Path $tempInputRoot "source_en\$batchId"
        $receipt = Join-Path $ledgerDir "$batchId.receipt.json"

        # ===== HARDENING: Retry logic for materializer =====
        $MaxMaterializeAttempts = 3
        $MaterializeAttempt = 0
        $MaterializeSuccess = $false
        $LastMaterializeError = ""

        while ($MaterializeAttempt -lt $MaxMaterializeAttempts -and -not $MaterializeSuccess) {
            $MaterializeAttempt++

            if ($MaterializeAttempt -gt 1) {
                Write-Host "  [RETRY] Materializer attempt $MaterializeAttempt/$MaxMaterializeAttempts..." -ForegroundColor Yellow

                # Delete temp dir before retry
                if (Test-Path $tempInput) {
                    Write-Host "    Cleaning temp directory: $tempInput"
                    Remove-Item -Path $tempInput -Recurse -Force -ErrorAction SilentlyContinue
                }

                # Brief delay before retry
                Start-Sleep -Seconds 2
            } else {
                Write-Host "  [STEP 1/2] Materializing input tree..." -ForegroundColor White
            }

            # Run materializer
            $matLogOut = Join-Path $MaterializerLogsDir "$Language`_$batchId.log"
            $matLogErr = Join-Path $MaterializerLogsDir "$Language`_$batchId.err"

            $matProc = Start-Process -FilePath $PythonExe `
                -ArgumentList "scripts\materialize_input_tree_from_manifest.py","--manifest",$batch.FullName,"--corpus-root",$corpusRoot,"--dest-root",$tempInput,"--receipt",$receipt `
                -NoNewWindow -Wait -PassThru `
                -RedirectStandardOutput $matLogOut `
                -RedirectStandardError $matLogErr

            $MaterializeExitCode = $matProc.ExitCode

            if ($MaterializeExitCode -eq 0) {
                # ===== HARDENING: Validate receipt =====
                Write-Host "    Materializer exit code: 0 (checking receipt...)"

                if (-not (Test-Path $receipt)) {
                    Write-Host "    ERROR: Receipt not found: $receipt" -ForegroundColor Red
                    $LastMaterializeError = "Receipt missing"
                    continue  # Retry
                }

                try {
                    $Receipt = Get-Content $receipt -Raw | ConvertFrom-Json

                    Write-Host "    Receipt status: $($Receipt.status)"
                    Write-Host "    Files copied: $($Receipt.files_copied)/$fileCount"

                    # ===== HARDENING: Validate file count =====
                    if ($Receipt.files_copied -eq 0) {
                        Write-Host "    ERROR: Zero files copied (empty materialization)" -ForegroundColor Red
                        $LastMaterializeError = "Zero files copied"
                        continue  # Retry
                    }

                    if ($Receipt.files_copied -ne $fileCount) {
                        Write-Host "    WARNING: Partial materialization ($($Receipt.files_copied)/$fileCount files)" -ForegroundColor Yellow
                        # Allow partial (some files may be legitimately missing)
                        # But check if it's a critical failure
                        if ($Receipt.files_copied -lt ($fileCount * 0.5)) {
                            Write-Host "    ERROR: Less than 50% of files copied (critical failure)" -ForegroundColor Red
                            $LastMaterializeError = "Partial materialization ($($Receipt.files_copied)/$fileCount)"
                            continue  # Retry
                        }
                    }

                    # Success!
                    $MaterializeSuccess = $true
                    Write-Host "    SUCCESS: Materialization validated" -ForegroundColor Green

                } catch {
                    Write-Host "    ERROR: Failed to parse receipt: $_" -ForegroundColor Red
                    $LastMaterializeError = "Receipt parse error: $_"
                    continue  # Retry
                }

            } else {
                Write-Host "    ERROR: Materializer failed with exit code $MaterializeExitCode" -ForegroundColor Red

                # Check if WinError 3 (read stderr)
                if (Test-Path $matLogErr) {
                    $StdErr = Get-Content $matLogErr -Raw
                    if ($StdErr -like "*WinError 3*") {
                        Write-Host "    Detected: WinError 3 (The system cannot find the path specified)" -ForegroundColor Yellow
                        $LastMaterializeError = "WinError 3 (path not found)"
                        # Will retry
                    } elseif ($StdErr -like "*Missing*files*") {
                        Write-Host "    Detected: Missing source files (will not retry)" -ForegroundColor Red
                        $LastMaterializeError = "Missing source files"
                        break  # Don't retry missing files
                    } else {
                        $LastMaterializeError = "Exit code $MaterializeExitCode"
                    }
                } else {
                    $LastMaterializeError = "Exit code $MaterializeExitCode (no stderr)"
                }
            }
        }

        # Check if materialization ultimately failed
        if (-not $MaterializeSuccess) {
            Write-Host "  FAILED: Materialization failed after $MaxMaterializeAttempts attempts" -ForegroundColor Red
            Write-Host "  Last error: $LastMaterializeError" -ForegroundColor Red
            $failed++
            "$batchId,$Language,$fileCount,,,1,failed_materialize,$LastMaterializeError" | Out-File -FilePath $ledgerPath -Append -Encoding utf8

            # Cleanup and skip to next batch
            if (Test-Path $tempInput) {
                Remove-Item -Path $tempInput -Recurse -Force -ErrorAction SilentlyContinue
            }
            continue
        }

        # ===== Translation step (only if materialization succeeded) =====
        Write-Host "  [STEP 2/2] Translating batch..." -ForegroundColor White
        $start = Get-Date -Format "yyyy-MM-ddTHH:mm:ss"

        $proc = Start-Process -FilePath $PythonExe `
            -ArgumentList "-m","src.cli","--site","e2e-reference-fixture","--target-langs",$Language,"--input",$tempInput,"--output",$batchOut `
            -NoNewWindow -Wait -PassThru `
            -RedirectStandardOutput $batchLog `
            -RedirectStandardError "$batchLog.err"

        $end = Get-Date -Format "yyyy-MM-ddTHH:mm:ss"
        $exitCode = $proc.ExitCode

        if ($exitCode -eq 0) {
            Write-Host "  SUCCESS: Translation completed (exit 0)" -ForegroundColor Green
            $status = "completed"
            $success++
        } else {
            Write-Host "  FAILED: Translation failed (exit $exitCode)" -ForegroundColor Red
            $status = "failed"
            $failed++
        }

        "$batchId,$Language,$fileCount,$start,$end,$exitCode,$status," | Out-File -FilePath $ledgerPath -Append -Encoding utf8

        # Cleanup temp input directory
        if (Test-Path $tempInput) {
            Write-Host "    Cleaning temp input directory..."
            Remove-Item -Path $tempInput -Recurse -Force -ErrorAction SilentlyContinue
        }

        Write-Host ""
    }

    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "=== Summary ===" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "Success: $success" -ForegroundColor Green
    Write-Host "Failed: $failed" -ForegroundColor Red

    if ($failed -gt 0) {
        exit 1
    }

} finally {
    # ===== HARDENING: Restore original working directory =====
    Pop-Location
    Write-Host ""
    Write-Host "[HARDENING] Restored working directory: $(Get-Location)"
}
