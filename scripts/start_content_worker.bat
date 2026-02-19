@echo off
REM Autonomous Content Translation Worker - Startup Script
REM This script starts the content translation worker in daemon mode
REM Designed for Windows Task Scheduler execution

echo ================================================================================
echo Starting Autonomous Content Translation Worker
echo ================================================================================
echo Timestamp: %date% %time%
echo Working Directory: %~dp0..
echo.

REM Change to project root directory
cd /d "%~dp0.."

REM Activate virtual environment
call .venv\Scripts\activate.bat

REM Start worker in daemon mode with CUDA support
echo Starting worker in daemon mode...
echo - Runs per day: 12
echo - Time window: 07:00-23:00 Pakistan Standard Time
echo - Device: CUDA (GPU acceleration)
echo - Max GPU memory: 50%%
echo - Timeout: 600 seconds (10 minutes)
echo.

python -m src.workers.autonomous_content_translation_worker ^
    --mode daemon ^
    --runs-per-day 12 ^
    --window-start 07:00 ^
    --window-end 23:00 ^
    --timezone Asia/Karachi ^
    --jitter-minutes 15 ^
    --device cuda ^
    --max-gpu-memory-percent 50 ^
    --file-timeout-seconds 600 ^
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
