# Log Viewer Script
# View various Hugo Translator log files
# Created: 2026-01-21

param(
    [Parameter(Mandatory=$false)]
    [ValidateSet("startup", "content", "tm", "structured", "all")]
    [string]$LogType = "all",

    [Parameter(Mandatory=$false)]
    [int]$Lines = 50
)

$projectRoot = Split-Path -Parent $PSScriptRoot

function Show-Log {
    param(
        [string]$Path,
        [string]$Name,
        [int]$TailLines
    )

    $fullPath = Join-Path $projectRoot $Path

    if (Test-Path $fullPath) {
        Write-Host ""
        Write-Host "======================================================================" -ForegroundColor Cyan
        Write-Host " $Name" -ForegroundColor Cyan
        Write-Host " Path: $fullPath" -ForegroundColor Gray
        Write-Host "======================================================================" -ForegroundColor Cyan
        Write-Host ""

        # Get last N lines
        $content = Get-Content $fullPath -Tail $TailLines -ErrorAction SilentlyContinue

        if ($content) {
            # Color code certain patterns
            foreach ($line in $content) {
                if ($line -match "ERROR|FAIL|Exception") {
                    Write-Host $line -ForegroundColor Red
                } elseif ($line -match "WARN") {
                    Write-Host $line -ForegroundColor Yellow
                } elseif ($line -match "SUCCESS|COMPLETE|Started") {
                    Write-Host $line -ForegroundColor Green
                } elseif ($line -match "INFO") {
                    Write-Host $line -ForegroundColor Cyan
                } else {
                    Write-Host $line
                }
            }
        } else {
            Write-Host "(File is empty)" -ForegroundColor Gray
        }

        Write-Host ""
    } else {
        Write-Host ""
        Write-Host "======================================================================" -ForegroundColor Yellow
        Write-Host " $Name" -ForegroundColor Yellow
        Write-Host "======================================================================" -ForegroundColor Yellow
        Write-Host "File not found: $fullPath" -ForegroundColor Yellow
        Write-Host "(Workers have not run yet, or logs not created)" -ForegroundColor Gray
        Write-Host ""
    }
}

# Display header
Write-Host ""
Write-Host "=============================================================================" -ForegroundColor Cyan
Write-Host "Hugo Translator - Log Viewer" -ForegroundColor Cyan
Write-Host "=============================================================================" -ForegroundColor Cyan
Write-Host "Showing last $Lines lines" -ForegroundColor Gray
Write-Host ""

# Show requested logs
switch ($LogType) {
    "startup" {
        Show-Log "data\logs\worker_startup.log" "Worker Startup Log" $Lines
    }
    "content" {
        Show-Log "data\logs\content_worker_console.log" "Content Worker Console" $Lines
    }
    "tm" {
        Show-Log "data\logs\tm_worker_console.log" "TM Worker Console" $Lines
    }
    "structured" {
        Show-Log "data\logs\hugo-translator.ndjson" "Structured Logs (NDJSON)" $Lines
    }
    "all" {
        Show-Log "data\logs\worker_startup.log" "Worker Startup Log" $Lines
        Show-Log "data\logs\content_worker_console.log" "Content Worker Console" $Lines
        Show-Log "data\logs\tm_worker_console.log" "TM Worker Console" $Lines
    }
}

Write-Host "=============================================================================" -ForegroundColor Cyan
Write-Host "Tip: Use -Lines parameter to show more/fewer lines (default: 50)" -ForegroundColor Gray
Write-Host "Example: .\scripts\view_logs.ps1 -LogType content -Lines 100" -ForegroundColor Gray
Write-Host "=============================================================================" -ForegroundColor Cyan
Write-Host ""
