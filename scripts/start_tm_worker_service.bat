@echo off
REM Service Wrapper for TM Improvement Worker
REM Designed for Windows Task Scheduler execution with logging
REM Created: 2026-01-21

set PROJECT_ROOT=%~dp0..
cd /d "%PROJECT_ROOT%"

REM Create logs directory if needed
if not exist "data\logs" mkdir "data\logs"

REM Log startup
echo [%date% %time%] Starting TM Improvement Worker (Service Mode) >> data\logs\worker_startup.log
echo ================================================================================ >> data\logs\worker_startup.log
echo Timestamp: %date% %time% >> data\logs\worker_startup.log
echo Working Directory: %CD% >> data\logs\worker_startup.log
echo Virtual Environment: .venv\Scripts\python.exe >> data\logs\worker_startup.log
echo Mode: Daemon (4 runs/day, 08:00-23:00 PT) >> data\logs\worker_startup.log
echo Device: CUDA (50%% GPU memory limit) >> data\logs\worker_startup.log
echo LLM Provider: from config (global.yaml tm_improvement.llm) >> data\logs\worker_startup.log
echo Batch Size: 50 candidates/run, 200 max LLM calls, 900s timeout >> data\logs\worker_startup.log
echo ================================================================================ >> data\logs\worker_startup.log
echo. >> data\logs\worker_startup.log

REM Start worker with output redirection
call .venv\Scripts\activate.bat
python -m src.workers.tm_improvement_worker ^
    --mode daemon ^
    --runs-per-day 4 ^
    --window-start 10:00 ^
    --window-end 20:00 ^
    --timezone Asia/Karachi ^
    --jitter-minutes 15 ^
    --device cuda ^
    --max-gpu-memory-percent 50 ^
    --candidates-per-run 500 ^
    --max-llm-calls-per-run 1000 ^
    --max-seconds-per-run 3600 ^
    --log-level INFO >> data\logs\tm_worker_console.log 2>&1

REM Capture exit code
set EXITCODE=%ERRORLEVEL%

REM Log exit
echo. >> data\logs\worker_startup.log
echo ================================================================================ >> data\logs\worker_startup.log
echo [%date% %time%] TM Improvement Worker exited with code %EXITCODE% >> data\logs\worker_startup.log
echo ================================================================================ >> data\logs\worker_startup.log
echo. >> data\logs\worker_startup.log

REM Exit with same code
exit /b %EXITCODE%
