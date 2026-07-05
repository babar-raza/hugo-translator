Get-WmiObject Win32_Process -Filter "Name='python.exe'" | ForEach-Object {
    $cmd = $_.CommandLine
    if ($cmd) {
        $cmd = if ($cmd.Length -gt 150) { $cmd.Substring($cmd.Length - 150) } else { $cmd }
    }
    "$($_.ProcessId): $cmd"
}
