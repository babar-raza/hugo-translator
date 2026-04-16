@echo off
REM Setup Auto-Start for Workers
REM Run this as Administrator to configure automatic startup

echo ================================================================================
echo Autonomous Workers - Auto-Start Setup
echo ================================================================================
echo.

REM Check for admin privileges
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [ERROR] This script requires Administrator privileges!
    echo.
    echo Right-click this file and select "Run as Administrator"
    echo.
    pause
    exit /b 1
)

echo [OK] Running with Administrator privileges
echo.

REM Get project directory
set PROJECT_DIR=%~dp0
cd /d "%PROJECT_DIR%"

echo Setting up Windows Task Scheduler...
echo.

powershell -ExecutionPolicy Bypass -File "%PROJECT_DIR%scripts\setup_task_scheduler.ps1"

if %errorLevel% equ 0 (
    echo.
    echo ================================================================================
    echo [SUCCESS] Auto-start configured successfully!
    echo ================================================================================
    echo.
    echo Workers will automatically start when Windows boots.
    echo.
    echo To start workers now without rebooting:
    echo   1. Open PowerShell as Administrator
    echo   2. Run: Start-ScheduledTask -TaskName "HugoTranslator-ContentWorker"
    echo   3. Run: Start-ScheduledTask -TaskName "HugoTranslator-TMWorker"
    echo.
    echo Or simply double-click START_WORKERS.bat to run them manually.
    echo.
) else (
    echo.
    echo [ERROR] Setup failed. Check error messages above.
    echo.
)

pause
