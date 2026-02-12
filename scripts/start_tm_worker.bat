@echo off
REM TM Improvement Worker - Startup Script
REM This script starts the TM improvement worker in daemon mode
REM Designed for Windows Task Scheduler execution

echo ================================================================================
echo Starting TM Improvement Worker
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
echo - Time window: 08:00-23:00 Pacific Time
echo - Device: CUDA (GPU acceleration)
echo - Max GPU memory: 50%%
echo - LLM: Ollama/qwen3:14b
echo.

python -m src.workers.tm_improvement_worker ^
    --mode daemon ^
    --runs-per-day 4 ^
    --window-start 08:00 ^
    --window-end 23:00 ^
    --timezone America/Los_Angeles ^
    --jitter-minutes 15 ^
    --device cuda ^
    --max-gpu-memory-percent 50 ^
    --llm-provider ollama ^
    --llm-model qwen3:14b ^
    --candidates-per-run 50 ^
    --max-llm-calls-per-run 200 ^
    --max-seconds-per-run 900 ^
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
