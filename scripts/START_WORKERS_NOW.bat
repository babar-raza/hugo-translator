@echo off
REM Manually Start Workers - Hugo Translator
REM Starts both autonomous workers immediately via Task Scheduler
REM Created: 2026-01-21

echo.
echo ================================================================================
echo Hugo Translator - Start Workers Now
echo ================================================================================
echo.

REM Check if tasks exist first
powershell -Command "Get-ScheduledTask -TaskName 'HugoTranslator-*' -ErrorAction SilentlyContinue" >nul 2>&1

if %errorLevel% neq 0 (
    echo [ERROR] No Hugo Translator tasks found!
    echo.
    echo You need to run SETUP_AUTOSTART.bat first to configure the tasks.
    echo Right-click SETUP_AUTOSTART.bat and select "Run as Administrator"
    echo.
    pause
    exit /b 1
)

echo [1/2] Starting Content Translation Worker...
powershell -Command "Start-ScheduledTask -TaskName 'HugoTranslator-ContentWorker'"

if %errorLevel% equ 0 (
    echo   [OK] Content Translation Worker started
) else (
    echo   [ERROR] Failed to start Content Translation Worker
)

echo.
echo [2/2] Starting TM Improvement Worker...
powershell -Command "Start-ScheduledTask -TaskName 'HugoTranslator-TMWorker'"

if %errorLevel% equ 0 (
    echo   [OK] TM Improvement Worker started
) else (
    echo   [ERROR] Failed to start TM Improvement Worker
)

echo.
echo ================================================================================
echo Workers Started!
echo ================================================================================
echo.
echo Both workers are now running in daemon mode.
echo They will self-schedule 4 runs per day between 08:00-23:00 Pacific Time.
echo.
echo Quick Commands:
echo   Check status:  CHECK_STATUS.bat
echo   View logs:     powershell -File scripts\view_logs.ps1 -LogType all
echo   Stop workers:  STOP_WORKERS.bat
echo.
echo TIP: Workers run in the background. You won't see any windows.
echo      Check data\logs\worker_startup.log to see when they started.
echo.
pause
