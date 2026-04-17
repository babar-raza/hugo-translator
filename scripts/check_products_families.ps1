$basePath = "D:\onedrive\Documents\GitHub\aspose.net\content\products.aspose.net"
$families = @('home', 'barcode', 'cad', 'cells', 'email')
$testLangs = @('en', 'fr', 'de', 'es', 'zh')

Write-Host "Products Site - Family Translation Status" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

foreach ($family in $families) {
    $familyPath = Join-Path $basePath $family
    if (-not (Test-Path $familyPath)) {
        Write-Host "$family : NOT FOUND" -ForegroundColor Red
        continue
    }

    Write-Host "$family :" -ForegroundColor Yellow

    $enPath = Join-Path $familyPath "en"
    if (-not (Test-Path $enPath)) {
        Write-Host "  No English folder!" -ForegroundColor Red
        continue
    }

    $sourceCount = (Get-ChildItem -Path $enPath -Filter *.md -Recurse -File | Measure-Object).Count
    Write-Host "  Source (en): $sourceCount files" -ForegroundColor Green

    foreach ($lang in $testLangs) {
        if ($lang -eq 'en') { continue }

        $langPath = Join-Path $familyPath $lang
        if (Test-Path $langPath) {
            $count = (Get-ChildItem -Path $langPath -Filter *.md -Recurse -File | Measure-Object).Count
            $missing = $sourceCount - $count
            $pct = [math]::Round(($count / $sourceCount) * 100, 1)

            $status = if ($missing -eq 0) { "[OK]" } else { "[MISSING]" }
            Write-Host "    $lang`: $count/$sourceCount ($pct`%) missing: $missing $status" -ForegroundColor White
        } else {
            Write-Host "    $lang`: 0/$sourceCount (0.0`%) missing: $sourceCount [MISSING]" -ForegroundColor Yellow
        }
    }
    Write-Host ""
}
