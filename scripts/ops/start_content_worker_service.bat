@echo off
REM Service Wrapper for Autonomous Content Translation Worker
REM Designed for Windows Task Scheduler execution with logging
REM Created: 2026-01-21

set PROJECT_ROOT=%~dp0..
cd /d "%PROJECT_ROOT%"

REM Create logs directory if needed
if not exist "data\logs" mkdir "data\logs"

REM Log startup
echo [%date% %time%] Starting Content Translation Worker (Service Mode) >> data\logs\worker_startup.log
echo ================================================================================ >> data\logs\worker_startup.log
echo Timestamp: %date% %time% >> data\logs\worker_startup.log
echo Working Directory: %CD% >> data\logs\worker_startup.log
echo Virtual Environment: .venv\Scripts\python.exe >> data\logs\worker_startup.log
echo Mode: Daemon (4 runs/day, 08:00-23:00 PT) >> data\logs\worker_startup.log
echo Device: CUDA (50%% GPU memory limit) >> data\logs\worker_startup.log
echo ================================================================================ >> data\logs\worker_startup.log
echo. >> data\logs\worker_startup.log

REM Start worker with output redirection
call .venv\Scripts\activate.bat
python -m src.workers.autonomous_content_translation_worker ^
    --mode daemon ^
    --runs-per-day 4 ^
    --window-start 08:00 ^
    --window-end 23:00 ^
    --timezone America/Los_Angeles ^
    --jitter-minutes 15 ^
    --device cuda ^
    --max-gpu-memory-percent 50 ^
    --log-level INFO >> data\logs\content_worker_console.log 2>&1

REM Capture exit code
set EXITCODE=%ERRORLEVEL%

REM Log exit
echo. >> data\logs\worker_startup.log
echo ================================================================================ >> data\logs\worker_startup.log
echo [%date% %time%] Content Translation Worker exited with code %EXITCODE% >> data\logs\worker_startup.log
echo ================================================================================ >> data\logs\worker_startup.log
echo. >> data\logs\worker_startup.log

REM Exit with same code
exit /b %EXITCODE%
