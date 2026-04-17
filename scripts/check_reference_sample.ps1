$basePath = "D:\onedrive\Documents\GitHub\aspose.net\content\reference.aspose.net"
$families = @('cells', 'words', 'pdf', 'slides', 'email')
$testLangs = @('en', 'fr', 'de', 'es', 'zh')

Write-Host "`nReference sample check — $basePath`n" -ForegroundColor Cyan
Write-Host ("{0,-12} {1}" -f "Family", ($testLangs -join "   "))
Write-Host ("-" * 60)

foreach ($family in $families) {
    $counts = foreach ($lang in $testLangs) {
        $dir = Join-Path $basePath "$family\$lang"
        if (Test-Path $dir) {
            $n = (Get-ChildItem -Recurse -Filter "*.md" $dir -ErrorAction SilentlyContinue).Count
            "{0,5}" -f $n
        } else {
            "  N/A"
        }
    }
    Write-Host ("{0,-12} {1}" -f $family, ($counts -join "   "))
}

Write-Host ""
