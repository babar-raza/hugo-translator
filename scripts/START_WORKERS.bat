@echo off
REM Quick Start Script for Both Autonomous Workers
REM Double-click this file to start both workers in separate windows

echo Starting Autonomous Workers...
echo.

REM Get project directory
set PROJECT_DIR=%~dp0
cd /d "%PROJECT_DIR%"

echo Starting Content Translation Worker...
start "Content Translation Worker" /MIN cmd /c scripts\start_content_worker.bat

echo Starting TM Improvement Worker...
start "TM Improvement Worker" /MIN cmd /c scripts\start_tm_worker.bat

echo.
echo ================================================================================
echo Both workers have been started in minimized windows
echo ================================================================================
echo.
echo To view worker windows: Check taskbar for minimized windows
echo To stop workers: Close the worker windows or press Ctrl+C in each
echo.
echo Workers will run 4 times per day:
echo   - Time window: 08:00 - 23:00 Pacific Time
echo   - Device: CUDA (GPU acceleration)
echo   - Schedule: ~08:00, ~13:00, ~18:00, ~23:00 (with +/-15min jitter)
echo.
echo For automatic startup on boot, see SETUP_AUTOSTART.bat
echo.
pause
