# Run elevated (Administrator) once to register the robust startup task.
# Right-click PowerShell -> "Run as Administrator", then:
#   powershell -ExecutionPolicy Bypass -File "...\register_startup_task.ps1"
#
# Robustness guarantees:
#   1. Starts orchestrator at logon
#   2. Repeats every 5 minutes — if orchestrator dies mid-session it is restarted within 5 min
#   3. MultipleInstances = IgnoreNew — silently skips if orchestrator is already running
#   4. --log-file writes directly to data/logs/orchestrator_daemon.log (append, no OS redirect)

$repoRoot   = 'C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator-gitlab'
$python     = "$repoRoot\.venv\Scripts\python.exe"
$logFile    = 'data\logs\orchestrator_daemon.log'
$workerArgs = "-m src.workers.worker_orchestrator --check-interval 900 --log-level INFO --log-file $logFile"

$action = New-ScheduledTaskAction `
    -Execute $python `
    -Argument $workerArgs `
    -WorkingDirectory $repoRoot

# Trigger 1: at logon
$triggerLogon = New-ScheduledTaskTrigger -AtLogOn

# Trigger 2: repeating every 5 minutes indefinitely (auto-restart watchdog)
$triggerRepeat = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes 5) -Once -At (Get-Date)

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName 'HugoTranslatorGitlab-Orchestrator' `
    -Action $action `
    -Trigger @($triggerLogon, $triggerRepeat) `
    -Settings $settings `
    -Description 'Hugo Translator GitLab orchestrator. Repeats every 5 min to auto-restart on crash.' `
    -RunLevel Highest `
    -Force

Write-Host 'SUCCESS: HugoTranslatorGitlab-Orchestrator registered.'
Write-Host '  - Starts at logon'
Write-Host '  - Repeats every 5 min (auto-restart if dead)'
Write-Host '  - Logs to data\logs\orchestrator_daemon.log'
