@echo off
REM Stop All Running Workers

echo ================================================================================
echo Stopping Autonomous Workers
echo ================================================================================
echo.

REM Kill all Python processes running worker modules
echo Searching for running worker processes...

for /f "tokens=2" %%a in ('tasklist /FI "IMAGENAME eq python.exe" /FI "WINDOWTITLE eq *Worker*" /NH 2^>nul') do (
    echo Stopping process %%a...
    taskkill /PID %%a /F >nul 2>&1
)

echo.
echo If workers were started via Task Scheduler, stopping scheduled tasks...
echo.

REM Check if PowerShell is available and stop scheduled tasks
where powershell >nul 2>&1
if %errorLevel% equ 0 (
    powershell -Command "Get-ScheduledTask -TaskName 'HugoTranslator-*' 2>$null | Stop-ScheduledTask" >nul 2>&1
    if %errorLevel% equ 0 (
        echo [OK] Scheduled tasks stopped
    ) else (
        echo [INFO] No scheduled tasks found or already stopped
    )
) else (
    echo [INFO] PowerShell not available, skipping scheduled task check
)

echo.
echo ================================================================================
echo Workers have been stopped
echo ================================================================================
echo.
echo To restart workers:
echo   - Manual mode: Double-click START_WORKERS.bat
echo   - Scheduled mode: Start-ScheduledTask in PowerShell
echo.
pause
