$basePath = "D:\onedrive\Documents\GitHub\aspose.net\content\websites.aspose.net"
$langs = @('ar', 'bg', 'ca', 'cs', 'da', 'de', 'el', 'es', 'fa', 'fi', 'fr', 'he', 'hi', 'hr', 'hu', 'id', 'it', 'ja', 'ko', 'lt', 'lv', 'ms', 'nl', 'no', 'pl', 'pt', 'ro', 'ru', 'sk', 'sr', 'sv', 'th', 'tr', 'uk', 'vi', 'zh')

Write-Host "Pilot Site: websites.aspose.net" -ForegroundColor Cyan
Write-Host "Source files (en): 14" -ForegroundColor Green
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
    $missing = 14 - $count
    $totalMissing += $missing

    $status = if ($count -eq 14) { "COMPLETE" } elseif ($count -eq 0) { "MISSING" } else { "PARTIAL" }

    $results += [PSCustomObject]@{
        Language = $lang
        Existing = $count
        Missing = $missing
        Status = $status
    }
}

$results | Format-Table -AutoSize

Write-Host "`nSummary:" -ForegroundColor Cyan
Write-Host "  Total possible translations: $($langs.Count * 14) = $($langs.Count * 14)" -ForegroundColor White
Write-Host "  Total existing: $($results | Measure-Object -Property Existing -Sum | Select-Object -ExpandProperty Sum)" -ForegroundColor Green
Write-Host "  Total missing: $totalMissing" -ForegroundColor Yellow
Write-Host "  Languages with missing translations: $(($results | Where-Object { $_.Missing -gt 0 }).Count)" -ForegroundColor Yellow
