$sites = @('about.aspose.net', 'blog.aspose.net', 'kb.aspose.net', 'products.aspose.net', 'www.aspose.net', 'websites.aspose.net', 'docs.aspose.net', 'reference.aspose.net')

$results = @()

foreach ($site in $sites) {
    $path = "D:\onedrive\Documents\GitHub\aspose.net\content\$site\en"
    if (Test-Path $path) {
        $count = (Get-ChildItem -Path $path -Filter *.md -Recurse -File | Measure-Object).Count
        $results += [PSCustomObject]@{
            Site = $site
            Count = $count
        }
    }
}

$results | Sort-Object Count | Format-Table -AutoSize
