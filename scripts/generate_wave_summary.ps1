# Generate Wave Summary from Metadata
# Reads .translation_metadata.json files to compute accurate file counts
param(
    [Parameter(Mandatory=$true)]
    [string]$RunDir,

    [Parameter(Mandatory=$false)]
    [string]$OutputFile = ""
)

$ErrorActionPreference = "Stop"

# Default output file if not specified
if ($OutputFile -eq "") {
    $OutputFile = Join-Path $RunDir "reports\WAVE_SUMMARY.txt"
}

Write-Host "=== Generating Wave Summary ===" -ForegroundColor Cyan
Write-Host "Run Directory: $RunDir"
Write-Host "Output File: $OutputFile"
Write-Host ""

# Ensure output directory exists
$outputDir = Split-Path -Parent $OutputFile
if (-not (Test-Path $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
}

# Find all metadata files in the run directory
$metadataFiles = Get-ChildItem -Path $RunDir -Recurse -Filter ".translation_metadata.json" -ErrorAction SilentlyContinue

if ($metadataFiles.Count -eq 0) {
    Write-Host "WARNING: No metadata files found in $RunDir" -ForegroundColor Yellow
    $summary = @"
===============================================================================
WAVE SUMMARY - NO METADATA FOUND
===============================================================================

Run Directory: $RunDir
Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')

ERROR: No .translation_metadata.json files found in run directory.

This could mean:
1. Translation has not completed yet
2. Metadata generation was disabled
3. The run directory path is incorrect

NOTE: Counts are derived from metadata, not from discovery scan.
===============================================================================
"@
    $summary | Out-File -FilePath $OutputFile -Encoding utf8
    Write-Host "Summary written to: $OutputFile" -ForegroundColor Yellow
    exit 1
}

Write-Host "Found $($metadataFiles.Count) metadata file(s)"
Write-Host ""

# Parse each metadata file and collect stats
$siteStats = @{}

foreach ($metadataFile in $metadataFiles) {
    Write-Host "Processing: $($metadataFile.FullName)"

    try {
        $metadata = Get-Content -Path $metadataFile.FullName -Raw -Encoding utf8 | ConvertFrom-Json

        # Extract site name from path (assuming structure: RunDir/outputs/{site}/{lang}/)
        $relativePath = $metadataFile.DirectoryName.Replace($RunDir, "").TrimStart('\', '/')
        $pathParts = $relativePath -split '[/\\]'

        # Find "outputs" in path and extract site name
        $siteNameIndex = [array]::IndexOf($pathParts, "outputs")
        if ($siteNameIndex -ge 0 -and $siteNameIndex + 1 -lt $pathParts.Length) {
            $siteName = $pathParts[$siteNameIndex + 1]
            $lang = if ($siteNameIndex + 2 -lt $pathParts.Length) { $pathParts[$siteNameIndex + 2] } else { "unknown" }
        } else {
            $siteName = "unknown"
            $lang = "unknown"
        }

        # Initialize site stats if not exists
        if (-not $siteStats.ContainsKey($siteName)) {
            $siteStats[$siteName] = @{
                languages = @{}
                totalSourceFiles = 0
                totalOutputs = 0
            }
        }

        # Initialize language stats if not exists
        if (-not $siteStats[$siteName].languages.ContainsKey($lang)) {
            $siteStats[$siteName].languages[$lang] = @{
                sourceFiles = 0
                successfulOutputs = 0
                failedOutputs = 0
            }
        }

        # Count files from metadata
        $files = $metadata.files
        $sourceCount = ($files | Measure-Object).Count

        # Count successful outputs per language
        $successCount = 0
        $failCount = 0

        foreach ($fileKey in $files.PSObject.Properties.Name) {
            $fileData = $files.$fileKey
            $outputs = $fileData.outputs

            if ($outputs) {
                foreach ($outputLang in $outputs.PSObject.Properties.Name) {
                    $outputData = $outputs.$outputLang
                    if ($outputData.status -eq "success") {
                        $successCount++
                    } else {
                        $failCount++
                    }
                }
            }
        }

        # Update stats
        $siteStats[$siteName].languages[$lang].sourceFiles = $sourceCount
        $siteStats[$siteName].languages[$lang].successfulOutputs = $successCount
        $siteStats[$siteName].languages[$lang].failedOutputs = $failCount
        $siteStats[$siteName].totalSourceFiles += $sourceCount
        $siteStats[$siteName].totalOutputs += $successCount

    } catch {
        Write-Host "  ERROR: Failed to parse metadata: $_" -ForegroundColor Red
    }
}

# Generate summary report
$summaryLines = @()
$summaryLines += "=" * 80
$summaryLines += "WAVE SUMMARY - METADATA-DERIVED COUNTS"
$summaryLines += "=" * 80
$summaryLines += ""
$summaryLines += "Run Directory: $RunDir"
$summaryLines += "Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
$summaryLines += "Metadata Files: $($metadataFiles.Count)"
$summaryLines += ""
$summaryLines += "NOTE: File counts are derived from .translation_metadata.json files."
$summaryLines += "      These are ACTUAL translation results, not discovery estimates."
$summaryLines += ""
$summaryLines += "=" * 80
$summaryLines += "PER-SITE RESULTS"
$summaryLines += "=" * 80

$grandTotalSourceFiles = 0
$grandTotalOutputs = 0
$grandTotalLanguages = New-Object System.Collections.Generic.HashSet[string]

foreach ($siteName in ($siteStats.Keys | Sort-Object)) {
    $site = $siteStats[$siteName]
    $summaryLines += ""
    $summaryLines += "Site: $siteName"
    $summaryLines += "  Total source files: $($site.totalSourceFiles)"
    $summaryLines += "  Total successful outputs: $($site.totalOutputs)"
    $summaryLines += "  Languages:"

    foreach ($lang in ($site.languages.Keys | Sort-Object)) {
        $langStats = $site.languages[$lang]
        $summaryLines += "    - ${lang}: $($langStats.successfulOutputs) successful, $($langStats.failedOutputs) failed (from $($langStats.sourceFiles) sources)"
        $grandTotalLanguages.Add($lang) | Out-Null
    }

    $grandTotalSourceFiles += $site.totalSourceFiles
    $grandTotalOutputs += $site.totalOutputs
}

$summaryLines += ""
$summaryLines += "=" * 80
$summaryLines += "OVERALL SUMMARY"
$summaryLines += "=" * 80
$summaryLines += "Total Sites: $($siteStats.Count)"
$summaryLines += "Total Languages: $($grandTotalLanguages.Count) ($($grandTotalLanguages -join ', '))"
$summaryLines += "Total Source Files Translated: $grandTotalSourceFiles"
$summaryLines += "Total Successful Outputs: $grandTotalOutputs"
$summaryLines += ""

# Check for gate reports
$gateReports = Get-ChildItem -Path $RunDir -Recurse -Filter "gates_*.md" -ErrorAction SilentlyContinue
if ($gateReports.Count -gt 0) {
    $summaryLines += "=" * 80
    $summaryLines += "GATE VERIFICATION"
    $summaryLines += "=" * 80
    $summaryLines += "Gate reports found: $($gateReports.Count)"

    # Count passes and failures
    $passCount = 0
    $failCount = 0

    foreach ($gateReport in $gateReports) {
        $content = Get-Content -Path $gateReport.FullName -Raw -Encoding utf8
        if ($content -match "ALL GATES PASSED") {
            $passCount++
        } elseif ($content -match "GATES FAILED") {
            $failCount++
        }
    }

    $summaryLines += "  Passed: $passCount"
    $summaryLines += "  Failed: $failCount"

    if ($failCount -gt 0) {
        $summaryLines += ""
        $summaryLines += "  WARNING: Some gate verifications failed!"
        $summaryLines += "  Check individual gate reports in scans/ directory."
    }
} else {
    $summaryLines += "=" * 80
    $summaryLines += "GATE VERIFICATION"
    $summaryLines += "=" * 80
    $summaryLines += "No gate reports found in run directory."
    $summaryLines += "Gates may not have been executed yet."
}

$summaryLines += ""
$summaryLines += "=" * 80

# Write summary to file
$summary = $summaryLines -join "`n"
$summary | Out-File -FilePath $OutputFile -Encoding utf8

Write-Host ""
Write-Host "=== Summary Generated ===" -ForegroundColor Green
Write-Host "Output: $OutputFile"
Write-Host ""
Write-Host "Summary Preview:"
Write-Host $summary
