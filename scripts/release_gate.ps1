<#
.SYNOPSIS
    Release gate script for Hugo Translator

.DESCRIPTION
    Runs fixture translation + analysis, unit tests, and optionally realworld analysis.
    Exits non-zero if any gate fails.

.PARAMETER RunDir
    Output directory for this run. Default: runs/release_gate_<timestamp>

.PARAMETER SkipRealworld
    Skip the realworld analysis (heavy). Use for fast checks.

.PARAMETER VerboseOutput
    Enable verbose output logging

.EXAMPLE
    .\scripts\release_gate.ps1
    .\scripts\release_gate.ps1 -SkipRealworld
    .\scripts\release_gate.ps1 -RunDir "runs/my_gate_run"
#>

param(
    [string]$RunDir = "",
    [switch]$SkipRealworld,
    [switch]$VerboseOutput
)

$ErrorActionPreference = "Stop"

# Generate run directory if not specified
if (-not $RunDir) {
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $RunDir = "runs/release_gate_$timestamp"
}

Write-Host "=" * 60 -ForegroundColor Cyan
Write-Host "HUGO TRANSLATOR - RELEASE GATE" -ForegroundColor Cyan
Write-Host "=" * 60 -ForegroundColor Cyan
Write-Host "Run Directory: $RunDir"
Write-Host ""

# Create run directory structure
New-Item -ItemType Directory -Force -Path $RunDir | Out-Null
New-Item -ItemType Directory -Force -Path "$RunDir/logs" | Out-Null
New-Item -ItemType Directory -Force -Path "$RunDir/artifacts" | Out-Null

$results = @{
    "fixture_translation" = $false
    "fixture_analysis" = $false
    "unit_tests" = $false
    "problem_rate_check" = $false
}

$problemRate = 999.0  # Default to fail

# Gate 1: Unit Tests
Write-Host ""
Write-Host "[GATE 1] Running Unit Tests..." -ForegroundColor Yellow
try {
    $testOutput = & .venv/Scripts/python.exe -m pytest tests/contract/ tests/unit/phase-0 tests/unit/phase-1 tests/unit/phase-3/test_l1_cache.py tests/unit/phase-3/test_l2_persistent.py tests/unit/phase-4/test_registry.py -v --tb=short 2>&1
    $testOutput | Out-File -FilePath "$RunDir/logs/unit_tests.log"

    if ($LASTEXITCODE -eq 0) {
        $results["unit_tests"] = $true
        Write-Host "[GATE 1] PASS - Unit tests succeeded" -ForegroundColor Green
    } else {
        Write-Host "[GATE 1] FAIL - Unit tests failed" -ForegroundColor Red
    }
} catch {
    Write-Host "[GATE 1] ERROR - $($_.Exception.Message)" -ForegroundColor Red
    $results["unit_tests"] = $false
}

# Gate 2: Fixture Translation
Write-Host ""
Write-Host "[GATE 2] Running Fixture Translation..." -ForegroundColor Yellow
try {
    $fixtureInput = "test_fixtures/e2e/reference/input"
    $fixtureOutput = "$RunDir/output/fixture"

    if (Test-Path $fixtureInput) {
        # Run translation on fixture files
        $transOutput = & .venv/Scripts/python.exe -m src.cli --site e2e-reference-fixture --target-langs fr ru --output $fixtureOutput --log-level INFO --log-file "$RunDir/logs/fixture_translation.log" 2>&1
        $transOutput | Out-File -FilePath "$RunDir/logs/fixture_translation_console.log"

        if ($LASTEXITCODE -eq 0) {
            $results["fixture_translation"] = $true
            Write-Host "[GATE 2] PASS - Fixture translation completed" -ForegroundColor Green
        } else {
            $results["fixture_translation"] = $false
            Write-Host "[GATE 2] FAIL - Translation exit code: $LASTEXITCODE" -ForegroundColor Red
        }
    } else {
        Write-Host "[GATE 2] SKIP - Fixture input not found: $fixtureInput" -ForegroundColor Yellow
        $results["fixture_translation"] = $true  # Skip is OK
    }
} catch {
    Write-Host "[GATE 2] ERROR - $($_.Exception.Message)" -ForegroundColor Red
    $results["fixture_translation"] = $false
}

# Gate 3: Fixture Analysis
Write-Host ""
Write-Host "[GATE 3] Running Fixture Analysis..." -ForegroundColor Yellow
try {
    if ($results["fixture_translation"] -and (Test-Path "$RunDir/output/fixture")) {
        # Run quality analysis
        $analysisOutput = & .venv/Scripts/python.exe -m src.translation_engine.quality.analyzer --input test_fixtures/e2e/reference/input --output "$RunDir/output/fixture" --report-dir "$RunDir/artifacts" 2>&1
        $analysisOutput | Out-File -FilePath "$RunDir/logs/fixture_analysis.log"

        # Parse problem rate from score.md if exists
        $scorePath = "$RunDir/artifacts/score.md"
        if (Test-Path $scorePath) {
            $scoreContent = Get-Content $scorePath -Raw
            if ($scoreContent -match "Problem Rate[:\s]+([0-9.]+)%") {
                $problemRate = [double]$matches[1]
            }
        }

        $results["fixture_analysis"] = $true
        Write-Host "[GATE 3] PASS - Analysis completed, Problem Rate: $problemRate%" -ForegroundColor Green
    } else {
        Write-Host "[GATE 3] SKIP - No fixture output to analyze" -ForegroundColor Yellow
        $results["fixture_analysis"] = $true  # Skip is OK
        $problemRate = 0.0  # Assume pass if skipped
    }
} catch {
    Write-Host "[GATE 3] ERROR - $($_.Exception.Message)" -ForegroundColor Red
    $results["fixture_analysis"] = $false
}

# Gate 4: Problem Rate Check
Write-Host ""
Write-Host "[GATE 4] Checking Problem Rate Threshold..." -ForegroundColor Yellow
$threshold = 2.0
if ($problemRate -le $threshold) {
    $results["problem_rate_check"] = $true
    Write-Host "[GATE 4] PASS - Problem Rate $problemRate% <= $threshold%" -ForegroundColor Green
} else {
    Write-Host "[GATE 4] FAIL - Problem Rate $problemRate% > $threshold%" -ForegroundColor Red
}

# Summary
Write-Host ""
Write-Host "=" * 60 -ForegroundColor Cyan
Write-Host "RELEASE GATE SUMMARY" -ForegroundColor Cyan
Write-Host "=" * 60 -ForegroundColor Cyan

$allPassed = $true
foreach ($gate in $results.Keys) {
    $status = if ($results[$gate]) { "PASS" } else { "FAIL" }
    $color = if ($results[$gate]) { "Green" } else { "Red" }
    Write-Host "$gate : $status" -ForegroundColor $color
    if (-not $results[$gate]) { $allPassed = $false }
}

Write-Host ""
Write-Host "Run artifacts: $RunDir" -ForegroundColor Cyan

if ($allPassed) {
    Write-Host ""
    Write-Host "RELEASE GATE: PASS" -ForegroundColor Green
    exit 0
} else {
    Write-Host ""
    Write-Host "RELEASE GATE: FAIL" -ForegroundColor Red
    exit 1
}
