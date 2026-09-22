$ErrorActionPreference = 'Stop'
$control = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$runtime = Join-Path $control '.local\portfolio-runtime-64'
$pythonw = 'C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\.venv\Scripts\pythonw.exe'
$manifest = Join-Path $control 'data\campaigns\manifests\portfolio-professionalize-unattended-20260921.yaml'
$ledger = Join-Path $control 'data\campaigns'
$spool = Join-Path $control 'data\tm\campaign-spools\portfolio-professionalize-unattended-20260921.sqlite3'
$args = @('-u','-m','scripts.campaign.unattended_controller','--manifest',$manifest,'--runtime',$runtime,'--control',$control,'--ledger-root',$ledger,'--spool',$spool)
Start-Process -FilePath $pythonw -ArgumentList $args -WorkingDirectory $runtime -WindowStyle Hidden | Out-Null
