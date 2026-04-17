Get-ScheduledTask | Where-Object { $_.TaskName -like '*ContentWorker*' -or $_.TaskName -like '*TMWorker*' -or $_.TaskName -like '*Watchdog*' -or $_.TaskName -like '*Verification*' } | ForEach-Object {
    Disable-ScheduledTask -TaskName $_.TaskName -ErrorAction SilentlyContinue
    Write-Host "Disabled: $($_.TaskName) (was $($_.State))"
}
