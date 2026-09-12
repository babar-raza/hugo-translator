# Run once to register the branch-sync scheduled task.
#   powershell -ExecutionPolicy Bypass -File "...\register_branch_sync_task.ps1"
#
# Keeps whatever branch is currently checked out in hugo-translator pushed to
# GitHub and (best-effort) GitLab every 5 minutes, independent of any specific
# mission - see scripts/ops/branch_sync.ps1. Does not require admin rights.

$repoRoot = 'C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator'
$script   = Join-Path $repoRoot 'scripts\ops\branch_sync.ps1'

$action = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`"" `
    -WorkingDirectory $repoRoot

$trigger = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes 5) -Once -At (Get-Date)

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 4) `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName 'HugoTranslatorBranchSync' `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description 'Pushes whatever branch is checked out in hugo-translator to GitHub and GitLab every 5 min.' `
    -RunLevel Limited `
    -Force

Write-Host 'SUCCESS: HugoTranslatorBranchSync registered.'
Write-Host '  - Repeats every 5 min'
Write-Host '  - Logs to logs\branch_sync.log'
