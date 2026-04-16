@echo off
REM Autonomous Verification Worker - Startup Script
REM This script starts the verification worker in daemon mode
REM Designed for Windows Task Scheduler execution

echo ================================================================================
echo Starting Autonomous Verification Worker
echo ================================================================================
echo Timestamp: %date% %time%
echo Working Directory: %~dp0..
echo.

REM Change to project root directory
cd /d "%~dp0.."

REM Activate virtual environment
call .venv\Scripts\activate.bat

REM Start worker in daemon mode
echo Starting worker in daemon mode...
echo - Runs per day: 4
echo - Time window: 08:00-23:00 Pakistan Standard Time
echo - Jitter: +/- 15 minutes
echo.

python -m src.workers.autonomous_verification_worker ^
    --mode daemon ^
    --runs-per-day 4 ^
    --window-start 08:00 ^
    --window-end 23:00 ^
    --timezone Asia/Karachi ^
    --jitter-minutes 15 ^
    --log-level INFO

REM Capture exit code
set EXITCODE=%ERRORLEVEL%

echo.
echo ================================================================================
echo Worker exited with code: %EXITCODE%
echo Timestamp: %date% %time%
echo ================================================================================

REM Exit with same code
exit /b %EXITCODE%
