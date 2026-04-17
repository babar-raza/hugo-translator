# E2E Path Discovery Script
# Discovers content repo roots for slides family across all subdomains

$contentRoot = "D:\onedrive\Documents\GitHub\aspose.net\content"
$outputFile = "c:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\reports\E2E_BULK_discovery_paths.txt"

Write-Output "CONTENT REPO PATH DISCOVERY" > $outputFile
Write-Output "===========================" >> $outputFile
Write-Output "" >> $outputFile
Write-Output "Content Root: $contentRoot" >> $outputFile
Write-Output "" >> $outputFile

# Define possible paths for each subdomain
$pathsToCheck = @(
    @{Name="docs (site)"; Path="$contentRoot\docs.aspose.net\slides\en"},
    @{Name="docs (root)"; Path="$contentRoot\docs\slides\en"},
    @{Name="kb (site)"; Path="$contentRoot\kb.aspose.net\slides\en"},
    @{Name="kb (root)"; Path="$contentRoot\kb\slides\en"},
    @{Name="reference (site)"; Path="$contentRoot\reference.aspose.net\slides\en"},
    @{Name="reference (root)"; Path="$contentRoot\reference\slides\en"},
    @{Name="blog (site)"; Path="$contentRoot\blog.aspose.net\slides"},
    @{Name="blog (root)"; Path="$contentRoot\blog\slides"}
)

Write-Output "SLIDES FAMILY PATHS:" >> $outputFile
Write-Output "-------------------" >> $outputFile

$discoveredPaths = @{}

foreach ($item in $pathsToCheck) {
    if (Test-Path $item.Path) {
        Write-Output "[FOUND] $($item.Name): $($item.Path)" >> $outputFile

        # Count markdown files
        $mdFiles = Get-ChildItem -Path $item.Path -Filter "*.md" -Recurse -File | Where-Object { $_.Name -match "\.en\.md$" }
        $count = $mdFiles.Count
        Write-Output "        Markdown files: $count" >> $outputFile

        # Extract subdomain key
        $subdomain = $item.Name.Split(" ")[0]
        if (-not $discoveredPaths.ContainsKey($subdomain)) {
            $discoveredPaths[$subdomain] = $item.Path
        }
    } else {
        Write-Output "[NOT FOUND] $($item.Name): $($item.Path)" >> $outputFile
    }
}

Write-Output "" >> $outputFile
Write-Output "SELECTED PATHS (one per subdomain):" >> $outputFile
Write-Output "-----------------------------------" >> $outputFile

foreach ($key in $discoveredPaths.Keys | Sort-Object) {
    Write-Output "$key=$($discoveredPaths[$key])" >> $outputFile
}

Write-Output "" >> $outputFile
Write-Output "Discovery complete. Paths saved to: $outputFile" | Tee-Object -Append $outputFile
