# Golden Test Suite Execution Script (PowerShell)
# Task: P0-02-GOLDEN-TESTS
# Author: Agent C

$ErrorActionPreference = "Stop"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Golden Test Suite - CLI Backward Compatibility" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# Check if pytest is available
try {
    python -m pytest --version | Out-Null
} catch {
    Write-Host "ERROR: pytest not found" -ForegroundColor Red
    Write-Host "Install: pip install pytest pytest-mock pytest-asyncio" -ForegroundColor Yellow
    exit 1
}

# Verify test file exists
if (-not (Test-Path "tests/golden/test_cli_backward_compat.py")) {
    Write-Host "ERROR: Test file not found" -ForegroundColor Red
    exit 1
}

# Verify site profile exists
if (-not (Test-Path "config/site_profiles/golden-test.yaml")) {
    Write-Host "ERROR: Site profile 'golden-test.yaml' not found" -ForegroundColor Red
    exit 1
}

# Verify test fixtures exist
if (-not (Test-Path "tests/golden/fixtures/minimal_en.md")) {
    Write-Host "ERROR: Test fixture 'minimal_en.md' not found" -ForegroundColor Red
    exit 1
}

Write-Host "✓ Pre-flight checks passed" -ForegroundColor Green
Write-Host ""

# Run golden tests
Write-Host "Running golden tests..." -ForegroundColor Cyan
Write-Host ""

python -m pytest tests/golden/test_cli_backward_compat.py -v $args

# Check exit code
if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "✓ All golden tests passed" -ForegroundColor Green
    Write-Host ""
    Write-Host "Baseline snapshots location:" -ForegroundColor Cyan
    Write-Host "  tests/golden/fixtures/expected_outputs/" -ForegroundColor Gray
    Write-Host ""

    if (Test-Path "tests/golden/fixtures/expected_outputs/*.json") {
        Get-ChildItem "tests/golden/fixtures/expected_outputs/*.json" | Format-Table Name, Length, LastWriteTime
    } else {
        Write-Host "  (No snapshots found - first run will create them)" -ForegroundColor Yellow
    }
} else {
    Write-Host ""
    Write-Host "✗ Golden tests failed" -ForegroundColor Red
    Write-Host ""
    Write-Host "Troubleshooting:" -ForegroundColor Yellow
    Write-Host "  1. Check diff output above to see what changed" -ForegroundColor Gray
    Write-Host "  2. Verify CLI dependencies are installed" -ForegroundColor Gray
    Write-Host "  3. Review test implementation for issues" -ForegroundColor Gray
    Write-Host "  4. If intentional change, update baselines:" -ForegroundColor Gray
    Write-Host "     Remove-Item tests/golden/fixtures/expected_outputs/*.json" -ForegroundColor Gray
    Write-Host "     python -m pytest tests/golden/test_cli_backward_compat.py -v" -ForegroundColor Gray
    exit 1
}

# Additional verification commands
Write-Host ""
Write-Host "=========================================="
Write-Host "Verification Commands"
Write-Host "=========================================="
Write-Host ""

Write-Host "1. Run specific test:" -ForegroundColor Cyan
Write-Host "   python -m pytest tests/golden/test_cli_backward_compat.py::TestCLIBackwardCompatibility::test_golden_01_multilang_strict -v" -ForegroundColor Gray
Write-Host ""

Write-Host "2. View snapshot:" -ForegroundColor Cyan
Write-Host "   Get-Content tests/golden/fixtures/expected_outputs/golden_01_multilang_strict.json | ConvertFrom-Json | ConvertTo-Json -Depth 10" -ForegroundColor Gray
Write-Host ""

Write-Host "3. Test count (expect 4 tests):" -ForegroundColor Cyan
Write-Host "   python -m pytest tests/golden/test_cli_backward_compat.py --collect-only" -ForegroundColor Gray
Write-Host ""

Write-Host "4. Manual CLI test:" -ForegroundColor Cyan
Write-Host "   python -m src.cli --site golden-test --target-langs es,fr --strict --dry-run" -ForegroundColor Gray
Write-Host ""
