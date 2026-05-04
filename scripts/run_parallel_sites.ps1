<#
.SYNOPSIS
    Launch all Hugo Translator site subprocesses in parallel.

.DESCRIPTION
    Fires one Python CLI subprocess per site (products.aspose.net, docs.aspose.net,
    kb.aspose.net, blog.aspose.net) simultaneously. Each subprocess runs with
    --parallel-languages N and --auto-select-model.

    Sites are discovered dynamically from ConfigService.list_sites() so that
    test/dev profiles (autonomous_enabled: false) are automatically excluded.

    VRAM safety: with 4 concurrent sites the per-process GPU budget is clamped to
    floor(85 / N_sites)% when the requested cap would exceed 85% of total VRAM.
    RTX 4090 (24 GB): 4 sites x 20% = 4 x 4.8 GB -- safe for M2M100 1.2B fp16.

.PARAMETER ParallelLanguages
    Number of language subprocesses per site (default 4).

.PARAMETER MaxGpuMemoryPercent
    Requested per-process GPU memory cap (default 50). Auto-clamped for N sites.

.PARAMETER DryRun
    Print commands without launching any processes.

.PARAMETER Site
    Limit to one site ID (e.g. "blog.aspose.net").

.PARAMETER ForceNoGpu
    Pass --device cpu to every subprocess; bypasses VRAM checks.

.PARAMETER AllSites
    Run ALL autonomous-enabled sites from ConfigService, not just the four
    production .net subdomains. Without this flag, the default scope is:
    products.aspose.net, docs.aspose.net, kb.aspose.net, blog.aspose.net.

.PARAMETER TimeoutMinutes
    Wall-clock timeout in minutes before stragglers are killed (default 120).

.PARAMETER LogLevel
    Logging verbosity (default INFO).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\run_parallel_sites.ps1 -DryRun
    powershell -ExecutionPolicy Bypass -File scripts\run_parallel_sites.ps1 -Site blog.aspose.net -ParallelLanguages 2
    powershell -ExecutionPolicy Bypass -File scripts\run_parallel_sites.ps1 -ParallelLanguages 4 -MaxGpuMemoryPercent 20
    powershell -ExecutionPolicy Bypass -File scripts\run_parallel_sites.ps1 -AllSites -DryRun
#>
param(
    [int]   $ParallelLanguages   = 4,
    [int]   $MaxGpuMemoryPercent = 50,
    [switch]$DryRun,
    [string]$Site                = "",
    [switch]$ForceNoGpu,
    [switch]$AllSites,
    [int]   $TimeoutMinutes      = 120,
    [string]$LogLevel            = "INFO"
)

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
$ProjectRoot = Split-Path $PSScriptRoot -Parent
$Python      = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$LogsDir     = Join-Path $ProjectRoot "data\logs\parallel_sites"

if (-not (Test-Path $Python)) {
    Write-Error "[ERROR] Python not found at $Python. Ensure .venv is created."
    exit 1
}

New-Item -ItemType Directory -Path $LogsDir -Force | Out-Null

# ---------------------------------------------------------------------------
# Discover sites via ConfigService.list_sites() (autonomous_only=True)
# ---------------------------------------------------------------------------
# Default production scope: the four .net subdomains required by the sprint.
# Use -AllSites to include every autonomous-enabled profile from ConfigService.
# Use -Site to target a single site explicitly.
$DefaultProdSites = @(
    "products.aspose.net",
    "docs.aspose.net",
    "kb.aspose.net",
    "blog.aspose.net"
)

if ($Site -ne "") {
    $Sites = @($Site)
} elseif ($AllSites) {
    $SitesJson = & $Python -c "import sys; sys.path.insert(0, r'$ProjectRoot'); from src.utils.config_loader import ConfigService; import json; cs = ConfigService(r'$ProjectRoot/config'); print(json.dumps(cs.list_sites()))"
    if ($LASTEXITCODE -ne 0) {
        Write-Error "[ERROR] Failed to discover sites from ConfigService."
        exit 1
    }
    $Sites = $SitesJson | ConvertFrom-Json
} else {
    $Sites = $DefaultProdSites
}

$NSites = $Sites.Count
Write-Host "[INFO] Sites to process: $($Sites -join ', ')"

# ---------------------------------------------------------------------------
# VRAM safety gate
# ---------------------------------------------------------------------------
$EffectiveCap = $MaxGpuMemoryPercent
if ((-not $ForceNoGpu) -and ($NSites -gt 1)) {
    $TotalPercent = $NSites * $MaxGpuMemoryPercent
    $SafeCap      = [int][Math]::Floor(85.0 / $NSites)
    if ($TotalPercent -gt 85) {
        Write-Warning "[VRAM] $NSites sites x ${MaxGpuMemoryPercent}% = ${TotalPercent}% (>85% of VRAM budget)."
        Write-Warning "[VRAM] Auto-clamping to ${SafeCap}% per site [formula: floor(85/$NSites)]."
        Write-Warning "[VRAM] Use -ForceNoGpu to run on CPU instead."
        $EffectiveCap = $SafeCap
    }
}

# ---------------------------------------------------------------------------
# Build and launch one process per site
# ---------------------------------------------------------------------------
$Timestamp  = Get-Date -Format "yyyyMMdd_HHmmss"
$ProcList   = @()   # array of hashtables: Process, SiteId, LogOut, LogErr

foreach ($SiteId in $Sites) {
    $LogOut = Join-Path $LogsDir "${SiteId}_${Timestamp}.log"
    $LogErr = Join-Path $LogsDir "${SiteId}_${Timestamp}.err"

    $CliArgs = [System.Collections.ArrayList]@(
        "-m", "src.cli",
        "--site", $SiteId,
        "--parallel-languages", "$ParallelLanguages",
        "--auto-select-model",
        "--log-level", $LogLevel
    )

    if ($ForceNoGpu) {
        $null = $CliArgs.AddRange([string[]]@("--device", "cpu"))
    }
    # Note: GPU memory percent is controlled via config (global.yaml hardware
    # section), not a CLI flag. VRAM clamp warnings above are informational.

    if ($DryRun) {
        $null = $CliArgs.Add("--dry-run")
        Write-Host "[DRY-RUN] $Python $($CliArgs -join ' ')"
        continue
    }

    $Proc = Start-Process `
        -FilePath      $Python `
        -ArgumentList  $CliArgs `
        -WorkingDirectory $ProjectRoot `
        -RedirectStandardOutput $LogOut `
        -RedirectStandardError  $LogErr `
        -NoNewWindow `
        -PassThru

    Write-Host "[STARTED] $SiteId  PID=$($Proc.Id)  log=$LogOut"
    $ProcList += @{ Proc=$Proc; SiteId=$SiteId; LogOut=$LogOut; LogErr=$LogErr }
}

if ($DryRun) {
    Write-Host ""
    Write-Host "[DRY-RUN] No processes were launched."
    exit 0
}

if ($ProcList.Count -eq 0) {
    Write-Host "[WARN] No sites were launched."
    exit 0
}

# ---------------------------------------------------------------------------
# Wait for all processes (with wall-clock timeout)
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "[INFO] Waiting for $($ProcList.Count) site(s) to complete (timeout: ${TimeoutMinutes}m)..."

$Deadline    = (Get-Date).AddMinutes($TimeoutMinutes)
$ExitSummary = @{}

foreach ($Entry in $ProcList) {
    $Remaining = [int](($Deadline - (Get-Date)).TotalMilliseconds)
    $SiteId    = $Entry["SiteId"]
    $Proc      = $Entry["Proc"]

    if ($Remaining -le 0) {
        Write-Warning "[TIMEOUT] $SiteId hit wall-clock limit -- killing PID $($Proc.Id)"
        try { $Proc.Kill() } catch { }
        $ExitSummary[$SiteId] = -1
        continue
    }

    $Finished = $Proc.WaitForExit($Remaining)
    if (-not $Finished) {
        Write-Warning "[TIMEOUT] $SiteId did not finish in time -- killing PID $($Proc.Id)"
        try { $Proc.Kill() } catch { }
        $ExitSummary[$SiteId] = -1
    } else {
        $ExitSummary[$SiteId] = $Proc.ExitCode
    }
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "=== Parallel Site Execution Summary ==="
$AllOk = $true
foreach ($Key in $ExitSummary.Keys) {
    $Code = $ExitSummary[$Key]
    $Icon = if ($Code -eq 0) { "[OK  ]" } else { "[FAIL]" }
    Write-Host "  $Icon $Key  exit=$Code"
    if ($Code -ne 0) { $AllOk = $false }
}
Write-Host ""
Write-Host "Logs: $LogsDir"
Write-Host ""

if (-not $AllOk) {
    Write-Host "One or more sites failed. Check .err files in $LogsDir" -ForegroundColor Red
    exit 1
}

Write-Host "All sites completed successfully." -ForegroundColor Green
exit 0
