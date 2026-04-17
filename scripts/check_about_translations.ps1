$basePath = "D:\onedrive\Documents\GitHub\aspose.net\content\about.aspose.net"
$sourceCount = (Get-ChildItem -Path (Join-Path $basePath "en") -Filter *.md -Recurse -File | Measure-Object).Count
$langs = @('ar', 'bg', 'ca', 'cs', 'da', 'de', 'el', 'es', 'fa', 'fi', 'fr', 'he', 'hi', 'hr', 'hu', 'id', 'it', 'ja', 'ko', 'lt', 'lv', 'ms', 'nl', 'no', 'pl', 'pt', 'ro', 'ru', 'sk', 'sr', 'sv', 'th', 'tr', 'uk', 'vi', 'zh')

Write-Host "Site: about.aspose.net" -ForegroundColor Cyan
Write-Host "Source files (en): $sourceCount" -ForegroundColor Green
Write-Host "`nExisting translations:" -ForegroundColor Cyan

$results = @()
$totalMissing = 0

foreach ($lang in $langs) {
    $langPath = Join-Path $basePath $lang
    if (Test-Path $langPath) {
        $count = (Get-ChildItem -Path $langPath -Filter *.md -Recurse -File | Measure-Object).Count
    } else {
        $count = 0
    }
    $missing = $sourceCount - $count
    $totalMissing += $missing

    $status = if ($count -eq $sourceCount) { "COMPLETE" } elseif ($count -eq 0) { "MISSING" } else { "PARTIAL" }

    $results += [PSCustomObject]@{
        Language = $lang
        Existing = $count
        Missing = $missing
        Status = $status
    }
}

$results | Format-Table -AutoSize

Write-Host "`nSummary:" -ForegroundColor Cyan
Write-Host "  Total possible translations: $($langs.Count * $sourceCount) = $($langs.Count * $sourceCount)" -ForegroundColor White
Write-Host "  Total existing: $($results | Measure-Object -Property Existing -Sum | Select-Object -ExpandProperty Sum)" -ForegroundColor Green
Write-Host "  Total missing: $totalMissing" -ForegroundColor Yellow
Write-Host "  Languages with missing translations: $(($results | Where-Object { $_.Missing -gt 0 }).Count)" -ForegroundColor Yellow
