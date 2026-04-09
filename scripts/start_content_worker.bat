@echo off
REM Autonomous Content Translation Worker - Startup Script
REM This script starts the content translation worker in daemon mode
REM Designed for Windows Task Scheduler execution

REM SW-5: CAMPAIGN MODE — daemon spawning intentionally disabled as of 2026-03-27.
REM Workers are currently managed manually via oneshot mode with parallel dispatch.
REM Task Scheduler will show "Succeeded" (exit 0) for all invocations while this
REM block is active — this is expected and not an error.
REM
REM TO RESTORE DAEMON SCHEDULING: Remove the four lines below (echo + exit /b 0).
REM Verify workers are not already running manually before re-enabling.
echo [CAMPAIGN MODE] Daemon spawning disabled (2026-03-27) - workers managed manually
echo.> "%~dp0..\data\logs\content_worker.campaign_disabled"
exit /b 0

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
echo - Runs per day: 4
echo - Time window: 10:00-20:00 Pakistan Standard Time
echo - Device: CUDA (GPU acceleration)
echo - Max GPU memory: 50%%
echo - File timeout: 600 seconds per file x languages
echo - Max run time: from config (global.yaml per_site_limits)
echo.

python -m src.workers.autonomous_content_translation_worker ^
    --mode daemon ^
    --runs-per-day 4 ^
    --window-start 10:00 ^
    --window-end 20:00 ^
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
