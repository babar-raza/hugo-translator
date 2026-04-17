$sites = @('kb.aspose.net', 'products.aspose.net', 'www.aspose.net', 'blog.aspose.net', 'docs.aspose.net')
$langs = @('ar', 'bg', 'ca', 'cs', 'da', 'de', 'el', 'es', 'fa', 'fi', 'fr', 'he', 'hi', 'hr', 'hu', 'id', 'it', 'ja', 'ko', 'lt', 'lv', 'ms', 'nl', 'no', 'pl', 'pt', 'ro', 'ru', 'sk', 'sr', 'sv', 'th', 'tr', 'uk', 'vi', 'zh')

foreach ($site in $sites) {
    $basePath = "D:\onedrive\Documents\GitHub\aspose.net\content\$site"
    $enPath = Join-Path $basePath "en"

    Write-Host "`n========================================" -ForegroundColor Cyan
    Write-Host "Site: $site" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan

    if (-not (Test-Path $enPath)) {
        Write-Host "  English folder not found!" -ForegroundColor Red
        continue
    }

    $sourceCount = (Get-ChildItem -Path $enPath -Filter *.md -Recurse -File | Measure-Object).Count
    Write-Host "  Source files (en): $sourceCount" -ForegroundColor Green

    if ($sourceCount -eq 0) {
        Write-Host "  No source files found!" -ForegroundColor Yellow
        continue
    }

    # Sample first 5 languages to estimate
    $sampleLangs = $langs | Select-Object -First 5
    $sampleResults = @()

    foreach ($lang in $sampleLangs) {
        $langPath = Join-Path $basePath $lang
        if (Test-Path $langPath) {
            $count = (Get-ChildItem -Path $langPath -Filter *.md -Recurse -File | Measure-Object).Count
        } else {
            $count = 0
        }
        $sampleResults += $count
    }

    $avgExisting = ($sampleResults | Measure-Object -Average).Average
    $estimatedTotal = $avgExisting * $langs.Count
    $estimatedMissing = ($sourceCount * $langs.Count) - $estimatedTotal

    Write-Host "  Sample of first 5 languages: $(($sampleResults -join ', '))" -ForegroundColor White
    Write-Host "  Estimated total existing: $([int]$estimatedTotal)" -ForegroundColor Green
    Write-Host "  Estimated total missing: $([int]$estimatedMissing)" -ForegroundColor Yellow

    if ($estimatedMissing -gt 0) {
        Write-Host "  >>> CANDIDATE FOR TRANSLATION <<<" -ForegroundColor Magenta
    }
}

Write-Host "`n========================================" -ForegroundColor Cyan
