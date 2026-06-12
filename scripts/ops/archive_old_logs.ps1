<#
.SYNOPSIS
    TC-SYS-02: Archive and compress log files older than RetentionDays days.

.DESCRIPTION
    Moves data/logs/*.log files older than RetentionDays to data/logs/_archive/YYYY-MM/,
    compresses each with Compress-Archive, then deletes compressed archives older than
    ArchiveRetentionDays days.

    SAFE BY DEFAULT: runs in dry-run mode unless -Apply is passed.

.PARAMETER RetentionDays
    Move files older than this many days (default: 30).

.PARAMETER ArchiveRetentionDays
    Delete compressed archives older than this many days (default: 90).

.PARAMETER Apply
    Actually move and compress files. Without this flag, only a dry-run report is shown.

.EXAMPLE
    # Dry-run (default): show what would be moved
    .\scripts\archive_old_logs.ps1 -RetentionDays 30

    # Apply: move and compress old log files
    .\scripts\archive_old_logs.ps1 -RetentionDays 30 -Apply
#>
[CmdletBinding()]
param(
    [int]$RetentionDays        = 30,
    [int]$ArchiveRetentionDays = 90,
    [switch]$Apply
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$LogDir      = Join-Path $ProjectRoot 'data\logs'
$ArchiveBase = Join-Path $LogDir '_archive'

$now           = Get-Date
$cutoff        = $now.AddDays(-$RetentionDays)
$archiveCutoff = $now.AddDays(-$ArchiveRetentionDays)

if (-not (Test-Path $LogDir)) {
    Write-Host "[INFO] Log directory does not exist: $LogDir"
    return
}

$mode = if ($Apply) { 'APPLY' } else { 'DRY-RUN' }
Write-Host "[$mode] archive_old_logs.ps1 -- retention=${RetentionDays}d, archive_retention=${ArchiveRetentionDays}d"
Write-Host "[$mode] Scanning: $LogDir"
Write-Host ''

# -----------------------------------------------------------------------
# Phase 1: Archive old *.log files
# -----------------------------------------------------------------------
$oldLogs = Get-ChildItem -Path $LogDir -Filter '*.log' -File |
           Where-Object { $_.LastWriteTime -lt $cutoff }

$totalMoved     = 0
$totalMovedSize = 0

foreach ($log in $oldLogs) {
    $monthFolder = $log.LastWriteTime.ToString('yyyy-MM')
    $destDir     = Join-Path $ArchiveBase $monthFolder
    $destLog     = Join-Path $destDir $log.Name
    $destZip     = $destLog + '.zip'
    $ageDays     = [int](($now - $log.LastWriteTime).TotalDays)
    $sizeKb      = [int]($log.Length / 1024)

    Write-Host "[$mode] Would archive: $($log.FullName) -> $destZip (age=${ageDays}d, size=${sizeKb}KB)"

    if ($Apply) {
        if (-not (Test-Path $destDir)) {
            New-Item -ItemType Directory -Path $destDir -Force | Out-Null
        }
        # Move to archive dir first
        Move-Item -Path $log.FullName -Destination $destLog -Force
        # Compress
        Compress-Archive -Path $destLog -DestinationPath $destZip -Force
        # Remove uncompressed copy from archive
        Remove-Item -Path $destLog -Force
        Write-Host '[APPLY]   Archived: ' + $destZip
    }

    $totalMoved++
    $totalMovedSize += $log.Length
}

$movedMb = [int]($totalMovedSize / (1024 * 1024))
Write-Host ''
Write-Host "[$mode] Files to archive: $totalMoved (${movedMb} MB)"

# -----------------------------------------------------------------------
# Phase 2: Delete old compressed archives
# -----------------------------------------------------------------------
$oldArchives = @()
if (Test-Path $ArchiveBase) {
    $oldArchives = Get-ChildItem -Path $ArchiveBase -Filter '*.zip' -File -Recurse |
                   Where-Object { $_.LastWriteTime -lt $archiveCutoff }
}

$totalDeleted     = 0
$totalDeletedSize = 0

foreach ($zip in $oldArchives) {
    $ageDays = [int](($now - $zip.LastWriteTime).TotalDays)
    Write-Host "[$mode] Would delete archive: $($zip.FullName) (age=${ageDays}d)"

    if ($Apply) {
        Remove-Item -Path $zip.FullName -Force
        Write-Host '[APPLY]   Deleted: ' + $zip.FullName
    }

    $totalDeleted++
    $totalDeletedSize += $zip.Length
}

$deletedMb = [int]($totalDeletedSize / (1024 * 1024))
Write-Host ''
Write-Host "[$mode] Archives to delete: $totalDeleted (${deletedMb} MB freed)"
Write-Host ''

if ($Apply) {
    $totalMb = [int](($totalMovedSize + $totalDeletedSize) / (1024 * 1024))
    Write-Host "[APPLY] Done. Total freed: ${totalMb} MB"
} else {
    Write-Host '[DRY-RUN] No changes made. Re-run with -Apply to execute.'
}
